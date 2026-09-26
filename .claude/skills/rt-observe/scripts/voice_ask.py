#!/usr/bin/env python3
"""
voice_ask.py - rt-dashboard's half of the voice question/answer exchange.

Writes a request into ~/.claude/obsidian-outbox/ask/requests/ and polls
~/.claude/obsidian-outbox/ask/answers/ for the reply. Never opens
OBSIDIAN_VAULT and never opens graphify-out/: the outbox is already outside
the vault (the same boundary collect_services.py's outbox_listed liveness
read already stands on), and the vault/graph reasoning is entirely
daemon_ask.py's (obsidian-cli skill), reached only through these files.

The request/answer shapes are locked in
docs/superpowers/plans/2026-09-26-voice-memory-query/spec.md and owned
jointly by this module and daemon_ask.py; changing one without the other
breaks the exchange silently, which is why both sides' tests assert the
exact field names rather than only "some dict came back".
"""
import io
import json
import os
import secrets
import time
from datetime import datetime, timezone
from pathlib import Path

# Section -> path inside the trimmed digest. A section reporting anything
# other than "ok" degrades that one field to None rather than raising: the
# question can still be answered with partial context (R8's "degrade, do not
# fail the whole thing" reading, since this digest is an ENRICHMENT of the
# prompt, not a required input).
_FIELDS = {
    "mirrors_totals": ("mirrors", "totals"),
    "repo_green": ("repo_state", "green", "value"),
    "repo_branch": ("repo_state", "branch", "value"),
    "progress_phases": ("progress", "phases"),
    "services_daemon_running": ("services", "vault_daemon", "running"),
    "graph_summary": ("graph", None),
}


def _dig(state, path):
    node = state
    for key in path:
        if key is None:
            return node
        if not isinstance(node, dict):
            return None
        node = node.get(key)
    return node


def build_context_snapshot(state: dict) -> dict:
    """
    --------------------------------------------------------------------------
    Purpose:
        Trim a full /api/state-shaped snapshot to the compact digest the
        daemon's prompt uses, per spec.md's locked field list.

    Inputs:
        state (dict): the sections rt-observe already collected this poll

    Outputs:
        digest (dict): one key per locked field; a field whose source
        section is missing or "status" != "ok" is None rather than absent,
        so the daemon's prompt formatting never has to guess a key exists.
    --------------------------------------------------------------------------
    """
    digest = {}
    for name, path in _FIELDS.items():
        section = state.get(path[0])
        if not isinstance(section, dict) or section.get("status") not in (
                "ok", None):
            digest[name] = None
            continue
        digest[name] = _dig(state, path)
    if isinstance(digest.get("graph_summary"), dict):
        digest["graph_summary"] = {
            k: digest["graph_summary"].get(k)
            for k in ("nodes", "links", "stale")}
    return digest


def write_ask_request(outbox_root: Path, question: str,
                      context_snapshot: dict, language: str = "auto",
                      ident=None, clock=None) -> str:
    """
    --------------------------------------------------------------------------
    Purpose:
        Stage one question atomically into ask/requests/, in the exact shape
        daemon_ask.read_request expects.

    Inputs:
        outbox_root (Path): ~/.claude/obsidian-outbox (config paths.obsidian_outbox)
        question (str): the transcribed question, already stripped
        context_snapshot (dict): from build_context_snapshot
        language (str): "auto", "en" or "fr", from the voice panel's
        dropdown - the one value driving both the STT decode hint (Task 4's
        route reads it before this call) and the daemon's answer language
        ident, clock (callable): injected for the suite (R19)

    Outputs:
        request_id (str): the file's stem, needed by poll_answer
    --------------------------------------------------------------------------
    """
    ident = ident or (lambda: secrets.token_hex(8))
    clock = clock or (lambda: datetime.now(timezone.utc))
    request_id = ident()
    folder = Path(outbox_root) / "ask" / "requests"
    folder.mkdir(parents=True, exist_ok=True)
    payload = {"id": request_id, "from": "rt-dashboard",
              "asked_at": clock().isoformat(timespec="seconds"),
              "question": question, "language": language,
              "context_snapshot": context_snapshot}
    tmp = folder / f"{request_id}.json.tmp"
    final = folder / f"{request_id}.json"
    with io.open(tmp, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False))
    os.replace(str(tmp), str(final))
    return request_id


def poll_answer(outbox_root: Path, request_id: str, timeout_s: float,
               poll_interval_s: float, sleep=None, clock=None) -> dict:
    """
    --------------------------------------------------------------------------
    Purpose:
        Wait for the daemon's answer file, bounded (R10). The file is removed
        once read, so a second poll for the same id never re-reads a stale
        answer.

    Inputs:
        outbox_root (Path): ~/.claude/obsidian-outbox
        request_id (str): from write_ask_request
        timeout_s (float): total wait budget
        poll_interval_s (float): wait between checks
        sleep, clock (callable): injected for the suite (R19, R21)

    Outputs:
        answer (dict): the daemon's answer payload, or
        {"id", "status": "timeout", "reason": ...} when the budget runs out.
    --------------------------------------------------------------------------
    """
    sleep = sleep or time.sleep
    clock = clock or time.monotonic
    path = Path(outbox_root) / "ask" / "answers" / f"{request_id}.json"
    deadline = clock() + timeout_s
    while clock() < deadline:
        if path.exists():
            try:
                answer = json.loads(path.read_text(encoding="utf-8"))
            except ValueError:
                answer = None
            path.unlink(missing_ok=True)
            if answer is not None:
                return answer
        sleep(poll_interval_s)
    return {"id": request_id, "status": "timeout",
           "reason": f"no answer within {timeout_s}s; is the vault daemon "
                     "running? (vault-daemon-autostart.ps1 -Status)"}
