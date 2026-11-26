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
MAX_GAP_CONFIG_KEY = "checks.max_gap_numbers"
MAX_GAP_SETTING_KEY = "max_gap_numbers"
MAX_NUMBER_CONFIG_KEY = "checks.max_number"
MAX_NUMBER_SETTING_KEY = "max_number"
CHECK_IDS = ("figures_cited", "tables_cited", "figure_order", "table_order", "equation_order")
# N5: a row added by the assemble step, not by run_checks; its id is named here so the annex can label it.
CITATION_CHECK_ID = "citation_placement"
UNTITLED_CHECK_ID = "untitled_elements"  # owner N2: elements with no title, a finding never a count
FIGURE_COUNT_CHECK_ID = "figure_counts"
TABLE_COUNT_CHECK_ID = "table_counts"
COUNT_CHECK_IDS = (FIGURE_COUNT_CHECK_ID, TABLE_COUNT_CHECK_ID)
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


def _check_positive_int(value: Any, key: str, source: str) -> int:
    """
    Purpose: Check that a configured limit is a whole number above zero.
    Inputs:
        value: Any - the value read from the settings or the configuration.
        key: str - the configuration key, named in the error.
        source: str - where the value came from, named in the error.
    Outputs:
        int - the limit.
    Raises:
        CrossrefConfigError: If the value is not an integer above zero (a boolean is not accepted).
    """
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise CrossrefConfigError(f"'{key}' must be a whole number above 0 ({source})")
    return value


def _config_value(raw: Any, key: str, config_path: Path) -> Any:
    """
    Purpose: Read the value of one configuration key, refusing when the key is absent.
    Inputs:
        raw: Any - the parsed configuration file.
        key: str - the configuration key.
        config_path: Path - the file, named in the error.
    Outputs:
        Any - the value of the key.
    Raises:
        CrossrefConfigError: If the key is absent or has no value; the message names the key and the file.
    """
    entry = raw.get(key) if isinstance(raw, dict) else None
    if not isinstance(entry, dict) or "value" not in entry:
        raise CrossrefConfigError(f"missing key '{key}' in {config_path}")
    return entry["value"]


def load_settings(path: Optional[Path] = None) -> Dict[str, Any]:
    """
    Purpose: Read the cross-reference settings from the configuration: the right-zone ratio, the longest
        gap of numbers listed and the largest number read.
    Inputs:
        path: Optional[Path] - the configuration file; None means the work-ugs-audit assets file.
    Outputs:
        Dict[str, Any] - {"right_zone_ratio", "max_gap_numbers", "max_number"} to pass to equation_numbers and
            run_checks.
    Raises:
        CrossrefConfigError: If the file is missing, is not JSON, or lacks a key or holds a bad value;
            the message names the key and the file.
    """
    config_path = Path(path) if path is not None else DEFAULT_CONFIG_PATH
    if not config_path.exists():
        raise CrossrefConfigError(f"missing configuration file: {config_path}")
    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CrossrefConfigError(f"configuration file {config_path} is not readable JSON: {exc}") from exc
    source = str(config_path)
    return {
        ZONE_SETTING_KEY: _check_ratio(_config_value(raw, ZONE_CONFIG_KEY, config_path), source),
        MAX_GAP_SETTING_KEY: _check_positive_int(
            _config_value(raw, MAX_GAP_CONFIG_KEY, config_path), MAX_GAP_CONFIG_KEY, source),
        MAX_NUMBER_SETTING_KEY: _check_positive_int(
            _config_value(raw, MAX_NUMBER_CONFIG_KEY, config_path), MAX_NUMBER_CONFIG_KEY, source),
    }


def _setting(settings: Dict[str, Any], setting_key: str, config_key: str) -> Any:
    """
    Purpose: Read one setting given to a check, refusing when it is absent.
    Inputs:
        settings: Dict[str, Any] - the settings dict given to the check.
        setting_key: str - the name of the setting in the dict.
        config_key: str - the configuration key the setting comes from, named in the error.
    Outputs:
        Any - the raw value of the setting.
    Raises:
        CrossrefConfigError: If the setting is absent; the message names the configuration key.
    """
    if not isinstance(settings, dict) or setting_key not in settings:
        raise CrossrefConfigError(
            f"settings lack '{setting_key}' (configuration key {config_key}, "
            f"read by load_settings from {DEFAULT_CONFIG_PATH})"
        )
    return settings[setting_key]


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
    return _check_ratio(_setting(settings, ZONE_SETTING_KEY, ZONE_CONFIG_KEY), "settings")


def _max_number(settings: Dict[str, Any]) -> int:
    """
    Purpose: Read the largest number a title or a citation may carry, from the settings given to a check.
    Inputs:
        settings: Dict[str, Any] - the settings dict, expected to hold max_number.
    Outputs:
        int - the ceiling, a whole number above zero.
    Raises:
        CrossrefConfigError: If the key is absent or the value is not a whole number above zero.
    """
    return _check_positive_int(_setting(settings, MAX_NUMBER_SETTING_KEY, MAX_NUMBER_CONFIG_KEY),
                               MAX_NUMBER_CONFIG_KEY, "settings")


def _max_gap(settings: Dict[str, Any]) -> int:
    """
    Purpose: Read how many numbers of one gap are listed, from the settings given to a check.
    Inputs:
        settings: Dict[str, Any] - the settings dict, expected to hold max_gap_numbers.
    Outputs:
        int - the number of gap numbers listed, a whole number above zero.
    Raises:
        CrossrefConfigError: If the key is absent or the value is not a whole number above zero.
    """
    return _check_positive_int(_setting(settings, MAX_GAP_SETTING_KEY, MAX_GAP_CONFIG_KEY),
                               MAX_GAP_CONFIG_KEY, "settings")


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


def _part_value(part: str, max_number: Optional[int]) -> Optional[int]:
    """
    Purpose: Turn one group of digits into an integer, refusing it when it exceeds the ceiling. The length is
        compared before any conversion, so a digit string too long to convert is refused, not raised.
    Inputs:
        part: str - one group of digits, such as "12" or "0007".
        max_number: Optional[int] - the ceiling, or None for no ceiling.
    Outputs:
        Optional[int] - the value, or None when it is above the ceiling.
    Raises:
        None.
    """
    significant = part.lstrip("0") or "0"
    if max_number is not None and len(significant) > len(str(max_number)):
        return None
    value = int(significant)
    if max_number is not None and value > max_number:
        return None
    return value


def parse_number(text: str, max_number: Optional[int] = None) -> Optional[Number]:
    """
    Purpose: Turn a number written with dots into a tuple, so that chapter numbers compare correctly. A number
        with any group above the ceiling is refused, so that a cited or titled number of a document cannot make
        the checks build a list of unbounded size (proposal 2026-11-17).
    Details: The callers of run_checks always pass checks.max_number. None applies the number syntax alone and is
        meant for a caller that has no settings of its own.
    Inputs:
        text: str - a number such as "2.3" or "3".
        max_number: Optional[int] - the largest group allowed, or None for no ceiling.
    Outputs:
        Optional[Tuple[int, ...]] - (2, 3) or (3,); None when a group is above the ceiling.
    Raises:
        ValueError: If the text is not a number made of digit groups separated by dots.
    """
    match = NUMBER_RE.match(text)
    if not match:
        raise ValueError(f"not a number: {text!r}")
    values = []
    for part in match.group(1).split("."):
        value = _part_value(part, max_number)
        if value is None:
            return None
        values.append(value)
    return tuple(values)


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


def cited_numbers(pages: List[str], prefixes: List[str], max_number: Optional[int] = None) -> Set[Number]:
    """
    Purpose: Collect the element numbers the text cites, ignoring the title line of each element.
    Inputs:
        pages: List[str] - the text of each page that is searched (excluded pages already removed).
        prefixes: List[str] - the marker words of the element type (for example Figure, Fig.).
        max_number: Optional[int] - the ceiling of parse_number; a citation above it is not counted.
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
                number = parse_number(match.group(1), max_number)
                if number is not None:
                    found.add(number)
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


def _title_numbers(elements: List[Dict[str, Any]], element_type: str, prefixes: List[str],
                   max_number: Optional[int] = None) -> List[Number]:
    """
    Purpose: Read the numbers of the titles of one element type, in document order.
    Inputs:
        elements: List[Dict[str, Any]] - element records.
        element_type: str - "figure" or "table".
        prefixes: List[str] - the marker words of that type.
        max_number: Optional[int] - the ceiling of parse_number; a title above it contributes no number.
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
            number = parse_number(match.group(1), max_number)
            if number is not None:
                numbers.append(number)
    return numbers


def element_numbers(elements: List[Dict[str, Any]], element_type: str,
                    max_number: Optional[int] = None) -> List[Number]:
    """
    Purpose: Read the figure or table numbers from the titles of the elements, in document order.
        The marker words come from figure-review's element_markers.json.
    Inputs:
        elements: List[Dict[str, Any]] - element records as figure-review writes them.
        element_type: str - "figure" or "table".
        max_number: Optional[int] - the ceiling of parse_number, None for no ceiling.
    Outputs:
        List[Tuple[int, ...]] - the numbers, for example (2, 1) for "Figure 2.1".
    Raises:
        ValueError: If element_type is neither figure nor table.
        element_labels.MarkerError: If the markers file is missing or malformed.
        CrossrefConfigError: If the marker list of the type is missing.
    """
    markers = element_labels.load_markers(DEFAULT_MARKERS_PATH)
    prefixes = _marker_list(markers, element_type)
    return _title_numbers(elements, element_type, prefixes, max_number)


def _sequence_detail(numbers: List[Number], max_gap: int) -> Tuple[str, Dict[str, Any]]:
    """
    Purpose: Judge that numbers increase through the document and list the ones that do not. A gap of skipped
        numbers lists at most max_gap of them, the first ones; the count of the rest is kept in skipped_omitted.
        A gap is never expanded in full, so a document citing a very large number cannot make a long list.
    Inputs:
        numbers: List[Tuple[int, ...]] - numbers in document order.
        max_gap: int - how many numbers of one gap are listed (checks.max_gap_numbers).
    Outputs:
        Tuple[str, Dict[str, Any]] - the status (ok, not_ok or not_applicable) and the detail with the keys
            out_of_order, repeated and skipped, each a list of numbers, and skipped_omitted (an integer) only when
            some gap was cut.
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
    omitted = 0
    for before, after in zip(unique, unique[1:]):
        same_chapter = len(before) == len(after) and before[:-1] == after[:-1]
        if same_chapter and after[-1] - before[-1] > 1:
            gap_length = after[-1] - before[-1] - 1
            listed = min(gap_length, max_gap)
            skipped.extend(before[:-1] + (before[-1] + offset,) for offset in range(1, listed + 1))
            omitted += gap_length - listed
    detail: Dict[str, Any] = {"out_of_order": out_of_order, "repeated": repeated, "skipped": skipped}
    if omitted:
        detail["skipped_omitted"] = omitted
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
    ceiling = _max_number(settings)
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
                    number = parse_number(match.group(1), ceiling)
                    if number is not None:
                        numbers.append(number)
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
            detail holds lists of numbers only, and skipped_omitted (an integer) when a gap was cut.
    Raises:
        CrossrefConfigError: If a marker list, the ratio or a limit (max_number, max_gap_numbers) is missing.
        FileNotFoundError: If the PDF does not exist.
    """
    ceiling = _max_number(settings)
    max_gap = _max_gap(settings)
    skipped = set(skip_pages)
    kept = [text for index, text in enumerate(pages) if index + 1 not in skipped]
    prepared = _strip_titles(kept, elements)
    figure_prefixes = _marker_list(markers, ELEMENT_FIGURE)
    table_prefixes = _marker_list(markers, ELEMENT_TABLE)
    figure_nums = _title_numbers(elements, ELEMENT_FIGURE, figure_prefixes, ceiling)
    table_nums = _title_numbers(elements, ELEMENT_TABLE, table_prefixes, ceiling)
    figures_status, figures_detail = _cited_check(
        figure_nums, cited_numbers(prepared, figure_prefixes, ceiling))
    tables_status, tables_detail = _cited_check(
        table_nums, cited_numbers(prepared, table_prefixes, ceiling))
    fig_order_status, fig_order_detail = _sequence_detail(figure_nums, max_gap)
    tab_order_status, tab_order_detail = _sequence_detail(table_nums, max_gap)
    eq_status, eq_detail = _sequence_detail(equation_numbers(pdf, skipped, settings), max_gap)
    results = [
        ("figures_cited", figures_status, figures_detail),
        ("tables_cited", tables_status, tables_detail),
        ("figure_order", fig_order_status, fig_order_detail),
        ("table_order", tab_order_status, tab_order_detail),
        ("equation_order", eq_status, eq_detail),
    ]
    return [{"id": check_id, "status": status, "detail": detail} for check_id, status, detail in results]


# N5: a numeric citation written after the sentence's period. The abbreviations are data (citation_rules.json, R6).
CITATION_RULES_PATH = SCRIPTS_DIR.parent / "assets" / "citation_rules.json"
MISPLACED_CITATION_RE = re.compile(
    # F4: the word before the period is bounded (40 characters, no space, no period, no bracket) so a long run of
    # letters cannot make the search quadratic. F6: the gap may be a line break as well as a space.
    r"(?P<word>[^\s.\[]{0,40}[^\W\d_])\.(?P<gap>\s?)\[(?P<body>\s*\d+(?:\s*[,\u2013\u2014\-]\s*\d+)*\s*)\]")


def load_citation_rules(language: str, path: Optional[Path] = None) -> List[str]:
    """
    Purpose: Read the abbreviations that end in a period and may stand before a citation without being a finding (N5).
    Inputs:
        language: str - the report language, a key of the file (fr, en).
        path: Optional[Path] - the rules file; None means assets/citation_rules.json.
    Outputs:
        List[str] - the abbreviations of the language, each with its period (for example "et al.").
    Raises:
        CrossrefConfigError: the file is unreadable, the language has no entry, or its value is not a list of strings.
    """
    rules_path = Path(path) if path is not None else CITATION_RULES_PATH
    try:
        raw = json.loads(rules_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise CrossrefConfigError(f"cannot read {rules_path.name}: {exc}") from None
    entry = raw.get(language) if isinstance(raw, dict) else None
    value = entry.get("value") if isinstance(entry, dict) else None
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise CrossrefConfigError(f"language '{language}' has no list of abbreviations in {rules_path.name}")
    return value


def misplaced_citations(pages: List[str], abbreviations: List[str]) -> List[Dict[str, Any]]:
    """
    Purpose: Find each numeric citation written after the period of its sentence (". [5]") on the given pages (N5).
    Details: The word before the period must end with a letter, so a decimal (3.5 [2]) is not a finding. A word
        that is one of the abbreviations (et al., etc.) is not a finding either. Spaces around the bracket may be
        absent; a list or a range is a citation too. The quote is the text as it stands in the page.
    Inputs:
        pages: List[str] - the body page texts, index 0 for page 1 (references must be removed by the caller).
        abbreviations: List[str] - the abbreviations ending in a period, from load_citation_rules.
    Outputs:
        List[Dict[str, Any]] - one {"page", "quote"} per occurrence, in page order.
    Raises:
        None.
    """
    forms = {item.casefold() for item in abbreviations}
    found: List[Dict[str, Any]] = []
    for number, text in enumerate(pages, start=1):
        for match in MISPLACED_CITATION_RE.finditer(text):
            if (match.group("word") + ".").casefold() in forms:
                continue
            found.append({"page": number, "quote": match.group(0)})
    return found


APPENDIX_CHECK_ID = "appendices"
APPENDIX_NOT_APPLICABLE = "not_applicable"
APPENDIX_TITLE_END = r"[ \t]*(?:[:\-–.|*]|$|\n)"


def _appendix_pattern(settings: Dict[str, Any], heading: bool) -> "re.Pattern":
    """
    --------------------------------------------------------------------------
    Purpose:
        Build the pattern of an appendix mention: an appendix word (group word), then its id (group id).

    Inputs:
        settings (dict): markers (the appendix words of both languages), plural (the plural words) and id_pattern
            (the id, read from front_matter.json).
        heading (bool): True for a heading, which must be followed by a title mark (':', '-', '.', a bold mark or the
            end of the line), so that a mention in a sentence is not one; False for a contents entry.

    Outputs:
        re.Pattern: case-insensitive on the word, case-sensitive on the id.

    Raises:
        re.error: when id_pattern is not a valid regular expression.
    --------------------------------------------------------------------------
    """
    words = "|".join(re.escape(word) for word in sorted(settings["markers"], key=len, reverse=True))
    base = r"(?<![\w'’])(?i:(?P<word>" + words + r"))\s+(?P<id>" + settings["id_pattern"] + r")(?![A-Za-z0-9])"
    if heading:
        base += "(?=" + APPENDIX_TITLE_END + ")"
    return re.compile(base, re.MULTILINE)


def _is_mention(text: str, match: "re.Match", settings: Dict[str, Any], heading: bool) -> bool:
    """
    --------------------------------------------------------------------------
    Purpose:
        Tell whether one match is an appendix id: a plural word takes no number (a page number), and a heading is not
        preceded by a lower-case word (in a sentence such as "voir l'annexe A").

    Inputs:
        text (str): the page text the match was found in.
        match (re.Match): the match, with groups word and id.
        settings (dict): the appendix settings (plural).

    Outputs:
        bool: True when the match counts.

    Raises:
        None.
    --------------------------------------------------------------------------
    """
    word, name = match.group("word"), match.group("id")
    plural = {p.lower() for p in settings["plural"]}
    if word.lower() in plural and name.isdigit():
        return False
    return not heading or _starts_a_heading(text, match.start())


def _starts_a_heading(text: str, start: int) -> bool:
    """
    --------------------------------------------------------------------------
    Purpose:
        Tell whether a match at a given position opens a heading: the same line holds nothing before it but markup,
        spaces and a number (a numbered heading). A word, or an apostrophe after a word, before the match means the
        match is in a sentence ('Voir Annexe A.', "l'annexe A").

    Inputs:
        text (str): the page text.
        start (int): the position of the appendix word in text.

    Outputs:
        bool: True when the match opens a heading.

    Raises:
        None.
    --------------------------------------------------------------------------
    """
    line = text[max(0, start - 200):start].rsplit("\n", 1)[-1]
    line = re.sub(r"[#*_|\s]+$", "", line)
    if re.search(r"\d{1,2}[.)]?$", line):
        # A number before the mention numbers a heading ('11. ANNEXE A'), even after a word of the previous sentence.
        return True
    return not line or not (line[-1].isalpha() or line[-1] in "'’")


def appendix_check(pages: List[str], toc_pages: Optional[List[int]], end_start_page: Optional[int],
                   settings: Dict[str, Any]) -> Dict[str, Any]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Check that every appendix listed in the table of contents is found after the references, and that every
        appendix found there is listed (plan 15, N4; review round 1 I3).

    Details:
        The listed appendices are the mentions on the contents pages. The present appendices are the headings on the
        pages from end_start_page on. A heading is a mention followed by a title mark and not preceded by a lower-case
        word, so it is found inside a joined text layer too. A plural word takes no number, so 'Annexes 45' is a page
        number. The status is not_applicable when there is no contents page or no reference heading (the reason says
        which), or when neither side lists any appendix. Ids are compared as printed.

    Inputs:
        pages (List[str]): the text of each page, index 0 for page 1.
        toc_pages (List[int] or None): the 1-based contents pages from the front roles; None when none was found.
        end_start_page (int or None): the 1-based page of the reference heading, searched from the body start.
        settings (dict): markers, plural and id_pattern (front_matter.load_appendix_settings).

    Outputs:
        dict: status (ok, not_ok or not_applicable), reason (None or the text naming why), listed, present,
            listed_missing and unlisted_present (lists of ids in order of appearance).

    Raises:
        re.error: when the id pattern is not a valid regular expression.
    --------------------------------------------------------------------------
    """
    empty = {"listed": [], "present": [], "listed_missing": [], "unlisted_present": []}
    if not toc_pages:
        return {"status": APPENDIX_NOT_APPLICABLE, "reason": "no contents page found", **empty}
    if end_start_page is None:
        return {"status": APPENDIX_NOT_APPLICABLE, "reason": "no reference heading found", **empty}
    listed = _unique_ids(pages, toc_pages, _appendix_pattern(settings, heading=False), settings, heading=False)
    present = _unique_ids(pages, range(end_start_page, len(pages) + 1), _appendix_pattern(settings, heading=True),
                          settings, heading=True)
    if not listed and not present:
        return {"status": APPENDIX_NOT_APPLICABLE, "reason": None, **empty}
    listed_missing = [name for name in listed if name not in present]
    unlisted_present = [name for name in present if name not in listed]
    status = "ok" if not listed_missing and not unlisted_present else "not_ok"
    return {"status": status, "reason": None, "listed": listed, "present": present,
            "listed_missing": listed_missing, "unlisted_present": unlisted_present}


def _unique_ids(pages: List[str], numbers: Iterable[int], pattern: "re.Pattern", settings: Dict[str, Any],
                heading: bool) -> List[str]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Collect the appendix ids matched on the given 1-based pages, once each, in order of appearance.

    Inputs:
        pages (List[str]): the text of each page.
        numbers (Iterable[int]): the 1-based pages to search.
        pattern (re.Pattern): an appendix pattern with groups word and id.
        settings (dict): the appendix settings, read by _is_mention.
        heading (bool): True for headings (the lower-case rule applies), False for contents entries.

    Outputs:
        List[str]: the distinct ids that count as mentions.

    Raises:
        None.
    --------------------------------------------------------------------------
    """
    found: List[str] = []
    for number in numbers:
        if not 1 <= number <= len(pages):
            continue
        text = pages[number - 1]
        for match in pattern.finditer(text):
            if _is_mention(text, match, settings, heading) and match.group("id") not in found:
                found.append(match.group("id"))
    return found
