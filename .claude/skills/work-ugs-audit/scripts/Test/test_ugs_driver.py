"""
Offline tests of ugs_driver.py (Issue #104): fictitious reports built with PyMuPDF in a temporary folder, a
fake kind-aware model call, an injected window and counter and no network. Fictitious data only (R34).
"""
import contextlib
import io
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent / "figure-review" / "scripts" / "Test"))

import ugs_driver
from _pdf_fixtures import make_report
from ugs_bridge import NotRun

MARKER = "UNIQUE-MARKER-SENTENCE-ZEBRA"
SCHEMAS = ugs_driver.load_schemas(ugs_driver.SCHEMAS_FILE, ugs_driver.SCHEMA_NAMES)
RUBRIC = {"assessment_type": "lab_report", "total_points": 10,
          "items": [{"id": "I01", "title": "Method", "max_points": 10, "criteria": ["The method is clear."],
                     "checklist": ["Equipment is listed."]}]}

SPLIT_SOURCE = """# Fictitious rubric

**Total : 15 points**

| Acronym | Meaning |
|---------|---------|
| ABC | Fictitious guide |

---

## 1. Method (/10)

The method is described with its tables:

| Type | What to document |
|------|------------------|
| Tests | name of the instrument |

> A quotation of the guide that must stay whole.

---

## 2. Conclusion (/5)

Recall the objectives and the constraints of the client.
"""

TEXT_SOURCE = "Method: 10 points. The method is clear and complete."
TEXT_ANSWER = {"assessment_type": "lab_report", "total_points": 10,
               "items": [{"id": "I01", "title": "Method", "max_points": 10, "text": TEXT_SOURCE}]}


class FakeModel:
    """A kind-aware call: a valid answer for every schema, the score read from `SCORE=` in the prompt."""

    def __init__(self, fail_with=None, echo=False, rubric_answer=None):
        self.calls = []
        self.fail_with = fail_with
        self.echo = echo
        self.rubric_answer = rubric_answer or RUBRIC

    def __call__(self, kind, prompt, schema, images=None):
        self.calls.append((kind, prompt))
        if self.fail_with is not None:
            raise self.fail_with
        if schema == SCHEMAS["grade_item"]:
            score = 9.0
            if "SCORE=" in prompt:
                score = float(prompt.split("SCORE=")[1].split()[0])
            comment = prompt[:300] if self.echo else "ok"
            return {"status": "rated", "score": score, "comment": comment,
                    "evidence": [{"page": 1, "quote": "Introduction text"}]}
        if schema == SCHEMAS["audit_item"]:
            return {"verdict": "agree", "reason": "r"}
        if schema == SCHEMAS["language"]:
            return {"findings": []}
        if schema == SCHEMAS["rubric"]:
            return self.rubric_answer
        raise AssertionError("unexpected schema")


def snapshot(folder: Path):
    return sorted((str(p.relative_to(folder)), p.stat().st_size) for p in folder.rglob("*"))


class TestUgsDriver(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.reports = self.tmp / "reports"
        self.reports.mkdir()
        self.work = self.tmp / "_correction"
        self.rubric_file = self.tmp / "rubric.json"
        self.rubric_file.write_text(json.dumps(RUBRIC), encoding="utf-8")
        self.model = FakeModel()
        patcher = patch("ugs_driver.ugs_config.annotation_author", return_value="Fictitious Author")
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def add_reports(self, scores):
        for index, score in enumerate(scores, start=1):
            make_report(self.reports / f"student{index}.pdf",
                        [{"text": f"SCORE={score} Introduction text of the fictitious report. {MARKER}"}])

    def drv(self, argv, model=None):
        model = model or self.model
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = ugs_driver.main(argv, call=model, fetch=None, window=100000, count=lambda text: len(text.split()))
        lines = [json.loads(line) for line in buffer.getvalue().splitlines() if line.strip()]
        return code, lines, buffer.getvalue()

    def prepare(self, extra=()):
        return self.drv(["prepare", "--reports", str(self.reports), "--rubric", str(self.rubric_file),
                         "--type", "lab_report", *extra])

    def run_loop(self, loop=1, extra=(), model=None):
        return self.drv(["run", "--work", str(self.work), "--reports", str(self.reports), "--loop", str(loop),
                         *extra], model=model)

    def ledger(self):
        return (self.work / "ledger.md").read_text(encoding="utf-8")

    def graded_batch(self, scores):
        self.add_reports(scores)
        self.prepare()
        self.run_loop()

    # --- prepare ---

    def test_prepare_writes_ids_rubric_spec_and_ledger(self):
        self.add_reports([9, 9])
        code, lines, _ = self.prepare()
        self.assertEqual(code, 0)
        self.assertEqual(lines, [{"report_id": "R01", "pages": 1, "step": "prepare", "status": "done"},
                                 {"report_id": "R02", "pages": 1, "step": "prepare", "status": "done"}])
        self.assertEqual(json.loads((self.work / "ids.json").read_text(encoding="utf-8")),
                         {"R01": "student1.pdf", "R02": "student2.pdf"})
        self.assertEqual(json.loads((self.work / "rubric.json").read_text(encoding="utf-8")), RUBRIC)
        rubric_md = (self.work / "rubric.md").read_text(encoding="utf-8")
        self.assertIn("## I01 - Method (10)", rubric_md)
        self.assertIn("- Equipment is listed.", rubric_md)
        text = self.ledger()
        self.assertIn("## R01", text)
        self.assertIn("- [x] prepare", text)
        self.assertIn("- [ ] grade I01", text)
        self.assertFalse((self.work / "loop_state.json").exists())

    def test_prepare_twice_adds_no_duplicate_section(self):
        self.add_reports([9])
        self.prepare()
        first = self.ledger()
        self.prepare()
        self.assertEqual(self.ledger(), first)
        self.assertEqual(first.count("## R01"), 1)

    def test_prepare_json_rubric_is_validated_and_not_sent_to_the_model(self):
        self.add_reports([9])
        model = FakeModel(fail_with=AssertionError("no model call for a JSON rubric"))
        code, _, _ = self.drv(["prepare", "--reports", str(self.reports), "--rubric", str(self.rubric_file),
                               "--type", "lab_report"], model=model)
        self.assertEqual(code, 0)
        self.assertEqual(model.calls, [])
        bad = dict(RUBRIC, total_points=99)
        self.rubric_file.write_text(json.dumps(bad), encoding="utf-8")
        shutil.rmtree(self.work)
        code, lines, _ = self.prepare()
        self.assertEqual(code, 2)
        self.assertIn("invalid rubric", lines[0]["error"])
        self.assertFalse(self.work.exists(), "a refusal leaves nothing behind")

    def test_a_text_rubric_goes_through_the_grader_model(self):
        self.add_reports([9])
        text_rubric = self.tmp / "rubric.md"
        text_rubric.write_text(TEXT_SOURCE, encoding="utf-8")
        model = FakeModel(rubric_answer=TEXT_ANSWER)
        code, lines, _ = self.drv(["prepare", "--reports", str(self.reports), "--rubric", str(text_rubric),
                                   "--type", "lab_report"], model=model)
        self.assertEqual(code, 0)
        self.assertEqual([k for k, _ in model.calls], ["grader"])
        self.assertEqual(json.loads((self.work / "rubric.json").read_text(encoding="utf-8")), TEXT_ANSWER)
        self.assertIn({"warning": "rubric_model_split"}, lines)

    def test_a_numbered_markdown_rubric_is_split_by_code_without_a_model_call(self):
        self.add_reports([4])
        source = self.tmp / "grille.md"
        source.write_text(SPLIT_SOURCE, encoding="utf-8")
        model = FakeModel(fail_with=AssertionError("no model call for a numbered Markdown rubric"))
        code, lines, _ = self.drv(["prepare", "--reports", str(self.reports), "--rubric", str(source),
                                   "--type", "lab_report"], model=model)
        self.assertEqual(code, 0)
        self.assertEqual(model.calls, [])
        self.assertNotIn({"warning": "rubric_model_split"}, lines)
        rubric = json.loads((self.work / "rubric.json").read_text(encoding="utf-8"))
        self.assertEqual([i["max_points"] for i in rubric["items"]], [10, 5])
        self.assertEqual(rubric["total_points"], 15)
        shown = (self.work / "rubric.md").read_text(encoding="utf-8")
        for line in SPLIT_SOURCE.splitlines():
            if line.strip() and line.strip() != "---":
                self.assertIn(line, shown)

    def test_a_stated_total_that_differs_from_the_sum_is_refused_and_nothing_is_written(self):
        self.add_reports([4])
        source = self.tmp / "grille.md"
        source.write_text(SPLIT_SOURCE.replace("**Total : 15 points**", "**Total : 99 points**"), encoding="utf-8")
        code, lines, _ = self.drv(["prepare", "--reports", str(self.reports), "--rubric", str(source),
                                   "--type", "lab_report"])
        self.assertEqual(code, 2)
        self.assertIn("99", lines[0]["error"])
        self.assertIn("15", lines[0]["error"])
        self.assertFalse(self.work.exists())

    def test_a_model_that_drops_a_line_of_an_unnumbered_rubric_is_refused(self):
        self.add_reports([4])
        source = self.tmp / "grille.txt"
        source.write_text(TEXT_SOURCE, encoding="utf-8")
        shortened = {"assessment_type": "lab_report", "total_points": 10,
                     "items": [{"id": "I01", "title": "Method", "max_points": 10, "text": "Method: 10 points."}]}
        code, lines, _ = self.drv(["prepare", "--reports", str(self.reports), "--rubric", str(source),
                                   "--type", "lab_report"], model=FakeModel(rubric_answer=shortened))
        self.assertEqual(code, 2)
        self.assertIn("The method is clear and complete", lines[-1]["error"])
        self.assertFalse(self.work.exists())

    def test_the_grader_receives_the_exact_section_and_the_acronym_block(self):
        self.add_reports([4])
        source = self.tmp / "grille.md"
        source.write_text(SPLIT_SOURCE, encoding="utf-8")
        self.drv(["prepare", "--reports", str(self.reports), "--rubric", str(source), "--type", "lab_report"])
        self.run_loop()
        prompts = [prompt for kind, prompt in self.model.calls if kind == "grader" and "Conclusion (/5)" in prompt]
        self.assertTrue(prompts)
        self.assertIn("Recall the objectives and the constraints of the client.", prompts[0])
        self.assertIn("| ABC | Fictitious guide |", prompts[0])
        self.assertNotIn("{'id'", prompts[0])

    def test_a_json_rubric_without_text_keeps_the_old_rendering(self):
        self.add_reports([4])
        self.prepare()
        shown = (self.work / "rubric.md").read_text(encoding="utf-8")
        self.assertIn("## I01 - Method (10)", shown)

    def test_unsupported_rubric_extension_is_a_refusal(self):
        self.add_reports([9])
        odd = self.tmp / "rubric.xlsx"
        odd.write_bytes(b"x")
        code, lines, _ = self.drv(["prepare", "--reports", str(self.reports), "--rubric", str(odd),
                                   "--type", "lab_report"])
        self.assertEqual(code, 2)
        self.assertIn("convert", lines[0]["error"])
        self.assertFalse(self.work.exists())

    def test_a_type_that_differs_from_the_rubric_is_refused(self):
        self.add_reports([9])
        code, lines, _ = self.drv(["prepare", "--reports", str(self.reports), "--rubric", str(self.rubric_file),
                                   "--type", "project_report"])
        self.assertEqual(code, 2)
        self.assertIn("differs", lines[0]["error"])

    def test_missing_configuration_key_is_named_and_exit_2(self):
        self.add_reports([9])
        config = dict(ugs_driver.ugs_config.load(ugs_driver.ugs_config.default_path()))
        del config["roles.vision"]
        with patch("ugs_driver.ugs_config.load", return_value=config):
            code, lines, _ = self.prepare()
        self.assertEqual(code, 2)
        self.assertIn("roles.vision", lines[0]["error"])

    def test_work_path_outside_the_reports_folder_is_refused(self):
        self.add_reports([9])
        elsewhere = self.tmp / "other" / "_correction"
        code, lines, _ = self.prepare(["--work", str(elsewhere)])
        self.assertEqual(code, 2)
        self.assertIn("beside", lines[0]["error"])
        inside = self.reports / "_correction"
        code, _, _ = self.prepare(["--work", str(inside)])
        self.assertEqual(code, 2)
        self.assertFalse(elsewhere.exists() or inside.exists())

    # --- run ---

    def test_run_grades_every_report_and_prints_json_lines_only(self):
        self.graded_batch([9, 9])
        code, lines, raw = self.run_loop(extra=["--only", "R01"])
        # the first run already happened in graded_batch, so this one only confirms the shape
        self.assertEqual(code, 0)
        for line in raw.splitlines():
            self.assertIsInstance(json.loads(line), dict)
        self.assertEqual(lines[0]["report_id"], "R01")
        text = self.ledger()
        for label in ("grade I01", "language", "audit", "assemble"):
            self.assertIn(f"- [x] {label}", text)
        self.assertTrue((self.work / "loop-1" / "R01" / "annotated.pdf").exists())
        self.assertTrue((self.work / "loop_state.json").exists())

    def test_the_role_of_each_step_is_chosen_by_the_driver(self):
        self.add_reports([9])
        self.prepare()
        self.run_loop()
        self.assertEqual([k for k, _ in self.model.calls], ["grader", "grader", "auditor"])

    def test_run_twice_makes_no_second_model_call(self):
        self.add_reports([9])
        self.prepare()
        self.run_loop()
        before = len(self.model.calls)
        code, lines, _ = self.run_loop()
        self.assertEqual(code, 0)
        self.assertEqual(len(self.model.calls), before)
        self.assertEqual(lines[0]["done"], 0)

    def test_unreachable_daemon_stops_with_exit_1_and_resume_continues(self):
        self.add_reports([9, 9])
        self.prepare()
        down = FakeModel(fail_with=NotRun("unreachable", "down"))
        code, lines, _ = self.run_loop(model=down)
        self.assertEqual(code, 1)
        self.assertEqual(lines, [{"report_id": "R01", "step": "grade I01", "status": "not_run", "kind": "unreachable"}])
        self.assertIn("- [ ] grade I01", self.ledger())
        code, lines, _ = self.run_loop(extra=["--resume"])
        self.assertEqual(code, 0)
        self.assertEqual([l["report_id"] for l in lines], ["R01", "R02"])
        self.assertIn("- [x] assemble", self.ledger())

    def test_marker_sentence_never_reaches_stdout_ledger_or_batch_files(self):
        self.add_reports([9, 9])
        self.prepare()
        echo = FakeModel(echo=True)
        _, lines_run, raw_run = self.run_loop(model=echo)
        _, lines_batch, raw_batch = self.drv(["batch", "--work", str(self.work), "--loop", "1"])
        self.assertTrue(any(MARKER in prompt for _, prompt in echo.calls), "the marker did reach the model")
        for text in (raw_run, raw_batch, self.ledger(),
                     (self.work / "loop-1" / "batch.json").read_text(encoding="utf-8"),
                     (self.work / "loop-1" / "grades.csv").read_text(encoding="utf-8"),
                     (self.work / "loop-1" / "batch_report.md").read_text(encoding="utf-8")):
            self.assertNotIn(MARKER, text)

    def test_a_loop_number_other_than_the_current_one_is_refused(self):
        self.graded_batch([9])
        code, lines, _ = self.run_loop(loop=3)
        self.assertEqual(code, 2)
        self.assertIn("not the current loop", lines[0]["error"])
        code, _, _ = self.drv(["batch", "--work", str(self.work), "--loop", "2"])
        self.assertEqual(code, 2)

    def test_run_refuses_an_unknown_report_and_a_folder_that_is_not_prepared(self):
        self.graded_batch([9])
        code, _, _ = self.run_loop(extra=["--only", "R99"])
        self.assertEqual(code, 2)
        code, _, _ = self.drv(["status", "--work", str(self.tmp / "nothing")])
        self.assertEqual(code, 2)

    # --- batch ---

    def test_batch_in_band_exits_0_and_writes_batch_json(self):
        self.graded_batch([9, 8.5, 9.5, 8.8])
        code, lines, _ = self.drv(["batch", "--work", str(self.work), "--loop", "1"])
        self.assertEqual(code, 0)
        self.assertEqual(lines[0]["verdict"], "in_band")
        stored = json.loads((self.work / "loop-1" / "batch.json").read_text(encoding="utf-8"))
        self.assertEqual(stored["verdict"], "in_band")
        self.assertIn("- [x] assemble", self.ledger())

    def test_batch_out_of_band_exits_3_reopens_the_ledger_and_loop_two_prompt_has_the_note(self):
        self.graded_batch([3, 3, 10, 10])
        code, lines, _ = self.drv(["batch", "--work", str(self.work), "--loop", "1"])
        self.assertEqual(code, 3)
        self.assertNotEqual(lines[0]["verdict"], "in_band")
        text = self.ledger()
        self.assertIn("- [x] prepare", text)
        self.assertIn("- [ ] grade I01", text)
        self.assertNotIn("- [x] grade", text)
        self.assertIn("loop 2 opened", text)
        self.assertEqual(json.loads((self.work / "loop_state.json").read_text(encoding="utf-8")), {"loop": 2})
        second = FakeModel()
        code, _, _ = self.run_loop(loop=2, model=second)
        self.assertEqual(code, 0)
        grader_prompts = [p for k, p in second.calls if k == "grader"]
        self.assertTrue(all("This is loop 2 of the batch" in p for p in grader_prompts[:1]))
        self.assertTrue((self.work / "loop-2" / "R01" / "grade.json").exists())
        self.assertTrue((self.work / "loop-1" / "R01" / "grade.json").exists())

    def test_third_loop_is_refused_without_the_flag_and_allowed_with_it(self):
        self.graded_batch([3, 3, 10, 10])
        self.drv(["batch", "--work", str(self.work), "--loop", "1"])
        self.run_loop(loop=2)
        code, lines, _ = self.drv(["batch", "--work", str(self.work), "--loop", "2"])
        self.assertEqual(code, 2)
        self.assertEqual(lines[-1], {"status": "refused", "reason": "loop_limit"})
        self.assertEqual(json.loads((self.work / "loop_state.json").read_text(encoding="utf-8")), {"loop": 2})
        code, _, _ = self.drv(["batch", "--work", str(self.work), "--loop", "2", "--allow-third"])
        self.assertEqual(code, 3)
        self.assertEqual(json.loads((self.work / "loop_state.json").read_text(encoding="utf-8")), {"loop": 3})

    # --- status and dry run ---

    def test_status_line(self):
        self.add_reports([9])
        self.prepare()
        code, lines, _ = self.drv(["status", "--work", str(self.work)])
        self.assertEqual(code, 0)
        self.assertEqual(lines, [{"done": 1, "open": 5, "blocked": 0, "first_open_report": "R01",
                                  "first_open_step": "grade I01"}])

    def test_dry_run_writes_nothing_for_every_subcommand(self):
        self.add_reports([9])
        before = snapshot(self.tmp)
        code, lines, _ = self.prepare(["--dry-run"])
        self.assertEqual((code, lines[0]["dry_run"]), (0, True))
        self.assertEqual(snapshot(self.tmp), before)
        self.prepare()
        prepared = snapshot(self.tmp)
        for argv in (["run", "--work", str(self.work), "--reports", str(self.reports), "--dry-run"],
                     ["batch", "--work", str(self.work), "--loop", "1", "--dry-run"],
                     ["status", "--work", str(self.work), "--dry-run"]):
            code, _, _ = self.drv(argv)
            self.assertEqual(code, 0)
            self.assertEqual(snapshot(self.tmp), prepared)
        self.assertEqual(self.model.calls, [])


if __name__ == "__main__":
    unittest.main()
