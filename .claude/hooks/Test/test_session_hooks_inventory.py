"""
Offline tests for the session-hooks-inventory SessionStart hook.

No settings file of this machine is ever read: every case injects its own dict, and the
existence predicate is injected too, so the suite passes on a machine with no ~/.claude at
all (R21). What is pinned here is the reason the hook exists - a declared hook whose script
is gone must be NAMED, since that is the 2026-08-27 failure that cost four turns - the
per-hook status a reader needs to act on it, the display directive without which the block
reaches the model and never the person, and the determinism the inventory needs to be
trustworthy across two consecutive sessions.
"""

import importlib.util
import io
import json
import os
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


def alert_lines(lines):
    return [line for line in lines if line.startswith("[HOOKS ALERT]")]


def event_lines(lines):
    return [
        line
        for line in lines
        if not line.startswith("[HOOKS ACTIVE]")
        and not line.startswith("[HOOKS ALERT]")
        and not line.startswith("[HOOKS DISPLAY]")
    ]


class HeaderAndShapeTest(unittest.TestCase):
    def test_header_counts_entries_events_and_statuses(self):
        data = settings(
            SessionStart=[group(entry('python "C:/h/a.py"'), entry('echo "[RTK ACTIVE] x"'))],
            SessionEnd=[group(entry('python "C:/h/a.py"'))],
        )
        lines = inv.build_inventory(data, script_exists=PRESENT)
        self.assertEqual(
            lines[0], "[HOOKS ACTIVE] 3 entries / 2 events | 2 ok | 0 missing | 1 inline"
        )

    def test_unsubstituted_placeholders_counted_separately(self):
        data = settings(PreToolUse=[group(entry('python "{{USERPROFILE}}/.claude/hooks/a.py"'))])
        lines = inv.build_inventory(data, script_exists=ABSENT)
        self.assertIn("1 unsubstituted", lines[0])

    def test_no_unsubstituted_segment_when_there_are_none(self):
        data = settings(PreToolUse=[group(entry('python "C:/h/a.py"'))])
        lines = inv.build_inventory(data, script_exists=PRESENT)
        self.assertNotIn("unsubstituted", lines[0])

    def test_canonical_event_order_is_not_declaration_order(self):
        data = {
            "hooks": {
                "SessionEnd": [group(entry('python "C:/h/z.py"'))],
                "SessionStart": [group(entry('python "C:/h/a.py"'))],
            }
        }
        lines = inv.build_inventory(data, script_exists=PRESENT)
        events = event_lines(lines)
        self.assertTrue(events[0].startswith("SessionStart("))
        self.assertTrue(events[1].startswith("SessionEnd("))

    def test_unknown_event_is_reported_not_dropped(self):
        data = settings(ZzzFutureEvent=[group(entry('python "C:/h/a.py"'))])
        lines = inv.build_inventory(data, script_exists=PRESENT)
        self.assertEqual(event_lines(lines)[0], "ZzzFutureEvent(1): a.py [ok]")


class StatusTest(unittest.TestCase):
    def test_present_script_is_ok(self):
        data = settings(SessionStart=[group(entry('python "C:/h/a.py"'))])
        lines = inv.build_inventory(data, script_exists=PRESENT)
        self.assertEqual(event_lines(lines)[0], "SessionStart(1): a.py [ok]")

    def test_absent_script_is_missing_and_alerts(self):
        data = settings(PreToolUse=[group(entry('python "C:/h/vault-access-guard.py"'))])
        lines = inv.build_inventory(data, script_exists=ABSENT)
        self.assertIn("vault-access-guard.py [MISSING", event_lines(lines)[0])
        alerts = alert_lines(lines)
        self.assertEqual(len(alerts), 1)
        self.assertIn("vault-access-guard.py (PreToolUse)", alerts[0])
        self.assertIn("REFUSED", alerts[0])

    def test_inline_hook_is_inline_never_missing(self):
        data = settings(SessionStart=[group(entry('echo "[RTK ACTIVE] ok"'))])
        lines = inv.build_inventory(data, script_exists=ABSENT)
        self.assertEqual(event_lines(lines)[0], "SessionStart(1): rtk-active [inline]")
        self.assertEqual(alert_lines(lines), [])

    def test_placeholder_path_is_template_never_missing(self):
        data = settings(PreToolUse=[group(entry('python "{{USERPROFILE}}/.claude/hooks/a.py"'))])
        lines = inv.build_inventory(data, script_exists=ABSENT)
        self.assertIn("a.py [template", event_lines(lines)[0])
        self.assertEqual(alert_lines(lines), [])

    def test_matcher_is_shown_for_a_tool_gated_hook(self):
        data = settings(
            PreToolUse=[
                group(entry('python "C:/h/vault-access-guard.py"'), matcher="Bash|Read|Grep")
            ]
        )
        lines = inv.build_inventory(data, script_exists=PRESENT)
        self.assertEqual(
            event_lines(lines)[0],
            "PreToolUse(1): vault-access-guard.py [ok, Bash|Read|Grep]",
        )

    def test_no_matcher_segment_when_the_event_is_not_tool_gated(self):
        data = settings(SessionStart=[group(entry('python "C:/h/a.py"'))])
        lines = inv.build_inventory(data, script_exists=PRESENT)
        self.assertEqual(event_lines(lines)[0], "SessionStart(1): a.py [ok]")


class DisplayDirectiveTest(unittest.TestCase):
    def test_directive_is_present_and_last(self):
        # Without it the block reaches the model's context and never the user's pane,
        # which is the whole reason the Session: status line has its own hook.
        data = settings(SessionStart=[group(entry('python "C:/h/a.py"'))])
        lines = inv.build_inventory(data, script_exists=PRESENT)
        self.assertTrue(lines[-1].startswith("[HOOKS DISPLAY]"))
        self.assertIn("verbatim", lines[-1])

    def test_directive_follows_the_alert_rather_than_preceding_it(self):
        data = settings(PreToolUse=[group(entry('python "C:/h/gone.py"'))])
        lines = inv.build_inventory(data, script_exists=ABSENT)
        self.assertTrue(lines[-2].startswith("[HOOKS ALERT]"))
        self.assertTrue(lines[-1].startswith("[HOOKS DISPLAY]"))

    def test_no_directive_when_there_is_nothing_to_show(self):
        self.assertEqual(inv.build_inventory({"hooks": {}}, script_exists=PRESENT), [])


class LabelTest(unittest.TestCase):
    def test_inline_hook_labelled_by_its_bracket_tag(self):
        data = settings(SessionStart=[group(entry('echo "[AUTO-SYNC CHECK] branch=main"'))])
        lines = inv.build_inventory(data, script_exists=PRESENT)
        self.assertIn("auto-sync-check", event_lines(lines)[0])

    def test_inline_hook_falls_back_to_status_message(self):
        data = settings(
            SessionStart=[group(entry("rtk_st=$(command -v rtk)", statusMessage="Checking RTK..."))]
        )
        lines = inv.build_inventory(data, script_exists=PRESENT)
        self.assertIn("checking-rtk", event_lines(lines)[0])

    def test_interpreter_exe_is_not_taken_for_the_script(self):
        data = settings(
            UserPromptSubmit=[
                group(entry('"C:/Program Files/nodejs/node.exe" "C:/h/caveman-mode-tracker.js"'))
            ]
        )
        lines = inv.build_inventory(data, script_exists=PRESENT)
        self.assertEqual(event_lines(lines)[0], "UserPromptSubmit(1): caveman-mode-tracker.js [ok]")

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
        self.assertEqual(event_lines(lines)[0], "Stop(1): memory-upkeep [inline]")
        self.assertEqual(alert_lines(lines), [])

    def test_quoted_semicolon_after_the_script_still_yields_the_script(self):
        command = (
            "powershell -NoProfile -Command \"if (Test-Path "
            "'C:/Martin Otis/ResearchTools/install-junctions.ps1') "
            "{ & 'C:/Martin Otis/ResearchTools/install-junctions.ps1' -Sync }; exit 0\""
        )
        data = settings(SessionStart=[group(entry(command))])
        lines = inv.build_inventory(data, script_exists=PRESENT)
        self.assertEqual(event_lines(lines)[0], "SessionStart(1): install-junctions.ps1 [ok]")

    def test_bare_relative_script_name_is_treated_as_inline(self):
        data = settings(SessionStart=[group(entry("python hook.py", statusMessage="Local..."))])
        lines = inv.build_inventory(data, script_exists=ABSENT)
        self.assertEqual(event_lines(lines)[0], "SessionStart(1): local [inline]")
        self.assertEqual(alert_lines(lines), [])


class RobustnessTest(unittest.TestCase):
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
        self.assertIn("SessionStart(1): rtk-active [inline]", out)
        self.assertIn("[HOOKS DISPLAY]", out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
