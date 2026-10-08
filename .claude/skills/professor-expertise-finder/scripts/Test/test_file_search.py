import csv
import sys
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


def test_header_not_found_is_rejected(tmp_path):
    bad = tmp_path / "bad.csv"
    with bad.open("w", newline="", encoding="utf-8") as fh:
        csv.writer(fh).writerow(["col1", "col2"])
    rc = main(["--file", str(bad), "--terms", "computer vision",
               "--out", str(tmp_path / "out.csv")])
    assert rc == 1


def test_match_and_unavailable_flag(tmp_path, capsys):
    reviewers = tmp_path / "reviewers.csv"
    write_reviewers(reviewers)
    out_path = tmp_path / "matches.csv"
    rc = main(["--file", str(reviewers), "--terms", "computer vision",
               "--out", str(out_path)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "MATCHES: 1" in out
    assert out_path.exists()
    with out_path.open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    assert rows[0]["name"] == "Jane Doe"
    assert rows[0]["availability"] == "Not available this year"


def test_availability_text_kept_verbatim_not_flattened(tmp_path):
    # 2026-10-08 code review: any non-empty, non-"not available" cell used
    # to collapse to the bare literal "Available", discarding detail like
    # "Available for 2 reviews max".
    reviewers = tmp_path / "reviewers.csv"
    with reviewers.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["Name", "Institution", "Areas of Expertise", "Availability"])
        w.writerow(["Jane Doe", "Example University", "computer vision",
                     "Available for 2 reviews max"])
    out_path = tmp_path / "matches.csv"
    rc = main(["--file", str(reviewers), "--terms", "computer vision",
               "--out", str(out_path)])
    assert rc == 0
    with out_path.open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    assert rows[0]["availability"] == "Available for 2 reviews max"


def test_dry_run_writes_nothing(tmp_path, capsys):
    reviewers = tmp_path / "reviewers.csv"
    write_reviewers(reviewers)
    out_path = tmp_path / "matches.csv"
    rc = main(["--file", str(reviewers), "--terms", "computer vision",
               "--out", str(out_path), "--dry-run"])
    assert rc == 0
    assert "DRY RUN" in capsys.readouterr().out
    assert not out_path.exists()
