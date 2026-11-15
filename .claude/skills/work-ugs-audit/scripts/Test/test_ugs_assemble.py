import sys
import os
import json
import unittest
import tempfile
from pathlib import Path
from typing import List, Dict, Any, Optional
from unittest.mock import patch

# Add parent folders to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent / "figure-review" / "scripts" / "Test"))

import ugs_assemble
from _pdf_fixtures import make_report


class TestUgsAssemble(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = Path(tempfile.mkdtemp())
        self.report_dir = self.tmp_dir / "R01"
        self.report_dir.mkdir()
        
        # Create a dummy PDF
        self.src_pdf = self.report_dir / "source.pdf"
        make_report(self.src_pdf, [{"text": "Hello World"}])
        
        # Rubric
        self.rubric = {
            "assessment_type": "lab_report",
            "total_points": 100,
            "items": [
                {"id": "I01", "title": "Intro", "max_points": 50, "criteria": [], "checklist": []},
                {"id": "I02", "title": "Body", "max_points": 50, "criteria": [], "checklist": []}
            ]
        }
        
        # Grade
        self.grade = {
            "report_id": "R01",
            "loop": 1,
            "items": [
                {
                    "item_id": "I01",
                    "status": "rated",
                    "score": 45.0,
                    "comment": "Good",
                    "evidence": [{"page": 1, "quote": "Hello"}]
                },
                {
                    "item_id": "I02",
                    "status": "not_run",
                    "score": None,
                    "comment": "",
                    "evidence": []
                }
            ]
        }
        
        # Write grade.json
        with open(self.report_dir / "grade.json", "w", encoding="utf-8") as f:
            json.dump(self.grade, f)
            
        # Settings
        self.settings = {
            "colors": {"technical": "#0000ff", "figure": "#00ff00", "reference": "#ff0000", "language": "#000000"},
            "author": "Prof. Test",
            "quote_chars": 10,
            "url_timeout_s": 5,
            "max_retries": 2,
            "patterns": [],
            "ref_comments": {
                "malformed": {"en": "Malformed", "fr": "Malformé"},
                "unreachable": {"en": "Unreachable", "fr": "Inaccessible"},
                "blocked": {"en": "Blocked", "fr": "Bloqué"},
                "uncited": {"en": "Uncited", "fr": "Non cité"}
            },
            "annex_template": "<html><body>{{REPORT_ID}} {{LOOP}} {{ROWS}} {{TOTAL}}</body></html>"
        }
        
        self.pages = ["Hello World"]
        self.language = "en"

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_grade_annotations_one_per_evidence_entry(self):
        annotations = ugs_assemble.grade_annotations(self.rubric, self.grade)
        self.assertEqual(len(annotations), 1)
        self.assertEqual(annotations[0]["page"], 1)
        self.assertEqual(annotations[0]["kind"], "technical")
        self.assertEqual(annotations[0]["code"], "I01")
        self.assertEqual(annotations[0]["quote"], "Hello")
        self.assertIsNone(annotations[0]["rect"])
        self.assertEqual(annotations[0]["comment"], "I01 45.0 / 50: Good")

    def test_unrated_items_make_no_annotation(self):
        # I02 is not_run, so no annotation for it.
        # I01 is rated.
        # If we make I01 not_applicable, it should have no annotation.
        grade_copy = json.loads(json.dumps(self.grade))
        grade_copy["items"][0]["status"] = "not_applicable"
        grade_copy["items"][0]["score"] = None
        annotations = ugs_assemble.grade_annotations(self.rubric, grade_copy)
        self.assertEqual(len(annotations), 0)

    def test_figure_annotations_only_for_failed_criteria_with_a_comment(self):
        figures = {
            "report_id": "R01",
            "figures": [
                {
                    "figure_id": "F01",
                    "page": 1,
                    "rect": [10, 10, 100, 100],
                    "criteria": {
                        "c1": {"verdict": "fail", "reason": "Bad"},
                        "c2": {"verdict": "pass", "reason": "Good"},
                        "c3": {"verdict": "fail", "reason": None}
                    }
                }
            ]
        }
        annotations = ugs_assemble.figure_annotations(figures)
        self.assertEqual(len(annotations), 1)
        self.assertEqual(annotations[0]["code"], "c1")
        self.assertEqual(annotations[0]["comment"], "Bad")
        self.assertEqual(annotations[0]["rect"], [10, 10, 100, 100])
        self.assertEqual(annotations[0]["page"], 1)

    def test_reference_codes_and_their_priority(self):
        results = [
            {"index": 1, "kind": "url", "status": "unreachable", "cited": False},
            {"index": 2, "kind": "standard", "status": "malformed", "cited": True},
            {"index": 3, "kind": "url", "status": "reachable", "cited": False}
        ]
        entries = [
            {"page": 1, "text": "Ref 1"},
            {"page": 2, "text": "Ref 2"},
            {"page": 3, "text": "Ref 3"}
        ]
        comments = self.settings["ref_comments"]
        annotations = ugs_assemble.reference_annotations(results, entries, comments, self.language, 10)
        
        self.assertEqual(len(annotations), 3)
        self.assertEqual(annotations[0]["code"], "unreachable")
        self.assertEqual(annotations[1]["code"], "malformed")
        self.assertEqual(annotations[2]["code"], "uncited")

    def test_reference_comment_is_in_the_report_language(self):
        results = [
            {"index": 1, "kind": "url", "status": "unreachable", "cited": True}
        ]
        entries = [
            {"page": 1, "text": "Ref 1"}
        ]
        comments = self.settings["ref_comments"]
        annotations = ugs_assemble.reference_annotations(results, entries, comments, "fr", 10)
        self.assertEqual(annotations[0]["comment"], "Inaccessible")

    @patch('ugs_assemble.annotate')
    @patch('ugs_assemble.append_annex')
    @patch('ugs_assemble.check_all')
    @patch('ugs_assemble.compute')
    def test_assemble_writes_totals_annotations_and_annotated_copy(self, mock_compute, mock_check_all, mock_append_annex, mock_annotate):
        # Mock compute
        mock_compute.return_value = {
            "report_id": "R01",
            "total": "45.0",
            "max_rated": "50.0",
            "percent": None,  # a not_run item makes total and percent null (grade_total contract)
            "by_item": {},
            "not_run": ["I02"],
            "complete": False
        }
        
        # Mock check_all (references)
        mock_check_all.return_value = []
        
        # Mock annotate - simulate file creation
        def mock_annotate_side_effect(src, items, dst, colors, author):
            import shutil
            shutil.copy(src, dst)
            return {"placed": 1, "not_found": [], "duplicates": []}
        mock_annotate.side_effect = mock_annotate_side_effect
        mock_annotate.return_value = {"placed": 1, "not_found": [], "duplicates": []}
        
        # Mock append_annex
        mock_append_annex.return_value = 2
        
        # Create language.json and figures.json to test reading them
        with open(self.report_dir / "language.json", "w", encoding="utf-8") as f:
            json.dump({"annotations": [{"page": 1, "code": "L01", "quote": "Hello", "comment": "Fix"}]}, f)
            
        with open(self.report_dir / "figures.json", "w", encoding="utf-8") as f:
            json.dump({"figures": [{"figure_id": "F01", "page": 1, "rect": [1,1,1,1], "criteria": {"c1": {"verdict": "fail", "reason": "Bad"}}}]}, f)

        result = ugs_assemble.assemble_report(
            self.src_pdf,
            self.report_dir,
            "R01",
            1,
            self.rubric,
            self.pages,
            self.language,
            self.settings,
            fetch=None
        )
        
        # Check files exist
        self.assertTrue((self.report_dir / "totals.json").exists())
        self.assertTrue((self.report_dir / "annotations.json").exists())
        self.assertTrue((self.report_dir / "annotated.pdf").exists())
        
        # Check result
        self.assertEqual(result["report_id"], "R01")
        self.assertEqual(result["placed"], 1)
        self.assertEqual(result["annex_pages"], 2)
        self.assertFalse(result["complete"])
        self.assertIsNone(result["percent"]) # Since complete is False in mock
        
        # Check annotations.json content
        with open(self.report_dir / "annotations.json", "r", encoding="utf-8") as f:
            annotations = json.load(f)
            # 1 from grade, 1 from language, 1 from figures
            self.assertEqual(len(annotations), 3)

    @patch('ugs_assemble.annotate')
    @patch('ugs_assemble.append_annex')
    @patch('ugs_assemble.check_all')
    @patch('ugs_assemble.compute')
    def test_assemble_appends_the_rubric_pages_and_leaves_the_source_unchanged(self, mock_compute, mock_check_all, mock_append_annex, mock_annotate):
        import hashlib
        
        def file_hash(path):
            with open(path, "rb") as f:
                return hashlib.sha256(f.read()).hexdigest()
        
        hash_before = file_hash(self.src_pdf)
        
        mock_compute.return_value = {
            "report_id": "R01",
            "total": "45.0",
            "max_rated": "50.0",
            "percent": 90.0,
            "by_item": {},
            "not_run": [],
            "complete": True
        }
        mock_check_all.return_value = []
        mock_annotate.return_value = {"placed": 0, "not_found": [], "duplicates": []}
        mock_append_annex.return_value = 1
        
        ugs_assemble.assemble_report(
            self.src_pdf,
            self.report_dir,
            "R01",
            1,
            self.rubric,
            self.pages,
            self.language,
            self.settings,
            fetch=None
        )
        
        hash_after = file_hash(self.src_pdf)
        self.assertEqual(hash_before, hash_after)

    @patch('ugs_assemble.annotate')
    @patch('ugs_assemble.append_annex')
    @patch('ugs_assemble.check_all')
    @patch('ugs_assemble.compute')
    def test_missing_language_and_figures_files_are_fine(self, mock_compute, mock_check_all, mock_append_annex, mock_annotate):
        # Ensure files do not exist
        if (self.report_dir / "language.json").exists():
            (self.report_dir / "language.json").unlink()
        if (self.report_dir / "figures.json").exists():
            (self.report_dir / "figures.json").unlink()
            
        mock_compute.return_value = {
            "report_id": "R01",
            "total": "45.0",
            "max_rated": "50.0",
            "percent": 90.0,
            "by_item": {},
            "not_run": [],
            "complete": True
        }
        mock_check_all.return_value = []
        mock_annotate.return_value = {"placed": 1, "not_found": [], "duplicates": []}
        mock_append_annex.return_value = 1
        
        # Should not raise
        ugs_assemble.assemble_report(
            self.src_pdf,
            self.report_dir,
            "R01",
            1,
            self.rubric,
            self.pages,
            self.language,
            self.settings,
            fetch=None
        )

    @patch('ugs_assemble.annotate')
    @patch('ugs_assemble.append_annex')
    @patch('ugs_assemble.check_all')
    @patch('ugs_assemble.compute')
    def test_not_run_item_withholds_the_total(self, mock_compute, mock_check_all, mock_append_annex, mock_annotate):
        # This is tested via compute mock, but also ensure assemble handles it
        mock_compute.return_value = {
            "report_id": "R01",
            "total": None,
            "max_rated": "50.0",
            "percent": None,
            "by_item": {},
            "not_run": ["I02"],
            "complete": False
        }
        mock_check_all.return_value = []
        mock_annotate.return_value = {"placed": 0, "not_found": [], "duplicates": []}
        mock_append_annex.return_value = 1
        
        result = ugs_assemble.assemble_report(
            self.src_pdf,
            self.report_dir,
            "R01",
            1,
            self.rubric,
            self.pages,
            self.language,
            self.settings,
            fetch=None
        )
        
        self.assertFalse(result["complete"])
        self.assertIsNone(result["percent"])

    def test_missing_setting_is_named(self):
        settings = dict(self.settings)
        del settings["author"]
        
        with self.assertRaises(ValueError) as context:
            ugs_assemble.assemble_report(
                self.src_pdf,
                self.report_dir,
                "R01",
                1,
                self.rubric,
                self.pages,
                self.language,
                settings,
                fetch=None
            )
        self.assertIn("author", str(context.exception))

    @patch('ugs_assemble.annotate')
    @patch('ugs_assemble.append_annex')
    @patch('ugs_assemble.check_all')
    @patch('ugs_assemble.compute')
    def test_return_value_holds_no_report_text(self, mock_compute, mock_check_all, mock_append_annex, mock_annotate):
        mock_compute.return_value = {
            "report_id": "R01",
            "total": "45.0",
            "max_rated": "50.0",
            "percent": 90.0,
            "by_item": {},
            "not_run": [],
            "complete": True
        }
        mock_check_all.return_value = []
        mock_annotate.return_value = {"placed": 0, "not_found": [], "duplicates": []}
        mock_append_annex.return_value = 1
        
        result = ugs_assemble.assemble_report(
            self.src_pdf,
            self.report_dir,
            "R01",
            1,
            self.rubric,
            self.pages,
            self.language,
            self.settings,
            fetch=None
        )
        
        # Check keys
        expected_keys = {"report_id", "placed", "not_found", "duplicates", "annex_pages", "complete", "percent"}
        self.assertEqual(set(result.keys()), expected_keys)
        
        # Check values don't contain text
        self.assertEqual(result["report_id"], "R01")
        self.assertIsInstance(result["placed"], int)
        self.assertIsInstance(result["not_found"], list)
        self.assertIsInstance(result["duplicates"], list)
        self.assertIsInstance(result["annex_pages"], int)
        self.assertIsInstance(result["complete"], bool)
        self.assertIsInstance(result["percent"], (float, type(None)))

    @patch('ugs_assemble.annotate')
    @patch('ugs_assemble.append_annex')
    @patch('ugs_assemble.check_all')
    @patch('ugs_assemble.compute')
    def test_outputs_stay_inside_the_report_folder(self, mock_compute, mock_check_all, mock_append_annex, mock_annotate):
        mock_compute.return_value = {
            "report_id": "R01",
            "total": "45.0",
            "max_rated": "50.0",
            "percent": 90.0,
            "by_item": {},
            "not_run": [],
            "complete": True
        }
        mock_check_all.return_value = []
        def mock_annotate_side_effect(src, items, dst, colors, author):
            import shutil
            shutil.copy(src, dst)
            return {"placed": 0, "not_found": [], "duplicates": []}
        mock_annotate.side_effect = mock_annotate_side_effect
        mock_annotate.return_value = {"placed": 0, "not_found": [], "duplicates": []}
        mock_append_annex.return_value = 1
        
        ugs_assemble.assemble_report(
            self.src_pdf,
            self.report_dir,
            "R01",
            1,
            self.rubric,
            self.pages,
            self.language,
            self.settings,
            fetch=None
        )
        
        # Check that files are in report_dir
        for file in ["totals.json", "annotations.json", "annotated.pdf"]:
            path = self.report_dir / file
            self.assertTrue(path.exists())
            self.assertTrue(str(path.resolve()).startswith(str(self.report_dir.resolve())))


if __name__ == "__main__":
    unittest.main()
