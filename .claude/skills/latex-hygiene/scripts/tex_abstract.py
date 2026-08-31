"""
tex_abstract - subcommand `abstract`: abstract word count and keyword count.

Stage: latex-hygiene pipeline, submission-readiness check. Port of count.py,
made argument-driven: takes the main .tex path instead of an absolute
constant, and reports missing abstract/keywords explicitly instead of raising
an IndexError on split().
"""

import logging
import re
from typing import Dict

from tex_common import read_text

logger = logging.getLogger(__name__)

_TAG_STRIP = re.compile(r"[\\{}$]")


def scan_abstract(main_file: str) -> Dict:
    """
    --------------------------------------------------------------------------
    Purpose:
        Count words in \\begin{abstract}...\\end{abstract} (LaTeX commands and
        math delimiters stripped) and entries in \\begin{IEEEkeywords}...
        \\end{IEEEkeywords}.

    Inputs:
        main_file (str): path to the manuscript's main .tex file.

    Outputs:
        result (Dict): {"abstract_words": int, "keyword_count": int,
            "abstract_found": bool, "keywords_found": bool}.
    --------------------------------------------------------------------------
    """
    text = read_text(main_file)
    abstract_found = r"\begin{abstract}" in text and r"\end{abstract}" in text
    abstract_words = 0
    if abstract_found:
        body = text.split(r"\begin{abstract}")[1].split(r"\end{abstract}")[0]
        body = _TAG_STRIP.sub(" ", body)
        words = [w for w in body.split() if any(c.isalnum() for c in w)]
        abstract_words = len(words)

    keywords_found = r"\begin{IEEEkeywords}" in text and r"\end{IEEEkeywords}" in text
    keyword_count = 0
    if keywords_found:
        kw_body = text.split(r"\begin{IEEEkeywords}")[1].split(r"\end{IEEEkeywords}")[0]
        keyword_count = len([w for w in kw_body.split(",") if w.strip()])

    logger.info(
        "[HYGIENE] abstract: %s -> %d words, %d keywords",
        main_file, abstract_words, keyword_count,
    )
    return {
        "abstract_words": abstract_words,
        "keyword_count": keyword_count,
        "abstract_found": abstract_found,
        "keywords_found": keywords_found,
    }
