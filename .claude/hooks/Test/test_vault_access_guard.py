"""
Offline tests for the vault-access-guard PreToolUse hook.

No Obsidian process, no network, no model. The vault root is forced through OBSIDIAN_VAULT so the
tests never depend on this machine's real vault. What is pinned here is the decision itself: the
main session is refused every path form, local-writer is exempt, and file CONTENT carrying the
vault path is not mistaken for a vault access.
"""

import importlib.util
import json
import io
import os
import sys
import unittest
from contextlib import redirect_stderr

HOOK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "vault-access-guard.py")
_spec = importlib.util.spec_from_file_location("vault_access_guard", HOOK)
guard = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(guard)

VAULT = "D:/Fixture Vault"
BACKSLASH = chr(92)


def run_hook(payload):
    """Feed a payload to the hook's main() and return (exit_code, stderr)."""
    stdin = sys.stdin
    sys.stdin = io.StringIO(json.dumps(payload))
    buffer = io.StringIO()
    try:
        with redirect_stderr(buffer):
            code = guard.main()
    finally:
        sys.stdin = stdin
    return code, buffer.getvalue()


class VaultAccessGuardTest(unittest.TestCase):
    def setUp(self):
        self._saved = os.environ.get("OBSIDIAN_VAULT")
        os.environ["OBSIDIAN_VAULT"] = VAULT
        # Precondition: the fixture vault, not the real one, is what the guard will match on.
        self.assertIn("fixture vault", " ".join(guard.vault_needles()))

    def tearDown(self):
        if self._saved is None:
            os.environ.pop("OBSIDIAN_VAULT", None)
        else:
            os.environ["OBSIDIAN_VAULT"] = self._saved

    def test_read_inside_vault_is_blocked(self):
        code, err = run_hook({
            "tool_name": "Read",
            "tool_input": {"file_path": "D:/Fixture Vault/30_Ressources/Python/note.md"},
        })
        self.assertEqual(code, 2)
        self.assertIn("local-writer", err)

    def test_windows_backslash_form_is_blocked(self):
        path = "D:" + BACKSLASH + "Fixture Vault" + BACKSLASH + "10_Projets" + BACKSLASH + "x.md"
        code, _ = run_hook({"tool_name": "Read", "tool_input": {"file_path": path}})
        self.assertEqual(code, 2)

    def test_git_bash_drive_form_is_blocked(self):
        code, _ = run_hook({
            "tool_name": "Bash",
            "tool_input": {"command": 'cat "/d/Fixture Vault/90_Archives/old.md"'},
        })
        self.assertEqual(code, 2)

    def test_bash_grep_over_vault_is_blocked(self):
        code, _ = run_hook({
            "tool_name": "Bash",
            "tool_input": {"command": 'grep -rn "torque" "D:/Fixture Vault"'},
        })
        self.assertEqual(code, 2)

    def test_environment_variable_reference_is_blocked(self):
        code, _ = run_hook({
            "tool_name": "Bash",
            "tool_input": {"command": 'ls "$OBSIDIAN_VAULT/30_Ressources"'},
        })
        self.assertEqual(code, 2)

    def test_local_writer_is_exempt(self):
        code, err = run_hook({
            "tool_name": "Read",
            "agent_type": "local-writer",
            "agent_id": "abc123",
            "tool_input": {"file_path": "D:/Fixture Vault/30_Ressources/Python/note.md"},
        })
        self.assertEqual(code, 0)
        self.assertEqual(err, "")

    def test_another_subagent_is_not_exempt(self):
        code, _ = run_hook({
            "tool_name": "Read",
            "agent_type": "local-coder",
            "tool_input": {"file_path": "D:/Fixture Vault/30_Ressources/Python/note.md"},
        })
        self.assertEqual(code, 2)

    def test_path_outside_vault_passes(self):
        code, _ = run_hook({
            "tool_name": "Read",
            "tool_input": {"file_path": "C:/Martin Otis/OutilsLogiciels/ResearchTools/README.md"},
        })
        self.assertEqual(code, 0)

    def test_outbox_is_not_the_vault(self):
        code, _ = run_hook({
            "tool_name": "Write",
            "tool_input": {"file_path": "C:/Users/x/.claude/obsidian-outbox/note.md"},
        })
        self.assertEqual(code, 0)

    def test_vault_path_in_file_content_is_not_an_access(self):
        # Documenting the vault path inside a repo file must stay possible.
        code, _ = run_hook({
            "tool_name": "Write",
            "tool_input": {
                "file_path": "C:/repo/docs/notes.md",
                "content": "The vault lives at D:/Fixture Vault and is read by local-writer.",
            },
        })
        self.assertEqual(code, 0)

    def test_unguarded_tool_passes(self):
        code, _ = run_hook({
            "tool_name": "WebFetch",
            "tool_input": {"url": "https://example.org/D:/Fixture Vault"},
        })
        self.assertEqual(code, 0)

    def test_malformed_payload_never_blocks(self):
        stdin = sys.stdin
        sys.stdin = io.StringIO("not json at all")
        try:
            self.assertEqual(guard.main(), 0)
        finally:
            sys.stdin = stdin


class PowerShellToolTest(unittest.TestCase):
    """The PowerShell tool is a separate tool name, so it needs its own entry in the matcher.
    Registering the guard without it left a live bypass on 2026-08-27, found by using it."""

    def setUp(self):
        self._saved = os.environ.get("OBSIDIAN_VAULT")
        os.environ["OBSIDIAN_VAULT"] = VAULT

    def tearDown(self):
        if self._saved is None:
            os.environ.pop("OBSIDIAN_VAULT", None)
        else:
            os.environ["OBSIDIAN_VAULT"] = self._saved

    def test_powershell_copy_into_vault_is_blocked(self):
        code, err = run_hook({
            "tool_name": "PowerShell",
            "tool_input": {"command": 'Copy-Item x.md "D:/Fixture Vault/30_Ressources/x.md"'},
        })
        self.assertEqual(code, 2)
        self.assertIn("local-writer", err)

    def test_powershell_outside_vault_passes(self):
        code, _ = run_hook({
            "tool_name": "PowerShell",
            "tool_input": {"command": "Get-ChildItem C:/repo"},
        })
        self.assertEqual(code, 0)

    def test_powershell_is_exempt_for_local_writer(self):
        code, _ = run_hook({
            "tool_name": "PowerShell",
            "agent_type": "local-writer",
            "tool_input": {"command": 'Get-Content "D:/Fixture Vault/x.md"'},
        })
        self.assertEqual(code, 0)



class GraphAccessGuardTest(unittest.TestCase):
    """
    The graph arm, added 2026-08-30 after local-writer was bypassed in three separate sessions.

    The vault half of this guard was enforced from 2026-08-27; the graph half was prose in
    .claude/CLAUDE.md and was not. What makes the graph different, and what these cases pin, is
    that a bypass does not have to name the graph at all: the last one ran a read-only audit
    script twice to learn the graph's state, and `graphify-out` never appeared in the command.
    So the script names are guarded too - but in an executed COMMAND only, never in a path
    argument, or maintaining those scripts would become impossible for everyone but local-writer.
    """

    def test_reading_graph_json_is_blocked(self):
        code, err = run_hook({
            "tool_name": "Read",
            "tool_input": {"file_path": "graphify-out/graph.json"},
        })
        self.assertEqual(code, 2)
        self.assertIn("GRAPH GUARD", err)

    def test_windows_form_of_the_graph_path_is_blocked(self):
        code, _ = run_hook({
            "tool_name": "Bash",
            "tool_input": {"command": "type C:" + BACKSLASH + "repo" + BACKSLASH +
                                      "graphify-out" + BACKSLASH + "graph.json"},
        })
        self.assertEqual(code, 2)

    def test_graphify_cli_is_blocked(self):
        code, err = run_hook({
            "tool_name": "Bash",
            "tool_input": {"command": "graphify update ."},
        })
        self.assertEqual(code, 2)
        self.assertIn("graphify (CLI)", err)

    def test_graphify_cli_after_a_chain_operator_is_blocked(self):
        # The bypass is trivial otherwise: prefix the call with a cd and it sails through.
        for command in ("cd /repo && graphify update scripts/lib",
                        "ls | graphify query foo",
                        "echo hi; graphify explain bar"):
            with self.subTest(command=command):
                code, _ = run_hook({"tool_name": "Bash", "tool_input": {"command": command}})
                self.assertEqual(code, 2)

    def test_the_word_graphify_in_prose_is_not_an_access(self):
        # The negative control that keeps the guard usable. Matching the bare word would refuse
        # every grep of the documentation, and a guard that fires on prose gets switched off.
        for command in ("grep -n 'graphify' .gitignore",
                        "rtk grep graphify README.md",
                        "echo 'the graphify skill is vendored here'"):
            with self.subTest(command=command):
                code, _ = run_hook({"tool_name": "Bash", "tool_input": {"command": command}})
                self.assertEqual(code, 0)

    def test_reading_the_vendored_skill_is_not_an_access(self):
        # .claude/skills/graphify/ is the SKILL, not the graph. Guarding the bare word would
        # make the instructions for using the graph unreadable, which is self-defeating.
        code, _ = run_hook({
            "tool_name": "Read",
            "tool_input": {"file_path": ".claude/skills/graphify/SKILL.md"},
        })
        self.assertEqual(code, 0)

    def test_running_check_graph_health_is_blocked(self):
        # The actual 2026-08-30 bypass, in both spellings that were used.
        for command in (r"& .\scripts\audit\check-graph-health.ps1",
                        r"powershell -File .\scripts\audit\check-graph-health.ps1"):
            with self.subTest(command=command):
                code, err = run_hook({"tool_name": "PowerShell",
                                      "tool_input": {"command": command}})
                self.assertEqual(code, 2)
                self.assertIn("check-graph-health.ps1", err)

    def test_running_verify_graph_health_is_blocked(self):
        code, _ = run_hook({
            "tool_name": "PowerShell",
            "tool_input": {"command": r".\scripts\test\verify-graph-health.ps1"},
        })
        self.assertEqual(code, 2)

    def test_editing_an_audit_script_is_not_an_access(self):
        # The asymmetry that makes the script names safe to guard: running one reads the graph,
        # maintaining one does not. Guarding the path key too would lock the repository's own
        # audit scripts behind an agent that has no business owning them.
        for tool in ("Edit", "Read", "Write"):
            with self.subTest(tool=tool):
                code, _ = run_hook({
                    "tool_name": tool,
                    "tool_input": {"file_path": "scripts/audit/check-graph-health.ps1"},
                })
                self.assertEqual(code, 0)

    def test_local_writer_is_exempt_from_the_graph_arm(self):
        code, _ = run_hook({
            "tool_name": "Bash",
            "tool_input": {"command": "graphify update ."},
            "agent_type": "local-writer",
        })
        self.assertEqual(code, 0)

    def test_another_subagent_is_not_exempt_from_the_graph_arm(self):
        code, _ = run_hook({
            "tool_name": "Bash",
            "tool_input": {"command": "graphify query foo"},
            "agent_type": "local-coder",
        })
        self.assertEqual(code, 2)

    def test_graph_path_in_file_content_is_not_an_access(self):
        # Same contract as the vault arm: content is never scanned, so documenting the graph
        # stays possible with Write and Edit.
        code, _ = run_hook({
            "tool_name": "Write",
            "tool_input": {"file_path": "docs/notes.md",
                           "content": "The graph lives in graphify-out/graph.json."},
        })
        self.assertEqual(code, 0)

    def test_unrelated_command_passes(self):
        code, _ = run_hook({
            "tool_name": "Bash",
            "tool_input": {"command": "python -m pytest"},
        })
        self.assertEqual(code, 0)

    def test_the_two_arms_report_separately(self):
        # A vault hit and a graph hit must not print the same message, or the reader is sent to
        # the wrong remedy. Both route to local-writer, but for different reasons.
        saved = os.environ.get("OBSIDIAN_VAULT")
        os.environ["OBSIDIAN_VAULT"] = VAULT
        try:
            _, vault_err = run_hook({
                "tool_name": "Read",
                "tool_input": {"file_path": VAULT + "/note.md"},
            })
            _, graph_err = run_hook({
                "tool_name": "Read",
                "tool_input": {"file_path": "graphify-out/graph.json"},
            })
        finally:
            if saved is None:
                os.environ.pop("OBSIDIAN_VAULT", None)
            else:
                os.environ["OBSIDIAN_VAULT"] = saved
        self.assertIn("VAULT GUARD", vault_err)
        self.assertNotIn("GRAPH GUARD", vault_err)
        self.assertIn("GRAPH GUARD", graph_err)
        self.assertNotIn("VAULT GUARD", graph_err)


if __name__ == "__main__":
    unittest.main(verbosity=2)
