"""
aider - report what the nightly coding pipeline is doing, from its run records.

Written 2026-09-03, OUTSIDE the ResearchTools clone, ready to be dropped into
`.claude/skills/rt-observe/scripts/adapters/` with one line added to
`harnesses.json`. Nothing here needs a core edit; that is the contract stated in
`adapters/__init__.py` and enforced by a test that registers a fake adapter and
checks the snapshot grows.

Why a record rather than a scan
-------------------------------
Claude Code is observable because `~/.claude/projects/` is a MACHINE-level
directory: one place to look, whatever project a session is in. Aider has no
equivalent - its state is per project, in the working tree. Scanning the disk for
`.aider*` is not an answer: unbounded, slow, and it would make a dashboard panel
depend on how many drives are mounted.

So the driver writes one small record per project under `<home>/.aider-plan/runs/`,
rewritten whole and atomically at every state change. This adapter reads those
and nothing else. It never opens a project, never runs git, and never invokes a
model.

What it deliberately does NOT report
------------------------------------
A token percentage is honest here, unlike the Claude Code panel where it is
refused: a transcript never records the window its tokens sit in, but the driver
computes and records both `window` and `working_set`. That difference is stated
in the payload rather than left for a reader to assume the two panels mean the
same thing.
"""
import io
import json
import os
import sys

# Every state the driver can write, in the order it walks them. The adapter is
# the ONE place this vocabulary lives on the viewer side: a page that carried its
# own copy would drift from the driver the first time a state was added.
FLOW_STATES = [
    ("starting",  "starting",   "setup"),
    ("writing",   "writing",    "model"),
    ("testing",   "testing",    "gate"),
    ("evicting",  "swapping",   "machine"),
    ("auditing",  "reviewing",  "model"),
    ("archiving", "archiving",  "setup"),
    ("done",      "done",       "terminal"),
    # A run that did everything it was asked to do and produced work a person
    # must now read: aider-plan.ps1:1129 writes it when every plan ran and at
    # least one carries a [!] in progress.md. Neither clean nor stopped, and a
    # dashboard showing it green hides the very lines the student is meant to
    # open.
    ("done_with_blocked", "done, needs reading", "terminal"),
    ("failed",    "stopped",    "terminal"),
]

# Derived, never restated. The list above says which states are terminal, and a
# second literal copy of that answer is exactly the drift the comment on
# FLOW_STATES warns about - it had already happened: the ageing test below read
# ("done", "failed"), so a done_with_blocked record older than the idle
# threshold was reported as "idle", which is a claim that nothing happened about
# a run that finished and needs reading.
TERMINAL_STATES = frozenset(s[0] for s in FLOW_STATES if s[2] == "terminal")

_KNOWN_SCHEMA = "aider-plan/run-record/1"


def _runs_dir(context):
    return context.home / ".aider-plan" / "runs"


def probe(context):
    """Has this machine ever run the pipeline."""
    directory = _runs_dir(context)
    if not directory.is_dir():
        return False
    return any(directory.glob("*.json"))


def _redact(text, home):
    """Rewrite a path under the home directory to '~'.

    The dashboard is rendered in a browser and screenshotted, which is exactly
    how an account name reaches a slide. rt_redact does this for the rest of the
    skill; it is repeated here only so this file can be dropped in before that
    import path is settled, and should be replaced by it on integration.
    """
    if not text:
        return text
    home = str(home)
    return str(text).replace(home, "~").replace(home.replace("\\", "/"), "~")


def _alive_windows(pid):
    """Windows has no null signal: measured 2026-09-24, `os.kill(pid, 0)` maps
    to `GenerateConsoleCtrlEvent(CTRL_C_EVENT, ...)` there (CTRL_C_EVENT == 0),
    which does not merely check the target - it can deliver a Ctrl+C to every
    process sharing the caller's console, up to and including the caller
    itself. Reproduced with a two-line script under a redirected-output
    Start-Process: the parent PowerShell process died with no output at all.
    The safe Windows check is OpenProcess/CloseHandle, never a signal."""
    import ctypes
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    handle = ctypes.windll.kernel32.OpenProcess(
        PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return False
    ctypes.windll.kernel32.CloseHandle(handle)
    return True


def _alive(pid):
    """Is the process that wrote this record still running.

    Liveness is asked of the PROCESS, never of the file. A run killed by a
    shutdown leaves its last record behind, and reading that as "still running"
    reports exactly backwards - the same lesson the vault daemon's singleton lock
    already carries.
    """
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return None
    if pid <= 0:
        return None
    if sys.platform == "win32":
        try:
            return _alive_windows(pid)
        except (AttributeError, OSError):
            # ctypes/kernel32 unavailable for some reason: unknown is an
            # honest answer and False is not.
            return None
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False
    except (AttributeError, PermissionError):
        # A process owned by someone else: unknown is an honest answer and
        # False is not.
        return None


def _flow(record, age_seconds, idle_after):
    """The step list the process tab draws, and the state it is in."""
    state = str(record.get("state") or "unknown")
    note = str(record.get("note") or "")

    steps = []
    plan = record.get("plan")
    if plan:
        rnd = record.get("round") or 1
        label = "%s, round %s" % (plan, rnd)
        steps.append({"kind": "plan", "name": label})
    if state in ("writing", "testing", "auditing", "evicting", "archiving"):
        steps.append({"kind": "state", "name": state, "detail": note})

    tests_exit = record.get("tests_exit")
    if tests_exit is not None:
        steps.append({"kind": "result", "name": "tests",
                      "error": bool(tests_exit)})
    if record.get("audit_bytes"):
        steps.append({"kind": "result", "name": "audit report",
                      "error": False})

    # A terminal state is never idle, however long ago it was written.
    if state in TERMINAL_STATES:
        shown = state
    elif age_seconds is not None and idle_after and age_seconds > idle_after:
        shown = "idle"
    else:
        shown = state

    window = record.get("window") or 0
    working = record.get("working_set") or 0
    tokens = {"window": window, "working_set": working}
    if window:
        tokens["percent"] = round(100.0 * (window - working) / window, 1)
        tokens["percent_of"] = "the fixed cost against the window the driver measured"
    else:
        tokens["percent"] = None
        tokens["percent_reason"] = "the record carries no window"

    return {"status": "ok", "state": shown, "steps": steps,
            "subagents": [], "hooks": [], "dropped": 0, "tokens": tokens}


def collect(context):
    """
    --------------------------------------------------------------------------
    Purpose:
        Report every project this machine has run the pipeline on, with what the
        harness was doing and how far through the plans it is.

    Inputs:
        context (AdapterContext): injected home, repo root, config and clock

    Outputs:
        state (dict): {"status", "sessions", "counts", "flow_states"}
    --------------------------------------------------------------------------
    """
    directory = _runs_dir(context)
    idle_after = 0
    try:
        idle_after = int(context.config["staleness_seconds"]["session_idle"])
    except (KeyError, TypeError, ValueError):
        idle_after = 0

    sessions = []
    unreadable = []
    for path in sorted(directory.glob("*.json")):
        try:
            # A context manager, not the bare io.open(...).read() this repository
            # uses elsewhere. There it runs once per snapshot; here it runs once
            # per project on every poll of a page that refreshes every couple of
            # seconds, so a leaked descriptor is not theoretical. Surfaced by
            # ResourceWarning under the suite's verbose run, 2026-09-03.
            with io.open(path, encoding="utf-8-sig") as handle:
                record = json.loads(handle.read())
        except (OSError, ValueError) as exc:
            # Named, never dropped: a record that cannot be read is a project
            # whose state is unknown, which is not the same as a project with
            # nothing happening.
            unreadable.append({"file": path.name, "reason": str(exc)})
            continue

        schema = record.get("schema")
        if schema != _KNOWN_SCHEMA:
            unreadable.append({"file": path.name,
                               "reason": "schema %r is not %r; refusing to "
                                         "guess its shape" % (schema, _KNOWN_SCHEMA)})
            continue

        try:
            age = int(max(0.0, context.now.timestamp() - path.stat().st_mtime))
        except OSError:
            age = None

        alive = _alive(record.get("pid"))
        done = record.get("plans_done") or 0
        total = record.get("plan_count") or 0

        sessions.append({
            "session_id": record.get("run_id") or path.stem,
            "project": _redact(record.get("project"), context.home),
            "cwd": _redact(record.get("project"), context.home),
            "branch": record.get("branch"),
            "mode": "skills" if record.get("skills") else "plain",
            "effort": None,
            "entrypoint": "aider-night",
            # Free text is where a path usually escapes, so this one is built
            # rather than copied: it names the plan and the progress, nothing else.
            "prompt": "%s, round %s  -  %s of %s plan(s) done" % (
                record.get("plan") or "no plan yet", record.get("round") or 0,
                done, total),
            "subagents": 0,
            "hook_errors": [],
            "age_seconds": age,
            "plan": record.get("plan"),
            "live": alive,
            "live_reason": ("the process that wrote this record is gone, so the "
                            "state below is where it stopped, not where it is"
                            if alive is False else None),
            "progress": {
                "plans_done": done,
                "plans_total": total,
                "steps_done": record.get("steps_done") or 0,
                "steps_open": record.get("steps_open") or 0,
                "steps_blocked": record.get("steps_blocked") or 0,
                "audit_bytes": record.get("audit_bytes") or 0,
            },
            "flow": _flow(record, age, idle_after),
            # Aider has no UserPromptSubmit event, so no inbox message can ever
            # reach it. Stated rather than omitted: a missing field would be read
            # as reachable.
            "inbox": {"status": "unreachable",
                      "reason": "aider has no prompt-submit hook, so a message "
                                "cannot be delivered into a run"},
        })

    sessions.sort(key=lambda s: (s["age_seconds"] is None, s["age_seconds"]))

    return {
        "status": "ok",
        "proven_by": "~/.aider-plan/runs/*.json",
        "proven_at": context.stamp,
        "counts": {"projects": len(sessions), "unreadable": len(unreadable)},
        "sessions": sessions,
        "unreadable": unreadable,
        "flow_states": [{"id": s[0], "label": s[1], "role": s[2]}
                        for s in FLOW_STATES],
    }
