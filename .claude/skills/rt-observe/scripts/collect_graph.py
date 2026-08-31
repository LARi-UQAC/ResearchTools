"""
collect_graph - the code graph panel, fed by a snapshot and never by the graph.

This module does NOT read the knowledge graph. It reads a snapshot file that the
`local-writer` agent produced, outside the graph's own storage.

That is not squeamishness, it is the rule this repository enforces at the tool
boundary: `vault-access-guard.py` refuses the graph's storage path, the graphify
CLI, and both graph audit scripts BY NAME to every caller except `local-writer`.
The audit scripts are refused precisely because they read the graph on a caller's
behalf, which is exactly what a dashboard server would be doing. Confirmed live
on 2026-08-30, when a bare directory listing of that storage was refused inside
the session that wrote this file.

So "live" is redefined honestly rather than claimed loosely. The panel is live
with respect to the SNAPSHOT: it reports the snapshot's age as a receipt and
renders it stale past a configured ceiling. It is not live with respect to the
graph, because refreshing that costs an agent dispatch, and a refresh control
here prints the dispatch to run rather than pretending it can run it. A server
cannot call an agent tool.
"""
import io
import json
from pathlib import Path

# What local-writer is asked to put in the snapshot. Named here so the panel can
# say which fields are missing rather than rendering blanks.
EXPECTED_FIELDS = ("generated", "nodes", "links", "origins", "file_types")

REFRESH_INSTRUCTION = (
    "Dispatch the local-writer agent (Agent tool, subagent_type: local-writer) and "
    "ask it to refresh the graph snapshot: it is the only caller allowed to read "
    "the graph, and it writes the snapshot to the configured path. This panel "
    "cannot do it, because a server cannot call an agent tool.")


def _resolve(path_value, home):
    text = str(path_value)
    if text.startswith("~/"):
        return Path(home) / text[2:]
    return Path(text)


def collect(snapshot_path, home, now, stale_after_s):
    """
    --------------------------------------------------------------------------
    Purpose:
        Report the code graph's shape from the snapshot local-writer wrote.

    Inputs:
        snapshot_path (str): configured path, may start with ~/
        home (Path): home directory, injected (R21)
        now (datetime): injected clock (R19)
        stale_after_s (int): age past which the snapshot renders stale

    Outputs:
        state (dict): {"status", ...} - always answers, never raises
    --------------------------------------------------------------------------
    """
    path = _resolve(snapshot_path, home)
    if not path.exists():
        return {
            "status": "unavailable",
            "reason": "no graph snapshot at %s. The dashboard never reads the "
                      "graph itself: the access guard refuses it to every caller "
                      "but local-writer, and a server reading it on your behalf is "
                      "the exact bypass that guard exists to stop." % path,
            "refresh": REFRESH_INSTRUCTION,
        }

    try:
        data = json.loads(io.open(path, encoding="utf-8-sig").read())
    except ValueError as exc:
        return {"status": "unavailable",
                "reason": "the graph snapshot does not parse: %s" % exc,
                "refresh": REFRESH_INSTRUCTION}
    except OSError as exc:
        return {"status": "unavailable",
                "reason": "the graph snapshot is unreadable: %s" % exc,
                "refresh": REFRESH_INSTRUCTION}

    try:
        age = max(0.0, now.timestamp() - path.stat().st_mtime)
    except OSError:
        age = None

    stale = age is not None and age > stale_after_s
    missing = [field for field in EXPECTED_FIELDS if field not in data]

    origins = data.get("origins", {})
    semantic = 0
    if isinstance(origins, dict):
        semantic = sum(count for key, count in origins.items()
                       if isinstance(count, int) and key != "ast")

    return {
        "status": "ok",
        "proven_by": str(path.name),
        "proven_at": data.get("generated"),
        "age_seconds": None if age is None else int(age),
        "stale": stale,
        "reason": ("this snapshot is older than the configured ceiling, so the "
                   "canvas is showing the graph as it was, not as it is"
                   if stale else None),
        "missing_fields": missing,
        "missing_fields_reason": (
            None if not missing else
            "the snapshot omits %s, so those parts of the panel are blank "
            "because the data is absent, not because the value is zero"
            % ", ".join(missing)),
        "nodes": data.get("nodes"),
        "links": data.get("links"),
        "origins": origins,
        "file_types": data.get("file_types", {}),
        "modules": data.get("modules", []),
        "ast_only": semantic == 0 and bool(origins),
        "ast_only_reason": (
            "every node in this snapshot came from an AST pass, so the graph "
            "holds what the code IS and no layer that read what the documents "
            "SAY. A why-question belongs to the vault, not here."
            if semantic == 0 and origins else None),
        "refresh": REFRESH_INSTRUCTION,
    }
