"""
collect_local - the `local_calls` snapshot section: what the local models have been doing.

Local coding exists to save cloud tokens, and until now a bridge call left almost no trace a
person could read. Since the local coding contract (plan 6) every attempt that
`ollama_bridge.py` appends to `~/.claude/loop-bridge-log.jsonl` carries `at`, `role`, `tag`,
`num_ctx`, `prompt_tokens`, `completion_tokens` and `plan`. This collector reads a bounded TAIL
of that log and groups it by role: which model, at what window, how many calls and tokens, how
long ago, and whether the role is active right now.

It follows the degradation contract of every other section here: a thing that cannot be
answered is `unavailable` WITH ITS REASON, never a zero and never a blank (R8, R11). Old lines
written before the enrichment have no role: they are skipped and counted, never crash and
never counted as a role. A cut last line is dropped. The log is read through a byte cap, so a
huge file costs a bounded read. Every string that can carry a path goes through
`rt_redact`, so no account name reaches the snapshot. The log is neither the vault nor the
graph, so reading it is not guarded.

Tokens here are the daemon's own `prompt_eval_count` and `eval_count`. They are summed per role
and say nothing about money, which is not readable from this machine.
"""
import json
from datetime import datetime, timezone
from pathlib import Path

import rt_redact


class ConfigKeyError(KeyError):
    """A configuration key is missing, named by its dotted path (R3)."""


def _cfg(config, *keys):
    """
    --------------------------------------------------------------------------
    Purpose:
        Read one {value, provenance} entry of observe-config.json.

    Inputs:
        config (dict): parsed observe-config.json
        keys (str): the path, for example ("caps", "local_calls_recent")

    Outputs:
        value (Any): the entry's "value".

    Raises:
        ConfigKeyError: the path or its value is absent, naming the dotted key.
    --------------------------------------------------------------------------
    """
    node = config
    for key in keys:
        if not isinstance(node, dict) or key not in node:
            raise ConfigKeyError("observe-config.json declares no %s" % ".".join(keys))
        node = node[key]
    if not isinstance(node, dict) or "value" not in node:
        raise ConfigKeyError("observe-config.json entry %s has no value" % ".".join(keys))
    return node["value"]


def _log_path(text, home):
    """
    --------------------------------------------------------------------------
    Purpose:
        Resolve the configured log path against the INJECTED home, never the real one (R21).

    Inputs:
        text (str): the configured path, a leading ~ meaning the home directory
        home (Path): the home directory

    Outputs:
        path (Path): the log file path.
    --------------------------------------------------------------------------
    """
    if text.startswith("~"):
        return Path(home) / text[1:].lstrip("/\\")
    return Path(text)


def _stamp(text):
    """
    --------------------------------------------------------------------------
    Purpose:
        Parse a record's ISO timestamp, accepting the Z suffix and treating a naive time as UTC.

    Inputs:
        text (Any): the `at` field

    Outputs:
        moment (datetime | None): an aware datetime, or None when unparsable.
    --------------------------------------------------------------------------
    """
    if not isinstance(text, str) or not text:
        return None
    try:
        moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def _read_tail(path, tail_bytes):
    """
    --------------------------------------------------------------------------
    Purpose:
        Read the last `tail_bytes` of the log and parse its JSON lines.

    Details:
        When the read starts inside the file its first line is partial and is dropped. Any line
        that is not a JSON object, a cut last line included, is skipped.

    Inputs:
        path (Path): the log file
        tail_bytes (int): the read cap

    Outputs:
        result (tuple): (records, truncated, size) where records is a list of dicts, truncated
        says the file was larger than the cap, and size is the file size in bytes.

    Raises:
        OSError: the file cannot be read.
    --------------------------------------------------------------------------
    """
    size = path.stat().st_size
    start = max(0, size - tail_bytes)
    with open(path, "rb") as handle:
        handle.seek(start)
        data = handle.read()
    lines = data.decode("utf-8", errors="replace").split("\n")
    if start > 0:
        lines = lines[1:]
    records = []
    for line in lines:
        try:
            item = json.loads(line)
        except ValueError:
            continue
        if isinstance(item, dict):
            records.append(item)
    return records, start > 0, size


def _group(records, now, active_seconds):
    """
    --------------------------------------------------------------------------
    Purpose:
        Group enriched records by role, in order of first appearance.

    Inputs:
        records (list[dict]): parsed log records, oldest first
        now (datetime): the injected clock (R19)
        active_seconds (int): a role is active when its last call is younger than this

    Outputs:
        result (tuple): (roles, kept, skipped) with roles a mapping role -> summary, kept the
        enriched records and skipped the count of records that carry no role.
    --------------------------------------------------------------------------
    """
    roles, kept, skipped = {}, [], 0
    for item in records:
        role = item.get("role")
        if not isinstance(role, str) or not role:
            skipped += 1
            continue
        kept.append(item)
        row = roles.setdefault(role, {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0})
        row["calls"] += 1
        for key in ("prompt_tokens", "completion_tokens"):
            if isinstance(item.get(key), int) and not isinstance(item.get(key), bool):
                row[key] += item[key]
        row.update(tag=item.get("tag"), num_ctx=item.get("num_ctx"),
                   last_at=item.get("at"), plan=item.get("plan"))
    for row in roles.values():
        moment = _stamp(row["last_at"])
        row["age_seconds"] = max(0, int((now - moment).total_seconds())) if moment else None
        row["active"] = row["age_seconds"] is not None and row["age_seconds"] < active_seconds
    return roles, kept, skipped


def collect(config, home, now):
    """
    --------------------------------------------------------------------------
    Purpose:
        Build the `local_calls` section from the bridge log.

    Inputs:
        config (dict): parsed observe-config.json (paths.bridge_log, caps.local_calls_tail_bytes,
            caps.local_calls_recent, staleness_seconds.local_active)
        home (Path): the home directory the log path resolves against and every string is
            redacted against
        now (datetime): the injected clock (R19)

    Outputs:
        state (dict): status "ok" with proven_by, proven_at, roles, recent, skipped_without_role,
        truncated and collected_at, or status "unavailable" with a named reason. Never raises.
    --------------------------------------------------------------------------
    """
    try:
        path_text = _cfg(config, "paths", "bridge_log")
        tail_bytes = _cfg(config, "caps", "local_calls_tail_bytes")
        recent_cap = _cfg(config, "caps", "local_calls_recent")
        active_seconds = _cfg(config, "staleness_seconds", "local_active")
    except ConfigKeyError as exc:
        return {"status": "unavailable", "reason": str(exc)}
    path = _log_path(path_text, home)
    shown = rt_redact.home_tilde(str(path), home)
    if not path.is_file():
        return {"status": "unavailable", "reason": "bridge log not found: %s" % shown}
    try:
        records, truncated, size = _read_tail(path, tail_bytes)
    except OSError as exc:
        return {"status": "unavailable",
                "reason": "bridge log unreadable: %s (%s)" % (shown, exc.__class__.__name__)}
    if size == 0:
        return {"status": "unavailable", "reason": "bridge log is empty: %s" % shown}
    roles, kept, skipped = _group(records, now, active_seconds)
    if not kept:
        return {"status": "unavailable",
                "reason": "no record carries a role yet in %s (%d older line(s) skipped)"
                          % (shown, skipped)}
    recent = [{key: item.get(key) for key in
               ("at", "role", "tag", "plan", "prompt_tokens", "completion_tokens", "accepted")}
              for item in reversed(kept[-recent_cap:])]
    state = {"status": "ok", "proven_by": shown,
             "proven_at": max((i.get("at") for i in kept if isinstance(i.get("at"), str)),
                              default=None),
             "roles": roles, "recent": recent, "skipped_without_role": skipped,
             "truncated": truncated, "collected_at": now.isoformat(timespec="seconds")}
    return rt_redact.redact_json(state, home)
