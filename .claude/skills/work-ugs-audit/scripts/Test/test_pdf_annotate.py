import sys
import unittest
import json
import tempfile
import os
from pathlib import Path
from unittest import mock

# Put the parent folder of this test folder at the start of sys.path
# The test folder is .claude/skills/work-ugs-audit/scripts/Test
# The module is in .claude/skills/work-ugs-audit/scripts
# So parent.parent is scripts
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Import the module under test
import pdf_annotate
from pdf_annotate import AnnotateError, normalize, annotate, main

# Import fixture helper from figure-review
# Path: .claude/skills/figure-review/scripts/Test
# Current: .claude/skills/work-ugs-audit/scripts/Test
# parent (Test) -> parent (scripts) -> parent (work-ugs-audit) -> parent (skills)
sys_path_base = Path(__file__).resolve().parent.parent.parent.parent
fixture_path = sys_path_base / "figure-review" / "scripts" / "Test"
sys.path.insert(0, str(fixture_path))

from _pdf_fixtures import make_report


class TestPdfAnnotate(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.test_dir = Path(self.tmpdir.name)
        self.src_pdf = self.test_dir / "source.pdf"
        self.dst_pdf = self.test_dir / "dest.pdf"
        
        # Create a simple PDF with some text
        pages = [
            {"text": "This is a test document.", "font_size": 12},
            {"text": "Another line of text here.", "font_size": 12}
        ]
        make_report(self.src_pdf, pages)
        
        self.colors = {
            "technical": "#FF0000",
            "figure": "#00FF00",
            "language": "#0000FF",
            "reference": "#FFFF00"
        }
        self.author = "Test Professor"

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_normalize_function(self):
        # Test basic normalization
        self.assertEqual(normalize("  hello   world  "), "hello world")
        # Test hyphenation
        self.assertEqual(normalize("hy-\nphen"), "hyphen")
        # Test apostrophes
        self.assertEqual(normalize("l’exemple"), "l'exemple")

    def test_quote_is_highlighted_with_its_note_on_the_right_page(self):
        items = [
            {
                "page": 1,
                "kind": "technical",
                "code": "T01",
                "quote": "This is a test document.",
                "rect": None,
                "comment": "Good start."
            }
        ]
        result = annotate(self.src_pdf, items, self.dst_pdf, self.colors, self.author)
        self.assertEqual(result["placed"], 1)
        self.assertEqual(result["not_found"], [])
        
        # Verify annotation exists
        import fitz
        doc = fitz.open(self.dst_pdf)
        page = doc[0]
        annots = list(page.annots())
        self.assertEqual(len(annots), 1)
        annot = annots[0]
        self.assertEqual(annot.type[0], 8) # Highlight
        self.assertEqual(annot.colors["stroke"], [1.0, 0.0, 0.0]) # Red
        # Note is usually a separate annotation or part of popup? 
        # PyMuPDF highlight annots have a popup. Let's check if there's a note annot.
        # Actually, usually we add a highlight and a note. 
        # The plan says: "A quote item gets a highlight annotation on the quoted words plus a note carrying comment"
        # So we expect 2 annotations? Or 1 highlight with a popup?
        # PyMuPDF: page.add_highlight_annot, then annot.set_info(title=author, content=comment)
        # This creates a single annotation object that is a highlight with a popup.
        # So len(annots) should be 1.
        self.assertEqual(annot.info["title"], self.author)
        self.assertEqual(annot.info["content"], "Good start.")
        doc.close()

    def test_missing_quote_is_reported_not_placed(self):
        items = [
            {
                "page": 1,
                "kind": "technical",
                "code": "T01",
                "quote": "This text does not exist in the document.",
                "rect": None,
                "comment": "Missing."
            }
        ]
        result = annotate(self.src_pdf, items, self.dst_pdf, self.colors, self.author)
        self.assertEqual(result["placed"], 0)
        self.assertEqual(result["not_found"], [0])

    def test_dst_equal_to_src_is_refused(self):
        items = [
            {
                "page": 1,
                "kind": "technical",
                "code": "T01",
                "quote": "This is a test document.",
                "rect": None,
                "comment": "Test."
            }
        ]
        with self.assertRaises(AnnotateError):
            annotate(self.src_pdf, items, self.src_pdf, self.colors, self.author)

    def test_source_file_is_unchanged(self):
        import hashlib
        def file_hash(path):
            with open(path, 'rb') as f:
                return hashlib.sha256(f.read()).hexdigest()
        
        hash_before = file_hash(self.src_pdf)
        items = [
            {
                "page": 1,
                "kind": "technical",
                "code": "T01",
                "quote": "This is a test document.",
                "rect": None,
                "comment": "Test."
            }
        ]
        annotate(self.src_pdf, items, self.dst_pdf, self.colors, self.author)
        hash_after = file_hash(self.src_pdf)
        self.assertEqual(hash_before, hash_after)

    def test_main_refusal(self):
        # Test main with dst == src
        items = [
            {
                "page": 1,
                "kind": "technical",
                "code": "T01",
                "quote": "This is a test document.",
                "rect": None,
                "comment": "Test."
            }
        ]
        items_file = self.test_dir / "items.json"
        items_file.write_text(json.dumps(items))
        
        argv = [
            "--src", str(self.src_pdf),
            "--items", str(items_file),
            "--dst", str(self.src_pdf),
            "--author", self.author
        ]
        
        with mock.patch('sys.argv', argv):
            exit_code = main()
            self.assertEqual(exit_code, 2)

    def test_main_success(self):
        items = [
            {
                "page": 1,
                "kind": "technical",
                "code": "T01",
                "quote": "This is a test document.",
                "rect": None,
                "comment": "Test."
            }
        ]
        items_file = self.test_dir / "items.json"
        items_file.write_text(json.dumps(items))
        
        argv = [
            "--src", str(self.src_pdf),
            "--items", str(items_file),
            "--dst", str(self.dst_pdf),
            "--author", self.author
        ]
        
        with mock.patch('sys.argv', argv):
            # We need to mock config loading or ensure it's available
            # The plan says colors come from configuration. 
            # ugs_config.default_path() points to assets/ugs_config.json
            # We assume it exists and has valid data for the test environment.
            exit_code = main()
            self.assertEqual(exit_code, 0)

    def test_hyphenated_and_split_quote_is_found(self):
        # Create a PDF with hyphenated text
        pages = [
            {"text": "This is a hy-\nphenated word.", "font_size": 12}
        ]
        src_hyphen = self.test_dir / "hyphen.pdf"
        make_report(src_hyphen, pages)
        
        items = [
            {
                "page": 1,
                "kind": "technical",
                "code": "T01",
                "quote": "hyphenated",
                "rect": None,
                "comment": "Found hyphen."
            }
        ]
        dst_hyphen = self.test_dir / "hyphen_out.pdf"
        result = annotate(src_hyphen, items, dst_hyphen, self.colors, self.author)
        self.assertEqual(result["placed"], 1)
        self.assertEqual(result["not_found"], [])

    def test_accented_quote_is_found(self):
        pages = [
            {"text": "Café au lait.", "font_size": 12}
        ]
        src_accent = self.test_dir / "accent.pdf"
        make_report(src_accent, pages)
        
        items = [
            {
                "page": 1,
                "kind": "technical",
                "code": "T01",
                "quote": "Café",
                "rect": None,
                "comment": "Found accent."
            }
        ]
        dst_accent = self.test_dir / "accent_out.pdf"
        result = annotate(src_accent, items, dst_accent, self.colors, self.author)
        self.assertEqual(result["placed"], 1)
        self.assertEqual(result["not_found"], [])

    def test_duplicate_quote_uses_first_and_is_reported(self):
        items = [
            {
                "page": 1,
                "kind": "technical",
                "code": "T01",
                "quote": "This is a test document.",
                "rect": None,
                "comment": "First."
            },
            {
                "page": 1,
                "kind": "technical",
                "code": "T02",
                "quote": "This is a test document.",
                "rect": None,
                "comment": "Second."
            }
        ]
        dst_dup = self.test_dir / "dup_out.pdf"
        result = annotate(self.src_pdf, items, dst_dup, self.colors, self.author)
        self.assertEqual(result["placed"], 1)
        self.assertEqual(result["not_found"], [])
        self.assertEqual(result["duplicates"], [1])

    def test_rect_item_gets_a_rectangle_annotation(self):
        items = [
            {
                "page": 1,
                "kind": "figure",
                "code": "F01",
                "quote": None,
                "rect": [50, 50, 100, 100],
                "comment": "Rect test."
            }
        ]
        dst_rect = self.test_dir / "rect_out.pdf"
        result = annotate(self.src_pdf, items, dst_rect, self.colors, self.author)
        self.assertEqual(result["placed"], 1)
        
        import fitz
        doc = fitz.open(dst_rect)
        page = doc[0]
        annots = list(page.annots())
        self.assertEqual(len(annots), 1)
        annot = annots[0]
        self.assertEqual(annot.type[1], "Square")
        doc.close()

    def test_author_is_the_value_passed_in(self):
        items = [
            {
                "page": 1,
                "kind": "technical",
                "code": "T01",
                "quote": "This is a test document.",
                "rect": None,
                "comment": "Auth."
            }
        ]
        dst_auth = self.test_dir / "auth_out.pdf"
        custom_author = "Prof. Smith"
        result = annotate(self.src_pdf, items, dst_auth, self.colors, custom_author)
        
        import fitz
        doc = fitz.open(dst_auth)
        page = doc[0]
        annots = list(page.annots())
        self.assertEqual(annots[0].info["title"], custom_author)
        doc.close()

    def test_stdout_carries_counts_only(self):
        items = [
            {
                "page": 1,
                "kind": "technical",
                "code": "T01",
                "quote": "This is a test document.",
                "rect": None,
                "comment": "Count."
            }
        ]
        items_file = self.test_dir / "items.json"
        items_file.write_text(json.dumps(items))
        
        argv = [
            "--src", str(self.src_pdf),
            "--items", str(items_file),
            "--dst", str(self.dst_pdf),
            "--author", self.author
        ]
        
        with mock.patch('sys.argv', argv):
            with mock.patch('sys.stdout', new_callable=mock.mock_open()) as mock_stdout:
                exit_code = main()
                self.assertEqual(exit_code, 0)
                output = mock_stdout.mock_calls[0][1][0]
                self.assertIn("Placed: 1", output)
                self.assertIn("Not found: 0", output)
                self.assertIn("Duplicates: 0", output)


if __name__ == "__main__":
    unittest.main()
