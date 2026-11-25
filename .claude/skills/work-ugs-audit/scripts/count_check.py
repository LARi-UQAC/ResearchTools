"""
count_check - declared against extracted counts of figures and tables (Issue 126, plan 6, requirement E2).

Stage: preparation of the work folder. compare_counts takes the declared counts of plan 5 and the element records
of figure extraction, and returns, per type, the extracted count, a status (ok, mismatch or not_found) and the printed
numbers missing or extra. A mismatch is a finding shown in the annex; it is never corrected here (spec E2). A
table_image counts as a table, a logo as nothing. The printed numbers come from crossref_checks.element_numbers.
"""

from typing import Any, Dict, List

import crossref_checks

STATUS_OK = "ok"
STATUS_MISMATCH = "mismatch"
STATUS_NOT_FOUND = "not_found"
FIGURE_TYPES = ("figure",)
TABLE_TYPES = ("table", "table_image")


def _numbers_text(numbers: List[tuple]) -> List[str]:
    """
    Purpose:
        Turn the numbers read from titles, tuples such as (2, 1), into the printed strings such as "2.1".

    Inputs:
        numbers (List[tuple]): numbers as crossref_checks.element_numbers returns them.

    Outputs:
        List[str]: the dotted strings, in the order given.

    Raises:
        None.
    """
    return [".".join(str(part) for part in number) for number in numbers]


def _kind_result(declared_count: Any, declared_numbers: Any, records: List[Dict[str, Any]], kind: str) -> dict:
    """
    Purpose:
        Compare the declared and extracted counts and numbers of one type.

    Inputs:
        declared_count (int or None): the declared count; None when the list was not found.
        declared_numbers (list of str or None): the declared printed numbers.
        records (List[dict]): the element records of this type.
        kind (str): "figure" or "table", the marker list used to read the titles.

    Outputs:
        dict: extracted, status, missing and extra numbers.

    Raises:
        crossref_checks.CrossrefConfigError: when the marker list of the type is missing.
    """
    as_kind = [dict(record, element_type=kind) for record in records]
    numbers = _numbers_text(crossref_checks.element_numbers(as_kind, kind))
    extracted = len(records)
    if declared_count is None:
        return {"extracted": extracted, "status": STATUS_NOT_FOUND, "missing": [], "extra": []}
    declared_set = list(declared_numbers or [])
    missing = [number for number in declared_set if number not in numbers]
    extra = [number for number in numbers if number not in declared_set]
    same = extracted == declared_count and not missing and not extra
    return {"extracted": extracted, "status": STATUS_OK if same else STATUS_MISMATCH,
            "missing": missing, "extra": extra}


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
        crossref_checks.CrossrefConfigError: when the marker lists of the element titles are missing.
    """
    figures = [e for e in elements if e.get("element_type") in FIGURE_TYPES]
    tables = [e for e in elements if e.get("element_type") in TABLE_TYPES]
    fig = _kind_result(declared.get("declared_figures"), declared.get("declared_figure_numbers"), figures, "figure")
    tab = _kind_result(declared.get("declared_tables"), declared.get("declared_table_numbers"), tables, "table")
    return {
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
