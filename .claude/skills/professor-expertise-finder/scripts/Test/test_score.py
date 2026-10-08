import json
import sys
from pathlib import Path

import pytest

SCRIPT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPT_DIR))

from score import band, fmt, main, total  # noqa: E402

ALLOWED = {0.0, 0.5, 1.0}


def test_happy_path_total_and_band():
    sub = {"a": 1.0, "b": 1.0, "c": 0.5, "d": 0.0, "e": 1.0}
    t = total(sub, ALLOWED)
    assert t == 3.5
    assert band(t) == "Very close"


def test_invalid_subscore_rejected():
    sub = {"a": 0.7, "b": 1.0, "c": 0.5, "d": 0.0, "e": 1.0}
    with pytest.raises(ValueError, match="subscore A"):
        total(sub, ALLOWED)


def test_e_zero_is_a_hard_exclusion():
    sub = {"a": 1.0, "b": 1.0, "c": 1.0, "d": 1.0, "e": 0.0}
    with pytest.raises(ValueError, match="E = 0"):
        total(sub, ALLOWED)


def test_fmt_drops_trailing_zero():
    assert fmt(1.0) == "1"
    assert fmt(0.5) == "0.5"


def test_cli_happy_path(capsys):
    rc = main(["--a", "1", "--b", "1", "--c", "0.5", "--d", "0", "--e", "1"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "3.5/5 (A 1, B 1, C 0.5, D 0, E 1)" in out


def test_cli_invalid_subscore_exits_1(capsys):
    rc = main(["--a", "0.7", "--b", "1", "--c", "0.5", "--d", "0", "--e", "1"])
    assert rc == 1
    assert "INVALID" in capsys.readouterr().out


def test_cli_below_threshold_is_flagged(capsys):
    rc = main(["--a", "0", "--b", "0", "--c", "0", "--d", "0", "--e", "1"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "below retain threshold" in out


def test_cli_json_report(tmp_path):
    report = tmp_path / "score.json"
    rc = main(["--a", "1", "--b", "1", "--c", "0.5", "--d", "0", "--e", "1",
               "--json", str(report)])
    assert rc == 0
    data = json.loads(report.read_text(encoding="utf-8"))
    assert data["total"] == 3.5 and data["retained"] is True
