"""
tex_wc - subcommand `wc`: prose word count, page estimate, the
`--accepted` / `--before` variants for changes-package track-changed text,
and the `--section` / `--limit` per-section cap check.

Stage: latex-hygiene pipeline, length and trim-delta measurement. Merges
wc_sections.py (plain prose count + float count) with accepted_wc.py (the
accepted-text resolver and its before/after delta table), and adds the
page-estimate heuristic that submit-checker.md Step 2 currently applies by
hand: words-per-page by column count and font size, with font size read from
\\documentclass[...] options rather than assumed.

`--section` answers the question a grant form asks and a journal does not:
how long is THIS section. Mitacs caps its project summary at 300 words,
its research question at 50, and its background at a 500-word minimum, and
CRSNG and FRQNT are shaped the same way. Counting the whole file answers
none of those, so before this existed the count was redone by hand, per
manuscript, which is the cost the rule against per-manuscript scripts
exists to stop.
"""

import logging
import math
import os
import re
from typing import Dict, List, Tuple

from tex_common import (
    count_words,
    expand_globs,
    read_balanced_arg,
    read_text,
    resolve_accepted,
    strip_comments,
    strip_floats,
    strip_macros,
    strip_non_prose_envs,
)

logger = logging.getLogger(__name__)

_FLOAT_BEGIN = re.compile(r"\\begin\{(table\*?|figure\*?)\}")
_DOCCLASS = re.compile(r"\\documentclass(\[(?P<opts>[^\]]*)\])?\{(?P<cls>[^}]*)\}")

# Sectioning commands, deepest number = deepest level. A section ends at the
# next heading whose level is the same or shallower, which is what makes
# "2.1" stop at "2.2" instead of swallowing the rest of the document.
_SECTION_LEVELS = {
    "part": 0,
    "chapter": 1,
    "section": 2,
    "subsection": 3,
    "subsubsection": 4,
    "paragraph": 5,
    "subparagraph": 6,
}
_SECTION_CMD = re.compile(
    r"\\(part|chapter|section|subsection|subsubsection|paragraph|subparagraph)\*?\s*\{"
)
_LABEL = re.compile(r"\\label\{[^}]*\}")
_MACRO = re.compile(r"\\[a-zA-Z]+\*?")

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
        body = strip_macros(strip_non_prose_envs(strip_comments(strip_floats(raw))))
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


def normalise_title(raw: str) -> str:
    """
    --------------------------------------------------------------------------
    Purpose:
        Reduce a heading argument to comparable plain text, so that a caller
        can name a section the way it reads on the page rather than the way
        it is spelled in the source.

    Inputs:
        raw (str): the brace argument of a sectioning command, for example
            "2.1~Sommaire du projet~:".

    Outputs:
        title (str): label text with \\label{} removed, other macros dropped,
            braces and tie characters turned into spaces, whitespace
            collapsed, and case folded for matching.
    --------------------------------------------------------------------------
    """
    t = _LABEL.sub(" ", raw)
    t = _MACRO.sub(" ", t)
    t = t.replace("~", " ").replace("{", " ").replace("}", " ")
    return re.sub(r"\s+", " ", t).strip().lower()


def list_sections(text: str) -> List[Dict]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Enumerate the sectioning commands of one file with the span of body
        text each one owns.

    Inputs:
        text (str): LaTeX source, comments already stripped.

    Outputs:
        sections (List[Dict]): one entry per heading, in document order,
            {"level": int, "command": str, "title": str, "raw_title": str,
            "body_start": int, "body_end": int}. body_end is the offset of
            the next heading at the same or a shallower level, or the end of
            the text.

    Known limit: only real sectioning commands delimit. A heading faked with
    \\textbf{...}, as Mitacs section 2.4 is in the proposal template, opens
    no section and is counted inside whichever real section precedes it.
    --------------------------------------------------------------------------
    """
    found = []
    for m in _SECTION_CMD.finditer(text):
        raw_title, after = read_balanced_arg(text, m.end())
        found.append({
            "level": _SECTION_LEVELS[m.group(1)],
            "command": m.group(1),
            "title": normalise_title(raw_title),
            "raw_title": raw_title.strip(),
            "heading_start": m.start(),
            "body_start": after,
        })
    for i, sec in enumerate(found):
        end = len(text)
        for nxt in found[i + 1:]:
            if nxt["level"] <= sec["level"]:
                end = nxt["heading_start"]
                break
        sec["body_end"] = end
    return found


def slice_section(text: str, name: str) -> Dict:
    """
    --------------------------------------------------------------------------
    Purpose:
        Return the body of the one section whose title matches `name`, or
        refuse. Nothing is guessed: zero matches and two or more matches are
        both refusals that name the candidates, because silently counting
        the wrong section produces a number that looks measured.

    Inputs:
        text (str): LaTeX source, comments already stripped.
        name (str): section name or a distinctive fragment of it, matched
            case-insensitively against the normalised title.

    Outputs:
        result (Dict): {"matched": bool, "body": str, "title": str,
            "reason": Optional[str], "candidates": List[str]}.
    --------------------------------------------------------------------------
    """
    sections = list_sections(text)
    needle = normalise_title(name)
    hits = [s for s in sections if needle and needle in s["title"]]
    if len(hits) == 1:
        s = hits[0]
        return {
            "matched": True,
            "body": text[s["body_start"]:s["body_end"]],
            "title": s["raw_title"],
            "reason": None,
            "candidates": [x["raw_title"] for x in sections],
        }
    reason = (
        "no section title contains %r" % name if not hits
        else "%d section titles contain %r" % (len(hits), name)
    )
    return {
        "matched": False,
        "body": "",
        "title": None,
        "reason": reason,
        "candidates": [x["raw_title"] for x in (hits or sections)],
    }


def scan_wc_section(files: List[str], name: str, accepted: bool = False,
                    limit: int = None) -> Dict:
    """
    --------------------------------------------------------------------------
    Purpose:
        Count the words of one named section, optionally after resolving the
        changes-package markup, and compare the count to a cap.

    Inputs:
        files (List[str]): .tex files to search; the section must be found in
            exactly one of them.
        name (str): section name or fragment.
        accepted (bool): count the accepted text rather than the raw source.
        limit (Optional[int]): word cap. When given, the result carries
            over_limit and overflow so --strict can gate on it.

    Outputs:
        result (Dict): {"section": str, "file": str, "words": int,
            "accepted": bool, "limit": Optional[int], "over_limit": bool,
            "overflow": int, "refused": bool, "reason": Optional[str],
            "candidates": List[str]}.
    --------------------------------------------------------------------------
    """
    matches = []
    everything = []
    per_file_reasons = []
    for path in files:
        text = strip_comments(read_text(path))
        found = slice_section(text, name)
        everything.extend("%s: %s" % (os.path.basename(path), c)
                          for c in found["candidates"])
        if found["matched"]:
            matches.append((path, found))
        elif found["reason"] and "no section title" not in found["reason"]:
            # An ambiguous match must not be reported as an absent one: the
            # remedy differs, since "2.1" failing against "2.10" and "2.11"
            # is fixed by naming the section more fully, not by looking
            # elsewhere for it.
            per_file_reasons.append("%s: %s" % (os.path.basename(path), found["reason"]))

    if len(matches) != 1:
        if per_file_reasons and not matches:
            reason = "section %r is ambiguous -- %s" % (name, "; ".join(per_file_reasons))
        elif not matches:
            reason = "section %r not found in any of the %d file(s) given" % (name, len(files))
        else:
            reason = "section %r matches in %d files: %s" % (
                name, len(matches), ", ".join(os.path.basename(p) for p, _ in matches))
        logger.error("[HYGIENE] wc --section: %s", reason)
        return {
            "section": name, "file": None, "words": 0, "accepted": accepted,
            "limit": limit, "over_limit": False, "overflow": 0,
            "refused": True, "reason": reason, "candidates": everything,
        }

    path, found = matches[0]
    body = found["body"]
    if accepted:
        body = resolve_accepted(body)
    words = count_words(strip_macros(strip_non_prose_envs(strip_floats(body))))
    over = bool(limit is not None and words > limit)
    logger.info("[HYGIENE] wc --section %r: %s -> %d word(s)%s",
                found["title"], path, words,
                (" over a cap of %d" % limit) if over else "")
    return {
        "section": found["title"], "file": path, "words": words,
        "accepted": accepted, "limit": limit, "over_limit": over,
        "overflow": (words - limit) if over else 0,
        "refused": False, "reason": None, "candidates": [],
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
    return count_words(strip_macros(strip_non_prose_envs(s)))


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
