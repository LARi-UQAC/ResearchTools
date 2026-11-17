"""
Offline tests of the action emission of the grading steps (plan 10, task 2, R11): the grade step emits `read` and
`call`, the run step emits `write` and `mark`, and the driver builds the emitter from the bridge log writer.
Fictitious data only (R34): the marker sentence below stands for report text that must never reach a record.
No model, no network, no PDF is opened; every model call is a fake.
"""
import contextlib
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS))

from ugs_events import make_emitter  # noqa: E402
from ugs_grade import grade_report  # noqa: E402
from ugs_ledger import new_ledger, add_report, read  # noqa: E402
from ugs_run import run_report  # noqa: E402
from ugs_text import StepContext  # noqa: E402

MARKER = "ZETA MARKER SENTENCE that only a fictitious report holds"
NOW = "2026-11-16T10:00:00.000+00:00"
ITEM = {"id": "I01", "title": "Item one", "max_points": 10, "criteria": [], "checklist": []}
RUBRIC = {"assessment_type": "lab_report", "total_points": 10, "items": [ITEM]}
FIGURES_DOC = {"report_id": "R01", "figures": [], "report_criteria": {}}
LANGUAGE_DOC = {"annotations": [], "rejected": 0, "not_run": []}
ASSEMBLE_DOC = {"report_id": "R01", "placed": 1, "not_found": 0, "duplicates": 0, "annex_pages": 1,
                "complete": True, "percent": 100.0}


def make_ctx(emit=None, *, prompts=None) -> StepContext:
    """A step context with fictitious prompt templates; emit is the optional emitter."""
    return StepContext(
        prompts=prompts if prompts is not None else {
            "grade_item": "{{ITEM}}|{{SECTIONS}}|{{LEVELS}}|{{LANGUAGE_OF_REPORT}}|{{CALIBRATION_NOTE}}",
        },
        schemas={"grade_item": {}}, levels={"0": 0.0, "10": 1.0}, window_tokens=100000, reserve_tokens=10,
        count=lambda text: 1, grade_retries=0, audit_retries=0, min_word_len=3, emit=emit,
    )


def recording_emitter(records: list):
    """The real emitter of ugs_events, writing into a list: what the driver builds, minus the file."""
    return make_emitter(records.append, lambda: "grader", lambda: NOW)


def rated_answer(evidence=None) -> dict:
    """A rated answer below the maximum, with evidence, so the text of the page is named in the call."""
    return {"status": "rated", "score": 5, "comment": "ok",
            "evidence": evidence if evidence is not None else [{"page": 1, "quote": MARKER}]}


class TestStepContextDefault(unittest.TestCase):

    def test_emit_defaults_to_none_and_old_constructor_still_works(self):
        ctx = StepContext(prompts={}, schemas={}, levels={}, window_tokens=1, reserve_tokens=0,
                          count=lambda text: 1, grade_retries=0, audit_retries=0, min_word_len=3)
        self.assertIsNone(ctx.emit)


class TestGradeEmission(unittest.TestCase):

    def test_grade_emits_read_with_the_page_range_and_call_per_model_call(self):
        records = []
        pages = ["page one text", "page two text"]
        call = MagicMock(return_value={"status": "rated", "score": 10, "comment": "ok", "evidence": []})
        grade_report(RUBRIC, pages, "R01", 1, call, make_ctx(recording_emitter(records)), "en", "")
        reads = [r for r in records if r["action"] == "read"]
        calls = [r for r in records if r["action"] == "call"]
        self.assertEqual([r["target"] for r in reads], ["p1-2"])
        self.assertEqual([r["target"] for r in calls], ["I01"])
        self.assertEqual(reads[0]["report_id"], "R01")
        self.assertEqual(calls[0]["role"], "grader")

    def test_no_emitter_changes_the_grade(self):
        pages = ["page one text"]
        answer = {"status": "rated", "score": 10, "comment": "ok", "evidence": []}
        with_emitter = grade_report(RUBRIC, pages, "R01", 1, MagicMock(return_value=answer),
                                    make_ctx(recording_emitter([])), "en", "")
        without = grade_report(RUBRIC, pages, "R01", 1, MagicMock(return_value=answer), make_ctx(None), "en", "")
        self.assertEqual(with_emitter, without)


class _RunFixture(unittest.TestCase):
    """A work folder with one report, a ledger holding one item, and every step but grade patched."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.work_dir = self.tmp / "work"
        self.work_dir.mkdir()
        pages_dir = self.work_dir / "R01" / "pages"
        pages_dir.mkdir(parents=True)
        (pages_dir / "p001.md").write_text("report text, " + MARKER, encoding="utf-8")
        (self.work_dir / "ledger.md").write_text(add_report(new_ledger("Ledger"), "R01", ["I01"]), encoding="utf-8")
        self.pdf = self.tmp / "report.pdf"
        self.pdf.write_bytes(b"%PDF-1.4\n")
        self.services = {"rubric": RUBRIC, "entries": [], "criteria_doc": {}, "hints": {},
                         "vision_ok": True, "settings": {}}

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_once(self, ctx, grade_answer=None):
        """Run the five steps; grade_report is patched to call on_item once, as the real one does."""
        answer = grade_answer if grade_answer is not None else {
            "item_id": "I01", "status": "rated", "score": 10, "comment": "ok", "evidence": [], "audit": "not_run",
            "flag": False}

        def fake_grade(rubric, pages, report_id, loop, call, ctx_, language, note, existing, on_item):
            on_item("I01", answer)
            return {"report_id": report_id, "loop": loop, "items": [answer]}

        with patch("ugs_run.grade_report", side_effect=fake_grade), \
                patch("ugs_run.language_report", return_value=LANGUAGE_DOC), \
                patch("ugs_run.figures_report", return_value=FIGURES_DOC), \
                patch("ugs_run.audit_report", side_effect=lambda rubric, pages, grade, *a, **k: grade), \
                patch("ugs_run.assemble_report", return_value=ASSEMBLE_DOC):
            return run_report(self.work_dir, "R01", 1, self.pdf, MagicMock(), ctx, self.services, "", None)


class TestRunEmission(_RunFixture):

    def test_run_emits_write_for_each_saved_file(self):
        records = []
        self.run_once(make_ctx(recording_emitter(records)))
        writes = sorted(r["target"] for r in records if r["action"] == "write")
        for name in ("grade.json", "language.json", "figures.json"):
            self.assertIn(name, writes)
        self.assertTrue(all("/" not in t and "\\" not in t for t in writes))

    def test_run_emits_mark_for_each_ledger_line_with_the_mark_as_detail(self):
        records = []
        self.run_once(make_ctx(recording_emitter(records)))
        marks = {(r["target"], r["detail"]) for r in records if r["action"] == "mark"}
        for label in ("grade I01", "language", "figures", "audit", "assemble"):
            self.assertIn((label, "done"), marks)
        ledger = read(self.work_dir / "ledger.md")
        self.assertIn("grade I01", ledger)

    def test_no_emitter_changes_the_ledger(self):
        records = []
        self.run_once(make_ctx(recording_emitter(records)))
        with_emitter = read(self.work_dir / "ledger.md")
        (self.work_dir / "ledger.md").write_text(add_report(new_ledger("Ledger"), "R01", ["I01"]), encoding="utf-8")
        shutil.rmtree(self.work_dir / "loop-1", ignore_errors=True)
        self.run_once(make_ctx(None))
        self.assertEqual(read(self.work_dir / "ledger.md"), with_emitter)

    def test_failing_emitter_does_not_stop_the_step(self):
        broken = make_emitter(MagicMock(side_effect=OSError("log is full")), lambda: "grader", lambda: NOW)
        summary = self.run_once(make_ctx(broken))
        self.assertEqual(summary["status"], "done")
        self.assertGreater(broken.lost, 0)
        self.assertIn("grade I01", read(self.work_dir / "ledger.md"))


class TestNoReportTextInAnyRecord(_RunFixture):

    def test_no_report_text_in_any_record(self):
        records = []
        ctx = make_ctx(recording_emitter(records))
        pages = [("report text, " + MARKER)]
        call = MagicMock(return_value=rated_answer())
        grade_report(RUBRIC, pages, "R01", 1, call, ctx, "en", "")
        self.run_once(ctx, grade_answer=rated_answer())
        self.assertTrue(records, "the emitter must have recorded something for the check to mean anything")
        dumped = json.dumps(records, ensure_ascii=False)
        self.assertNotIn("ZETA MARKER", dumped)
        self.assertNotIn("SENTENCE that only", dumped)


class TestDriverEmitter(unittest.TestCase):

    def test_no_deps_means_no_emitter(self):
        import ugs_driver
        self.assertIsNone(ugs_driver._action_emitter(None, lambda: "grader", lambda: NOW))

    def test_emitter_writes_through_the_deps_log_writer(self):
        import ugs_driver
        written = []
        deps = MagicMock()
        deps.log = written.append
        emit = ugs_driver._action_emitter(deps, lambda: "grader", lambda: NOW)
        emit("read", "p1-3", report_id="R01")
        self.assertEqual(len(written), 1)
        self.assertEqual(written[0]["event"], "action")
        self.assertEqual(written[0]["target"], "p1-3")
        self.assertEqual(written[0]["report_id"], "R01")
        self.assertEqual(written[0]["role"], "grader")


if __name__ == "__main__":
    unittest.main()
