"""
Offline tests for fig_export.py: the label repair goes into a copy and leaves the
source figure untouched, the draw.io CLI is discovered in the documented order, a
raster input is refused rather than upscaled, and the export waits for the file
instead of sleeping. The CLI itself is patched; nothing here runs draw.io.
"""
import json
import os
import struct
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fig_export as fe  # noqa: E402

SVG_WITH_MXFILE = (
    '<svg xmlns="http://www.w3.org/2000/svg" content="'
    "%3Cmxfile%3E%3Cmxcell%20value%3D%22vonyeyor%20compartiments%22%2F%3E%3C%2Fmxfile%3E"
    '"><text>vonyeyor</text></svg>'
)


def fake_png(path, w=4663, h=2435):
    with open(path, "wb") as fh:
        fh.write(b"\x89PNG\r\n\x1a\n")
        fh.write(struct.pack(">I", 13) + b"IHDR" + struct.pack(">II", w, h))
    return path


class TestFixText(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.src = os.path.join(self.dir, "fig1.svg")
        with open(self.src, "w", encoding="utf8") as fh:
            fh.write(SVG_WITH_MXFILE)

    def test_substitutions_land_in_the_copy_and_are_counted(self):
        dst = os.path.join(self.dir, "figsrc", "fig1.svg")
        counts = fe.apply_fix_text(self.src, dst,
                                   {"vonyeyor": "conveyor",
                                    "compartiments": "compartments"})
        with open(dst, encoding="utf8") as fh:
            fixed = fh.read()
        self.assertNotIn("vonyeyor", fixed)
        self.assertIn("conveyor", fixed)
        self.assertGreaterEqual(counts["vonyeyor"], 1)
        self.assertGreaterEqual(counts["compartiments"], 1)

    def test_the_embedded_mxfile_is_rewritten_too(self):
        dst = os.path.join(self.dir, "figsrc", "fig1.svg")
        fe.apply_fix_text(self.src, dst, {"vonyeyor": "conveyor"})
        with open(dst, encoding="utf8") as fh:
            fixed = fh.read()
        import urllib.parse
        payload = urllib.parse.unquote(fixed.split('content="', 1)[1].split('"', 1)[0])
        self.assertIn("conveyor", payload)
        self.assertNotIn("vonyeyor", payload)

    def test_the_source_figure_the_paper_cites_is_never_touched(self):
        dst = os.path.join(self.dir, "figsrc", "fig1.svg")
        fe.apply_fix_text(self.src, dst, {"vonyeyor": "conveyor"})
        with open(self.src, encoding="utf8") as fh:
            self.assertEqual(fh.read(), SVG_WITH_MXFILE)


class TestCliDiscovery(unittest.TestCase):
    def test_the_explicit_path_wins(self):
        with tempfile.NamedTemporaryFile(suffix=".exe", delete=False) as fh:
            explicit = fh.name
        with mock.patch.dict(os.environ, {"DRAWIO_EXE": explicit}, clear=False), \
                mock.patch.object(fe.shutil, "which", return_value="C:/on/path/drawio"):
            self.assertEqual(fe.find_drawio(explicit), explicit)

    def test_the_environment_variable_comes_before_path(self):
        with tempfile.NamedTemporaryFile(suffix=".exe", delete=False) as fh:
            env_exe = fh.name
        with mock.patch.dict(os.environ, {"DRAWIO_EXE": env_exe}, clear=False), \
                mock.patch.object(fe.shutil, "which", return_value="C:/on/path/drawio"):
            self.assertEqual(fe.find_drawio(None), env_exe)

    def test_path_is_the_last_resort(self):
        with mock.patch.dict(os.environ, {}, clear=True), \
                mock.patch.object(fe, "DEFAULT_WINDOWS_PATHS", ()), \
                mock.patch.object(fe.shutil, "which",
                                  side_effect=lambda n: "C:/path/drawio.exe"
                                  if n == "drawio" else None):
            self.assertEqual(fe.find_drawio(None), "C:/path/drawio.exe")

    def test_no_cli_at_all_returns_none_and_export_says_so(self):
        with mock.patch.dict(os.environ, {}, clear=True), \
                mock.patch.object(fe, "DEFAULT_WINDOWS_PATHS", ()), \
                mock.patch.object(fe.shutil, "which", return_value=None):
            self.assertIsNone(fe.find_drawio(None))
            with self.assertRaises(RuntimeError):
                fe.export("a.svg", "b.png")


class TestExport(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def test_a_raster_input_is_refused_rather_than_upscaled(self):
        src = fake_png(os.path.join(self.dir, "fig.png"), 571, 358)
        rc = fe.main([src, "--out", os.path.join(self.dir, "out.png")])
        self.assertEqual(rc, 2)

    def test_the_cli_is_invoked_with_scale_three_and_crop(self):
        src = os.path.join(self.dir, "fig.svg")
        with open(src, "w", encoding="utf8") as fh:
            fh.write(SVG_WITH_MXFILE)
        out = os.path.join(self.dir, "out.png")

        def fake_run(cmd, **kwargs):
            fake_png(cmd[cmd.index("-o") + 1])
            return mock.Mock(returncode=0)

        with mock.patch.object(fe, "find_drawio", return_value="drawio.exe"), \
                mock.patch.object(fe.subprocess, "run", side_effect=fake_run) as run:
            self.assertTrue(fe.export(src, out, scale=3))
        args = run.call_args[0][0]
        self.assertIn("-x", args)
        self.assertIn("--crop", args)
        self.assertEqual(args[args.index("-s") + 1], "3")

    def test_the_export_waits_for_a_stable_file_rather_than_sleeping(self):
        out = os.path.join(self.dir, "late.png")
        fake_png(out)
        with mock.patch.object(fe.time, "sleep"):
            self.assertTrue(fe.wait_for_output(out, timeout=1.0, interval=0.0))
        self.assertFalse(fe.wait_for_output(os.path.join(self.dir, "never.png"),
                                            timeout=0.0))

    def test_the_dpi_report_reads_the_png_header(self):
        out = fake_png(os.path.join(self.dir, "big.png"), 4663, 2435)
        self.assertEqual(fe.png_size(out), (4663, 2435))
        # 4663 px across 5 in is 933 DPI, comfortably over the 150 floor.
        self.assertGreater(4663 / 5.0, fe.MIN_DPI)

    def test_fix_text_map_is_read_from_json(self):
        src = os.path.join(self.dir, "fig2.svg")
        with open(src, "w", encoding="utf8") as fh:
            fh.write(SVG_WITH_MXFILE)
        mapping = os.path.join(self.dir, "typos.json")
        with open(mapping, "w", encoding="utf8") as fh:
            json.dump({"vonyeyor": "conveyor"}, fh)
        out = os.path.join(self.dir, "out2.png")

        with mock.patch.object(fe, "find_drawio", return_value="drawio.exe"), \
                mock.patch.object(fe.subprocess, "run",
                                  side_effect=lambda cmd, **kw: fake_png(
                                      cmd[cmd.index("-o") + 1])):
            rc = fe.main([src, "--out", out, "--fix-text", mapping,
                          "--figsrc", os.path.join(self.dir, "figsrc")])
        self.assertEqual(rc, 0)
        with open(os.path.join(self.dir, "figsrc", "fig2.svg"), encoding="utf8") as fh:
            self.assertIn("conveyor", fh.read())


if __name__ == "__main__":
    unittest.main(verbosity=2)
