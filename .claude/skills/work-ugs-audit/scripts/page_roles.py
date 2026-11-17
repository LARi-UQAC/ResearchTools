"""
page_roles - which pages of a student report are not content to grade (Issue 122, plan 1, R7).

Stage: preparation of the work folder. The function classify_page judges one page from its
text, its index and its count of small images. The marker words, thresholds and reason codes
come from assets/page_roles.json (R0, R4, R6). No grading logic lives here: the caller writes
the result into report_meta.json.
"""

import json
import re
import unicodedata
from pathlib import Path
from typing import Dict, List, Optional

import fitz

MARKER_KEYS = ("cover_markers", "signature_markers", "version_markers")
NUMERIC_KEYS = ("max_leading_pages", "max_cover_words", "min_markers")
LANGUAGES = ("fr", "en")
ROLE_COVER = "cover"
ROLE_SIGNATURE = "signature_table"
ROLE_VERSION = "version_table"
WORD_PATTERN = re.compile(r"\w+")
SPACE_PATTERN = re.compile(r"\s+")


class PageRolesConfigError(ValueError):
    """Raised when the page-roles data file lacks a key or holds a value of the wrong shape (R3)."""


def _normalize(text: str) -> str:
    """
    Purpose:
        Put a text in the form used for every comparison: lower case, no accents, single spaces.

    Inputs:
        text (str): any text, French or English.

    Outputs:
        str: the normalized text.

    Raises:
        None.
    """
    decomposed = unicodedata.normalize("NFKD", text)
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return SPACE_PATTERN.sub(" ", stripped.lower()).strip()


def _require(data: dict, key: str, path: Path) -> object:
    """
    Purpose:
        Return one top-level key of the data file, or refuse it with the key and the file named.

    Inputs:
        data (dict): the parsed data file.
        key (str): the key expected at the top level.
        path (Path): the data file, named in the error.

    Outputs:
        object: the value stored under the key.

    Raises:
        PageRolesConfigError: when the key is absent.
    """
    if key not in data:
        raise PageRolesConfigError(f"missing key '{key}' in {path}")
    return data[key]


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
        PageRolesConfigError: when the entry, its value or its provenance is missing or invalid.
    """
    entry = _require(data, key, path)
    if not isinstance(entry, dict) or "value" not in entry or "provenance" not in entry:
        raise PageRolesConfigError(f"'{key}' in {path} must be an object with 'value' and 'provenance'")
    value = entry["value"]
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise PageRolesConfigError(f"'{key}.value' in {path} must be a non-negative whole number")
    return value


def _markers_of(data: dict, key: str, path: Path) -> Dict[str, List[str]]:
    """
    Purpose:
        Read one marker map (fr and en, each a list of words) from the data file.

    Inputs:
        data (dict): the parsed data file.
        key (str): the marker map name.
        path (Path): the data file, named in the error.

    Outputs:
        dict: {"fr": [words], "en": [words]}.

    Raises:
        PageRolesConfigError: when a language is missing or a list is not a list of strings.
    """
    entry = _require(data, key, path)
    if not isinstance(entry, dict):
        raise PageRolesConfigError(f"'{key}' in {path} must map 'fr' and 'en' to lists of words")
    result: Dict[str, List[str]] = {}
    for lang in LANGUAGES:
        if lang not in entry:
            raise PageRolesConfigError(f"missing language '{lang}' in '{key}' of {path}")
        words = entry[lang]
        if not isinstance(words, list) or not all(isinstance(w, str) for w in words):
            raise PageRolesConfigError(f"'{key}.{lang}' in {path} must be a list of strings")
        result[lang] = words
    return result


def load_markers(path: Path) -> dict:
    """
    Purpose:
        Load the marker words and the numeric settings of the page-role judgement.

    Inputs:
        path (Path): the JSON data file (assets/page_roles.json for the shipped values).

    Outputs:
        dict: keys cover_markers, signature_markers, version_markers (each {"fr": [...], "en": [...]}),
            max_leading_pages, max_cover_words, min_markers (each a plain int).

    Raises:
        PageRolesConfigError: when the file is unreadable, not JSON, or lacks or mis-shapes a key.
    """
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PageRolesConfigError(f"cannot read {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise PageRolesConfigError(f"{path} must hold a JSON object")
    result: dict = {key: _markers_of(data, key, path) for key in MARKER_KEYS}
    for key in NUMERIC_KEYS:
        result[key] = _numeric(data, key, path)
    return result


def small_image_counts(pdf: Path, max_area_ratio: float) -> List[int]:
    """
    Purpose:
        Count, for each page, the raster images whose placed area is at most a given share of the page.

    Inputs:
        pdf (Path): the PDF to read.
        max_area_ratio (float): largest image area, as a share of the page area, in ]0, 1].

    Outputs:
        List[int]: one count per page, in page order.

    Raises:
        ValueError: when max_area_ratio is outside ]0, 1].
        RuntimeError: when PyMuPDF cannot open the PDF.
    """
    if isinstance(max_area_ratio, bool) or not isinstance(max_area_ratio, (int, float)):
        raise ValueError("max_area_ratio must be a number")
    if not 0 < max_area_ratio <= 1:
        raise ValueError("max_area_ratio must be in ]0, 1]")
    counts: List[int] = []
    try:
        doc = fitz.open(str(pdf))
    except Exception as exc:  # PyMuPDF raises several types for an unreadable file
        raise RuntimeError(f"cannot open {pdf}: {exc}") from exc
    try:
        for page in doc:
            page_area = page.rect.width * page.rect.height
            small = 0
            for info in page.get_image_info():
                if fitz.Rect(info["bbox"]).get_area() <= max_area_ratio * page_area:
                    small += 1
            counts.append(small)
    finally:
        doc.close()
    return counts


def _count_hits(norm_text: str, words: List[str]) -> int:
    """
    Purpose:
        Count how many distinct marker words occur in a normalized text.

    Inputs:
        norm_text (str): a text already passed through _normalize.
        words (List[str]): marker words in any case or accent.

    Outputs:
        int: the number of distinct normalized markers found as whole words (no letter on either side,
            so "version" does not match "versions").

    Raises:
        None.
    """
    distinct = {_normalize(w) for w in words if _normalize(w)}
    return sum(1 for w in distinct if re.search(r"(?<!\w)" + re.escape(w) + r"(?!\w)", norm_text))


def _all_words(markers: dict, key: str) -> List[str]:
    """
    Purpose:
        Flatten the French and English words of one marker map.

    Inputs:
        markers (dict): the result of load_markers.
        key (str): one of MARKER_KEYS.

    Outputs:
        List[str]: every word of both languages.

    Raises:
        KeyError: when the key is absent from markers.
    """
    return [w for lang in LANGUAGES for w in markers[key][lang]]


def classify_page(text: str, index: int, small_images: int, markers: dict) -> Optional[str]:
    """
    Purpose:
        Decide whether a page is excluded from grading, and why.

    Inputs:
        text (str): the text layer of the page.
        index (int): the 0-based page index.
        small_images (int): the count of small raster images on the page.
        markers (dict): the result of load_markers.

    Outputs:
        Optional[str]: "cover", "signature_table", "version_table", or None when the page is graded.

    Raises:
        KeyError: when markers lacks one of its keys (a caller error, see load_markers).
    """
    norm = _normalize(text)
    words = len(WORD_PATTERN.findall(norm))
    min_markers = markers["min_markers"]
    short = words <= markers["max_cover_words"]
    if index < markers["max_leading_pages"] and short:
        cover_hits = _count_hits(norm, _all_words(markers, "cover_markers"))
        if cover_hits >= min_markers or (cover_hits >= 1 and small_images >= 1):
            return ROLE_COVER
    # A table is short by nature: a long body page that uses a marker word is content to grade (defect 1, Issue 122).
    if short and _count_hits(norm, _all_words(markers, "signature_markers")) >= min_markers:
        return ROLE_SIGNATURE
    if short and _count_hits(norm, _all_words(markers, "version_markers")) >= min_markers:
        return ROLE_VERSION
    return None


def excluded_pages(pages: List[str], small_images: List[int], markers: dict) -> List[dict]:
    """
    Purpose:
        List the pages excluded from grading, in page order, with their reason code.

    Inputs:
        pages (List[str]): the text layer of each page, in order.
        small_images (List[int]): the small-image count of each page; a missing entry counts as 0.
        markers (dict): the result of load_markers.

    Outputs:
        List[dict]: entries {"page": int (1-based), "reason": str}, in page order.

    Raises:
        KeyError: when markers lacks one of its keys (a caller error, see load_markers).
    """
    result: List[dict] = []
    for index, text in enumerate(pages):
        count = small_images[index] if index < len(small_images) else 0
        role = classify_page(text, index, count, markers)
        if role is not None:
            result.append({"page": index + 1, "reason": role})
    return result
