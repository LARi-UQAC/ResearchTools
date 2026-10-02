#!/usr/bin/env python3
"""
daemon_ask.py - the vault daemon's read-only ask queue.

Answers a question using vault search plus a state digest the caller already
computed, through the local LLM. `read_request`'s "from" check is a routing
label, not access control: it refuses a request that does not DECLARE itself
as coming from rt-dashboard, but any process able to write a file into
outbox/ask/requests/ can declare it and get a vault-grounded answer back -
this queue trusts the outbox the way every other write to it already is
trusted, on the single-user local-machine model security.md states, and does
not itself enforce that only rt-dashboard actually wrote the file. Path
containment (R24) and the request/TTL/exception guards below are real; the
"from" field is a contract between callers, not a boundary.

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
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import daemon_graph  # noqa: E402
import daemon_states  # noqa: E402
import outbox_io  # noqa: E402

# Unicode letters (ASCII plus accented Latin, e.g. "etat") so a French
# question is tokenized at all; previously ASCII-only, so an accented word
# never matched its own search term.
_TOKEN = re.compile(r"[^\W\d_]{3,}", re.UNICODE)
# Same shape as narrative-cv's cv_select.py: tokenize, drop the shortest and
# most common words, score by overlap, break ties deterministically (R19).
_STOPWORDS = {
    "the", "and", "for", "are", "was", "were", "this", "that", "with",
    "from", "have", "has", "had", "does", "did", "why", "what", "which",
    "who", "when", "how", "not", "but", "you", "your", "our", "its",
    "le", "la", "les", "un", "une", "des", "du", "de", "et", "est", "quel",
    "quelle", "pour", "avec", "sur", "dans", "ne", "pas", "qui", "que",
    "comment",
}


def _fold_accents(token: str) -> str:
    """NFKD-decompose and drop combining marks, so "etat" and "etat" (with
    an accent) compare equal - standard library only, no new dependency."""
    decomposed = unicodedata.normalize("NFKD", token)
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def _tokenize(text: str) -> set:
    """Lower-cased tokens, each paired with its accent-folded spelling, so a
    question written without accents still overlaps a note written with
    them and vice versa - every token's set membership includes both
    spellings, even when they are identical (no accent to fold)."""
    tokens = set()
    for match in _TOKEN.findall(text):
        lowered = match.lower()
        if lowered in _STOPWORDS:
            continue
        tokens.add(lowered)
        tokens.add(_fold_accents(lowered))
    return tokens


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


def _entity_folder(rel: str, matched_root: str) -> "str | None":
    """The project/resource folder a hit belongs to: the first path segment
    under its matching search root, except under 10_Projets/<nature>/,
    where the entity is the project itself - the SECOND segment."""
    after_root = Path(rel).parts[len(Path(matched_root).parts):]
    if matched_root == "10_Projets":
        return after_root[1] if len(after_root) > 1 else None
    return after_root[0] if after_root else None


def search_vault(vault: Path, question: str, max_notes: int,
                 excerpt_chars: int, search_roots: list) -> list:
    """
    --------------------------------------------------------------------------
    Purpose:
        Rank every note under the configured search roots by keyword overlap
        with the question, and return the top matches with an excerpt. Pure
        keyword overlap, no embedding and no external index: this is a
        bounded local scan, not a search engine.

        A hit whose entity folder (the project or resource folder it lives
        under) is named in the question ranks before every hit whose is not,
        ties within each group broken as before (score, then rel) - this is
        what lets "quel est le statut du projet DemoRepo" prefer DemoRepo's
        own notes over an equally-scoring note from an unrelated project.

    Inputs:
        vault (Path): the vault root
        question (str): the caller's question, already stripped
        max_notes (int): cap on how many notes are returned (R0)
        excerpt_chars (int): cap on each returned excerpt (R0)
        search_roots (list): vault-relative folder names to search
        (daemon.ask_search_roots, R0 - previously hardcoded to
        30_Ressources/10_Projets)

    Outputs:
        hits (list): [{"rel", "score", "excerpt"}], sorted by
        (folder named in question, score descending, rel ascending); empty
        when nothing scores above zero or no configured root exists.
    --------------------------------------------------------------------------
    """
    question_terms = _tokenize(question)
    if not question_terms:
        return []
    scored = []
    for root in search_roots:
        root_path = Path(vault) / root
        if not root_path.is_dir():
            continue
        for note in sorted(root_path.rglob("*.md")):
            try:
                body = note.read_text(encoding="utf-8")
            except OSError:
                continue
            overlap = len(question_terms & _tokenize(body))
            if overlap == 0:
                continue
            rel = note.relative_to(vault).as_posix()
            entity = _entity_folder(rel, root)
            named = bool(entity) and bool(
                _tokenize(entity) & question_terms)
            scored.append({"rel": rel, "score": overlap,
                           "excerpt": body[:excerpt_chars],
                           "_named": named})
    scored.sort(key=lambda h: (0 if h["_named"] else 1, -h["score"],
                               h["rel"]))
    return [{k: v for k, v in h.items() if k != "_named"}
           for h in scored[:max_notes]]


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

GRAPH_FOLLOWUP_PREFIX = (
    "You already told the user: {already_said}\n"
    "Below is the CODE STRUCTURE of the matched project, from static "
    "analysis of its source files - file and function names, and what "
    "calls what. It is NOT progress and NOT a decision log. Add only what "
    "it usefully adds to your earlier answer, in the same short spoken "
    "style, or say plainly that it adds nothing. Never use markdown. "
    "{language}\n"
)


def graph_sentence(outcome: str, language: str, config: dict) -> str:
    """
    --------------------------------------------------------------------------
    Purpose:
        The catalogue sentence spoken for one graph-part outcome, read from
        daemon-config.json rather than a Python literal (R6).

    Inputs:
        outcome (str): "skipped" or "error"
        language (str): "fr" or "en"
        config (dict): daemon-config.json

    Outputs:
        sentence (str): the configured sentence.

    Raises:
        outbox_io.ConfigError: the outcome/language pair is not declared in
        daemon.ask_graph_sentences.
    --------------------------------------------------------------------------
    """
    sentences = config.get("daemon", {}).get("ask_graph_sentences", {})
    value = sentences.get(outcome, {}).get(language)
    if value is None:
        raise outbox_io.ConfigError(
            f"[OUTBOX] daemon.ask_graph_sentences.{outcome}.{language} is "
            "missing")
    return value


def _age_seconds(asked_at: str, today: str) -> float:
    try:
        asked = datetime.fromisoformat(asked_at)
        now = datetime.fromisoformat(today)
        # `today` and `asked_at` can each be naive (a bare date) or aware
        # (a full ISO datetime with offset), and the two do not have to
        # match: a naive-minus-aware subtraction raises TypeError, which
        # used to escape uncaught and kill the daemon on the first real
        # request (production's default `today` is a bare date; every
        # `asked_at` this queue ever sees is aware). Coerce both to aware
        # UTC before subtracting, inside the same guard, so no shape of
        # either input can raise past this point.
        if asked.tzinfo is None:
            asked = asked.replace(tzinfo=timezone.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        return max(0.0, (now - asked).total_seconds())
    except (TypeError, ValueError):
        return 0.0


def _snapshot_text(context_snapshot: dict, max_chars: int) -> str:
    text = json.dumps(context_snapshot, ensure_ascii=False)
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + " ...(truncated)"


def _graph_language(request_language: str, keyword_language: "str | None") -> str:
    """fr/en the catalogue sentence and the follow-up prompt are spoken in:
    the dropdown's own choice wins; "auto" defers to the keyword call's own
    detected language; a FAILED keyword call (no keyword_language) defaults
    to French, the workspace's documented default (preferences.md)."""
    if request_language in ("fr", "en"):
        return request_language
    return keyword_language or "fr"


def answer(request: dict, vault: Path, model: str, window: int,
          timeout: float, config: dict, today: str, publish=None) -> dict:
    """
    --------------------------------------------------------------------------
    Purpose:
        Compose the answer to one already-gated ask request in two parts:
        the vault answer (published at once via `publish`), then the
        matched project's code graph, or a stated reason it could not be
        reached.

    Inputs:
        request (dict): the parsed request from read_request()
        vault (Path): the vault root
        model (str): the resolved writer-role tag
        window (int): the measured retained window for that tag
        timeout (float): each model call's socket timeout (R10)
        config (dict): daemon-config.json, for the ask_* bounds
        today (str): ISO 8601 UTC "now", injected by the caller (R19)
        publish (Callable[[dict], None] | None): called exactly once, with
        the partial (vault-only) result, right after part 1 and before the
        graph part starts. None (every caller before 2026-10-02) skips this.

    Outputs:
        result (dict): {"id", "answered_at", "status", ...}.
        "expired"/"refused" keep the bare {"reason"} shape (no "parts").
        Part-1 failure keeps the bare "error" shape (no "parts", `publish`
        NOT called). On success: "status": "ok", "parts": [vault_part,
        graph_part], "answer_text" (both parts' text, joined), "sources"
        (vault_notes plus "graph": {"entity", "status", "reason"}),
        "model_calls" (1 to 3, however many calls were actually made).
    --------------------------------------------------------------------------
    """
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
    search_roots = outbox_io.require(config, "daemon", "ask_search_roots")

    hits = search_vault(vault, request["question"], max_notes, excerpt_chars,
                       search_roots)
    excerpts = "\n".join(
        f"\nVault note ({h['rel']}):\n{h['excerpt']}\n" for h in hits)
    request_language = request.get("language", "auto")
    prompt = (ASK_PREFIX.format(
                  language=_LANGUAGE_INSTRUCTION[request_language])
             + f"\nState digest:\n{_snapshot_text(request['context_snapshot'], snapshot_max)}\n"
             + excerpts
             + f"\nQuestion: {request['question']}\n")
    model_calls = 1
    try:
        vault_text = daemon_states.call_model(prompt, model, window, timeout)
    except daemon_states.ob.BridgeError as exc:
        return dict(base, status="error", reason=str(exc))
    except daemon_states.EventRefused as exc:
        return dict(base, status="error", reason=str(exc))

    sources = {"vault_notes": [h["rel"] for h in hits]}
    vault_part = {"stage": "vault", "status": "ok", "text": vault_text,
                 "reason": None}
    if publish is not None:
        publish(dict(base, status="partial", parts=[vault_part],
                     answer_text=vault_part["text"], sources=sources,
                     model_calls=model_calls))

    keyword_language = None
    try:
        keywords = daemon_graph.extract_keywords(
            request["question"], model, window, timeout,
            outbox_io.require(config, "daemon", "ask_keywords_max"))
        model_calls += 1
        keyword_language = keywords["question_language"]
    except daemon_graph.GraphRefused:
        language = _graph_language(request_language, keyword_language)
        graph_part = {"stage": "graph", "status": "error",
                     "text": graph_sentence("error", language, config),
                     "reason": "keyword extraction failed"}
        entity = None
    else:
        resolved = daemon_graph.entity_repo(vault, hits, search_roots)
        entity = resolved.get("entity")
        if entity is None:
            language = _graph_language(request_language, keyword_language)
            graph_part = {"stage": "graph", "status": "skipped",
                         "text": graph_sentence("skipped", language, config),
                         "reason": resolved["reason"]}
        else:
            graph_result = daemon_graph.query_graph(
                resolved["repo"], keywords["keywords_en"],
                outbox_io.require(config, "daemon", "ask_graph_budget_tokens"),
                outbox_io.require(config, "daemon", "ask_graph_max_chars"),
                outbox_io.require(config, "daemon", "ask_graph_timeout_s"))
            language = _graph_language(request_language, keyword_language)
            if graph_result["text"] is None:
                graph_part = {"stage": "graph", "status": "error",
                             "text": graph_sentence("error", language, config),
                             "reason": graph_result["reason"]}
            else:
                followup = (GRAPH_FOLLOWUP_PREFIX.format(
                                already_said=vault_part["text"],
                                language=_LANGUAGE_INSTRUCTION[
                                    request_language])
                           + f"\nCode structure:\n{graph_result['text']}\n")
                try:
                    graph_text = daemon_states.call_model(
                        followup, model, window, timeout)
                    model_calls += 1
                    graph_part = {"stage": "graph", "status": "ok",
                                 "text": graph_text, "reason": None}
                except (daemon_states.ob.BridgeError,
                       daemon_states.EventRefused) as exc:
                    graph_part = {"stage": "graph", "status": "error",
                                 "text": graph_sentence(
                                     "error", language, config),
                                 "reason": str(exc)}

    sources["graph"] = {"entity": entity, "status": graph_part["status"],
                        "reason": graph_part["reason"]}
    answer_text = " ".join(
        p["text"] for p in (vault_part, graph_part) if p["text"]).strip()
    return dict(base, status="ok", parts=[vault_part, graph_part],
               answer_text=answer_text, sources=sources,
               model_calls=model_calls)
