"""test_grade_total - offline suite for grade totals (Issue 104, plan 3).

Every fixture is fictitious (R34). Sums use Decimal, so a run of half points adds up exactly.
"""
import copy
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS))
import grade_total as gt  # noqa: E402
from grade_total import GradeError  # noqa: E402


def _item(item_id, points):
    """Return one fictitious rubric item."""
    return {
        "id": item_id,
        "title": "Fictitious item",
        "max_points": points,
        "criteria": ["Fictitious criterion."],
        "checklist": ["Fictitious check."],
    }


def _rubric():
    """Return a fictitious three-item rubric totalling 20."""
    return {
        "assessment_type": "lab_report",
        "total_points": 20,
        "items": [_item("I01", 5), _item("I02", 5), _item("I03", 10)],
    }


def _entry(item_id, status="rated", score=None):
    """Return one fictitious grade entry."""
    return {"item_id": item_id, "status": status, "score": score, "comment": "Fictitious.",
            "evidence": [], "audit": "not_run", "flag": False}


def _grade(*entries):
    """Return a fictitious grade record holding the given entries."""
    return {"report_id": "R01", "loop": 1, "items": list(entries)}


class GradeTotalTests(unittest.TestCase):
    """Totals, percentages and the not_run and not_applicable rules."""

    def test_total_and_percent_on_a_full_grade(self):
        """A full grade gives the exact total and 100 percent."""
        result = gt.compute(_rubric(), _grade(_entry("I01", score=5), _entry("I02", score=5),
                                              _entry("I03", score=10)))
        self.assertEqual(result["total"], "20")
        self.assertEqual(result["max_rated"], "20")
        self.assertEqual(result["percent"], 100.0)
        self.assertTrue(result["complete"])

    def test_decimal_points_sum_exactly(self):
        """Half points add up exactly, with no float drift."""
        rubric = {"assessment_type": "lab_report", "total_points": 1.5,
                  "items": [_item("I01", 0.5), _item("I02", 0.5), _item("I03", 0.5)]}
        grade = _grade(_entry("I01", score=0.5), _entry("I02", score=0.5), _entry("I03", score=0.5))
        self.assertEqual(gt.compute(rubric, grade)["total"], "1.5")

    def test_not_applicable_is_excluded_from_the_maximum(self):
        """A not_applicable item leaves the maximum and the total unchanged."""
        result = gt.compute(_rubric(), _grade(_entry("I01", score=5),
                                              _entry("I02", status="not_applicable"),
                                              _entry("I03", score=5)))
        self.assertEqual(result["max_rated"], "15")
        self.assertEqual(result["total"], "10")
        self.assertAlmostEqual(result["percent"], 66.67, places=2)

    def test_an_absent_element_rated_zero_counts_as_zero(self):
        """A rated zero is a score, not a missing value."""
        result = gt.compute(_rubric(), _grade(_entry("I01", score=0), _entry("I02", score=5),
                                              _entry("I03", score=10)))
        self.assertEqual(result["total"], "15")
        self.assertEqual(result["by_item"]["I01"]["score"], "0")

    def test_not_run_makes_the_total_null_and_lists_the_item(self):
        """A not_run item leaves total and percent null and is listed."""
        result = gt.compute(_rubric(), _grade(_entry("I01", score=5),
                                              _entry("I02", status="not_run"),
                                              _entry("I03", score=10)))
        self.assertFalse(result["complete"])
        self.assertIsNone(result["total"])
        self.assertIsNone(result["percent"])
        self.assertEqual(result["not_run"], ["I02"])

    def test_all_not_applicable_gives_null_percent(self):
        """Nothing rated gives an undefined percentage, not a division by zero."""
        result = gt.compute(_rubric(), _grade(_entry("I01", status="not_applicable"),
                                              _entry("I02", status="not_applicable"),
                                              _entry("I03", status="not_applicable")))
        self.assertIsNone(result["percent"])
        self.assertEqual(result["max_rated"], "0")
        self.assertTrue(result["complete"])


class GradeRefusalTests(unittest.TestCase):
    """Each GradeError cause is refused and names what is wrong."""

    def _refused(self, grade, fragment, rubric=None):
        """Assert compute refuses the grade and the message contains the fragment."""
        with self.assertRaises(GradeError) as ctx:
            gt.compute(rubric or _rubric(), grade)
        self.assertIn(fragment, str(ctx.exception))

    def test_score_above_the_maximum_names_the_item(self):
        """A score above the item maximum is refused naming the item."""
        self._refused(_grade(_entry("I01", score=6), _entry("I02", score=5), _entry("I03", score=10)),
                      "I01")

    def test_negative_score_names_the_item(self):
        """A negative score is refused naming the item."""
        self._refused(_grade(_entry("I01", score=-1), _entry("I02", score=5), _entry("I03", score=10)),
                      "I01")

    def test_rated_without_a_score_is_refused(self):
        """A rated item with a null score is refused naming the item."""
        self._refused(_grade(_entry("I01", score=None), _entry("I02", score=5), _entry("I03", score=10)),
                      "I01")

    def test_not_run_with_a_score_is_refused(self):
        """A not_run item carrying a score is refused naming the item."""
        self._refused(_grade(_entry("I01", status="not_run", score=3), _entry("I02", score=5),
                             _entry("I03", score=10)), "I01")

    def test_id_mismatch_lists_missing_and_extra_ids(self):
        """A grade whose ids differ from the rubric lists both sides."""
        self._refused(_grade(_entry("I01", score=5), _entry("I02", score=5), _entry("I09", score=1)),
                      "I03")

    def test_duplicate_grade_id_is_refused(self):
        """A grade listing one item twice is refused."""
        self._refused(_grade(_entry("I01", score=5), _entry("I01", score=5), _entry("I03", score=10)),
                      "I01")

    def test_invalid_rubric_is_refused_before_grading(self):
        """An invalid rubric is refused and the grade is not read."""
        rubric = copy.deepcopy(_rubric())
        rubric["total_points"] = 99
        with self.assertRaises(Exception) as ctx:
            gt.compute(rubric, _grade(_entry("I01", score=5), _entry("I02", score=5), _entry("I03", score=10)))
        self.assertIn("99", str(ctx.exception))


class CliTests(unittest.TestCase):
    """Exit codes of the command line."""

    def test_cli_exit_codes(self):
        """A valid grade exits 0 and a grade with a bad score exits 2."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            rubric_path = root / "rubric.json"
            rubric_path.write_text(json.dumps(_rubric()), encoding="utf-8")
            good = root / "good.json"
            good.write_text(json.dumps(_grade(_entry("I01", score=5), _entry("I02", score=5),
                                              _entry("I03", score=10))), encoding="utf-8")
            bad = root / "bad.json"
            bad.write_text(json.dumps(_grade(_entry("I01", score=9), _entry("I02", score=5),
                                             _entry("I03", score=10))), encoding="utf-8")
            with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                self.assertEqual(gt.main([str(rubric_path), str(good)]), 0)
                self.assertEqual(gt.main([str(rubric_path), str(bad)]), 2)
                self.assertEqual(gt.main([str(rubric_path), str(root / "missing.json")]), 2)


if __name__ == "__main__":
    unittest.main()
