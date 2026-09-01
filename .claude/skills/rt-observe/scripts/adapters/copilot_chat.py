"""
copilot_chat - the GitHub Copilot Chat adapter, over a read-only SQLite store.

The VS Code extension keeps its sessions in a SQLite database. It is opened
through a `file:...?mode=ro` URI and NEVER for writing: this is somebody else's
live application store, and a dashboard has no business holding a write lock on
it. A database locked by the running editor degrades this one panel with its
reason rather than raising, because one adapter must never take the page down.

Schema confirmed on 2026-08-30:
    sessions(id, cwd, repository, host_type, branch, summary, agent_name,
             agent_description, created_at, updated_at)
    turns(session_id, turn_index, user_message, assistant_response, timestamp)

Only session-level metadata is read. Message bodies are never selected: the
`turns` table is touched for a COUNT and nothing else, so no prompt text from
another harness reaches the snapshot at all.
"""
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rt_redact import home_tilde  # noqa: E402

RELATIVE_STORE = ("Code", "User", "globalStorage", "github.copilot-chat",
                  "session-store.db")


def _store_path(context):
    return Path(context.home).joinpath("AppData", "Roaming", *RELATIVE_STORE)


def probe(context):
    return _store_path(context).exists()


def _cap(context, *keys):
    node = context.config
    for key in keys:
        node = node[key]
    return node["value"]


def _truncate(text, limit):
    if text is None:
        return None
    text = str(text).replace("\n", " ").strip()
    return text if len(text) <= limit else text[:limit - 1] + "…"


def _redact(text, home):
    """Delegates to rt_redact.home_tilde, the single implementation."""
    return home_tilde(text, home)


def collect(context):
    """
    --------------------------------------------------------------------------
    Purpose:
        Report recent Copilot Chat sessions from the extension's own store.

    Inputs:
        context (AdapterContext): injected home, config and clock

    Outputs:
        state (dict): {"status", "sessions", "counts"} or an unavailable panel
    --------------------------------------------------------------------------
    """
    path = _store_path(context)
    shown = _cap(context, "caps", "sessions_shown")
    summary_cap = _cap(context, "caps", "summary_chars")
    excluded = set(_cap(context, "privacy", "excluded_projects"))

    uri = "file:%s?mode=ro" % path.as_posix()
    try:
        connection = sqlite3.connect(uri, uri=True, timeout=2.0)
    except sqlite3.Error as exc:
        return {"status": "unavailable",
                "reason": "the Copilot Chat store could not be opened read-only: "
                          "%s. It is the editor's live database, so a lock here is "
                          "normal and costs this panel only." % exc}

    try:
        cursor = connection.cursor()
        try:
            cursor.execute(
                "SELECT id, cwd, repository, host_type, branch, summary, "
                "agent_name, updated_at FROM sessions "
                "ORDER BY updated_at DESC LIMIT ?", (shown,))
            rows = cursor.fetchall()
        except sqlite3.Error as exc:
            return {"status": "unavailable",
                    "reason": "the sessions table did not answer the expected "
                              "columns, so the extension's schema may have "
                              "changed: %s" % exc}

        try:
            cursor.execute("SELECT COUNT(*) FROM turns")
            turn_count = cursor.fetchone()[0]
        except sqlite3.Error:
            turn_count = None

        sessions = []
        for row in rows:
            (session_id, cwd, repository, host_type, branch, summary,
             agent_name, updated_at) = row
            if repository and repository in excluded:
                continue
            sessions.append({
                "session_id": session_id,
                "cwd": _redact(cwd, context.home),
                "repository": repository,
                "host_type": host_type,
                "branch": branch,
                # Same reason as the Claude adapter's prompt: a summary is free
                # text and can quote a path under the home directory.
                "summary": _truncate(_redact(summary, context.home),
                                     summary_cap),
                "agent_name": agent_name,
                "updated_at": updated_at,
                # The Real-Time Process tab is adapter-fed, so a harness that
                # cannot report a step says so rather than being drawn as an
                # idle flow, which would be indistinguishable from a session
                # sitting quietly and is the wrong answer twice over.
                "flow": {
                    "status": "unavailable",
                    "reason": "the extension's store records session metadata "
                              "only, so no step timeline exists to read",
                },
                "inbox": {
                    "reachable": False,
                    "pending": 0,
                    "reason": "Copilot Chat has no hook that could deliver an "
                              "inbox message, so this session is reportable but "
                              "not reachable",
                },
            })
    finally:
        connection.close()

    return {
        "status": "ok",
        "proven_by": "session-store.db (read-only)",
        "proven_at": context.stamp,
        "counts": {"sessions": len(sessions), "turns": turn_count},
        "sessions": sessions,
    }
