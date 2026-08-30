"""
test_settings_template_distribution - what a SECOND machine actually receives.

Offline. Reads repository files and, for one case, runs the shipped Stop hook's
own command in a scratch environment. It never reads or writes the live
~/.claude, and it invokes no git: the one bash case is arranged so the hook
returns at its first guard, before it reaches a git call.

Why it exists. Measured 2026-08-30: `~/.claude/skills/graphify` and
`~/.claude/skills/tech-debt` were REAL directories rather than junctions, so
`install-junctions.ps1` did not manage them and `check-deployment.ps1` could not
see them. Every other skill here is a junction into this repository. The result
was a clone - a colleague's machine, or a claude.ai routine - that received
`local-writer` with instructions to consult the code graph and no graphify skill
to consult, with nothing reporting the absence. The Stop memory-upkeep hook and
the `GRAPHIFY_*` values were in the same position: present in one machine's
`~/.claude/settings.json`, absent from `settings.template.json`, therefore
undistributed.

The distribution rule that governs the hook half is the one already written in
the global CLAUDE.md: a hook that ships must exit 0 and say nothing when its own
dependency is absent (R11). The Stop hook's entire instruction is "dispatch
local-writer", so on a machine with no such agent it could only block a turn to
ask for something impossible. That guard is asserted here in both directions.
"""
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
TEMPLATE = REPO / ".claude" / "settings.template.json"
SKILLS = REPO / ".claude" / "skills"

# Skills that were hand-installed on one machine and are now vendored. Named
# rather than discovered: their ABSENCE is the defect, and a discovered list
# cannot report something that is not there.
VENDORED = ("graphify", "tech-debt")

FRONTMATTER = re.compile(r"(?s)\A---\r?\n(.*?)\r?\n---")
KEY = re.compile(r"(?m)^(name|description)\s*:")


def template():
    return json.loads(TEMPLATE.read_text(encoding="utf-8"))


def find_git_bash():
    """The bash the hook will actually run under, which is NOT the first one on
    PATH.

    Measured while writing this suite: `shutil.which("bash")` resolves to
    C:\\Windows\\System32\\bash.exe, the WSL launcher, which answered
    `execvpe(/bin/bash) failed: No such file or directory` and exit 1 for every
    case here. A test that had trusted that result would have reported the
    shipped guard as broken when the guard was fine. Claude Code itself is told
    which bash to use, through CLAUDE_CODE_GIT_BASH_PATH, so that is the first
    place to look.
    """
    configured = os.environ.get("CLAUDE_CODE_GIT_BASH_PATH")
    if configured and Path(configured).is_file():
        return configured
    for candidate in (r"C:\Program Files\Git\bin\bash.exe",
                      Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Git" / "bin" / "bash.exe"):
        if Path(candidate).is_file():
            return str(candidate)
    found = shutil.which("bash")
    if found and "system32" not in found.lower():
        return found
    return None


class TestVendoredSkillsAreInTheRepository(unittest.TestCase):
    def test_each_vendored_skill_is_present(self):
        for name in VENDORED:
            with self.subTest(skill=name):
                self.assertTrue(
                    (SKILLS / name / "SKILL.md").is_file(),
                    f"{name} exists only in one machine's ~/.claude/skills; a clone "
                    "gets instructions to use it and no way to reach it",
                )

    def test_each_vendored_skill_declares_name_and_description(self):
        # install-junctions.ps1 and the Codex mirror both read these two keys.
        # A skill whose frontmatter does not parse is installed and unusable.
        for name in VENDORED:
            with self.subTest(skill=name):
                text = (SKILLS / name / "SKILL.md").read_text(encoding="utf-8")
                m = FRONTMATTER.match(text)
                self.assertIsNotNone(m, f"{name}/SKILL.md has no frontmatter block")
                keys = set(KEY.findall(m.group(1)))
                self.assertEqual({"name", "description"}, keys,
                                 f"{name}/SKILL.md must declare name and description")

    def test_every_skill_directory_carries_a_skill_file(self):
        # The general form of the same rule, so the next vendoring cannot land
        # half-done without being noticed.
        missing = sorted(d.name for d in SKILLS.iterdir()
                         if d.is_dir() and not (d / "SKILL.md").is_file())
        self.assertEqual([], missing)

    def test_the_finder_can_fail(self):
        # Negative control: a check that cannot fail is not a check.
        with tempfile.TemporaryDirectory() as tmp:
            self.assertFalse((Path(tmp) / "graphify" / "SKILL.md").is_file())


class TestTemplateCarriesTheMemoryLayer(unittest.TestCase):
    def test_graphify_env_keys_are_declared(self):
        env = template()["env"]
        # These must live in Claude Code's env, not the registry: graphify runs
        # as a CHILD of Claude Code and sends its own keep_alive in every request
        # body, which overrides whatever default the daemon was started with.
        self.assertIn("GRAPHIFY_OLLAMA_KEEP_ALIVE", env)
        self.assertIn("GRAPHIFY_OLLAMA_NUM_CTX", env)

    def test_ollama_daemon_keys_are_NOT_shipped_here(self):
        # The mirror image, and the trap the global CLAUDE.md records: the Ollama
        # daemon is started by its tray application at login and never sees
        # Claude Code's environment, so an OLLAMA_* key placed here would look
        # configured and do nothing. It belongs in the user registry, and the
        # README says so.
        env = template()["env"]
        stray = sorted(k for k in env if k.startswith("OLLAMA_"))
        self.assertEqual([], stray)

    def test_the_stop_upkeep_hook_is_declared(self):
        hooks = template()["hooks"]
        self.assertIn("Stop", hooks, "the memory-upkeep nudge reaches no other machine")
        cmd = hooks["Stop"][0]["hooks"][0]["command"]
        self.assertIn("[memory upkeep]", cmd)
        self.assertIn("local-writer", cmd)

    def test_the_stop_hook_states_the_standing_permission(self):
        cmd = template()["hooks"]["Stop"][0]["hooks"][0]["command"]
        self.assertIn("standing-permitted", cmd)
        # And its bound, which is the half that keeps it from reading as licence
        # for a parallel fan-out of agents.
        self.assertIn("fan-out", cmd)

    def test_the_stop_hook_names_no_machine_path(self):
        cmd = template()["hooks"]["Stop"][0]["hooks"][0]["command"]
        self.assertNotIn(":\\", cmd)
        self.assertNotIn(os.environ.get("USERNAME", "\x00nope"), cmd)

    def test_the_dependency_guard_precedes_every_git_call(self):
        # Order is the mechanism, not a preference: a guard placed after the
        # first git invocation would already have run git on a machine the hook
        # has no business acting on.
        cmd = template()["hooks"]["Stop"][0]["hooks"][0]["command"]
        guard = cmd.index("agents/local-writer.md")
        first_git = cmd.index("git ")
        self.assertLess(guard, first_git,
                        "the local-writer guard must come before the first git call")


class TestTheShippedGuardActuallyGuards(unittest.TestCase):
    """Runs the hook's own command. Arranged to return at the first guard, so
    no git call is made by this suite."""

    def setUp(self):
        self.bash = find_git_bash()
        if not self.bash:
            self.skipTest("Git Bash not found; the shipped hook declares shell=bash")
        self.cmd = template()["hooks"]["Stop"][0]["hooks"][0]["command"]

    def _run(self, config_dir):
        env = dict(os.environ)
        env["CLAUDE_CONFIG_DIR"] = str(config_dir)
        return subprocess.run([self.bash, "-c", self.cmd], input="{}",
                              capture_output=True, text=True, timeout=30, env=env)

    def test_no_local_writer_means_silence_and_exit_0(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "agents").mkdir()
            proc = self._run(tmp)
            self.assertEqual(0, proc.returncode)
            self.assertEqual("", proc.stdout.strip(),
                             "a hook whose dependency is absent must say nothing (R11)")

    def test_the_guard_can_be_satisfied(self):
        # Negative control for the case above: with the agent file present the
        # hook gets PAST the guard. It then meets its stop_hook_active guard,
        # which is fed here deliberately so the run still stops before git.
        with tempfile.TemporaryDirectory() as tmp:
            agents = Path(tmp) / "agents"
            agents.mkdir()
            (agents / "local-writer.md").write_text("stub", encoding="utf-8")
            env = dict(os.environ)
            env["CLAUDE_CONFIG_DIR"] = str(tmp)
            env["CLAUDE_CODE_GIT_BASH_PATH"] = self.bash
            proc = subprocess.run([self.bash, "-c", self.cmd],
                                  input='{"stop_hook_active": true}',
                                  capture_output=True, text=True, timeout=30, env=env)
            self.assertEqual(0, proc.returncode)
            self.assertEqual("", proc.stdout.strip())


if __name__ == "__main__":
    unittest.main(verbosity=2)
