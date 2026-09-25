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
        offsets when PyMuPDF is the resolved backend (it is the only one that
        reports page boundaries).

    Details:
        Goes through extract_text.pymupdf rather than a fresh `import pymupdf`:
        that module already resolves the package under its legacy `fitz` name
        when the real one is absent, and a bare re-import here would silently
        lose page offsets (raising ModuleNotFoundError, caught below) on any
        machine where only the fitz alias resolves.

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
    pymupdf = getattr(extract_text, "pymupdf", None)
    if pymupdf is not None:
        try:
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
