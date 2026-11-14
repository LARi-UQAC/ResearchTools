import contextlib
import io
import json
import sys
import unittest
import tempfile
from pathlib import Path

# Add the parent folder of the Test folder to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Add the figure-review Test folder to sys.path for _pdf_fixtures
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "figure-review" / "scripts" / "Test"))

import pdf_annex
from _pdf_fixtures import make_report

class TestPdfAnnex(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.test_dir = Path(self.tmpdir.name)
        self.pdf_path = self.test_dir / "report.pdf"
        
        # Create a simple PDF
        pages = [{"text": "Page 1 content", "font_size": 12}]
        make_report(self.pdf_path, pages)
        
        self.rubric = {
            "items": [
                {"id": "I01", "title": "Item 1", "max_points": 1.0},
                {"id": "I02", "title": "Item 2", "max_points": 1.0}
            ]
        }
        
        self.grade = {
            "items": [
                {"item_id": "I01", "status": "rated", "score": 0.5, "comment": "Good start"},
                {"item_id": "I02", "status": "rated", "score": 1.0, "comment": "Perfect"}
            ]
        }
        
        self.totals = {
            "total": "1.5",
            "by_item": {
                "I01": 0.5,
                "I02": 1.0
            }
        }

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_annex_pages_are_appended_and_text_is_readable(self):
        rows = pdf_annex.render_rows(self.rubric, self.grade, self.totals)
        html = pdf_annex.build_html("Template {{REPORT_ID}} {{LOOP}} {{ROWS}} {{TOTAL}}", rows, "R01", 1, "1.5")
        pages_added = pdf_annex.append_annex(self.pdf_path, html)
        
        self.assertGreater(pages_added, 0)
        
        import fitz
        doc = fitz.open(str(self.pdf_path))
        full_text = ""
        for page in doc:
            full_text += page.get_text()
        
        self.assertIn("Item 1", full_text)
        self.assertIn("0.5 / 1", full_text)
        self.assertIn("1.5", full_text)
        doc.close()

    def test_long_comments_span_pages_without_clipping(self):
        long_comment = "This is a very long comment that should span multiple pages if the layout requires it. " * 50
        self.grade["items"][0]["comment"] = long_comment
        
        rows = pdf_annex.render_rows(self.rubric, self.grade, self.totals)
        html = pdf_annex.build_html("Template {{REPORT_ID}} {{LOOP}} {{ROWS}} {{TOTAL}}", rows, "R01", 1, "1.5")
        pdf_annex.append_annex(self.pdf_path, html)
        
        import fitz
        doc = fitz.open(str(self.pdf_path))
        full_text = ""
        for page in doc:
            full_text += page.get_text()
        
        self.assertIn(" ".join(long_comment.split()), " ".join(full_text.split()))
        doc.close()

    def test_html_special_characters_are_escaped(self):
        self.grade["items"][0]["comment"] = "A < B & C > D"
        rows = pdf_annex.render_rows(self.rubric, self.grade, self.totals)
        
        self.assertIn("&lt;", rows)
        self.assertIn("&amp;", rows)
        self.assertIn("&gt;", rows)
        self.assertNotIn("< B", rows)

    def test_not_run_item_shows_not_run_and_the_total_is_a_dash(self):
        self.grade["items"][0]["status"] = "not_run"
        self.grade["items"][0]["score"] = None
        self.totals["total"] = None
        
        rows = pdf_annex.render_rows(self.rubric, self.grade, self.totals)
        html = pdf_annex.build_html("Template {{REPORT_ID}} {{LOOP}} {{ROWS}} {{TOTAL}}", rows, "R01", 1, None)
        
        self.assertIn("not_run", rows)
        self.assertIn("-", html)

    def test_accents_render(self):
        self.grade["items"][0]["comment"] = "Café au lait"
        rows = pdf_annex.render_rows(self.rubric, self.grade, self.totals)
        html = pdf_annex.build_html("Template {{REPORT_ID}} {{LOOP}} {{ROWS}} {{TOTAL}}", rows, "R01", 1, "1.5")
        
        self.assertIn("Café", rows)

    def test_an_unreplaced_placeholder_raises(self):
        with self.assertRaises(pdf_annex.AnnexError):
            pdf_annex.build_html("Template {{REPORT_ID}} {{LOOP}} {{ROWS}} {{TOTAL}} {{UNKNOWN}}", "rows", "R01", 1, "1.5")

    def test_original_pages_are_unchanged(self):
        import fitz
        doc = fitz.open(str(self.pdf_path))
        original_text = doc[0].get_text()
        doc.close()
        
        rows = pdf_annex.render_rows(self.rubric, self.grade, self.totals)
        html = pdf_annex.build_html("Template {{REPORT_ID}} {{LOOP}} {{ROWS}} {{TOTAL}}", rows, "R01", 1, "1.5")
        pdf_annex.append_annex(self.pdf_path, html)
        
        doc = fitz.open(str(self.pdf_path))
        new_text = doc[0].get_text()
        doc.close()
        
        self.assertEqual(original_text, new_text)

    def _write_inputs(self):
        paths = {}
        for name, data in (("rubric", self.rubric), ("grade", self.grade), ("totals", self.totals)):
            paths[name] = self.test_dir / f"{name}.json"
            paths[name].write_text(json.dumps(data), encoding="utf-8")
        return paths

    def _argv(self, paths, pdf=None):
        return ["--pdf", str(pdf or self.pdf_path), "--rubric", str(paths["rubric"]),
                "--grade", str(paths["grade"]), "--totals", str(paths["totals"]),
                "--report-id", "R01", "--loop", "1"]

    def test_main_with_the_default_template_adds_pages_and_prints_only_a_count(self):
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = pdf_annex.main(self._argv(self._write_inputs()))
        self.assertEqual(code, 0)
        self.assertTrue(buffer.getvalue().strip().isdigit())

    def test_main_refuses_a_missing_input_without_naming_the_path(self):
        paths = self._write_inputs()
        paths["grade"].unlink()
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code = pdf_annex.main(self._argv(paths))
        self.assertEqual(code, 2)
        self.assertNotIn(self.test_dir.name, err.getvalue())

    def test_main_refuses_a_file_that_is_not_a_pdf_and_leaves_it_unchanged(self):
        fake = self.test_dir / "not_a_pdf.pdf"
        fake.write_bytes(b"plain text, not a pdf")
        with contextlib.redirect_stderr(io.StringIO()):
            code = pdf_annex.main(self._argv(self._write_inputs(), pdf=fake))
        self.assertEqual(code, 2)
        self.assertEqual(fake.read_bytes(), b"plain text, not a pdf")


if __name__ == "__main__":
    unittest.main()
