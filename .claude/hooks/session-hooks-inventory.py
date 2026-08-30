"""
session-hooks-inventory - SessionStart hook that reports the hook inventory actually
loaded from settings.json, plus any declared hook whose script is absent from disk.

Stage: session startup. It is the counterpart of the measured defect of 2026-08-27, when
vault-access-guard.py had been removed while settings.json still declared it and nine tools
were refused for four turns with nothing at startup saying so. A hand-maintained table in a
CLAUDE.md cannot report that, and drifted on its own (11 documented against 13 declared,
measured 2026-08-28).

Contract:
  stdout  the inventory, because only a SessionStart hook's stdout reaches the session
          context (stderr and -Quiet runs are invisible)
  exit 0  always, including a missing, unreadable or malformed settings file (R11)
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Callable, Iterable, Optional

# R5: the canonical event order, defined once. Events absent from settings.json are
# skipped; an event present but unknown here is appended after these, sorted, so a new
# Claude Code event is reported rather than silently dropped.
EVENT_ORDER = (
    "SessionStart",
    "UserPromptSubmit",
    "PreToolUse",
    "PostToolUse",
    "Stop",
    "SubagentStop",
    "PreCompact",
    "Notification",
    "SessionEnd",
)

# A command mentioning one of these is a script whose existence can be checked.
SCRIPT_SUFFIXES = (".py", ".js", ".ps1", ".sh", ".cmd", ".bat")

# Environment override, so a test never reads this machine's real settings file (R21).
SETTINGS_ENV_VAR = "CLAUDE_HOOKS_SETTINGS_PATH"

# R5: the per-hook status vocabulary, defined once. "ok" and "MISSING" are the two
# that matter; "inline" means there is no script file to check, and "template" means
# the path still carries an unsubstituted placeholder.
STATUS_OK = "ok"
STATUS_MISSING = "MISSING"
STATUS_INLINE = "inline"
STATUS_TEMPLATE = "template"

_BRACKET_TAG = re.compile(r"\[([A-Za-z][A-Za-z0-9 _-]{2,30})\]")
_SCRIPT_PATH = re.compile(
    r"([^\"'|;&<>]*?(?:" + "|".join(re.escape(s) for s in SCRIPT_SUFFIXES) + r"))",
    re.IGNORECASE,
)
# Only the invocation head can name the script. Measured 2026-08-28: the Stop hook's
# command carries a long prose reason mentioning Decisions.md and model_resolver.py, and
# scanning the whole string turned that prose into the hook's label and then reported it
# as a missing file. A file name is an argument only before the first statement break.
_SEGMENT_BREAK = re.compile(r";|\n")


def settings_path():
    """
    --------------------------------------------------------------------------
    Purpose:
        Resolve the settings file to inspect, from the environment rather than a
        literal path (R1).

    Inputs:
        none (reads SETTINGS_ENV_VAR, else the user's home directory)

    Outputs:
        path (Path): the settings.json to read; may not exist
    --------------------------------------------------------------------------
    """
    override = os.environ.get(SETTINGS_ENV_VAR)
    if override:
        return Path(override)
    return Path.home() / ".claude" / "settings.json"


def script_in_command(command):
    """
    --------------------------------------------------------------------------
    Purpose:
        Extract the script path a hook command invokes, if it invokes one. An
        inline shell hook returns None.

    Inputs:
        command (str): the hook's command string

    Outputs:
        path (str | None): the script path as written, or None
    --------------------------------------------------------------------------
    """
    head = _SEGMENT_BREAK.split(command, 1)[0]
    for match in _SCRIPT_PATH.finditer(head):
        candidate = match.group(1).strip().strip('"').strip("'").strip()
        if not candidate:
            continue
        # The interpreter itself (node.exe, python.exe) is not the hook's script.
        if candidate.lower().endswith(".exe"):
            continue
        # A bare name with no directory cannot be checked against the disk, since the
        # hook's working directory is not ours to assume. Treat it as an inline hook.
        if "/" not in candidate and "\\" not in candidate:
            continue
        return candidate
    return None


def label_for(hook, command):
    """
    --------------------------------------------------------------------------
    Purpose:
        Name a hook in one short token, preferring the most stable source
        available: its script's file name, then the bracket tag it prints, then
        its statusMessage, then the first word of its command.

    Inputs:
        hook (dict): the hook entry from settings.json
        command (str): that entry's command string

    Outputs:
        label (str): a short name for the inventory line
    --------------------------------------------------------------------------
    """
    script = script_in_command(command)
    if script:
        return Path(script.replace("\\", "/")).name

    tag = _BRACKET_TAG.search(command)
    if tag:
        return tag.group(1).strip().lower().replace(" ", "-")

    status = str(hook.get("statusMessage", "")).strip()
    if status:
        return status.rstrip(". ").lower().replace(" ", "-")

    return command.strip().split(" ", 1)[0] or "(unnamed)"


def _ordered_events(declared):
    declared = list(declared)
    known = [e for e in EVENT_ORDER if e in declared]
    unknown = sorted(e for e in declared if e not in EVENT_ORDER)
    return known + unknown


def build_inventory(settings, script_exists=None):
    """
    --------------------------------------------------------------------------
    Purpose:
        Render the compact inventory: one header line of totals, one line per
        event, and an alert line naming every declared script absent from disk.
        Pure and deterministic - no clock, no randomness, no IO of its own
        beyond the injected existence predicate (R19).

    Inputs:
        settings (object): the parsed settings.json, or anything at all
        script_exists (callable | None): path -> bool; defaults to os.path.exists

    Outputs:
        lines (list[str]): the lines to print; empty when nothing is declared
    --------------------------------------------------------------------------
    """
    if script_exists is None:
        script_exists = os.path.exists

    if not isinstance(settings, dict):
        return []
    hooks = settings.get("hooks")
    if not isinstance(hooks, dict) or not hooks:
        return []

    per_event = {}
    missing = []
    tally = {STATUS_OK: 0, STATUS_MISSING: 0, STATUS_INLINE: 0, STATUS_TEMPLATE: 0}
    total = 0

    for event in _ordered_events(hooks.keys()):
        groups = hooks.get(event)
        if not isinstance(groups, list):
            continue
        rendered = []
        for group in groups:
            if not isinstance(group, dict):
                continue
            matcher = str(group.get("matcher", "")).strip()
            for hook in group.get("hooks", []):
                if not isinstance(hook, dict):
                    continue
                command = str(hook.get("command", ""))
                label = label_for(hook, command)
                total += 1

                script = script_in_command(command)
                if not script:
                    status = STATUS_INLINE
                elif "{{" in script:
                    # A template setup has not substituted yet; its absence on
                    # disk proves nothing either way.
                    status = STATUS_TEMPLATE
                elif script_exists(script):
                    status = STATUS_OK
                else:
                    status = STATUS_MISSING
                    missing.append("%s (%s)" % (label, event))
                tally[status] += 1

                detail = status if not matcher else "%s, %s" % (status, matcher)
                rendered.append("%s [%s]" % (label, detail))
        if rendered:
            per_event[event] = rendered

    if not per_event:
        return []

    header = "[HOOKS ACTIVE] %d entries / %d events | %d ok | %d missing | %d inline" % (
        total,
        len(per_event),
        tally[STATUS_OK],
        tally[STATUS_MISSING],
        tally[STATUS_INLINE],
    )
    if tally[STATUS_TEMPLATE]:
        header += " | %d unsubstituted" % tally[STATUS_TEMPLATE]

    lines = [header]
    for event, rendered in per_event.items():
        lines.append("%s(%d): %s" % (event, len(rendered), " | ".join(rendered)))
    if missing:
        lines.append(
            "[HOOKS ALERT] declared but script absent from disk: "
            + ", ".join(missing)
            + " - the matched tools will be REFUSED until the file is restored "
            "or the entry is removed from settings.json."
        )
    # A hook's stdout reaches the model's context, never the user's pane. The
    # Session: status line is seen only because its hook asks for it to be
    # printed; this asks for the same, so the inventory is visible to a person
    # and not only to the assistant reading it.
    lines.append(
        "[HOOKS DISPLAY] Output every [HOOKS ACTIVE], event and [HOOKS ALERT] line above "
        "to the user verbatim, in a code block, immediately after the Session: status line "
        "at the start of your first response. Do not summarise or re-order them."
    )
    return lines


def main():
    path = settings_path()
    try:
        with open(path, encoding="utf-8") as handle:
            settings = json.load(handle)
    except (OSError, ValueError):
        # R11: a hook whose own dependency is absent or unreadable says nothing
        # and exits 0. Only a real violation of what it guards is loud.
        return 0

    for line in build_inventory(settings):
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
