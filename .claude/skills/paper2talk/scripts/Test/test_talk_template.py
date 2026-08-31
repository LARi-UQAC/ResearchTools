"""
Offline tests for talk_template.py: the two conversions the generator depends on
(EMU to inches, srcRect to a keep-fraction) and the object extraction, against a
synthetic .pptx built in the test. No PowerPoint, no template file, no network.
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _fixtures as fx  # noqa: E402

import talk_template as tt  # noqa: E402


class TestConversions(unittest.TestCase):
    def test_emu_to_inches(self):
        self.assertEqual(tt.emu_to_in(914400), 1.0)
        self.assertEqual(tt.emu_to_in(9144000), 10.0)
        # x=1911930 is where the CASE master crops its banner picture.
        self.assertAlmostEqual(tt.emu_to_in(1911930), 2.0909, places=4)
        self.assertIsNone(tt.emu_to_in(None))

    def test_src_rect_keeps_the_top_when_the_bottom_is_cropped(self):
        # b="71648" crops 71.648 % off the bottom, so 28.352 % of the height survives.
        keep = tt.src_rect_keep({"b": "71648"})
        self.assertAlmostEqual(keep["crop_b"], 0.71648, places=6)
        self.assertAlmostEqual(keep["keep_h"], 0.28352, places=6)
        self.assertAlmostEqual(keep["keep_w"], 1.0, places=6)

    def test_src_rect_absent_is_none(self):
        self.assertIsNone(tt.src_rect_keep({}))


class TestReadContract(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.deck = os.path.join(self.dir, "gabarit.pptx")
        body = (
            fx.pic_xml("Banner", 2.09, 0.0, 2.642, 1.124, src_rect={"b": "71648"})
            + fx.sp_xml("Title 1", "Automatic and Robotic Interaction Lab",
                        sz=1800, bold=True, algn="ctr", x_in=4.757, y_in=0.185)
        )
        fx.build_pptx(self.deck, [{"body": body, "notes": None, "media": True}],
                      master_background="bg_uqac.png")

    def test_canvas_and_aspect(self):
        c = tt.read_contract(self.deck)["canvas"]
        self.assertEqual((c["w_in"], c["h_in"]), (10.0, 7.5))
        self.assertEqual(c["aspect"], "4:3")

    def test_widescreen_canvas_is_recognised(self):
        wide = os.path.join(self.dir, "wide.pptx")
        fx.build_pptx(wide, [{"body": "", "notes": None}], sld_size_in=(13.333, 7.5))
        self.assertEqual(tt.read_contract(wide)["canvas"]["aspect"], "16:9")

    def test_objects_carry_geometry_text_and_crop(self):
        objects = tt.read_contract(self.deck)["objects"]["1"]
        pic = next(o for o in objects if o["type"] == "picture")
        self.assertAlmostEqual(pic["x_in"], 2.09, places=3)
        self.assertAlmostEqual(pic["w_in"], 2.642, places=3)
        self.assertAlmostEqual(pic["src_rect"]["keep_h"], 0.28352, places=5)
        self.assertEqual(pic["media"], "ppt/media/image1.png")

        shape = next(o for o in objects if o["type"] == "shape")
        self.assertEqual(shape["text"], "Automatic and Robotic Interaction Lab")
        self.assertEqual(shape["font_size_pt"], 18.0)
        self.assertTrue(shape["bold"])
        self.assertEqual(shape["align"], "ctr")

    def test_master_background_is_resolved_through_the_rels(self):
        contract = tt.read_contract(self.deck)
        self.assertEqual(contract["master_background"], "ppt/media/bg_uqac.png")
        self.assertEqual(contract["layouts"]["count"], 1)

    def test_extract_media_copies_bytes_out(self):
        out = os.path.join(self.dir, "assets")
        written = tt.extract_media(self.deck, out)
        self.assertTrue(written)
        with open(written[0], "rb") as fh:
            self.assertTrue(fh.read().startswith(b"\x89PNG"))


class TestLegacyPpt(unittest.TestCase):
    """The 4:3 lab gabarit shipped as a legacy binary .ppt, which no OOXML reader opens."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.legacy = os.path.join(self.dir, "Gabarit43.ppt")
        with open(self.legacy, "wb") as fh:
            fh.write(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 64)
        self.modern = os.path.join(self.dir, "Gabarit169.pptx")
        fx.build_pptx(self.modern, [{"body": "", "notes": None}])

    def test_the_format_is_read_from_the_magic_bytes_not_the_extension(self):
        self.assertTrue(tt.is_legacy_ppt(self.legacy))
        self.assertFalse(tt.is_legacy_ppt(self.modern))
        # A .ppt extension on an OOXML file is still OOXML.
        renamed = os.path.join(self.dir, "mislabelled.ppt")
        with open(self.modern, "rb") as src, open(renamed, "wb") as dst:
            dst.write(src.read())
        self.assertFalse(tt.is_legacy_ppt(renamed))

    def test_a_legacy_file_exits_two_with_an_actionable_message(self):
        import contextlib
        import io

        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            rc = tt.main([self.legacy])
        self.assertEqual(rc, 2)
        self.assertIn("--convert", err.getvalue())

    def test_convert_saves_as_pptx_and_leaves_the_original_alone(self):
        from unittest import mock

        dst = os.path.splitext(self.legacy)[0] + ".pptx"
        before = os.path.getsize(self.legacy)

        def fake_run(cmd, **kwargs):
            script = cmd[-1]
            # 24 is ppSaveAsOpenXMLPresentation; the source is opened read-only.
            assert "SaveAs(" in script and ", 24)" in script, script
            assert "$true, $false, $false" in script, script
            with open(dst, "wb") as fh:
                fh.write(b"PK\x03\x04")
            return mock.Mock(returncode=0)

        with mock.patch("subprocess.run", side_effect=fake_run):
            out = tt.convert_legacy(self.legacy)
        self.assertEqual(out, os.path.abspath(dst))
        self.assertEqual(os.path.getsize(self.legacy), before)


if __name__ == "__main__":
    unittest.main(verbosity=2)
