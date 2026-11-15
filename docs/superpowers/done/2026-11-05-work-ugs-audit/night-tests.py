"""
night-tests.py - one test command for a night project that holds several skills (Issue #104).

aider-night.ps1 takes ONE test command for every plan, while the plans of this effort write tests in
three different Test folders. This runner finds every test_*.py under .claude/skills and runs each as a
script with the interpreter that runs this file. It exits 0 only when all of them pass.

A test file named in a section of progress.md that carries a blocked mark `[!]` is skipped and listed:
that plan has already failed on its own, and its red test must not fail every plan that follows
(measured 2026-11-11: one blocked plan made the suite of the five next plans fail, and each of them
spent its fix attempts on a test that was not theirs).

It is mounted at the project root by `run-plan.sh mount-night`; it holds no product logic.
"""
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LEDGER = ROOT / "docs" / "superpowers" / "plans" / "progress.md"
TIMEOUT_SECONDS = 600  # the limit of one test file, the author's choice, unmeasured
BLOCKED_MARK = "- [!]"
TEST_NAME = re.compile(r"[\w./-]*test_\w+\.py")


def blocked_tests(ledger_text: str) -> set:
    """
    --------------------------------------------------------------------------
    Purpose:
        Name the test files of the ledger sections that carry a blocked mark.

    Inputs:
        ledger_text (str): the text of progress.md, one `## planN.md` section per plan

    Outputs:
        names (set[str]): file names (no folder) of the test files named in a blocked section.
    --------------------------------------------------------------------------
    """
    names = set()
    for section in re.split(r"(?m)^## ", ledger_text):
        if BLOCKED_MARK in section:
            names.update(Path(match).name for match in TEST_NAME.findall(section))
    return names


def main() -> int:
    """
    --------------------------------------------------------------------------
    Purpose:
        Run every test file of the project except those of blocked plans, and report the failing ones.

    Inputs:
        None

    Outputs:
        code (int): 0 when every file run passed, 1 otherwise. A failing file's last lines are
        printed so the fix loop sees the cause.
    --------------------------------------------------------------------------
    """
    skipped = blocked_tests(LEDGER.read_text(encoding="utf-8", errors="replace")) if LEDGER.is_file() else set()
    files = sorted(ROOT.glob(".claude/skills/*/scripts/Test/test_*.py"))
    failed = 0
    run = 0
    for path in files:
        if path.name in skipped:
            print("SKIPPED %s (its plan is blocked)" % path.relative_to(ROOT))
            continue
        run += 1
        done = subprocess.run([sys.executable, str(path)], capture_output=True, text=True,
                              errors="replace", timeout=TIMEOUT_SECONDS)
        if done.returncode != 0:
            failed += 1
            print("FAILED %s" % path.relative_to(ROOT))
            print((done.stdout + done.stderr)[-3000:])
    print("%d test file(s) run, %d skipped, %d failed" % (run, len(files) - run, failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
