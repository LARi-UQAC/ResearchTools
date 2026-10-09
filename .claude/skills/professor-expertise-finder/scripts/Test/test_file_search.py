import contextlib
import csv
import io
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPT_DIR))

from file_search import main  # noqa: E402


def write_reviewers(path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["Name", "Institution", "Areas of Expertise", "Availability"])
        w.writerow(["Jane Doe", "Example University", "computer vision, surface defects",
                     "Not available this year"])
        w.writerow(["John Smith", "Other University", "robotics", "Available"])


def run_main(argv):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = main(argv)
    return rc, buf.getvalue()


class FileSearchTest(unittest.TestCase):
    def test_header_not_found_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            bad = tmp_path / "bad.csv"
            with bad.open("w", newline="", encoding="utf-8") as fh:
                csv.writer(fh).writerow(["col1", "col2"])
            rc, _ = run_main(["--file", str(bad), "--terms", "computer vision",
                               "--out", str(tmp_path / "out.csv")])
            self.assertEqual(rc, 1)

    def test_match_and_unavailable_flag(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            reviewers = tmp_path / "reviewers.csv"
            write_reviewers(reviewers)
            out_path = tmp_path / "matches.csv"
            rc, out = run_main(["--file", str(reviewers), "--terms", "computer vision",
                                 "--out", str(out_path)])
            self.assertEqual(rc, 0)
            self.assertIn("MATCHES: 1", out)
            self.assertTrue(out_path.exists())
            with out_path.open(newline="", encoding="utf-8") as fh:
                rows = list(csv.DictReader(fh))
            self.assertEqual(rows[0]["name"], "Jane Doe")
            self.assertEqual(rows[0]["availability"], "Not available this year")

    def test_availability_text_kept_verbatim_not_flattened(self):
        # 2026-10-08 code review: any non-empty, non-"not available" cell used
        # to collapse to the bare literal "Available", discarding detail like
        # "Available for 2 reviews max".
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            reviewers = tmp_path / "reviewers.csv"
            with reviewers.open("w", newline="", encoding="utf-8") as fh:
                w = csv.writer(fh)
                w.writerow(["Name", "Institution", "Areas of Expertise", "Availability"])
                w.writerow(["Jane Doe", "Example University", "computer vision",
                             "Available for 2 reviews max"])
            out_path = tmp_path / "matches.csv"
            rc, _ = run_main(["--file", str(reviewers), "--terms", "computer vision",
                               "--out", str(out_path)])
            self.assertEqual(rc, 0)
            with out_path.open(newline="", encoding="utf-8") as fh:
                rows = list(csv.DictReader(fh))
            self.assertEqual(rows[0]["availability"], "Available for 2 reviews max")

    def test_french_not_available_phrase_is_recognized(self):
        # Third 2026-10-08 code-review round: NOT_AVAILABLE only checked the
        # English phrase, though SKILL.md documents the French one too.
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            reviewers = tmp_path / "reviewers.csv"
            with reviewers.open("w", newline="", encoding="utf-8") as fh:
                w = csv.writer(fh)
                w.writerow(["Name", "Institution", "Areas of Expertise", "Availability"])
                w.writerow(["Jane Doe", "Example University", "computer vision",
                             "Non disponible cette annee"])
            out_path = tmp_path / "matches.csv"
            rc, _ = run_main(["--file", str(reviewers), "--terms", "computer vision",
                               "--out", str(out_path)])
            self.assertEqual(rc, 0)
            with out_path.open(newline="", encoding="utf-8") as fh:
                rows = list(csv.DictReader(fh))
            self.assertEqual(rows[0]["availability"], "Not available this year")

    def test_institution_column_never_claimed_as_name_column(self):
        # Third 2026-10-08 code-review round: the French name hint "nom d" is a
        # substring of "Nom de l'etablissement" (institution); institution is
        # now resolved first and excluded before the name column is resolved.
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            reviewers = tmp_path / "reviewers.csv"
            with reviewers.open("w", newline="", encoding="utf-8") as fh:
                w = csv.writer(fh)
                w.writerow(["Nom de l'etablissement", "Nom", "Domaines de competence"])
                w.writerow(["Example University", "Jane Doe", "computer vision"])
            out_path = tmp_path / "matches.csv"
            rc, _ = run_main(["--file", str(reviewers), "--terms", "computer vision",
                               "--out", str(out_path)])
            self.assertEqual(rc, 0)
            with out_path.open(newline="", encoding="utf-8") as fh:
                rows = list(csv.DictReader(fh))
            self.assertEqual(rows[0]["name"], "Jane Doe")
            self.assertEqual(rows[0]["institution"], "Example University")

    def test_title_row_alone_is_not_accepted_as_header(self):
        # 2026-10-09 review finding: a lone "external reviewer" prefix made
        # a plain TITLE row ("External Reviewers 2026 list", no expertise
        # column) satisfy find_header() by itself, contradicting its own
        # docstring ("no row carries both a name-like AND an expertise-like
        # header cell").
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            reviewers = tmp_path / "reviewers.csv"
            with reviewers.open("w", newline="", encoding="utf-8") as fh:
                w = csv.writer(fh)
                w.writerow(["External Reviewers 2026 list"])
                w.writerow([])
                w.writerow(["Name", "Institution", "Areas of Expertise", "Availability"])
                w.writerow(["Jane Doe", "Example University", "computer vision", "Available"])
            out_path = tmp_path / "matches.csv"
            rc, _ = run_main(["--file", str(reviewers), "--terms", "computer vision",
                               "--out", str(out_path)])
            self.assertEqual(rc, 0)
            with out_path.open(newline="", encoding="utf-8") as fh:
                rows = list(csv.DictReader(fh))
            self.assertEqual(rows[0]["name"], "Jane Doe")

    def test_keyword_matching_is_word_boundary_not_substring(self):
        # 2026-10-09 review finding: a raw `in` substring check let "ai"
        # match inside "maintenance" and inflated match_count, the sort key.
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            reviewers = tmp_path / "reviewers.csv"
            with reviewers.open("w", newline="", encoding="utf-8") as fh:
                w = csv.writer(fh)
                w.writerow(["Name", "Institution", "Areas of Expertise", "Availability"])
                w.writerow(["Jane Doe", "Example University", "predictive maintenance", "Available"])
            out_path = tmp_path / "matches.csv"
            rc, out = run_main(["--file", str(reviewers), "--terms", "ai",
                                 "--out", str(out_path)])
            self.assertEqual(rc, 0)
            self.assertIn("MATCHES: 0", out)

    def test_availability_column_titled_with_the_literal_flag_phrase(self):
        # 2026-10-09 review finding: AVAILABILITY_HINTS only had the generic
        # words "availability"/"disponibilite" - a column header using the
        # flag phrase itself ("Not available this year") as its NAME,
        # rather than as a cell value under a generic "Availability"
        # header, matched neither hint.
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            reviewers = tmp_path / "reviewers.csv"
            with reviewers.open("w", newline="", encoding="utf-8") as fh:
                w = csv.writer(fh)
                w.writerow(["Name", "Institution", "Areas of Expertise",
                             "Not available this year"])
                w.writerow(["Jane Doe", "Example University", "computer vision", "X"])
            out_path = tmp_path / "matches.csv"
            rc, _ = run_main(["--file", str(reviewers), "--terms", "computer vision",
                               "--out", str(out_path)])
            self.assertEqual(rc, 0)
            with out_path.open(newline="", encoding="utf-8") as fh:
                rows = list(csv.DictReader(fh))
            self.assertEqual(rows[0]["availability"], "X")

    def test_reads_a_real_xlsx_workbook_and_closes_it(self):
        # No existing test exercised the .xlsx branch of read_grid() at all
        # (every fixture above is .csv) - the workbook-close fix (2026-10-09
        # review finding: read-only workbooks were never closed, keeping a
        # Windows file lock until garbage collection) was therefore
        # completely untested. openpyxl is a declared dependency
        # (scripts/requirements.txt), not vendored here.
        try:
            import openpyxl
        except ImportError:
            self.skipTest("openpyxl not installed (scripts/requirements.txt)")
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            wb = openpyxl.Workbook()
            ws = wb.active
            ws.append(["Name", "Institution", "Areas of Expertise", "Availability"])
            ws.append(["Jane Doe", "Example University", "computer vision", "Available"])
            xlsx_path = tmp_path / "reviewers.xlsx"
            wb.save(xlsx_path)
            wb.close()
            out_path = tmp_path / "matches.csv"
            rc, _ = run_main(["--file", str(xlsx_path), "--terms", "computer vision",
                               "--out", str(out_path)])
            self.assertEqual(rc, 0)
            with out_path.open(newline="", encoding="utf-8") as fh:
                rows = list(csv.DictReader(fh))
            self.assertEqual(rows[0]["name"], "Jane Doe")
            # The workbook must be closeable/removable right after main()
            # returns - a lingering read-only lock (the bug) would make this
            # raise PermissionError on Windows.
            xlsx_path.unlink()

    def test_dry_run_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            reviewers = tmp_path / "reviewers.csv"
            write_reviewers(reviewers)
            out_path = tmp_path / "matches.csv"
            rc, out = run_main(["--file", str(reviewers), "--terms", "computer vision",
                                 "--out", str(out_path), "--dry-run"])
            self.assertEqual(rc, 0)
            self.assertIn("DRY RUN", out)
            self.assertFalse(out_path.exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
