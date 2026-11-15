import sys
import unittest
from pathlib import Path
import json
import io
import tempfile
import shutil
from contextlib import redirect_stdout

# Put the parent folder of the Test folder (scripts/) on sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from _pdf_fixtures import make_report
import figure_extract


class TestFigureExtract(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.test_dir = Path(self.tmpdir.name)
        self.pdf_path = self.test_dir / "test.pdf"
        self.out_dir = self.test_dir / "out"
        self.out_dir.mkdir(exist_ok=True)

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_counts_and_pages_of_raster_and_vector_figures(self):
        pages = [
            {"text": "Intro", "image": True, "caption": "Figure 1: Raster"},
            {"text": "Analysis", "vector_chart": True, "caption": "Figure 2: Vector"}
        ]
        make_report(self.pdf_path, pages)
        
        # min_area_pt2: 100x100 = 10000. Raster is 600x400=240000. Vector is ~550x320 > 10000.
        # logo is 40x40=1600.
        records = figure_extract.extract(self.pdf_path, self.out_dir, 10000, 128)
        
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0]["figure_id"], "F01")
        self.assertEqual(records[0]["page"], 1)
        self.assertEqual(records[0]["source"], "raster")
        
        self.assertEqual(records[1]["figure_id"], "F02")
        self.assertEqual(records[1]["page"], 2)
        self.assertEqual(records[1]["source"], "vector")

    def test_logo_under_min_area_is_ignored(self):
        pages = [
            {"text": "Header", "logo": True}
        ]
        make_report(self.pdf_path, pages)
        
        # Logo is 40x40 = 1600 pt2. If min_area is 2000, it should be ignored.
        records = figure_extract.extract(self.pdf_path, self.out_dir, 2000, 128)
        self.assertEqual(len(records), 0)

    def test_png_files_are_written_inside_out_dir(self):
        pages = [
            {"text": "Intro", "image": True, "caption": "Figure 1"}
        ]
        make_report(self.pdf_path, pages)
        
        records = figure_extract.extract(self.pdf_path, self.out_dir, 100, 128)
        
        for rec in records:
            file_path = self.out_dir / rec["file"]
            self.assertTrue(file_path.exists())
            self.assertTrue(str(file_path).startswith(str(self.out_dir)))

    def test_ratio_of_a_full_chart_is_above_0_7(self):
        pages = [
            {"vector_chart": True}
        ]
        make_report(self.pdf_path, pages)
        
        records = figure_extract.extract(self.pdf_path, self.out_dir, 100, 128)
        self.assertEqual(len(records), 1)
        # The fixture draws lines that cover a significant area. 
        # The ratio is calculated on the rendered PNG.
        # A "full chart" in the fixture has lines spanning the width.
        # We expect a high ratio.
        self.assertGreater(records[0]["drawing_area_ratio"], 0.7)

    def test_ratio_of_a_small_chart_in_a_large_frame_is_below_0_7(self):
        # Build a 100 by 100 RGB sample as bytes, white except one dark 20 by 20 square
        width = 100
        height = 100
        n = 3
        samples = bytearray(width * height * n)
        
        # Fill with white (255)
        for i in range(len(samples)):
            samples[i] = 255
            
        # Create a dark 20x20 square at (10, 10)
        for y in range(10, 30):
            for x in range(10, 30):
                idx = (y * width + x) * n
                samples[idx] = 0
                samples[idx+1] = 0
                samples[idx+2] = 0
                
        ratio = figure_extract.drawing_area_ratio(bytes(samples), width, height, n, 128)
        # Area of dark pixels is 20*20 = 400. Total area 100*100 = 10000. Ratio 0.04
        self.assertAlmostEqual(ratio, 0.04, places=3)
        self.assertLess(ratio, 0.7)

    def test_caption_found_below_and_in_french(self):
        pages = [
            {"text": "Intro", "image": True, "caption": "Fig. 1: Image"}
        ]
        make_report(self.pdf_path, pages)
        
        records = figure_extract.extract(self.pdf_path, self.out_dir, 100, 128)
        self.assertEqual(records[0]["caption"], "Fig. 1: Image")

    def test_figure_without_caption_has_null_caption(self):
        pages = [
            {"text": "Intro", "image": True}
        ]
        make_report(self.pdf_path, pages)
        
        records = figure_extract.extract(self.pdf_path, self.out_dir, 100, 128)
        self.assertIsNone(records[0]["caption"])

    def test_raster_record_carries_pixel_size_and_vector_record_does_not(self):
        pages = [
            {"text": "Intro", "image": True, "caption": "Figure 1"},
            {"text": "Analysis", "vector_chart": True, "caption": "Figure 2"}
        ]
        make_report(self.pdf_path, pages)
        
        records = figure_extract.extract(self.pdf_path, self.out_dir, 100, 128)
        
        raster_rec = next(r for r in records if r["source"] == "raster")
        vector_rec = next(r for r in records if r["source"] == "vector")
        
        self.assertIn("pixel_size", raster_rec)
        self.assertEqual(len(raster_rec["pixel_size"]), 2)
        self.assertNotIn("pixel_size", vector_rec)

    def test_vector_record_carries_the_sizes_of_its_labels_and_raster_does_not(self):
        pages = [
            {"text": "Intro", "image": True, "caption": "Figure 1"},
            {"text": "Analysis", "vector_chart": True, "caption": "Figure 2"}
        ]
        make_report(self.pdf_path, pages)
        
        records = figure_extract.extract(self.pdf_path, self.out_dir, 100, 128)
        
        raster_rec = next(r for r in records if r["source"] == "raster")
        vector_rec = next(r for r in records if r["source"] == "vector")
        
        self.assertNotIn("text_sizes", raster_rec)
        self.assertIn("text_sizes", vector_rec)
        # The fixture adds a label "Chart" with font size 10
        self.assertIn(10, vector_rec["text_sizes"])

    def test_blank_image_has_ratio_zero(self):
        # We can test the helper function directly
        import fitz
        # Create a blank pixmap
        pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 10, 10))
        pix.clear_with(255) # White
        samples = pix.samples
        
        ratio = figure_extract.drawing_area_ratio(samples, 10, 10, 3, 128)
        self.assertEqual(ratio, 0.0)

    def test_ratio_refuses_samples_shorter_than_the_stated_size(self):
        with self.assertRaises(ValueError):
            figure_extract.drawing_area_ratio(b"\x00" * 10, 10, 10, 3, 128)
        with self.assertRaises(ValueError):
            figure_extract.drawing_area_ratio(b"", 0, 10, 3, 128)

    def test_a_vector_chart_made_of_straight_lines_is_one_figure(self):
        # Lines have a zero-width or zero-height rectangle, which PyMuPDF reports as empty.
        make_report(self.pdf_path, [{"vector_chart": True}])
        records = figure_extract.extract(self.pdf_path, self.out_dir, 100, 128)
        self.assertEqual([r["source"] for r in records], ["vector"])

    def test_stdout_never_carries_a_caption(self):
        pages = [
            {"text": "Intro", "image": True, "caption": "Figure 1: Secret Caption"}
        ]
        make_report(self.pdf_path, pages)
        
        f = io.StringIO()
        with redirect_stdout(f):
            argv = ['--pdf', str(self.pdf_path), '--out', str(self.out_dir), '--min-area', '100', '--threshold', '128']
            figure_extract.main(argv)
        
        output = f.getvalue()
        self.assertNotIn("Secret Caption", output)
        self.assertNotIn("Figure 1: Secret Caption", output)

    def test_missing_pdf_is_a_refusal(self):
        argv = ['--pdf', 'nonexistent.pdf', '--out', str(self.out_dir), '--min-area', '100', '--threshold', '128']
        # main returns 2, does not raise SystemExit
        exit_code = figure_extract.main(argv)
        self.assertEqual(exit_code, 2)


if __name__ == '__main__':
    unittest.main()
