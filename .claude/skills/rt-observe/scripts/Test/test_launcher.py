"""
test_launcher - the rt-dashboard entry points and their one refusal.

The launchers exist because Python cannot find its own interpreter. Everything
else - the port probe, the two refusals about a held port, the bind, the token -
lives in rt_state.py, where test_rt_state.py drives it with nothing spawned and
no port bound. So what is left to prove here is small and specific:

1. **The root wrappers hold no logic.** A second copy of the interpreter search
   at the repository root would drift from the canonical one beside the module
   (R18), and nothing would report it. Asserted in both directions: a root
   wrapper must NAME the canonical launcher and must NOT name rt_state.py.
2. **The canonical launchers name every candidate they try, in their refusal.**
   A launcher that says "python not found" without saying where it looked sends
   the reader nowhere.
3. **The POSIX launcher's refusal is EXECUTED, not asserted from its text.** The
   whole point of the refusal is the exit code and the message, and a string
   match proves neither. It runs against a fixture tree with an emptied PATH, so
   the real .venv-skills cannot satisfy it by accident.
4. **The positive control.** With an interpreter present, the launcher must
   actually forward `--serve` and every extra argument. Without this, every
   assertion above passes on a launcher that refuses unconditionally.

bash is located the way `test_settings_template_distribution.py` documents:
`shutil.which("bash")` resolves to WSL's System32 launcher on this machine,
which fails every case for reasons that have nothing to do with the code.
"""
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
SKILL_ROOT = SCRIPTS.parent
REPO_ROOT = SKILL_ROOT.parent.parent.parent

CANONICAL_PS1 = SCRIPTS / "rt-dashboard.ps1"
CANONICAL_SH = SCRIPTS / "rt-dashboard.sh"
ROOT_PS1 = REPO_ROOT / "rt-dashboard.ps1"
ROOT_SH = REPO_ROOT / "rt-dashboard.sh"
ROOT_BAT = REPO_ROOT / "rt-dashboard.bat"

# The candidate order each canonical launcher must name in its refusal. Kept
# here as the contract rather than parsed out of the script, so a launcher that
# quietly drops a candidate fails instead of agreeing with itself.
PS1_CANDIDATES = (".venv-skills", "python", "python3", "py")
SH_CANDIDATES = (".venv-skills/bin/python", ".venv-skills/Scripts/python.exe",
                 "python3", "python")


def read(path):
    return path.read_text(encoding="utf-8")


def find_git_bash():
    """Not the first bash on PATH: on this machine that is WSL's System32
    launcher, which answers execvpe(/bin/bash) failed for every case."""
    configured = os.environ.get("CLAUDE_CODE_GIT_BASH_PATH")
    if configured and Path(configured).is_file():
        return configured
    for candidate in (r"C:\Program Files\Git\bin\bash.exe",
                      Path(os.environ.get("LOCALAPPDATA", "")) / "Programs"
                      / "Git" / "bin" / "bash.exe"):
        if Path(candidate).is_file():
            return str(candidate)
    found = shutil.which("bash")
    if found and "system32" not in found.lower():
        return found
    return None


class EntryPointsExist(unittest.TestCase):
    def test_all_five_entry_points_are_present(self):
        for path in (CANONICAL_PS1, CANONICAL_SH, ROOT_PS1, ROOT_SH, ROOT_BAT):
            with self.subTest(path=path.name):
                self.assertTrue(path.is_file(), "%s is missing" % path)

    def test_the_vscode_task_reaches_the_root_wrapper(self):
        tasks = REPO_ROOT / ".vscode" / "tasks.json"
        self.assertTrue(tasks.is_file(), "%s is missing" % tasks)
        text = read(tasks)
        self.assertIn("rt-dashboard", text)
        self.assertIn("rt-dashboard.ps1", text)
        # OS-neutrality is part of the contract, not an extra.
        self.assertIn("rt-dashboard.sh", text)


class RootWrappersHoldNoLogic(unittest.TestCase):
    def test_each_root_wrapper_names_the_next_hop(self):
        self.assertIn("rt-observe\\scripts\\rt-dashboard.ps1", read(ROOT_PS1))
        self.assertIn("rt-observe/scripts/rt-dashboard.sh", read(ROOT_SH))
        self.assertIn("rt-dashboard.ps1", read(ROOT_BAT))

    def test_no_root_wrapper_invokes_the_module_itself(self):
        # The negative half, and the one that matters: a root wrapper that
        # called rt_state.py directly would need its own interpreter search,
        # which is the duplicate this layout exists to avoid.
        for path in (ROOT_PS1, ROOT_SH, ROOT_BAT):
            with self.subTest(path=path.name):
                self.assertNotIn("rt_state.py", read(path))

    def test_no_root_wrapper_searches_for_an_interpreter(self):
        for path in (ROOT_PS1, ROOT_SH, ROOT_BAT):
            with self.subTest(path=path.name):
                self.assertNotIn(".venv-skills", read(path))

    def test_a_root_wrapper_states_a_missing_canonical_launcher(self):
        for path in (ROOT_PS1, ROOT_SH):
            with self.subTest(path=path.name):
                text = read(path)
                self.assertIn("canonical launcher is missing", text)
                self.assertIn("exit 2", text)


class CanonicalLaunchersNameTheirCandidates(unittest.TestCase):
    def test_the_powershell_launcher_names_every_candidate(self):
        text = read(CANONICAL_PS1)
        for candidate in PS1_CANDIDATES:
            with self.subTest(candidate=candidate):
                self.assertIn(candidate, text)
        self.assertIn("no Python interpreter found", text)
        self.assertIn("exit 2", text)

    def test_the_posix_launcher_names_every_candidate(self):
        text = read(CANONICAL_SH)
        for candidate in SH_CANDIDATES:
            with self.subTest(candidate=candidate):
                self.assertIn(candidate, text)
        self.assertIn("no Python interpreter found", text)
        self.assertIn("exit 2", text)

    def test_both_canonical_launchers_forward_to_serve(self):
        for path in (CANONICAL_PS1, CANONICAL_SH):
            with self.subTest(path=path.name):
                text = read(path)
                self.assertIn("rt_state.py", text)
                self.assertIn("--serve", text)

    def test_neither_canonical_launcher_decides_anything_about_ports(self):
        # The port probe, the holding PID and the already-running verdict are
        # rt_state.py's, where the offline suite reaches them. A launcher that
        # re-decided any of it would be untestable PowerShell.
        for path in (CANONICAL_PS1, CANONICAL_SH):
            with self.subTest(path=path.name):
                text = read(path).lower()
                for forbidden in ("netstat", "test-netconnection", "lsof",
                                  "already running"):
                    self.assertNotIn(forbidden, text)


class PosixLauncherRefusal(unittest.TestCase):
    """The refusal, executed. A string match proves neither the exit code nor
    the message, and those two ARE the refusal."""

    def setUp(self):
        self.bash = find_git_bash()
        if not self.bash:
            self.skipTest("no non-WSL bash found; the POSIX launcher is sh")
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tree = Path(self._tmp.name)
        # A fixture tree with the real depth, so the launcher's own
        # ../../../.. resolves, and with NO .venv-skills, so the real one
        # cannot satisfy the search by accident.
        self.scripts = (self.tree / "clone" / ".claude" / "skills"
                        / "rt-observe" / "scripts")
        self.scripts.mkdir(parents=True)
        shutil.copy2(CANONICAL_SH, self.scripts / "rt-dashboard.sh")
        (self.scripts / "rt_state.py").write_text(
            "import sys\nprint('MODULE ' + ' '.join(sys.argv[1:]))\n",
            encoding="utf-8")
        self.empty_bin = self.tree / "emptybin"
        self.empty_bin.mkdir()

    def _run(self, path_value, args=()):
        env = dict(os.environ)
        env["PATH"] = path_value
        return subprocess.run(
            [self.bash, str(self.scripts / "rt-dashboard.sh")] + list(args),
            capture_output=True, text=True, env=env, timeout=60)

    def test_with_no_interpreter_it_refuses_and_names_what_it_tried(self):
        done = self._run(str(self.empty_bin))
        self.assertEqual(2, done.returncode, done.stdout + done.stderr)
        self.assertIn("no Python interpreter found", done.stderr)
        for candidate in ("bin/python", "Scripts/python.exe", "python3"):
            with self.subTest(candidate=candidate):
                self.assertIn(candidate, done.stderr)

    def test_it_never_guesses_an_interpreter_it_did_not_find(self):
        done = self._run(str(self.empty_bin))
        self.assertNotIn("MODULE", done.stdout)

    def test_with_an_interpreter_present_it_forwards_serve_and_the_rest(self):
        """The positive control. Without it every assertion above would pass on
        a launcher that refuses unconditionally."""
        fake = self.empty_bin / "python3"
        fake.write_text('#!/usr/bin/env sh\nexec "%s" "$@"\n'
                        % Path(sys.executable).as_posix(), encoding="utf-8")
        fake.chmod(fake.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP
                   | stat.S_IXOTH)
        done = self._run(str(self.empty_bin), args=["--dry-run", "--port", "9"])
        self.assertEqual(0, done.returncode, done.stdout + done.stderr)
        self.assertIn("MODULE --serve --dry-run --port 9", done.stdout)

    def test_a_launcher_with_no_module_beside_it_refuses(self):
        (self.scripts / "rt_state.py").unlink()
        done = self._run(str(self.empty_bin))
        self.assertEqual(2, done.returncode)
        self.assertIn("rt_state.py is not beside this launcher", done.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
