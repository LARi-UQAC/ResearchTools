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

# Cap parsed input so a malformed or oversized file cannot exhaust memory.
MAX_FILE_BYTES = 50 * 1024 * 1024  # 50 MB
MAX_TABLE_ROWS = 40                # rows kept per table preview
CONTEXT_CHARS = 60                 # chars of context around each stats match


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
        Extract text and tables from a local PDF with PyMuPDF. The text is
        LLM-ready Markdown via pymupdf4llm (tables preserved inline) when
        available, else plain page text via PyMuPDF. Tables are also returned as
        structured row lists (PyMuPDF find_tables) so numeric values can be
        cross-validated against the prose.

    Inputs:
        path (str): path to a local .pdf file

    Outputs:
        result (tuple): (text, tables) where text is the Markdown/plain text and
        tables is a list of tables, each a list of rows (list of cell strings),
        truncated to MAX_TABLE_ROWS rows.

    Raises:
        RuntimeError if PyMuPDF is not importable.
    --------------------------------------------------------------------------
    """
    if pymupdf is None and pymupdf4llm is None:
        raise RuntimeError("PyMuPDF not installed - run: pip install -r requirements.txt")
    _check_size(path)

    # LLM-ready Markdown when pymupdf4llm is present. Capture stdout so its
    # progress output can never corrupt the JSON this script prints.
    if pymupdf4llm is not None:
        with contextlib.redirect_stdout(io.StringIO()):
            text = pymupdf4llm.to_markdown(path)
    else:
        parts: list[str] = []
        with pymupdf.open(path) as doc:
            for page in doc:
                parts.append(page.get_text())
        text = "\n".join(parts)

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
        Read an HTML, plaintext, LaTeX, or Markdown full-text file as plain
        text. HTML is reduced to text by stripping script/style blocks and
        tags; other formats are read verbatim.

    Inputs:
        path (str): path to a .html/.htm/.txt/.tex/.md file

    Outputs:
        text (str): plain text content
    --------------------------------------------------------------------------
    """
    _check_size(path)
    with open(path, encoding="utf-8", errors="replace") as handle:
        raw = handle.read()
    if path.lower().endswith((".html", ".htm")):
        raw = re.sub(r"(?is)<(script|style)\b.*?>.*?</\1>", " ", raw)
        raw = re.sub(r"(?s)<[^>]+>", " ", raw)
        raw = re.sub(r"&nbsp;", " ", raw)
        raw = re.sub(r"[ \t]+", " ", raw)
    return raw


def parse_one(path: str, stats_scan: bool, include_text: bool) -> dict[str, Any]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Extract one file (dispatched on extension) and assemble its record.

    Inputs:
        path (str): file to parse
        stats_scan (bool): run scan_stats over the extracted text
        include_text (bool): emit the full text (else only a char count)

    Outputs:
        record (dict): {file, status, text_chars, n_tables, tables,
        stats_candidates[, text]} or {file, status:'error', error} on failure.
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
        args (Namespace): query (.bib path), latex, out_dir, insttoken,
        stats_scan, include_text

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
    entries = dl.extract_bib_entries(bib_path)

    records: list[dict[str, Any]] = []
    for entry in entries:
        result = dl.download_one(entry, out_dir, api_key, args.insttoken)
        dest = os.path.join(out_dir, dl.target_filename(entry))
        citekey = entry.get("citekey", "")
        if result.get("status") in ("present", "elsevier", "semantic_scholar") and os.path.exists(dest):
            rec = parse_one(dest, args.stats_scan, args.include_text)
            rec["citekey"] = citekey
            rec["pdf_source"] = result.get("source") or result.get("status")
            records.append(rec)
        else:
            records.append({
                "file": dl.target_filename(entry), "citekey": citekey,
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
    record = parse_one(args.query, args.stats_scan, args.include_text)
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
    common.add_argument("--include-text", action="store_true",
                        help="emit the full extracted text (default: char count only)")

    parser = argparse.ArgumentParser(description="Extract full text and statistics candidates")
    sub = parser.add_subparsers(dest="mode", required=True)

    p_pdf = sub.add_parser("pdf", parents=[common], help="parse one local PDF")
    p_pdf.add_argument("query", help="path to a .pdf file")
    p_pdf.set_defaults(func=lambda a: _run_single(a, "pdf"))

    p_text = sub.add_parser("text", parents=[common], help="parse one HTML/plaintext/LaTeX/Markdown file")
    p_text.add_argument("query", help="path to a .html/.txt/.tex/.md file")
    p_text.set_defaults(func=lambda a: _run_single(a, "text"))

    p_bib = sub.add_parser("bib", parents=[common], help="ensure each DOI's PDF then parse every present PDF")
    p_bib.add_argument("query", nargs="?", default=None,
                       help="path to the .bib file (omit to auto-discover from --latex)")
    p_bib.add_argument("--latex", default=None, help="main .tex file; refs/ is next to it")
    p_bib.add_argument("--out-dir", default=None, help="explicit refs/ directory")
    p_bib.add_argument("--insttoken", default=None, help="Elsevier institutional token (off-campus)")
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
