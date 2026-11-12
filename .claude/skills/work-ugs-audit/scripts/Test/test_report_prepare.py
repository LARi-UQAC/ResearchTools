"""
Offline tests of report_prepare.py. The reports are fictitious PDFs built in a temporary folder.
"""
import io
import json
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(SCRIPTS.parent.parent / "figure-review" / "scripts" / "Test"))

import report_prepare  # noqa: E402
from report_prepare import PrepareError, main, prepare, skipped_count  # noqa: E402
from _pdf_fixtures import make_report  # noqa: E402

ARGUMENTS = ("--reports", "--work")


class ReportPrepareTests(unittest.TestCase):
    """Ids, pages, refusals and what is printed."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.reports = self.tmp / "reports"
        self.reports.mkdir()
        self.work = self.tmp / "_correction"

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def run_main(self, *extra):
        """Run main with the two folders and return (exit code, stdout)."""
        out = io.StringIO()
        with redirect_stdout(out):
            code = main([ARGUMENTS[0], str(self.reports), ARGUMENTS[1], str(self.work), *extra])
        return code, out.getvalue()

    def test_ids_follow_sorted_names_and_are_stable_on_rerun(self):
        make_report(self.reports / "report_b.pdf", [{"text": "Page 1"}])
        make_report(self.reports / "report_a.pdf", [{"text": "Page 1"}])
        first = prepare(self.reports, self.work)
        self.assertEqual([item["report_id"] for item in first], ["R01", "R02"])
        ids = json.loads((self.work / "ids.json").read_text(encoding="utf-8"))
        self.assertEqual(ids, {"R01": "report_a.pdf", "R02": "report_b.pdf"})
        second = prepare(self.reports, self.work)
        self.assertEqual([item["report_id"] for item in second], ["R01", "R02"])

    def test_a_report_added_later_gets_the_next_id_and_keeps_the_old_ones(self):
        make_report(self.reports / "report_b.pdf", [{"text": "Page 1"}])
        prepare(self.reports, self.work)
        make_report(self.reports / "report_a.pdf", [{"text": "Page 1"}])
        result = prepare(self.reports, self.work)
        by_id = {item["report_id"] for item in result}
        self.assertEqual(by_id, {"R01", "R02"})
        ids = json.loads((self.work / "ids.json").read_text(encoding="utf-8"))
        self.assertEqual(ids["R01"], "report_b.pdf")
        self.assertEqual(ids["R02"], "report_a.pdf")

    def test_non_pdf_files_are_skipped_and_counted(self):
        make_report(self.reports / "report.pdf", [{"text": "Page 1"}])
        (self.reports / "notes.txt").touch()
        (self.reports / "image.png").touch()
        result = prepare(self.reports, self.work)
        self.assertEqual(len(result), 1)
        self.assertEqual(skipped_count(self.reports), 2)

    def test_one_markdown_file_per_page_with_accents_kept(self):
        make_report(self.reports / "report.pdf", [{"text": "Étude des réseaux électriques"}])
        result = prepare(self.reports, self.work)
        self.assertEqual(result[0]["pages"], 1)
        page = self.work / "R01" / "pages" / "p001.md"
        self.assertIn("Étude des réseaux électriques", page.read_text(encoding="utf-8"))

    def test_an_empty_page_is_flagged_and_its_file_is_empty(self):
        make_report(self.reports / "report.pdf", [{}])
        result = prepare(self.reports, self.work)
        self.assertEqual(result[0]["empty_pages"], [1])
        self.assertEqual((self.work / "R01" / "pages" / "p001.md").read_text(encoding="utf-8").strip(), "")

    def test_a_work_folder_inside_the_reports_folder_is_refused(self):
        make_report(self.reports / "report.pdf", [{"text": "Page 1"}])
        with self.assertRaises(PrepareError):
            prepare(self.reports, self.reports / "_correction")

    def test_the_reports_folder_itself_is_refused_as_work_folder(self):
        make_report(self.reports / "report.pdf", [{"text": "Page 1"}])
        with self.assertRaises(PrepareError):
            prepare(self.reports, self.reports)
        self.assertEqual([path.name for path in self.reports.iterdir()], ["report.pdf"])

    def test_a_work_folder_with_another_parent_is_refused(self):
        make_report(self.reports / "report.pdf", [{"text": "Page 1"}])
        with self.assertRaises(PrepareError):
            prepare(self.reports, self.tmp / "other" / "_correction")

    def test_an_unreadable_id_map_is_refused_without_naming_a_file(self):
        make_report(self.reports / "report.pdf", [{"text": "Page 1"}])
        self.work.mkdir()
        (self.work / "ids.json").write_text("not json", encoding="utf-8")
        with self.assertRaises(PrepareError) as raised:
            prepare(self.reports, self.work)
        self.assertNotIn("ids.json", str(raised.exception))

    def test_a_missing_configuration_key_is_named(self):
        make_report(self.reports / "report.pdf", [{"text": "Page 1"}])
        with patch("report_prepare.ugs_config.load", return_value={}):
            with self.assertRaises(PrepareError) as raised:
                prepare(self.reports, self.work)
        self.assertIn("reports.id_prefix", str(raised.exception))

    def test_stdout_never_carries_a_file_name(self):
        make_report(self.reports / "invented_student_name.pdf", [{"text": "Page 1"}])
        code, output = self.run_main()
        self.assertEqual(code, 0)
        self.assertNotIn("invented_student_name", output)
        self.assertEqual(json.loads(output)["ids"], ["R01"])

    def test_dry_run_writes_nothing(self):
        make_report(self.reports / "report.pdf", [{"text": "Page 1"}])
        code, output = self.run_main("--dry-run")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output), {"reports": 1, "skipped": 0})
        self.assertFalse(self.work.exists())

    def test_a_missing_reports_folder_exits_2(self):
        out = io.StringIO()
        with redirect_stdout(out):
            code = main([ARGUMENTS[0], str(self.tmp / "absent"), ARGUMENTS[1], str(self.work)])
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(out.getvalue())["status"], "refused")

    def test_a_refusal_prints_no_file_name_or_path(self):
        make_report(self.reports / "secret_report.pdf", [{"text": "Page 1"}])
        error = PrepareError(f"failed on {self.reports}/secret_report.pdf")
        with patch.object(report_prepare, "prepare", side_effect=error):
            code, output = self.run_main()
        self.assertEqual(code, 2)
        self.assertNotIn("secret_report", output)
        self.assertNotIn(str(self.reports), output)

    def test_an_unexpected_failure_prints_the_type_and_no_path(self):
        make_report(self.reports / "report.pdf", [{"text": "Page 1"}])
        error = FileNotFoundError(f"No such file: '{self.reports}/report.pdf'")
        with patch.object(report_prepare, "prepare", side_effect=error):
            code, output = self.run_main()
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(output)["error_type"], "FileNotFoundError")
        self.assertNotIn(str(self.reports), output)


if __name__ == "__main__":
    unittest.main()
