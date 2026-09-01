"""
tex_refcov - subcommand `refcov`: label / cross-reference coverage.

Stage: latex-hygiene pipeline, reference-integrity check. Sibling to
tex_citecov.py, but for \\label/\\ref instead of \\cite/.bib: .claude/CLAUDE.md
requires every figure, table, and equation to carry a label and be cited in
the text (\\ref{}/\\eqref{}), and nothing in the repo measured that before
this subcommand. Also flags duplicate \\label{} keys, since a duplicate makes
every \\ref to that key ambiguous at compile time.
"""

import logging
import re
from typing import Dict, List

from tex_common import build_line_starts, line_at, read_text

logger = logging.getLogger(__name__)

_LABEL = re.compile(r"\\label\{([^}]*)\}")
_REF = re.compile(r"\\(ref|eqref|cref|autoref)\{([^}]*)\}")


def scan_refcov(files: List[str]) -> Dict:
    """
    --------------------------------------------------------------------------
    Purpose:
        Compare the set of \\label{} keys defined across `files` against the
        keys used in \\ref/\\eqref/\\cref/\\autoref, reporting labels never
        referenced, references with no matching label, and duplicate label
        keys.

    Inputs:
        files (List[str]): .tex files to scan.

    Outputs:
        result (Dict): {"label_count": int, "reference_count": int,
            "uncited_labels": List[str], "dangling_references": List[str],
            "duplicate_labels": [{"key": str, "lines": [{"file": str,
            "line": int}, ...]}, ...], "all_labels": List[str],
            "all_references": List[str]}.
    --------------------------------------------------------------------------
    """
    label_occurrences: Dict[str, List[Dict]] = {}
    ref_keys = set()

    for path in files:
        text = read_text(path)
        starts = build_line_starts(text)
        for m in _LABEL.finditer(text):
            key = m.group(1).strip()
            if key:
                label_occurrences.setdefault(key, []).append(
                    {"file": path, "line": line_at(m.start(), starts)}
                )
        for m in _REF.finditer(text):
            for key in m.group(2).split(","):
                key = key.strip()
                if key:
                    ref_keys.add(key)

    label_keys = set(label_occurrences)
    uncited_labels = sorted(label_keys - ref_keys)
    dangling_references = sorted(ref_keys - label_keys)
    duplicate_labels = [
        {"key": key, "lines": occurrences}
        for key, occurrences in sorted(label_occurrences.items())
        if len(occurrences) > 1
    ]

    logger.info(
        "[HYGIENE] refcov: %d labels, %d references, %d uncited, %d dangling, %d duplicate",
        len(label_keys), len(ref_keys), len(uncited_labels), len(dangling_references),
        len(duplicate_labels),
    )
    return {
        "label_count": len(label_keys),
        "reference_count": len(ref_keys),
        "uncited_labels": uncited_labels,
        "dangling_references": dangling_references,
        "duplicate_labels": duplicate_labels,
        "all_labels": sorted(label_keys),
        "all_references": sorted(ref_keys),
    }
