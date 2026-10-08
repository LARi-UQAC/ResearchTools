import csv
import json
import sys
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


def test_apply_exclusions_matches_and_reports_unmatched():
    ranking = [{"professor": "Jane Doe", "university": "U1"},
               {"professor": "John Smith", "university": "U2"}]
    exclusion_rows = [{"name": "Doe, Jane", "reason": "unavailable"},
                       {"name": "Nobody Here", "reason": "typo"}]
    kept, excluded, unmatched, ambiguous = apply_exclusions(ranking, exclusion_rows)
    assert [r["professor"] for r in kept] == ["John Smith"]
    assert len(excluded) == 1 and excluded[0][1]["reason"] == "unavailable"
    assert unmatched[0]["name"] == "Nobody Here"
    assert ambiguous == []


def test_homonym_with_different_university_is_ambiguous_not_excluded():
    # Two different real people can share a name; university disambiguates
    # (2026-10-08 code review finding).
    ranking = [{"professor": "Jane Doe", "university": "University Y"}]
    exclusion_rows = [{"name": "Jane Doe", "university": "University X",
                        "reason": "unavailable"}]
    kept, excluded, unmatched, ambiguous = apply_exclusions(ranking, exclusion_rows)
    # Ambiguous is never excluded, but it IS kept (fourth 2026-10-08 round:
    # an ambiguous row used to vanish from both lists, silently dropped).
    assert len(kept) == 1 and excluded == []
    assert len(ambiguous) == 1
    assert ambiguous[0][1]["university"] == "University X"


def test_unknown_ranking_university_with_two_conflicting_candidates_is_ambiguous():
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
    assert len(kept) == 1 and excluded == []
    assert len(ambiguous) == 1


def test_duplicate_identical_exclusion_entries_still_confidently_excluded():
    # Fourth 2026-10-08 round: the original `len(matches) == 1` rule
    # flagged two IDENTICAL exclusion-file rows (an export duplicate, no
    # actual disagreement) as ambiguous merely for being two indices.
    ranking = [{"professor": "Jane Doe", "university": ""}]
    exclusion_rows = [{"name": "Jane Doe", "university": "University X",
                        "reason": "unavailable"},
                       {"name": "Jane Doe", "university": "University X",
                        "reason": "unavailable"}]
    kept, excluded, unmatched, ambiguous = apply_exclusions(ranking, exclusion_rows)
    assert kept == [] and len(excluded) == 1 and ambiguous == []


def test_name_match_still_excludes_when_either_side_lacks_university():
    ranking = [{"professor": "Jane Doe", "university": ""}]
    exclusion_rows = [{"name": "Jane Doe", "university": "University X",
                        "reason": "unavailable"}]
    kept, excluded, unmatched, ambiguous = apply_exclusions(ranking, exclusion_rows)
    assert kept == [] and len(excluded) == 1 and ambiguous == []


def test_first_name_last_name_columns_are_matched():
    # pick() must normalize its OWN candidate column names (first_name ->
    # "first name") to compare against a normalized header - regression
    # for the bug where every first_name/last_name exclusion file row
    # silently resolved to no name and not even an "unmatched" entry.
    ranking = [{"professor": "Jane Doe", "university": "U1"}]
    exclusion_rows = [{"first_name": "Jane", "last_name": "Doe",
                        "reason": "unavailable"}]
    kept, excluded, unmatched, ambiguous = apply_exclusions(ranking, exclusion_rows)
    assert kept == [] and len(excluded) == 1


def test_cli_dry_run_writes_nothing(tmp_path, capsys):
    ranking = tmp_path / "ranking.csv"
    write_csv(ranking, RANKING_FIELDS, [["Jane Doe", "U1"], ["John Smith", "U2"]])
    excl = tmp_path / "excl.csv"
    write_csv(excl, ["name", "reason"], [["Jane Doe", "unavailable"]])
    out_path = tmp_path / "filtered.csv"
    rc = main(["--ranking", str(ranking), "--exclusions", str(excl),
               "--out", str(out_path), "--dry-run"])
    assert rc == 0
    assert "DRY RUN" in capsys.readouterr().out
    assert not out_path.exists()


def test_cli_missing_professor_column_rejected(tmp_path):
    ranking = tmp_path / "ranking.csv"
    write_csv(ranking, ["name"], [["Jane Doe"]])
    excl = tmp_path / "excl.csv"
    write_csv(excl, ["name"], [["Jane Doe"]])
    rc = main(["--ranking", str(ranking), "--exclusions", str(excl),
               "--out", str(tmp_path / "out.csv")])
    assert rc == 1


def test_cli_ambiguous_row_survives_into_the_written_output(tmp_path):
    ranking = tmp_path / "ranking.csv"
    write_csv(ranking, RANKING_FIELDS,
              [["Jane Doe", "University Y"], ["John Smith", "University Z"]])
    excl = tmp_path / "excl.csv"
    write_csv(excl, ["name", "university", "reason"],
              [["Jane Doe", "University X", "unavailable"]])
    out_path = tmp_path / "filtered.csv"
    rc = main(["--ranking", str(ranking), "--exclusions", str(excl), "--out", str(out_path)])
    assert rc == 0
    with out_path.open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    assert {r["professor"] for r in rows} == {"Jane Doe", "John Smith"}


def test_cli_ranking_with_bom_is_read_correctly(tmp_path):
    ranking = tmp_path / "ranking.csv"
    ranking.write_text("professor,university\r\nJane Doe,U1\r\n", encoding="utf-8-sig")
    excl = tmp_path / "excl.csv"
    write_csv(excl, ["name", "reason"], [["Jane Doe", "unavailable"]])
    out_path = tmp_path / "filtered.csv"
    rc = main(["--ranking", str(ranking), "--exclusions", str(excl), "--out", str(out_path)])
    assert rc == 0


def test_cli_json_report(tmp_path):
    ranking = tmp_path / "ranking.csv"
    write_csv(ranking, RANKING_FIELDS, [["Jane Doe", "U1"]])
    excl = tmp_path / "excl.csv"
    write_csv(excl, ["name", "reason"], [["Jane Doe", "unavailable"]])
    report = tmp_path / "report.json"
    rc = main(["--ranking", str(ranking), "--exclusions", str(excl),
               "--out", str(tmp_path / "out.csv"), "--json", str(report)])
    assert rc == 0
    data = json.loads(report.read_text(encoding="utf-8"))
    assert data["excluded_count"] == 1 and data["kept_count"] == 0
