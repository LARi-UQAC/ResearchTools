import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from _pdf_fixtures import make_report, image_info
import fitz


class TestPdfFixtures(unittest.TestCase):
    def setUp(self):
        self.test_dir = Path(__file__).parent / "fixtures"
        if not self.test_dir.exists():
            self.test_dir.mkdir()
        self.pdf_path = self.test_dir / "test_report.pdf"

    def tearDown(self):
        if self.pdf_path.exists():
            self.pdf_path.unlink()

    def test_page_count_matches_the_page_list(self):
        pages = [
            {"text": "Page 1"},
            {"text": "Page 2"},
            {"text": "Page 3"}
        ]
        make_report(self.pdf_path, pages)
        doc = fitz.open(self.pdf_path)
        self.assertEqual(doc.page_count, 3)
        doc.close()

    def test_accented_text_is_extracted_unchanged(self):
        text = "Étude de la réponse fréquentielle du système"
        pages = [{"text": text}]
        make_report(self.pdf_path, pages)
        doc = fitz.open(self.pdf_path)
        extracted = doc[0].get_text()
        self.assertIn(text, extracted)
        doc.close()

    def test_image_page_holds_one_embedded_image_of_the_requested_size(self):
        pages = [{"image": True}]
        make_report(self.pdf_path, pages)
        images = image_info(self.pdf_path)
        self.assertEqual(len(images), 1)
        self.assertGreaterEqual(images[0]["width"], 600)
        self.assertGreaterEqual(images[0]["height"], 400)

    def test_vector_chart_page_holds_drawings_and_no_embedded_image(self):
        pages = [{"vector_chart": True}]
        make_report(self.pdf_path, pages)
        images = image_info(self.pdf_path)
        self.assertEqual(len(images), 0)
        doc = fitz.open(self.pdf_path)
        drawings = doc[0].get_drawings()
        self.assertGreater(len(drawings), 0)
        doc.close()

    def test_logo_is_a_small_embedded_image(self):
        pages = [{"logo": True}]
        make_report(self.pdf_path, pages)
        images = image_info(self.pdf_path)
        self.assertEqual(len(images), 1)
        self.assertLessEqual(images[0]["width"], 50)
        self.assertLessEqual(images[0]["height"], 50)

    def test_caption_is_found_below_the_figure(self):
        pages = [{"image": True, "caption": "Figure 1 - Courbe de réponse"}]
        make_report(self.pdf_path, pages)
        doc = fitz.open(self.pdf_path)
        page = doc[0]
        caption_rect = page.search_for("Figure 1")[0]
        image_rects = [img["bbox"] for img in page.get_image_info()]
        self.assertTrue(caption_rect.y0 > image_rects[0][3])
        doc.close()

    def test_font_size_is_applied(self):
        pages = [{"text": "Test", "font_size": 14}]
        make_report(self.pdf_path, pages)
        doc = fitz.open(self.pdf_path)
        spans = doc[0].get_text("dict")["blocks"][0]["lines"][0]["spans"]
        self.assertEqual(spans[0]["size"], 14)
        doc.close()

    def test_make_report_writes_only_the_given_path(self):
        pages = [{"text": "Test"}]
        make_report(self.pdf_path, pages)
        files_in_dir = list(self.test_dir.glob("*"))
        self.assertEqual(len(files_in_dir), 1)
        self.assertEqual(files_in_dir[0].name, "test_report.pdf")

    def test_empty_pages_list(self):
        pages = []
        with self.assertRaises(ValueError) as context:
            make_report(self.pdf_path, pages)
        self.assertIn("zero pages", str(context.exception))

    def test_invalid_page_data_raises(self):
        pages = [{"invalid_key": True}]
        make_report(self.pdf_path, pages)
        doc = fitz.open(self.pdf_path)
        self.assertEqual(doc.page_count, 1)
        doc.close()


if __name__ == "__main__":
    unittest.main()
