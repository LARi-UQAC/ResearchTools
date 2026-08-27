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

if __name__ == "__main__":
    unittest.main(verbosity=2)
