"""
claude_code - the Claude Code adapter: sessions, hooks, and inbox reachability.

Sessions are tail-read from the JSONL transcripts. A transcript grows without
bound and only its tail carries current state, so a configured number of bytes is
read from the end rather than the whole file.

The hooks inventory is carried here rather than in the core because it is
harness-specific. It reuses `build_inventory` out of
`.claude/hooks/session-hooks-inventory.py`, loaded BY PATH: that filename carries
hyphens and cannot be imported by name, and the function has exactly one caller
of its own, so it was never an API. It is covered by a 26-test suite, which is
what makes the reuse defensible - not its visibility.

Privacy is applied before anything leaves this module. A project named in the
configured exclusion list contributes nothing at all rather than something
shortened, prompts and summaries are truncated to their configured caps, and
every path under the home directory is rewritten to `~/...` so no account name
reaches the snapshot or the page.
"""
import importlib.util
import io
import json
import os
import sys
from pathlib import Path


def _projects_dir(context):
    return context.home / ".claude" / "projects"


def probe(context):
    """Is Claude Code present on this machine at all."""
    return _projects_dir(context).is_dir()


def _cap(context, *keys):
    node = context.config
    for key in keys:
        node = node[key]
    return node["value"]


def _redact(text, home):
    """Rewrite any path under the home directory to ~/..., so the snapshot never
    carries the account name (verify-no-personal-data.ps1 stays green, and the
    page is safe to screenshot)."""
    if not text:
        return text
    home_text = str(home)
    out = str(text).replace(home_text, "~")
    out = out.replace(home_text.replace("\\", "/"), "~")
    return out


def _truncate(text, limit):
    if text is None:
        return None
    text = str(text).replace("\n", " ").strip()
    return text if len(text) <= limit else text[:limit - 1] + "…"


def _tail_records(path, tail_bytes):
    """The last decodable JSON records of a transcript, newest last.

    A truncated first line is expected when reading from an offset and must not
    abort the fleet, so undecodable lines are skipped rather than raised on.
    """
    try:
        size = path.stat().st_size
        with io.open(path, "rb") as handle:
            if size > tail_bytes:
                handle.seek(size - tail_bytes)
            blob = handle.read()
    except OSError:
        return []
    text = blob.decode("utf-8", errors="replace")
    records = []
    for line in text.splitlines():
        line = line.strip()
        if not line or not line.startswith("{"):
            continue
        try:
            records.append(json.loads(line))
        except ValueError:
            continue
    return records


def _session_from(records):
    """Fold a transcript's tail into one session card."""
    card = {}
    hook_errors = []
    sidechains = 0
    for record in records:
        for key in ("sessionId", "cwd", "gitBranch", "mode", "lastPrompt",
                    "entrypoint", "effort", "version"):
            if record.get(key) not in (None, ""):
                card[key] = record[key]
        if record.get("isSidechain"):
            sidechains += 1
        system = record.get("system")
        if isinstance(system, dict):
            summary = system.get("stop_hook_summary")
            if isinstance(summary, dict):
                for err in summary.get("hookErrors", []) or []:
                    hook_errors.append(str(err))
    card["sidechain_records"] = sidechains
    card["hook_errors"] = hook_errors[-3:]
    return card


def _hooks_inventory(context):
    """The hooks inventory, reusing the SessionStart hook's own builder."""
    script = (context.repo_root / ".claude" / "hooks"
              / "session-hooks-inventory.py")
    settings = context.home / ".claude" / "settings.json"
    if not script.exists():
        return {"status": "unavailable",
                "reason": "session-hooks-inventory.py is not in this clone, so "
                          "the hook inventory cannot be built"}
    if not settings.exists():
        return {"status": "unavailable",
                "reason": "no ~/.claude/settings.json, so no hook is declared "
                          "on this machine"}
    spec = importlib.util.spec_from_file_location(
        "rt_observe_hooks_inventory", str(script))
    if spec is None or spec.loader is None:
        return {"status": "unavailable",
                "reason": "session-hooks-inventory.py could not be loaded"}
    module = importlib.util.module_from_spec(spec)
    sys.modules["rt_observe_hooks_inventory"] = module
    try:
        spec.loader.exec_module(module)
    except Exception as exc:                            # noqa: BLE001
        return {"status": "unavailable",
                "reason": "session-hooks-inventory.py failed to import: %s" % exc}
    if not hasattr(module, "build_inventory"):
        return {"status": "unavailable",
                "reason": "session-hooks-inventory.py no longer exposes "
                          "build_inventory, the function this panel reuses"}
    try:
        parsed = json.loads(io.open(settings, encoding="utf-8-sig").read())
    except (ValueError, OSError) as exc:
        return {"status": "unavailable",
                "reason": "~/.claude/settings.json does not parse: %s" % exc}
    try:
        inventory = module.build_inventory(parsed)
    except Exception as exc:                            # noqa: BLE001
        return {"status": "unavailable",
                "reason": "build_inventory failed: %s" % exc}
    return {"status": "ok", "proven_by": "session-hooks-inventory.build_inventory",
            "inventory": inventory}


def _inbox(context, session_id):
    """Is this session reachable by the dashboard's inbox, and what is pending.

    A message written into a directory nobody drains is the vault drop that sat
    in working/ for an hour. So an unreachable target is SAID to be unreachable
    rather than reported as delivered.
    """
    root = context.home / ".claude" / "rt-inbox"
    hook_installed = False
    settings = context.home / ".claude" / "settings.json"
    if settings.exists():
        try:
            hook_installed = "rt-inbox" in io.open(
                settings, encoding="utf-8-sig").read()
        except OSError:
            hook_installed = False
    folder = root / session_id if session_id else None
    pending = 0
    if folder is not None and folder.is_dir():
        pending = len([p for p in folder.glob("*.json") if p.is_file()])
    return {
        "reachable": hook_installed,
        "pending": pending,
        "reason": (None if hook_installed else
                   "no inbox delivery hook is declared in ~/.claude/settings.json, "
                   "so a message written for this session would never be read"),
    }


def collect(context):
    """
    --------------------------------------------------------------------------
    Purpose:
        Report Claude Code's live state: recent sessions, the hook inventory,
        and whether each session can be reached by the inbox.

    Inputs:
        context (AdapterContext): injected home, repo root, config and clock

    Outputs:
        state (dict): {"status", "sessions", "hooks", "counts"}
    --------------------------------------------------------------------------
    """
    projects = _projects_dir(context)
    excluded = set(_cap(context, "privacy", "excluded_projects"))
    prompt_cap = _cap(context, "caps", "prompt_chars")
    shown = _cap(context, "caps", "sessions_shown")
    tail_bytes = _cap(context, "caps", "transcript_tail_bytes")

    transcripts = []
    for project_dir in sorted(projects.iterdir()) if projects.is_dir() else []:
        if not project_dir.is_dir() or project_dir.name in excluded:
            continue
        for path in project_dir.glob("*.jsonl"):
            try:
                mtime = path.stat().st_mtime
            except OSError:
                continue
            transcripts.append((mtime, project_dir.name, path))

    transcripts.sort(reverse=True)
    plans = {p.stem: p.name for p in (context.home / ".claude" / "plans").glob("*.md")} \
        if (context.home / ".claude" / "plans").is_dir() else {}

    sessions = []
    for mtime, project, path in transcripts[:shown]:
        card = _session_from(_tail_records(path, tail_bytes))
        session_id = card.get("sessionId") or path.stem
        age = int(max(0.0, context.now.timestamp() - mtime))
        sessions.append({
            "session_id": session_id,
            "project": project,
            "cwd": _redact(card.get("cwd"), context.home),
            "branch": card.get("gitBranch"),
            "mode": card.get("mode"),
            "effort": card.get("effort"),
            "entrypoint": card.get("entrypoint"),
            "prompt": _truncate(card.get("lastPrompt"), prompt_cap),
            "subagents": card.get("sidechain_records", 0),
            "hook_errors": [_truncate(_redact(e, context.home), prompt_cap)
                            for e in card.get("hook_errors", [])],
            "age_seconds": age,
            "plan": plans.get(session_id),
            "inbox": _inbox(context, session_id),
        })

    return {
        "status": "ok",
        "proven_by": "~/.claude/projects/*/*.jsonl",
        "proven_at": context.stamp,
        "counts": {"transcripts": len(transcripts), "shown": len(sessions),
                   "excluded_projects": len(excluded)},
        "sessions": sessions,
        "hooks": _hooks_inventory(context),
    }
