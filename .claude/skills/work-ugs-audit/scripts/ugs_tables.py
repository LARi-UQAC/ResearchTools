"""
ugs_tables.py - the table text and the element records of one report (Issue #122, plan 4).

The preparation of a report writes `elements.json`, one record per figure, table or logo found on the pages.
This module reads those records, gives the table Markdown of a page to the page text the models read when the
text layer does not already carry it, and hands the figure records to the figure step, which then judges
figures only. Nothing from a report leaves this module except the page text it returns to its caller.
"""
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

TABLE_TYPE = "table"
FIGURE_TYPE = "figure"
TABLE_HEADING = "## Table {element_id} (detected)"
TABLE_PAGE_LINE = "Page {page}"
SEPARATOR_PATTERN = r"[\s|:\-]*"
IGNORED_CHARS_PATTERN = r"[\s|]"
MIN_ANCHOR_KEY = "tables.min_anchor_chars"
DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent / "assets" / "ugs_config.json"


class TablesError(ValueError):
    """A record or the elements file is not usable; the message names the file or the key."""


def load_min_anchor_chars(path: Optional[Path] = None) -> int:
    """
    --------------------------------------------------------------------------
    Purpose:
        Read the shortest anchor, in characters after normalisation, that can prove a table is already in
        the page text (`tables.min_anchor_chars`).

    Inputs:
        path (Path | None): the configuration file; None means the work-ugs-audit assets file

    Outputs:
        value (int): the configured minimum, a positive integer.

    Raises:
        TablesError: the file is missing or not JSON, the key is absent, or its value is not a positive
        integer; the message names the key and the file (R3).
    --------------------------------------------------------------------------
    """
    config_path = Path(path) if path is not None else DEFAULT_CONFIG_PATH
    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise TablesError(f"configuration {config_path.name} is not readable JSON: {exc}") from None
    entry = raw.get(MIN_ANCHOR_KEY) if isinstance(raw, dict) else None
    value = entry.get("value") if isinstance(entry, dict) else None
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise TablesError(f"missing or invalid key '{MIN_ANCHOR_KEY}' in {config_path.name}")
    return value


def _require(record: Dict[str, Any], key: str) -> Any:
    """
    --------------------------------------------------------------------------
    Purpose:
        Return one key of an element record, or raise a named error when it is absent (R3).

    Inputs:
        record (dict): an element record
        key (str): the key required

    Outputs:
        value (Any): the value stored under `key`.

    Raises:
        TablesError: the key is missing from the record.
    --------------------------------------------------------------------------
    """
    if key not in record:
        raise TablesError(f"element record {record.get('element_id', '?')} has no key '{key}'")
    return record[key]


def _top(record: Dict[str, Any]) -> float:
    """
    --------------------------------------------------------------------------
    Purpose:
        Return the vertical position of an element record, used to order records in reading order.

    Inputs:
        record (dict): an element record with a `rect` of four numbers [x0, y0, x1, y1]

    Outputs:
        top (float): the y coordinate of the top edge of the element.

    Raises:
        TablesError: the `rect` key is missing from the record.
    --------------------------------------------------------------------------
    """
    return float(_require(record, "rect")[1])


def _key(text: str) -> str:
    """
    --------------------------------------------------------------------------
    Purpose:
        Reduce a line or a text to the form used to compare a table row with the page text.

    Inputs:
        text (str): any text

    Outputs:
        key (str): the text without spaces and pipes, in lower case.

    Raises:
        None.
    --------------------------------------------------------------------------
    """
    return re.sub(IGNORED_CHARS_PATTERN, "", text).casefold()


def _anchor_row(markdown: str) -> str:
    """
    --------------------------------------------------------------------------
    Purpose:
        Choose the line of a table Markdown that identifies it in the page text: its first data row, the row
        after the header, or the header when the table has no other row.

    Inputs:
        markdown (str): the Markdown of one table

    Outputs:
        line (str): the chosen line, or an empty string when the Markdown holds no row beyond separators.

    Raises:
        None.
    --------------------------------------------------------------------------
    """
    rows = [line for line in markdown.splitlines()
            if line.strip() and not re.fullmatch(SEPARATOR_PATTERN, line)]
    if not rows:
        return ""
    return rows[1] if len(rows) > 1 else rows[0]


def load_elements(path: Path) -> List[Dict[str, Any]]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Read the element records of a report from its `elements.json`.

    Inputs:
        path (Path): the `elements.json` file of the report

    Outputs:
        records (list[dict]): the records in file order, an empty list when the file does not exist.

    Raises:
        TablesError: the file is not valid JSON, or its content is not a list of objects.
    --------------------------------------------------------------------------
    """
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise TablesError(f"{path.name} is not readable JSON: {exc}") from None
    if not isinstance(data, list) or not all(isinstance(item, dict) for item in data):
        raise TablesError(f"{path.name} must hold a JSON list of element records")
    return data


def tables_on_page(elements: List[Dict[str, Any]], page: int) -> List[Dict[str, Any]]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Select the table records of one page, in reading order.

    Inputs:
        elements (list[dict]): the element records of a report
        page (int): the page, 1-based

    Outputs:
        tables (list[dict]): the records of type `table` on that page, sorted by their top edge.

    Raises:
        TablesError: a table record has no `rect`.
    --------------------------------------------------------------------------
    """
    found = [e for e in elements if e.get("element_type") == TABLE_TYPE and e.get("page") == page]
    return sorted(found, key=_top)


def enrich_page_text(text: str, tables: List[Dict[str, Any]], min_anchor_chars: Optional[int] = None) -> str:
    """
    --------------------------------------------------------------------------
    Purpose:
        Append the Markdown of each table whose first data row is not already in the page text.

    Details:
        The row compared is the first data row after the header, or the header of a table with no other row.
        Spaces, pipes and case are ignored on both sides. A table with no row beyond its separator adds
        nothing. An anchor shorter than `min_anchor_chars` after normalisation cannot prove the table is in
        the text (a short number matches almost any page), so the table is added: the model then sees it
        twice rather than not at all. The added block is headed by the element id and states the page, in
        the order given.

    Inputs:
        text (str): the text of one page
        tables (list[dict]): the table records of that page, in reading order (see tables_on_page)
        min_anchor_chars (int | None): the shortest anchor that proves presence; None reads
            `tables.min_anchor_chars` from the configuration

    Outputs:
        page_text (str): the text with the missing tables appended, or `text` itself when nothing is added.

    Raises:
        TablesError: a table record has no `element_id` or no `page`, or the configured minimum is absent.
    --------------------------------------------------------------------------
    """
    minimum = load_min_anchor_chars() if min_anchor_chars is None else min_anchor_chars
    haystack = _key(text)
    blocks = []
    for table in tables:
        markdown = (table.get("markdown") or "").strip()
        anchor = _key(_anchor_row(markdown))
        if not anchor or (len(anchor) >= minimum and anchor in haystack):
            continue
        element_id = _require(table, "element_id")
        page = _require(table, "page")
        blocks.append("\n".join([TABLE_HEADING.format(element_id=element_id),
                                 TABLE_PAGE_LINE.format(page=page), "", markdown]))
    if not blocks:
        return text
    body = "\n\n".join(blocks)
    return f"{text.rstrip()}\n\n{body}" if text.strip() else body


def figure_records(elements: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Select the figure records of a report for the figure step, each with a `figure_id` equal to its
        element id, in reading order.

    Inputs:
        elements (list[dict]): the element records of a report

    Outputs:
        records (list[dict]): copies of the records of type `figure`, with `figure_id` added, sorted by page
        and top edge. Tables and logos are not returned.

    Raises:
        TablesError: a figure record has no `element_id`, `page` or `rect`.
    --------------------------------------------------------------------------
    """
    figures = [e for e in elements if e.get("element_type") == FIGURE_TYPE]
    for record in figures:
        _require(record, "element_id")
        _require(record, "page")
    ordered = sorted(figures, key=lambda e: (e["page"], _top(e)))
    return [dict(record, figure_id=record["element_id"]) for record in ordered]
