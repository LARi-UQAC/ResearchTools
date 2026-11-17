"""
Offline tests of the grade mark of ugs_run.py and of the validation fields kept out of the audit prompt
(plan 12, Task 2, R12). Fictitious data only (R34). No model, no network, no PDF.
"""
import sys
import unittest
from pathlib import Path

# Put the parent folder of the test folder (scripts) on the path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
# Add loop-engineer scripts to path to satisfy ugs_bridge imports
_LOOP_ENGINEER_SCRIPTS = Path(__file__).resolve().parent.parent.parent.parent / "loop-engineer" / "scripts"
if _LOOP_ENGINEER_SCRIPTS.exists() and str(_LOOP_ENGINEER_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_LOOP_ENGINEER_SCRIPTS))

from ugs_run import _grade_mark
from ugs_audit import audit_item, audit_report
from ugs_text import StepContext


class FakeCall:
    """A model call that answers from a list and records every prompt it was given."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.prompts = []

    def __call__(self, prompt, schema, images=None):
        self.prompts.append(prompt)
        return self.responses.pop(0)


def make_ctx():
    """A step context with the smallest prompts that still carry every slot the audit reads."""
    return StepContext(
        prompts={
            "audit_item": "AUDIT {{ITEM}} {{GRADE_RECORD}} {{EVIDENCE_PAGES}}",
            "grade_item": "GRADE {{ITEM}} {{SECTIONS}} {{LEVELS}} {{LANGUAGE_OF_REPORT}} {{CALIBRATION_NOTE}}",
        },
        schemas={"audit_item": {"type": "object"}, "grade_item": {"type": "object"}},
        levels={"absent": 0, "attempted": 0.5, "partial": 0.75, "complete": 0.88, "exemplary": 1.0},
        window_tokens=10000,
        reserve_tokens=100,
        count=lambda text: len(text) // 4,
        grade_retries=1,
        audit_retries=1,
        min_word_len=3,
    )


def graded_record(status="rated", validation="ok", score=8.0):
    """A fictitious grade record as ugs_grade.grade_item builds it after plan 12, Task 1."""
    return {
        "item_id": "I01",
        "status": status,
        "score": score if status == "rated" else None,
        "model_score": score,
        "comment": "fictitious comment",
        "evidence": [{"page": 1, "quote": "text"}],
        "validation": validation,
        "attempts": 2,
        "audit": "not_run",
        "flag": validation != "ok",
    }


class TestGradeMark(unittest.TestCase):
    """The mark and the note a grade line receives in the ledger (the note is a code, never text)."""

    def test_refused_proof_is_done_with_the_code(self):
        record = graded_record(status="rated", validation="quote_not_found")
        self.assertEqual(_grade_mark(record), ("x", "quote_not_found"))

    def test_unusable_score_is_blocked_with_the_code(self):
        record = graded_record(status="not_run", validation="score_above_max")
        self.assertEqual(_grade_mark(record), ("!", "score_above_max"))

    def test_ok_has_no_note(self):
        record = graded_record(status="rated", validation="ok")
        self.assertEqual(_grade_mark(record), ("x", None))

    def test_a_record_without_validation_still_uses_its_comment_code(self):
        # A record written before plan 12 carries no validation field; its comment is the code, as before.
        record = {"item_id": "I01", "status": "not_run", "comment": "no_fit"}
        self.assertEqual(_grade_mark(record), ("!", "no_fit"))

    def test_a_note_that_is_not_a_code_never_reaches_the_ledger(self):
        record = graded_record(status="rated", validation="The quote says SECRET text")
        mark, note = _grade_mark(record)
        self.assertEqual(mark, "x")
        self.assertEqual(note, "not_run")


class TestAuditValidationFields(unittest.TestCase):
    """The auditor sees the grade without the validation fields; the saved record keeps them."""

    def setUp(self):
        self.ctx = make_ctx()
        self.item = {"id": "I01", "title": "Intro", "max_points": 10}
        self.pages = ["text on page 1", "text on page 2"]

    def test_audit_prompt_excludes_validation_fields(self):
        call = FakeCall([{"verdict": "agree", "reason": "ok"}])
        audit_item(self.item, graded_record(validation="quote_not_found"), self.pages, call, self.ctx)
        prompt = call.prompts[0]
        self.assertNotIn('"validation"', prompt)
        self.assertNotIn('"attempts"', prompt)
        self.assertNotIn('"model_score"', prompt)
        # Control: the grade itself is still sent, so the auditor has something to judge.
        self.assertIn('"comment"', prompt)

    def test_audit_keeps_validation_fields_in_the_saved_record(self):
        grade = {"report_id": "R01", "loop": 1, "items": [graded_record(validation="quote_not_found")]}
        rubric = {"assessment_type": "lab_report", "total_points": 10,
                  "items": [{"id": "I01", "title": "Intro", "max_points": 10}]}
        call = FakeCall([{"verdict": "agree", "reason": "ok"}])
        result = audit_report(rubric, self.pages, grade, call, self.ctx, "en", "")
        saved = result["items"][0]
        self.assertEqual(saved["validation"], "quote_not_found")
        self.assertEqual(saved["attempts"], 2)
        self.assertEqual(saved["model_score"], 8.0)
        self.assertEqual(saved["audit"], "agree")


if __name__ == "__main__":
    unittest.main()
