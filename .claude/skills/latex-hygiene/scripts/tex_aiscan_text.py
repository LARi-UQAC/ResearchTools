"""
tex_aiscan_text - prose extraction, sentence statistics, section attribution,
first-person pronoun scan, and list detection for the `aiscan` subcommand.

Stage: latex-hygiene pipeline, structural helpers behind aiscan's AI-style
scoring. Split out of tex_aiscan.py to stay under the repo's per-file token
ceiling (.claude/rules/code-style.md). The prose-extraction and sentence-
statistics functions are a direct port of aiscan.py's sentence-length-
uniformity computation; build_sections/section_of, scan_pronouns, and
scan_lists are the four behaviours merged in from compose_audit.py (source
#9): section attribution, the first-person pronoun scan, list detection, and
(handled here via the abstract begin/end tags rather than a hardcoded line
range) the abstract special case.
"""

import logging
import re
import statistics
from typing import Dict, List, Optional, Tuple

from tex_common import build_line_starts, line_at

logger = logging.getLogger(__name__)

_FLOAT_LIKE_ENV = re.compile(
    r"(?s)\\begin\{(equation|align|tabular|table|figure|IEEEkeywords)\*?\}.*?\\end\{\1\*?\}"
)
_COMMENT_TO_EOL = re.compile(r"%.*")
_INLINE_MATH = re.compile(r"\$[^$]*\$")
_MACRO = re.compile(r"\\[a-zA-Z]+\*?(\[[^\]]*\])?(\{[^{}]*\})?")
_BRACE_TILDE = re.compile(r"[{}\\~]")
_WHITESPACE = re.compile(r"\s+")

_SECTION_HEADING = re.compile(r"\s*\\(section|subsection)\{(.+?)\}")
# Matches "I" as-is, the lowercase pronouns for mid-sentence use, and their
# sentence-initial Title-case spellings ("We propose", "Our contribution")
# since that is where most first-person prose in a paper actually starts.
# Fully upper-case spellings ("US", "WE") are deliberately excluded: they are
# not in the alternation, so "US" (United States) and similar acronyms never
# match. The negative lookbehind on a backslash stays load-bearing (see
# scan_pronouns below).
_PRONOUN = re.compile(
    r"(?<![A-Za-z\\])(I|my|me|mine|we|our|ours|us|My|Me|Mine|We|Our|Ours|Us)(?![A-Za-z])"
)
_LIST_BEGIN = re.compile(r"\\begin\{(itemize|enumerate|description)\}")


def extract_prose(raw: str) -> str:
    """
    --------------------------------------------------------------------------
    Purpose:
        Reduce a .tex file to approximate running prose for sentence-length
        statistics: float-like and keyword environments removed, comments
        stripped, inline math collapsed to a placeholder token, macros and
        braces stripped. Not a full LaTeX parser; the approximation is the
        same one aiscan.py measured the sentence-uniformity signal against.

    Inputs:
        raw (str): full .tex source.

    Outputs:
        prose (str): whitespace-collapsed approximate prose text.
    --------------------------------------------------------------------------
    """
    txt = _FLOAT_LIKE_ENV.sub(" ", raw)
    txt = _COMMENT_TO_EOL.sub("", txt)
    txt = _INLINE_MATH.sub(" X ", txt)
    txt = _MACRO.sub(" ", txt)
    txt = _BRACE_TILDE.sub(" ", txt)
    txt = _WHITESPACE.sub(" ", txt)
    return txt


def sentence_lengths(prose: str) -> Tuple[List[str], List[int]]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Split prose into sentences and measure each one's word count.

    Inputs:
        prose (str): output of extract_prose (or any plain text).

    Outputs:
        sentences (List[str]), lengths (List[int]): sentences longer than 3
            characters after stripping, and their word counts, same order.
    --------------------------------------------------------------------------
    """
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", prose) if len(s.strip()) > 3]
    lengths = [len(s.split()) for s in sentences]
    return sentences, lengths


def sentence_uniformity(lengths: List[int]) -> Optional[Dict]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Find the 10-sentence sliding window with the lowest population
        standard deviation of sentence length, the signal paper-auditor.md
        Step 7.5 flags when that minimum falls below 4 words.

    Inputs:
        lengths (List[int]): per-sentence word counts, in document order.

    Outputs:
        result (Optional[Dict]): None if fewer than 10 sentences exist
            (no window to measure), else {"min_window_stdev": float,
            "min_window_start_sentence": int, "flagged": bool}.
    --------------------------------------------------------------------------
    """
    if len(lengths) < 10:
        return None
    min_std = None
    min_start = None
    for i in range(0, len(lengths) - 9):
        window = lengths[i:i + 10]
        sd = statistics.pstdev(window)
        if min_std is None or sd < min_std:
            min_std, min_start = sd, i
    return {
        "min_window_stdev": min_std,
        "min_window_start_sentence": min_start,
        "flagged": min_std is not None and min_std < 4,
    }


def build_sections(text: str) -> Dict:
    """
    --------------------------------------------------------------------------
    Purpose:
        Build a \\section/\\subsection line map plus the abstract's line
        range (detected from \\begin{abstract}/\\end{abstract} rather than a
        hardcoded line range), so a hit can be attributed to the section it
        falls in.

    Inputs:
        text (str): single manuscript's .tex source.

    Outputs:
        section_map (Dict): {"sections": [{"line": int, "kind": str,
            "title": str}, ...], "abstract_start": Optional[int],
            "abstract_end": Optional[int]}.
    --------------------------------------------------------------------------
    """
    sections = []
    abstract_start = None
    abstract_end = None
    for i, line in enumerate(text.split("\n"), 1):
        m = _SECTION_HEADING.match(line)
        if m:
            sections.append({"line": i, "kind": m.group(1), "title": m.group(2)})
        if abstract_start is None and r"\begin{abstract}" in line:
            abstract_start = i
        if abstract_end is None and r"\end{abstract}" in line:
            abstract_end = i
    return {"sections": sections, "abstract_start": abstract_start, "abstract_end": abstract_end}


def section_of(line_no: int, section_map: Optional[Dict]) -> Optional[str]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Attribute a line number to the most specific heading it falls under.
        Both \\section and \\subsection headings advance the current title,
        so a hit inside subsection B (nested in section A) is reported
        against B, not against A. This is more specific than
        compose_audit.py's section_of, which only tracked \\section.

    Inputs:
        line_no (int): 1-based line number.
        section_map (Optional[Dict]): output of build_sections, or None when
            section attribution is not available (multi-file fallback).

    Outputs:
        title (Optional[str]): "Abstract", the nearest preceding \\section or
            \\subsection title, "PREAMBLE" if line_no precedes the first
            heading, or None if section_map is None.
    --------------------------------------------------------------------------
    """
    if section_map is None:
        return None
    if (
        section_map["abstract_start"] is not None
        and section_map["abstract_end"] is not None
        and section_map["abstract_start"] <= line_no <= section_map["abstract_end"]
    ):
        return "Abstract"
    current = "PREAMBLE"
    for entry in section_map["sections"]:
        if entry["line"] <= line_no:
            current = entry["title"]
    return current


def scan_pronouns(text: str, section_map: Optional[Dict], path: str) -> List[Dict]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Find first-person pronoun occurrences outside comments. The negative
        lookbehind on a backslash is load-bearing: without it, `\\item`,
        `\\mine`, and any macro ending in a pronoun token would match.

    Inputs:
        text (str): .tex source.
        section_map (Optional[Dict]): output of build_sections, or None.
        path (str): file path, recorded on every hit.

    Outputs:
        hits (List[Dict]): [{"file": str, "line": int, "token": str,
            "context": str, "section": Optional[str]}, ...], context being
            50 characters on each side of the match.
    --------------------------------------------------------------------------
    """
    hits = []
    for i, line in enumerate(text.split("\n"), 1):
        if line.strip().startswith("%"):
            continue
        body = re.sub(r"%.*$", "", line)
        for m in _PRONOUN.finditer(body):
            context = body[max(0, m.start() - 50):m.end() + 50].strip()
            hits.append({
                "file": path,
                "line": i,
                "token": m.group(1),
                "context": context,
                "section": section_of(i, section_map),
            })
    return hits


def scan_lists(text: str, section_map: Optional[Dict]) -> List[Dict]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Locate itemize/enumerate/description environments and flag ones with
        3+ items of nearly equal length as a "perfect parallel list" signal
        (paper-auditor.md Step 7.5): items whose word-count spread (population
        stdev / mean) is below 0.3. Environment ranges derive from the
        \\begin/\\end markers actually present, never a hardcoded line range.

    Inputs:
        text (str): .tex source.
        section_map (Optional[Dict]): output of build_sections, or None.

    Outputs:
        lists (List[Dict]): [{"line": int, "env": str, "item_count": int,
            "parallel": bool, "section": Optional[str]}, ...].
    --------------------------------------------------------------------------
    """
    starts = build_line_starts(text)
    results = []
    for m in _LIST_BEGIN.finditer(text):
        env = m.group(1)
        end_m = re.search(r"\\end\{" + re.escape(env) + r"\}", text[m.end():])
        end_pos = m.end() + end_m.start() if end_m else len(text)
        body = text[m.end():end_pos]
        items = [it.strip() for it in re.split(r"\\item\b", body)[1:] if it.strip()]
        item_lens = [len(it.split()) for it in items]
        parallel = False
        if len(item_lens) >= 3:
            mean = statistics.mean(item_lens)
            if mean > 0:
                parallel = (statistics.pstdev(item_lens) / mean) < 0.3
        ln = line_at(m.start(), starts)
        results.append({
            "line": ln,
            "env": env,
            "item_count": len(item_lens),
            "parallel": parallel,
            "section": section_of(ln, section_map),
        })
    return results
