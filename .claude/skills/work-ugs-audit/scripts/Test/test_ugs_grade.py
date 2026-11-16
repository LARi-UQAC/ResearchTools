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
        result = grade_item(self.item, self.pages, call, self.ctx, self.language, self.calibration_note)
        self.assertEqual(result["status"], "not_applicable")
        self.assertIsNone(result["score"])

    def test_score_above_max_is_refused_and_retried_once_with_the_reason(self):
        invalid_answer = {
            "status": "rated",
            "score": 11, # Above max 10
            "comment": "Too high",
            "evidence": [{"page": 1, "quote": "Page 1 text"}]
        }
        valid_answer = {
            "status": "rated",
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
        self.assertIn("above", call.calls[1].lower())

    def test_low_score_without_evidence_is_refused(self):
        invalid_answer = {
            "status": "rated",
            "score": 5,
            "comment": "Low",
            "evidence": [] # Missing evidence for score < max
        }
        valid_answer = {
            "status": "rated",
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
            "score": 5,
            "comment": "Bad quote",
            "evidence": [{"page": 1, "quote": "NOT IN PAGE"}]
        }
        valid_answer = {
            "status": "rated",
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
        invalid_answer = {
            "status": "rated",
            "score": 11,
            "comment": "Bad",
            "evidence": [{"page": 1, "quote": "Page 1 text"}]
        }
        call = FakeCall([invalid_answer, invalid_answer])
        result = grade_item(self.item, self.pages, call, self.ctx, self.language, self.calibration_note)
        self.assertEqual(result["status"], "not_run")
        self.assertIsNone(result["score"])
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
                {"item_id": "I01", "status": "rated", "score": 10, "comment": "Done", "evidence": [], "audit": "not_run", "flag": False}
            ]
        }
        
        # I02 needs grading
        answer_i02 = {
            "status": "rated",
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
        
        answer_i01 = {"status": "rated", "score": 10, "comment": "Ok", "evidence": [{"page": 1, "quote": "Page 1"}]}
        answer_i02 = {"status": "rated", "score": 10, "comment": "Ok", "evidence": [{"page": 1, "quote": "Page 1"}]}
        
        call = FakeCall([answer_i01, answer_i02])
        
        result = grade_report(
            self.rubric, self.pages, self.report_id, self.loop,
            call, self.ctx, self.language, self.calibration_note,
            existing=existing,
            on_item=on_item
        )
        
        self.assertEqual(calls, ["I01", "I02"])

    def test_calibration_note_reaches_the_prompt(self):
        answer = {"status": "rated", "score": 10, "comment": "Ok", "evidence": [{"page": 1, "quote": "Page 1"}]}
        call = FakeCall([answer, answer])
        
        grade_report(
            self.rubric, self.pages, self.report_id, self.loop,
            call, self.ctx, "en", "Important Note",
            existing={}
        )
        
        self.assertIn("Important Note", call.calls[0])


class TestItemPromptText(unittest.TestCase):
    def test_the_item_slot_holds_the_exact_text_not_a_dict(self):
        ctx = make_ctx()
        item = {"id": "I01", "title": "Intro", "max_points": 2, "text": "## 1. Intro (/2)\n\nUne regle exacte.",
                "preamble": "| ABC | Guide fictif |"}
        call = FakeCall([{"status": "rated", "score": 1.0, "comment": "ok",
                          "evidence": [{"page": 1, "quote": "texte"}]}])
        grade_item(item, ["Un texte du rapport."], call, ctx, "fr", "")
        self.assertIn("Une regle exacte.", call.calls[0])
        self.assertIn("| ABC | Guide fictif |", call.calls[0])
        self.assertNotIn("{'id'", call.calls[0])


if __name__ == "__main__":
    unittest.main()
