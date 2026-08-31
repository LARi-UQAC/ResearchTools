"""
tex_chars - subcommand `chars`: forbidden invisible / typographic character scan.

Stage: latex-hygiene pipeline, character-level hygiene check. Verbatim port of
charscan.py's BAD table (via tex_common.BAD_CHARS), extended with the three
characters from compose_audit.py (MULT SIGN, DEGREE, MINUS SIGN).
"""

import logging
from typing import Dict, List

from tex_common import BAD_CHARS, read_text

logger = logging.getLogger(__name__)


def scan_chars(files: List[str]) -> Dict:
    """
    --------------------------------------------------------------------------
    Purpose:
        Report every forbidden character hit, per file and per line.

    Inputs:
        files (List[str]): .tex files to scan.

    Outputs:
        result (Dict): {"files": {path: [{"line": int, "name": str}, ...]},
            "total": int}. A file with no hits maps to an empty list.
    --------------------------------------------------------------------------
    """
    per_file = {}
    total = 0
    for path in files:
        hits = []
        text = read_text(path)
        for ln, line in enumerate(text.split("\n"), 1):
            for ch, name in BAD_CHARS.items():
                if ch in line:
                    hits.append({"line": ln, "name": name})
        per_file[path] = hits
        total += len(hits)
        logger.info("[HYGIENE] chars: %s -> %d hit(s)", path, len(hits))
    return {"files": per_file, "total": total}
