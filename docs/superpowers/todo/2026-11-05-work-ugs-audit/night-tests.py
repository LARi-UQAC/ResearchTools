"""
night-tests.py - one test command for a night project that holds several skills (Issue #104).

aider-night.ps1 takes ONE test command for every plan, while the plans of this effort write tests in
three different Test folders. This runner finds every test_*.py under .claude/skills and runs each as a
script with the interpreter that runs this file. It exits 0 only when all of them pass.
It is mounted at the project root by `run-plan.sh mount-night`; it holds no product logic.
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TIMEOUT_SECONDS = 600  # the limit of the whole suite step, the author's choice, unmeasured


def main() -> int:
    """
    --------------------------------------------------------------------------
    Purpose:
        Run every test file of the project and report the failing ones.

    Inputs:
        None

    Outputs:
        code (int): 0 when every file passed, 1 otherwise. A failing file's last
        lines are printed so the fix loop sees the cause.
    --------------------------------------------------------------------------
    """
    files = sorted(ROOT.glob(".claude/skills/*/scripts/Test/test_*.py"))
    failed = 0
    for path in files:
        done = subprocess.run([sys.executable, str(path)], capture_output=True, text=True,
                              errors="replace", timeout=TIMEOUT_SECONDS)
        if done.returncode != 0:
            failed += 1
            print("FAILED %s" % path.relative_to(ROOT))
            print((done.stdout + done.stderr)[-3000:])
    print("%d test file(s), %d failed" % (len(files), failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
