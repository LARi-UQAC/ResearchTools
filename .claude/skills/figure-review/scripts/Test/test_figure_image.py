import sys
import tempfile
import unittest
from pathlib import Path
from typing import List, Optional

sys.path.insert(0, str(Path(__file__).parent.parent))

import fitz
from figure_image import (
    ImageError,
    contact_sheet,
    estimated_tokens,
    fit_for_model,
    main,
)


class TestFigureImage(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.test_dir = Path(self.tmpdir.name)
        self.dst_dir = self.test_dir / "out"
        self.dst_dir.mkdir()

    def tearDown(self):
        self.tmpdir.cleanup()

    def _make_flat_image(self, path: Path, w: int, h: int) -> None:
        pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, w, h), False)
        pix.clear_with(255)
        for x in range(w // 2):
            for y in range(h):
                pix.set_pixel(x, y, (0, 0, 0))
        pix.save(str(path))

    def _make_gradient_image(self, path: Path, w: int, h: int) -> None:
        pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, w, h), False)
        for x in range(w):
            for y in range(h):
                pix.set_pixel(x, y, (x * 255 // max(w - 1, 1), y * 255 // max(h - 1, 1), 128))
        pix.save(str(path))

    def test_fit_downscales_to_the_long_edge_and_never_upscales(self):
        src = self.test_dir / "large.png"
        self._make_flat_image(src, 2000, 1000)
        
        result = fit_for_model(src, self.dst_dir, 1000, 10, 85)
        
        self.assertEqual(result["width"], 1000)
        self.assertEqual(result["height"], 500)
        self.assertTrue((self.dst_dir / result["file"]).exists())

        src_small = self.test_dir / "small.png"
        self._make_flat_image(src_small, 500, 500)
        
        result_small = fit_for_model(src_small, self.dst_dir, 1000, 10, 85)
        self.assertEqual(result_small["width"], 500)
        self.assertEqual(result_small["height"], 500)

    def test_line_art_is_png_and_photo_is_jpeg(self):
        src_flat = self.test_dir / "flat.png"
        self._make_flat_image(src_flat, 100, 100)
        
        result_flat = fit_for_model(src_flat, self.dst_dir, 1000, 10, 85)
        self.assertEqual(result_flat["format"], "png")
        self.assertTrue(result_flat["file"].endswith(".png"))

        src_grad = self.test_dir / "grad.png"
        self._make_gradient_image(src_grad, 100, 100)
        
        result_grad = fit_for_model(src_grad, self.dst_dir, 1000, 10, 85)
        self.assertEqual(result_grad["format"], "jpeg")
        self.assertTrue(result_grad["file"].endswith(".jpg"))

    def test_estimated_tokens_follow_the_28_pixel_patch_formula(self):
        self.assertEqual(estimated_tokens(1092, 819), 1170)
        self.assertEqual(estimated_tokens(28, 28), 1)
        self.assertEqual(estimated_tokens(29, 29), 4)

    def test_contact_sheet_is_one_image_within_the_long_edge(self):
        files = []
        for i in range(4):
            p = self.test_dir / f"img_{i}.png"
            self._make_flat_image(p, 100, 100)
            files.append(p)
        
        dst = self.test_dir / "sheet.png"
        result = contact_sheet(files, dst, 500)
        
        self.assertTrue(dst.exists())
        self.assertLessEqual(result["width"], 500)
        self.assertLessEqual(result["height"], 500)

    def test_contact_sheet_counts_its_tiles(self):
        files = []
        for i in range(5):
            p = self.test_dir / f"tile_{i}.png"
            self._make_flat_image(p, 50, 50)
            files.append(p)
        
        dst = self.test_dir / "sheet5.png"
        result = contact_sheet(files, dst, 500)
        self.assertEqual(result["tiles"], 5)

    def test_missing_source_raises_image_error(self):
        missing = self.test_dir / "missing.png"
        with self.assertRaises(ImageError):
            fit_for_model(missing, self.dst_dir, 100, 10, 85)

    def test_empty_contact_sheet_raises_image_error(self):
        dst = self.test_dir / "empty_sheet.png"
        with self.assertRaises(ImageError):
            contact_sheet([], dst, 100)

    def test_output_stays_inside_the_destination_folder(self):
        src = self.test_dir / "src.png"
        self._make_flat_image(src, 100, 100)
        
        result = fit_for_model(src, self.dst_dir, 1000, 10, 85)
        out_path = self.dst_dir / result["file"]
        self.assertTrue(out_path.is_relative_to(self.dst_dir))


if __name__ == "__main__":
    unittest.main()
