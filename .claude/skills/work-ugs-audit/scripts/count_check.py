"""
count_check - declared against extracted counts of figures and tables (Issue 126, plan 6, requirement E2).

Stage: preparation of the work folder. compare_counts takes the declared counts of plan 5 and the element records
of figure extraction, and returns, per type, the extracted count, a status (ok, mismatch or not_found) and the printed
numbers missing or extra. A mismatch is a finding shown in the annex; it is never corrected here (spec E2). A
table_image counts as a table, a logo as nothing. Declared and extracted numbers use one pattern (front_matter.json).
"""

from typing import Any, Dict, List

import front_matter

STATUS_OK = "ok"
STATUS_MISMATCH = "mismatch"
STATUS_NOT_FOUND = "not_found"
FIGURE_TYPES = ("figure",)
TABLE_TYPES = ("table", "table_image")


def _title_numbers(records: List[Dict[str, Any]], kind: str, settings: Dict[str, Any]) -> List[str]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Read the printed number of each element title with the same pattern the declared list uses (plan 5), so both
        sides meet in one form.

    Inputs:
        records (List[dict]): the element records of one type; the title is a dict with "text", or a plain string.
        kind (str): "figure" or "table", which selects the entry words.
        settings (dict): the result of front_matter.load_entry_settings.

    Outputs:
        List[str]: the normalized numbers, in document order; a title with no number contributes nothing.

    Raises:
        re.error: when the number pattern is not a valid regular expression.
    --------------------------------------------------------------------------
    """
    words = [w for lang in ("fr", "en") for w in settings[f"{kind}_entry_words"][lang]]
    pattern = front_matter.entry_pattern(words, settings[front_matter.NUMBER_PATTERN_KEY])
    numbers: List[str] = []
    for record in records:
        title = record.get("title")
        text = title.get("text") if isinstance(title, dict) else title
        if not isinstance(text, str):
            continue
        match = pattern.search(text)
        if match:
            numbers.append(front_matter.normalize_number(match.group(1)))
    return numbers


def _kind_result(declared_count: Any, declared_numbers: Any, records: List[Dict[str, Any]], kind: str,
                 settings: Dict[str, Any]) -> dict:
    """
    --------------------------------------------------------------------------
    Purpose:
        Compare the declared and extracted counts and numbers of one type.

    Inputs:
        declared_count (int or None): the declared count; None when the list was not found.
        declared_numbers (list of str or None): the declared printed numbers, as the list printed them.
        records (List[dict]): the element records of this type.
        kind (str): "figure" or "table".
        settings (dict): the result of front_matter.load_entry_settings.

    Outputs:
        dict: extracted, status, missing and extra numbers (normalized).

    Raises:
        re.error: when the number pattern is not a valid regular expression.
    --------------------------------------------------------------------------
    """
    numbers = _title_numbers(records, kind, settings)
    extracted = len(records)
    if declared_count is None:
        return {"extracted": extracted, "status": STATUS_NOT_FOUND, "missing": [], "extra": []}
    declared_set = [front_matter.normalize_number(n) for n in (declared_numbers or [])]
    missing = [number for number in declared_set if number not in numbers]
    extra = [number for number in numbers if number not in declared_set]
    same = extracted == declared_count and not missing and not extra
    return {"extracted": extracted, "status": STATUS_OK if same else STATUS_MISMATCH,
            "missing": missing, "extra": extra}


def _untitled_summary(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Purpose: Summarise the elements with no title: how many, and on which pages (owner N2, never counted).
    Inputs:
        records (List[dict]): the untitled element records of one type.
    Outputs:
        dict - count and the sorted list of their pages, each page once.
    Raises:
        None.
    """
    return {"count": len(records), "pages": sorted({record.get("page") for record in records})}


def compare_counts(declared: Dict[str, Any], elements: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Purpose:
        Compare the declared figure and table counts with the extracted elements, per type.

    Inputs:
        declared (dict): declared_figures, declared_figure_numbers, declared_tables and declared_table_numbers, as
            plan 5 writes them into report_meta.json (a count None means the list was not found).
        elements (List[dict]): the element records, with element_type and title.

    Outputs:
        dict: declared_figures, extracted_figures, figure_count_status, declared_tables, extracted_tables,
            table_count_status, missing_figure_numbers, extra_figure_numbers, missing_table_numbers and
            extra_table_numbers. A status is ok, mismatch or not_found; a logo is counted as nothing.

    Raises:
        re.error: when the number pattern is not a valid regular expression.
    """
    figures = [e for e in elements if e.get("element_type") in FIGURE_TYPES and e.get("title")]
    tables = [e for e in elements if e.get("element_type") in TABLE_TYPES and e.get("title")]
    untitled_figures = [e for e in elements if e.get("element_type") in FIGURE_TYPES and not e.get("title")]
    untitled_tables = [e for e in elements if e.get("element_type") in TABLE_TYPES and not e.get("title")]
    settings = front_matter.load_entry_settings()
    fig = _kind_result(declared.get("declared_figures"), declared.get("declared_figure_numbers"), figures, "figure",
                       settings)
    tab = _kind_result(declared.get("declared_tables"), declared.get("declared_table_numbers"), tables, "table",
                       settings)
    return {
        "untitled_figures": _untitled_summary(untitled_figures),
        "untitled_tables": _untitled_summary(untitled_tables),
        "declared_figures": declared.get("declared_figures"),
        "extracted_figures": fig["extracted"],
        "figure_count_status": fig["status"],
        "declared_tables": declared.get("declared_tables"),
        "extracted_tables": tab["extracted"],
        "table_count_status": tab["status"],
        "missing_figure_numbers": fig["missing"],
        "extra_figure_numbers": fig["extra"],
        "missing_table_numbers": tab["missing"],
        "extra_table_numbers": tab["extra"],
    }
