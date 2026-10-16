"""
test_worktree_link_guard - the PreToolUse gate on `git worktree remove` (R37).

Offline. No network, no git, no model. Every behavioural case runs the REAL hook as a
subprocess against a COPY of it in a temporary directory, so the exit code and the stderr a
refused call would produce are what is asserted, and so the R11 cases (a missing or broken
config) can be staged at all, since the hook reads its settings from a file beside itself.

The links are REAL: a Windows junction made with `mklink /J` in a temporary folder, because the
whole point of the gate is a reparse point that a naive directory walk would follow. The hook
only reads; one case asserts that the junction's target is untouched after a refusal and after a
pass. Folder names are fictitious (R34). The case this was written for is reproduced from a
measurement taken 2026-10-16: `git worktree remove` followed an ignored junction and emptied its
target, so the refusal must not depend on `--force`.

R21: no setting is read from the machine. Every case injects its own fixture config; the one
case that reads the SHIPPED config asserts only that it parses and carries the keys the hook
consults.

R20: both directions are asserted - the refusals, and the passes without which a gate that
refuses everything would look correct (a clean worktree, a link already removed, another git
verb, another tool, a path the hook cannot resolve).
"""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
HOOK = REPO / ".claude" / "hooks" / "worktree-link-guard.py"
SHIPPED_CONFIG = REPO / ".claude" / "hooks" / "worktree-link-guard.json"
TEMPLATE = REPO / ".claude" / "settings.template.json"
CONFIG_NAME = "worktree-link-guard.json"

FIXTURE_CONFIG = {"enabled": True, "max_entries": 5000}
WINDOWS = os.name == "nt"


def load_module():
    """Import the hook by path (its file name holds a hyphen)."""
    spec = importlib.util.spec_from_file_location("worktree_link_guard", HOOK)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def make_junction(link, target):
    """Create a directory junction; skip the test when the platform cannot."""
    if not WINDOWS:
        raise unittest.SkipTest("junctions exist on Windows only")
    done = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)],
                          capture_output=True, text=True, timeout=30)
    if done.returncode != 0:
        raise unittest.SkipTest("mklink /J unavailable: " + done.stdout + done.stderr)


def run_hook(payload, config=FIXTURE_CONFIG, write_config=True, raw_config=None, stdin=None,
             env=None):
    """
    --------------------------------------------------------------------------
    Purpose:
        Run the real hook against a copy of itself with its config staged
        beside it (or deliberately absent or broken).

    Inputs:
        payload (dict): the PreToolUse stdin payload
        config (dict): settings written next to the copied hook
        write_config (bool): False stages no config, for the R11 case
        raw_config (str): raw text written instead of JSON
        stdin (str): raw stdin text replacing the JSON payload

    Outputs:
        result (tuple): (returncode int, stderr str)
    --------------------------------------------------------------------------
    """
    with tempfile.TemporaryDirectory() as tmp:
        copied = Path(tmp) / HOOK.name
        copied.write_bytes(HOOK.read_bytes())
        if write_config:
            text = raw_config if raw_config is not None else json.dumps(config)
            (Path(tmp) / CONFIG_NAME).write_text(text, encoding="utf-8")
        done = subprocess.run(
            [sys.executable, str(copied)],
            input=stdin if stdin is not None else json.dumps(payload),
            capture_output=True, text=True, timeout=60,
            env=None if env is None else dict(os.environ, **env))
    return done.returncode, done.stderr


def bash(command, cwd=None, tool="Bash"):
    """A PreToolUse payload for a shell command."""
    payload = {"tool_name": tool, "tool_input": {"command": command}}
    if cwd is not None:
        payload["cwd"] = str(cwd)
    return payload


class Tree(unittest.TestCase):
    """A fictitious main-clone environment and a worktree holding a junction to it."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.env = self.root / "alpha-env"
        (self.env / "Scripts").mkdir(parents=True)
        (self.env / "pyvenv.cfg").write_text("x", encoding="utf-8")
        (self.env / "Scripts" / "python.exe").write_text("x", encoding="utf-8")
        self.worktree = self.root / "my worktree"
        self.worktree.mkdir()
        (self.worktree / "readme.txt").write_text("x", encoding="utf-8")
        self.link = self.worktree / ".venv-skills"

    def linked(self):
        """Create the junction once; a second call in the same test is a no-op, so a
        loop of sub-cases is not skipped by mklink refusing an existing link."""
        if not os.path.lexists(self.link):
            make_junction(self.link, self.env)

    def target_intact(self):
        return ((self.env / "pyvenv.cfg").exists()
                and (self.env / "Scripts" / "python.exe").exists())


class RefusesAWorktreeHoldingALink(Tree):

    def test_a_plain_remove_is_refused_with_no_force(self):
        """The measured case: the junction is ignored by git, no --force is needed."""
        self.linked()
        code, err = run_hook(bash('git worktree remove "%s"' % self.worktree))
        self.assertEqual(2, code, err)
        self.assertIn("WORKTREE LINK GUARD", err)
        self.assertIn(str(self.link), err)
        self.assertIn("alpha-env", err)

    def test_the_refusal_gives_the_command_that_removes_only_the_link(self):
        self.linked()
        _, err = run_hook(bash('git worktree remove "%s"' % self.worktree))
        self.assertIn('cmd /c rmdir "%s"' % self.link, err)

    def test_force_is_refused_too(self):
        self.linked()
        code, _ = run_hook(bash('git worktree remove --force "%s"' % self.worktree))
        self.assertEqual(2, code)
        code, _ = run_hook(bash('git worktree remove "%s" -f' % self.worktree))
        self.assertEqual(2, code)

    def test_the_target_is_untouched_by_the_hook(self):
        self.linked()
        run_hook(bash('git worktree remove "%s"' % self.worktree))
        self.assertTrue(self.target_intact(), "the hook must only read")

    def test_a_link_nested_deeper_is_found(self):
        (self.worktree / "deep" / "er").mkdir(parents=True)
        self.link = self.worktree / "deep" / "er" / "env"
        self.linked()
        code, err = run_hook(bash('git worktree remove "%s"' % self.worktree))
        self.assertEqual(2, code, err)
        self.assertIn(str(self.link), err)

    def test_other_spellings_of_the_same_command(self):
        self.linked()
        spellings = [
            'rtk git worktree remove "%s"' % self.worktree,
            'git.exe worktree remove "%s"' % self.worktree,
            "git worktree remove '%s'" % self.worktree,
            'cd C:\\ && git worktree remove "%s"' % self.worktree,
            'echo done; git -c core.quotepath=off worktree remove "%s"' % self.worktree,
            'git worktree remove -- "%s"' % self.worktree,
        ]
        for command in spellings:
            with self.subTest(command=command):
                code, err = run_hook(bash(command))
                self.assertEqual(2, code, err)

    def test_dash_c_and_a_relative_path_resolve_together(self):
        self.linked()
        command = 'git -C "%s" worktree remove "my worktree"' % self.root
        code, err = run_hook(bash(command))
        self.assertEqual(2, code, err)

    def test_a_cd_earlier_in_the_line_moves_the_relative_path(self):
        """Code-review finding: `cd X && git worktree remove rel` used to resolve `rel`
        against the payload cwd, find nothing, and let the removal through."""
        self.linked()
        elsewhere = self.root.parent
        for command in ('cd "%s" && git worktree remove "my worktree"' % self.root,
                        'Set-Location "%s"; git worktree remove "my worktree"' % self.root,
                        'pushd "%s"; git worktree remove "my worktree"' % self.root,
                        'cd "%s"; cd "my worktree/.."; git worktree remove "my worktree"'
                        % self.root):
            with self.subTest(command=command):
                code, err = run_hook(bash(command, cwd=elsewhere))
                self.assertEqual(2, code, err)

    def test_a_tilde_path_is_expanded_like_the_shell_would(self):
        """Code-review finding: `git worktree remove ~/x` resolved to <cwd>/~/x, which does
        not exist, so the guard passed the removal of a worktree holding a link."""
        self.linked()
        home = {"USERPROFILE": str(self.root), "HOME": str(self.root)}
        for command in ('git worktree remove ~/"my worktree"',
                        'git worktree remove "~/my worktree"'):
            with self.subTest(command=command):
                code, err = run_hook(bash(command, cwd=self.root.parent), env=home)
                self.assertEqual(2, code, err)
        # Control: without the expansion the same path is not found and passes, so the
        # refusal above is the tilde handling and not the fixture.
        code, _ = run_hook(bash('git worktree remove "~/my worktree"', cwd=self.root.parent),
                           env={"USERPROFILE": str(self.root.parent / "nowhere"),
                                "HOME": str(self.root.parent / "nowhere")})
        self.assertEqual(0, code)

    def test_a_worktree_path_that_is_itself_a_link_is_refused(self):
        """The scan would follow the junction and see only its target's contents."""
        self.linked()
        alias = self.root / "alias-to-worktree"
        make_junction(alias, self.worktree)
        # a clean target: remove the inner link so only the ROOT is a link
        subprocess.run(["cmd", "/c", "rmdir", str(self.link)], capture_output=True, timeout=30)
        code, err = run_hook(bash('git worktree remove "%s"' % alias))
        self.assertEqual(2, code, err)
        self.assertIn("alias-to-worktree", err)
        self.assertTrue(self.worktree.exists(), "the hook must only read")

    def test_a_subshell_cd_is_followed(self):
        """Security-review note: `(cd X; git worktree remove rel)` was not followed."""
        self.linked()
        code, err = run_hook(bash('(cd "%s"; git worktree remove "my worktree")' % self.root,
                                  cwd=self.root.parent))
        self.assertEqual(2, code, err)

    def test_a_cd_into_the_worktree_itself_then_a_dot_path(self):
        self.linked()
        code, err = run_hook(bash('cd "%s" && git worktree remove .' % self.worktree,
                                  cwd=self.root.parent))
        self.assertEqual(2, code, err)

    def test_an_unresolvable_cd_hides_relative_paths_but_not_absolute_ones(self):
        """The stated limit: after `cd $dir` a relative path cannot be judged (passes),
        while an absolute path still is."""
        self.linked()
        relative = run_hook(bash('cd $dir && git worktree remove "my worktree"',
                                 cwd=self.root))
        self.assertEqual(0, relative[0], relative[1])
        absolute = run_hook(bash('cd $dir && git worktree remove "%s"' % self.worktree,
                                 cwd=self.root.parent))
        self.assertEqual(2, absolute[0], absolute[1])

    def test_a_relative_path_resolves_against_the_payload_cwd(self):
        self.linked()
        code, err = run_hook(bash('git worktree remove "my worktree"', cwd=self.root))
        self.assertEqual(2, code, err)

    def test_the_powershell_tool_is_judged_like_bash(self):
        self.linked()
        code, _ = run_hook(bash('git worktree remove "%s"' % self.worktree, tool="PowerShell"))
        self.assertEqual(2, code)

    @unittest.skipUnless(WINDOWS, "the /c/ drive spelling is translated on Windows only")
    def test_a_git_bash_drive_spelling_is_translated(self):
        self.linked()
        posix = "/" + str(self.worktree)[0].lower() + str(self.worktree)[2:].replace("\\", "/")
        code, err = run_hook(bash('git worktree remove "%s"' % posix))
        self.assertEqual(2, code, err)

    def test_a_scan_that_cannot_finish_is_refused_not_passed(self):
        """A link could hide in the part never reached, so an incomplete scan refuses."""
        for index in range(40):
            (self.worktree / ("file%02d.txt" % index)).write_text("x", encoding="utf-8")
        code, err = run_hook(bash('git worktree remove "%s"' % self.worktree),
                             config={"enabled": True, "max_entries": 5})
        self.assertEqual(2, code, err)
        self.assertIn("without finishing", err)
        self.assertIn("max_entries", err)


class AllowsWhatIsNotTheCase(Tree):

    def test_a_clean_worktree_passes(self):
        code, err = run_hook(bash('git worktree remove "%s"' % self.worktree))
        self.assertEqual(0, code, err)
        self.assertEqual("", err)

    def test_once_the_link_is_removed_the_same_command_passes(self):
        """The remedy works, and removing the link leaves the target alone."""
        self.linked()
        self.assertEqual(2, run_hook(bash('git worktree remove "%s"' % self.worktree))[0])
        done = subprocess.run(["cmd", "/c", "rmdir", str(self.link)],
                              capture_output=True, text=True, timeout=30)
        self.assertEqual(0, done.returncode, done.stderr)
        self.assertTrue(self.target_intact(), "rmdir on a junction must keep its target")
        code, err = run_hook(bash('git worktree remove "%s"' % self.worktree))
        self.assertEqual(0, code, err)

    def test_another_git_verb_passes_even_with_a_link(self):
        self.linked()
        for command in ('git worktree list', 'git worktree prune',
                        'git worktree add "%s" -b x' % self.worktree,
                        'git status "%s"' % self.worktree,
                        'rm -rf "%s"' % self.worktree):
            with self.subTest(command=command):
                self.assertEqual(0, run_hook(bash(command))[0])

    def test_another_tool_passes(self):
        self.linked()
        payload = bash('git worktree remove "%s"' % self.worktree, tool="Read")
        self.assertEqual(0, run_hook(payload)[0])

    def test_a_path_the_hook_cannot_resolve_passes(self):
        """The stated limit: a variable or substitution cannot be judged here."""
        self.linked()
        for command in ('git worktree remove $wt', 'git worktree remove "$(pwd)/x"',
                        'git worktree remove %WT%', 'git worktree remove `pwd`'):
            with self.subTest(command=command):
                self.assertEqual(0, run_hook(bash(command))[0])

    def test_a_path_that_does_not_exist_passes(self):
        code, _ = run_hook(bash('git worktree remove "%s"' % (self.root / "no-such")))
        self.assertEqual(0, code)

    def test_a_command_with_no_path_passes(self):
        self.assertEqual(0, run_hook(bash("git worktree remove"))[0])

    def test_a_payload_that_is_not_ours_passes(self):
        for stdin in ("", "not json", "[]", json.dumps({"tool_name": "Bash"}),
                      json.dumps({"tool_name": "Bash", "tool_input": "x"}),
                      json.dumps({"tool_name": "Bash", "tool_input": {"command": 5}})):
            with self.subTest(stdin=stdin):
                self.assertEqual(0, run_hook(None, stdin=stdin)[0])


class FailsSilentlyWhenItsOwnDependencyIsAbsent(Tree):
    """R11: a hook that cannot do its job stays quiet; it never refuses a tool for that."""

    def refused_without(self, **kwargs):
        self.linked()
        return run_hook(bash('git worktree remove "%s"' % self.worktree), **kwargs)

    def test_a_missing_config_disables_the_gate(self):
        self.assertEqual((0, ""), self.refused_without(write_config=False))

    def test_an_unparsable_config_disables_the_gate(self):
        self.assertEqual((0, ""), self.refused_without(raw_config="{not json"))

    def test_a_disabled_gate_passes(self):
        self.assertEqual((0, ""), self.refused_without(
            config={"enabled": False, "max_entries": 100}))

    def test_a_bad_limit_disables_the_gate(self):
        for bad in (0, -1, "many", None, True, 1.5):
            with self.subTest(limit=bad):
                self.assertEqual((0, ""), self.refused_without(
                    config={"enabled": True, "max_entries": bad}))

    def test_the_positive_control_the_same_staging_refuses(self):
        """Without this, every case above would pass on a hook that refuses nothing."""
        code, _ = self.refused_without()
        self.assertEqual(2, code)


class Parsing(unittest.TestCase):
    """The command parser on its own, imported, for the shapes a subprocess case is too slow for."""

    @classmethod
    def setUpClass(cls):
        cls.module = load_module()

    def paths(self, command, base="C:\\base" if WINDOWS else "/base"):
        return self.module.find_removals(command, base)

    def test_a_quoted_path_with_a_space_is_one_token(self):
        out = self.paths('git worktree remove "C:\\a b\\wt"')
        self.assertEqual([os.path.normpath("C:\\a b\\wt")], out)

    def test_each_command_of_a_compound_line_is_judged(self):
        out = self.paths("git worktree remove one && git worktree remove two")
        self.assertEqual(2, len(out))

    def test_a_separator_inside_quotes_does_not_split(self):
        self.assertEqual(1, len(self.paths('git worktree remove "a;b"')))

    def test_options_are_not_taken_for_the_path(self):
        out = self.paths("git worktree remove --force -f wt")
        self.assertEqual([os.path.normpath(os.path.join(
            "C:\\base" if WINDOWS else "/base", "wt"))], out)

    def test_another_verb_yields_nothing(self):
        self.assertEqual([], self.paths("git worktree add wt"))
        self.assertEqual([], self.paths("git status"))
        self.assertEqual([], self.paths("worktree remove wt"))

    def test_a_variable_path_yields_nothing(self):
        self.assertEqual([], self.paths("git worktree remove $wt"))

    def test_cd_moves_the_base_and_a_later_cd_is_relative_to_the_earlier_one(self):
        base = "C:\\base" if WINDOWS else "/base"
        out = self.paths("cd one && cd two && git worktree remove wt", base)
        self.assertEqual([os.path.normpath(os.path.join(base, "one", "two", "wt"))], out)

    def test_a_cd_after_the_removal_does_not_move_it(self):
        base = "C:\\base" if WINDOWS else "/base"
        out = self.paths("git worktree remove wt && cd elsewhere", base)
        self.assertEqual([os.path.normpath(os.path.join(base, "wt"))], out)


class ShippedFiles(unittest.TestCase):

    def test_the_hook_compiles_with_every_warning_as_an_error(self):
        """Code-review finding: an invalid escape such as backslash-space in the docstring
        raises a SyntaxWarning on Python 3.12+, written to stderr on EVERY call, which breaks
        the silence R11 requires and becomes a SyntaxError in a later release. Python 3.11
        only warns under -W, so the check forces it."""
        for path in (HOOK, Path(__file__)):
            with self.subTest(path=path.name):
                done = subprocess.run(
                    [sys.executable, "-W", "error", "-c",
                     "import pathlib, sys; compile(pathlib.Path(sys.argv[1]).read_text(encoding='utf-8'), sys.argv[1], 'exec')",
                     str(path)],
                    capture_output=True, text=True, timeout=60)
                self.assertEqual(0, done.returncode, done.stderr)

    def test_the_warning_check_can_fail(self):
        """Control: the same check rejects a file with an invalid escape."""
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "bad.py"
            bad.write_text('"""a\\ b"""\n', encoding="utf-8")
            done = subprocess.run(
                [sys.executable, "-W", "error", "-c",
                 "import pathlib, sys; compile(pathlib.Path(sys.argv[1]).read_text(encoding='utf-8'), sys.argv[1], 'exec')",
                 str(bad)], capture_output=True, text=True, timeout=60)
        self.assertNotEqual(0, done.returncode)

    def test_the_shipped_config_parses_and_carries_the_keys_the_hook_reads(self):
        config = json.loads(SHIPPED_CONFIG.read_text(encoding="utf-8"))
        self.assertIs(True, config["enabled"])
        self.assertIsInstance(config["max_entries"], int)
        self.assertGreater(config["max_entries"], 0)
        self.assertIsNotNone(load_module().load_config(str(SHIPPED_CONFIG.parent)))

    def test_the_template_declares_the_hook_on_both_shell_tools(self):
        """Without this declaration the gate is written and never runs."""
        template = json.loads(TEMPLATE.read_text(encoding="utf-8"))
        found = [entry for entry in template["hooks"]["PreToolUse"]
                 if any("worktree-link-guard.py" in hook.get("command", "")
                        for hook in entry["hooks"])]
        self.assertEqual(1, len(found))
        matcher = found[0]["matcher"].split("|")
        self.assertIn("Bash", matcher)
        self.assertIn("PowerShell", matcher)
        self.assertEqual(2, len(matcher), "the gate must stay narrow: shell tools only")


if __name__ == "__main__":
    unittest.main(verbosity=2)
