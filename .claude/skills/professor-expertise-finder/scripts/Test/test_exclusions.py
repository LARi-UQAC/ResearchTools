import contextlib
import csv
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPT_DIR))

from exclusions import apply_exclusions, main  # noqa: E402

RANKING_FIELDS = ["professor", "university"]


def write_csv(path: Path, header: list[str], rows: list[list[str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        w.writerows(rows)


def run_main(argv):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = main(argv)
    return rc, buf.getvalue()


class ExclusionsTest(unittest.TestCase):
    def test_apply_exclusions_matches_and_reports_unmatched(self):
        ranking = [{"professor": "Jane Doe", "university": "U1"},
                   {"professor": "John Smith", "university": "U2"}]
        exclusion_rows = [{"name": "Doe, Jane", "reason": "unavailable"},
                           {"name": "Nobody Here", "reason": "typo"}]
        kept, excluded, unmatched, ambiguous = apply_exclusions(ranking, exclusion_rows)
        self.assertEqual([r["professor"] for r in kept], ["John Smith"])
        self.assertEqual(len(excluded), 1)
        self.assertEqual(excluded[0][1]["reason"], "unavailable")
        self.assertEqual(unmatched[0]["name"], "Nobody Here")
        self.assertEqual(ambiguous, [])

    def test_homonym_with_different_university_is_ambiguous_not_excluded(self):
        # Two different real people can share a name; university disambiguates
        # (2026-10-08 code review finding).
        ranking = [{"professor": "Jane Doe", "university": "University Y"}]
        exclusion_rows = [{"name": "Jane Doe", "university": "University X",
                            "reason": "unavailable"}]
        kept, excluded, unmatched, ambiguous = apply_exclusions(ranking, exclusion_rows)
        # Ambiguous is never excluded, but it IS kept (fourth 2026-10-08 round:
        # an ambiguous row used to vanish from both lists, silently dropped).
        self.assertEqual(len(kept), 1)
        self.assertEqual(excluded, [])
        self.assertEqual(len(ambiguous), 1)
        self.assertEqual(ambiguous[0][1]["university"], "University X")

    def test_spelling_variant_university_still_cleanly_excludes(self):
        # 2026-10-09 review round 6: _resolve_exclusion_match() compared
        # universities with norm() rather than canonical_university(), so
        # an exclusion-file entry written as the acronym and a ranking row
        # carrying the full name went from a clean exclude to "ambiguous"
        # - exactly the spelling-variant bypass the selections.py fix
        # already closed for the cap/COI/no-reuse checks.
        ranking = [{"professor": "Jane Doe", "university": "Universite du Quebec a Chicoutimi"}]
        exclusion_rows = [{"name": "Jane Doe", "university": "UQAC", "reason": "unavailable"}]
        kept, excluded, unmatched, ambiguous = apply_exclusions(ranking, exclusion_rows)
        self.assertEqual(kept, [])
        self.assertEqual(len(excluded), 1)
        self.assertEqual(ambiguous, [])

    def test_duplicate_entry_as_acronym_and_full_name_still_confidently_excluded(self):
        # Same bypass, the duplicate-entry shape: one exclusion-file row
        # spells the university as the acronym and its duplicate sibling
        # spells it in full. Without canonicalization these read as TWO
        # distinct universities (distinct_unis size 2) and the row is
        # wrongly reported "ambiguous" instead of excluded.
        ranking = [{"professor": "Jane Doe", "university": ""}]
        exclusion_rows = [{"name": "Jane Doe", "university": "UQAC", "reason": "unavailable"},
                           {"name": "Jane Doe",
                            "university": "Universite du Quebec a Chicoutimi",
                            "reason": "unavailable"}]
        kept, excluded, unmatched, ambiguous = apply_exclusions(ranking, exclusion_rows)
        self.assertEqual(kept, [])
        self.assertEqual(len(excluded), 1)
        self.assertEqual(ambiguous, [])

    def test_unknown_ranking_university_with_two_conflicting_candidates_is_ambiguous(self):
        # Second 2026-10-08 code-review round: when the ranking row's own
        # university is unknown and the exclusion FILE ITSELF lists two
        # different "Jane Doe" entries at two different universities, the old
        # code silently picked the first one in file order instead of
        # flagging the ambiguity.
        ranking = [{"professor": "Jane Doe", "university": ""}]
        exclusion_rows = [{"name": "Jane Doe", "university": "University X",
                            "reason": "unavailable"},
                           {"name": "Jane Doe", "university": "University Y",
                            "reason": "sabbatical"}]
        kept, excluded, unmatched, ambiguous = apply_exclusions(ranking, exclusion_rows)
        self.assertEqual(len(kept), 1)
        self.assertEqual(excluded, [])
        self.assertEqual(len(ambiguous), 1)

    def test_duplicate_identical_exclusion_entries_still_confidently_excluded(self):
        # Fourth 2026-10-08 round: the original `len(matches) == 1` rule
        # flagged two IDENTICAL exclusion-file rows (an export duplicate, no
        # actual disagreement) as ambiguous merely for being two indices.
        ranking = [{"professor": "Jane Doe", "university": ""}]
        exclusion_rows = [{"name": "Jane Doe", "university": "University X",
                            "reason": "unavailable"},
                           {"name": "Jane Doe", "university": "University X",
                            "reason": "unavailable"}]
        kept, excluded, unmatched, ambiguous = apply_exclusions(ranking, exclusion_rows)
        self.assertEqual(kept, [])
        self.assertEqual(len(excluded), 1)
        self.assertEqual(ambiguous, [])
        # Fifth round: the sibling duplicate agreeing with the chosen one must
        # not be reported as a typo that "matched nobody".
        self.assertEqual(unmatched, [])

    def test_name_match_still_excludes_when_either_side_lacks_university(self):
        ranking = [{"professor": "Jane Doe", "university": ""}]
        exclusion_rows = [{"name": "Jane Doe", "university": "University X",
                            "reason": "unavailable"}]
        kept, excluded, unmatched, ambiguous = apply_exclusions(ranking, exclusion_rows)
        self.assertEqual(kept, [])
        self.assertEqual(len(excluded), 1)
        self.assertEqual(ambiguous, [])

    def test_first_name_last_name_columns_are_matched(self):
        # pick() must normalize its OWN candidate column names (first_name ->
        # "first name") to compare against a normalized header - regression
        # for the bug where every first_name/last_name exclusion file row
        # silently resolved to no name and not even an "unmatched" entry.
        ranking = [{"professor": "Jane Doe", "university": "U1"}]
        exclusion_rows = [{"first_name": "Jane", "last_name": "Doe",
                            "reason": "unavailable"}]
        kept, excluded, unmatched, ambiguous = apply_exclusions(ranking, exclusion_rows)
        self.assertEqual(kept, [])
        self.assertEqual(len(excluded), 1)

    def test_cli_dry_run_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            ranking = tmp_path / "ranking.csv"
            write_csv(ranking, RANKING_FIELDS, [["Jane Doe", "U1"], ["John Smith", "U2"]])
            excl = tmp_path / "excl.csv"
            write_csv(excl, ["name", "reason"], [["Jane Doe", "unavailable"]])
            out_path = tmp_path / "filtered.csv"
            rc, out = run_main(["--ranking", str(ranking), "--exclusions", str(excl),
                                 "--out", str(out_path), "--dry-run"])
            self.assertEqual(rc, 0)
            self.assertIn("DRY RUN", out)
            self.assertFalse(out_path.exists())

    def test_cli_missing_professor_column_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            ranking = tmp_path / "ranking.csv"
            write_csv(ranking, ["name"], [["Jane Doe"]])
            excl = tmp_path / "excl.csv"
            write_csv(excl, ["name"], [["Jane Doe"]])
            rc, _ = run_main(["--ranking", str(ranking), "--exclusions", str(excl),
                               "--out", str(tmp_path / "out.csv")])
            self.assertEqual(rc, 1)

    def test_cli_ambiguous_row_survives_into_the_written_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            ranking = tmp_path / "ranking.csv"
            write_csv(ranking, RANKING_FIELDS,
                      [["Jane Doe", "University Y"], ["John Smith", "University Z"]])
            excl = tmp_path / "excl.csv"
            write_csv(excl, ["name", "university", "reason"],
                      [["Jane Doe", "University X", "unavailable"]])
            out_path = tmp_path / "filtered.csv"
            rc, _ = run_main(["--ranking", str(ranking), "--exclusions", str(excl),
                               "--out", str(out_path)])
            self.assertEqual(rc, 0)
            with out_path.open(newline="", encoding="utf-8") as fh:
                rows = list(csv.DictReader(fh))
            self.assertEqual({r["professor"] for r in rows}, {"Jane Doe", "John Smith"})

    def test_cli_ranking_with_bom_is_read_correctly(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            ranking = tmp_path / "ranking.csv"
            ranking.write_text("professor,university\r\nJane Doe,U1\r\n", encoding="utf-8-sig")
            excl = tmp_path / "excl.csv"
            write_csv(excl, ["name", "reason"], [["Jane Doe", "unavailable"]])
            out_path = tmp_path / "filtered.csv"
            rc, _ = run_main(["--ranking", str(ranking), "--exclusions", str(excl),
                               "--out", str(out_path)])
            self.assertEqual(rc, 0)

    def test_reads_a_real_xlsx_exclusion_file_and_closes_it(self):
        # No existing test exercised read_rows()'s .xlsx branch (every
        # fixture above is .csv) - the workbook-close fix (2026-10-09
        # review finding) was therefore completely untested here too.
        try:
            import openpyxl
        except ImportError:
            self.skipTest("openpyxl not installed (scripts/requirements.txt)")
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            ranking = tmp_path / "ranking.csv"
            write_csv(ranking, RANKING_FIELDS, [["Jane Doe", "U1"]])
            wb = openpyxl.Workbook()
            ws = wb.active
            ws.append(["name", "reason"])
            ws.append(["Jane Doe", "unavailable"])
            excl_path = tmp_path / "excl.xlsx"
            wb.save(excl_path)
            wb.close()
            out_path = tmp_path / "filtered.csv"
            rc, _ = run_main(["--ranking", str(ranking), "--exclusions", str(excl_path),
                               "--out", str(out_path)])
            self.assertEqual(rc, 0)
            with out_path.open(newline="", encoding="utf-8") as fh:
                self.assertEqual(list(csv.DictReader(fh)), [])
            excl_path.unlink()  # a lingering lock (the bug) raises PermissionError here

    def test_cli_json_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            ranking = tmp_path / "ranking.csv"
            write_csv(ranking, RANKING_FIELDS, [["Jane Doe", "U1"]])
            excl = tmp_path / "excl.csv"
            write_csv(excl, ["name", "reason"], [["Jane Doe", "unavailable"]])
            report = tmp_path / "report.json"
            rc, _ = run_main(["--ranking", str(ranking), "--exclusions", str(excl),
                               "--out", str(tmp_path / "out.csv"), "--json", str(report)])
            self.assertEqual(rc, 0)
            data = json.loads(report.read_text(encoding="utf-8"))
            self.assertEqual(data["excluded_count"], 1)
            self.assertEqual(data["kept_count"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
