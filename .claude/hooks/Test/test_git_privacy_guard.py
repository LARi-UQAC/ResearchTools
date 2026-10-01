"""
test_git_privacy_guard - the global git privacy guard (.claude/hooks/git/).

Why it exists. Measured 2026-10-01: the PUBLIC repository carried an account name,
a machine path, code-permanent-shaped values, student emails and a real name, in
current files and in history. Nothing ran at commit time; the only check
(verify-no-personal-data.ps1) was manual and red. The guard is a betterleaks rules
file used by a global pre-commit hook and by the privacy-scan CI workflow.

Offline, no network. Every git call runs with GIT_CONFIG_GLOBAL pointed at a
scratch file and GIT_CONFIG_NOSYSTEM set, so the operator's real global config
(which holds core.hooksPath once installed) is never read or written. The
betterleaks cases skip when the binary is absent; the static cases always run.
Expected duration: about 30 seconds (each git commit spawns the hook and betterleaks).
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HOOKS = Path(__file__).resolve().parents[1] / "git"
REPO = Path(__file__).resolve().parents[3]
RULES = HOOKS / "privacy-rules.toml"
WORKFLOW = REPO / ".github" / "workflows" / "privacy-scan.yml"
RULE_IDS = ("windows-home-account", "posix-home-account", "quebec-code-permanent",
            "uqac-student-email", "frq-identifier")


def find_betterleaks():
    """
    --------------------------------------------------------------------------
    Purpose:
        Locate the betterleaks binary the hook itself would find.

    Inputs:
        None

    Outputs:
        path (str or None): the executable, or None when not installed
    --------------------------------------------------------------------------
    """
    found = shutil.which("betterleaks")
    if found:
        return found
    packages = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Packages"
    for candidate in packages.glob("Betterleaks*/betterleaks.exe"):
        return str(candidate)
    return None


BETTERLEAKS = find_betterleaks()


def isolated_env(tmp, **extra):
    """Environment for a git call that never touches the real global or system config."""
    cfg = Path(tmp) / "gitconfig"
    cfg.touch()
    env = dict(os.environ, GIT_CONFIG_GLOBAL=str(cfg), GIT_CONFIG_NOSYSTEM="1")
    env.update(extra)
    return env


def run(cmd, cwd, env):
    """Run a command with a 60 s timeout (R10); return the CompletedProcess."""
    return subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True, timeout=60)


SAMPLE_HITS = {
    "windows-home-account": "path C:\\Users\\jdoe\\.config\\x",
    "posix-home-account": "home /home/jdoe/projects",
    "quebec-code-permanent": "code ABCD12345678 here",
    "uqac-student-email": "mail jane.doe@etu.uqac.ca",
    "frq-identifier": "frq QWERT5678 id",
}
SAMPLE_CLEAN = (
    "placeholder C:\\Users\\x\\.claude C:\\Users\\someone\\bin C:/Users/<you>/ {{HOME}}/x\n"
    "home /home/user/x\n"
    "code XXXX000000 XXXX12345678\n"
    "frq XXXYY1234 ABCDE1234\n"
    "allowed C:\\Users\\jdoe\\x betterleaks:allow\n"
)


class StaticContract(unittest.TestCase):
    """The files agree with each other; runs with no binary at all."""

    def test_rules_file_declares_every_rule_and_extends_the_defaults(self):
        text = RULES.read_text(encoding="utf-8")
        for rule_id in RULE_IDS:
            self.assertIn('id = "%s"' % rule_id, text)
        self.assertRegex(text, r"(?m)^\[extend\]\s*\nuseDefault = true")

    def test_rules_file_parses_as_toml(self):
        try:
            import tomllib
        except ImportError:
            self.skipTest("tomllib needs Python 3.11+")
        data = tomllib.loads(RULES.read_text(encoding="utf-8"))
        self.assertEqual(sorted(r["id"] for r in data["rules"]), sorted(RULE_IDS))

    def test_workflow_points_at_the_rules_file_that_exists(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        rel = RULES.relative_to(REPO).as_posix()
        self.assertIn(rel, text)
        self.assertTrue(RULES.is_file())

    def test_workflow_pins_actions_by_sha_and_the_binary_by_checksum(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        code = "\n".join(l for l in text.splitlines() if not l.lstrip().startswith("#"))
        uses = re.findall(r"uses:\s*([^\s#]+)", code)
        self.assertTrue(uses)
        for ref in uses:
            self.assertRegex(ref, r"@[0-9a-f]{40}$", ref)
        self.assertRegex(text, r"\b[0-9a-f]{64}\s+bl\.tgz")

    def test_shell_scripts_have_no_carriage_return(self):
        # Git's sh fails with '\r: command not found' on a CRLF hook.
        for name in ("pre-commit", "_chain"):
            self.assertNotIn(b"\r", (HOOKS / name).read_bytes(), name)


@unittest.skipUnless(BETTERLEAKS, "betterleaks not installed")
class RulesDetect(unittest.TestCase):
    """Each rule fires on its sample and stays silent on placeholders."""

    def scan(self, content):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "sample.txt").write_text(content, encoding="utf-8")
            report = Path(tmp) / "r.json"
            run([BETTERLEAKS, "dir", "--no-banner", "--redact", "--config", str(RULES),
                 "--report-format", "json", "--report-path", str(report), str(tmp)],
                tmp, isolated_env(tmp))
            return [f["RuleID"] for f in (json.loads(report.read_text(encoding="utf-8")) or [])]

    def test_each_rule_catches_its_sample(self):
        for rule_id, line in SAMPLE_HITS.items():
            with self.subTest(rule=rule_id):
                self.assertIn(rule_id, self.scan(line + "\n"))

    def test_placeholders_and_the_allow_marker_pass(self):
        self.assertEqual(self.scan(SAMPLE_CLEAN), [])


@unittest.skipUnless(shutil.which("git"), "git not installed")
class HookEndToEnd(unittest.TestCase):
    """Real commits in a scratch repository whose local core.hooksPath is a copy of the hooks."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.hooks = Path(self.tmp) / "hooks"
        self.hooks.mkdir()
        for name in ("pre-commit", "privacy-rules.toml"):
            shutil.copy(HOOKS / name, self.hooks / name)
        shutil.copy(HOOKS / "_chain", self.hooks / "post-commit")
        self.repo = Path(self.tmp) / "repo"
        self.repo.mkdir()
        self.env = isolated_env(self.tmp, USERNAME="zqacct", USER="zqacct")
        for cmd in (["git", "init", "-q", "."],
                    ["git", "config", "user.email", "t@example.org"],
                    ["git", "config", "user.name", "t"],
                    ["git", "config", "core.hooksPath", self.hooks.as_posix()]):
            run(cmd, self.repo, self.env)

    def commit(self, content, name="f.txt"):
        (self.repo / name).write_text(content, encoding="utf-8")
        run(["git", "add", name], self.repo, self.env)
        return run(["git", "commit", "-qm", "t"], self.repo, self.env)

    def repo_hook(self, name, marker):
        hook = self.repo / ".git" / "hooks" / name
        hook.write_text("#!/bin/sh\necho ran > '%s'\n" % (self.repo / marker).as_posix(),
                        encoding="utf-8", newline="\n")
        hook.chmod(0o755)

    def test_clean_commit_passes_and_chains_the_repository_hooks(self):
        self.repo_hook("pre-commit", "pre.marker")
        self.repo_hook("post-commit", "post.marker")
        result = self.commit("nothing personal here\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.repo / "pre.marker").exists(), "repository pre-commit not chained")
        self.assertTrue((self.repo / "post.marker").exists(), "repository post-commit not chained")

    def test_account_name_is_refused_without_echoing_the_line(self):
        result = self.commit("secret line zqacct here\n", name="notes.txt")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("notes.txt", result.stderr)
        self.assertNotIn("secret line", result.stderr)

    def test_allow_marker_lets_a_deliberate_line_through(self):
        result = self.commit("zqacct betterleaks:allow\n")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_opt_out_lets_a_private_repository_through(self):
        run(["git", "config", "privacyguard.enabled", "false"], self.repo, self.env)
        result = self.commit("zqacct C:\\Users\\jdoe\\x\n")
        self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipUnless(BETTERLEAKS, "betterleaks not installed")
    def test_personal_data_shape_is_refused(self):
        result = self.commit("config C:\\Users\\jdoe\\.config\\x\n")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("privacy guard", result.stderr)


POWERSHELL = shutil.which("powershell") or shutil.which("pwsh")


@unittest.skipUnless(POWERSHELL and shutil.which("git"), "PowerShell or git not installed")
class Installer(unittest.TestCase):
    """install-git-hooks.ps1 against a scratch global config, never the real one."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.env = isolated_env(self.tmp)
        self.target = Path(self.tmp) / "hooks"

    def install(self, *args):
        return run([POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                    str(HOOKS / "install-git-hooks.ps1"), "-Target", str(self.target), *args],
                   self.tmp, self.env)

    def global_hooks_path(self):
        return run(["git", "config", "--global", "--get", "core.hooksPath"], self.tmp, self.env).stdout.strip()

    def test_dry_run_changes_nothing(self):
        result = self.install("-DryRun")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(self.target.exists())
        self.assertEqual(self.global_hooks_path(), "")

    def test_install_copies_the_hooks_and_sets_core_hooks_path(self):
        result = self.install()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        for name in ("pre-commit", "privacy-rules.toml", "pre-push", "commit-msg"):
            self.assertTrue((self.target / name).is_file(), name)
        self.assertEqual(Path(self.global_hooks_path()), self.target)

    def test_another_hooks_path_is_refused_not_overwritten(self):
        run(["git", "config", "--global", "core.hooksPath", "C:/other/hooks"], self.tmp, self.env)
        result = self.install()
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertEqual(self.global_hooks_path(), "C:/other/hooks")
        self.assertFalse(self.target.exists())


if __name__ == "__main__":
    unittest.main()
