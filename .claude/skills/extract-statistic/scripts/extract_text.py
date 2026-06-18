"""
extract_text.py - Full-text extraction and statistics scanning for the
extract-statistic skill.

Stage: post-retrieval parsing. Turns a local PDF (or an HTML / plaintext
full-text file) into analyzable text plus a list of statistics candidates, so
the audit and corpus-mining modes of the extract-statistic skill can reason over
what a paper actually reports. For a .bib input it reuses
.claude/skills/scopus/scripts/download_pdf.py to ensure each PDF is present
(presence-gated, no re-download) before parsing - it never reimplements
downloading.

Modes:
  pdf  <file.pdf>                         parse one local PDF
  text <file.html|.txt|.tex|.md>          strip/read one text file
  bib  <file.bib> [--latex M] [--out-dir] ensure each DOI's PDF (download_pdf.py)
                                          then parse every present PDF

Common flag --stats-scan adds a regex pass that tags p-values, sample sizes,
mean +/- SD, named tests, confidence intervals, effect sizes, ML metrics, and
reproducibility signals (seeds, cross-validation). Output is JSON on stdout. By
default the heavy full text is summarized (char count + table previews +
candidates with context); pass --include-text to emit the full extracted text.

See .claude/rules/security.md for the input-validation and file-size rules this
script follows.
"""

import argparse
import contextlib
import io
import json
import logging
import os
import re
import sys
from typing import Any

logger = logging.getLogger(__name__)

# Reuse the scopus skill's downloader for the bib mode (presence-gated).
_SCOPUS_SCRIPTS = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "scopus", "scripts")
)
sys.path.insert(0, _SCOPUS_SCRIPTS)
try:
    import download_pdf as dl
except ImportError:  # pragma: no cover - bib mode simply unavailable without it
    dl = None

# PyMuPDF: fast PDF parsing + structured table extraction. pymupdf4llm renders
# the page as LLM-ready Markdown (tables preserved inline), which is the input
# the statistics reasoning consumes. Both are AGPL-3.0 (or commercial); see
# requirements.txt. Either missing degrades PDF parsing to a flagged skip.
try:
    import pymupdf
except ImportError:  # pragma: no cover - legacy import name fallback
    try:
        import fitz as pymupdf
    except ImportError:
        pymupdf = None
try:
    import pymupdf4llm
except ImportError:  # pragma: no cover
    pymupdf4llm = None

# Markdown backends (Part 1 of the plan), pluggable and optional. Docling is the
# default high-fidelity converter (PDF + HTML -> structured Markdown with tables,
# layout, reading order); MarkItDown is the light fallback for HTML/Markdown.
# When neither is installed the parser degrades to PyMuPDF (PDF) or the tag-strip
# (HTML). Availability is probed cheaply with find_spec; the (heavy) import of
# Docling/torch is deferred to the moment a conversion is actually requested, so
# a plain stats/section run that never converts a file pays no import cost.
import importlib.util  # noqa: E402

_HAS_DOCLING = importlib.util.find_spec("docling") is not None
_HAS_MARKITDOWN = importlib.util.find_spec("markitdown") is not None

# Cap parsed input so a malformed or oversized file cannot exhaust memory.
MAX_FILE_BYTES = 50 * 1024 * 1024  # 50 MB
MAX_TABLE_ROWS = 40                # rows kept per table preview
CONTEXT_CHARS = 60                 # chars of context around each stats match
MAX_SECTION_CHARS = 4000           # excerpt cap per detected section

# Heading cues for section detection (mode section-scan / the future-works skill).
# Each (label, pattern) maps a normalized heading to a category. Patterns are
# matched case-insensitively against the heading text only (English + French).
_SECTION_CUES: list[tuple[str, "re.Pattern[str]"]] = [
    ("future_work", re.compile(
        r"\b(future works?|future directions?|future research|travaux futurs?|"
        r"perspectives?|recommandations?|recommendations?|further works?)\b", re.IGNORECASE)),
    ("open_problems", re.compile(
        r"\b(open problems?|open questions?|open challenges?|challenges?|"
        r"problemes? ouverts?|defis?)\b", re.IGNORECASE)),
    ("limitations", re.compile(r"\b(limitations?|limites?)\b", re.IGNORECASE)),
    ("conclusion", re.compile(r"\b(conclusions?|concluding remarks?)\b", re.IGNORECASE)),
]


# --------------------------------------------------------------------------- #
# Statistics scanner
# --------------------------------------------------------------------------- #
# (label, compiled pattern). Patterns are case-insensitive and deliberately
# permissive: this is a candidate finder for a human/LLM auditor, not a parser.
_STATS_PATTERNS: list[tuple[str, "re.Pattern[str]"]] = [
    ("p_value", re.compile(r"\bp\s*[<>=]\s*0?\.\d+", re.IGNORECASE)),
    ("sample_size", re.compile(r"\bn\s*=\s*\d+", re.IGNORECASE)),
    ("mean_sd", re.compile(r"\d+(?:\.\d+)?\s*(?:±|\+/-|\\pm)\s*\d+(?:\.\d+)?")),
    ("conf_interval", re.compile(r"\b\d{2}\s*%?\s*CI\b|\bconfidence interval\b", re.IGNORECASE)),
    ("test_named", re.compile(
        r"\b(?:t-test|student'?s t|ANOVA|MANOVA|Kruskal[- ]Wallis|Mann[- ]Whitney|"
        r"Wilcoxon|chi[- ]?square|χ2|χ²|Fisher(?:'s)? exact|Pearson|Spearman|"
        r"Tukey|Bonferroni|Dunn|Scheff[eé]|Shapiro[- ]Wilk|Kolmogorov[- ]Smirnov|"
        r"Levene|Bartlett|Mauchly|Greenhouse[- ]Geisser)\b", re.IGNORECASE)),
    ("effect_size", re.compile(
        r"\b(?:Cohen'?s d|eta[- ]?squared|η2|η²|omega[- ]?squared|ω2|ω²|"
        r"Cram[eé]r'?s V|odds ratio|\bOR\b|risk ratio|\bRR\b|rank[- ]biserial)\b",
        re.IGNORECASE)),
    ("ml_metric", re.compile(
        r"\b(?:accuracy|precision|recall|F1(?:[- ]score)?|AUC|AU[- ]?ROC|ROC|"
        r"RMSE|MAE|MAPE|R\^?2|mAP|IoU|Dice|BLEU|perplexity)\b", re.IGNORECASE)),
    ("reproducibility", re.compile(
        r"\b(?:random seed|seeds?|standard deviation|std\.?\s*dev|cross[- ]validation|"
        r"k[- ]?fold|train[\s/]+test split|hold[- ]?out|monte[- ]carlo)\b",
        re.IGNORECASE)),
]


def scan_stats(text: str) -> list[dict[str, str]]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Tag every statistics candidate in extracted text. Each candidate carries
        its category, the matched substring, and a short context window so the
        auditor can locate and judge it without re-reading the whole document.

    Inputs:
        text (str): extracted full text of one document

    Outputs:
        candidates (list[dict]): each {type, match, context}, de-duplicated on
        (type, match, context).
    --------------------------------------------------------------------------
    """
    seen: set[tuple[str, str, str]] = set()
    candidates: list[dict[str, str]] = []
    for label, pattern in _STATS_PATTERNS:
        for m in pattern.finditer(text):
            start = max(0, m.start() - CONTEXT_CHARS)
            end = min(len(text), m.end() + CONTEXT_CHARS)
            context = re.sub(r"\s+", " ", text[start:end]).strip()
            key = (label, m.group(0).strip(), context)
            if key in seen:
                continue
            seen.add(key)
            candidates.append({"type": label, "match": m.group(0).strip(), "context": context})
    return candidates


# --------------------------------------------------------------------------- #
# Section scanner (mode section-scan; consumed by the future-works skill)
# --------------------------------------------------------------------------- #
def _heading_lines(text: str) -> list[tuple[int, str]]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Find every heading in the document and return (line_index, heading_text)
        pairs. A heading is a Markdown ATX line (``# ... ######``), a LaTeX
        ``\\section``/``\\subsection`` macro, or a short standalone line (under 80
        chars, no terminal period) that reads like a title. These bound the
        section excerpts in scan_sections.

    Inputs:
        text (str): extracted document text (Markdown, LaTeX, or plain)

    Outputs:
        headings (list[tuple[int, str]]): line index and cleaned heading text,
        in document order.
    --------------------------------------------------------------------------
    """
    md_re = re.compile(r"^\s{0,3}#{1,6}\s+(?P<t>.+?)\s*#*\s*$")
    tex_re = re.compile(r"^\s*\\(?:sub)*section\*?\{(?P<t>[^}]+)\}")
    headings: list[tuple[int, str]] = []
    for i, line in enumerate(text.splitlines()):
        stripped = line.strip()
        if not stripped:
            continue
        m = md_re.match(line) or tex_re.match(line)
        if m:
            headings.append((i, m.group("t").strip()))
            continue
        # Plain-text heading heuristic: a short line, no terminal sentence
        # punctuation, optionally numbered (e.g. "5. Conclusion", "VI Future Work").
        if len(stripped) <= 79 and not stripped.endswith((".", ",", ";", ":")):
            candidate = re.sub(r"^\s*(?:\d+(?:\.\d+)*|[IVXLC]+)[.)]?\s+", "", stripped)
            if candidate and candidate[0].isalpha() and len(candidate.split()) <= 8:
                headings.append((i, candidate.strip()))
    return headings


def scan_sections(text: str) -> list[dict[str, str]]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Locate the future-work / conclusion / limitations / open-problems
        sections of a document and return each as a labeled excerpt. The excerpt
        runs from a matching heading to the next heading of any kind, capped at
        MAX_SECTION_CHARS. This is the section analogue of scan_stats: a
        candidate finder for the future-works skill, not a semantic parser.

    Inputs:
        text (str): extracted document text

    Outputs:
        sections (list[dict]): each {label, heading, excerpt}, where label is one
        of the _SECTION_CUES categories. De-duplicated on (label, heading).
    --------------------------------------------------------------------------
    """
    lines = text.splitlines()
    headings = _heading_lines(text)
    seen: set[tuple[str, str]] = set()
    sections: list[dict[str, str]] = []
    for pos, (line_idx, heading) in enumerate(headings):
        label = None
        for cue_label, pattern in _SECTION_CUES:
            if pattern.search(heading):
                label = cue_label
                break
        if not label:
            continue
        end_idx = headings[pos + 1][0] if pos + 1 < len(headings) else len(lines)
        excerpt = "\n".join(lines[line_idx + 1:end_idx]).strip()
        excerpt = re.sub(r"\n{3,}", "\n\n", excerpt)[:MAX_SECTION_CHARS]
        key = (label, heading.lower())
        if key in seen:
            continue
        seen.add(key)
        sections.append({"label": label, "heading": heading, "excerpt": excerpt})
    return sections


# --------------------------------------------------------------------------- #
# Markdown backends (pluggable, optional; see the imports above)
# --------------------------------------------------------------------------- #
def _docling_markdown(path: str) -> str | None:
    """Convert any supported file to Markdown via Docling, or None on failure.
    The heavy import is deferred to here (first actual conversion)."""
    if not _HAS_DOCLING:
        return None
    try:
        from docling.document_converter import DocumentConverter
        with contextlib.redirect_stdout(io.StringIO()):
            result = DocumentConverter().convert(path)
            return result.document.export_to_markdown()
    except Exception as exc:  # pragma: no cover - backend is best-effort
        logger.warning("[EXTRACT-STAT] Docling failed for %s: %s", path, exc)
        return None


def _markitdown_markdown(path: str) -> str | None:
    """Convert any supported file to Markdown via MarkItDown, or None on failure.
    The import is deferred to here (first actual conversion)."""
    if not _HAS_MARKITDOWN:
        return None
    try:
        from markitdown import MarkItDown
        with contextlib.redirect_stdout(io.StringIO()):
            return MarkItDown().convert(path).text_content
    except Exception as exc:  # pragma: no cover - backend is best-effort
        logger.warning("[EXTRACT-STAT] MarkItDown failed for %s: %s", path, exc)
        return None


# --------------------------------------------------------------------------- #
# Per-format extraction
# --------------------------------------------------------------------------- #
def _check_size(path: str) -> None:
    """Reject a missing or oversized file before reading it (fail fast)."""
    if not os.path.isfile(path):
        raise FileNotFoundError(f"not a file: {path}")
    size = os.path.getsize(path)
    if size > MAX_FILE_BYTES:
        raise ValueError(f"file exceeds {MAX_FILE_BYTES}-byte cap: {path} ({size} bytes)")


def read_pdf(path: str) -> tuple[str, list[list[list[str]]]]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Extract text and tables from a local PDF. The text is structured Markdown
        via Docling when installed (best table/layout/reading-order fidelity),
        else LLM-ready Markdown via pymupdf4llm, else plain page text via PyMuPDF.
        Tables are also returned as structured row lists (PyMuPDF find_tables)
        whenever PyMuPDF is available, so numeric values can be cross-validated
        against the prose regardless of which backend produced the text.

    Inputs:
        path (str): path to a local .pdf file

    Outputs:
        result (tuple): (text, tables) where text is the Markdown/plain text and
        tables is a list of tables, each a list of rows (list of cell strings),
        truncated to MAX_TABLE_ROWS rows.

    Raises:
        RuntimeError if no PDF backend (Docling, pymupdf4llm, PyMuPDF) is
        importable.
    --------------------------------------------------------------------------
    """
    if not _HAS_DOCLING and pymupdf is None and pymupdf4llm is None:
        raise RuntimeError(
            "no PDF backend installed - run: pip install -r requirements.txt "
            "(docling, or pymupdf4llm + pymupdf)")
    _check_size(path)

    # Backend order: Docling (default) -> pymupdf4llm -> PyMuPDF plain text.
    # Capture stdout so any backend progress output cannot corrupt the JSON this
    # script prints.
    text = _docling_markdown(path)
    if text is None and pymupdf4llm is not None:
        with contextlib.redirect_stdout(io.StringIO()):
            text = pymupdf4llm.to_markdown(path)
    if text is None and pymupdf is not None:
        parts: list[str] = []
        with pymupdf.open(path) as doc:
            for page in doc:
                parts.append(page.get_text())
        text = "\n".join(parts)
    if text is None:
        text = ""

    # Structured tables (row lists) via PyMuPDF find_tables, when available.
    tables: list[list[list[str]]] = []
    if pymupdf is not None:
        with pymupdf.open(path) as doc:
            for page in doc:
                for table in page.find_tables().tables:
                    rows = [["" if c is None else str(c) for c in row] for row in table.extract()]
                    tables.append(rows[:MAX_TABLE_ROWS])
    return text, tables


def read_textlike(path: str) -> str:
    """
    --------------------------------------------------------------------------
    Purpose:
        Read an HTML, plaintext, LaTeX, or Markdown full-text file as text. For
        HTML, the Markdown backends are tried first (Docling, then MarkItDown)
        because they preserve headings and tables that the section and statistics
        scanners rely on; when neither is installed, HTML falls back to a
        tag-strip. LaTeX, Markdown, and plain text are read verbatim.

    Inputs:
        path (str): path to a .html/.htm/.txt/.tex/.md file

    Outputs:
        text (str): text content (Markdown when a backend handled the HTML)
    --------------------------------------------------------------------------
    """
    _check_size(path)
    if path.lower().endswith((".html", ".htm")):
        # Backend order mirrors read_pdf: Docling -> MarkItDown -> tag-strip.
        converted = _docling_markdown(path) or _markitdown_markdown(path)
        if converted is not None:
            return converted
        with open(path, encoding="utf-8", errors="replace") as handle:
            raw = handle.read()
        raw = re.sub(r"(?is)<(script|style)\b.*?>.*?</\1>", " ", raw)
        raw = re.sub(r"(?s)<[^>]+>", " ", raw)
        raw = re.sub(r"&nbsp;", " ", raw)
        raw = re.sub(r"[ \t]+", " ", raw)
        return raw
    with open(path, encoding="utf-8", errors="replace") as handle:
        return handle.read()


def parse_one(path: str, stats_scan: bool, include_text: bool,
              section_scan: bool = False) -> dict[str, Any]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Extract one file (dispatched on extension) and assemble its record.

    Inputs:
        path (str): file to parse
        stats_scan (bool): run scan_stats over the extracted text
        include_text (bool): emit the full text (else only a char count)
        section_scan (bool): run scan_sections (future-work / conclusion /
            limitations / open-problems excerpts) over the extracted text

    Outputs:
        record (dict): {file, status, text_chars, n_tables, tables,
        stats_candidates, sections[, text]} or {file, status:'error', error} on
        failure.
    --------------------------------------------------------------------------
    """
    record: dict[str, Any] = {"file": os.path.basename(path)}
    try:
        if path.lower().endswith(".pdf"):
            text, tables = read_pdf(path)
        else:
            text, tables = read_textlike(path), []
    except Exception as exc:  # surface an actionable message, never a bare trace
        logger.warning("[EXTRACT-STAT] parse failed for %s: %s", path, exc)
        return {**record, "status": "error", "error": str(exc)}

    record["status"] = "ok"
    record["text_chars"] = len(text)
    record["n_tables"] = len(tables)
    record["tables"] = tables
    record["stats_candidates"] = scan_stats(text) if stats_scan else []
    record["sections"] = scan_sections(text) if section_scan else []
    if include_text:
        record["text"] = text
    return record


# --------------------------------------------------------------------------- #
# bib mode (reuses download_pdf.py)
# --------------------------------------------------------------------------- #
def _ensure_and_parse_bib(args: argparse.Namespace) -> list[dict[str, Any]]:
    """
    --------------------------------------------------------------------------
    Purpose:
        For each DOI entry in a .bib, ensure its PDF is present in refs/ (via
        download_pdf.download_one, presence-gated) and parse every present PDF.
        A paper whose PDF is absent is recorded with status 'pdf-missing' so the
        skill can flag it without aborting.

    Inputs:
        args (Namespace): query (.bib path), latex, out_dir, insttoken, email,
        no_html, stats_scan, section_scan, include_text

    Outputs:
        records (list[dict]): one record per bib entry.
    --------------------------------------------------------------------------
    """
    if dl is None:
        raise RuntimeError("download_pdf.py not importable - check the scopus skill scripts path")

    bib_path = args.query
    if not bib_path and args.latex:
        bib_path = dl.find_bib_from_latex(args.latex)
    if not bib_path or not os.path.exists(bib_path):
        raise FileNotFoundError(f"no .bib file found (got: {bib_path!r})")

    out_dir = dl.resolve_out_dir(args.out_dir, args.latex)
    api_key = dl._scopus_key_optional()
    email = getattr(args, "email", None) or dl._unpaywall_email_optional()
    allow_html = not getattr(args, "no_html", False)
    entries = dl.extract_bib_entries(bib_path)

    records: list[dict[str, Any]] = []
    for entry in entries:
        result = dl.download_one(entry, out_dir, api_key, args.insttoken,
                                 email=email, allow_html=allow_html)
        citekey = entry.get("citekey", "")
        # download_one now returns the actual written file in any format
        # (pdf/html/md); parse whatever was retrieved.
        fname = result.get("file") or ""
        dest = os.path.join(out_dir, fname) if fname else ""
        retrieved = result.get("status") not in ("failed", "no-doi")
        if retrieved and dest and os.path.exists(dest):
            rec = parse_one(dest, args.stats_scan, args.include_text,
                            getattr(args, "section_scan", False))
            rec["citekey"] = citekey
            rec["fulltext_source"] = result.get("source") or result.get("status")
            rec["format"] = result.get("format")
            records.append(rec)
        else:
            records.append({
                "file": fname or dl.target_filename(entry), "citekey": citekey,
                "status": "pdf-missing", "doi": entry.get("doi", ""),
            })
    return records


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _emit(records: list[dict[str, Any]], mode: str) -> None:
    counts: dict[str, int] = {}
    for r in records:
        counts[r.get("status", "?")] = counts.get(r.get("status", "?"), 0) + 1
    print(json.dumps({
        "mode": mode,
        "total": len(records),
        "counts": counts,
        "records": records,
    }, ensure_ascii=False, indent=2))


def _run_single(args: argparse.Namespace, mode: str) -> None:
    record = parse_one(args.query, args.stats_scan, args.include_text,
                       getattr(args, "section_scan", False))
    _emit([record], mode)


def _run_bib(args: argparse.Namespace) -> None:
    _emit(_ensure_and_parse_bib(args), "bib")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    # Shared flags, attached to every subparser so they may appear after the
    # subcommand (extract_text.py text <file> --stats-scan), as documented.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--stats-scan", action="store_true",
                        help="tag p-values, sample sizes, tests, effect sizes, ML metrics")
    common.add_argument("--section-scan", action="store_true",
                        help="extract future-work / conclusion / limitations / open-problems sections")
    common.add_argument("--include-text", action="store_true",
                        help="emit the full extracted text (default: char count only)")

    parser = argparse.ArgumentParser(
        description="Extract full text, statistics candidates, and section excerpts")
    sub = parser.add_subparsers(dest="mode", required=True)

    p_pdf = sub.add_parser("pdf", parents=[common], help="parse one local PDF")
    p_pdf.add_argument("query", help="path to a .pdf file")
    p_pdf.set_defaults(func=lambda a: _run_single(a, "pdf"))

    p_text = sub.add_parser("text", parents=[common], help="parse one HTML/plaintext/LaTeX/Markdown file")
    p_text.add_argument("query", help="path to a .html/.txt/.tex/.md file")
    p_text.set_defaults(func=lambda a: _run_single(a, "text"))

    p_bib = sub.add_parser("bib", parents=[common],
                           help="ensure each DOI's full text then parse every retrieved file")
    p_bib.add_argument("query", nargs="?", default=None,
                       help="path to the .bib file (omit to auto-discover from --latex)")
    p_bib.add_argument("--latex", default=None, help="main .tex file; refs/ is next to it")
    p_bib.add_argument("--out-dir", default=None, help="explicit refs/ directory")
    p_bib.add_argument("--insttoken", default=None, help="Elsevier institutional token (off-campus)")
    p_bib.add_argument("--email", default=None,
                       help="Unpaywall contact email (else the UNPAYWALL_EMAIL env var)")
    p_bib.add_argument("--no-html", action="store_true",
                       help="restrict retrieval to PDF only (skip the HTML/landing tiers)")
    p_bib.set_defaults(func=_run_bib)

    args = parser.parse_args()
    try:
        args.func(args)
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        # Surface an actionable message, not a bare traceback (code-style.md).
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
