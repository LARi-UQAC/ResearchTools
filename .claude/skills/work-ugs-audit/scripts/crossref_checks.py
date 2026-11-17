"""
crossref_checks - the cross-reference checks of the last step (Issue 122, plan 8 task 1, spec R9).

Stage: last step and annex of the work-ugs-audit pipeline. Five checks, each giving ok, not_ok or
not_applicable and the NUMBERS concerned (never text of the report): every figure and every table
is cited in the text, figure and table numbers increase, and equation numbers increase. Marker
words come from figure-review's assets/element_markers.json; the right-zone ratio comes from the
configuration key checks.right_zone_ratio (R0, R3, R6). Nothing here reads a report by itself:
the caller passes the page texts, the element records and the PDF.
"""

import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

SCRIPTS_DIR = Path(__file__).resolve().parent
FIGURE_REVIEW_SCRIPTS = SCRIPTS_DIR.parent.parent / "figure-review" / "scripts"
FIGURE_REVIEW_ASSETS = SCRIPTS_DIR.parent.parent / "figure-review" / "assets"
DEFAULT_CONFIG_PATH = SCRIPTS_DIR.parent / "assets" / "ugs_config.json"
DEFAULT_MARKERS_PATH = FIGURE_REVIEW_ASSETS / "element_markers.json"
if str(FIGURE_REVIEW_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(FIGURE_REVIEW_SCRIPTS))

import fitz  # noqa: E402
import element_labels  # noqa: E402

ZONE_CONFIG_KEY = "checks.right_zone_ratio"
ZONE_SETTING_KEY = "right_zone_ratio"
CHECK_IDS = ("figures_cited", "tables_cited", "figure_order", "table_order", "equation_order")
STATUS_OK = "ok"
STATUS_NOT_OK = "not_ok"
STATUS_NOT_APPLICABLE = "not_applicable"
ELEMENT_FIGURE = "figure"
ELEMENT_TABLE = "table"
ELEMENT_MARKER_KEYS = {ELEMENT_FIGURE: "figure_prefixes", ELEMENT_TABLE: "table_prefixes"}
NUMBER_TEXT = r"\d+(?:\.\d+)*"
NUMBER_RE = re.compile(rf"^\s*({NUMBER_TEXT})\s*$")
EQUATION_RE = re.compile(rf"^\(({NUMBER_TEXT})\)$")
BODY_SENTENCE_RE = re.compile(r"[A-Za-z)\]]\.(?:\s|$)")
Number = Tuple[int, ...]


class CrossrefConfigError(ValueError):
    """Raised when a configuration value, a marker list or the ratio setting is missing or malformed (R3)."""


def _clean(text: str) -> str:
    """
    Purpose: Collapse every run of whitespace, line breaks included, into one space.
    Inputs:
        text: str - the raw text.
    Outputs:
        str - the normalised text, stripped at both ends.
    Raises:
        None.
    """
    return " ".join(text.split())


def _check_ratio(value: Any, source: str) -> float:
    """
    Purpose: Check that a right-zone ratio is a number strictly between 0 and 1.
    Inputs:
        value: Any - the value read from the settings or the configuration.
        source: str - where it came from, named in the error.
    Outputs:
        float - the ratio.
    Raises:
        CrossrefConfigError: If the value is not a number or lies outside the open interval (0, 1).
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 < value < 1:
        raise CrossrefConfigError(f"'{ZONE_CONFIG_KEY}' must be a number between 0 and 1 ({source})")
    return float(value)


def load_settings(path: Optional[Path] = None) -> Dict[str, float]:
    """
    Purpose: Read the right-zone ratio from the configuration key checks.right_zone_ratio.
    Inputs:
        path: Optional[Path] - the configuration file; None means the work-ugs-audit assets file.
    Outputs:
        Dict[str, float] - {"right_zone_ratio": ratio} to pass to equation_numbers and run_checks.
    Raises:
        CrossrefConfigError: If the file is missing, is not JSON, or lacks the key or holds a bad value;
            the message names the key and the file.
    """
    config_path = Path(path) if path is not None else DEFAULT_CONFIG_PATH
    if not config_path.exists():
        raise CrossrefConfigError(f"missing configuration file: {config_path}")
    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CrossrefConfigError(f"configuration file {config_path} is not readable JSON: {exc}") from exc
    entry = raw.get(ZONE_CONFIG_KEY) if isinstance(raw, dict) else None
    if not isinstance(entry, dict) or "value" not in entry:
        raise CrossrefConfigError(f"missing key '{ZONE_CONFIG_KEY}' in {config_path}")
    return {ZONE_SETTING_KEY: _check_ratio(entry["value"], str(config_path))}


def _zone_ratio(settings: Dict[str, Any]) -> float:
    """
    Purpose: Read the right-zone ratio from the settings given to a check, refusing when absent.
    Inputs:
        settings: Dict[str, Any] - the settings dict, expected to hold right_zone_ratio.
    Outputs:
        float - the ratio.
    Raises:
        CrossrefConfigError: If the key is absent or the value is not a ratio between 0 and 1.
    """
    if not isinstance(settings, dict) or ZONE_SETTING_KEY not in settings:
        raise CrossrefConfigError(
            f"settings lack '{ZONE_SETTING_KEY}' (configuration key {ZONE_CONFIG_KEY}, "
            f"read by load_settings from {DEFAULT_CONFIG_PATH})"
        )
    return _check_ratio(settings[ZONE_SETTING_KEY], "settings")


def _marker_list(markers: Dict[str, Any], element_type: str) -> List[str]:
    """
    Purpose: Read the marker words of one element type from the loaded markers.
    Inputs:
        markers: Dict[str, Any] - the data returned by element_labels.load_markers.
        element_type: str - "figure" or "table".
    Outputs:
        List[str] - the non-empty list of marker words.
    Raises:
        ValueError: If element_type is neither figure nor table.
        CrossrefConfigError: If the list is missing or empty; the message names the key.
    """
    if element_type not in ELEMENT_MARKER_KEYS:
        raise ValueError(f"unknown element type '{element_type}' (expected figure or table)")
    key = ELEMENT_MARKER_KEYS[element_type]
    prefixes = markers.get(key) if isinstance(markers, dict) else None
    if not isinstance(prefixes, list) or not prefixes:
        raise CrossrefConfigError(f"element markers: key '{key}' (marker words) is missing or empty")
    return [str(p) for p in prefixes]


def _alternatives(prefixes: List[str]) -> str:
    """
    Purpose: Build a regex alternation of marker words, longest first and escaped.
    Inputs:
        prefixes: List[str] - the marker words.
    Outputs:
        str - the alternation text, for example "Tableau|Table".
    Raises:
        None.
    """
    words = sorted({p.strip() for p in prefixes if p.strip()}, key=len, reverse=True)
    return "|".join(re.escape(word) for word in words)


def parse_number(text: str) -> Number:
    """
    Purpose: Turn a number written with dots into a tuple, so that chapter numbers compare correctly.
    Inputs:
        text: str - a number such as "2.3" or "3".
    Outputs:
        Tuple[int, ...] - (2, 3) or (3,).
    Raises:
        ValueError: If the text is not a number made of digit groups separated by dots.
    """
    match = NUMBER_RE.match(text)
    if not match:
        raise ValueError(f"not a number: {text!r}")
    return tuple(int(part) for part in match.group(1).split("."))


def _title_pattern(prefixes: List[str]) -> "re.Pattern[str]":
    """
    Purpose: Compile the pattern that opens a title: a marker word, then a number.
    Inputs:
        prefixes: List[str] - the marker words.
    Outputs:
        re.Pattern - matches at the start of a cleaned title, group 1 is the number.
    Raises:
        None.
    """
    return re.compile(rf"^(?:{_alternatives(prefixes)})s?\.?\s*({NUMBER_TEXT})", re.IGNORECASE)


def _citation_pattern(prefixes: List[str]) -> "re.Pattern[str]":
    """
    Purpose: Compile the pattern of a citation: a marker word anywhere, then a number.
    Inputs:
        prefixes: List[str] - the marker words.
    Outputs:
        re.Pattern - group 1 is the number.
    Raises:
        None.
    """
    return re.compile(rf"\b(?:{_alternatives(prefixes)})s?\.?\s*({NUMBER_TEXT})", re.IGNORECASE)


def _is_title_line(line: str, prefixes: List[str]) -> bool:
    """
    Purpose: Tell whether a text line is an element title rather than a sentence of the body.
    Inputs:
        line: str - one line of a page text.
        prefixes: List[str] - the marker words.
    Outputs:
        bool - True when the line opens with a marker word and a number and carries no sentence end
            after that number (a title is short and unpunctuated, a sentence says what the figure shows).
    Raises:
        None.
    """
    cleaned = _clean(line)
    match = _title_pattern(prefixes).match(cleaned)
    if not match:
        return False
    return BODY_SENTENCE_RE.search(cleaned[match.end():]) is None


def cited_numbers(pages: List[str], prefixes: List[str]) -> Set[Number]:
    """
    Purpose: Collect the element numbers the text cites, ignoring the title line of each element.
    Inputs:
        pages: List[str] - the text of each page that is searched (excluded pages already removed).
        prefixes: List[str] - the marker words of the element type (for example Figure, Fig.).
    Outputs:
        Set[Tuple[int, ...]] - the cited numbers. A number that appears only in a title line is absent.
    Raises:
        None.
    """
    pattern = _citation_pattern(prefixes)
    found: Set[Number] = set()
    for page in pages:
        for line in page.splitlines():
            if _is_title_line(line, prefixes):
                continue
            for match in pattern.finditer(line):
                found.add(parse_number(match.group(1)))
    return found


def _ordered(elements: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Purpose: Put element records in document order: by page, then top, then left edge.
    Inputs:
        elements: List[Dict[str, Any]] - element records as figure-review writes them.
    Outputs:
        List[Dict[str, Any]] - the same records, sorted (stable for records at the same place).
    Raises:
        None.
    """
    def key(element: Dict[str, Any]) -> Tuple[int, float, float]:
        rect = element.get("rect") or [0.0, 0.0, 0.0, 0.0]
        return (int(element.get("page", 0)), float(rect[1]), float(rect[0]))

    return sorted(elements, key=key)


def _title_numbers(elements: List[Dict[str, Any]], element_type: str, prefixes: List[str]) -> List[Number]:
    """
    Purpose: Read the numbers of the titles of one element type, in document order.
    Inputs:
        elements: List[Dict[str, Any]] - element records.
        element_type: str - "figure" or "table".
        prefixes: List[str] - the marker words of that type.
    Outputs:
        List[Tuple[int, ...]] - one number per titled element whose title opens with a marker and a number.
    Raises:
        None.
    """
    pattern = _title_pattern(prefixes)
    numbers: List[Number] = []
    for element in _ordered(elements):
        if element.get("element_type") != element_type:
            continue
        title = element.get("title")
        if not isinstance(title, dict) or not isinstance(title.get("text"), str):
            continue
        match = pattern.match(_clean(title["text"]))
        if match:
            numbers.append(parse_number(match.group(1)))
    return numbers


def element_numbers(elements: List[Dict[str, Any]], element_type: str) -> List[Number]:
    """
    Purpose: Read the figure or table numbers from the titles of the elements, in document order.
        The marker words come from figure-review's element_markers.json.
    Inputs:
        elements: List[Dict[str, Any]] - element records as figure-review writes them.
        element_type: str - "figure" or "table".
    Outputs:
        List[Tuple[int, ...]] - the numbers, for example (2, 1) for "Figure 2.1".
    Raises:
        ValueError: If element_type is neither figure nor table.
        element_labels.MarkerError: If the markers file is missing or malformed.
        CrossrefConfigError: If the marker list of the type is missing.
    """
    markers = element_labels.load_markers(DEFAULT_MARKERS_PATH)
    prefixes = _marker_list(markers, element_type)
    return _title_numbers(elements, element_type, prefixes)


def _sequence_detail(numbers: List[Number]) -> Tuple[str, Dict[str, List[Number]]]:
    """
    Purpose: Judge that numbers increase through the document and list the ones that do not.
    Inputs:
        numbers: List[Tuple[int, ...]] - numbers in document order.
    Outputs:
        Tuple[str, Dict[str, List[Tuple[int, ...]]]] - the status (ok, not_ok or not_applicable) and the
            detail with the keys out_of_order, repeated and skipped, each a list of numbers.
    Raises:
        None.
    """
    if not numbers:
        return STATUS_NOT_APPLICABLE, {"out_of_order": [], "repeated": [], "skipped": []}
    counts = Counter(numbers)
    repeated = sorted(n for n, count in counts.items() if count > 1)
    out_of_order: List[Number] = []
    highest: Optional[Number] = None
    for number in numbers:
        if highest is not None and number <= highest:
            out_of_order.append(number)
        else:
            highest = number
    out_of_order = list(dict.fromkeys(out_of_order))
    unique = sorted(counts)
    skipped: List[Number] = []
    for before, after in zip(unique, unique[1:]):
        same_chapter = len(before) == len(after) and before[:-1] == after[:-1]
        if same_chapter and after[-1] - before[-1] > 1:
            skipped.extend(before[:-1] + (k,) for k in range(before[-1] + 1, after[-1]))
    detail = {"out_of_order": out_of_order, "repeated": repeated, "skipped": skipped}
    status = STATUS_OK if not (out_of_order or repeated or skipped) else STATUS_NOT_OK
    return status, detail


def _cited_check(numbers: List[Number], cited: Set[Number]) -> Tuple[str, Dict[str, List[Number]]]:
    """
    Purpose: Judge that every titled element number is cited in the text.
    Inputs:
        numbers: List[Tuple[int, ...]] - the numbers of the titles, in document order.
        cited: Set[Tuple[int, ...]] - the numbers the text cites.
    Outputs:
        Tuple[str, Dict[str, List[Tuple[int, ...]]]] - the status and the detail key missing.
    Raises:
        None.
    """
    if not numbers:
        return STATUS_NOT_APPLICABLE, {"missing": []}
    missing = list(dict.fromkeys(n for n in numbers if n not in cited))
    return (STATUS_OK if not missing else STATUS_NOT_OK), {"missing": missing}


def _strip_titles(pages: List[str], elements: List[Dict[str, Any]]) -> List[str]:
    """
    Purpose: Remove from the page texts the lines that are exactly the title of an element.
    Inputs:
        pages: List[str] - the searched page texts.
        elements: List[Dict[str, Any]] - the element records, whose titles are removed.
    Outputs:
        List[str] - the page texts without the title lines.
    Raises:
        None.
    """
    titles = set()
    for element in elements:
        title = element.get("title")
        if isinstance(title, dict) and isinstance(title.get("text"), str):
            titles.add(_clean(title["text"]))
    titles.discard("")
    return ["\n".join(line for line in page.splitlines() if _clean(line) not in titles) for page in pages]


def equation_numbers(pdf: Path, skip_pages: Iterable[int], settings: Dict[str, Any]) -> List[Number]:
    """
    Purpose: Find the equation numbers, words shaped (n) or (n.m) whose left edge lies beyond the
        right-zone ratio of the page width, in document order. Excluded pages are not searched.
    Inputs:
        pdf: Path - the compiled PDF of the report.
        skip_pages: Iterable[int] - 1-based page numbers that are not searched.
        settings: Dict[str, Any] - holds right_zone_ratio (see load_settings).
    Outputs:
        List[Tuple[int, ...]] - the equation numbers, for example (2, 1) for "(2.1)".
    Raises:
        CrossrefConfigError: If right_zone_ratio is absent or not a ratio between 0 and 1.
        FileNotFoundError: If the PDF does not exist.
    """
    ratio = _zone_ratio(settings)
    pdf_path = Path(pdf)
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")
    skipped = set(skip_pages)
    numbers: List[Number] = []
    doc = fitz.open(str(pdf_path))
    try:
        for index in range(doc.page_count):
            if index + 1 in skipped:
                continue
            page = doc[index]
            limit = ratio * page.rect.width
            words = sorted(page.get_text("words"), key=lambda w: (w[1], w[0]))
            for word in words:
                match = EQUATION_RE.match(word[4])
                if match and word[0] > limit:
                    numbers.append(parse_number(match.group(1)))
    finally:
        doc.close()
    return numbers


def run_checks(pdf: Path, pages: List[str], elements: List[Dict[str, Any]], markers: Dict[str, Any],
               settings: Dict[str, Any], skip_pages: Iterable[int]) -> List[Dict[str, Any]]:
    """
    Purpose: Run the five cross-reference checks of the last step (spec R9).
    Inputs:
        pdf: Path - the compiled PDF of the report, read for the equation numbers.
        pages: List[str] - the text of each page, index 0 for page 1.
        elements: List[Dict[str, Any]] - the element records of the report.
        markers: Dict[str, Any] - the data returned by element_labels.load_markers.
        settings: Dict[str, Any] - holds right_zone_ratio (see load_settings).
        skip_pages: Iterable[int] - 1-based pages excluded from evaluation; not searched.
    Outputs:
        List[Dict[str, Any]] - five entries {"id", "status", "detail"} in the order of CHECK_IDS; the
            detail holds lists of numbers only.
    Raises:
        CrossrefConfigError: If a marker list or the ratio is missing.
        FileNotFoundError: If the PDF does not exist.
    """
    skipped = set(skip_pages)
    kept = [text for index, text in enumerate(pages) if index + 1 not in skipped]
    prepared = _strip_titles(kept, elements)
    figure_prefixes = _marker_list(markers, ELEMENT_FIGURE)
    table_prefixes = _marker_list(markers, ELEMENT_TABLE)
    figure_nums = _title_numbers(elements, ELEMENT_FIGURE, figure_prefixes)
    table_nums = _title_numbers(elements, ELEMENT_TABLE, table_prefixes)
    figures_status, figures_detail = _cited_check(figure_nums, cited_numbers(prepared, figure_prefixes))
    tables_status, tables_detail = _cited_check(table_nums, cited_numbers(prepared, table_prefixes))
    fig_order_status, fig_order_detail = _sequence_detail(figure_nums)
    tab_order_status, tab_order_detail = _sequence_detail(table_nums)
    eq_status, eq_detail = _sequence_detail(equation_numbers(pdf, skipped, settings))
    results = [
        ("figures_cited", figures_status, figures_detail),
        ("tables_cited", tables_status, tables_detail),
        ("figure_order", fig_order_status, fig_order_detail),
        ("table_order", tab_order_status, tab_order_detail),
        ("equation_order", eq_status, eq_detail),
    ]
    return [{"id": check_id, "status": status, "detail": detail} for check_id, status, detail in results]
