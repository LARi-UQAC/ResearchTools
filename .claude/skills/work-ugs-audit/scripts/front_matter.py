"""
front_matter - the declared number of figures and tables of a student report (Issue 126, plan 5, requirement E1).

Stage: preparation of the work folder. declared_counts reads the entries printed in the list of figures and the
list of tables, on the pages the front roles of plan 10 identified. The entry words and the printed-number pattern
come from assets/front_matter.json (R0, R4, R6). A list that cannot be found is None, never zero; a list whose heading
is found with no entry is zero. No PDF is opened here: the caller passes the page texts.
"""

import json
import re
from pathlib import Path
from typing import Dict, List, Optional

import front_pages

ENTRY_WORDS_KEYS = ("figure_entry_words", "table_entry_words")
LANGUAGES = ("fr", "en")
NUMBER_PATTERN_KEY = "entry_number_pattern"


class FrontMatterEntryError(front_pages.FrontMatterConfigError):
    """Raised when the entry settings of the front-matter data file are missing or malformed (R3)."""


def _normalize(text: str) -> str:
    """
    Purpose:
        Put a text in the form used for marker comparisons: no accents, lower case, single spaces.

    Inputs:
        text (str): any text.

    Outputs:
        str: the normalized text.

    Raises:
        None.
    """
    return front_pages._normalize(text)


def load_entry_settings(path: Optional[Path] = None) -> dict:
    """
    Purpose:
        Load the entry words, the printed-number pattern and the list heading words from the front-matter file.

    Inputs:
        path (Path or None): the JSON data file; None means assets/front_matter.json.

    Outputs:
        dict: figure_entry_words and table_entry_words (each {"fr": [...], "en": [...]}), entry_number_pattern (str),
            and the marker maps of the list headings, as front_pages.load_front_matter returns them.

    Raises:
        FrontMatterEntryError: when the file, a key, a language or the pattern is missing or malformed.
    """
    target = Path(path) if path is not None else front_pages.DATA_FILE
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FrontMatterEntryError(f"cannot read {target}: {exc}") from exc
    result = front_pages.load_front_matter(target)
    for key in ENTRY_WORDS_KEYS:
        if key not in raw:
            raise FrontMatterEntryError(f"missing key '{key}' in {target}")
        entry = raw[key]
        for lang in LANGUAGES:
            words = entry.get(lang) if isinstance(entry, dict) else None
            if not isinstance(words, list) or not words or not all(isinstance(w, str) and w.strip() for w in words):
                raise FrontMatterEntryError(f"'{key}.{lang}' in {target} must be a non-empty list of words")
        result[key] = {lang: entry[lang] for lang in LANGUAGES}
    if NUMBER_PATTERN_KEY not in raw or not isinstance(raw[NUMBER_PATTERN_KEY], dict):
        raise FrontMatterEntryError(f"missing key '{NUMBER_PATTERN_KEY}' in {target}")
    pattern = raw[NUMBER_PATTERN_KEY].get("value")
    if not isinstance(pattern, str):
        raise FrontMatterEntryError(f"'{NUMBER_PATTERN_KEY}.value' in {target} must be a string")
    try:
        re.compile(pattern)
    except re.error as exc:
        raise FrontMatterEntryError(f"'{NUMBER_PATTERN_KEY}.value' in {target} is not a valid pattern: {exc}") from exc
    result[NUMBER_PATTERN_KEY] = pattern
    return result


def _entry_pattern(words: List[str], number_pattern: str) -> "re.Pattern":
    """
    Purpose:
        Build the pattern of one printed entry: a marker word, an optional dot, then the printed number.

    Inputs:
        words (List[str]): the entry words of the kind and language.
        number_pattern (str): the printed-number pattern from the data file.

    Outputs:
        re.Pattern: a case-insensitive pattern whose group 1 is the printed number.

    Raises:
        re.error: when the number pattern is not a valid regular expression.
    """
    alternatives = "|".join(re.escape(word) for word in words)
    return re.compile(r"(?<!\w)(?:" + alternatives + r")\.?\s*(" + number_pattern + r")(?!\w)", re.IGNORECASE)


def _heading_in(texts: List[str], pages: List[int], heading: List[str]) -> bool:
    """
    Purpose:
        Tell whether a list heading appears anywhere on the given pages (the text layer may hold it mid-page).

    Inputs:
        texts (List[str]): the text of each page, 1-based pages index texts[page - 1].
        pages (List[int]): the pages to search.
        heading (List[str]): the heading words of the list in the report language.

    Outputs:
        bool: True when one of the heading words is a whole word of one of the pages.

    Raises:
        None.
    """
    words = [_normalize(word) for word in heading if _normalize(word)]
    for page in pages:
        norm = _normalize(texts[page - 1])
        if any(re.search(r"(?<!\w)" + re.escape(word) + r"(?!\w)", norm) for word in words):
            return True
    return False


def _count_kind(texts: List[str], roles: dict, role: str, heading: List[str], words: List[str],
                settings: dict, toc_pages: List[int], label: str) -> dict:
    """
    Purpose:
        Count the printed entries of one kind (figures or tables), or report that the list is not found.

    Inputs:
        texts (List[str]): the text of each page, 1-based pages index texts[page - 1].
        roles (dict): the front roles of the report.
        role (str): the role of the list pages, "list_of_figures" or "list_of_tables".
        heading (List[str]): the heading words of the list in the report language.
        words (List[str]): the entry words of the kind in the report language.
        settings (dict): the result of load_entry_settings.
        toc_pages (List[int]): the contents pages, searched for the heading when the list has no page of its own.
        label (str): "figure" or "table", used in the duplicate list.

    Outputs:
        dict: count (None when not found), numbers, pages (one per entry), duplicates and source.

    Raises:
        None.
    """
    not_found = {"count": None, "numbers": None, "pages": None, "duplicates": [], "source": None}
    list_pages = list(roles.get(role) or [])
    if list_pages:
        pages, source = list_pages, role
    elif toc_pages and _heading_in(texts, toc_pages, heading):
        pages, source = list(toc_pages), "table_of_contents"
    else:
        return not_found
    pattern = _entry_pattern(words, settings[NUMBER_PATTERN_KEY])
    numbers: List[str] = []
    entry_pages: List[int] = []
    for page in pages:
        for match in pattern.finditer(texts[page - 1]):
            numbers.append(match.group(1))
            entry_pages.append(page)
    seen: Dict[str, int] = {}
    for number in numbers:
        seen[number] = seen.get(number, 0) + 1
    duplicates = [f"{label} {number}" for number in dict.fromkeys(numbers) if seen[number] > 1]
    return {"count": len(numbers), "numbers": numbers, "pages": entry_pages, "duplicates": duplicates,
            "source": source}


def declared_counts(page_texts: List[str], front_roles: dict, language: str, settings: dict) -> dict:
    """
    Purpose:
        Read the declared number of figures and of tables from the list pages of a report.

    Inputs:
        page_texts (List[str]): the text layer of each page, in order.
        front_roles (dict): the result of front_pages.find_front_roles for the report.
        language (str): "fr" or "en", the report language.
        settings (dict): the result of load_entry_settings.

    Outputs:
        dict: declared_figures and declared_tables (int, 0, or None when the list is not found),
            declared_figure_numbers and declared_table_numbers (printed strings, or None), declared_figure_pages and
            declared_table_pages (the page of each entry, or None), duplicate_numbers ("figure N" or "table N" listed
            once for each repeated number), declared_sources (per kind: the list role used, "table_of_contents" when the
            heading was found only on the contents pages, or None).

    Raises:
        FrontMatterEntryError: when the language is not fr or en.
    """
    if language not in LANGUAGES:
        raise FrontMatterEntryError(f"unknown report language '{language}' (expected fr or en)")
    toc_pages = list(front_roles.get("table_of_contents") or [])
    figures = _count_kind(page_texts, front_roles, "list_of_figures", settings["figure_list_markers"][language],
                          settings["figure_entry_words"][language], settings, toc_pages, "figure")
    tables = _count_kind(page_texts, front_roles, "list_of_tables", settings["table_list_markers"][language],
                         settings["table_entry_words"][language], settings, toc_pages, "table")
    return {
        "declared_figures": figures["count"],
        "declared_figure_numbers": figures["numbers"],
        "declared_figure_pages": figures["pages"],
        "declared_tables": tables["count"],
        "declared_table_numbers": tables["numbers"],
        "declared_table_pages": tables["pages"],
        "duplicate_numbers": figures["duplicates"] + tables["duplicates"],
        "declared_sources": {"figures": figures["source"], "tables": tables["source"]},
    }
