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
from typing import Any, Dict, List

TABLE_TYPE = "table"
FIGURE_TYPE = "figure"
TABLE_HEADING = "## Table {element_id} (detected)"
TABLE_PAGE_LINE = "Page {page}"
SEPARATOR_PATTERN = r"[\s|:\-]*"
IGNORED_CHARS_PATTERN = r"[\s|]"


class TablesError(ValueError):
    """A record or the elements file is not usable; the message names the file or the key."""


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


def enrich_page_text(text: str, tables: List[Dict[str, Any]]) -> str:
    """
    --------------------------------------------------------------------------
    Purpose:
        Append the Markdown of each table whose first data row is not already in the page text.

    Details:
        The row compared is the first data row after the header, or the header of a table with no other row.
        Spaces, pipes and case are ignored on both sides. A table with no row beyond its separator adds
        nothing. The added block is headed by the element id and states the page, in the order given.

    Inputs:
        text (str): the text of one page
        tables (list[dict]): the table records of that page, in reading order (see tables_on_page)

    Outputs:
        page_text (str): the text with the missing tables appended, or `text` itself when nothing is added.

    Raises:
        TablesError: a table record has no `element_id` or no `page`.
    --------------------------------------------------------------------------
    """
    haystack = _key(text)
    blocks = []
    for table in tables:
        markdown = (table.get("markdown") or "").strip()
        anchor = _anchor_row(markdown)
        if not anchor or _key(anchor) in haystack:
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
