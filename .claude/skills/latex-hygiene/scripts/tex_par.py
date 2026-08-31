"""
tex_par - subcommand `par`: blank-line-inside-changes-macro detection.

Stage: latex-hygiene pipeline, changes-package safety check. Port of
par_check.py. The changes package macros (\\added, \\deleted, \\replaced) are
not \\long, so an argument that spans a blank line (a LaTeX \\par) breaks the
build; this reuses tex_common.macro_arg_spans, which walks the same
balanced-brace argument reader as read_balanced_arg (accepted_wc.py::_arg),
so both arguments of \\replaced are checked, not just the first.
"""

import logging
import re
from typing import Dict, List

from tex_common import CHANGES_MACRO, build_line_starts, line_at, macro_arg_spans, read_text

logger = logging.getLogger(__name__)

_BLANK_LINE = re.compile(r"\n[ \t]*\n")


def scan_par(files: List[str]) -> Dict:
    """
    --------------------------------------------------------------------------
    Purpose:
        Flag every \\added/\\deleted/\\replaced call whose argument text
        contains a blank line.

    Inputs:
        files (List[str]): .tex files to scan.

    Outputs:
        result (Dict): {"files": {path: [{"line": int, "macro": str}, ...]},
            "total": int}. A clean file maps to an empty list.
    --------------------------------------------------------------------------
    """
    per_file = {}
    total = 0
    for path in files:
        src = read_text(path)
        starts = build_line_starts(src)
        bad = []
        for start, end, name, full_text in macro_arg_spans(src, CHANGES_MACRO):
            if _BLANK_LINE.search(full_text):
                bad.append({"line": line_at(start, starts), "macro": name})
        per_file[path] = bad
        total += len(bad)
        logger.info("[HYGIENE] par: %s -> %d occurrence(s)", path, len(bad))
    return {"files": per_file, "total": total}
