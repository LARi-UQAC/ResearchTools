"""
pdf_line_compare - Step 5 (visual verification) of the word2latex workflow.

Compares, line by line, a reference PDF (the .docx rendered by Word) with a candidate
PDF (the LaTeX build) and reports every line whose page, baseline, left edge or right
edge differs by more than a tolerance, plus the lines present on one side only. The
right edge is taken from the last visible glyph, because Word includes the trailing
space of a line in the line's bounding box while LaTeX does not.

Exit codes: 0 no difference, 1 differences found, 2 refusal (a PDF or the configuration
is missing or unreadable, or PyMuPDF is not installed).
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import re
import sys
import unicodedata
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

CONFIG_FILE = Path(__file__).with_name("pdf-line-compare.json")
CONFIG_KEYS = ("tolerance_cm", "match_prefix_chars", "ignored_glyphs",
               "list_label_regex", "max_extra_reported")
POINTS_PER_INCH = 72.0
CM_PER_INCH = 2.54


class CompareError(Exception):
    """A refusal by design: missing input, unreadable configuration, missing package."""


def load_config(path: Path = CONFIG_FILE) -> dict[str, Any]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Read the tolerances and matching rules from the JSON configuration.

    Inputs:
        path (Path): configuration file, each key holding {value, provenance}.

    Outputs:
        config (dict): key -> value for every key of CONFIG_KEYS.

    Raises:
        CompareError: the file is missing, is not JSON, or lacks a key.
    --------------------------------------------------------------------------
    """
    if not path.is_file():
        raise CompareError(f"configuration file not found: {path}")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise CompareError(f"configuration file is not valid UTF-8 JSON: {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise CompareError(f"configuration file must hold a JSON object: {path}")
    config: dict[str, Any] = {}
    for key in CONFIG_KEYS:
        entry = raw.get(key)
        if not isinstance(entry, dict) or "value" not in entry:
            raise CompareError(f"configuration key '{key}' is missing from {path}")
        config[key] = entry["value"]
    _check_types(config, path)
    return config


def _check_types(config: dict[str, Any], path: Path) -> None:
    """
    --------------------------------------------------------------------------
    Purpose:
        Refuse a configuration value of the wrong type before any PDF is read, so
        a broken configuration exits 2 (refusal) and never 1 (differences found).

    Inputs:
        config (dict): key -> value, as read by load_config.
        path (Path): the configuration file, named in the message.

    Outputs:
        None.

    Raises:
        CompareError: a numeric key is not a non-negative number (a bool is not a
            number here), a text key is not a string, or the regex does not compile.
    --------------------------------------------------------------------------
    """
    def number(key: str, integer: bool, positive: bool = False) -> None:
        v = config[key]
        kinds = (int,) if integer else (int, float)
        # NaN fails every comparison, so a NaN tolerance would flag nothing at all.
        if (isinstance(v, bool) or not isinstance(v, kinds) or not math.isfinite(v)
                or v < 0 or (positive and v == 0)):
            sign = "a positive" if positive else "a non-negative"
            kind = f"{sign} integer" if integer else f"{sign} finite number"
            raise CompareError(f"configuration key '{key}' in {path} must be {kind}, got {v!r}")

    number("tolerance_cm", integer=False)
    # A zero prefix makes every matching key empty, and empty keys are never compared.
    number("match_prefix_chars", integer=True, positive=True)
    number("max_extra_reported", integer=True)
    for key in ("ignored_glyphs", "list_label_regex"):
        if not isinstance(config[key], str):
            raise CompareError(f"configuration key '{key}' in {path} must be a string")
    try:
        re.compile(config["list_label_regex"])
    except re.error as exc:
        raise CompareError(f"configuration key 'list_label_regex' in {path} is not a valid regex: {exc}") from exc


def to_cm(points: float) -> float:
    """
    --------------------------------------------------------------------------
    Purpose:
        Convert PDF points (1/72 inch) to centimetres.

    Inputs:
        points (float): a PDF coordinate or length.

    Outputs:
        cm (float): the same length in centimetres.
    --------------------------------------------------------------------------
    """
    return points / POINTS_PER_INCH * CM_PER_INCH


def match_key(text: str, config: dict[str, Any]) -> str:
    """
    --------------------------------------------------------------------------
    Purpose:
        Build the key used to pair a reference line with a candidate line.

    Details:
        NFKC normalisation, curly apostrophes made straight, non-breaking spaces made
        plain, fallback-font symbols and a leading list label removed, whitespace
        collapsed, then truncated to match_prefix_chars characters.

    Inputs:
        text (str): the raw text of one extracted line.
        config (dict): the loaded configuration.

    Outputs:
        key (str): the normalised prefix; empty when the line holds no text.
    --------------------------------------------------------------------------
    """
    t = unicodedata.normalize("NFKC", text)
    t = t.replace("’", "'").replace("‘", "'")
    t = t.replace(" ", " ").replace(" ", " ")
    t = "".join(ch for ch in t if ch not in config["ignored_glyphs"])
    t = re.sub(config["list_label_regex"], "", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t[: int(config["match_prefix_chars"])]


def extract_lines(pdf_path: Path) -> list[dict[str, Any]]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Extract every text line of a PDF with its page, baseline and visible extent.

    Inputs:
        pdf_path (Path): the PDF to read.

    Outputs:
        lines (list of dict): page (1-based), baseline_cm, x0_cm, x1_cm (left edge of
            the first and right edge of the last visible glyph), size (pt of the first
            visible span) and text, in reading order.

    Raises:
        CompareError: PyMuPDF is not installed or the file cannot be opened.
    --------------------------------------------------------------------------
    """
    try:
        import fitz  # PyMuPDF, declared in requirements.txt
    except ImportError as exc:
        raise CompareError("PyMuPDF is not installed (pip install pymupdf)") from exc
    if not pdf_path.is_file():
        raise CompareError(f"PDF not found: {pdf_path}")
    try:
        doc = fitz.open(pdf_path)
    except Exception as exc:  # PyMuPDF raises its own types for corrupt files
        raise CompareError(f"cannot open PDF: {pdf_path}: {exc}") from exc
    lines: list[dict[str, Any]] = []
    with doc:
        for page_index, page in enumerate(doc):
            for block in page.get_text("rawdict")["blocks"]:
                for line in block.get("lines", []):
                    chars = [c for span in line["spans"] for c in span["chars"]]
                    visible = [c for c in chars if c["c"].strip()]
                    if not visible:
                        continue
                    spans = [s for s in line["spans"]
                             if "".join(c["c"] for c in s["chars"]).strip()]
                    lines.append({
                        "page": page_index + 1,
                        "baseline_cm": to_cm(spans[0]["origin"][1]),
                        "x0_cm": to_cm(visible[0]["bbox"][0]),
                        "x1_cm": to_cm(visible[-1]["bbox"][2]),
                        "size": round(spans[0]["size"], 2),
                        "text": "".join(c["c"] for c in chars),
                    })
    return lines


def compare_lines(reference: list[dict[str, Any]], candidate: list[dict[str, Any]],
                  config: dict[str, Any]) -> dict[str, Any]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Pair reference and candidate lines by key and measure their differences.

    Details:
        Each reference line takes the first unused candidate line with the same key,
        in reading order, so repeated lines ("Cliquez ou appuyez ici...") pair in order.
        A pair is flagged when the pages differ or any delta exceeds tolerance_cm.

    Inputs:
        reference (list of dict): lines of the reference PDF (extract_lines).
        candidate (list of dict): lines of the candidate PDF.
        config (dict): the loaded configuration.

    Outputs:
        report (dict): pairs (each with d_baseline_cm, d_x0_cm, d_x1_cm, flagged),
            missing (reference lines with no candidate), extra (candidate lines never
            paired), and counts.
    --------------------------------------------------------------------------
    """
    tol = float(config["tolerance_cm"])
    keyed = [(match_key(c["text"], config), c) for c in candidate]
    used: set[int] = set()
    pairs, missing = [], []
    for ref in reference:
        key = match_key(ref["text"], config)
        if not key:
            continue
        hit = next((i for i, (k, _) in enumerate(keyed) if i not in used and k == key), None)
        if hit is None:
            missing.append(ref)
            continue
        used.add(hit)
        cand = keyed[hit][1]
        deltas = {
            "d_baseline_cm": cand["baseline_cm"] - ref["baseline_cm"],
            "d_x0_cm": cand["x0_cm"] - ref["x0_cm"],
            "d_x1_cm": cand["x1_cm"] - ref["x1_cm"],
        }
        flagged = cand["page"] != ref["page"] or any(abs(v) > tol for v in deltas.values())
        pairs.append({"reference": ref, "candidate": cand, **deltas, "flagged": flagged})
    extra = [c for i, (k, c) in enumerate(keyed) if i not in used and k]
    flagged_count = sum(p["flagged"] for p in pairs)
    return {
        "pairs": pairs, "missing": missing, "extra": extra,
        "counts": {"reference_lines": len(reference), "candidate_lines": len(candidate),
                   "paired": len(pairs), "flagged": flagged_count,
                   "missing": len(missing), "extra": len(extra)},
        "identical": flagged_count == 0 and not missing and not extra,
    }


def format_report(report: dict[str, Any], config: dict[str, Any], show_all: bool) -> str:
    """
    --------------------------------------------------------------------------
    Purpose:
        Render the comparison as text for a person reading a terminal.

    Inputs:
        report (dict): output of compare_lines.
        config (dict): the loaded configuration.
        show_all (bool): list every pair, not only the flagged ones.

    Outputs:
        text (str): one line per reported pair, then the missing and extra lines and
            a summary line.
    --------------------------------------------------------------------------
    """
    out = []
    for p in report["pairs"]:
        if not (show_all or p["flagged"]):
            continue
        r, c = p["reference"], p["candidate"]
        out.append("%s ref p%d / cand p%d  b=%5.2f  db=%+.2f dx0=%+.2f dx1=%+.2f | %s" % (
            "!!" if p["flagged"] else "  ", r["page"], c["page"], r["baseline_cm"],
            p["d_baseline_cm"], p["d_x0_cm"], p["d_x1_cm"], r["text"].strip()[:60]))
    for r in report["missing"]:
        out.append("MISSING ref p%d b=%5.2f | %s" % (r["page"], r["baseline_cm"], r["text"].strip()[:60]))
    for c in report["extra"][: int(config["max_extra_reported"])]:
        out.append("EXTRA  cand p%d b=%5.2f | %s" % (c["page"], c["baseline_cm"], c["text"].strip()[:60]))
    n = report["counts"]
    out.append("reference %d lines, candidate %d, paired %d, flagged %d, missing %d, extra %d" % (
        n["reference_lines"], n["candidate_lines"], n["paired"], n["flagged"],
        n["missing"], n["extra"]))
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    """
    --------------------------------------------------------------------------
    Purpose:
        Command-line entry point.

    Inputs:
        argv (list of str or None): arguments; None reads sys.argv.

    Outputs:
        exit_code (int): 0 identical, 1 differences, 2 refusal. Prints the text report,
            or the JSON report with --json.
    --------------------------------------------------------------------------
    """
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("reference", type=Path, help="PDF rendered by Word from the .docx")
    parser.add_argument("candidate", type=Path, help="PDF built from the .tex")
    parser.add_argument("--all", action="store_true", help="list every pair, not only flagged ones")
    parser.add_argument("--json", action="store_true", help="print the machine-readable report")
    parser.add_argument("--config", type=Path, default=CONFIG_FILE, help="configuration file")
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    try:
        config = load_config(args.config)
        report = compare_lines(extract_lines(args.reference), extract_lines(args.candidate), config)
    except CompareError as exc:
        logger.error("[COMPARE] %s", exc)
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=1))
    else:
        print(format_report(report, config, args.all))
    return 0 if report["identical"] else 1


if __name__ == "__main__":
    sys.exit(main())
