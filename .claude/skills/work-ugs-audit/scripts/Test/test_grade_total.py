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
import ugs_grade  # noqa: E402
from ugs_config import default_path  # noqa: E402


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


def _rubric_four():
    """Return a fictitious rubric of one 1-point section whose four elements are listed (plan 29)."""
    item = _item("I01", 1)
    item["elements"] = [{"id": "E%d" % n, "text": "Fictitious element %d" % n} for n in (1, 2, 3, 4)]
    return {"assessment_type": "lab_report", "total_points": 1, "items": [item]}


def _el(identifier, verdict):
    """Return one fictitious element of a grade item, as a hand-written file gives it."""
    return {"id": identifier, "verdict": verdict}


def _rated_elements(last_verdict, stored=None):
    """Return a fictitious grade of I01 with four elements, the last one with the given verdict."""
    item = {"item_id": "I01", "status": "rated", "score": stored, "comment": "Fictitious.", "evidence": [],
            "elements": [_el("E1", "present"), _el("E2", "present"), _el("E3", "present"), _el(
                "E4", last_verdict)]}
    return {"report_id": "R01", "items": [item]}


class RecomputeTests(unittest.TestCase):
    """Plan 29 Task 1: the section and the final scores are recomputed from the elements (owner, 2026-11-27)."""

    def run_cli(self, argv):
        """Run the command with the given arguments; return (exit code, parsed JSON or None, stderr text)."""
        out, err = StringIO(), StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = gt.main(argv)
        text = out.getvalue()
        try:
            return code, json.loads(text), err.getvalue()
        except ValueError:
            return code, None, err.getvalue()

    def test_a_hand_written_four_element_section_with_one_partial_recomputes_to_0_875(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            rubric = root / "rubric.json"
            rubric.write_text(json.dumps(_rubric_four()), encoding="utf-8")
            hand = root / "hand.json"
            hand.write_text(json.dumps(_rated_elements("partial")), encoding="utf-8")
            code, result, _ = self.run_cli([str(rubric), str(hand), "--recompute", "--json"])
        self.assertEqual(code, 0)
        item = result["items"][0]
        self.assertEqual(item["recomputed_score"], "0.875")
        self.assertEqual([(loss["id"], loss["lost"]) for loss in item["losses"]], [("E4", 0.125)])
        self.assertEqual(result["total"], "0.875")
        self.assertEqual(result["max_rated"], "1")

    def test_a_stored_score_edited_by_hand_is_a_mismatch_and_exits_1(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            rubric = root / "rubric.json"
            rubric.write_text(json.dumps(_rubric_four()), encoding="utf-8")
            edited = root / "edited.json"
            edited.write_text(json.dumps(_rated_elements("partial", stored=1.0)), encoding="utf-8")
            code, result, _ = self.run_cli([str(rubric), str(edited), "--recompute", "--json"])
        self.assertEqual(code, 1)
        self.assertIs(result["items"][0]["match"], False)
        self.assertEqual(result["items"][0]["stored_score"], "1")

    def test_an_unknown_verdict_is_refused_naming_the_item_and_the_element(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            rubric = root / "rubric.json"
            rubric.write_text(json.dumps(_rubric_four()), encoding="utf-8")
            bad = root / "bad.json"
            bad.write_text(json.dumps(_rated_elements("maybe")), encoding="utf-8")
            code, _, err = self.run_cli([str(rubric), str(bad), "--recompute"])
        self.assertEqual(code, 2)
        self.assertIn("I01", err)
        self.assertIn("E4", err)

    def test_an_element_count_different_from_the_rubric_is_refused_naming_the_item(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            rubric = root / "rubric.json"
            rubric.write_text(json.dumps(_rubric_four()), encoding="utf-8")
            short = _rated_elements("partial")
            short["items"][0]["elements"] = short["items"][0]["elements"][:3]
            path = root / "short.json"
            path.write_text(json.dumps(short), encoding="utf-8")
            code, _, err = self.run_cli([str(rubric), str(path), "--recompute"])
        self.assertEqual(code, 2)
        self.assertIn("I01", err)

    def test_write_without_yes_changes_nothing_and_with_yes_writes_a_reproducible_file(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            rubric = root / "rubric.json"
            rubric.write_text(json.dumps(_rubric_four()), encoding="utf-8")
            hand = root / "hand.json"
            hand.write_text(json.dumps(_rated_elements("partial")), encoding="utf-8")
            out = root / "grade_recomputed.json"
            self.run_cli([str(rubric), str(hand), "--recompute", "--write", str(out)])
            self.assertFalse(out.exists())
            self.run_cli([str(rubric), str(hand), "--recompute", "--write", str(out), "--yes"])
            self.assertTrue(out.exists())
            code, result, _ = self.run_cli([str(rubric), str(out), "--recompute", "--json"])
        self.assertEqual(code, 0)
        self.assertIs(result["items"][0]["match"], True)

    def test_write_onto_the_input_is_refused(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            rubric = root / "rubric.json"
            rubric.write_text(json.dumps(_rubric_four()), encoding="utf-8")
            hand = root / "hand.json"
            hand.write_text(json.dumps(_rated_elements("partial")), encoding="utf-8")
            code, _, _ = self.run_cli([str(rubric), str(hand), "--recompute", "--write", str(hand), "--yes"])
            self.assertEqual(code, 2)
            self.assertIn("E4", hand.read_text(encoding="utf-8"))


def _split_rubric_two_sections():
    """Return the rubric split by rubric_split from fictitious text: section 1 lists a checklist, section 2 none."""
    import rubric_split
    import ugs_config
    cfg = ugs_config.load(ugs_config.default_path())
    text = ("## 1. Resume (/1)\n\nLe resume contient :\n\n- [ ] Contexte\n- [ ] Objectif\n\n---\n\n"
            "## 2. Methode (/1)\n\nSimple prose, no checklist here.\n")
    return rubric_split.split_rubric(text, "lab_report", cfg["rubric.section_heading_regex"], cfg["rubric.total_regex"],
                                     cfg["rubric.loose_heading_regex"], cfg["rubric.element_regexes"])


class SplitRubricRecomputeTests(unittest.TestCase):
    """Review round 2, finding 1: a section that lists no element is recomputed from its own stored elements."""

    def test_a_checklist_section_and_a_model_named_section_both_recompute(self):
        rubric = _split_rubric_two_sections()
        self.assertEqual(rubric["items"][1]["elements"], [])
        grade = {"report_id": "R01", "items": [
            {"item_id": "I01", "status": "rated", "score": 0.5, "elements": [
                {"id": "E1", "verdict": "present"}, {"id": "E2", "verdict": "absent"}]},
            {"item_id": "I02", "status": "rated", "score": 1.0, "elements": [
                {"element": "Alpha", "verdict": "present"}, {"element": "Beta", "verdict": "present"},
                {"element": "Gamma", "verdict": "present"}]}]}
        result = gt.recompute(rubric, grade, ugs_grade.load_grade_scale(), ugs_grade.read_grade_step(default_path()))
        self.assertEqual([item["match"] for item in result["items"]], [True, True])
        self.assertEqual(result["exit_code"], 0)

    def test_the_command_exits_0_on_the_split_rubric(self):
        rubric = _split_rubric_two_sections()
        grade = {"report_id": "R01", "items": [
            {"item_id": "I01", "status": "rated", "score": 0.5, "elements": [
                {"id": "E1", "verdict": "present"}, {"id": "E2", "verdict": "absent"}]},
            {"item_id": "I02", "status": "rated", "score": 1.0, "elements": [
                {"element": "Alpha", "verdict": "present"}]}]}
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            rubric_path, grade_path = root / "rubric.json", root / "grade.json"
            rubric_path.write_text(json.dumps(rubric), encoding="utf-8")
            grade_path.write_text(json.dumps(grade), encoding="utf-8")
            with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                self.assertEqual(gt.main([str(rubric_path), str(grade_path), "--recompute"]), 0)


class ErrorCodeTests(unittest.TestCase):
    """Review round 2, finding 9: each refusal class carries the code the ledger note writes."""

    def test_grade_and_rubric_errors_carry_their_codes(self):
        from rubric_check import RubricError
        self.assertEqual(GradeError.code, "grade_error")
        self.assertEqual(RubricError.code, "rubric_error")

    def test_the_annex_error_carries_its_code(self):
        from pdf_annex import AnnexError
        self.assertEqual(AnnexError.code, "annex_error")


class StoredScoreAbsentTests(unittest.TestCase):
    """Review round 2, finding 8: a null stored score with elements is reported no_stored_score."""

    def test_a_null_stored_score_with_elements_is_no_stored_score(self):
        rubric = _rubric_four()
        grade = _rated_elements("partial")
        grade["items"][0]["score"] = None
        result = gt.recompute(rubric, grade, ugs_grade.load_grade_scale(), ugs_grade.read_grade_step(default_path()))
        self.assertEqual(result["items"][0]["match"], "no_stored_score")
        self.assertEqual(result["exit_code"], 0)


if __name__ == "__main__":
    unittest.main()
