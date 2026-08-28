"""
Offline tests for the session-hooks-inventory SessionStart hook.

No settings file of this machine is ever read: every case injects its own dict, and the
existence predicate is injected too, so the suite passes on a machine with no ~/.claude at
all (R21). What is pinned here is the reason the hook exists - a declared hook whose script
is gone must be NAMED, since that is the 2026-08-27 failure that cost four turns - plus the
determinism the inventory needs to be trustworthy across two consecutive sessions.
"""

import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

HOOK = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "session-hooks-inventory.py"
)
_spec = importlib.util.spec_from_file_location("session_hooks_inventory", HOOK)
inv = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(inv)

PRESENT = lambda path: True  # noqa: E731 - injected predicate, deliberately trivial
ABSENT = lambda path: False  # noqa: E731


def entry(command, **extra):
    hook = {"type": "command", "command": command}
    hook.update(extra)
    return hook


def settings(**events):
    return {"hooks": {name: groups for name, groups in events.items()}}


def group(*hooks, **kwargs):
    out = {"hooks": list(hooks)}
    if "matcher" in kwargs:
        out["matcher"] = kwargs["matcher"]
    return out


class BuildInventoryTest(unittest.TestCase):
    def test_header_counts_entries_and_events(self):
        data = settings(
            SessionStart=[group(entry('python "C:/h/a.py"'), entry('python "C:/h/b.py"'))],
            SessionEnd=[group(entry('python "C:/h/a.py"'))],
        )
        lines = inv.build_inventory(data, script_exists=PRESENT)
        self.assertEqual(lines[0], "[HOOKS ACTIVE] 3 entries / 2 events")

    def test_one_line_per_event_with_labels(self):
        data = settings(
            PreToolUse=[
                group(entry('python "C:/h/betterleaks-hook.py"'), matcher="Write|Edit"),
                group(entry('python "C:/h/vault-access-guard.py"'), matcher="Bash|Read"),
            ]
        )
        lines = inv.build_inventory(data, script_exists=PRESENT)
        self.assertEqual(
            lines[1], "PreToolUse(2): betterleaks-hook.py | vault-access-guard.py"
        )

    def test_canonical_event_order_is_not_declaration_order(self):
        # SessionEnd is declared first but must be rendered last.
        data = {
            "hooks": {
                "SessionEnd": [group(entry('python "C:/h/z.py"'))],
                "SessionStart": [group(entry('python "C:/h/a.py"'))],
            }
        }
        lines = inv.build_inventory(data, script_exists=PRESENT)
        self.assertTrue(lines[1].startswith("SessionStart("))
        self.assertTrue(lines[2].startswith("SessionEnd("))

    def test_unknown_event_is_reported_not_dropped(self):
        data = settings(ZzzFutureEvent=[group(entry('python "C:/h/a.py"'))])
        lines = inv.build_inventory(data, script_exists=PRESENT)
        self.assertEqual(lines[1], "ZzzFutureEvent(1): a.py")

    def test_inline_hook_labelled_by_its_bracket_tag(self):
        data = settings(
            SessionStart=[group(entry('echo "[AUTO-SYNC CHECK] branch=main"'))]
        )
        lines = inv.build_inventory(data, script_exists=PRESENT)
        self.assertEqual(lines[1], "SessionStart(1): auto-sync-check")

    def test_inline_hook_falls_back_to_status_message(self):
        data = settings(
            SessionStart=[group(entry("rtk_st=$(command -v rtk)", statusMessage="Checking RTK..."))]
        )
        lines = inv.build_inventory(data, script_exists=PRESENT)
        self.assertEqual(lines[1], "SessionStart(1): checking-rtk")

    def test_interpreter_exe_is_not_taken_for_the_script(self):
        data = settings(
            UserPromptSubmit=[
                group(entry('"C:/Program Files/nodejs/node.exe" "C:/h/caveman-mode-tracker.js"'))
            ]
        )
        lines = inv.build_inventory(data, script_exists=PRESENT)
        self.assertEqual(lines[1], "UserPromptSubmit(1): caveman-mode-tracker.js")

    def test_prose_filename_after_a_statement_break_is_not_the_script(self):
        # The real Stop hook: an inline shell command whose echoed reason mentions
        # Decisions.md and model_resolver.py. Measured 2026-08-28, scanning the whole
        # command made that prose the label AND reported it as a missing file.
        command = (
            "if grep -q 'stop_hook_active'; then exit 0; fi; "
            "echo '{\"reason\": \"[memory upkeep] append to Decisions.md instead. "
            "Never name a model tag: model_resolver.py refuses.\"}'"
        )
        data = settings(Stop=[group(entry(command))])
        lines = inv.build_inventory(data, script_exists=ABSENT)
        self.assertEqual(lines[1], "Stop(1): memory-upkeep")
        self.assertFalse(any("[HOOKS ALERT]" in line for line in lines))

    def test_quoted_semicolon_after_the_script_still_yields_the_script(self):
        # The install-junctions entry: its ';' sits inside the quoted -Command string,
        # after the .ps1, so the head still carries the real path.
        command = (
            "powershell -NoProfile -Command \"if (Test-Path "
            "'C:/Martin Otis/ResearchTools/install-junctions.ps1') "
            "{ & 'C:/Martin Otis/ResearchTools/install-junctions.ps1' -Sync }; exit 0\""
        )
        data = settings(SessionStart=[group(entry(command))])
        lines = inv.build_inventory(data, script_exists=PRESENT)
        self.assertEqual(lines[1], "SessionStart(1): install-junctions.ps1")

    def test_bare_relative_script_name_is_treated_as_inline(self):
        data = settings(SessionStart=[group(entry('python hook.py', statusMessage="Local..."))])
        lines = inv.build_inventory(data, script_exists=ABSENT)
        self.assertEqual(lines[1], "SessionStart(1): local")
        self.assertFalse(any("[HOOKS ALERT]" in line for line in lines))

    # --- failure paths (R20) -------------------------------------------------

    def test_missing_script_produces_the_alert_line(self):
        data = settings(PreToolUse=[group(entry('python "C:/h/vault-access-guard.py"'))])
        lines = inv.build_inventory(data, script_exists=ABSENT)
        self.assertIn("[HOOKS ALERT]", lines[-1])
        self.assertIn("vault-access-guard.py (PreToolUse)", lines[-1])
        self.assertIn("REFUSED", lines[-1])

    def test_no_alert_line_when_every_script_is_present(self):
        data = settings(PreToolUse=[group(entry('python "C:/h/a.py"'))])
        lines = inv.build_inventory(data, script_exists=PRESENT)
        self.assertFalse(any("[HOOKS ALERT]" in line for line in lines))

    def test_unsubstituted_template_placeholder_is_not_reported_missing(self):
        # settings.template.json ships {{USERPROFILE}}; its absence on disk proves nothing.
        data = settings(PreToolUse=[group(entry('python "{{USERPROFILE}}/.claude/hooks/a.py"'))])
        lines = inv.build_inventory(data, script_exists=ABSENT)
        self.assertFalse(any("[HOOKS ALERT]" in line for line in lines))

    def test_inline_hook_never_reported_missing(self):
        data = settings(SessionStart=[group(entry('echo "[RTK ACTIVE] ok"'))])
        lines = inv.build_inventory(data, script_exists=ABSENT)
        self.assertFalse(any("[HOOKS ALERT]" in line for line in lines))

    def test_malformed_settings_yield_no_output_and_no_exception(self):
        for bad in (None, [], "hooks", 7, {}, {"hooks": None}, {"hooks": {}}):
            self.assertEqual(inv.build_inventory(bad, script_exists=PRESENT), [])

    def test_malformed_group_and_hook_entries_are_skipped(self):
        data = {"hooks": {"SessionStart": ["not-a-dict", {"hooks": ["not-a-dict"]}]}}
        self.assertEqual(inv.build_inventory(data, script_exists=PRESENT), [])

    def test_output_is_deterministic_across_two_runs(self):
        data = settings(
            SessionStart=[group(entry('python "C:/h/a.py"'), entry('echo "[RTK ACTIVE] x"'))],
            Stop=[group(entry("md5sum", statusMessage="memory upkeep..."))],
        )
        first = inv.build_inventory(data, script_exists=PRESENT)
        second = inv.build_inventory(data, script_exists=PRESENT)
        self.assertEqual(first, second)


class MainTest(unittest.TestCase):
    def _run_main(self, settings_file):
        previous = os.environ.get(inv.SETTINGS_ENV_VAR)
        os.environ[inv.SETTINGS_ENV_VAR] = settings_file
        buffer = io.StringIO()
        try:
            with redirect_stdout(buffer):
                code = inv.main()
        finally:
            if previous is None:
                os.environ.pop(inv.SETTINGS_ENV_VAR, None)
            else:
                os.environ[inv.SETTINGS_ENV_VAR] = previous
        return code, buffer.getvalue()

    def test_missing_settings_file_is_silent_and_exits_zero(self):
        code, out = self._run_main(os.path.join(tempfile.gettempdir(), "no-such-settings.json"))
        self.assertEqual(code, 0)
        self.assertEqual(out, "")

    def test_unparsable_settings_file_is_silent_and_exits_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "settings.json")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("{ not json")
            code, out = self._run_main(path)
        self.assertEqual(code, 0)
        self.assertEqual(out, "")

    def test_inventory_is_written_to_stdout(self):
        # The whole point: stderr never reaches the session context.
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "settings.json")
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(settings(SessionStart=[group(entry('echo "[RTK ACTIVE] x"'))]), handle)
            code, out = self._run_main(path)
        self.assertEqual(code, 0)
        self.assertIn("[HOOKS ACTIVE] 1 entries / 1 events", out)
        self.assertIn("SessionStart(1): rtk-active", out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
