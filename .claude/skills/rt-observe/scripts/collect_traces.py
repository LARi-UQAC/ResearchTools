"""
collect_traces - Phase 3 panel: agent traces read back from OpenObserve.

Follows the same collector contract every other section here does: fn(...) ->
dict, never raising, an unavailable panel names its own reason (R8). It does NOT
reimplement token counting - that semantics (sum input + cache_creation + output,
deliberately excluding cache_read so one cached conversation is not counted every
time it is re-read) already exists in collect_usage.py and stays owned there
(plan section 1.2, section 3's own requirement). This collector reports what the
trace stream itself carries: row and distinct-session counts, and the newest
event's timestamp, never a re-derived token total.

Bounded pagination and an explicit timeout come from observe-config.json (R0,
R10): a deeper history belongs in OpenObserve's own UI, not a panel read standing
up.
"""
from datetime import datetime, timezone

import rt_openobserve


def collect(repo_root, home, config, now=None, env=None, opener=None):
    """
    --------------------------------------------------------------------------
    Purpose:
        Report the trace stream's own shape: row count, distinct sessions, and
        the newest event seen, or why OpenObserve could not answer.

    Inputs:
        repo_root, home (Path): injected roots (R21); home is also what
                                every returned string is redacted against
        config (dict): parsed observe-config.json
        now (datetime): injected clock (R19)
        env, opener: injected seams for the offline suite (R21)

    Outputs:
        state (dict)
    --------------------------------------------------------------------------
    """
    try:
        values, reason = rt_openobserve.load_oo_config(config, env=env)
    except rt_openobserve.OpenObserveError as exc:
        return {"status": "unavailable", "reason": str(exc)}
    if values is None:
        return {"status": "unavailable", "reason": reason}

    def cfg(*keys):
        node = config
        for key in keys:
            node = node[key]
        return node["value"]

    timeout_s = cfg("timeouts_seconds", "openobserve_search")
    page_size = cfg("caps", "traces_page_size")
    max_pages = cfg("caps", "traces_max_pages")

    ok, rows, reason, truncated = rt_openobserve.search(
        values, "traces", "SELECT * ORDER BY _timestamp DESC",
        timeout_s, page_size, max_pages, opener=opener)
    if not ok:
        return {"status": "unavailable", "reason": reason}

    sessions = set()
    newest = None
    for row in rows:
        session_id = row.get("session_id") or row.get("resource_session_id")
        if session_id:
            sessions.add(session_id)
        stamp = row.get("_timestamp") or row.get("timestamp")
        if stamp and (newest is None or stamp > newest):
            newest = stamp

    stamp = (now or datetime.now(timezone.utc)).isoformat(timespec="seconds")
    return {
        "status": "ok",
        "rows": len(rows),
        "distinct_sessions": len(sessions),
        "newest_event": newest,
        "truncated": truncated,
        "reason": ("more rows exist than the configured page/pagination "
                   "bound; showing the most recent %d" % (page_size * max_pages)
                   if truncated else None),
        "collected_at": stamp,
    }
