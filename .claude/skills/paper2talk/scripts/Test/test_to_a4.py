"""
Offline tests for to_a4.py: the scale and centring maths on A4 and Letter in both
orientations, the A4 landscape mediabox, aspect preservation, the margin guard, and
the handout grid. Needs pypdf; everything else is stdlib.
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import to_a4  # noqa: E402

A4_LONG = 841.89
A4_SHORT = 595.276


def slide_pdf(path, pages=1, size=(720.0, 540.0)):
    """A source PDF of blank slide-sized pages."""
    from pypdf import PageObject, PdfWriter

    writer = PdfWriter()
    for _ in range(pages):
        writer.add_page(PageObject.create_blank_page(width=size[0], height=size[1]))
    with open(path, "wb") as fh:
        writer.write(fh)
    return path


class TestSheetGeometry(unittest.TestCase):
    def test_a4_landscape_is_the_portrait_size_swapped(self):
        w, h = to_a4.sheet_size("a4", "landscape")
        self.assertAlmostEqual(w, A4_LONG, places=2)
        self.assertAlmostEqual(h, A4_SHORT, places=2)

    def test_letter_landscape_is_792_by_612(self):
        w, h = to_a4.sheet_size("letter", "landscape")
        self.assertAlmostEqual(w, 792.0, places=6)
        self.assertAlmostEqual(h, 612.0, places=6)

    def test_an_unknown_paper_raises(self):
        with self.assertRaises(ValueError):
            to_a4.sheet_size("a3", "portrait")


class TestPlacement(unittest.TestCase):
    def test_case_deck_scale_on_a4_landscape(self):
        # Measured on the CASE deck: 720 x 540 pt scaled 1.0499 onto A4 landscape
        # with 5 mm margins, leaving 15.2 mm at the sides.
        w, h = to_a4.sheet_size("a4", "landscape")
        scale, dx, dy = to_a4.placement(720.0, 540.0, w, h, 5.0 * to_a4.MM)
        self.assertAlmostEqual(scale, 1.0499, places=3)
        self.assertAlmostEqual(dx / to_a4.MM, 15.2, places=1)
        self.assertAlmostEqual(dy / to_a4.MM, 5.0, places=1)

    def test_the_slide_stays_centred(self):
        w, h = to_a4.sheet_size("letter", "portrait")
        scale, dx, dy = to_a4.placement(720.0, 540.0, w, h, 10.0)
        self.assertAlmostEqual(dx * 2 + 720.0 * scale, w, places=6)
        self.assertAlmostEqual(dy * 2 + 540.0 * scale, h, places=6)

    def test_the_scale_is_uniform_so_the_aspect_survives(self):
        for paper in ("a4", "letter"):
            for orientation in ("landscape", "portrait"):
                w, h = to_a4.sheet_size(paper, orientation)
                scale, _, _ = to_a4.placement(720.0, 540.0, w, h, 5.0 * to_a4.MM)
                self.assertAlmostEqual((720.0 * scale) / (540.0 * scale),
                                       720.0 / 540.0, delta=1e-6)

    def test_a_margin_larger_than_the_sheet_raises(self):
        w, h = to_a4.sheet_size("a4", "portrait")
        with self.assertRaises(ValueError):
            to_a4.placement(720.0, 540.0, w, h, w)


class TestHandout(unittest.TestCase):
    def test_grid_transposes_on_a_landscape_sheet(self):
        self.assertEqual(to_a4.grid_cells(2, "portrait"), (1, 2))
        self.assertEqual(to_a4.grid_cells(2, "landscape"), (2, 1))
        self.assertEqual(to_a4.grid_cells(6, "portrait"), (2, 3))
        self.assertEqual(to_a4.grid_cells(6, "landscape"), (3, 2))

    def test_an_unsupported_handout_raises(self):
        with self.assertRaises(ValueError):
            to_a4.grid_cells(3, "portrait")

    def test_cells_read_left_to_right_then_down(self):
        w, h = to_a4.sheet_size("a4", "portrait")
        margin = 5.0 * to_a4.MM
        _, dx0, dy0 = to_a4.placement(720.0, 540.0, w, h, margin, 2, 2, 0)
        _, dx1, dy1 = to_a4.placement(720.0, 540.0, w, h, margin, 2, 2, 1)
        _, dx2, dy2 = to_a4.placement(720.0, 540.0, w, h, margin, 2, 2, 2)
        self.assertGreater(dx1, dx0)          # cell 1 sits to the right of cell 0
        self.assertAlmostEqual(dy1, dy0, places=6)
        self.assertLess(dy2, dy0)             # cell 2 sits below, PDF y grows upward
        self.assertAlmostEqual(dx2, dx0, places=6)


class TestReflowOutput(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def test_a4_landscape_mediabox(self):
        from pypdf import PdfReader

        src = slide_pdf(os.path.join(self.dir, "src.pdf"), pages=3)
        dst = os.path.join(self.dir, "dst.pdf")
        to_a4.reflow(src, dst, "a4", "landscape", 5.0, 1, verbose=False)
        page = PdfReader(dst).pages[0]
        self.assertAlmostEqual(float(page.mediabox.width), A4_LONG, places=2)
        self.assertAlmostEqual(float(page.mediabox.height), A4_SHORT, places=2)
        self.assertEqual(len(PdfReader(dst).pages), 3)

    def test_handout_four_puts_four_slides_on_one_sheet(self):
        from pypdf import PdfReader

        src = slide_pdf(os.path.join(self.dir, "src8.pdf"), pages=8)
        dst = os.path.join(self.dir, "dst8.pdf")
        sheets = to_a4.reflow(src, dst, "a4", "landscape", 5.0, 4, verbose=False)
        self.assertEqual(sheets, 2)
        self.assertEqual(len(PdfReader(dst).pages), 2)

    def test_an_oversized_margin_exits_two(self):
        src = slide_pdf(os.path.join(self.dir, "src2.pdf"))
        dst = os.path.join(self.dir, "dst2.pdf")
        self.assertEqual(to_a4.main([src, dst, "--margin-mm", "400"]), 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
