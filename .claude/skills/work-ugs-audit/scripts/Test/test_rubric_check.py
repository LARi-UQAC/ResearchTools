"""test_rubric_check - rubric validation suite (Issue 104, plan 3)."""
import copy
import json
import tempfile
import sys
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS))
from rubric_check import RubricError, validate
import ugs_config
from ugs_config import ConfigError


def _item(item_id, points):
    """Return one fictitious rubric item."""
    return {
        "id": item_id,
        "title": "Fictitious item",
        "max_points": points,
        "criteria": ["Fictitious criterion."],
        "checklist": ["Fictitious check."],
    }


def _points_table():
    """Return a fictitious points-table rubric totalling 100."""
    points = [10] * 9 + [5, 5]
    return {
        "assessment_type": "lab_report",
        "total_points": 100,
        "items": [_item("I%02d" % (n + 1), p) for n, p in enumerate(points)],
    }


def _checklist():
    """Return a fictitious checklist rubric totalling 28.5."""
    points = [1, 2, 10, 5, 5, 0.5, 0.5, 1, 1, 1, 1, 0.5]
    return {
        "assessment_type": "lab_report",
        "total_points": 28.5,
        "items": [_item("I%02d" % (n + 1), p) for n, p in enumerate(points)],
    }


class RubricPassTests(unittest.TestCase):
    def test_points_table_rubric_totalling_100_passes(self):
        result = validate(_points_table())
        self.assertEqual(result["items"], 11)
        self.assertEqual(result["total_points"], "100")

    def test_checklist_rubric_with_fractional_points_totalling_28_5_passes(self):
        result = validate(_checklist())
        self.assertEqual(result["total_points"], "28.5")

    def test_a_sum_mismatch_names_both_sums(self):
        table = _points_table()
        table["total_points"] = 99
        with self.assertRaises(RubricError) as ctx:
            validate(table)
        self.assertIn("100", str(ctx.exception))
        self.assertIn("99", str(ctx.exception))

    def test_unmodified_points_table_still_passes(self):
        validate(_points_table())


def _rubric():
    """Return a fictitious one-item rubric that validates."""
    return {
        "assessment_type": "lab_report",
        "total_points": 10,
        "items": [_item("I01", 10)],
    }


def _refused(case, rubric, fragment):
    """Assert validate refuses the rubric and the message names the fragment."""
    with case.assertRaises(RubricError) as ctx:
        validate(rubric)
    assert fragment in str(ctx.exception)


class RubricRefusalTests(unittest.TestCase):
    def test_unknown_assessment_type_is_refused(self):
        rubric = _rubric()
        rubric["assessment_type"] = "thesis"
        _refused(self, rubric, "assessment_type")

    def test_empty_items_is_refused(self):
        rubric = _rubric()
        rubric["items"] = []
        _refused(self, rubric, "items")

    def test_duplicate_id_is_refused(self):
        rubric = _rubric()
        rubric["items"] = [_item("I01", 5), _item("I01", 5)]
        rubric["total_points"] = 10
        _refused(self, rubric, "I01")

    def test_malformed_id_is_refused(self):
        rubric = _rubric()
        rubric["items"][0]["id"] = "A1"
        _refused(self, rubric, "A1")

    def test_non_positive_max_points_is_refused(self):
        rubric = _rubric()
        rubric["items"][0]["max_points"] = 0
        rubric["total_points"] = 0
        _refused(self, rubric, "I01")

    def test_empty_title_is_refused(self):
        rubric = _rubric()
        rubric["items"][0]["title"] = ""
        _refused(self, rubric, "title")

    def test_missing_top_level_key_is_named(self):
        rubric = _rubric()
        del rubric["items"]
        _refused(self, rubric, "items")

    def test_each_refusal_leaves_the_input_unchanged(self):
        rubric = _rubric()
        rubric["items"] = []
        original = copy.deepcopy(rubric)
        _refused(self, rubric, "items")
        self.assertEqual(rubric, original)


class ConfigTests(unittest.TestCase):
    """Config loader tests."""

    def test_shipped_config_loads_with_every_required_key(self):
        """Shipped config loads with every required key."""
        values = ugs_config.load(ugs_config.default_path())
        for key in ugs_config.REQUIRED_KEYS:
            self.assertIn(key, values)
        self.assertEqual(values["batch.outlier_z"], 2.0)
        self.assertEqual(set(values["annotation.colors"]), {"technical", "figure", "language", "reference"})

    def test_shipped_config_values_carry_provenance(self):
        """Shipped config values carry provenance."""
        data = json.loads(ugs_config.default_path().read_text(encoding="utf-8"))
        for entry in data.values():
            self.assertIsInstance(entry["provenance"], str)
            self.assertTrue(len(entry["provenance"]) > 0)

    def test_missing_key_is_named_with_its_file(self):
        """Missing key is named with its file."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            shipped = ugs_config.default_path().read_text(encoding="utf-8")
            shipped = json.loads(shipped)
            del shipped["driver.audit_retries"]
            (root / "config.json").write_text(json.dumps(shipped), encoding="utf-8")
            with self.assertRaises(ConfigError) as ctx:
                ugs_config.load(root / "config.json")
            self.assertIn("driver.audit_retries", str(ctx.exception))
            self.assertIn("config.json", str(ctx.exception))

    def test_annotation_author_reads_the_active_profile(self):
        """Annotation author reads the active profile."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / ".claude" / "CLAUDE.md").parent.mkdir(parents=True, exist_ok=True)
            (root / ".claude" / "CLAUDE.md").write_text("active_profile: fixture\n", encoding="utf-8")
            (root / "profiles").mkdir()
            (root / "profiles" / "fixture.yaml").write_text("author:\n  name: Test Author\n", encoding="utf-8")
            self.assertEqual(ugs_config.annotation_author(root), "Test Author")

    def test_missing_profile_is_refused_naming_it(self):
        """Missing profile is refused naming it."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / ".claude" / "CLAUDE.md").parent.mkdir(parents=True, exist_ok=True)
            (root / ".claude" / "CLAUDE.md").write_text("active_profile: absent\n", encoding="utf-8")
            with self.assertRaises(ConfigError) as ctx:
                ugs_config.annotation_author(root)
            self.assertIn("absent", str(ctx.exception))

    def test_author_without_name_is_refused(self):
        """Author without name is refused."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / ".claude" / "CLAUDE.md").parent.mkdir(parents=True, exist_ok=True)
            (root / ".claude" / "CLAUDE.md").write_text("active_profile: fixture\n", encoding="utf-8")
            (root / "profiles").mkdir()
            (root / "profiles" / "fixture.yaml").write_text("author:\n  email: test@example.org\n", encoding="utf-8")
            with self.assertRaises(ConfigError) as ctx:
                ugs_config.annotation_author(root)
            self.assertIn("name", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
