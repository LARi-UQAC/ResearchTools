#!/usr/bin/env python3
"""
daemon_ask.py - the vault daemon's read-only ask queue.

Answers a question using vault search plus a state digest the caller already
computed, through the local LLM. The one caller allowed to submit here is
rt-dashboard: `read_request` refuses anything whose "from" is not
"rt-dashboard" rather than silently accepting an unlabeled request, which is
the one runtime check standing behind the "only rt-dashboard, no other
caller" instruction this queue exists to satisfy.

This module never calls `graphify query` and never reads `graphify-out/`.
daemon-config.json's `daemon.graphify_repo_root` is null on purpose (see its
own _provenance comment): the vault is cross-project, a graph is per-project,
and this daemon has no fixed notion of "the repository" to query. A
graph-shaped question is answered from the `context_snapshot` the caller
supplies, which already carries a local-writer-produced graph snapshot
summary when rt-observe collected one.

Split from daemon_states.py rather than added to it, matching the existing
seam: daemon_states answers "what happens to a knowledge drop", this module
answers "what happens to a question about the vault", and neither imports
the other's prompts.
"""
import json
import re
import sys
from datetime import datetime
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import daemon_states  # noqa: E402
import daemon_taxonomy  # noqa: E402

_TOKEN = re.compile(r"[a-zA-Z][a-zA-Z0-9_-]{2,}")
# Same shape as narrative-cv's cv_select.py: tokenize, drop the shortest and
# most common words, score by overlap, break ties deterministically (R19).
_STOPWORDS = {
    "the", "and", "for", "are", "was", "were", "this", "that", "with",
    "from", "have", "has", "had", "does", "did", "why", "what", "which",
    "who", "when", "how", "not", "but", "you", "your", "our", "its",
}


def _tokenize(text: str) -> set:
    return {t.lower() for t in _TOKEN.findall(text)
            if t.lower() not in _STOPWORDS}


class AskRefused(RuntimeError):
    """The request cannot be answered and must be recorded as refused."""


def read_request(path: Path) -> dict:
    """
    --------------------------------------------------------------------------
    Purpose:
        Parse one ask request and refuse anything not shaped like a
        legitimate rt-dashboard question.

    Inputs:
        path (Path): the .json file in outbox/ask/requests/

    Outputs:
        request (dict): id, from, asked_at, question, language,
        context_snapshot (context_snapshot defaults to {} when absent,
        language defaults to "auto" when absent)

    Raises:
        AskRefused: the file is not valid JSON, is not an object, names no
        question, declares a "from" other than "rt-dashboard", or names a
        "language" outside auto/en/fr.
    --------------------------------------------------------------------------
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise AskRefused(f"request file could not be read: {exc}") from exc
    try:
        payload = json.loads(text)
    except ValueError as exc:
        raise AskRefused(f"request is not JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise AskRefused("request is not an object")
    if payload.get("from") != "rt-dashboard":
        raise AskRefused(
            f"request declares from={payload.get('from')!r}; this queue "
            "answers rt-dashboard only")
    question = payload.get("question")
    if not isinstance(question, str) or not question.strip():
        raise AskRefused("request names no question")
    language = payload.get("language") or "auto"
    if language not in ("auto", "en", "fr"):
        raise AskRefused(f"request names an unsupported language {language!r}; "
                         "the voice panel's dropdown offers auto, en, fr only")
    return {
        "id": payload.get("id"),
        "from": payload["from"],
        "asked_at": payload.get("asked_at"),
        "question": question.strip(),
        "language": language,
        "context_snapshot": payload.get("context_snapshot") or {},
    }


def search_vault(vault: Path, question: str, max_notes: int,
                 excerpt_chars: int) -> list:
    """
    --------------------------------------------------------------------------
    Purpose:
        Rank every note under 30_Ressources/ and 10_Projets/ by keyword
        overlap with the question, and return the top matches with an
        excerpt. Pure keyword overlap, no embedding and no external index:
        this is a bounded local scan, not a search engine.

    Inputs:
        vault (Path): the vault root
        question (str): the caller's question, already stripped
        max_notes (int): cap on how many notes are returned (R0)
        excerpt_chars (int): cap on each returned excerpt (R0)

    Outputs:
        hits (list): [{"rel", "score", "excerpt"}], sorted by score
        descending then rel ascending; empty when nothing scores above zero
        or the vault has neither folder.
    --------------------------------------------------------------------------
    """
    question_terms = _tokenize(question)
    if not question_terms:
        return []
    roots = [Path(vault) / daemon_taxonomy.RESOURCES,
             Path(vault) / daemon_taxonomy.PROJECTS]
    scored = []
    for root in roots:
        if not root.is_dir():
            continue
        for note in sorted(root.rglob("*.md")):
            try:
                body = note.read_text(encoding="utf-8")
            except OSError:
                continue
            overlap = len(question_terms & _tokenize(body))
            if overlap == 0:
                continue
            rel = note.relative_to(vault).as_posix()
            scored.append({"rel": rel, "score": overlap,
                           "excerpt": body[:excerpt_chars]})
    scored.sort(key=lambda h: (-h["score"], h["rel"]))
    return scored[:max_notes]


# Keyed by the dropdown's own three values (plan2's voice panel), so a
# language this module cannot express is a KeyError caught nowhere by
# design - read_request already refused anything outside this set (R5).
_LANGUAGE_INSTRUCTION = {
    "en": "Answer in English.",
    "fr": "Reponds en francais.",
    "auto": "Answer in the same language the question below is written in.",
}

ASK_PREFIX = (
    "You answer a spoken question about a personal research toolkit's own "
    "state, using ONLY the state digest and vault excerpts given below. "
    "Speak in plain prose, in short sentences: your answer will be read "
    "aloud by a speech synthesizer. Never use markdown, never use bullet "
    "points, never use asterisks or headings. If the digest and excerpts do "
    "not answer the question, say so plainly rather than guessing. {language}\n"
)


def _age_seconds(asked_at: str, today: str) -> float:
    try:
        asked = datetime.fromisoformat(asked_at)
        now = datetime.fromisoformat(today)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, (now - asked).total_seconds())


def _snapshot_text(context_snapshot: dict, max_chars: int) -> str:
    text = json.dumps(context_snapshot, ensure_ascii=False)
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + " ...(truncated)"


def answer(request: dict, vault: Path, model: str, window: int,
          timeout: float, config: dict, today: str) -> dict:
    """
    --------------------------------------------------------------------------
    Purpose:
        Compose the answer to one already-gated ask request: expire a stale
        one, search the vault, call the local model, and shape the result
        into one of the answer file's locked statuses.

    Inputs:
        request (dict): the parsed request from read_request()
        vault (Path): the vault root
        model (str): the resolved writer-role tag
        window (int): the measured retained window for that tag
        timeout (float): the model call's socket timeout (R10)
        config (dict): daemon-config.json, for the ask_* bounds
        today (str): ISO 8601 UTC "now", injected by the caller (R19)

    Outputs:
        result (dict): {"id", "answered_at", "status", ...}. status is
        "ok" (answer_text, sources, model_calls), "expired" (reason), or
        "error" (reason, from a caught ob.BridgeError).
    --------------------------------------------------------------------------
    """
    import outbox_io
    ttl = outbox_io.require(config, "daemon", "ask_request_ttl_s")
    base = {"id": request["id"], "answered_at": today}
    age = _age_seconds(request.get("asked_at") or today, today)
    if age > ttl:
        return dict(base, status="expired",
                    reason=f"request is {int(age)}s old, past the {ttl}s TTL")

    max_notes = outbox_io.require(config, "daemon", "ask_max_vault_notes")
    excerpt_chars = outbox_io.require(config, "daemon", "ask_note_excerpt_chars")
    snapshot_max = outbox_io.require(
        config, "daemon", "ask_context_snapshot_max_chars")

    hits = search_vault(vault, request["question"], max_notes, excerpt_chars)
    excerpts = "\n".join(
        f"\nVault note ({h['rel']}):\n{h['excerpt']}\n" for h in hits)
    language = request.get("language", "auto")
    prompt = (ASK_PREFIX.format(language=_LANGUAGE_INSTRUCTION[language])
             + f"\nState digest:\n{_snapshot_text(request['context_snapshot'], snapshot_max)}\n"
             + excerpts
             + f"\nQuestion: {request['question']}\n")
    try:
        text = daemon_states.call_model(prompt, model, window, timeout)
    except daemon_states.ob.BridgeError as exc:
        return dict(base, status="error", reason=str(exc))
    except daemon_states.EventRefused as exc:
        return dict(base, status="error", reason=str(exc))
    return dict(base, status="ok", answer_text=text, model_calls=1,
               sources={"vault_notes": [h["rel"] for h in hits]})
