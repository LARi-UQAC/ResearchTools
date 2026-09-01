"""
collect_usage - how many tokens this machine has actually spent, over a window.

The Real-Time Process tab draws three bars, and this module answers the middle
one. It is a separate snapshot section rather than part of the fleet for the
same reason MCP is: cost. The fleet reads the TAIL of each transcript every ten
seconds; this reads them whole, so it runs on a timer of its own and carries its
own floor, which a viewer's refresh control cannot go below.

What is counted, and why it is not the obvious sum. A cached prompt re-reads the
same tokens on every message of a session, so adding `cache_read_input_tokens`
would count one conversation dozens of times and produce a number that looks
like usage and measures repetition. What is counted is what was NEW on each
message: `input_tokens` + `cache_creation_input_tokens` + `output_tokens`.

What is NOT here, and will not be invented: money. No transcript records a
price, a plan, an overage or an invoice, so this module reports tokens and the
page says as much. The limits the bars fill against are the operator's own
numbers, typed in the page, because nothing on this machine reports them either.
"""
import io
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path


def _projects_dir(context):
    return context.home / ".claude" / "projects"


def _cap(context, *keys):
    node = context.config
    for key in keys:
        node = node[key]
    return node["value"]


def _stamp(text):
    """A transcript timestamp, or None. Written to accept the `Z` suffix the
    harness uses, which `fromisoformat` refuses before Python 3.11."""
    if not text:
        return None
    try:
        return datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    except ValueError:
        return None


def _new_tokens(usage):
    """What this message added, never what it re-read.

    `cache_read_input_tokens` is the context handed back unchanged on every
    message of a cached session; summing it would report one conversation as
    dozens and read as spend.
    """
    return (int(usage.get("input_tokens") or 0)
            + int(usage.get("cache_creation_input_tokens") or 0)
            + int(usage.get("output_tokens") or 0))


def _scan(path, since, byte_cap):
    """One transcript, streamed. Returns (tokens, messages, truncated)."""
    tokens = 0
    messages = 0
    read = 0
    truncated = False
    with io.open(path, encoding="utf-8", errors="replace") as handle:
        for line in handle:
            read += len(line)
            if byte_cap and read > byte_cap:
                truncated = True
                break
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                record = json.loads(line)
            except ValueError:
                continue
            message = record.get("message")
            if not isinstance(message, dict):
                continue
            usage = message.get("usage")
            if not isinstance(usage, dict):
                continue
            when = _stamp(record.get("timestamp"))
            if when is None or when < since:
                continue
            tokens += _new_tokens(usage)
            messages += 1
    return tokens, messages, truncated


def collect(context):
    """
    --------------------------------------------------------------------------
    Purpose:
        Sum the tokens this machine spent inside a configured window, from the
        transcripts it already has, so the week bar fills against something
        measured rather than something assumed.

    Inputs:
        context (AdapterContext): injected home, config and clock

    Outputs:
        state (dict): {"status", "window_days", "tokens", "messages",
                       "sessions", "truncated", "proven_by", "proven_at"}
    --------------------------------------------------------------------------
    """
    projects = _projects_dir(context)
    if not projects.is_dir():
        # Not a failure: a machine with no Claude Code has no transcripts, and
        # saying so is the answer (R8).
        return {"status": "unavailable",
                "reason": "no ~/.claude/projects directory on this machine, so "
                          "no transcript records what was spent",
                "proven_at": context.stamp}

    days = _cap(context, "caps", "usage_window_days")
    byte_cap = _cap(context, "caps", "usage_scan_bytes")
    excluded = set(_cap(context, "privacy", "excluded_projects"))
    since = context.now - timedelta(days=days)
    if since.tzinfo is None:
        since = since.replace(tzinfo=timezone.utc)

    tokens = 0
    messages = 0
    sessions = 0
    truncated = 0
    scanned = 0
    for project_dir in sorted(projects.iterdir()):
        if not project_dir.is_dir() or project_dir.name in excluded:
            continue
        for path in project_dir.glob("*.jsonl"):
            try:
                stat = path.stat()
            except OSError:
                continue
            when = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)
            if when < since:
                # Untouched inside the window: nothing in it can be inside it.
                continue
            scanned += 1
            try:
                found, count, cut = _scan(path, since, byte_cap)
            except OSError:
                continue
            tokens += found
            messages += count
            truncated += 1 if cut else 0
            if count:
                sessions += 1

    return {
        "status": "ok",
        "window_days": days,
        "tokens": tokens,
        "messages": messages,
        "sessions": sessions,
        "transcripts_scanned": scanned,
        "transcripts_truncated": truncated,
        "counts_what": "input + cache_creation + output, per message. Tokens "
                       "re-read from cache are excluded, since they are the "
                       "same conversation counted again rather than new spend",
        "proven_by": "~/.claude/projects/*/*.jsonl",
        "proven_at": context.stamp,
    }
