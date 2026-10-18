"""
Offline suite for the "memory is silent" contract (plan4 of the docs-site-links effort).

The owner reported, 2026-10-17, a lot of useless chat output from memory reads and writes through
`local-writer`. Read and measured the same day: the Stop hook of `.claude/settings.template.json`
injected a reminder of about 1900 characters each time the working tree changed, and each
injection forced one more turn; the `local-writer` definition asked for a report at the end of
every run. The contract now is: on success, one short line and no narration, on failure, the full
account. The shipped Stop command is run for real in temporary repositories (no vault is read, no
agent is called), with fictitious data (R34) and no machine-local file (R21).

Proves the texts and the hook output. Does not prove that a live session prints less: that needs
the owner's synced settings and a real session (R15).
"""

import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_settings_template_distribution import find_git_bash, template  # noqa: E402

REPO = Path(__file__).resolve().parents[3]
AGENT = REPO / ".claude" / "agents" / "local-writer.md"
# Chosen 2026-10-17 by the author of plan4: the reminder measured about 1900 characters before
# this change, and the dispatch instruction with its permission and bound needs far less.
MAX_REASON_CHARS = 800
MAX_STATUS_CHARS = 24
GIT_TIMEOUT_S = 60
OLD_SENTENCE = "Finally, check whether the project CLAUDE.md should reflect anything structural"


def narration_banned(reason: str) -> bool:
    """True when the reminder tells the session not to narrate and to show an answer only on failure."""
    return "Do not narrate" in reason and "unless it reports a failure" in reason


def stop_command() -> str:
    """The shipped Stop hook command of the settings template."""
    return template()["hooks"]["Stop"][0]["hooks"][0]["command"]


def fire(bash: str, with_graph: bool) -> dict:
    """
    --------------------------------------------------------------------------
    Purpose:
        Run the shipped Stop command in a temporary git repository whose working tree changed,
        so the hook fires, and return the JSON it prints.

    Inputs:
        bash (str): path of Git Bash.
        with_graph (bool): create a graphify-out directory so the graph variant is chosen.

    Outputs:
        decision (dict): the parsed hook output.
    --------------------------------------------------------------------------
    """
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "repo"
        agents = Path(tmp) / "cfg" / "agents"
        root.mkdir()
        agents.mkdir(parents=True)
        (agents / "local-writer.md").write_text("stub", encoding="utf-8")
        subprocess.run(["git", "init", "-q", str(root)], check=True, timeout=GIT_TIMEOUT_S)
        (root / "a.txt").write_text("a", encoding="utf-8")
        if with_graph:
            (root / "graphify-out").mkdir()
        env = dict(os.environ)
        env["CLAUDE_CONFIG_DIR"] = str(Path(tmp) / "cfg")
        env["CLAUDE_PROJECT_DIR"] = str(root)
        env["CLAUDE_CODE_GIT_BASH_PATH"] = bash
        done = subprocess.run(
            [bash, "-c", stop_command()], input='{"session_id": "s-test"}',
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=GIT_TIMEOUT_S, env=env,
        )
    return json.loads(done.stdout)


class StopReminder(unittest.TestCase):
    def setUp(self):
        self.bash = find_git_bash()
        if not self.bash:
            self.skipTest("Git Bash not found; the shipped hook declares shell=bash")

    def test_both_variants_block_with_valid_json(self):
        for with_graph in (False, True):
            out = fire(self.bash, with_graph)
            self.assertEqual("block", out["decision"])
            self.assertIn("[memory upkeep]", out["reason"])
            self.assertIn("local-writer", out["reason"])

    def test_reminder_forbids_narration_in_both_variants(self):
        for with_graph in (False, True):
            self.assertTrue(narration_banned(fire(self.bash, with_graph)["reason"]))

    def test_reminder_is_short(self):
        for with_graph in (False, True):
            reason = fire(self.bash, with_graph)["reason"]
            self.assertLessEqual(len(reason), MAX_REASON_CHARS, len(reason))

    def test_reminder_keeps_permission_and_bound(self):
        for with_graph in (False, True):
            reason = fire(self.bash, with_graph)["reason"]
            self.assertIn("standing-permitted", reason)
            self.assertIn("ONE agent", reason)
            self.assertIn("fan-out", reason)

    def test_graph_clause_only_when_a_graph_exists(self):
        self.assertIn("graphify update", fire(self.bash, True)["reason"])
        self.assertNotIn("graphify", fire(self.bash, False)["reason"])

    def test_graph_variant_refreshes_from_the_repository_root_even_with_no_lesson(self):
        reason = fire(self.bash, True)["reason"]
        self.assertIn("repository root", reason)
        self.assertIn("still refresh the graph", reason)
        self.assertNotIn("graphify update on the changed paths", reason)

    def test_the_plain_variant_names_no_note_to_skip_the_graph(self):
        self.assertIn("write no note", fire(self.bash, False)["reason"])

    def test_the_entry_keeps_the_identity_the_settings_merge_uses(self):
        # Merge-RtGlobalSettings recognises a hook by the first script name in its command
        # (rt-global-config.ps1, Get-RtHookToken). The live entry carries model_resolver.py, so a
        # command without it would be added as a SECOND Stop entry beside the old one.
        first = re.search(r"[\w.\-]+\.(py|ps1|js|mjs|cjs)", stop_command())
        self.assertIsNotNone(first)
        self.assertEqual("model_resolver.py", first.group(0))

    def test_old_wording_is_gone(self):
        self.assertNotIn(OLD_SENTENCE, stop_command())


class Texts(unittest.TestCase):
    def test_status_message_is_short_and_names_no_agent(self):
        message = template()["hooks"]["Stop"][0]["hooks"][0]["statusMessage"]
        self.assertLessEqual(len(message), MAX_STATUS_CHARS, message)
        self.assertNotIn("local-writer", message)

    def test_local_writer_returns_one_line_on_success(self):
        text = AGENT.read_text(encoding="utf-8")
        self.assertIn("on success in one line", text)

    def test_local_writer_still_reports_failure_in_full(self):
        text = AGENT.read_text(encoding="utf-8")
        self.assertIn("a failure in full", text)
        for case in ("refused command", "parked drop", "held lock", "not seen on disk"):
            self.assertIn(case, text)
        self.assertIn("### Verify the write before reporting it", text)

    def test_the_old_report_rule_is_gone(self):
        text = AGENT.read_text(encoding="utf-8")
        self.assertNotIn("Report at the end of every run", text)

    def test_finder_negative_controls(self):
        self.assertFalse(narration_banned("[memory upkeep] Route it to local-writer. " + OLD_SENTENCE))
        self.assertFalse(narration_banned("Do not narrate the dispatch."))
        self.assertTrue(narration_banned(
            "Do not narrate. Show its answer unless it reports a failure."))


if __name__ == "__main__":
    unittest.main()
