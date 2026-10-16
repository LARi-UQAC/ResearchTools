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
import re
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

# What each canonical launcher must carry, kept here as the contract rather than
# parsed out of the script, so a launcher that quietly drops a candidate fails
# instead of agreeing with itself. The PowerShell launcher no longer lists
# candidates itself: scripts/lib/rt-venv.ps1 owns that decision (R18) and its own
# verify script proves it, so here the launcher must USE the helper and expose the
# explicit opt-in to PATH (R8). The POSIX launcher has no helper and lists both
# venv layouts, and names PATH only behind --allow-path-fallback.
PS1_MUST_CONTAIN = ("rt-venv.ps1", "Resolve-RtVenvPython", "AllowPathFallback")
SH_CANDIDATES = (".venv-skills/bin/python", ".venv-skills/Scripts/python.exe",
                 "git-common-dir", "--allow-path-fallback")


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

    def test_the_root_powershell_wrapper_forwards_the_interpreter_switches(self):
        """Code-review finding: the refusal tells the user to pass -AllowPathFallback or
        -Python, so the root wrapper has to declare them, or they land in -Rest and the
        documented remedy never works from the repository root."""
        text = read(ROOT_PS1)
        self.assertRegex(text, r"\[switch\]\$AllowPathFallback")
        self.assertRegex(text, r"\[string\]\$Python")

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
        for needle in PS1_MUST_CONTAIN:
            with self.subTest(needle=needle):
                self.assertIn(needle, text)
        self.assertIn("no Python interpreter found", text)
        self.assertIn("exit 2", text)

    def test_the_powershell_launcher_keeps_no_interpreter_search_of_its_own(self):
        # R18, the negative half: the old private copy joined the venv path and
        # then fell through to PATH. Neither may come back here.
        text = re.sub(r"<#.*?#>", "", read(CANONICAL_PS1), flags=re.S)
        code = "\n".join(line for line in text.splitlines()
                         if not line.lstrip().startswith("#"))
        self.assertNotIn(".venv-skills", code)
        self.assertNotIn("Get-Command", code)

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
        # cannot satisfy the search by accident. The folder name holds a space
        # on purpose: the candidate list is newline-separated text, and a
        # launcher that split it on blanks would break on this machine's own
        # clone path.
        self.scripts = (self.tree / "my clone" / ".claude" / "skills"
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

    def _stub(self, path, body=None):
        """An executable shell stub standing in for an interpreter: it runs
        this suite's own Python, so rt_state.py's stand-in executes for real."""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body or '#!/usr/bin/env sh\nexec "%s" "$@"\n'
                        % Path(sys.executable).as_posix(), encoding="utf-8")
        path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP
                   | stat.S_IXOTH)

    def test_with_no_interpreter_it_refuses_and_names_what_it_tried(self):
        done = self._run(str(self.empty_bin))
        self.assertEqual(2, done.returncode, done.stdout + done.stderr)
        self.assertIn("no Python interpreter found", done.stderr)
        for candidate in ("bin/python", "Scripts/python.exe",
                          "setup.ps1 -InstallPython", "--allow-path-fallback"):
            with self.subTest(candidate=candidate):
                self.assertIn(candidate, done.stderr)

    def test_it_never_guesses_an_interpreter_it_did_not_find(self):
        done = self._run(str(self.empty_bin))
        self.assertNotIn("MODULE", done.stdout)

    def test_a_python_on_path_is_refused_without_the_explicit_flag(self):
        """R8, the case that hid the 2026-10-06 loss for a week: a python on
        PATH must NOT be taken when the environment is absent."""
        self._stub(self.empty_bin / "python3")
        done = self._run(str(self.empty_bin), args=["--dry-run"])
        self.assertEqual(2, done.returncode, done.stdout + done.stderr)
        self.assertNotIn("MODULE", done.stdout)
        self.assertIn("no Python interpreter found", done.stderr)

    def test_with_the_flag_a_path_python_is_used_and_said(self):
        """The positive control. Without it every assertion above would pass on
        a launcher that refuses unconditionally."""
        self._stub(self.empty_bin / "python3")
        done = self._run(str(self.empty_bin),
                         args=["--allow-path-fallback", "--dry-run", "--port", "9"])
        self.assertEqual(0, done.returncode, done.stdout + done.stderr)
        self.assertIn("MODULE --serve --dry-run --port 9", done.stdout)
        self.assertNotIn("--allow-path-fallback", done.stdout)
        self.assertIn("from PATH", done.stderr)

    def test_the_flag_is_honoured_in_any_position_and_order_is_kept(self):
        """Code-review finding: it used to work only as the first argument, unlike the
        PowerShell launcher, and otherwise leaked to rt_state.py."""
        self._stub(self.empty_bin / "python3")
        done = self._run(str(self.empty_bin),
                         args=["--open", "--allow-path-fallback", "--port", "9"])
        self.assertEqual(0, done.returncode, done.stdout + done.stderr)
        self.assertIn("MODULE --serve --open --port 9", done.stdout)
        self.assertNotIn("allow-path-fallback", done.stdout)

    def test_the_flag_with_no_python_anywhere_still_refuses(self):
        done = self._run(str(self.empty_bin), args=["--allow-path-fallback"])
        self.assertEqual(2, done.returncode, done.stdout + done.stderr)
        self.assertIn("none found", done.stderr)

    def test_an_own_environment_is_used_and_forwards_serve_and_the_rest(self):
        clone = self.scripts.parents[3]
        self._stub(clone / ".venv-skills" / "bin" / "python")
        done = self._run(str(self.empty_bin), args=["--dry-run", "--port", "9"])
        self.assertEqual(0, done.returncode, done.stdout + done.stderr)
        self.assertIn("MODULE --serve --dry-run --port 9", done.stdout)

    def test_a_worktree_reaches_the_main_environment_with_no_link(self):
        """The 2026-10-06 cause, closed: a linked worktree finds the main
        clone's environment through git's common directory, by absolute path,
        and nothing is linked into the worktree."""
        git = shutil.which("git")
        if not git:
            self.skipTest("git is not installed")
        main = self.tree / "main clone"
        wt = self.tree / "linked tree"
        main.mkdir()
        base = [git, "-C", str(main), "-c", "user.name=Fictitious",
                "-c", "user.email=fictitious@example.org"]
        for args in (["init", "--quiet"],
                     ["commit", "--quiet", "--allow-empty", "-m", "init"],
                     ["worktree", "add", "--quiet", "--detach", str(wt)]):
            done = subprocess.run(base + args, capture_output=True, text=True,
                                  timeout=60)
            self.assertEqual(0, done.returncode, done.stderr)
        scripts = (wt / ".claude" / "skills" / "rt-observe" / "scripts")
        scripts.mkdir(parents=True)
        shutil.copy2(CANONICAL_SH, scripts / "rt-dashboard.sh")
        (scripts / "rt_state.py").write_text(
            "import sys\nprint('MODULE ' + ' '.join(sys.argv[1:]))\n",
            encoding="utf-8")
        self._stub(main / ".venv-skills" / "bin" / "python")
        env = dict(os.environ)
        # git must be reachable (the launcher asks it for the common dir) but
        # no python may be: the environment, not PATH, has to be what answers.
        env["PATH"] = os.pathsep.join([str(self.empty_bin),
                                       str(Path(git).parent)])
        done = subprocess.run(
            [self.bash, str(scripts / "rt-dashboard.sh"), "--dry-run"],
            capture_output=True, text=True, env=env, timeout=60)
        self.assertEqual(0, done.returncode, done.stdout + done.stderr)
        self.assertIn("MODULE --serve --dry-run", done.stdout)
        self.assertFalse((wt / ".venv-skills").exists(),
                         "the launcher must not create a link in the worktree")

    def test_a_launcher_with_no_module_beside_it_refuses(self):
        (self.scripts / "rt_state.py").unlink()
        done = self._run(str(self.empty_bin))
        self.assertEqual(2, done.returncode)
        self.assertIn("rt_state.py is not beside this launcher", done.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
