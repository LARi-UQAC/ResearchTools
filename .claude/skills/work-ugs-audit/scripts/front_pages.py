"""
front_pages - which pages of a student report are its front matter (Issue 126, plan 10, requirement F1).

Stage: preparation of the work folder. find_front_roles takes the text of every page and returns the 1-based pages
of the cover, the version and signature page, the table of contents, the list of figures, the list of tables and
the executive summary, plus the first body page. The marker words and thresholds come from
assets/front_matter.json (R0, R4, R6); the cover, signature and version rules are page_roles' own. No PDF is
opened here: the caller passes the page texts.
"""

import json
import re
from pathlib import Path
from typing import Dict, List, Optional

import page_roles

ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets"
DATA_FILE = ASSETS_DIR / "front_matter.json"
PAGE_ROLES_FILE = ASSETS_DIR / "page_roles.json"
LANGUAGES = ("fr", "en")
MARKER_KEYS = ("table_of_contents_markers", "figure_list_markers", "table_list_markers", "executive_summary_markers")
NUMERIC_KEYS = ("heading_max_chars", "max_list_words", "min_entry_lines")
ENTRY_LINE_PATTERN = re.compile(r"\d+\s*$")
DOT_LEADER_PATTERN = re.compile(r"\.{3,}\s*\d{1,4}\b")
HEADING_PREFIX_PATTERN = re.compile(r"^[\W\d_]+")
SPACE_PATTERN = re.compile(r"\s+")
WORD_PATTERN = re.compile(r"\w+")


class FrontMatterConfigError(ValueError):
    """Raised when the front-matter data file lacks a key or holds a value of the wrong shape (R3)."""


def _normalize(text: str) -> str:
    """
    Purpose:
        Put a text in the form used for every marker comparison: no accents, lower case, single spaces.

    Inputs:
        text (str): any text.

    Outputs:
        str: the normalized text.

    Raises:
        None.
    """
    return page_roles._normalize(text)


def _require(data: dict, key: str, path: Path) -> object:
    """
    Purpose:
        Return a top-level key of the data file, or refuse it with the key and the file named.

    Inputs:
        data (dict): the parsed data file.
        key (str): the expected key.
        path (Path): the data file, named in the error.

    Outputs:
        object: the stored value.

    Raises:
        FrontMatterConfigError: when the key is absent.
    """
    if key not in data:
        raise FrontMatterConfigError(f"missing key '{key}' in {path}")
    return data[key]


def _markers_of(data: dict, key: str, path: Path) -> Dict[str, List[str]]:
    """
    Purpose:
        Read one marker map (a list of words per language, and a provenance) from the data file.

    Inputs:
        data (dict): the parsed data file.
        key (str): the marker map name.
        path (Path): the data file, named in the error.

    Outputs:
        dict: {"fr": [words], "en": [words]}.

    Raises:
        FrontMatterConfigError: when a language or the provenance is missing, or a list is not a list of strings.
    """
    entry = _require(data, key, path)
    if not isinstance(entry, dict):
        raise FrontMatterConfigError(f"'{key}' in {path} must map 'fr' and 'en' to lists of words")
    if not isinstance(entry.get("provenance"), str) or not entry["provenance"].strip():
        raise FrontMatterConfigError(f"'{key}' in {path} lacks its 'provenance'")
    result: Dict[str, List[str]] = {}
    for lang in LANGUAGES:
        if lang not in entry:
            raise FrontMatterConfigError(f"missing language '{lang}' in '{key}' of {path}")
        words = entry[lang]
        if not isinstance(words, list) or not all(isinstance(w, str) and w.strip() for w in words):
            raise FrontMatterConfigError(f"'{key}.{lang}' in {path} must be a list of non-empty strings")
        result[lang] = words
    return result


def _numeric(data: dict, key: str, path: Path) -> int:
    """
    Purpose:
        Read a numeric setting stored as {value, provenance} and check its shape (R4).

    Inputs:
        data (dict): the parsed data file.
        key (str): the setting name.
        path (Path): the data file, named in the error.

    Outputs:
        int: the value, a non-negative whole number.

    Raises:
        FrontMatterConfigError: when the entry, its value or its provenance is missing or invalid.
    """
    entry = _require(data, key, path)
    if not isinstance(entry, dict) or "value" not in entry or "provenance" not in entry:
        raise FrontMatterConfigError(f"'{key}' in {path} must be an object with 'value' and 'provenance'")
    value = entry["value"]
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise FrontMatterConfigError(f"'{key}.value' in {path} must be a non-negative whole number")
    return value


def load_front_matter(path: Optional[Path] = None) -> dict:
    """
    Purpose:
        Load the marker words and the numeric settings of the front-matter judgement.

    Inputs:
        path (Path or None): the JSON data file; None means assets/front_matter.json beside this module.

    Outputs:
        dict: the marker maps (each {"fr": [...], "en": [...]}) and the numeric settings (each a plain int).

    Raises:
        FrontMatterConfigError: when the file is unreadable, not JSON, or lacks or mis-shapes a key.
    """
    target = Path(path) if path is not None else DATA_FILE
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FrontMatterConfigError(f"cannot read {target}: {exc}") from exc
    if not isinstance(data, dict):
        raise FrontMatterConfigError(f"{target} must hold a JSON object")
    result: dict = {key: _markers_of(data, key, target) for key in MARKER_KEYS}
    for key in NUMERIC_KEYS:
        result[key] = _numeric(data, key, target)
    return result


def _has_heading(text: str, markers: List[str], data: dict) -> bool:
    """
    Purpose:
        Tell whether a marker word is the heading of a page: it starts within the first characters of the page text,
        after any markup or numbering, and is a whole word.

    Inputs:
        text (str): the text layer of the page.
        markers (List[str]): the marker words of the report language.
        data (dict): the result of load_front_matter.

    Outputs:
        bool: True when a marker starts within heading_max_chars characters of the normalized text.

    Raises:
        None.
    """
    norm = HEADING_PREFIX_PATTERN.sub("", _normalize(text))
    head = norm[: data["heading_max_chars"]]
    for marker in markers:
        word = _normalize(marker)
        if word and re.search(r"(?<!\w)" + re.escape(word) + r"(?!\w)", head):
            return True
    return False


def _is_continuation(text: str, data: dict) -> bool:
    """
    Purpose:
        Tell whether a page reads as the next page of a list: enough entries (a line ending with a page number, or a
        dot leader followed by a page number, the text layer being joined into one line) and not a long page.

    Inputs:
        text (str): the text layer of the page.
        data (dict): the result of load_front_matter.

    Outputs:
        bool: True when the page has at least min_entry_lines entry lines and at most max_list_words words.

    Raises:
        None.
    """
    by_line = sum(1 for line in text.splitlines() if ENTRY_LINE_PATTERN.search(line.strip()))
    by_leader = len(DOT_LEADER_PATTERN.findall(text))
    entries = max(by_line, by_leader)
    words = len(WORD_PATTERN.findall(text))
    return entries >= data["min_entry_lines"] and words <= data["max_list_words"]


def _list_pages(texts: List[str], markers: List[str], taken: set, data: dict,
                all_markers: List[str]) -> Optional[List[int]]:
    """
    Purpose:
        Find the pages of one list: each page carrying its heading, plus the pages that directly follow it and read
        as its continuation.

    Inputs:
        texts (List[str]): the text of each page, in order.
        markers (List[str]): the heading words of the list in the report language.
        taken (set): the 1-based pages already given another role; they are never reused.
        data (dict): the result of load_front_matter.
        all_markers (List[str]): the heading words of every list, so that a continuation never swallows another list.

    Outputs:
        List[int] or None: the sorted 1-based pages, or None when no heading is found.

    Raises:
        None.
    """
    found: List[int] = []
    for index, text in enumerate(texts):
        number = index + 1
        if number in taken or not _has_heading(text, markers, data):
            continue
        found.append(number)
        follow = number + 1
        while (follow <= len(texts) and follow not in taken and not _has_heading(texts[follow - 1], all_markers, data)
               and _is_continuation(texts[follow - 1], data)):
            found.append(follow)
            taken.add(follow)
            follow += 1
    if not found:
        return None
    taken.update(found)
    return sorted(found)


def find_front_roles(page_texts: List[str], language: str, data: dict, small_images: List[int]) -> dict:
    """
    Purpose:
        Give the front-matter role of every page of a report and the first body page.

    Inputs:
        page_texts (List[str]): the text layer of each page, in order (after repair).
        language (str): "fr" or "en", the report language; its marker words only are read.
        data (dict): the result of load_front_matter.
        small_images (List[int]): the small-image count of each page; a missing entry counts as 0.

    Outputs:
        dict: keys cover, version_signature, table_of_contents, list_of_figures, list_of_tables and
            executive_summary (each a sorted list of 1-based pages, or None when not found), and body_start
            (the first page after the last front-matter page, 1 when there is none).

    Raises:
        FrontMatterConfigError: when the language is not fr or en, or the page-role data file is incomplete.
    """
    if language not in LANGUAGES:
        raise FrontMatterConfigError(f"unknown report language '{language}' (expected fr or en)")
    markers = page_roles.load_markers(PAGE_ROLES_FILE)
    counts = [small_images[i] if i < len(small_images) else 0 for i in range(len(page_texts))]
    taken: set = set()
    all_markers = [word for key in MARKER_KEYS for word in data[key][language]]
    cover: List[int] = []
    signature_or_version: List[int] = []
    for index, text in enumerate(page_texts):
        role = page_roles.classify_page(text, index, counts[index], markers)
        if role == page_roles.ROLE_COVER:
            cover.append(index + 1)
            taken.add(index + 1)
        elif role in (page_roles.ROLE_SIGNATURE, page_roles.ROLE_VERSION):
            signature_or_version.append(index + 1)
            taken.add(index + 1)
    result: dict = {
        "cover": cover or None,
        "version_signature": signature_or_version or None,
    }
    result["table_of_contents"] = _list_pages(page_texts, data["table_of_contents_markers"][language], taken, data, all_markers)
    result["list_of_figures"] = _list_pages(page_texts, data["figure_list_markers"][language], taken, data, all_markers)
    result["list_of_tables"] = _list_pages(page_texts, data["table_list_markers"][language], taken, data, all_markers)
    summary = _list_pages(page_texts, data["executive_summary_markers"][language], taken, data, all_markers)
    result["executive_summary"] = summary
    last = 0
    for key in ("cover", "version_signature", "table_of_contents", "list_of_figures", "list_of_tables",
                "executive_summary"):
        if result[key]:
            last = max(last, max(result[key]))
    result["body_start"] = last + 1
    return result


