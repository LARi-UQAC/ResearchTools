import json
import sys
import unittest
from pathlib import Path

# Put the parent folder of the test folder on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ugs_grade import (
    normalize_rubric,
    grade_item,
    grade_report,
)
from ugs_text import StepContext
import ugs_bridge
from ugs_bridge import NotRun
from rubric_check import RubricError


class FakeCall:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, prompt, schema, images=None):
        self.calls.append(prompt)
        if not self.responses:
            raise NotRun("unreachable", "No more responses")
        resp = self.responses.pop(0)
        if isinstance(resp, Exception):
            raise resp
        return resp


def make_ctx():
    return StepContext(
        prompts={
            "grade_item": "Grade {{ITEM}} on {{SECTIONS}}. Levels: {{LEVELS}}. Lang: {{LANGUAGE_OF_REPORT}}. Note: {{CALIBRATION_NOTE}}",
            "rubric_normalize": "Normalize {{RUBRIC_TEXT}} for {{ASSESSMENT_TYPE}}",
            "retry_grade_item": (
                "## fr_score\nScore {{SCORE}} au-dessus de {{MAX}}.\n\n"
                "## en_score\nScore {{SCORE}} above {{MAX}}.\n\n"
                "## fr_not_applicable\nNon facultatif : {{MAX}}.\n\n"
                "## en_not_applicable\nNot optional: {{MAX}}.\n"
            ),
        },
        schemas={
            "grade_item": {"type": "object"},
            "rubric": {"type": "object"},
        },
        levels={"absent": 0, "attempted": 0.5, "partial": 0.75, "complete": 0.88, "exemplary": 1.0},
        window_tokens=1000,
        reserve_tokens=100,
        count=lambda text: len(text.split()),  # Simple word count as token proxy
        grade_retries=1,
        audit_retries=1,
        min_word_len=3,
    )


class TestNormalizeRubric(unittest.TestCase):
    def test_normalize_rubric_returns_a_valid_rubric(self):
        ctx = make_ctx()
        valid_rubric = {
            "assessment_type": "lab_report",
            "total_points": 100,
            "items": [{"id": "I01", "title": "Intro", "max_points": 100}]
        }
        call = FakeCall([valid_rubric])
        result = normalize_rubric("text", "lab_report", call, ctx)
        self.assertEqual(result["total_points"], 100)

    def test_normalize_rubric_retries_an_invalid_answer_then_raises(self):
        ctx = make_ctx()
        # First call returns invalid, second call returns invalid (exhausts retries)
        call = FakeCall([{"bad": "data"}, {"bad": "data"}])
        with self.assertRaises(NotRun) as ctx_manager:
            normalize_rubric("text", "lab_report", call, ctx)
        self.assertEqual(ctx_manager.exception.kind, "invalid")


class TestGradeItem(unittest.TestCase):
    def setUp(self):
        self.ctx = make_ctx()
        self.item = {"id": "I01", "title": "Intro", "max_points": 10}
        self.pages = ["Page 1 text", "Page 2 text"]
        self.language = "en"
        self.calibration_note = ""

    def test_a_rated_item_is_recorded_with_its_evidence(self):
        answer = {
            "status": "rated",
            "level": "attempted",
            "score": 5,
            "comment": "Good",
            "evidence": [{"page": 1, "quote": "Page 1 text"}]
        }
        call = FakeCall([answer])
        result = grade_item(self.item, self.pages, call, self.ctx, self.language, self.calibration_note)
        self.assertEqual(result["status"], "rated")
        self.assertEqual(result["score"], 5)

    def test_not_applicable_has_a_null_score(self):
        answer = {
            "status": "not_applicable",
            "score": None,
            "comment": "N/A",
            "evidence": []
        }
        call = FakeCall([answer])
        # Plan 22 task 2: not_applicable is an answer only for an optional item
        result = grade_item(dict(self.item, optional=True), self.pages, call, self.ctx, self.language,
                            self.calibration_note)
        self.assertEqual(result["status"], "not_applicable")
        self.assertIsNone(result["score"])

    def test_an_unknown_level_is_refused_and_retried_once_with_the_reason(self):
        invalid_answer = {
            "status": "rated",
            "level": "great",
            "score": 11, # no level named
            "comment": "Too high",
            "evidence": [{"page": 1, "quote": "Page 1 text"}]
        }
        valid_answer = {
            "status": "rated",
            "level": "exemplary",
            "score": 10,
            "comment": "Fixed",
            "evidence": [{"page": 1, "quote": "Page 1 text"}]
        }
        call = FakeCall([invalid_answer, valid_answer])
        result = grade_item(self.item, self.pages, call, self.ctx, self.language, self.calibration_note)
        self.assertEqual(result["score"], 10)
        self.assertEqual(len(call.calls), 2)
        # Check that the second call included the reason in calibration note? 
        # The prompt should contain the calibration note.
        # We can't easily inspect the prompt sent to FakeCall unless we capture it, 
        # but FakeCall captures `prompt`.
        # Actually, `call` in ugs_grade is called with `prompt`.
        # The test name says "with the reason".
        # The plan says: "a line naming the refusal added to calibration_note".
        # So the second prompt should contain the reason.
        # Let's verify call.calls[1] contains "above" or similar.
        self.assertIn("previous refusal: level must be one of", call.calls[1].lower())

    def test_low_score_without_evidence_is_refused(self):
        invalid_answer = {
            "status": "rated",
            "level": "attempted",
            "score": 5,
            "comment": "Low",
            "evidence": [] # Missing evidence for score < max
        }
        valid_answer = {
            "status": "rated",
            "level": "attempted",
            "score": 5,
            "comment": "Fixed",
            "evidence": [{"page": 1, "quote": "Page 1 text"}]
        }
        call = FakeCall([invalid_answer, valid_answer])
        result = grade_item(self.item, self.pages, call, self.ctx, self.language, self.calibration_note)
        self.assertEqual(len(call.calls), 2)

    def test_quote_absent_from_its_page_is_refused(self):
        invalid_answer = {
            "status": "rated",
            "level": "attempted",
            "score": 5,
            "comment": "Bad quote",
            "evidence": [{"page": 1, "quote": "NOT IN PAGE"}]
        }
        valid_answer = {
            "status": "rated",
            "level": "attempted",
            "score": 5,
            "comment": "Good quote",
            "evidence": [{"page": 1, "quote": "Page 1 text"}]
        }
        call = FakeCall([invalid_answer, valid_answer])
        result = grade_item(self.item, self.pages, call, self.ctx, self.language, self.calibration_note)
        self.assertEqual(len(call.calls), 2)

    def test_a_quote_split_across_a_line_break_is_accepted(self):
        # Page text has a line break, quote does not
        self.pages = ["Page 1\nsplit text"]
        answer = {
            "status": "rated",
            "level": "attempted",
            "score": 5,
            "comment": "Split quote",
            "evidence": [{"page": 1, "quote": "Page 1 split text"}]
        }
        call = FakeCall([answer])
        # normalize in pdf_annotate handles line breaks? 
        # ugs_grade should use normalize from pdf_annotate or similar logic.
        # The spec says "found, after normalize, in the text of its page".
        result = grade_item(self.item, self.pages, call, self.ctx, self.language, self.calibration_note)
        self.assertEqual(result["status"], "rated")

    def test_invalid_after_retries_is_not_run_and_flagged(self):
        # Updated by plan 12: the exhausted-retries record is built from the LAST answer, not a blank record.
        # A score above the maximum drops the score (status not_run, score null) and keeps the raw value in
        # model_score, the code says why, and the model comment is kept instead of the old "invalid_answer" word.
        invalid_answer = {
            "status": "rated",
            "level": "great",
            "score": 11,
            "comment": "Bad",
            "evidence": [{"page": 1, "quote": "Page 1 text"}]
        }
        call = FakeCall([invalid_answer, invalid_answer])
        result = grade_item(self.item, self.pages, call, self.ctx, self.language, self.calibration_note)
        self.assertEqual(result["status"], "not_run")
        self.assertIsNone(result["score"])
        self.assertEqual(result["model_score"], "great")
        self.assertEqual(result["validation"], "unknown_level")
        self.assertEqual(result["comment"], "Bad")
        self.assertEqual(result["attempts"], 2)
        self.assertTrue(result["flag"])

    def test_over_budget_is_not_run(self):
        # The pages fit the window, so the model is called and the bridge itself refuses the prompt.
        def fake_call(prompt, schema, images=None):
            raise NotRun("over_budget", "Too big")
        
        result = grade_item(self.item, self.pages, fake_call, self.ctx, self.language, self.calibration_note)
        self.assertEqual(result["status"], "not_run")
        self.assertEqual(result["comment"], "over_budget")

    def test_unreachable_propagates(self):
        def fake_call(prompt, schema, images=None):
            raise NotRun("unreachable", "Down")
        
        with self.assertRaises(NotRun) as ctx_manager:
            grade_item(self.item, self.pages, fake_call, self.ctx, self.language, self.calibration_note)
        self.assertEqual(ctx_manager.exception.kind, "unreachable")

    def test_large_report_is_graded_on_matching_pages_only(self):
        # Setup context with small window
        # 45 - 10 leaves 35 tokens, the prompt overhead is 23, so the three pages (23) do not fit but one (9) does.
        self.ctx.window_tokens = 45
        self.ctx.reserve_tokens = 10
        # Pages are selected by their headings
        self.pages = ["## Intro\nIntro page with keyword", "## Methods\nOther page", "## Results\nAnother page"]
        # Item with keyword "Intro"
        self.item["title"] = "Intro"
        
        answer = {
            "status": "rated",
            "level": "attempted",
            "score": 5,
            "comment": "Ok",
            "evidence": [{"page": 1, "quote": "Intro page"}]
        }
        call = FakeCall([answer])
        result = grade_item(self.item, self.pages, call, self.ctx, self.language, self.calibration_note)
        # Check that the prompt sent to call only contained the matching page
        # The prompt contains SECTIONS.
        # We can check call.calls[0]
        self.assertIn("Intro page", call.calls[0])
        self.assertNotIn("Other page", call.calls[0])

    def test_item_that_still_does_not_fit_is_not_run_with_no_fit(self):
        self.ctx.window_tokens = 10
        self.ctx.reserve_tokens = 5
        self.pages = ["Very long page text that definitely exceeds the tiny budget limit"]
        
        def fake_call(prompt, schema, images=None):
            # Should not be called if no_fit
            raise AssertionError("Should not call model if no pages fit")
        
        result = grade_item(self.item, self.pages, fake_call, self.ctx, self.language, self.calibration_note)
        self.assertEqual(result["status"], "not_run")
        self.assertEqual(result["comment"], "no_fit")
        self.assertTrue(result["flag"])


class TestGradeReport(unittest.TestCase):
    def setUp(self):
        self.ctx = make_ctx()
        self.rubric = {
            "assessment_type": "lab_report",
            "total_points": 20,
            "items": [
                {"id": "I01", "title": "Intro", "max_points": 10},
                {"id": "I02", "title": "Body", "max_points": 10}
            ]
        }
        self.pages = ["Page 1", "Page 2"]
        self.report_id = "R01"
        self.loop = 1
        self.language = "en"
        self.calibration_note = ""

    def test_grade_report_skips_items_in_existing(self):
        existing = {
            "report_id": "R01",
            "loop": 1,
            "items": [
                {"item_id": "I01", "status": "rated", "level": "exemplary", "score": 10, "comment": "Done", "evidence": [], "audit": "not_run", "flag": False}
            ]
        }
        
        # I02 needs grading
        answer_i02 = {
            "status": "rated",
            "level": "exemplary",
            "score": 10,
            "comment": "Ok",
            "evidence": [{"page": 1, "quote": "Page 1"}]
        }
        call = FakeCall([answer_i02])
        
        result = grade_report(
            self.rubric, self.pages, self.report_id, self.loop,
            call, self.ctx, self.language, self.calibration_note,
            existing=existing
        )
        
        self.assertEqual(len(result["items"]), 2)
        self.assertEqual(result["items"][0]["item_id"], "I01")
        self.assertEqual(result["items"][0]["score"], 10) # From existing
        self.assertEqual(result["items"][1]["item_id"], "I02")
        self.assertEqual(result["items"][1]["score"], 10) # From call
        
        # Only one call should have been made (for I02)
        self.assertEqual(len(call.calls), 1)

    def test_on_item_is_called_once_per_new_item(self):
        calls = []
        def on_item(item_id, record):
            calls.append(item_id)
            
        existing = {}
        
        answer_i01 = {"status": "rated", "level": "exemplary", "score": 10, "comment": "Ok", "evidence": [{"page": 1, "quote": "Page 1"}]}
        answer_i02 = {"status": "rated", "level": "exemplary", "score": 10, "comment": "Ok", "evidence": [{"page": 1, "quote": "Page 1"}]}
        
        call = FakeCall([answer_i01, answer_i02])
        
        result = grade_report(
            self.rubric, self.pages, self.report_id, self.loop,
            call, self.ctx, self.language, self.calibration_note,
            existing=existing,
            on_item=on_item
        )
        
        self.assertEqual(calls, ["I01", "I02"])

    def test_calibration_note_reaches_the_prompt(self):
        answer = {"status": "rated", "level": "exemplary", "score": 10, "comment": "Ok", "evidence": [{"page": 1, "quote": "Page 1"}]}
        call = FakeCall([answer, answer])
        
        grade_report(
            self.rubric, self.pages, self.report_id, self.loop,
            call, self.ctx, "en", "Important Note",
            existing={}
        )
        
        self.assertIn("Important Note", call.calls[0])


PROMPTS_DIR = Path(__file__).resolve().parents[2] / "prompts"


class TestMissingInThePromptAndSchema(unittest.TestCase):
    """The grader is asked for `missing` in the report language, and the schema does not require it."""

    def test_prompt_asks_for_missing_in_the_report_language(self):
        template = (PROMPTS_DIR / "grade_item.md").read_text(encoding="utf-8")
        ctx = StepContext(
            prompts={"grade_item": template},
            schemas={"grade_item": {"type": "object"}},
            levels={"absent": 0, "attempted": 0.5, "partial": 0.75, "complete": 0.88, "exemplary": 1.0},
            window_tokens=100000,
            reserve_tokens=100,
            count=lambda text: len(text.split()),
            grade_retries=0,
            audit_retries=0,
            min_word_len=3,
        )
        call = FakeCall([{"status": "rated", "level": "exemplary", "score": 10, "comment": "Fictitious.", "evidence": [], "missing": ""}])
        item = {"id": "I01", "title": "Intro", "max_points": 10}
        grade_item(item, ["Un rapport fictif."], call, ctx, "fr", "")
        prompt = call.calls[0]
        self.assertIn("'missing'", prompt)
        self.assertIn("in fr, one sentence at most", prompt)
        self.assertIn("status, level, comment, evidence and missing", prompt)
        self.assertNotIn("{{", prompt)

    def test_schema_accepts_an_answer_without_missing(self):
        schema = json.loads((PROMPTS_DIR / "schemas.json").read_text(encoding="utf-8"))["grade_item"]
        self.assertNotIn("missing", schema["required"])
        self.assertEqual(ugs_bridge.validate_answer(
            {"status": "rated", "level": "attempted", "score": 5, "comment": "Fictitious.", "evidence": []}, schema), [])
        self.assertEqual(ugs_bridge.validate_answer(
            {"status": "rated", "level": "attempted", "score": 5, "comment": "Fictitious.", "evidence": [], "missing": "A gap."}, schema), [])
        # Control: the key exists and is typed, so a number under it is refused.
        self.assertTrue(ugs_bridge.validate_answer(
            {"status": "rated", "level": "attempted", "score": 5, "comment": "Fictitious.", "evidence": [], "missing": 5}, schema))


class TestTimeoutIsOneItem(unittest.TestCase):
    def setUp(self):
        self.ctx = make_ctx()
        self.rubric = {
            "assessment_type": "lab_report",
            "total_points": 30,
            "items": [
                {"id": "I01", "title": "Intro", "max_points": 10},
                {"id": "I02", "title": "Body", "max_points": 10},
                {"id": "I03", "title": "End", "max_points": 10},
            ]
        }
        self.pages = ["Page 1", "Page 2"]
        self.full_answer = {
            "status": "rated",
            "level": "exemplary",
            "score": 10,
            "comment": "Ok",
            "evidence": [{"page": 1, "quote": "Page 1"}],
        }

    def test_timeout_marks_only_its_item_and_the_grade_goes_on(self):
        # Item 1 answered; item 2 times out on its call and on its one retry (grade_retries=1); item 3 answered.
        call = FakeCall([
            self.full_answer,
            NotRun("timeout", "post timed out"),
            NotRun("timeout", "post timed out"),
            self.full_answer,
        ])
        result = grade_report(
            self.rubric, self.pages, "R01", 1, call, self.ctx, "en", "",
        )
        by_id = {record["item_id"]: record for record in result["items"]}
        self.assertEqual(by_id["I01"]["status"], "rated")
        self.assertEqual(by_id["I03"]["status"], "rated")
        self.assertEqual(by_id["I03"]["score"], 10)
        timed_out = by_id["I02"]
        self.assertEqual(timed_out["validation"], "timeout")
        self.assertEqual(timed_out["status"], "not_run")
        self.assertIsNone(timed_out["score"])
        self.assertIsNone(timed_out["model_score"])
        self.assertEqual(timed_out["comment"], "")
        self.assertEqual(timed_out["evidence"], [])
        self.assertEqual(timed_out["missing"], "")
        self.assertTrue(timed_out["flag"])
        self.assertEqual(timed_out["attempts"], self.ctx.grade_retries + 1)

    def test_unreachable_still_stops(self):
        call = FakeCall([
            self.full_answer,
            NotRun("unreachable", "daemon down"),
        ])
        with self.assertRaises(NotRun) as ctx:
            grade_report(self.rubric, self.pages, "R01", 1, call, self.ctx, "en", "")
        self.assertEqual(ctx.exception.kind, "unreachable")


class TestItemPromptText(unittest.TestCase):
    def test_the_item_slot_holds_the_exact_text_not_a_dict(self):
        ctx = make_ctx()
        item = {"id": "I01", "title": "Intro", "max_points": 2, "text": "## 1. Intro (/2)\n\nUne regle exacte.",
                "preamble": "| ABC | Guide fictif |"}
        call = FakeCall([{"status": "rated", "level": "exemplary", "score": 1.0, "comment": "ok",
                          "evidence": [{"page": 1, "quote": "texte"}]}])
        grade_item(item, ["Un texte du rapport."], call, ctx, "fr", "")
        self.assertIn("Une regle exacte.", call.calls[0])
        self.assertIn("| ABC | Guide fictif |", call.calls[0])
        self.assertNotIn("{'id'", call.calls[0])


class TestStrictJson(unittest.TestCase):
    """D1: every grade record is strict JSON, a non-finite score included."""

    def _strict_loads(self, text):
        def refuse(name):
            raise ValueError("non-finite constant in JSON: " + name)
        return json.loads(text, parse_constant=refuse)

    def test_nan_score_is_written_as_strict_json(self):
        from ugs_grade import _record_from_answer
        answer = {"status": "rated", "score": float("nan"), "comment": "c", "evidence": []}
        record = _record_from_answer("i1", answer, "score_missing", 1, 5)
        text = json.dumps(record, allow_nan=False)
        back = self._strict_loads(text)
        self.assertIsNone(back["model_score"])
        self.assertEqual(back["model_score_raw"], "nan")
        self.assertEqual(back["status"], "not_run")

    def test_infinite_score_keeps_raw_text(self):
        from ugs_grade import _record_from_answer
        answer = {"status": "rated", "score": float("-inf"), "comment": "", "evidence": []}
        record = _record_from_answer("i2", answer, "score_missing", 1, 5)
        back = self._strict_loads(json.dumps(record, allow_nan=False))
        self.assertIsNone(back["model_score"])
        self.assertEqual(back["model_score_raw"], "-inf")

    def test_finite_score_has_no_raw_key(self):
        from ugs_grade import _record_from_answer
        answer = {"status": "rated", "score": 3.0, "comment": "", "evidence": []}
        record = _record_from_answer("i3", answer, "ok", 1, 5)
        self.assertNotIn("model_score_raw", record)
        self.assertEqual(record["model_score"], 3.0)


class TestMissingLimitFromConfig(unittest.TestCase):
    """D2: the character limit of the missing-element text is configuration, read by name."""

    def _write_config(self, payload):
        import tempfile
        folder = Path(tempfile.mkdtemp())
        path = folder / "ugs_config.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def test_limit_is_read_from_config(self):
        from ugs_grade import read_missing_max_chars, _missing_text
        path = self._write_config({"grade.missing_max_chars": {"value": 10, "provenance": "test"}})
        limit = read_missing_max_chars(path)
        self.assertEqual(limit, 10)
        answer = {"missing": "x" * 50}
        self.assertEqual(len(_missing_text(answer, 2, 5, limit)), 10)

    def test_missing_key_is_named_with_its_file(self):
        from ugs_grade import read_missing_max_chars
        path = self._write_config({"other.key": {"value": 1, "provenance": "test"}})
        with self.assertRaises(ValueError) as ctx:
            read_missing_max_chars(path)
        message = str(ctx.exception)
        self.assertIn("grade.missing_max_chars", message)
        self.assertIn(path.name, message)

    def test_shipped_config_holds_the_limit(self):
        from ugs_grade import read_missing_max_chars
        from ugs_config import default_path
        self.assertEqual(read_missing_max_chars(default_path()), 300)


class RealR01GradeTest(unittest.TestCase):
    """Plan 25 Task 3, pre-batch acceptance on the owner's R01 report (grade step only). Skipped unless UGS_REAL_WORK
    names the check work folder holding R01/grade.json (R11). Only ids, levels, scores, pages and codes are asserted,
    never report text (R34)."""

    def setUp(self):
        """
        Purpose: Locate the R01 grade of the real-data work folder, or skip the class.
        Inputs:
            None.
        Outputs:
            None. Sets self.grade and self.pages.
        Raises:
            unittest.SkipTest: when UGS_REAL_WORK is not set or holds no grade of R01.
        """
        import os
        from ugs_text import read_pages
        work = os.environ.get("UGS_REAL_WORK", "")
        if not work:
            self.skipTest("UGS_REAL_WORK is not set (owner's real-data check)")
        grade_path = Path(work) / "loop-1" / "R01" / "grade.json"
        if not grade_path.exists():
            self.skipTest("no grade.json for R01 in UGS_REAL_WORK yet")
        self.grade = json.loads(grade_path.read_text(encoding="utf-8"))
        self.pages = read_pages(Path(work), "R01")

    def test_every_item_is_rated_with_a_level_and_no_score_above_its_maximum(self):
        items = self.grade["items"]
        self.assertTrue(items)
        self.assertEqual([item["item_id"] for item in items if item["status"] != "rated"], [])
        self.assertEqual([item["item_id"] for item in items if item["validation"] not in ("ok", "quote_not_found",
                         "evidence_missing", "evidence_incomplete", "evidence_page_out_of_range")], [])
        self.assertEqual([item["item_id"] for item in items if item["score"] is None], [])

    def test_the_levels_are_not_all_the_same_fraction(self):
        fractions = {item["model_score"] for item in self.grade["items"]}
        self.assertGreater(len(fractions), 1, "every item carries one level: check the grader's answers")

    def test_the_timesheet_item_is_graded_on_an_appendix_page(self):
        from ugs_text import _is_appendix_heading
        appendix_pages = [number for number, text in enumerate(self.pages, start=1)
                          if any(_is_appendix_heading(line) for line in text.split("\n"))]
        self.assertTrue(appendix_pages, "no appendix page found in the report")
        item = next(item for item in self.grade["items"] if item["item_id"] == "I07")
        self.assertEqual(item["status"], "rated")
        self.assertTrue(any(entry["page"] >= min(appendix_pages) for entry in item["evidence"]),
                        "I07 has no evidence on an appendix page")


if __name__ == "__main__":
    unittest.main()
