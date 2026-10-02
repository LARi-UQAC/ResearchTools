"""
_fixtures.py - shared test fixtures for the wp-portfolio-sync skill.

Stage: imported by every test_*.py in this folder. Never discovered as a
suite itself (leading underscore), per run-offline-tests.ps1's discovery
rule.
"""
import sys
from pathlib import Path

# scripts/Test/_fixtures.py -> parents[1] is scripts/
SCRIPTS = Path(__file__).resolve().parents[1]
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


def make_data_dir(root, files):
    """
    --------------------------------------------------------------------------
    Purpose:
        Build a fictitious researcher data folder for an offline test, never
        touching a real data folder or /tmp (R21).

    Inputs:
        root (Path): a tempfile.TemporaryDirectory() path or similar scratch
            root; the data folder is created at root/data.
        files (dict[str, str]): relative path -> UTF-8 text content. Parent
            directories are created as needed.

    Outputs:
        data_dir (Path): root/data, existing, with every file written.
    --------------------------------------------------------------------------
    """
    data_dir = Path(root) / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    for relative, text in files.items():
        target = data_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    return data_dir
