"""
tex_citecov - subcommand `citecov`: citation coverage against a .bib file.

Stage: latex-hygiene pipeline, reference-integrity check. Port of citecov.py:
splits \\cite{a,b} on the comma and reads .bib keys with `@\\w+\\{([^,]+),`.
"""

import logging
import re
from typing import Dict, List

from tex_common import read_text

logger = logging.getLogger(__name__)

_CITE = re.compile(r"\\cite\{([^}]*)\}")
_BIB_KEY = re.compile(r"@\w+\{([^,]+),")


def scan_citecov(tex_files: List[str], bib_file: str) -> Dict:
    """
    --------------------------------------------------------------------------
    Purpose:
        Compare the set of keys cited across `tex_files` against the entries
        defined in `bib_file`, reporting dangling citations (cited, no bib
        entry) and uncited entries (in the bib, never cited).

    Inputs:
        tex_files (List[str]): .tex files to scan for \\cite{...}.
        bib_file (str): path to the .bib file.

    Outputs:
        result (Dict): {"cited_count": int, "bib_entry_count": int,
            "dangling": List[str], "uncited": List[str],
            "all_cited": List[str]}.
    --------------------------------------------------------------------------
    """
    cited = set()
    for path in tex_files:
        text = read_text(path)
        for m in _CITE.findall(text):
            for key in m.split(","):
                key = key.strip()
                if key:
                    cited.add(key)
    bib_text = read_text(bib_file)
    bib_keys = set(_BIB_KEY.findall(bib_text))
    dangling = sorted(cited - bib_keys)
    uncited = sorted(bib_keys - cited)
    logger.info(
        "[HYGIENE] citecov: %d cited, %d bib entries, %d dangling, %d uncited",
        len(cited), len(bib_keys), len(dangling), len(uncited),
    )
    return {
        "cited_count": len(cited),
        "bib_entry_count": len(bib_keys),
        "dangling": dangling,
        "uncited": uncited,
        "all_cited": sorted(cited),
    }
