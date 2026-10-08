import csv
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPT_DIR))

from table import HEADER, csv_path, main, validate  # noqa: E402


def test_slugify_is_location_agnostic():
    from pef_common import slugify
    assert slugify("Canada, Ontario") == "canada-ontario"
    assert slugify("Canada") == "canada"
    assert slugify("France, Île-de-France") == "france-ile-de-france"
    assert slugify("Worldwide") == "worldwide"


def test_data_root_env_override(tmp_path, monkeypatch):
    monkeypatch.setenv("PROFESSOR_EXPERTISE_DATA", str(tmp_path))
    path = csv_path("Canada, Ontario")
    assert path == tmp_path / "canada-ontario" / "departments.csv"


def test_init_never_overwrites(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("PROFESSOR_EXPERTISE_DATA", str(tmp_path))
    rc = main(["init", "--location", "Canada, Ontario"])
    out = capsys.readouterr().out
    assert rc == 0 and "CREATED" in out
    path = tmp_path / "canada-ontario" / "departments.csv"
    assert path.exists()
    with path.open("a", newline="", encoding="utf-8") as fh:
        csv.writer(fh).writerow(["U", "D", "https://x.example", "", ""])
    rc = main(["init", "--location", "Canada, Ontario"])
    assert rc == 0 and "EXISTS" in capsys.readouterr().out
    rc = main(["check", "--location", "Canada, Ontario"])
    assert rc == 0 and "1 rows" in capsys.readouterr().out


def test_init_dry_run_writes_nothing(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("PROFESSOR_EXPERTISE_DATA", str(tmp_path))
    rc = main(["init", "--location", "Worldwide", "--dry-run"])
    out = capsys.readouterr().out
    assert rc == 0 and "DRY RUN" in out
    assert not (tmp_path / "worldwide" / "departments.csv").exists()


def test_check_json_report_written(tmp_path, monkeypatch):
    monkeypatch.setenv("PROFESSOR_EXPERTISE_DATA", str(tmp_path))
    main(["init", "--location", "Canada"])
    report = tmp_path / "report.json"
    rc = main(["check", "--location", "Canada", "--json", str(report)])
    assert rc == 0
    data = json.loads(report.read_text(encoding="utf-8"))
    assert data["status"] == "ok" and data["row_count"] == 0


def test_validate_flags_bad_url_and_duplicates(tmp_path):
    path = tmp_path / "departments.csv"
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(HEADER)
        w.writerow(["U", "D", "not-a-url", "", ""])
        w.writerow(["U", "D", "https://x.example", "", ""])
    problems = validate(path)
    assert any("not an http" in p for p in problems)
    assert any("duplicate" in p for p in problems)
