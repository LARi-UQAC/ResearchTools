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

# The fictitious answers of this suite name elements, as the model now does; the level and the points are computed.


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
                "## fr_elements\nListe les éléments demandés.\n\n"
                "## en_elements\nList the elements asked.\n\n"
                "## fr_evidence\nCite une preuve exacte.\n\n"
                "## en_evidence\nCite an exact quote.\n\n"
                "## fr_exceptional\nNon justifié.\n\n"
                "## en_exceptional\nNot supported.\n\n"
                "## fr_not_applicable\nNon facultatif.\n\n"
                "## en_not_applicable\nNot optional.\n"
            ),
        },
        schemas={
            "grade_item": {"type": "object"},
            "rubric": {"type": "object"},
        },
        levels={"absent": 0, "attempted": 0.5, "partial": 0.75, "complete_correct": 0.88, "exemplary": 1.0},
        window_tokens=1000,
        reserve_tokens=100,
        count=lambda text: len(text.split()),  # Simple word count as token proxy
        grade_retries=1,
        audit_retries=1,
        min_word_len=3,
    )


def _rated(elements, comment="Ok", missing=""):
    answer = {"status": "rated", "elements": elements, "comment": comment}
    if missing:
        answer["missing"] = missing
    return answer


def _present(page=1, quote="Page 1 text", name="element"):
    return {"element": name, "verdict": "present", "page": page, "quote": quote}


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

    def test_a_rated_item_is_recorded_with_its_elements_and_evidence(self):
        call = FakeCall([_rated([_present(), {"element": "other", "verdict": "absent"}])])
        result = grade_item(self.item, self.pages, call, self.ctx, self.language, self.calibration_note)
        self.assertEqual(result["status"], "rated")
        self.assertEqual(result["level"], "attempted")
        self.assertEqual(result["score"], 5.0)
        self.assertEqual(result["evidence"], [{"page": 1, "quote": "Page 1 text"}])

    def test_not_applicable_has_a_null_score(self):
        answer = {"status": "not_applicable", "elements": [], "comment": "N/A"}
        call = FakeCall([answer])
        result = grade_item(dict(self.item, optional=True), self.pages, call, self.ctx, self.language,
                            self.calibration_note)
        self.assertEqual(result["status"], "not_applicable")
        self.assertIsNone(result["score"])

    def test_elements_missing_is_asked_again_with_its_note_and_then_accepted(self):
        call = FakeCall([_rated([]), _rated([_present()])])
        result = grade_item(self.item, self.pages, call, self.ctx, self.language, self.calibration_note)
        self.assertEqual(len(call.calls), 2)
        self.assertIn("List the elements asked.", call.calls[1])
        self.assertEqual(result["validation"], "ok")

    def test_quote_absent_from_its_page_is_refused_and_asked_again(self):
        bad = _rated([_present(quote="NOT IN PAGE")])
        call = FakeCall([bad, _rated([_present()])])
        result = grade_item(self.item, self.pages, call, self.ctx, self.language, self.calibration_note)
        self.assertEqual(len(call.calls), 2)
        self.assertEqual(result["validation"], "ok")

    def test_a_quote_split_across_a_line_break_is_accepted(self):
        self.pages = ["Page 1\nsplit text"]
        answer = _rated([_present(quote="Page 1 split text")])
        result = grade_item(self.item, self.pages, FakeCall([answer]), self.ctx, self.language, self.calibration_note)
        self.assertEqual(result["status"], "rated")
        self.assertEqual(result["validation"], "ok")

    def test_an_item_with_no_verified_evidence_is_refused_at_any_level(self):
        # The I08 case: a full level on an item whose elements carry no verified quote is refused.
        unproven = _rated([{"element": "x", "verdict": "present"}])
        call = FakeCall([unproven, unproven])
        result = grade_item(self.item, self.pages, call, self.ctx, self.language, self.calibration_note)
        self.assertEqual(result["validation"], "evidence_missing")
        self.assertIs(result["flag"], True)

    def test_invalid_after_retries_is_not_run_and_flagged(self):
        bad = _rated([])
        bad["comment"] = "Bad"
        call = FakeCall([bad, bad])
        result = grade_item(self.item, self.pages, call, self.ctx, self.language, self.calibration_note)
        self.assertEqual(result["status"], "not_run")
        self.assertIsNone(result["score"])
        self.assertEqual(result["validation"], "elements_missing")
        self.assertEqual(result["comment"], "Bad")
        self.assertEqual(result["attempts"], 2)
        self.assertTrue(result["flag"])

    def test_over_budget_is_not_run(self):
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
        self.ctx.window_tokens = 45
        self.ctx.reserve_tokens = 10
        self.pages = ["## Intro\nIntro page with keyword", "## Methods\nOther page", "## Results\nAnother page"]
        self.item["title"] = "Intro"
        answer = _rated([_present(quote="Intro page")], comment="Ok")
        call = FakeCall([answer])
        grade_item(self.item, self.pages, call, self.ctx, self.language, self.calibration_note)
        self.assertIn("Intro page", call.calls[0])
        self.assertNotIn("Other page", call.calls[0])

    def test_item_that_still_does_not_fit_is_not_run_with_no_fit(self):
        self.ctx.window_tokens = 10
        self.ctx.reserve_tokens = 5
        self.pages = ["Very long page text that definitely exceeds the tiny budget limit"]

        def fake_call(prompt, schema, images=None):
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
                {"item_id": "I01", "status": "rated", "level": "exemplary", "score": 10, "comment": "Done",
                 "evidence": [], "audit": "not_run", "flag": False}
            ]
        }
        answer_i02 = _rated([_present(page=1, quote="Page 1")])
        call = FakeCall([answer_i02])
        result = grade_report(self.rubric, self.pages, self.report_id, self.loop, call, self.ctx, self.language,
                              self.calibration_note, existing=existing)
        self.assertEqual(len(result["items"]), 2)
        self.assertEqual(result["items"][0]["item_id"], "I01")
        self.assertEqual(result["items"][0]["score"], 10)  # From existing
        self.assertEqual(result["items"][1]["item_id"], "I02")
        self.assertEqual(result["items"][1]["score"], 8.75)  # complete_correct of 10 points
        self.assertEqual(len(call.calls), 1)

    def test_on_item_is_called_once_per_new_item(self):
        calls = []

        def on_item(item_id, record):
            calls.append(item_id)

        answer = _rated([_present(page=1, quote="Page 1")])
        call = FakeCall([answer, answer])
        grade_report(self.rubric, self.pages, self.report_id, self.loop, call, self.ctx, self.language,
                     self.calibration_note, existing={}, on_item=on_item)
        self.assertEqual(calls, ["I01", "I02"])

    def test_calibration_note_reaches_the_prompt(self):
        answer = _rated([_present(page=1, quote="Page 1")])
        call = FakeCall([answer, answer])
        grade_report(self.rubric, self.pages, self.report_id, self.loop, call, self.ctx, "en", "Important Note",
                     existing={})
        self.assertIn("Important Note", call.calls[0])


PROMPTS_DIR = Path(__file__).resolve().parents[2] / "prompts"


class TestMissingInThePromptAndSchema(unittest.TestCase):
    """The grader is asked for `missing` in the report language, and the schema does not require it."""

    def test_prompt_asks_for_missing_in_the_report_language(self):
        template = (PROMPTS_DIR / "grade_item.md").read_text(encoding="utf-8")
        ctx = StepContext(
            prompts={"grade_item": template},
            schemas={"grade_item": {"type": "object"}},
            levels={"absent": 0, "attempted": 0.5, "partial": 0.75, "complete_correct": 0.88, "exemplary": 1.0},
            window_tokens=100000,
            reserve_tokens=100,
            count=lambda text: len(text.split()),
            grade_retries=0,
            audit_retries=0,
            min_word_len=3,
        )
        call = FakeCall([_rated([_present(page=1, quote="Un rapport fictif")], comment="Fictitious.")])
        item = {"id": "I01", "title": "Intro", "max_points": 10}
        grade_item(item, ["Un rapport fictif."], call, ctx, "fr", "")
        prompt = call.calls[0]
        self.assertIn("'missing'", prompt)
        self.assertIn("in fr, one sentence at most", prompt)
        self.assertIn("status, elements, exceptional, comment and missing", prompt)
        self.assertNotIn("{{", prompt)

    def test_schema_accepts_an_answer_without_missing(self):
        schema = json.loads((PROMPTS_DIR / "schemas.json").read_text(encoding="utf-8"))["grade_item"]
        self.assertNotIn("missing", schema["required"])
        base = {"status": "rated", "elements": [_present()], "comment": "Fictitious."}
        self.assertEqual(ugs_bridge.validate_answer(base, schema), [])
        self.assertEqual(ugs_bridge.validate_answer(dict(base, missing="A gap."), schema), [])
        # Control: the key exists and is typed, so a number under it is refused.
        self.assertTrue(ugs_bridge.validate_answer(dict(base, missing=5), schema))


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
        self.full_answer = _rated([_present(page=1, quote="Page 1")])

    def test_timeout_marks_only_its_item_and_the_grade_goes_on(self):
        call = FakeCall([
            self.full_answer,
            NotRun("timeout", "post timed out"),
            NotRun("timeout", "post timed out"),
            self.full_answer,
        ])
        result = grade_report(self.rubric, self.pages, "R01", 1, call, self.ctx, "en", "")
        by_id = {record["item_id"]: record for record in result["items"]}
        self.assertEqual(by_id["I01"]["status"], "rated")
        self.assertEqual(by_id["I03"]["status"], "rated")
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
        call = FakeCall([self.full_answer, NotRun("unreachable", "daemon down")])
        with self.assertRaises(NotRun) as ctx:
            grade_report(self.rubric, self.pages, "R01", 1, call, self.ctx, "en", "")
        self.assertEqual(ctx.exception.kind, "unreachable")


class TestItemPromptText(unittest.TestCase):
    def test_the_item_slot_holds_the_exact_text_not_a_dict(self):
        ctx = make_ctx()
        item = {"id": "I01", "title": "Intro", "max_points": 2, "text": "## 1. Intro (/2)\n\nUne regle exacte.",
                "preamble": "| ABC | Guide fictif |"}
        call = FakeCall([_rated([_present(page=1, quote="texte")], comment="ok")])
        grade_item(item, ["Un texte du rapport."], call, ctx, "fr", "")
        self.assertIn("Une regle exacte.", call.calls[0])
        self.assertIn("| ABC | Guide fictif |", call.calls[0])
        self.assertNotIn("{'id'", call.calls[0])


class TestRecordIsStrictJson(unittest.TestCase):
    """Every grade record is strict JSON: the verdicts are text, so no non-finite number can reach it."""

    def test_an_element_record_round_trips_as_strict_json(self):
        ctx = make_ctx()
        item = {"id": "I01", "title": "Intro", "max_points": 10}
        record = grade_item(item, ["Page 1 text"], FakeCall([_rated([_present()])]), ctx, "en", "")

        def refuse(name):
            raise ValueError("non-finite constant in JSON: " + name)

        back = json.loads(json.dumps(record, allow_nan=False), parse_constant=refuse)
        self.assertEqual(back["model_score"], "present 1, partial 0, absent 0")


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
        self.assertEqual(len(_missing_text({"missing": "x" * 50}, 2, 1, limit)), 10)

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
        self.assertEqual([item["item_id"] for item in items if item["score"] is None], [])

    def test_the_levels_are_not_all_the_same_fraction(self):
        levels = {item["level"] for item in self.grade["items"]}
        self.assertGreater(len(levels), 1, "every item carries one level: check the element verdicts")

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
