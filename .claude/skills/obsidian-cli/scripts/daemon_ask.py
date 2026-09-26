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
