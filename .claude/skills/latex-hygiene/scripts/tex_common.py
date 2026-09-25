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

# Environments whose content is NOT the author's prose and must never enter a
# word count. `formhelp` holds the printed instructions of a grant form, which
# the applicant may neither delete nor restyle: they are on the page, they are
# not the applicant's words, and a form that caps a section at 300 words is
# not counting them. Named once here so the section counter and the file
# counter cannot disagree about what prose is (R5).
NON_PROSE_ENVS = ("formhelp",)
NON_PROSE_ENV = re.compile(
    r"\\begin\{(%s)\}.*?\\end\{\1\}" % "|".join(NON_PROSE_ENVS), re.S
)

# Accented Latin letters are part of a word. The ASCII-only class this
# replaced silently mis-tokenised French, the default language of a UQAC
# thesis: measured 2026-09-12 by tex_common.count_words, "ete", "ou" and
# "deja" written with their accents each counted as ZERO words, and
# "detection" counted as one token spelled "tection". A counter that drops
# the accented function words of the language it is pointed at reports an
# undercount that reads exactly like a measurement.
# U+00C0-U+024F covers Latin-1 Supplement letters, Latin Extended-A and
# Latin Extended-B, minus U+00D7 and U+00F7, the multiplication and
# division signs, which sit inside that block and are not letters.
# The two-character minimum is UNCHANGED and deliberate: a lone letter is
# skipped in French exactly as it already was in English, so "a" and "a"
# with a grave accent are treated alike and no existing count moves for a
# reason other than an accent.
_LETTER = "A-Za-z\u00c0-\u00d6\u00d8-\u00f6\u00f8-\u024f"
WORD = re.compile("[%s][%s'-]+" % (_LETTER, _LETTER))

# Macros whose braced argument is an identifier, a path or a setting rather
# than prose: the whole call goes, argument included.
_IDENT_MACROS = (
    "label|ref|eqref|autoref|pageref|nameref"
    "|cite|citep|citet|citeauthor|citeyear"
    "|includegraphics|input|include|usepackage|documentclass|bibliographystyle"
    "|bibitem|url|hypersetup|definecolor|setlength|renewcommand|newcommand"
    "|graphicspath|tikzset|usetikzlibrary|pagestyle|thispagestyle|bibliography"
)
_IDENT_MACRO = re.compile(
    r"\\(?:%s)\*?\s*(?:\[[^\]]*\])?\s*\{[^{}]*\}(?:\s*\{[^{}]*\})?" % _IDENT_MACROS
)
# Any remaining control sequence: the name is markup, not a word. Its braced
# argument is kept, because that is where \emph, \textbf and the
# changes-package macros carry real prose.
_ANY_MACRO = re.compile(r"\\[a-zA-Z]+\*?(?:\[[^\]]*\])?|\\.")


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


def read_artifact_text(path: str) -> str:
    """
    --------------------------------------------------------------------------
    Purpose:
        Read a LaTeX BUILD ARTIFACT (.log, .blg, .bbl) as text, tolerating
        bytes that are not valid UTF-8.

        Measured 2026-09-16 on MiKTeX under a French Windows, building
        BuildingGIS/financement/revue_litterature_complete.tex: the engine
        writes paths and messages in the system codepage, so byte 0xe9
        appeared at offset 43098 of the .log, the strict UTF-8 read of
        read_text raised UnicodeDecodeError, and `tex_check.py build`
        reported NOTHING although pdflatex and bibtex had both succeeded and
        the 61-page PDF was on disk. A build whose result cannot be read is
        indistinguishable from a build that failed, which is the defect.

        Source files keep read_text and its strict decode. A .tex or .bib
        that is not UTF-8 is an authoring defect to surface, while a log that
        is not UTF-8 is the ordinary output of the engine on this platform.

        Replacement is safe for every counter parse_counters extracts, since
        "!", "undefined", "doi.org" and the page-count pattern are pure ASCII
        and a replaced byte can neither create nor destroy one.

    Inputs:
        path (str): build-artifact file path.

    Outputs:
        text (str): file content, undecodable bytes replaced by U+FFFD.
    --------------------------------------------------------------------------
    """
    with open(path, encoding="utf-8", errors="replace") as handle:
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


def strip_non_prose_envs(text: str) -> str:
    """
    --------------------------------------------------------------------------
    Purpose:
        Remove the environments listed in NON_PROSE_ENVS, content included.
        A grant form prints its own instructions on the page ("Veuillez
        fournir : a) un apercu du probleme de recherche ... Maximum de 300
        mots"), and those words belong to the funding agency, not to the
        applicant. Counting them against the applicant's own cap is counting
        the ruler as part of what it measures.

    Inputs:
        text (str): LaTeX source.

    Outputs:
        text (str): source with those environments removed.

    Limit: the match is non-greedy and does not nest, so a formhelp inside a
    formhelp would end at the first \\end. Grant instruction blocks do not
    nest, and a nested one would be a authoring error worth seeing.
    --------------------------------------------------------------------------
    """
    return NON_PROSE_ENV.sub(" ", text)


def strip_macros(text: str) -> str:
    """
    --------------------------------------------------------------------------
    Purpose:
        Remove what a reader does not read aloud: the control sequences
        themselves, and the arguments of the macros whose argument is an
        identifier rather than prose. Measured 2026-09-12 on a Mitacs
        proposal section, "\\label{sommaire}" contributed the two words
        "label" and "sommaire", and every "\\subsubsection" contributed one
        more, so a 300-word form cap was being judged partly on markup.

    Inputs:
        text (str): LaTeX source, comments and floats already stripped.

    Outputs:
        text (str): source with identifier-only macro calls removed and
            remaining control sequences reduced to a space, braces kept as
            separators.

    Deliberate limit: the argument of any macro NOT named below is kept, and
    that is correct for the ones that wrap prose (\\emph, \\textbf, and the
    changes-package macros). A macro carrying a non-prose argument that is
    not in the list is counted as prose, so the list is the thing to extend
    rather than the rule.
    --------------------------------------------------------------------------
    """
    # \href{url}{text}: the first argument is an address, the second is prose.
    text = re.sub(r"\\href\s*\{[^{}]*\}\s*(?=\{)", " ", text)
    text = _IDENT_MACRO.sub(" ", text)
    text = _ANY_MACRO.sub(" ", text)
    return text.replace("{", " ").replace("}", " ")


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
