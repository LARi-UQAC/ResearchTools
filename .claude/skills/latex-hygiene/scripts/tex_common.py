"""
tex_common - shared parsing primitives for the latex-hygiene skill.

Every tex_check.py subcommand imports this module for glob expansion, comment
stripping, the changes-package accepted-text resolver, float stripping, word
counting, and line-number lookup. Keeping these in one place is what lets
`wc --accepted` and `par` reuse the exact same balanced-brace argument reader
instead of each carrying a slightly different copy.
"""

import bisect
import glob
import logging
import re
from typing import List, Tuple

logger = logging.getLogger(__name__)

# Forbidden characters for the `chars` subcommand and the house-style rule in
# .claude/CLAUDE.md "Style hygiene". The last three (MULT SIGN, DEGREE, MINUS
# SIGN) come from compose_audit.py (source #9); LaTeX renders them as
# $\times$, $^\circ$, and $-$ rather than the raw Unicode glyph.
BAD_CHARS = {
    "\u200b": "ZERO WIDTH SPACE",
    "\u200c": "ZWNJ",
    "\u200d": "ZWJ",
    "\u2014": "EM DASH",
    "\u2013": "EN DASH",
    "\u2018": "LEFT SINGLE QUOTE",
    "\u2019": "RIGHT SINGLE QUOTE",
    "\u201c": "LEFT DOUBLE QUOTE",
    "\u201d": "RIGHT DOUBLE QUOTE",
    "\u2026": "HORIZONTAL ELLIPSIS",
    "\u00d7": "MULT SIGN",
    "\u00b0": "DEGREE",
    "\u2212": "MINUS SIGN",
}

# changes-package track-change macros: \added{...}, \deleted{...},
# \replaced{new}{old}, each with an optional [comment] argument.
CHANGES_MACRO = re.compile(r"\\(added|deleted|replaced)(\[[^\]]*\])?\{")

FLOAT_ENV = re.compile(r"\\begin\{(table\*?|figure\*?)\}.*?\\end\{\1\}", re.S)
COMMENT_LINE = re.compile(r"(?m)(?<!\\)%.*$")
WORD = re.compile(r"[A-Za-z][A-Za-z'-]+")


def expand_globs(patterns: List[str]) -> List[str]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Expand a list of file paths / glob patterns into a sorted, deduplicated
        list of existing file paths. Every subcommand takes paths as arguments
        (never a hardcoded file list or a chdir), so this is the single entry
        point that turns CLI arguments into files to read.

    Inputs:
        patterns (List[str]): literal paths and/or glob patterns.

    Outputs:
        files (List[str]): sorted, deduplicated, existing files.
    --------------------------------------------------------------------------
    """
    seen = set()
    for pattern in patterns:
        for match in glob.glob(pattern):
            seen.add(match)
        if "*" not in pattern and "?" not in pattern:
            seen.add(pattern)
    return sorted(p for p in seen if p)


def read_text(path: str) -> str:
    """
    --------------------------------------------------------------------------
    Purpose:
        Read a .tex (or .bib) file as UTF-8 text.

    Inputs:
        path (str): file path.

    Outputs:
        text (str): file content.
    --------------------------------------------------------------------------
    """
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def strip_comments(text: str) -> str:
    """
    --------------------------------------------------------------------------
    Purpose:
        Remove LaTeX line comments (`%` to end of line) without treating an
        escaped `\\%` as a comment start.

    Inputs:
        text (str): raw LaTeX source.

    Outputs:
        text (str): source with comments removed.
    --------------------------------------------------------------------------
    """
    return COMMENT_LINE.sub("", text)


def strip_floats(text: str) -> str:
    """
    --------------------------------------------------------------------------
    Purpose:
        Remove table/figure float environments (including starred variants)
        so word counts and prose scans measure body text only.

    Inputs:
        text (str): LaTeX source.

    Outputs:
        text (str): source with float environments removed.
    --------------------------------------------------------------------------
    """
    return FLOAT_ENV.sub("", text)


def count_words(text: str) -> int:
    """
    --------------------------------------------------------------------------
    Purpose:
        Count prose words in already-cleaned text.

    Inputs:
        text (str): text with comments/floats already stripped.

    Outputs:
        count (int): number of word-tokens matched by WORD.
    --------------------------------------------------------------------------
    """
    return len(WORD.findall(text))


def build_line_starts(text: str) -> List[int]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Precompute the character offset of the start of every line, so a
        character position can be converted to a 1-based line number in
        O(log n) via bisect instead of re-scanning the file per lookup.

    Inputs:
        text (str): file content.

    Outputs:
        starts (List[int]): starts[i] is the offset of line i+1.
    --------------------------------------------------------------------------
    """
    starts = [0]
    for line in text.split("\n"):
        starts.append(starts[-1] + len(line) + 1)
    return starts


def line_at(pos: int, starts: List[int]) -> int:
    """
    --------------------------------------------------------------------------
    Purpose:
        Convert a character offset into a 1-based line number.

    Inputs:
        pos (int): character offset into the text used to build `starts`.
        starts (List[int]): output of build_line_starts.

    Outputs:
        line (int): 1-based line number containing pos.
    --------------------------------------------------------------------------
    """
    return bisect.bisect_right(starts, pos)


def read_balanced_arg(src: str, i: int) -> Tuple[str, int]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Read one balanced-brace macro argument. `i` must point just past the
        opening `{`. Skips `\\{` and `\\}` escapes so an escaped brace never
        throws off the depth count. Verbatim port of accepted_wc.py::_arg,
        reused by both `wc --accepted` (via resolve) and `par`.

    Inputs:
        src (str): full source text.
        i (int): index just past the opening brace.

    Outputs:
        content (str), end (int): the argument's inner text, and the index
        just past the matching closing brace.
    --------------------------------------------------------------------------
    """
    depth, start = 1, i
    while i < len(src):
        c = src[i]
        if c == "\\":
            i += 2
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return src[start:i], i + 1
        i += 1
    return src[start:], i


def resolve_accepted(src: str) -> str:
    """
    --------------------------------------------------------------------------
    Purpose:
        Resolve changes-package track-change macros to the text that
        `\\usepackage[final]{changes}` actually renders: \\replaced{new}{old}
        -> new, \\deleted{...} -> nothing, \\added{...} -> content (recursed,
        so a \\replaced nested inside an \\added resolves to just the nested
        replacement, never the concatenation of both branches). Verbatim port
        of accepted_wc.py::resolve.

    Inputs:
        src (str): LaTeX source, comments already stripped.

    Outputs:
        text (str): source with all changes-package macros resolved.
    --------------------------------------------------------------------------
    """
    out: List[str] = []
    pos = 0
    while True:
        m = CHANGES_MACRO.search(src, pos)
        if not m:
            out.append(src[pos:])
            break
        out.append(src[pos:m.start()])
        kind = m.group(1)
        a1, j = read_balanced_arg(src, m.end())
        if kind == "replaced":
            k = src.find("{", j)
            _a2, j = read_balanced_arg(src, k + 1)
            out.append(resolve_accepted(a1))
        elif kind == "added":
            out.append(resolve_accepted(a1))
        # deleted -> nothing emitted
        pos = j
    return "".join(out)


def macro_arg_spans(src: str, macro: re.Pattern) -> List[Tuple[int, int, str, str]]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Locate every match of a `\\name{...}` (or `\\name{a}{b}` for
        `\\replaced`) style macro and return the full source span each call
        occupies, using the same balanced-brace walk as read_balanced_arg so
        nested braces inside the argument(s) do not truncate the span early.

    Inputs:
        src (str): LaTeX source.
        macro (re.Pattern): pattern whose group(1) is the macro name; only
            "replaced" is treated as two-argument, everything else as one.

    Outputs:
        spans (List[Tuple[int, int, str, str]]): (start, end, name, full_text)
            for each match, where full_text is src[start:end].
    --------------------------------------------------------------------------
    """
    spans = []
    for m in macro.finditer(src):
        i = m.end()
        depth = 1
        nargs = 2 if m.group(1) == "replaced" else 1
        done = 0
        while i < len(src) and done < nargs:
            c = src[i]
            if c == "\\":
                i += 2
                continue
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    done += 1
                    if done < nargs:
                        j = src.find("{", i + 1)
                        if j == -1:
                            break
                        i = j
                        depth = 1
            i += 1
        spans.append((m.start(), i, m.group(1), src[m.start():i]))
    return spans


def scan_bad_chars(text: str) -> dict:
    """
    --------------------------------------------------------------------------
    Purpose:
        Count each BAD_CHARS occurrence in text, keyed by character name.

    Inputs:
        text (str): LaTeX source (any file).

    Outputs:
        hits (dict): {name: count} for characters actually present.
    --------------------------------------------------------------------------
    """
    hits = {}
    for ch, name in BAD_CHARS.items():
        n = text.count(ch)
        if n:
            hits[name] = n
    return hits


def excerpt_words(text: str, start: int, max_words: int = 15) -> str:
    """
    --------------------------------------------------------------------------
    Purpose:
        Take up to max_words words starting at a character offset, for the
        "15-word excerpt per hit" requirement of the aiscan output.

    Inputs:
        text (str): source text to excerpt from.
        start (int): character offset to start at.
        max_words (int): word budget (default 15).

    Outputs:
        excerpt (str): whitespace-joined excerpt, possibly shorter than
            max_words if the text ends first.
    --------------------------------------------------------------------------
    """
    tail = text[start:start + 400]
    words = tail.split()
    return " ".join(words[:max_words])
