"""
Offline tests of ugs_run.py (Issue #104): the five steps of one report with every step function patched, a
fixture PDF and a temporary work folder. Fictitious data only (R34).
"""
import contextlib
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# Put the parent folder of the test folder (scripts) on the path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
# Put the figure-review test folder on the path for _pdf_fixtures
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent / "figure-review" / "scripts" / "Test"))

from ugs_run import run_report
from ugs_ledger import new_ledger, add_report, read
from ugs_bridge import NotRun
from _pdf_fixtures import make_report

MARKER = "SECRET MARKER SENTENCE of the report"


def grade_record(item_id="I01", status="rated", comment="ok", flag=False, audit="not_run"):
    return {"item_id": item_id, "status": status, "score": 10 if status == "rated" else None,
            "comment": comment, "evidence": [], "audit": audit, "flag": flag}


def grade_doc(*records):
    return {"report_id": "R01", "loop": 1, "items": list(records)}


FIGURES_DOC = {"report_id": "R01", "figures": [], "report_criteria": {}}
LANGUAGE_DOC = {"annotations": [], "rejected": 0, "not_run": []}
ASSEMBLE_DOC = {"report_id": "R01", "placed": 1, "not_found": 0, "duplicates": 0, "annex_pages": 1,
                "complete": True, "percent": 100.0}


class TestRunReport(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.tmp_dir = Path(self.tmp)
        self.work_dir = self.tmp_dir / "work"
        self.work_dir.mkdir()
        self.pdf_path = self.tmp_dir / "report.pdf"
        make_report(self.pdf_path, [{"text": "text"}])
        pages_dir = self.work_dir / "R01" / "pages"
        pages_dir.mkdir(parents=True)
        (pages_dir / "p001.md").write_text("text on page 1", encoding="utf-8")
        self.rubric = {"assessment_type": "lab_report", "total_points": 10,
                       "items": [{"id": "I01", "title": "Item 1", "max_points": 10}]}
        self.ledger_path = self.work_dir / "ledger.md"
        self.ledger_path.write_text(add_report(new_ledger("Test Ledger"), "R01", ["I01"]), encoding="utf-8")
        self.services = {"rubric": self.rubric, "entries": [], "criteria_doc": {}, "hints": {},
                         "vision_ok": True, "settings": {}}
        self.ctx = MagicMock()
        self.call = MagicMock()
        self.fetch = MagicMock()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_it(self, **kwargs):
        args = {"work_dir": self.work_dir, "report_id": "R01", "loop": 1, "src_pdf": self.pdf_path,
                "call": self.call, "ctx": self.ctx, "services": self.services, "calibration_note": "",
                "fetch": self.fetch}
        args.update(kwargs)
        return run_report(**args)

    @contextlib.contextmanager
    def steps(self, grade=None, language=None, figures=None, audit=None, assemble=None):
        """Patch the five step functions; each answers a valid document unless one is given."""
        grade = grade if grade is not None else grade_doc(grade_record())
        with patch("ugs_run.grade_report") as g, patch("ugs_run.language_report") as lang, \
                patch("ugs_run.figures_report") as fig, patch("ugs_run.audit_report") as aud, \
                patch("ugs_run.assemble_report") as asm:
            g.return_value = grade
            lang.return_value = language if language is not None else LANGUAGE_DOC
            fig.return_value = figures if figures is not None else FIGURES_DOC
            aud.return_value = audit if audit is not None else grade
            asm.return_value = assemble if assemble is not None else ASSEMBLE_DOC
            yield {"grade": g, "language": lang, "figures": fig, "audit": aud, "assemble": asm}

    def ledger(self):
        return read(self.ledger_path)

    def test_all_five_steps_run_and_the_ledger_is_marked(self):
        with self.steps():
            result = self.run_it()
        self.assertEqual(result["status"], "done")
        self.assertEqual(result["steps"], {s: "done" for s in ("grade", "language", "figures", "audit", "assemble")})
        text = self.ledger()
        for line in ("- [x] grade I01", "- [x] language", "- [x] figures", "- [x] audit", "- [x] assemble - pages=1"):
            self.assertIn(line, text)

    def test_vision_not_validated_blocks_the_figures_line_only(self):
        self.services["vision_ok"] = False
        with self.steps():
            result = self.run_it()
        self.assertEqual(result["steps"]["figures"], "blocked")
        self.assertEqual(result["steps"]["audit"], "done")
        self.assertIn("- [!] figures - vision_not_ok", self.ledger())

    def test_second_run_makes_no_model_call(self):
        with self.steps():
            self.run_it()
        with self.steps() as mocks:
            result = self.run_it()
        self.assertEqual(result["status"], "done")
        self.assertEqual(set(result["steps"].values()), {"skipped"})
        for mock in mocks.values():
            mock.assert_not_called()

    def test_a_call_per_step_is_used_when_a_map_is_given(self):
        calls = {step: MagicMock(name=step) for step in ("grade", "language", "figures", "audit")}
        with self.steps() as mocks:
            self.run_it(call=calls)
        self.assertIs(mocks["grade"].call_args[0][4], calls["grade"])
        self.assertIs(mocks["language"].call_args[0][1], calls["language"])
        self.assertIs(mocks["figures"].call_args[0][4], calls["figures"])
        self.assertIs(mocks["audit"].call_args[0][3], calls["audit"])

    def test_a_blocked_step_is_settled_and_not_run_again(self):
        with self.steps(grade=grade_doc(grade_record(status="not_run", comment="no_fit"))):
            self.run_it()
        with self.steps() as mocks:
            self.run_it()
        mocks["grade"].assert_not_called()

    def test_resume_continues_at_the_first_item_not_saved(self):
        self.rubric["items"].append({"id": "I02", "title": "Item 2", "max_points": 10})
        self.ledger_path.write_text(add_report(new_ledger("Test Ledger"), "R01", ["I01", "I02"]), encoding="utf-8")

        def interrupted(rubric, pages, report_id, loop, call, ctx, language, note, existing=None, on_item=None):
            on_item("I01", grade_record("I01"))
            raise NotRun("unreachable", "the daemon went away")

        with self.steps() as mocks:
            mocks["grade"].side_effect = interrupted
            with self.assertRaises(NotRun):
                self.run_it()
        partial = json.loads((self.work_dir / "loop-1" / "R01" / "grade.json").read_text(encoding="utf-8"))
        self.assertEqual([i["item_id"] for i in partial["items"]], ["I01"])
        text = self.ledger()
        self.assertIn("- [x] grade I01", text)
        self.assertIn("- [ ] grade I02", text)

        both = grade_doc(grade_record("I01"), grade_record("I02"))
        with self.steps(grade=both) as mocks:
            result = self.run_it()
        existing = mocks["grade"].call_args[0][8]
        self.assertEqual([i["item_id"] for i in existing["items"]], ["I01"])
        self.assertEqual(result["steps"]["grade"], "done")
        self.assertIn("- [x] grade I02", self.ledger())

    def test_unreachable_leaves_the_step_open_and_propagates(self):
        with self.steps() as mocks:
            mocks["grade"].side_effect = NotRun("unreachable", "Model down")
            with self.assertRaises(NotRun):
                self.run_it()
        self.assertIn("- [ ] grade I01", self.ledger())
        mocks["language"].assert_not_called()

    def test_not_run_item_is_marked_blocked(self):
        with self.steps(grade=grade_doc(grade_record(status="not_run", comment="no_fit", flag=True))):
            result = self.run_it()
        self.assertIn("- [!] grade I01 - no_fit", self.ledger())
        self.assertEqual(result["steps"]["grade"], "blocked")

    def test_a_not_run_comment_that_is_not_a_code_never_reaches_the_ledger(self):
        with self.steps(grade=grade_doc(grade_record(status="not_run", comment=MARKER))):
            self.run_it()
        self.assertNotIn("SECRET", self.ledger())
        self.assertIn("- [!] grade I01 - not_run", self.ledger())

    def test_figure_lines_are_added_and_marked(self):
        record = {"figure_id": "F01", "page": 1, "rect": [0, 0, 10, 10], "file": "f01.png", "kind": "chart",
                  "criteria": {"c1": {"verdict": "pass", "reason": "ok"}}}
        blocked = {"figure_id": "F02", "page": 1, "rect": [0, 0, 10, 10], "file": "f02.png", "kind": "chart",
                   "criteria": {"c1": {"verdict": "not_run", "reason": "x"}}}
        with self.steps(figures={"report_id": "R01", "figures": [record, blocked], "report_criteria": {}}):
            self.run_it()
        text = self.ledger()
        self.assertEqual(text.count("figure F01"), 1)
        self.assertIn("- [x] figure F01", text)
        self.assertIn("- [!] figure F02 - not_run", text)
        saved = json.loads((self.work_dir / "loop-1" / "R01" / "figures.json").read_text(encoding="utf-8"))
        self.assertEqual([f["figure_id"] for f in saved["figures"]], ["F01", "F02"])

    def test_figures_resume_passes_the_saved_figures_by_id(self):
        loop_dir = self.work_dir / "loop-1" / "R01"
        loop_dir.mkdir(parents=True)
        saved = {"report_id": "R01", "report_criteria": {},
                 "figures": [{"figure_id": "F01", "criteria": {}}]}
        (loop_dir / "figures.json").write_text(json.dumps(saved), encoding="utf-8")
        with self.steps() as mocks:
            self.run_it()
        existing = mocks["figures"].call_args[0][9]
        self.assertEqual(list(existing), ["F01"])

    def test_flagged_item_blocks_the_audit_line_with_a_count(self):
        flagged = grade_doc(grade_record(audit="disagree", flag=True))
        with self.steps(audit=flagged):
            result = self.run_it()
        self.assertIn("- [!] audit - flags=1", self.ledger())
        self.assertEqual(result["steps"]["audit"], "blocked")

    def test_the_audit_rewrites_the_saved_grade(self):
        flagged = grade_doc(grade_record(audit="disagree", flag=True))
        with self.steps(audit=flagged):
            self.run_it()
        saved = json.loads((self.work_dir / "loop-1" / "R01" / "grade.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["items"][0]["audit"], "disagree")

    def test_ordinary_error_blocks_the_step_and_stops_the_report(self):
        with self.steps() as mocks:
            mocks["language"].side_effect = ValueError("Something went wrong")
            result = self.run_it()
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["steps"]["language"], "blocked")
        self.assertEqual(result["steps"]["figures"], "skipped")
        mocks["figures"].assert_not_called()
        self.assertIn("- [!] language - error=ValueError", self.ledger())

    def test_an_ordinary_error_in_the_grade_step_marks_the_first_open_grade_line(self):
        with self.steps() as mocks:
            mocks["grade"].side_effect = KeyError("rubric")
            result = self.run_it()
        self.assertEqual(result["steps"]["grade"], "blocked")
        self.assertIn("- [!] grade I01 - error=KeyError", self.ledger())

    def test_loop_two_writes_into_its_own_folder_and_keeps_loop_one(self):
        with self.steps():
            self.run_it()
        loop_one = (self.work_dir / "loop-1" / "R01" / "grade.json").read_text(encoding="utf-8")
        # a new loop reopens the ledger, as the driver does
        self.ledger_path.write_text(add_report(new_ledger("Test Ledger"), "R01", ["I01"]), encoding="utf-8")
        with self.steps():
            self.run_it(loop=2)
        self.assertTrue((self.work_dir / "loop-2" / "R01" / "grade.json").exists())
        self.assertEqual((self.work_dir / "loop-1" / "R01" / "grade.json").read_text(encoding="utf-8"), loop_one)

    def test_marker_sentence_never_reaches_the_ledger(self):
        with self.steps(grade=grade_doc(grade_record(comment=MARKER))):
            self.run_it()
        self.assertNotIn("SECRET", self.ledger())

    def test_returned_summary_holds_no_report_text(self):
        with self.steps(grade=grade_doc(grade_record(comment=MARKER))):
            result = self.run_it()
        self.assertNotIn("SECRET", str(result))
        self.assertEqual(set(result), {"report_id", "status", "steps"})

    def test_figure_step_passes_element_records_to_figures_report(self):
        records = [{"element_id": "F01", "element_type": "figure", "page": 1,
                    "rect": [72.0, 100.0, 500.0, 300.0], "file": "F01.png", "title": None, "legend": "",
                    "notes": [], "caption": "Figure 1: A fictitious plant.", "markdown": None}]
        (self.work_dir / "R01" / "elements.json").write_text(json.dumps(records), encoding="utf-8")
        with self.steps() as mocks:
            self.run_it()
        self.assertEqual(mocks["figures"].call_args.kwargs["elements"], records)

    def test_figure_step_reads_prepared_figures_folder(self):
        (self.work_dir / "R01" / "elements.json").write_text("[]", encoding="utf-8")
        with self.steps() as mocks:
            self.run_it()
        report_dir = mocks["figures"].call_args.args[1]
        self.assertEqual(report_dir, self.work_dir / "R01")
        self.assertNotEqual(report_dir, self.work_dir / "loop-1" / "R01")

    def test_a_step_that_raised_is_retried_on_resume(self):
        with self.steps() as mocks:
            mocks["audit"].side_effect = TypeError("Something went wrong")
            first = self.run_it()
        self.assertEqual(first["status"], "failed")
        self.assertIn("- [!] audit - error=TypeError", self.ledger())
        order = []
        grade = grade_doc(grade_record())
        with self.steps() as mocks:
            mocks["audit"].side_effect = lambda *args, **kwargs: (order.append("audit"), grade)[1]
            mocks["assemble"].side_effect = lambda *args, **kwargs: (order.append("assemble"), ASSEMBLE_DOC)[1]
            second = self.run_it()
        self.assertEqual(second["status"], "done")
        self.assertEqual(order, ["audit", "assemble"])
        self.assertIn("- [x] audit", self.ledger())

    def test_a_bad_language_stops_only_its_report(self):
        self.ledger_path.write_text(
            add_report(add_report(new_ledger("Test Ledger"), "R01", ["I01"]), "R02", ["I01"]), encoding="utf-8")
        pages_dir = self.work_dir / "R02" / "pages"
        pages_dir.mkdir(parents=True)
        (pages_dir / "p001.md").write_text("text on page 1", encoding="utf-8")
        (self.work_dir / "R01" / "report_meta.json").write_text(json.dumps({"language": "xx"}), encoding="utf-8")
        with self.steps() as mocks:
            bad = self.run_it()
            good = self.run_it(report_id="R02")
        self.assertEqual(bad["status"], "failed")
        self.assertIn("language", bad["reason"])
        self.assertIn("report_meta.json", bad["reason"])
        self.assertEqual(good["status"], "done")
        self.assertEqual(mocks["grade"].call_count, 1)


if __name__ == "__main__":
    unittest.main()
