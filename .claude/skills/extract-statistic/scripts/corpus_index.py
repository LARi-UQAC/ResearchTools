"""
corpus_index.py - Opt-in semantic index over a review corpus, for ad-hoc
cross-corpus retrieval only.

Four rules govern this module and none of them is negotiable:

  1. STRICTLY ADDITIVE. scan_sections() and scan_stats() in extract_text.py are
     not modified and remain the sole source for the statistics and future-works
     pipelines. This index never feeds them.
  2. Every hit returns citekey, page, and the verbatim passage, so a human
     verifies before use. This is the geolocalisation provenance contract.
  3. The build is OPT-IN and never runs implicitly inside another skill.
  4. A retrieval hit is NEVER a citation. A passage surfaced by similarity still
     passes the normal Scopus validation gate before entering any document. Every
     result carries that statement in its `note` field.

The embedder is an injected callable, so the tests run offline with a
deterministic fake and no model ever loads.

Usage:
  python corpus_index.py build  --bib <corpus.bib> [--refs <dir>] [--dsn ...]
  python corpus_index.py query  "<question>" [--top 8] [--dsn ...]
  python corpus_index.py status [--dsn ...]
"""

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

CHUNK_CHARS = 1200
CHUNK_OVERLAP = 200

NOT_A_CITATION = (
    "Retrieved by similarity. This is provenance, not a citation: validate the "
    "reference through the scopus skill before it enters any document.")

_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+(.+?)\s*$", re.MULTILINE)


def _headings(text: str) -> list[tuple[int, str]]:
    """Character offset and title of every Markdown heading, in order."""
    return [(m.start(), m.group(1).strip()) for m in _HEADING_RE.finditer(text)]


def _heading_at(headings: list[tuple[int, str]], offset: int) -> str:
    """The nearest heading at or before `offset`, or an empty string."""
    title = ""
    for start, name in headings:
        if start > offset:
            break
        title = name
    return title


def _page_at(page_offsets: list[int] | None, offset: int) -> int | None:
    """The 1-based page containing `offset`, or None when unknown."""
    if not page_offsets:
        return None
    page = 1
    for index, start in enumerate(page_offsets, start=1):
        if start > offset:
            break
        page = index
    return page


def chunk_text(text: str, citekey: str,
               page_offsets: list[int] | None = None) -> list[dict[str, Any]]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Split one document's cached text into overlapping windows, each carrying
        the provenance a human needs to verify a hit: citekey, character range,
        page when knowable, the nearest preceding heading, and the verbatim
        passage.

        The split is deterministic: fixed window, fixed overlap, no randomness
        and no tokenizer, so the same text yields identical chunks everywhere.

    Inputs:
        text (str): the cached document text
        citekey (str): the BibTeX key of the source
        page_offsets (list[int] | None): character offset where each page starts,
            when the parse backend reported it

    Outputs:
        chunks (list[dict]): {citekey, chunk_index, char_start, char_end, page,
        heading, passage}; empty when the text is blank
    --------------------------------------------------------------------------
    """
    if not text or not text.strip():
        return []

    headings = _headings(text)
    step = max(1, CHUNK_CHARS - CHUNK_OVERLAP)
    chunks: list[dict[str, Any]] = []
    start = 0
    index = 0
    while start < len(text):
        end = min(len(text), start + CHUNK_CHARS)
        chunks.append({
            "citekey": citekey,
            "chunk_index": index,
            "char_start": start,
            "char_end": end,
            "page": _page_at(page_offsets, start),
            "heading": _heading_at(headings, start),
            "passage": text[start:end],
        })
        if end >= len(text):
            break
        start += step
        index += 1
    return chunks
