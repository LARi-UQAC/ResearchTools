"""
tex_wc - subcommand `wc`: prose word count, page estimate, and the
`--accepted` / `--before` variants for changes-package track-changed text.

Stage: latex-hygiene pipeline, length and trim-delta measurement. Merges
wc_sections.py (plain prose count + float count) with accepted_wc.py (the
accepted-text resolver and its before/after delta table), and adds the
page-estimate heuristic that submit-checker.md Step 2 currently applies by
hand: words-per-page by column count and font size, with font size read from
\\documentclass[...] options rather than assumed.
"""

import logging
import math
import os
import re
from typing import Dict, List, Tuple

from tex_common import (
    count_words,
    expand_globs,
    read_text,
    resolve_accepted,
    strip_comments,
    strip_floats,
)

logger = logging.getLogger(__name__)

_FLOAT_BEGIN = re.compile(r"\\begin\{(table\*?|figure\*?)\}")
_DOCCLASS = re.compile(r"\\documentclass(\[(?P<opts>[^\]]*)\])?\{(?P<cls>[^}]*)\}")

# Midpoints of the three heuristics in submit-checker.md Step 2:
#   two-column, 10pt: ~700-800 words/page
#   single-column, 11pt: ~500-600 words/page
#   single-column, 12pt: ~400-500 words/page
_RATES = {
    (True, 10): 750,
    (False, 11): 550,
    (False, 12): 450,
}


def detect_layout(files: List[str]) -> Dict:
    """
    --------------------------------------------------------------------------
    Purpose:
        Find the first \\documentclass[...]{...} among the given files and
        read its font size and column count, the way submit-checker.md Step 2
        requires ("detect the font size from \\documentclass[...] options").

    Inputs:
        files (List[str]): candidate files (the main file is usually one of
            them; a sections/*.tex glob alone will not contain it).

    Outputs:
        layout (Dict): {"detected": bool, "documentclass": Optional[str],
            "options": List[str], "font_size": int, "two_column": bool,
            "source_file": Optional[str]}. Undetected falls back to
            single-column 11pt, the middle of the three heuristics.
    --------------------------------------------------------------------------
    """
    for path in files:
        text = read_text(path)
        m = _DOCCLASS.search(text)
        if not m:
            continue
        opts = [o.strip() for o in (m.group("opts") or "").split(",") if o.strip()]
        cls = m.group("cls") or ""
        font_size = 10
        for o in opts:
            fm = re.match(r"(\d+)pt$", o)
            if fm:
                font_size = int(fm.group(1))
        two_column = "twocolumn" in opts or (
            "ieeetran" in cls.lower() and "onecolumn" not in opts
        )
        return {
            "detected": True,
            "documentclass": cls,
            "options": opts,
            "font_size": font_size,
            "two_column": two_column,
            "source_file": path,
        }
    logger.info("[HYGIENE] wc: no \\documentclass found, defaulting to single-column 11pt")
    return {
        "detected": False,
        "documentclass": None,
        "options": [],
        "font_size": 11,
        "two_column": False,
        "source_file": None,
    }


def words_per_page(two_column: bool, font_size: int) -> Tuple[int, bool]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Map a (columns, font size) layout to a words-per-page rate. Only three
        buckets are backed by an explicit heuristic in submit-checker.md; any
        other combination falls back to the nearest defined bucket rather
        than inventing a new rate, and the fallback is reported so the
        estimate does not read as more precise than it is.

    Inputs:
        two_column (bool): column layout.
        font_size (int): point size.

    Outputs:
        rate (int), exact_bucket (bool): words/page and whether that rate came
            from an exact heuristic match (True) or a nearest-bucket fallback
            (False).
    --------------------------------------------------------------------------
    """
    key = (two_column, font_size)
    if key in _RATES:
        return _RATES[key], True
    if two_column:
        return _RATES[(True, 10)], False
    nearest = min((11, 12), key=lambda fs: abs(fs - font_size))
    return _RATES[(False, nearest)], False


def scan_wc(files: List[str]) -> Dict:
    """
    --------------------------------------------------------------------------
    Purpose:
        Count prose words per file (floats and comments excluded), count
        floats, and estimate the compiled page count.

    Inputs:
        files (List[str]): .tex files to scan.

    Outputs:
        result (Dict): {"files": {path: {"prose_words": int, "floats": int}},
            "total_prose_words": int, "total_floats": int, "layout": Dict,
            "words_per_page": int, "estimate_exact_bucket": bool,
            "estimated_pages": int}.
    --------------------------------------------------------------------------
    """
    per_file = {}
    total_words = 0
    total_floats = 0
    for path in files:
        raw = read_text(path)
        body = strip_comments(strip_floats(raw))
        w = count_words(body)
        fl = len(_FLOAT_BEGIN.findall(raw))
        per_file[path] = {"prose_words": w, "floats": fl}
        total_words += w
        total_floats += fl
        logger.info("[HYGIENE] wc: %s -> prose_words=%d floats=%d", path, w, fl)

    layout = detect_layout(files)
    rate, exact = words_per_page(layout["two_column"], layout["font_size"])
    pages = math.ceil(total_words / rate) if rate else None
    return {
        "files": per_file,
        "total_prose_words": total_words,
        "total_floats": total_floats,
        "layout": layout,
        "words_per_page": rate,
        "estimate_exact_bucket": exact,
        "estimated_pages": pages,
    }


def accepted_word_count(path: str) -> int:
    """
    --------------------------------------------------------------------------
    Purpose:
        Word count of one file's accepted (changes-resolved) text, floats and
        comments excluded.

    Inputs:
        path (str): .tex file.

    Outputs:
        count (int): accepted-text prose word count.
    --------------------------------------------------------------------------
    """
    s = strip_comments(read_text(path))
    s = resolve_accepted(s)
    s = strip_floats(s)
    return count_words(s)


def scan_wc_accepted(files: List[str]) -> Dict:
    """
    --------------------------------------------------------------------------
    Purpose:
        Word count of the accepted text per file (what
        `\\usepackage[final]{changes}` renders), with no before/after
        comparison.

    Inputs:
        files (List[str]): .tex files to scan.

    Outputs:
        result (Dict): {"files": {path: int}, "total": int}.
    --------------------------------------------------------------------------
    """
    per_file = {}
    total = 0
    for path in files:
        n = accepted_word_count(path)
        per_file[path] = n
        total += n
        logger.info("[HYGIENE] wc --accepted: %s -> %d", path, n)
    return {"files": per_file, "total": total}


def scan_wc_accepted_delta(before_dir: str, after_files: List[str]) -> Dict:
    """
    --------------------------------------------------------------------------
    Purpose:
        Compare accepted-text word counts between a "before" directory
        (matched by basename) and the given "after" files, producing a
        before/after/delta/pct row per file plus a TOTAL row.

    Inputs:
        before_dir (str): directory holding the pre-trim .tex files.
        after_files (List[str]): the current .tex files (post-trim).

    Outputs:
        result (Dict): {"rows": [{"file": str, "before": int, "after": int,
            "delta": int, "pct": Optional[float]}, ...], "total_before": int,
            "total_after": int, "total_delta": int, "total_pct": Optional[float]}.
            pct is None when the before count is 0 (division by zero avoided).
    --------------------------------------------------------------------------
    """
    before_files = expand_globs([os.path.join(before_dir, "*.tex")])
    before = {os.path.basename(f): accepted_word_count(f) for f in before_files}
    after = {os.path.basename(f): accepted_word_count(f) for f in after_files}
    rows = []
    total_before = total_after = 0
    for key in sorted(set(before) | set(after)):
        b = before.get(key, 0)
        a = after.get(key, 0)
        delta = a - b
        pct = (100.0 * delta / b) if b else None
        rows.append({"file": key, "before": b, "after": a, "delta": delta, "pct": pct})
        total_before += b
        total_after += a
    total_delta = total_after - total_before
    total_pct = (100.0 * total_delta / total_before) if total_before else None
    return {
        "rows": rows,
        "total_before": total_before,
        "total_after": total_after,
        "total_delta": total_delta,
        "total_pct": total_pct,
    }
