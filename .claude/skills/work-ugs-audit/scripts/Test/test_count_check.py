"""
Offline tests for count_check.py (Issue 126, plan 6 task 1, requirement E2).

Every title is fictitious (R34). No PDF and no model is used (R21): the element records and the declared counts are
given directly.
"""
import sys
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS))

import count_check  # noqa: E402


def _declared(figures=None, figure_numbers=None, tables=None, table_numbers=None) -> dict:
    """
    Purpose:
        Build the declared-count dict the way plan 5 writes it into report_meta.json.

    Inputs:
        figures (int or None), figure_numbers (list of str or None), tables (int or None), table_numbers (list or None).

    Outputs:
        dict: the declared keys.

    Raises:
        None.
    """
    return {"declared_figures": figures, "declared_figure_numbers": figure_numbers,
            "declared_tables": tables, "declared_table_numbers": table_numbers}


def _element(kind: str, title: str) -> dict:
    """
    Purpose:
        Build a fictitious element record with a type and a title.

    Inputs:
        kind (str): figure, table, table_image or logo.
        title (str): the title line of the element.

    Outputs:
        dict: the record.

    Raises:
        None.
    """
    return {"element_id": "X", "element_type": kind, "title": {"text": title}}


class CompareTests(unittest.TestCase):
    """The comparison per type, with the numbers listed."""

    def test_declared_three_extracted_two_is_mismatch(self):
        declared = _declared(3, ["1", "2", "3"])
        elements = [_element("figure", "Figure 1. A"), _element("figure", "Figure 2. B")]
        result = count_check.compare_counts(declared, elements)
        self.assertEqual(result["figure_count_status"], "mismatch")
        self.assertEqual(result["declared_figures"], 3)
        self.assertEqual(result["extracted_figures"], 2)
        self.assertEqual(result["missing_figure_numbers"], ["3"])

    def test_equal_counts_are_ok(self):
        declared = _declared(2, ["1", "2"])
        elements = [_element("figure", "Figure 1. A"), _element("figure", "Figure 2. B")]
        result = count_check.compare_counts(declared, elements)
        self.assertEqual(result["figure_count_status"], "ok")
        self.assertEqual(result["missing_figure_numbers"], [])
        self.assertEqual(result["extra_figure_numbers"], [])

    def test_missing_declared_is_not_found(self):
        elements = [_element("figure", "Figure 1. A")]
        result = count_check.compare_counts(_declared(None, None), elements)
        self.assertEqual(result["figure_count_status"], "not_found")
        self.assertEqual(result["table_count_status"], "not_found")
        self.assertEqual(result["extracted_figures"], 1)

    def test_table_image_counts_as_table(self):
        declared = _declared(tables=1, table_numbers=["1"])
        elements = [_element("table_image", "Table 1. Parametres")]
        result = count_check.compare_counts(declared, elements)
        self.assertEqual(result["extracted_tables"], 1)
        self.assertEqual(result["table_count_status"], "ok")

    def test_logo_is_not_counted(self):
        declared = _declared(1, ["1"])
        elements = [_element("logo", "Figure 1. Logo"), _element("figure", "Figure 1. A")]
        result = count_check.compare_counts(declared, elements)
        self.assertEqual(result["extracted_figures"], 1)
        self.assertEqual(result["figure_count_status"], "ok")

    def test_same_count_different_numbers_is_mismatch(self):
        declared = _declared(3, ["1", "2", "3"])
        elements = [_element("figure", "Figure 1. A"), _element("figure", "Figure 2. B"),
                    _element("figure", "Figure 5. C")]
        result = count_check.compare_counts(declared, elements)
        self.assertEqual(result["figure_count_status"], "mismatch")
        self.assertEqual(result["missing_figure_numbers"], ["3"])
        self.assertEqual(result["extra_figure_numbers"], ["5"])

    def test_more_extracted_than_declared_gives_both_numbers(self):
        declared = _declared(1, ["1"])
        elements = [_element("figure", "Figure 1. A"), _element("figure", "Figure 2. B")]
        result = count_check.compare_counts(declared, elements)
        self.assertEqual(result["figure_count_status"], "mismatch")
        self.assertEqual(result["declared_figures"], 1)
        self.assertEqual(result["extracted_figures"], 2)


if __name__ == "__main__":
    unittest.main()
