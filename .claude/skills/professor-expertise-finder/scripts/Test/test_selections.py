import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPT_DIR))

from selections import main  # noqa: E402


def init(tmp_path, monkeypatch, batch="test-batch"):
    monkeypatch.setenv("PROFESSOR_EXPERTISE_DATA", str(tmp_path))
    main(["init", "--batch", batch])
    return batch


def test_no_reuse_across_applications_is_rejected(tmp_path, monkeypatch, capsys):
    batch = init(tmp_path, monkeypatch)
    rc = main(["add", "--batch", batch, "--application", "Set 1",
               "--professor", "Test Person", "--university", "Example University",
               "--score", "4/5", "--status", "final"])
    assert rc == 0
    rc = main(["add", "--batch", batch, "--application", "Set 2",
               "--professor", "Test Person", "--university", "Other University",
               "--score", "4/5", "--status", "final"])
    assert rc == 1
    assert "REJECTED" in capsys.readouterr().out
    rc = main(["check", "--batch", batch, "--professor", "Test Person"])
    assert rc == 1
    assert "TAKEN" in capsys.readouterr().out


def test_university_cap_rejected_past_configured_max(tmp_path, monkeypatch):
    # max_per_university is 1 (SKILL.md Operating Rule 9, 2026-10-08): all
    # evaluators of one application must come from distinct universities.
    batch = init(tmp_path, monkeypatch)
    rc = main(["add", "--batch", batch, "--application", "Set 1",
               "--professor", "Prof 0", "--university", "Same University",
               "--score", "3/5", "--status", "final"])
    assert rc == 0
    rc = main(["add", "--batch", batch, "--application", "Set 1",
               "--professor", "Prof 1", "--university", "Same University",
               "--score", "3/5", "--status", "final"])
    assert rc == 1


def test_conflict_of_interest_rejected_after_origin_declared(tmp_path, monkeypatch):
    batch = init(tmp_path, monkeypatch)
    rc = main(["origin", "--batch", batch, "--application", "Set 1",
               "--university", "Applicant University"])
    assert rc == 0
    rc = main(["add", "--batch", batch, "--application", "Set 1",
               "--professor", "Conflicted Prof", "--university", "Applicant University",
               "--score", "4/5", "--status", "final"])
    assert rc == 1


def test_dry_run_writes_nothing(tmp_path, monkeypatch):
    batch = init(tmp_path, monkeypatch)
    rc = main(["add", "--batch", batch, "--application", "Set 1",
               "--professor", "Test Person", "--university", "Example University",
               "--score", "4/5", "--status", "final", "--dry-run"])
    assert rc == 0
    rc = main(["check", "--batch", batch, "--professor", "Test Person"])
    assert rc == 0  # still AVAILABLE: the dry run above wrote nothing
