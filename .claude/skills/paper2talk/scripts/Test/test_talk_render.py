"""
Offline tests for talk_render.py: the backend is chosen in the documented order, a
page count that does not match the slide count fails, and --paper delegates to
to_a4 rather than duplicating the transform. No PowerPoint, no LibreOffice, no
Poppler: shutil.which, platform.system and subprocess are patched.
"""
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _fixtures as fx  # noqa: E402

import talk_render as tr  # noqa: E402


class TestBackendOrder(unittest.TestCase):
    def test_soffice_wins_when_it_is_on_path(self):
        with mock.patch.object(tr.shutil, "which", return_value="/usr/bin/soffice"), \
                mock.patch.object(tr.platform, "system", return_value="Windows"):
            self.assertEqual(tr.choose_backend(), "soffice")

    def test_windows_falls_back_to_powerpoint_com(self):
        with mock.patch.object(tr.shutil, "which", return_value=None), \
                mock.patch.object(tr.platform, "system", return_value="Windows"):
            self.assertEqual(tr.choose_backend(), "powerpoint-com")

    def test_no_backend_elsewhere(self):
        with mock.patch.object(tr.shutil, "which", return_value=None), \
                mock.patch.object(tr.platform, "system", return_value="Linux"):
            self.assertIsNone(tr.choose_backend())

    def test_the_com_call_saves_as_pdf_read_only(self):
        script = tr._powershell_com_script("C:/d.pptx", "C:/d.pdf")
        self.assertIn("Presentations.Open('C:/d.pptx', $true, $false, $false)", script)
        self.assertIn("SaveAs('C:/d.pdf', 32)", script)   # 32 = ppSaveAsPDF
        self.assertIn("ReleaseComObject", script)

    def test_no_backend_raises_a_message_naming_both(self):
        with mock.patch.object(tr, "choose_backend", return_value=None):
            with self.assertRaises(RuntimeError) as ctx:
                tr.convert_to_pdf("a.pptx", "a.pdf")
        message = str(ctx.exception)
        self.assertIn("soffice", message)
        self.assertIn("PowerPoint", message)
        self.assertIn("AF_UNIX", message)


class TestSlideCount(unittest.TestCase):
    def test_slides_are_counted_from_the_package(self):
        path = os.path.join(tempfile.mkdtemp(), "deck.pptx")
        fx.build_pptx(path, [{"body": "", "notes": "a"}, {"body": "", "notes": "b"},
                             {"body": "", "notes": "c"}])
        self.assertEqual(tr.slide_count(path), 3)


class TestMain(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.deck = os.path.join(self.dir, "deck.pptx")
        fx.build_pptx(self.deck, [{"body": "", "notes": "a"}, {"body": "", "notes": "b"}])
        self.pdf = os.path.join(self.dir, "deck.pdf")

    def test_a_short_render_exits_one(self):
        with mock.patch.object(tr, "convert_to_pdf", return_value="soffice"), \
                mock.patch.object(tr, "pdf_page_count", return_value=1), \
                mock.patch.object(tr, "rasterize", return_value=[]):
            rc = tr.main([self.deck, "--pdf", self.pdf, "--no-raster"])
        self.assertEqual(rc, 1)

    def test_a_matching_render_exits_zero(self):
        with mock.patch.object(tr, "convert_to_pdf", return_value="soffice"), \
                mock.patch.object(tr, "pdf_page_count", return_value=2):
            rc = tr.main([self.deck, "--pdf", self.pdf, "--no-raster"])
        self.assertEqual(rc, 0)

    def test_paper_delegates_to_to_a4(self):
        with mock.patch.object(tr, "convert_to_pdf", return_value="soffice"), \
                mock.patch.object(tr, "pdf_page_count", return_value=2), \
                mock.patch.object(tr.to_a4, "reflow", return_value=2) as reflow:
            rc = tr.main([self.deck, "--pdf", self.pdf, "--no-raster",
                          "--paper", "a4", "--orientation", "landscape",
                          "--margin-mm", "8", "--handout", "2"])
        self.assertEqual(rc, 0)
        args = reflow.call_args[0]
        self.assertEqual(args[2], "a4")
        self.assertEqual(args[3], "landscape")
        self.assertEqual(args[4], 8.0)
        self.assertEqual(args[5], 2)

    def test_slide_size_output_never_calls_the_reflow(self):
        with mock.patch.object(tr, "convert_to_pdf", return_value="soffice"), \
                mock.patch.object(tr, "pdf_page_count", return_value=2), \
                mock.patch.object(tr.to_a4, "reflow") as reflow:
            tr.main([self.deck, "--pdf", self.pdf, "--no-raster"])
        reflow.assert_not_called()


class TestRasterize(unittest.TestCase):
    def test_the_images_are_globbed_not_named(self):
        # pdftoppm zero-pads by page count, so qa-01.jpg exists and qa-1.jpg does not.
        out = tempfile.mkdtemp()
        for name in ("qa-01.jpg", "qa-02.jpg", "qa-10.jpg"):
            with open(os.path.join(out, name), "wb") as fh:
                fh.write(b"\xff\xd8\xff")
        with mock.patch.object(tr.subprocess, "run", return_value=mock.Mock(returncode=0)):
            images = tr.rasterize("deck.pdf", out, dpi=100)
        self.assertEqual([os.path.basename(p) for p in images],
                         ["qa-01.jpg", "qa-02.jpg", "qa-10.jpg"])

    def test_the_dpi_and_range_reach_pdftoppm(self):
        out = tempfile.mkdtemp()
        with mock.patch.object(tr.subprocess, "run",
                               return_value=mock.Mock(returncode=0)) as run:
            tr.rasterize("deck.pdf", out, dpi=150, pages="2-5")
        cmd = run.call_args[0][0]
        self.assertEqual(cmd[:4], ["pdftoppm", "-jpeg", "-r", "150"])
        self.assertEqual(cmd[cmd.index("-f") + 1], "2")
        self.assertEqual(cmd[cmd.index("-l") + 1], "5")


if __name__ == "__main__":
    unittest.main(verbosity=2)
