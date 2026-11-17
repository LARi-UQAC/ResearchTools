import sys
import unittest
from pathlib import Path

# Add parent folder to path
_SCRIPTS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_SCRIPTS_DIR))

# Add loop-engineer scripts to path to satisfy ugs_bridge imports
_LOOP_ENGINEER_SCRIPTS = _SCRIPTS_DIR.parent.parent / "loop-engineer" / "scripts"
if _LOOP_ENGINEER_SCRIPTS.exists() and str(_LOOP_ENGINEER_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_LOOP_ENGINEER_SCRIPTS))

from ugs_audit import audit_report, audit_item
from ugs_bridge import NotRun
from ugs_text import StepContext
from ugs_grade import grade_item

class FakeCall:
    def __init__(self, responses):
        self.responses = list(responses)
        self.prompts = []
        
    def __call__(self, prompt, schema, images=None):
        self.prompts.append(prompt)
        if not self.responses:
            raise AssertionError("No more responses in FakeCall")
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r

def make_ctx():
    return StepContext(
        prompts={
            "audit_item": "AUDIT {{ITEM}} {{GRADE_RECORD}} {{EVIDENCE_PAGES}}",
            "grade_item": "GRADE {{ITEM}} {{SECTIONS}} {{LEVELS}} {{LANGUAGE_OF_REPORT}} {{CALIBRATION_NOTE}}"
        },
        schemas={
            "audit_item": {"type": "object"},
            "grade_item": {"type": "object"}
        },
        levels={"absent": 0, "attempted": 0.5, "partial": 0.75, "complete": 0.88, "exemplary": 1.0},
        window_tokens=10000,
        reserve_tokens=100,
        count=lambda text: len(text) // 4,
        grade_retries=1,
        audit_retries=1,
        min_word_len=3
    )

class TestAuditItem(unittest.TestCase):
    def setUp(self):
        self.ctx = make_ctx()
        self.item = {"id": "I01", "title": "Intro", "max_points": 10}
        self.record = {
            "item_id": "I01",
            "status": "rated",
            "score": 8.0,
            "comment": "Good",
            "evidence": [{"page": 1, "quote": "text"}],
            "audit": "not_run",
            "flag": False
        }
        self.pages = ["text on page 1", "text on page 2"]

    def test_agree_marks_the_item(self):
        call = FakeCall([{"verdict": "agree", "reason": "ok"}])
        result = audit_item(self.item, self.record, self.pages, call, self.ctx)
        self.assertEqual(result["verdict"], "agree")
        self.assertEqual(result["reason"], "ok")

    def test_disagree_returns_disagree(self):
        call = FakeCall([{"verdict": "disagree", "reason": "bad"}])
        result = audit_item(self.item, self.record, self.pages, call, self.ctx)
        self.assertEqual(result["verdict"], "disagree")
        self.assertEqual(result["reason"], "bad")

    def test_retryable_notrun_retries(self):
        call = FakeCall([
            NotRun("unparsable", "err"),
            {"verdict": "agree", "reason": "ok"}
        ])
        result = audit_item(self.item, self.record, self.pages, call, self.ctx)
        self.assertEqual(result["verdict"], "agree")

    def test_unreachable_propagates(self):
        call = FakeCall([NotRun("unreachable", "err")])
        with self.assertRaises(NotRun) as ctx:
            audit_item(self.item, self.record, self.pages, call, self.ctx)
        self.assertEqual(ctx.exception.kind, "unreachable")

    def test_evidence_pages_are_the_pages_named_by_the_evidence(self):
        call = FakeCall([{"verdict": "agree", "reason": "ok"}])
        audit_item(self.item, self.record, self.pages, call, self.ctx)
        prompt = call.prompts[0]
        self.assertIn("text on page 1", prompt)
        self.assertNotIn("text on page 2", prompt)

    def test_audit_item_skips_an_evidence_page_that_is_not_an_int(self):
        bad_records = [
            dict(self.record, evidence=[{"page": None, "quote": "text"}]),
            dict(self.record, evidence=[{"page": True, "quote": "text"}]),
            dict(self.record, evidence=[None, "text", {"page": "1", "quote": "text"}]),
        ]
        for record in bad_records:
            call = FakeCall([{"verdict": "agree", "reason": "ok"}])
            result = audit_item(self.item, record, self.pages, call, self.ctx)
            self.assertEqual(result["verdict"], "agree")
            # No usable page left: the audit falls back to the selected pages, as for a record with no evidence.
            self.assertIn("text on page 1", call.prompts[0])

class TestAuditReport(unittest.TestCase):
    def setUp(self):
        self.ctx = make_ctx()
        self.rubric = {
            "assessment_type": "lab_report",
            "total_points": 10,
            "items": [{"id": "I01", "title": "Intro", "max_points": 10}]
        }
        self.pages = ["text on page 1", "text on page 2"]
        self.grade = {
            "report_id": "R01",
            "loop": 1,
            "items": [
                {
                    "item_id": "I01",
                    "status": "rated",
                    "score": 8.0,
                    "comment": "Good",
                    "evidence": [{"page": 1, "quote": "text"}],
                    "audit": "not_run",
                    "flag": False
                }
            ]
        }

    def test_agree_marks_the_item(self):
        # Auditor agrees
        call = FakeCall([
            {"verdict": "agree", "reason": "ok"}
        ])
        result = audit_report(self.rubric, self.pages, self.grade, call, self.ctx, "en", "")
        self.assertEqual(result["items"][0]["audit"], "agree")
        self.assertFalse(result["items"][0]["flag"])

    def test_disagree_then_agree_on_regrade_replaces_the_record(self):
        # Auditor disagrees
        # Grader regrades (returns a new record)
        # Auditor agrees with new record
        call = FakeCall([
            {"verdict": "disagree", "reason": "bad"}, # Audit 1
            {"status": "rated", "score": 9.0, "comment": "Better", "evidence": [{"page": 1, "quote": "text"}]}, # Regrade
            {"verdict": "agree", "reason": "ok"} # Audit 2
        ])
        result = audit_report(self.rubric, self.pages, self.grade, call, self.ctx, "en", "")
        item = result["items"][0]
        self.assertEqual(item["audit"], "agree")
        self.assertEqual(item["score"], 9.0)
        self.assertFalse(item["flag"])

    def test_disagree_twice_keeps_the_first_record_and_flags(self):
        # Auditor disagrees
        # Grader regrades
        # Auditor disagrees again
        call = FakeCall([
            {"verdict": "disagree", "reason": "bad"}, # Audit 1
            {"status": "rated", "score": 9.0, "comment": "Better", "evidence": [{"page": 1, "quote": "text"}]}, # Regrade
            {"verdict": "disagree", "reason": "still bad"} # Audit 2
        ])
        result = audit_report(self.rubric, self.pages, self.grade, call, self.ctx, "en", "")
        item = result["items"][0]
        self.assertEqual(item["audit"], "disagree")
        self.assertEqual(item["score"], 8.0) # Original score
        self.assertTrue(item["flag"])

    def test_not_applicable_and_not_run_items_are_not_audited(self):
        grade_na = {
            "report_id": "R01",
            "loop": 1,
            "items": [
                {
                    "item_id": "I01",
                    "status": "not_applicable",
                    "score": None,
                    "comment": "",
                    "evidence": [],
                    "audit": "not_run",
                    "flag": False
                }
            ]
        }
        call = FakeCall([])
        result = audit_report(self.rubric, self.pages, grade_na, call, self.ctx, "en", "")
        self.assertEqual(result["items"][0]["audit"], "not_run")
        self.assertEqual(len(call.prompts), 0)

    def test_auditor_failure_is_not_run_without_flag(self):
        # Auditor fails with retryable error, exhausts retries
        call = FakeCall([
            NotRun("unparsable", "err1"),
            NotRun("unparsable", "err2")
        ])
        result = audit_report(self.rubric, self.pages, self.grade, call, self.ctx, "en", "")
        item = result["items"][0]
        self.assertEqual(item["audit"], "not_run")
        self.assertFalse(item["flag"])

    def test_unreachable_propagates(self):
        call = FakeCall([NotRun("unreachable", "err")])
        with self.assertRaises(NotRun):
            audit_report(self.rubric, self.pages, self.grade, call, self.ctx, "en", "")

    def test_the_input_record_is_not_changed(self):
        call = FakeCall([{"verdict": "agree", "reason": "ok"}])
        original_grade = self.grade
        # Deep copy for comparison? Or just check reference
        audit_report(self.rubric, self.pages, self.grade, call, self.ctx, "en", "")
        self.assertEqual(self.grade["items"][0]["audit"], "not_run")
        self.assertFalse(self.grade["items"][0]["flag"])

    def test_on_item_is_called_per_audited_item(self):
        calls = []
        def on_item(item_id, record):
            calls.append(item_id)
            
        call = FakeCall([{"verdict": "agree", "reason": "ok"}])
        audit_report(self.rubric, self.pages, self.grade, call, self.ctx, "en", "", on_item=on_item)
        self.assertEqual(calls, ["I01"])

    def test_regrade_prompt_carries_the_auditor_reason(self):
        # Disagree -> Regrade -> Agree
        call = FakeCall([
            {"verdict": "disagree", "reason": "specific_reason"},
            {"status": "rated", "score": 9.0, "comment": "Better", "evidence": [{"page": 1, "quote": "text"}]},
            {"verdict": "agree", "reason": "ok"}
        ])
        audit_report(self.rubric, self.pages, self.grade, call, self.ctx, "en", "calibration_note")
        
        # Check prompt of the regrade (second call)
        regrade_prompt = call.prompts[1]
        self.assertIn("specific_reason", regrade_prompt)
        self.assertIn("calibration_note", regrade_prompt)


class TestMissingInTheAudit(unittest.TestCase):
    """`missing` follows the rule of `comment`: the auditor is shown it, and the saved record keeps it."""

    def setUp(self):
        self.ctx = make_ctx()
        self.item = {"id": "I01", "title": "Intro", "max_points": 10}
        self.pages = ["text on page 1", "text on page 2"]
        self.record = {
            "item_id": "I01", "status": "rated", "score": 5, "comment": "CMT_ONE",
            "evidence": [{"page": 1, "quote": "text"}], "missing": "MISS_ONE", "audit": "not_run", "flag": False,
        }

    def test_auditor_is_shown_missing_as_it_is_shown_comment(self):
        call = FakeCall([{"verdict": "agree", "reason": "ok"}])
        audit_item(self.item, self.record, self.pages, call, self.ctx)
        self.assertIn("CMT_ONE", call.prompts[0])
        self.assertIn("MISS_ONE", call.prompts[0])

    def test_saved_audit_record_keeps_missing(self):
        grade = {"report_id": "R01", "loop": 1, "items": [dict(self.record)]}
        rubric = {"assessment_type": "lab_report", "total_points": 10, "items": [self.item]}
        call = FakeCall([{"verdict": "agree", "reason": "ok"}])
        result = audit_report(rubric, self.pages, grade, call, self.ctx, "en", "")
        self.assertEqual(result["items"][0]["missing"], "MISS_ONE")
        self.assertEqual(result["items"][0]["comment"], "CMT_ONE")


if __name__ == '__main__':
    unittest.main()
