# RT-7: Corpus Parse Cache and Semantic Index Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cache the expensive PDF parse keyed by file hash so every text-extraction consumer gets faster, and build an opt-in pgvector index over the cached text for ad-hoc cross-corpus retrieval whose every hit carries citekey, page, and the verbatim passage.

**Architecture:** `parse_cache.py` wraps the existing `read_pdf` / `read_textlike` of `extract_text.py` with a content-addressed cache: `refs/<key>.parsed.md` plus a `refs/<key>.parsed.meta.json` sidecar carrying the source SHA-256, the backend that produced it, and page offsets when the backend provides them. `corpus_index.py` chunks that cached text deterministically, embeds each chunk through an **injected callable** (default: the local Ollama HTTP endpoint on `127.0.0.1`), and stores the vectors in the `pgvector` Postgres RT-5 already runs. Retrieval returns provenance, never a conclusion.

**This unit was recommended against, then approved by the professor.** The objections were not dismissed; each is answered by a binding constraint below, and the constraints are the reason the unit is safe to build.

**Tech Stack:** Python 3.13, `psycopg` 3, `pgvector`, `requests`, standard library. No cloud embedding API, no new vendor.

## Global Constraints

- Definition files (agents, skills, commands) are **English-only**.
- Style hygiene in any produced text: no em dash, no double or triple dash, straight quotes only, no zero-width or Unicode-tag characters, no single-character ellipsis, no leftover `*` or `#`.
- Python naming and type hints per `.claude/rules/code-style.md`; docstrings in the repo's extended `Purpose: / Inputs: / Outputs:` format.
- Logging: `logging.getLogger(__name__)`, messages prefixed `[CORPUS-INDEX]` and `[PARSE-CACHE]`.
- Dependencies pinned exactly; `pip-audit -r .claude/skills/extract-statistic/scripts/requirements.txt --strict`.

### The four binding constraints, one per objection raised

| Objection raised | Binding constraint |
|---|---|
| It trades a deterministic extractor for a similarity score | **STRICTLY ADDITIVE.** `scan_sections()` and `scan_stats()` are **not modified** and remain the sole source for the statistics and future-works pipelines. The index serves ad-hoc cross-corpus retrieval only, and every hit returns source `citekey`, page, and the verbatim passage so a human verifies before use, matching the `geolocalisation` provenance contract. |
| It breaks offline testability | **The embedder is an injected callable.** Tests pass a deterministic fake and never load a model, staying offline like `test_download_pdf.py` and `test_section_scan.py`. The pgvector store is exercised on a temporary table and **skipped with a clear message** when no database is configured. |
| It adds dependency surface | **No new vendor.** pgvector rides the Postgres already in RT-5's compose; embeddings run on the local Ollama bridge the repo already uses for `local-writer` and `local-coder`. No cloud embedding API, so no corpus text leaves the machine. |
| The real cost is parsing, not retrieval | **The parse cache is folded into this unit**, not deferred, so `extract_text.py` gets the speed benefit whether or not the index is ever built. |

### Two further rules, equally binding

1. **The index build is opt-in and never runs implicitly inside another skill.** No agent, auditor, or researcher triggers a build as a side effect. It is a command a human runs.
2. **A retrieval hit is never a citation.** A passage surfaced by similarity still passes the normal Scopus validation gate before entering any document. Every result object carries this in a `note` field so it cannot be forgotten downstream.

**Depends on:** RT-5 (`feat/uqac-forms-service`), for the `pgvector/pgvector` Postgres in `deploy/docker-compose.yml`. Independent of RT-6. On no critical path: it can land last.

---

## File Structure

**New files**

- `.claude/skills/extract-statistic/scripts/parse_cache.py` - content-addressed parse cache.
- `.claude/skills/extract-statistic/scripts/corpus_index.py` - chunker, embedder seam, pgvector store, `build` / `query` / `status`.
- `.claude/skills/extract-statistic/scripts/Test/test_parse_cache.py` - offline unit tests.
- `.claude/skills/extract-statistic/scripts/Test/test_corpus_index.py` - offline unit tests.

**Modified files**

- `.claude/skills/extract-statistic/scripts/extract_text.py` - route `parse_one` through the cache. `scan_sections` and `scan_stats` are **untouched**.
- `.claude/skills/extract-statistic/scripts/requirements.txt` - `psycopg` and `pgvector` pins, both optional at import time.
- `.claude/skills/extract-statistic/SKILL.md` - a section for the cache and the index, with the two further rules stated verbatim.
- `.claude/rules/testing.md` - the two new offline test commands.
- `.gitignore` - ignore the parse-cache artifacts.

---

## Interfaces consumed

From `extract_text.py` (read, never modified): `read_pdf(path) -> tuple[str, list[list[list[str]]]]`, `read_textlike(path) -> str`, `parse_one(path, stats_scan, include_text, section_scan) -> dict`, `MAX_FILE_BYTES`.

From RT-5: the `db` service of `deploy/docker-compose.yml`, `pgvector/pgvector:pg17`, `vector` extension created by `deploy/initdb/01-pgvector.sql`, reachable at `127.0.0.1:5433` on the host.

---

## Task 1: Content-addressed parse cache

**Files:**

- Create: `.claude/skills/extract-statistic/scripts/parse_cache.py`
- Test: `.claude/skills/extract-statistic/scripts/Test/test_parse_cache.py`

**Interfaces:**

- Consumes: `read_pdf`, `read_textlike` from `extract_text.py`.
- Produces:
  - `source_hash(path: str) -> str` - streamed SHA-256 of the source file.
  - `cache_paths(path: str, cache_dir: str | None = None) -> tuple[str, str]` - `(<key>.parsed.md, <key>.parsed.meta.json)` next to the source unless `cache_dir` is given.
  - `parse_cached(path: str, cache_dir: str | None = None, reader: Callable[[str], tuple[str, list, dict]] | None = None) -> dict[str, Any]` returning `{"text": str, "tables": list, "meta": {...}, "cache_hit": bool}`.
  - Meta shape: `{"source_sha256": str, "source_name": str, "backend": str, "chars": int, "pages": int | None, "page_offsets": list[int] | None, "cached_at": str}`. `page_offsets[i]` is the character offset in `text` where page `i + 1` starts, present only when the backend reports page boundaries.

- [ ] **Step 1: Write the failing test**

Create `.claude/skills/extract-statistic/scripts/Test/test_parse_cache.py`:

```python
"""
test_parse_cache.py - Offline unit tests for parse_cache.py.

No network, no model load, no PDF backend: the reader is injected, so the heavy
Docling and PyMuPDF imports never run. Run with the project Python:
    python .claude/skills/extract-statistic/scripts/Test/test_parse_cache.py
"""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import parse_cache  # noqa: E402


class TestParseCache(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.pdf = os.path.join(self.tmp.name, "otis2025diagnosis.pdf")
        with open(self.pdf, "wb") as handle:
            handle.write(b"%PDF-1.7\noriginal content\n%%EOF")
        self.calls: list = []

        def reader(path: str):
            self.calls.append(path)
            return ("# Introduction\n\nBody text.\n", [[["a", "b"]]],
                    {"backend": "fake", "page_offsets": [0, 16]})
        self.reader = reader

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_the_first_parse_is_a_miss_and_writes_the_cache(self) -> None:
        result = parse_cache.parse_cached(self.pdf, reader=self.reader)
        self.assertFalse(result["cache_hit"])
        md, meta = parse_cache.cache_paths(self.pdf)
        self.assertTrue(os.path.isfile(md))
        self.assertTrue(os.path.isfile(meta))

    def test_the_second_parse_is_a_hit_and_never_calls_the_reader(self) -> None:
        parse_cache.parse_cached(self.pdf, reader=self.reader)
        result = parse_cache.parse_cached(self.pdf, reader=self.reader)
        self.assertTrue(result["cache_hit"])
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(result["text"], "# Introduction\n\nBody text.\n")

    def test_a_changed_source_invalidates_the_cache(self) -> None:
        parse_cache.parse_cached(self.pdf, reader=self.reader)
        with open(self.pdf, "wb") as handle:
            handle.write(b"%PDF-1.7\nDIFFERENT content\n%%EOF")
        result = parse_cache.parse_cached(self.pdf, reader=self.reader)
        self.assertFalse(result["cache_hit"])
        self.assertEqual(len(self.calls), 2)

    def test_the_meta_records_the_source_hash_and_the_backend(self) -> None:
        parse_cache.parse_cached(self.pdf, reader=self.reader)
        _md, meta_path = parse_cache.cache_paths(self.pdf)
        with open(meta_path, encoding="utf-8") as handle:
            meta = json.load(handle)
        self.assertEqual(meta["source_sha256"], parse_cache.source_hash(self.pdf))
        self.assertEqual(meta["backend"], "fake")
        self.assertEqual(meta["page_offsets"], [0, 16])
        self.assertEqual(meta["pages"], 2)

    def test_an_explicit_cache_dir_is_honoured(self) -> None:
        elsewhere = os.path.join(self.tmp.name, "cache")
        parse_cache.parse_cached(self.pdf, cache_dir=elsewhere, reader=self.reader)
        self.assertTrue(os.listdir(elsewhere))
        md, _meta = parse_cache.cache_paths(self.pdf)
        self.assertFalse(os.path.exists(md))

    def test_a_corrupt_meta_file_is_treated_as_a_miss_not_a_crash(self) -> None:
        parse_cache.parse_cached(self.pdf, reader=self.reader)
        _md, meta_path = parse_cache.cache_paths(self.pdf)
        with open(meta_path, "w", encoding="utf-8") as handle:
            handle.write("{not json")
        result = parse_cache.parse_cached(self.pdf, reader=self.reader)
        self.assertFalse(result["cache_hit"])

    def test_tables_survive_the_round_trip(self) -> None:
        parse_cache.parse_cached(self.pdf, reader=self.reader)
        result = parse_cache.parse_cached(self.pdf, reader=self.reader)
        self.assertEqual(result["tables"], [[["a", "b"]]])

    def test_source_hash_is_stable(self) -> None:
        self.assertEqual(parse_cache.source_hash(self.pdf), parse_cache.source_hash(self.pdf))
        self.assertEqual(len(parse_cache.source_hash(self.pdf)), 64)


if __name__ == "__main__":
    unittest.main(verbosity=2)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python .claude/skills/extract-statistic/scripts/Test/test_parse_cache.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'parse_cache'`.

- [ ] **Step 3: Write the minimal implementation**

Create `.claude/skills/extract-statistic/scripts/parse_cache.py`:

```python
"""
parse_cache.py - Content-addressed cache for the expensive PDF parse.

Parsing is the real cost of every text-extraction path in this repo: Docling on
a 20-page paper dwarfs everything the scanners then do. This cache keys the
result on the SHA-256 of the source file, so a re-run of the statistics scan, the
future-works scan, or the corpus index reuses one parse.

The cache is additive: nothing in extract_text.py's scan_sections() or
scan_stats() changes, and a cache miss behaves exactly as before.

Artifacts, next to the source unless a cache directory is given:
  <name>.parsed.md         the extracted text
  <name>.parsed.meta.json  {source_sha256, source_name, backend, chars, pages,
                            page_offsets, tables, cached_at}
"""

import datetime
import hashlib
import json
import logging
import os
from typing import Any, Callable

logger = logging.getLogger(__name__)

CHUNK_BYTES = 8192


def source_hash(path: str) -> str:
    """
    --------------------------------------------------------------------------
    Purpose:
        Hash the source file with SHA-256, streamed.

    Inputs:
        path (str): the source document

    Outputs:
        digest (str): lowercase hexadecimal digest, 64 characters
    --------------------------------------------------------------------------
    """
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK_BYTES), b""):
            digest.update(chunk)
    return digest.hexdigest()


def cache_paths(path: str, cache_dir: str | None = None) -> tuple[str, str]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Locate the two cache artifacts of one source document.

    Inputs:
        path (str): the source document
        cache_dir (str | None): where the artifacts live; next to the source
            when None

    Outputs:
        paths (tuple[str, str]): (markdown path, meta path)
    --------------------------------------------------------------------------
    """
    directory = cache_dir or os.path.dirname(os.path.abspath(path))
    stem = os.path.splitext(os.path.basename(path))[0]
    return (os.path.join(directory, f"{stem}.parsed.md"),
            os.path.join(directory, f"{stem}.parsed.meta.json"))


def _default_reader(path: str) -> tuple[str, list, dict[str, Any]]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Parse a document with the existing extract_text.py backends, adding page
        offsets when PyMuPDF is the backend that ran (it is the only one that
        reports page boundaries).

    Inputs:
        path (str): the source document

    Outputs:
        result (tuple): (text, tables, extra) where extra carries backend and
        page_offsets (page_offsets is None when the backend does not report them)
    --------------------------------------------------------------------------
    """
    import extract_text

    if not path.lower().endswith(".pdf"):
        return extract_text.read_textlike(path), [], {"backend": "textlike",
                                                      "page_offsets": None}

    # Page offsets are only knowable from the plain PyMuPDF path. Docling and
    # pymupdf4llm return one Markdown blob with no page boundaries, so page
    # attribution is best effort and a chunk from those backends reports page
    # None while still carrying its verbatim passage and character offsets.
    offsets: list[int] | None = None
    try:
        import pymupdf  # noqa: F401 (presence check only)
        with pymupdf.open(path) as doc:
            running = 0
            offsets = []
            for page in doc:
                offsets.append(running)
                running += len(page.get_text()) + 1
    except Exception:
        offsets = None

    text, tables = extract_text.read_pdf(path)
    backend = "docling-or-pymupdf4llm-or-pymupdf"
    if offsets is not None and sum(offsets[-1:] or [0]) > len(text):
        offsets = None  # the Markdown backend won: the offsets do not apply
    return text, tables, {"backend": backend, "page_offsets": offsets}


def parse_cached(path: str, cache_dir: str | None = None,
                 reader: Callable[[str], tuple[str, list, dict[str, Any]]] | None = None
                 ) -> dict[str, Any]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Return the parsed text of a document, from cache when the source is
        unchanged. A missing, stale, or unreadable cache entry is a miss, never
        an error: the parse simply runs.

    Inputs:
        path (str): the source document
        cache_dir (str | None): cache location, next to the source when None
        reader (callable | None): injected parser for tests; defaults to the
            extract_text.py backends

    Outputs:
        result (dict): {text, tables, meta, cache_hit}
    --------------------------------------------------------------------------
    """
    md_path, meta_path = cache_paths(path, cache_dir)
    digest = source_hash(path)

    if os.path.isfile(md_path) and os.path.isfile(meta_path):
        try:
            with open(meta_path, encoding="utf-8") as handle:
                meta = json.load(handle)
            if meta.get("source_sha256") == digest:
                with open(md_path, encoding="utf-8") as handle:
                    text = handle.read()
                logger.info("[PARSE-CACHE] hit for %s", os.path.basename(path))
                return {"text": text, "tables": meta.get("tables", []),
                        "meta": meta, "cache_hit": True}
        except (OSError, json.JSONDecodeError):
            logger.info("[PARSE-CACHE] unreadable cache entry for %s, re-parsing",
                        os.path.basename(path))

    text, tables, extra = (reader or _default_reader)(path)
    offsets = extra.get("page_offsets")
    meta = {
        "source_sha256": digest,
        "source_name": os.path.basename(path),
        "backend": extra.get("backend", "unknown"),
        "chars": len(text),
        "pages": len(offsets) if offsets else None,
        "page_offsets": offsets,
        "tables": tables,
        "cached_at": datetime.datetime.now(datetime.timezone.utc)
        .replace(microsecond=0).isoformat(),
    }
    os.makedirs(os.path.dirname(os.path.abspath(md_path)), exist_ok=True)
    with open(md_path, "w", encoding="utf-8") as handle:
        handle.write(text)
    with open(meta_path, "w", encoding="utf-8") as handle:
        json.dump(meta, handle, ensure_ascii=False)
    logger.info("[PARSE-CACHE] miss for %s, cached %d chars", os.path.basename(path), len(text))
    return {"text": text, "tables": tables, "meta": meta, "cache_hit": False}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python .claude/skills/extract-statistic/scripts/Test/test_parse_cache.py`
Expected: PASS, 8 tests.

- [ ] **Step 5: Route `parse_one` through the cache, without touching the scanners**

In `.claude/skills/extract-statistic/scripts/extract_text.py`, inside `parse_one`, replace the read block

```python
        if path.lower().endswith(".pdf"):
            text, tables = read_pdf(path)
        else:
            text, tables = read_textlike(path), []
```

with

```python
        # Additive: the cache only avoids re-parsing an unchanged file. The
        # scanners below are untouched and stay the sole source of truth for the
        # statistics and future-works pipelines.
        import parse_cache
        cached = parse_cache.parse_cached(path)
        text, tables = cached["text"], cached["tables"]
```

Then confirm the existing scanner suite still passes unchanged:

```powershell
python .claude/skills/extract-statistic/scripts/Test/test_section_scan.py
```

Expected: PASS. `scan_sections` and `scan_stats` were not edited.

- [ ] **Step 6: Ignore the cache artifacts**

Append to `.gitignore`:

```
# parse cache: derived from the source PDF, never committed
*.parsed.md
*.parsed.meta.json
```

- [ ] **Step 7: Commit**

```bash
git add .claude/skills/extract-statistic/scripts/parse_cache.py \
        .claude/skills/extract-statistic/scripts/extract_text.py \
        .claude/skills/extract-statistic/scripts/Test/test_parse_cache.py .gitignore
git commit -m "feat(extract-statistic): content-addressed parse cache, additive to the scanners"
```

---

## Task 2: Deterministic chunker with provenance

**Files:**

- Create: `.claude/skills/extract-statistic/scripts/corpus_index.py`
- Test: `.claude/skills/extract-statistic/scripts/Test/test_corpus_index.py`

**Interfaces:**

- Consumes: `parse_cached`, and the meta shape from Task 1.
- Produces:
  - `CHUNK_CHARS: int = 1200`, `CHUNK_OVERLAP: int = 200` module constants.
  - `chunk_text(text: str, citekey: str, page_offsets: list[int] | None = None) -> list[dict[str, Any]]`, each chunk `{"citekey", "chunk_index", "char_start", "char_end", "page", "heading", "passage"}`. `page` is `None` when the backend gave no offsets.
  - Chunking is deterministic: the same text yields byte-identical chunks on every run and on every machine.

- [ ] **Step 1: Write the failing test**

Create `.claude/skills/extract-statistic/scripts/Test/test_corpus_index.py`:

```python
"""
test_corpus_index.py - Offline unit tests for corpus_index.py.

No network, no model load, no database unless CORPUS_INDEX_DSN is set: the
embedder is injected as a deterministic fake, and the pgvector tests skip with a
clear message when no database is configured. Run with the project Python:
    python .claude/skills/extract-statistic/scripts/Test/test_corpus_index.py
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import corpus_index  # noqa: E402


LONG_TEXT = (
    "# Introduction\n\n"
    + "Le diagnostic industriel repose sur des mesures vibratoires. " * 40
    + "\n\n# Methode\n\n"
    + "Un reseau convolutif classe les signatures spectrales. " * 40
)


class TestChunker(unittest.TestCase):
    def test_a_short_text_is_one_chunk(self) -> None:
        chunks = corpus_index.chunk_text("Short body.", "otis2025diagnosis")
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0]["passage"], "Short body.")

    def test_a_long_text_is_split_with_overlap(self) -> None:
        chunks = corpus_index.chunk_text(LONG_TEXT, "otis2025diagnosis")
        self.assertGreater(len(chunks), 1)
        for previous, current in zip(chunks, chunks[1:]):
            self.assertLess(current["char_start"], previous["char_end"],
                            "consecutive chunks must overlap")

    def test_chunking_is_deterministic(self) -> None:
        first = corpus_index.chunk_text(LONG_TEXT, "otis2025diagnosis")
        second = corpus_index.chunk_text(LONG_TEXT, "otis2025diagnosis")
        self.assertEqual(first, second)

    def test_every_chunk_carries_its_citekey_and_offsets(self) -> None:
        for chunk in corpus_index.chunk_text(LONG_TEXT, "otis2025diagnosis"):
            self.assertEqual(chunk["citekey"], "otis2025diagnosis")
            self.assertLess(chunk["char_start"], chunk["char_end"])

    def test_the_passage_is_verbatim_from_the_source(self) -> None:
        for chunk in corpus_index.chunk_text(LONG_TEXT, "otis2025diagnosis"):
            self.assertEqual(LONG_TEXT[chunk["char_start"]:chunk["char_end"]],
                             chunk["passage"])

    def test_the_nearest_preceding_heading_is_recorded(self) -> None:
        chunks = corpus_index.chunk_text(LONG_TEXT, "otis2025diagnosis")
        self.assertEqual(chunks[0]["heading"], "Introduction")
        self.assertIn("Methode", {c["heading"] for c in chunks})

    def test_page_is_none_when_the_backend_gave_no_offsets(self) -> None:
        chunks = corpus_index.chunk_text(LONG_TEXT, "otis2025diagnosis", page_offsets=None)
        self.assertTrue(all(c["page"] is None for c in chunks))

    def test_page_is_attributed_from_the_offsets_when_available(self) -> None:
        offsets = [0, len(LONG_TEXT) // 2]
        chunks = corpus_index.chunk_text(LONG_TEXT, "otis2025diagnosis", page_offsets=offsets)
        self.assertEqual(chunks[0]["page"], 1)
        self.assertEqual(chunks[-1]["page"], 2)

    def test_an_empty_text_yields_no_chunk(self) -> None:
        self.assertEqual(corpus_index.chunk_text("   \n  ", "otis2025diagnosis"), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python .claude/skills/extract-statistic/scripts/Test/test_corpus_index.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'corpus_index'`.

- [ ] **Step 3: Write the minimal implementation**

Create `.claude/skills/extract-statistic/scripts/corpus_index.py`:

```python
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

import argparse
import json
import logging
import os
import re
from typing import Any, Callable

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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python .claude/skills/extract-statistic/scripts/Test/test_corpus_index.py`
Expected: PASS, 9 tests.

- [ ] **Step 5: Commit**

```bash
git add .claude/skills/extract-statistic/scripts/corpus_index.py \
        .claude/skills/extract-statistic/scripts/Test/test_corpus_index.py
git commit -m "feat(corpus-index): deterministic chunker carrying full provenance"
```

---

## Task 3: Embedder seam and pgvector store

**Files:**

- Modify: `.claude/skills/extract-statistic/scripts/corpus_index.py`
- Modify: `.claude/skills/extract-statistic/scripts/requirements.txt`
- Test: `.claude/skills/extract-statistic/scripts/Test/test_corpus_index.py`

**Interfaces:**

- Consumes: `chunk_text` from Task 2.
- Produces:
  - `Embedder = Callable[[list[str]], list[list[float]]]` type alias.
  - `ollama_embedder(model: str = "nomic-embed-text", endpoint: str = "http://127.0.0.1:11434/api/embed") -> Embedder`, the default. Local HTTP only, so no corpus text leaves the machine.
  - `class VectorStore` with `VectorStore(dsn: str, table: str = "corpus_chunks")`, methods `ensure_schema(dim: int) -> None`, `upsert(chunks: list[dict], vectors: list[list[float]]) -> int`, `search(vector: list[float], top: int) -> list[dict]`, `stats() -> dict`, `drop() -> None`.
  - `resolve_dsn(explicit: str | None = None) -> str | None` reading `CORPUS_INDEX_DSN`, returning `None` when unset.

- [ ] **Step 1: Write the failing test**

Append to `.claude/skills/extract-statistic/scripts/Test/test_corpus_index.py`, above the `if __name__` block:

```python
def fake_embedder(dim: int = 8):
    """Deterministic embedder: no model, no network, stable across machines."""
    def embed(texts: list[str]) -> list[list[float]]:
        vectors = []
        for text in texts:
            digest = [0.0] * dim
            for position, char in enumerate(text):
                digest[position % dim] += (ord(char) % 17) / 100.0
            vectors.append(digest)
        return vectors
    return embed


class TestEmbedderSeam(unittest.TestCase):
    def test_the_fake_embedder_is_deterministic(self) -> None:
        embed = fake_embedder()
        self.assertEqual(embed(["hello"]), embed(["hello"]))

    def test_embed_chunks_returns_one_vector_per_chunk(self) -> None:
        chunks = corpus_index.chunk_text(LONG_TEXT, "otis2025diagnosis")
        vectors = corpus_index.embed_chunks(chunks, fake_embedder())
        self.assertEqual(len(vectors), len(chunks))
        self.assertEqual(len(vectors[0]), 8)

    def test_embed_chunks_batches_without_changing_the_order(self) -> None:
        chunks = corpus_index.chunk_text(LONG_TEXT, "otis2025diagnosis")
        one = corpus_index.embed_chunks(chunks, fake_embedder(), batch_size=1)
        many = corpus_index.embed_chunks(chunks, fake_embedder(), batch_size=100)
        self.assertEqual(one, many)

    def test_the_default_embedder_targets_the_local_endpoint_only(self) -> None:
        # No corpus text may leave the machine: the default endpoint is loopback.
        self.assertIn("127.0.0.1", corpus_index.DEFAULT_EMBED_ENDPOINT)


@unittest.skipUnless(
    os.environ.get("CORPUS_INDEX_DSN"),
    "CORPUS_INDEX_DSN is not set: skipping the pgvector store tests. Start the "
    "RT-5 compose stack and export "
    "CORPUS_INDEX_DSN=postgresql://uqac:...@127.0.0.1:5433/uqac to run them.")
class TestVectorStore(unittest.TestCase):
    def setUp(self) -> None:
        self.store = corpus_index.VectorStore(
            os.environ["CORPUS_INDEX_DSN"], table="corpus_chunks_test")
        self.store.ensure_schema(dim=8)
        self.chunks = corpus_index.chunk_text(LONG_TEXT, "otis2025diagnosis")
        self.vectors = corpus_index.embed_chunks(self.chunks, fake_embedder())

    def tearDown(self) -> None:
        self.store.drop()

    def test_upsert_then_stats_counts_the_chunks(self) -> None:
        self.store.upsert(self.chunks, self.vectors)
        self.assertEqual(self.store.stats()["chunks"], len(self.chunks))

    def test_upserting_twice_does_not_duplicate(self) -> None:
        self.store.upsert(self.chunks, self.vectors)
        self.store.upsert(self.chunks, self.vectors)
        self.assertEqual(self.store.stats()["chunks"], len(self.chunks))

    def test_search_returns_provenance_not_a_conclusion(self) -> None:
        self.store.upsert(self.chunks, self.vectors)
        hits = self.store.search(self.vectors[0], top=3)
        self.assertTrue(hits)
        for hit in hits:
            self.assertIn("citekey", hit)
            self.assertIn("passage", hit)
            self.assertIn("page", hit)
            self.assertIn("char_start", hit)

    def test_the_verbatim_passage_survives_the_round_trip(self) -> None:
        self.store.upsert(self.chunks, self.vectors)
        hits = self.store.search(self.vectors[0], top=1)
        self.assertEqual(hits[0]["passage"], self.chunks[0]["passage"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python .claude/skills/extract-statistic/scripts/Test/test_corpus_index.py`
Expected: FAIL with `AttributeError: module 'corpus_index' has no attribute 'embed_chunks'`. The `TestVectorStore` class reports as skipped with the message naming `CORPUS_INDEX_DSN`.

- [ ] **Step 3: Add the pins**

In `.claude/skills/extract-statistic/scripts/requirements.txt`, add:

```
# corpus_index.py (OPTIONAL, RT-7): pgvector store and the local embedder.
# Both degrade gracefully when absent: the chunker and the parse cache work
# without them, and the index simply reports itself unavailable.
psycopg[binary]==3.3.4
pgvector==0.5.0
```

Then:

```powershell
pip install -r .claude/skills/extract-statistic/scripts/requirements.txt
pip-audit -r .claude/skills/extract-statistic/scripts/requirements.txt --strict
```

- [ ] **Step 4: Write the minimal implementation**

Append to `.claude/skills/extract-statistic/scripts/corpus_index.py`:

```python
Embedder = Callable[[list[str]], list[list[float]]]

DEFAULT_EMBED_MODEL = "nomic-embed-text"
# Loopback only. No corpus text leaves the machine, so there is no cloud
# embedding vendor and no data-residency question under Law 25.
DEFAULT_EMBED_ENDPOINT = "http://127.0.0.1:11434/api/embed"
DEFAULT_BATCH_SIZE = 16


def ollama_embedder(model: str = DEFAULT_EMBED_MODEL,
                    endpoint: str = DEFAULT_EMBED_ENDPOINT) -> Embedder:
    """
    --------------------------------------------------------------------------
    Purpose:
        Build the default embedder: the local Ollama HTTP endpoint the repo
        already runs for local-writer and local-coder.

    Inputs:
        model (str): the local embedding model
        endpoint (str): the loopback embedding endpoint

    Outputs:
        embed (Embedder): texts to vectors

    Raises (at call time):
        RuntimeError with an actionable message when Ollama is unreachable.
    --------------------------------------------------------------------------
    """
    import requests

    def embed(texts: list[str]) -> list[list[float]]:
        try:
            response = requests.post(endpoint, json={"model": model, "input": texts},
                                     timeout=120)
            response.raise_for_status()
        except Exception as exc:
            raise RuntimeError(
                f"the local embedder at {endpoint} is unreachable: {exc}. Start "
                f"Ollama and pull the model with: ollama pull {model}") from exc
        payload = response.json()
        vectors = payload.get("embeddings") or payload.get("data") or []
        if len(vectors) != len(texts):
            raise RuntimeError(
                f"the embedder returned {len(vectors)} vector(s) for {len(texts)} input(s)")
        return [list(map(float, v)) for v in vectors]

    return embed


def embed_chunks(chunks: list[dict[str, Any]], embedder: Embedder,
                 batch_size: int = DEFAULT_BATCH_SIZE) -> list[list[float]]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Embed every chunk, in batches, preserving order so vector i belongs to
        chunk i.

    Inputs:
        chunks (list[dict]): as returned by chunk_text
        embedder (Embedder): the injected embedding callable
        batch_size (int): how many passages per call

    Outputs:
        vectors (list[list[float]]): one vector per chunk, in order
    --------------------------------------------------------------------------
    """
    vectors: list[list[float]] = []
    for start in range(0, len(chunks), max(1, batch_size)):
        window = [c["passage"] for c in chunks[start:start + batch_size]]
        vectors.extend(embedder(window))
    return vectors


def resolve_dsn(explicit: str | None = None) -> str | None:
    """
    --------------------------------------------------------------------------
    Purpose:
        Resolve the Postgres connection string, preferring an explicit value.

    Inputs:
        explicit (str | None): a value from the command line

    Outputs:
        dsn (str | None): the connection string, or None when unconfigured
    --------------------------------------------------------------------------
    """
    return explicit or os.environ.get("CORPUS_INDEX_DSN") or None


class VectorStore:
    """
    The pgvector store. It rides the Postgres RT-5's compose already runs, so no
    vector vendor is introduced. Every stored row keeps the provenance the
    retrieval contract requires.
    """

    def __init__(self, dsn: str, table: str = "corpus_chunks") -> None:
        self.dsn = dsn
        # The table name is a code-controlled identifier, never user input; it is
        # validated here so it can be interpolated into DDL safely.
        if not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", table):
            raise ValueError(f"invalid table name: {table!r}")
        self.table = table

    def _connect(self):
        import psycopg
        return psycopg.connect(self.dsn)

    def ensure_schema(self, dim: int) -> None:
        """
        ----------------------------------------------------------------------
        Purpose:
            Create the extension, the table, and the similarity index.

        Inputs:
            dim (int): embedding dimension

        Outputs:
            none
        ----------------------------------------------------------------------
        """
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
            cur.execute(f"""
                CREATE TABLE IF NOT EXISTS {self.table} (
                    citekey     text NOT NULL,
                    chunk_index int  NOT NULL,
                    char_start  int  NOT NULL,
                    char_end    int  NOT NULL,
                    page        int,
                    heading     text,
                    passage     text NOT NULL,
                    embedding   vector({dim}) NOT NULL,
                    indexed_at  timestamptz NOT NULL DEFAULT now(),
                    PRIMARY KEY (citekey, chunk_index)
                )""")
            cur.execute(f"""
                CREATE INDEX IF NOT EXISTS {self.table}_embedding_idx
                ON {self.table} USING hnsw (embedding vector_cosine_ops)""")
            conn.commit()

    def upsert(self, chunks: list[dict[str, Any]], vectors: list[list[float]]) -> int:
        """
        ----------------------------------------------------------------------
        Purpose:
            Store or replace the chunks of one or more documents. Re-indexing a
            document overwrites its rows rather than duplicating them.

        Inputs:
            chunks (list[dict]): as returned by chunk_text
            vectors (list[list[float]]): one vector per chunk, in order

        Outputs:
            written (int): number of rows written
        ----------------------------------------------------------------------
        """
        if len(chunks) != len(vectors):
            raise ValueError(f"{len(chunks)} chunk(s) but {len(vectors)} vector(s)")
        rows = [(c["citekey"], c["chunk_index"], c["char_start"], c["char_end"],
                 c["page"], c["heading"], c["passage"],
                 "[" + ",".join(f"{v:.6f}" for v in vec) + "]")
                for c, vec in zip(chunks, vectors)]
        with self._connect() as conn, conn.cursor() as cur:
            cur.executemany(f"""
                INSERT INTO {self.table}
                  (citekey, chunk_index, char_start, char_end, page, heading,
                   passage, embedding)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s::vector)
                ON CONFLICT (citekey, chunk_index) DO UPDATE SET
                  char_start = EXCLUDED.char_start, char_end = EXCLUDED.char_end,
                  page = EXCLUDED.page, heading = EXCLUDED.heading,
                  passage = EXCLUDED.passage, embedding = EXCLUDED.embedding,
                  indexed_at = now()""", rows)
            conn.commit()
        logger.info("[CORPUS-INDEX] stored %d chunk(s)", len(rows))
        return len(rows)

    def search(self, vector: list[float], top: int) -> list[dict[str, Any]]:
        """
        ----------------------------------------------------------------------
        Purpose:
            Return the nearest chunks by cosine distance, each with its full
            provenance and the standing reminder that a hit is not a citation.

        Inputs:
            vector (list[float]): the query embedding
            top (int): how many hits

        Outputs:
            hits (list[dict]): {citekey, page, heading, char_start, char_end,
            passage, distance, note}
        ----------------------------------------------------------------------
        """
        literal = "[" + ",".join(f"{v:.6f}" for v in vector) + "]"
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(f"""
                SELECT citekey, chunk_index, char_start, char_end, page, heading,
                       passage, embedding <=> %s::vector AS distance
                FROM {self.table}
                ORDER BY embedding <=> %s::vector
                LIMIT %s""", (literal, literal, top))
            rows = cur.fetchall()
        return [{
            "citekey": r[0], "chunk_index": r[1], "char_start": r[2], "char_end": r[3],
            "page": r[4], "heading": r[5], "passage": r[6], "distance": float(r[7]),
            "note": NOT_A_CITATION,
        } for r in rows]

    def stats(self) -> dict[str, Any]:
        """Row and document counts, for the status command."""
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(f"SELECT count(*), count(DISTINCT citekey) FROM {self.table}")
            chunks, documents = cur.fetchone()
        return {"table": self.table, "chunks": int(chunks), "documents": int(documents)}

    def drop(self) -> None:
        """Remove the table. Used by the tests, and by a deliberate rebuild."""
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(f"DROP TABLE IF EXISTS {self.table}")
            conn.commit()
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python .claude/skills/extract-statistic/scripts/Test/test_corpus_index.py`
Expected: PASS with the four embedder tests green and the five store tests **skipped**, printing the `CORPUS_INDEX_DSN` message.

- [ ] **Step 6: Run the store tests against the real database**

```powershell
docker compose -f deploy/docker-compose.yml --env-file deploy/.env up -d db
$env:CORPUS_INDEX_DSN = "postgresql://uqac:<password>@127.0.0.1:5433/uqac"
python .claude/skills/extract-statistic/scripts/Test/test_corpus_index.py
```

Expected: 13 tests pass, none skipped. The test table `corpus_chunks_test` is dropped in `tearDown`, so nothing is left behind.

- [ ] **Step 7: Commit**

```bash
git add .claude/skills/extract-statistic/scripts/corpus_index.py \
        .claude/skills/extract-statistic/scripts/requirements.txt \
        .claude/skills/extract-statistic/scripts/Test/test_corpus_index.py
git commit -m "feat(corpus-index): injected embedder seam and pgvector store with provenance"
```

---

## Task 4: build, query, status

**Files:**

- Modify: `.claude/skills/extract-statistic/scripts/corpus_index.py`
- Modify: `.claude/skills/extract-statistic/SKILL.md`
- Modify: `.claude/rules/testing.md`
- Test: `.claude/skills/extract-statistic/scripts/Test/test_corpus_index.py`

**Interfaces:**

- Consumes: everything above, plus `bib_batch` (already imported by `litreview_update.py`) for the `.bib` parse, and `parse_cache.parse_cached`.
- Produces:
  - `build_index(bib_path: str, refs_dir: str, store: VectorStore, embedder: Embedder, cache_dir: str | None = None) -> dict[str, Any]` returning `{"documents": int, "chunks": int, "missing": list[str], "cache_hits": int}`. `missing` lists the citekeys with no retrievable full text; they are reported, never silently dropped.
  - CLI `build` / `query` / `status`.

- [ ] **Step 1: Write the failing test**

Append to `.claude/skills/extract-statistic/scripts/Test/test_corpus_index.py`, above the `if __name__` block:

```python
import tempfile  # noqa: E402


class _RecordingStore:
    """Stand-in for VectorStore: no database, records what it was given."""

    def __init__(self) -> None:
        self.rows: list = []
        self.dim: int | None = None

    def ensure_schema(self, dim: int) -> None:
        self.dim = dim

    def upsert(self, chunks, vectors) -> int:
        self.rows.extend(zip(chunks, vectors))
        return len(chunks)


class TestBuildIndex(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.refs = os.path.join(self.tmp.name, "refs")
        os.makedirs(self.refs, exist_ok=True)
        self.bib = os.path.join(self.tmp.name, "corpus.bib")
        with open(self.bib, "w", encoding="utf-8") as handle:
            handle.write(
                "@article{otis2025diagnosis,\n  title = {Diagnostic industriel},\n"
                "  doi = {10.1109/TRO.2025.000001}\n}\n"
                "@article{absent2024missing,\n  title = {Sans texte integral},\n"
                "  doi = {10.9999/x}\n}\n")
        with open(os.path.join(self.refs, "otis2025diagnosis.parsed.md"), "w",
                  encoding="utf-8") as handle:
            handle.write(LONG_TEXT)
        with open(os.path.join(self.refs, "otis2025diagnosis.parsed.meta.json"), "w",
                  encoding="utf-8") as handle:
            handle.write('{"source_sha256": "x", "page_offsets": null, "tables": []}')

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_it_indexes_the_documents_it_can_read(self) -> None:
        store = _RecordingStore()
        result = corpus_index.build_index(self.bib, self.refs, store, fake_embedder())
        self.assertEqual(result["documents"], 1)
        self.assertGreater(result["chunks"], 0)

    def test_a_document_with_no_full_text_is_reported_never_silently_dropped(self) -> None:
        store = _RecordingStore()
        result = corpus_index.build_index(self.bib, self.refs, store, fake_embedder())
        self.assertEqual(result["missing"], ["absent2024missing"])

    def test_every_stored_chunk_carries_the_citekey_of_its_source(self) -> None:
        store = _RecordingStore()
        corpus_index.build_index(self.bib, self.refs, store, fake_embedder())
        self.assertEqual({chunk["citekey"] for chunk, _ in store.rows},
                         {"otis2025diagnosis"})

    def test_the_schema_dimension_comes_from_the_embedder(self) -> None:
        store = _RecordingStore()
        corpus_index.build_index(self.bib, self.refs, store, fake_embedder(dim=8))
        self.assertEqual(store.dim, 8)

    def test_an_empty_corpus_reports_zero_rather_than_raising(self) -> None:
        empty = os.path.join(self.tmp.name, "empty.bib")
        with open(empty, "w", encoding="utf-8") as handle:
            handle.write("")
        store = _RecordingStore()
        result = corpus_index.build_index(empty, self.refs, store, fake_embedder())
        self.assertEqual(result["documents"], 0)
        self.assertEqual(result["chunks"], 0)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python .claude/skills/extract-statistic/scripts/Test/test_corpus_index.py`
Expected: FAIL with `AttributeError: module 'corpus_index' has no attribute 'build_index'`.

- [ ] **Step 3: Write the minimal implementation**

Append to `.claude/skills/extract-statistic/scripts/corpus_index.py`:

```python
_BIB_KEY_RE = re.compile(r"@\w+\s*\{\s*([^,\s]+)\s*,")

_FULLTEXT_EXTENSIONS = (".parsed.md", ".pdf", ".html", ".md", ".txt")


def _citekeys(bib_path: str) -> list[str]:
    """Every citekey of a .bib file, in file order."""
    if not os.path.isfile(bib_path):
        raise FileNotFoundError(f"bib file not found: {bib_path}")
    with open(bib_path, encoding="utf-8", errors="replace") as handle:
        return _BIB_KEY_RE.findall(handle.read())


def _fulltext_for(citekey: str, refs_dir: str) -> str | None:
    """The first retrievable full-text artifact of a citekey, or None."""
    for extension in _FULLTEXT_EXTENSIONS:
        candidate = os.path.join(refs_dir, f"{citekey}{extension}")
        if os.path.isfile(candidate):
            return candidate
    return None


def build_index(bib_path: str, refs_dir: str, store: Any, embedder: Embedder,
                cache_dir: str | None = None) -> dict[str, Any]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Index a corpus: for each citekey of the .bib, read its full text through
        the parse cache, chunk it, embed the chunks, and store them.

        This is OPT-IN and is never called from another skill. A citekey with no
        retrievable full text is reported in `missing`, never silently dropped,
        because a silently short corpus is a wrong corpus.

    Inputs:
        bib_path (str): the corpus .bib
        refs_dir (str): the refs/ directory holding the retrieved full texts
        store (VectorStore): the destination store
        embedder (Embedder): the injected embedding callable
        cache_dir (str | None): parse-cache location, next to the source when None

    Outputs:
        result (dict): {documents, chunks, missing, cache_hits}
    --------------------------------------------------------------------------
    """
    import parse_cache

    keys = _citekeys(bib_path)
    missing: list[str] = []
    documents = 0
    total_chunks = 0
    cache_hits = 0
    dim_set = False

    for citekey in keys:
        source = _fulltext_for(citekey, refs_dir)
        if source is None:
            missing.append(citekey)
            continue

        if source.endswith(".parsed.md"):
            with open(source, encoding="utf-8") as handle:
                text = handle.read()
            offsets = None
            meta_path = source.replace(".parsed.md", ".parsed.meta.json")
            if os.path.isfile(meta_path):
                try:
                    with open(meta_path, encoding="utf-8") as handle:
                        offsets = json.load(handle).get("page_offsets")
                except (OSError, json.JSONDecodeError):
                    offsets = None
            cache_hits += 1
        else:
            parsed = parse_cache.parse_cached(source, cache_dir)
            text = parsed["text"]
            offsets = parsed["meta"].get("page_offsets")
            cache_hits += 1 if parsed["cache_hit"] else 0

        chunks = chunk_text(text, citekey, offsets)
        if not chunks:
            missing.append(citekey)
            continue

        vectors = embed_chunks(chunks, embedder)
        if not dim_set:
            store.ensure_schema(len(vectors[0]))
            dim_set = True
        store.upsert(chunks, vectors)
        documents += 1
        total_chunks += len(chunks)

    logger.info("[CORPUS-INDEX] indexed %d document(s), %d chunk(s), %d without full text",
                documents, total_chunks, len(missing))
    return {"documents": documents, "chunks": total_chunks,
            "missing": missing, "cache_hits": cache_hits}


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(
        description="Opt-in corpus index. A retrieval hit is provenance, never a citation.")
    sub = parser.add_subparsers(dest="mode", required=True)

    p_build = sub.add_parser("build", help="index a corpus (opt-in, never implicit)")
    p_build.add_argument("--bib", required=True)
    p_build.add_argument("--refs", default=None, help="refs/ directory (default next to the .bib)")
    p_build.add_argument("--dsn", default=None)
    p_build.add_argument("--table", default="corpus_chunks")
    p_build.add_argument("--model", default=DEFAULT_EMBED_MODEL)

    p_query = sub.add_parser("query", help="retrieve passages with full provenance")
    p_query.add_argument("question")
    p_query.add_argument("--top", type=int, default=8)
    p_query.add_argument("--dsn", default=None)
    p_query.add_argument("--table", default="corpus_chunks")
    p_query.add_argument("--model", default=DEFAULT_EMBED_MODEL)

    p_status = sub.add_parser("status", help="report what is indexed")
    p_status.add_argument("--dsn", default=None)
    p_status.add_argument("--table", default="corpus_chunks")

    args = parser.parse_args()
    dsn = resolve_dsn(args.dsn)
    if dsn is None:
        raise SystemExit(
            "no database configured: set CORPUS_INDEX_DSN or pass --dsn. Start the "
            "stack with: docker compose -f deploy/docker-compose.yml up -d db")
    store = VectorStore(dsn, table=args.table)

    if args.mode == "status":
        print(json.dumps(store.stats(), indent=2, ensure_ascii=False))
        return

    embedder = ollama_embedder(model=args.model)

    if args.mode == "build":
        refs = args.refs or os.path.join(os.path.dirname(os.path.abspath(args.bib)), "refs")
        result = build_index(args.bib, refs, store, embedder)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        if result["missing"]:
            logger.warning("[CORPUS-INDEX] %d citekey(s) had no retrievable full text: %s",
                           len(result["missing"]), ", ".join(result["missing"]))
        return

    vector = embedder([args.question])[0]
    hits = store.search(vector, args.top)
    print(json.dumps({"question": args.question, "hits": hits,
                      "note": NOT_A_CITATION}, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python .claude/skills/extract-statistic/scripts/Test/test_corpus_index.py`
Expected: PASS, 18 tests (5 skipped without `CORPUS_INDEX_DSN`).

- [ ] **Step 5: Verify end to end against a real corpus**

```powershell
docker compose -f deploy/docker-compose.yml --env-file deploy/.env up -d db
$env:CORPUS_INDEX_DSN = "postgresql://uqac:<password>@127.0.0.1:5433/uqac"
ollama pull nomic-embed-text
python .claude/skills/extract-statistic/scripts/corpus_index.py build --bib <corpus.bib>
python .claude/skills/extract-statistic/scripts/corpus_index.py status
python .claude/skills/extract-statistic/scripts/corpus_index.py query "controle adaptatif de cable" --top 5
```

Expected: `build` reports the document and chunk counts plus every citekey without full text; `status` reports the same totals; `query` returns five hits, each with a citekey, a page (or `null`), the verbatim passage, and the `note` field saying a hit is not a citation. Open one hit's source and confirm the passage is present verbatim.

- [ ] **Step 6: Update SKILL.md**

Add to `.claude/skills/extract-statistic/SKILL.md`:

````markdown
## Parse cache

`parse_cache.py` caches the expensive PDF parse keyed by the source SHA-256, as
`<name>.parsed.md` plus a `<name>.parsed.meta.json` sidecar. `parse_one` reads
through it, so a repeated statistics scan or future-works scan on an unchanged
file costs no parse. The cache is additive: `scan_sections()` and `scan_stats()`
are unchanged and a cache miss behaves exactly as before.

## Corpus index (opt-in)

`corpus_index.py` indexes a corpus for ad-hoc cross-corpus retrieval.

```
python .claude/skills/extract-statistic/scripts/corpus_index.py build --bib <corpus.bib>
python .claude/skills/extract-statistic/scripts/corpus_index.py query "<question>" --top 8
python .claude/skills/extract-statistic/scripts/corpus_index.py status
```

Four rules, none negotiable:

1. Strictly additive. `scan_sections()` and `scan_stats()` are not modified and
   remain the sole source for the statistics and future-works pipelines. The
   index never feeds them.
2. Every hit returns the source citekey, the page, and the verbatim passage, so
   a human verifies before use. Same provenance contract as `geolocalisation`.
3. The build is opt-in and never runs implicitly inside another skill.
4. **A retrieval hit is never a citation.** A passage surfaced by similarity
   still passes the normal Scopus validation gate before entering any document.

The embedder is injected and defaults to the local Ollama endpoint on
`127.0.0.1`, so no corpus text leaves the machine. The store is the pgvector
Postgres of `deploy/docker-compose.yml`; set `CORPUS_INDEX_DSN` to reach it.
````

- [ ] **Step 7: Update `.claude/rules/testing.md`**

Add:

```powershell
python .claude/skills/extract-statistic/scripts/Test/test_parse_cache.py    # cache hit, miss, invalidation, meta
python .claude/skills/extract-statistic/scripts/Test/test_corpus_index.py   # chunker, embedder seam, build; store tests skip without CORPUS_INDEX_DSN
```

and extend the script-surface paragraph: `parse_cache.py` (content-addressed parse cache, additive) and `corpus_index.py` (opt-in chunk, embed, pgvector store; injected embedder so tests stay offline).

- [ ] **Step 8: Run the full offline suite (no regression)**

```powershell
python .claude/skills/extract-statistic/scripts/Test/test_parse_cache.py
python .claude/skills/extract-statistic/scripts/Test/test_corpus_index.py
python .claude/skills/extract-statistic/scripts/Test/test_section_scan.py
python .claude/skills/scopus/scripts/Test/test_download_pdf.py
python .claude/skills/scopus/scripts/Test/test_browser_fetch.py
python .claude/skills/scopus/scripts/Test/test_bib_batch.py
python .claude/skills/scopus/scripts/Test/test_litreview_update.py
```

Expected: all pass. `test_section_scan.py` in particular must be green with no edit, which is the proof that this unit stayed additive.

- [ ] **Step 9: Commit**

```bash
git add .claude/skills/extract-statistic .claude/rules/testing.md
git commit -m "feat(corpus-index): opt-in build, query, and status over the pgvector store"
```

---

## Interfaces published by RT-7

| Name | Signature | Notes |
|---|---|---|
| `parse_cache.source_hash` | `source_hash(path: str) -> str` | streamed SHA-256 |
| `parse_cache.cache_paths` | `cache_paths(path: str, cache_dir: str \| None = None) -> tuple[str, str]` | markdown and meta paths |
| `parse_cache.parse_cached` | `parse_cached(path, cache_dir=None, reader=None) -> {"text", "tables", "meta", "cache_hit"}` | consumed by `extract_text.parse_one` |
| `corpus_index.chunk_text` | `chunk_text(text: str, citekey: str, page_offsets: list[int] \| None = None) -> list[dict]` | deterministic |
| `corpus_index.embed_chunks` | `embed_chunks(chunks, embedder, batch_size=16) -> list[list[float]]` | order preserving |
| `corpus_index.ollama_embedder` | `ollama_embedder(model=..., endpoint=DEFAULT_EMBED_ENDPOINT) -> Embedder` | loopback only |
| `corpus_index.VectorStore` | `VectorStore(dsn: str, table: str = "corpus_chunks")` | `ensure_schema`, `upsert`, `search`, `stats`, `drop` |
| `corpus_index.build_index` | `build_index(bib_path, refs_dir, store, embedder, cache_dir=None) -> {"documents", "chunks", "missing", "cache_hits"}` | opt-in only |
| `corpus_index.NOT_A_CITATION` | `str` | carried in every hit's `note` |

Chunk shape: `{"citekey": str, "chunk_index": int, "char_start": int, "char_end": int, "page": int | None, "heading": str, "passage": str}`.
Hit shape: the chunk shape plus `"distance": float` and `"note": NOT_A_CITATION`.

---

## Acceptance

```powershell
python .claude/skills/extract-statistic/scripts/Test/test_parse_cache.py
python .claude/skills/extract-statistic/scripts/Test/test_corpus_index.py
python .claude/skills/extract-statistic/scripts/Test/test_section_scan.py   # must pass UNCHANGED
pip-audit -r .claude/skills/extract-statistic/scripts/requirements.txt --strict
```

With the stack running, the five store tests must also pass:

```powershell
$env:CORPUS_INDEX_DSN = "postgresql://uqac:<password>@127.0.0.1:5433/uqac"
python .claude/skills/extract-statistic/scripts/Test/test_corpus_index.py
```
