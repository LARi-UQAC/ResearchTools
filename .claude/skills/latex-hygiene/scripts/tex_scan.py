"""
tex_scan - subcommand `scan`: post-write LaTeX track-changes hygiene guard.

Stage: latex-hygiene pipeline, write-side verification. Six guards distilled
from the 2026-08-26 Assistive-feeding-robot session
(docs/superpowers/todo/2026-08-26-latex-trackchanges-patcher.md): control
characters including TAB, damaged control-sequence residue, a `changes`
macro crossing a table/figure boundary, a `%` comment swallowing a table
row terminator, a retracted `\\cite` still resolved by BibTeX, and live
`\\hl{}`/`\\todo{}`/`TODO()` markers. Runs standalone on any `.tex` file
edited by any means, and automatically at the end of a successful
(non-dry-run) `patch` (tex_patch.py).
"""

import logging
import re
from typing import Dict, List, Optional

from tex_common import CHANGES_MACRO, build_line_starts, line_at, macro_arg_spans, read_balanced_arg, read_text

logger = logging.getLogger(__name__)

# Guard 2: control characters, INCLUDING TAB (\x09). This is the load-bearing
# detail: a non-raw Python replacement string turns \t into a real tab inside
# \textbf, \n into a real line break inside \newline, and \a into BEL inside
# \approx. It happened five times in one session and the first scan MISSED
# ALL FIVE because its class [\x00-\x08\x0b\x0c\x0e-\x1f] excludes \x09.
_CONTROL_CHAR = re.compile(r"[\x00-\x09\x0b\x0c\x0e-\x1f]")

# Guard 2b: control-sequence residue left when the same corruption eats the
# leading backslash (\textbf -> <TAB>extbf, \newline -> <LF>ewline, ...).
_DAMAGED_RESIDUE = re.compile(r"(?<!\\)(extbf|extit|extt|ewline|note\{|pprox|imes|ilde)")

# Guard 4: float/table environments a `changes` macro must not cross. A whole
# `table` inside `\replaced` does not compile; a `\replaced` inside a
# tabularx cell compiles in draft but fails under [final]{changes}, because
# tabularx re-scans the cell body.
_FLOAT_ENV = re.compile(r"\\begin\{(tabularx|tabular|table\*?|figure\*?)\}(.*?)\\end\{\1\}", re.S)

# Guard 5: an unescaped '%' precedes the LaTeX row terminator on the same
# line, so it is dead comment text instead of the actual row terminator.
_COMMENT_START = re.compile(r"(?<!\\)%")
_ROW_TERMINATOR = "\\" + "\\"  # two literal backslash characters

# Live markers: submission defects, not automatically fatal (--fail-on-markers).
_MARKER = re.compile(r"\\hl\{|\\todo\{|TODO\([^)]*\)")

_CITE = re.compile(r"\\cite\{([^}]*)\}")
_BIB_KEY = re.compile(r"@\w+\{([^,]+),")


def _context60(text: str, pos: int) -> str:
    """
    --------------------------------------------------------------------------
    Purpose:
        Take a 60-character window centered on a hit position, for the
        per-guard report.

    Inputs:
        text (str): source text.
        pos (int): character offset of the hit.

    Outputs:
        context (str): up to 60 characters around pos, newlines escaped so
            the report stays one line per hit.
    --------------------------------------------------------------------------
    """
    start = max(0, pos - 30)
    return text[start:pos + 30].replace("\n", "\\n")


def _scan_control_chars(text: str, starts: List[int]) -> List[Dict]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Guard 2: locate every control character, TAB included.

    Inputs:
        text (str): .tex source.
        starts (List[int]): tex_common.build_line_starts(text).

    Outputs:
        hits (List[Dict]): {"line", "code", "context"} per hit.
    --------------------------------------------------------------------------
    """
    return [
        {"line": line_at(m.start(), starts), "code": "0x%02x" % ord(m.group(0)), "context": _context60(text, m.start())}
        for m in _CONTROL_CHAR.finditer(text)
    ]


def _scan_damaged_residue(text: str, starts: List[int]) -> List[Dict]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Guard 2b: locate control-sequence residue not preceded by a backslash.

    Inputs:
        text (str): .tex source.
        starts (List[int]): tex_common.build_line_starts(text).

    Outputs:
        hits (List[Dict]): {"line", "match", "context"} per hit.
    --------------------------------------------------------------------------
    """
    return [
        {"line": line_at(m.start(), starts), "match": m.group(1), "context": _context60(text, m.start())}
        for m in _DAMAGED_RESIDUE.finditer(text)
    ]


def _scan_float_boundary(text: str, starts: List[int]) -> List[Dict]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Guard 4: flag a `changes` macro whose span overlaps (in either
        direction of containment) a tabularx/tabular/table/figure span.

    Inputs:
        text (str): .tex source.
        starts (List[int]): tex_common.build_line_starts(text).

    Outputs:
        hits (List[Dict]): {"line", "macro", "env"} per overlapping pair.
    --------------------------------------------------------------------------
    """
    envs = [(m.start(), m.end(), m.group(1)) for m in _FLOAT_ENV.finditer(text)]
    hits = []
    for ms, me, kind, _full in macro_arg_spans(text, CHANGES_MACRO):
        for es, ee, envname in envs:
            if ms < ee and es < me:
                hits.append({"line": line_at(ms, starts), "macro": kind, "env": envname})
                break
    return hits


def _scan_table_comment(text: str) -> List[Dict]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Guard 5: flag a line whose unescaped `%` is followed, later on the
        same line, by the LaTeX row terminator - the terminator was appended
        after the comment marker and is now dead text.

    Inputs:
        text (str): .tex source.

    Outputs:
        hits (List[Dict]): {"line", "context"} per hit.
    --------------------------------------------------------------------------
    """
    hits = []
    for ln, line in enumerate(text.split("\n"), 1):
        m = _COMMENT_START.search(line)
        if m and _ROW_TERMINATOR in line[m.end():]:
            hits.append({"line": ln, "context": line.strip()[:60]})
    return hits


def _scan_dangling_cite(text: str, bib_keys: Optional[set], starts: List[int]) -> List[Dict]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Guard 6: flag a `\\cite{key}` inside a `\\deleted` argument, or the
        second (old) argument of a `\\replaced`, whose key is absent from
        the given `.bib`. `changes` typesets that argument, so its citations
        still hit BibTeX even after the key was renamed elsewhere.

    Inputs:
        text (str): .tex source.
        bib_keys (Optional[set]): known bib entry keys, or None to skip
            (no --bib given).
        starts (List[int]): tex_common.build_line_starts(text).

    Outputs:
        hits (List[Dict]): {"line", "key", "macro"} per dangling citation.
    --------------------------------------------------------------------------
    """
    if bib_keys is None:
        return []
    hits = []
    pos = 0
    while True:
        m = CHANGES_MACRO.search(text, pos)
        if not m:
            break
        kind = m.group(1)
        a1, j = read_balanced_arg(text, m.end())
        checked = None
        if kind == "deleted":
            checked = a1
        elif kind == "replaced":
            k = text.find("{", j)
            checked, j = read_balanced_arg(text, k + 1)
        if checked:
            for cite_arg in _CITE.findall(checked):
                for key in cite_arg.split(","):
                    key = key.strip()
                    if key and key not in bib_keys:
                        hits.append({"line": line_at(m.start(), starts), "key": key, "macro": kind})
        pos = j
    return hits


def _scan_markers(text: str, starts: List[int]) -> List[Dict]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Locate live `\\hl{}`, `\\todo{}` and `TODO(author)` markers, counted
        always and failed only when --fail-on-markers is passed.

    Inputs:
        text (str): .tex source.
        starts (List[int]): tex_common.build_line_starts(text).

    Outputs:
        hits (List[Dict]): {"line", "marker", "context"} per hit.
    --------------------------------------------------------------------------
    """
    return [
        {"line": line_at(m.start(), starts), "marker": m.group(0), "context": _context60(text, m.start())}
        for m in _MARKER.finditer(text)
    ]


def scan_files(files: List[str], bib_file: Optional[str], fail_on_markers: bool) -> Dict:
    """
    --------------------------------------------------------------------------
    Purpose:
        Run all six guards over a set of .tex files.

    Inputs:
        files (List[str]): .tex file paths (already glob-expanded).
        bib_file (Optional[str]): .bib file for the dangling-cite guard, or
            None to skip that guard.
        fail_on_markers (bool): recorded in the result; the --strict gate
            reads it via has_scan_defect.

    Outputs:
        result (Dict): {"files": {path: {guard_name: [hits]}}, "totals":
            {guard_name: int}, "bib_checked": bool, "fail_on_markers": bool}.
    --------------------------------------------------------------------------
    """
    bib_keys = set(_BIB_KEY.findall(read_text(bib_file))) if bib_file else None
    per_file: Dict[str, Dict] = {}
    totals = {"control_chars": 0, "damaged_residue": 0, "float_boundary": 0,
              "table_comment": 0, "dangling_cite": 0, "markers": 0}
    for path in files:
        text = read_text(path)
        starts = build_line_starts(text)
        info = {
            "control_chars": _scan_control_chars(text, starts),
            "damaged_residue": _scan_damaged_residue(text, starts),
            "float_boundary": _scan_float_boundary(text, starts),
            "table_comment": _scan_table_comment(text),
            "dangling_cite": _scan_dangling_cite(text, bib_keys, starts),
            "markers": _scan_markers(text, starts),
        }
        per_file[path] = info
        for name in totals:
            totals[name] += len(info[name])
    logger.info("[HYGIENE] scan: %d files, totals=%s", len(files), totals)
    return {"files": per_file, "totals": totals, "bib_checked": bib_keys is not None, "fail_on_markers": fail_on_markers}


def has_scan_defect(result: Dict, fail_on_markers: bool) -> bool:
    """
    --------------------------------------------------------------------------
    Purpose:
        Decide whether a scan result should trip --strict: the five
        mandatory guards always count; markers only when fail_on_markers.

    Inputs:
        result (Dict): output of scan_files.
        fail_on_markers (bool): --fail-on-markers as passed on the CLI.

    Outputs:
        defect (bool): True if --strict should cause a non-zero exit.
    --------------------------------------------------------------------------
    """
    t = result["totals"]
    mandatory = t["control_chars"] or t["damaged_residue"] or t["float_boundary"] or t["table_comment"] or t["dangling_cite"]
    return bool(mandatory or (fail_on_markers and t["markers"]))


def print_scan_text(result: Dict) -> None:
    """
    --------------------------------------------------------------------------
    Purpose:
        Plain-text rendering of a `scan` result for interactive use.

    Inputs:
        result (Dict): output of scan_files.

    Outputs:
        None. Writes to stdout.
    --------------------------------------------------------------------------
    """
    for path, info in result["files"].items():
        print(path)
        for name, hits in info.items():
            print("  %s: %d" % (name, len(hits)))
    print("TOTALS:", result["totals"])
    if not result["bib_checked"]:
        print("dangling_cite: skipped (no --bib given)")
