import contextlib
import csv
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SCRIPT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPT_DIR))

from table import HEADER, csv_path, main, validate  # noqa: E402


def run_main(argv):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = main(argv)
    return rc, buf.getvalue()


class TableTest(unittest.TestCase):
    def test_slugify_is_location_agnostic(self):
        from pef_common import slugify
        self.assertEqual(slugify("Canada, Ontario"), "canada-ontario")
        self.assertEqual(slugify("Canada"), "canada")
        self.assertEqual(slugify("France, Île-de-France"), "france-ile-de-france")
        self.assertEqual(slugify("Worldwide"), "worldwide")

    def test_data_root_env_override(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, {"PROFESSOR_EXPERTISE_DATA": tmp}):
                path = csv_path("Canada, Ontario")
                self.assertEqual(path, Path(tmp) / "canada-ontario" / "departments.csv")

    def test_init_never_overwrites(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            with mock.patch.dict(os.environ, {"PROFESSOR_EXPERTISE_DATA": tmp}):
                rc, out = run_main(["init", "--location", "Canada, Ontario"])
                self.assertEqual(rc, 0)
                self.assertIn("CREATED", out)
                path = tmp_path / "canada-ontario" / "departments.csv"
                self.assertTrue(path.exists())
                with path.open("a", newline="", encoding="utf-8") as fh:
                    csv.writer(fh).writerow(["U", "D", "https://x.example", "", ""])
                rc, out = run_main(["init", "--location", "Canada, Ontario"])
                self.assertEqual(rc, 0)
                self.assertIn("EXISTS", out)
                rc, out = run_main(["check", "--location", "Canada, Ontario"])
                self.assertEqual(rc, 0)
                self.assertIn("1 rows", out)

    def test_init_dry_run_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            with mock.patch.dict(os.environ, {"PROFESSOR_EXPERTISE_DATA": tmp}):
                rc, out = run_main(["init", "--location", "Worldwide", "--dry-run"])
                self.assertEqual(rc, 0)
                self.assertIn("DRY RUN", out)
                self.assertFalse((tmp_path / "worldwide" / "departments.csv").exists())

    def test_check_json_report_written(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            with mock.patch.dict(os.environ, {"PROFESSOR_EXPERTISE_DATA": tmp}):
                main(["init", "--location", "Canada"])
                report = tmp_path / "report.json"
                rc, _ = run_main(["check", "--location", "Canada", "--json", str(report)])
                self.assertEqual(rc, 0)
                data = json.loads(report.read_text(encoding="utf-8"))
                self.assertEqual(data["status"], "ok")
                self.assertEqual(data["row_count"], 0)

    def test_validate_flags_bad_url_and_duplicates(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "departments.csv"
            with path.open("w", newline="", encoding="utf-8") as fh:
                w = csv.writer(fh)
                w.writerow(HEADER)
                w.writerow(["U", "D", "not-a-url", "", ""])
                w.writerow(["U", "D", "https://x.example", "", ""])
            problems = validate(path)
            self.assertTrue(any("not an http" in p for p in problems))
            self.assertTrue(any("duplicate" in p for p in problems))


if __name__ == "__main__":
    unittest.main(verbosity=2)
