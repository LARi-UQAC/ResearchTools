"""
Offline tests for talk_validate.py: the document-skills validator is located rather
than hardcoded (env var first, then the newest cache match), the built-in checks
fire on a dangling r:embed and on a chart with a secondary axis but no declared
axes, and the web target refuses an external URL.
"""
import os
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _fixtures as fx  # noqa: E402

import talk_validate as tv  # noqa: E402

CHART_BAD = (
    '<?xml version="1.0"?><c:chartSpace xmlns:c="http://schemas.openxmlformats.org/'
    'drawingml/2006/chart"><c:chart><c:plotArea><c:lineChart>'
    "<c:secondaryValAxis/></c:lineChart></c:plotArea></c:chart></c:chartSpace>"
)
CHART_GOOD = (
    '<?xml version="1.0"?><c:chartSpace xmlns:c="http://schemas.openxmlformats.org/'
    'drawingml/2006/chart"><c:chart><c:plotArea><c:lineChart/>'
    "<c:catAx></c:catAx><c:valAx></c:valAx></c:plotArea></c:chart></c:chartSpace>"
)


class TestPluginDiscovery(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def _cache(self, hashes):
        made = []
        for h in hashes:
            folder = os.path.join(self.dir, "document-skills", h, "skills", "pptx",
                                  "scripts", "office")
            os.makedirs(folder, exist_ok=True)
            path = os.path.join(folder, "validate.py")
            with open(path, "w", encoding="utf8") as fh:
                fh.write("# stub\n")
            made.append(path)
            time.sleep(0.01)
        return made

    def test_the_environment_variable_wins(self):
        explicit = os.path.join(self.dir, "explicit_validate.py")
        with open(explicit, "w", encoding="utf8") as fh:
            fh.write("# stub\n")
        self._cache(["aaa"])
        pattern = os.path.join(self.dir, "document-skills", "*", "skills", "pptx",
                               "scripts", "office", "validate.py")
        found = tv.find_plugin_validator({"DOCUMENT_SKILLS_PPTX": explicit}, pattern)
        self.assertEqual(found, explicit)

    def test_the_newest_cache_entry_wins_when_several_are_installed(self):
        made = self._cache(["f17010c9bb48", "b99ff01c2210"])
        newest = made[-1]
        os.utime(newest, (time.time() + 10, time.time() + 10))
        pattern = os.path.join(self.dir, "document-skills", "*", "skills", "pptx",
                               "scripts", "office", "validate.py")
        self.assertEqual(tv.find_plugin_validator({}, pattern), newest)

    def test_no_match_returns_none_so_the_builtin_checks_run(self):
        pattern = os.path.join(self.dir, "nothing", "*", "validate.py")
        self.assertIsNone(tv.find_plugin_validator({}, pattern))


class TestPackageChecks(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def test_a_dangling_relationship_is_caught(self):
        deck = os.path.join(self.dir, "dangling.pptx")
        fx.build_pptx(deck, [{"body": fx.pic_xml(), "notes": "x",
                              "media": True, "dangling": True}])
        problems = tv.check_package(deck)
        self.assertTrue(any("no relationship declares it" in p for p in problems))

    def test_a_resolved_relationship_passes(self):
        deck = os.path.join(self.dir, "ok.pptx")
        fx.build_pptx(deck, [{"body": fx.pic_xml(), "notes": "x", "media": True}])
        self.assertEqual(tv.check_package(deck), [])

    def test_a_secondary_axis_without_declared_axes_is_caught(self):
        deck = os.path.join(self.dir, "chart_bad.pptx")
        fx.build_pptx(deck, [{"body": fx.graphic_frame_xml(), "notes": "x"}],
                      charts={"chart1.xml": CHART_BAD})
        problems = tv.check_package(deck)
        self.assertTrue(any("secondary value axis" in p for p in problems))

    def test_a_chart_declaring_both_axes_passes(self):
        deck = os.path.join(self.dir, "chart_ok.pptx")
        fx.build_pptx(deck, [{"body": fx.graphic_frame_xml(), "notes": "x"}],
                      charts={"chart1.xml": CHART_GOOD})
        self.assertEqual(tv.check_package(deck), [])


class TestWebTarget(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def _html(self, name, body):
        path = os.path.join(self.dir, name)
        with open(path, "w", encoding="utf8") as fh:
            fh.write(body)
        return path

    def test_a_cdn_font_fails_the_self_containment_rule(self):
        page = self._html("cdn.html",
                          '<link href="https://api.fontshare.com/v2/css?f[]=x">')
        problems = tv.check_web(page)
        self.assertTrue(problems)
        self.assertIn("external URL", problems[0])

    def test_a_remote_image_fails(self):
        page = self._html("img.html", '<img src="http://example.org/fig.png">')
        self.assertTrue(tv.check_web(page))

    def test_a_remote_css_url_fails(self):
        page = self._html("css.html",
                          "<style>body{background:url('https://cdn.example/x.png')}</style>")
        self.assertTrue(tv.check_web(page))

    def test_an_inlined_deck_passes(self):
        page = self._html("inline.html",
                          '<img src="data:image/png;base64,iVBORw0KG"><style>'
                          "body{font-family:Calibri}</style>")
        self.assertEqual(tv.check_web(page), [])


class TestOverlaps(unittest.TestCase):
    """A caption under a logo and a heading colliding with the row beneath it are
    both bounding-box overlaps, and they were the two most frequent defects."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def _deck(self, name, body):
        path = os.path.join(self.dir, name)
        fx.build_pptx(path, [{"body": body, "notes": "x"}])
        return path

    def test_two_shapes_on_top_of_each_other_are_named(self):
        body = (fx.sp_xml("Caption", "Fig. 1", x_in=1.0, y_in=6.5, w_in=3.0, h_in=0.4)
                + fx.pic_xml("Wordmark", x_in=1.2, y_in=6.5, w_in=3.0, h_in=0.4))
        warnings = tv.check_overlaps(self._deck("overlap.pptx", body))
        self.assertTrue(warnings)
        self.assertIn("Caption", warnings[0])
        self.assertIn("Wordmark", warnings[0])

    def test_shapes_side_by_side_do_not_trip_it(self):
        body = (fx.sp_xml("Left", "a", x_in=0.5, y_in=2.0, w_in=4.0, h_in=1.0)
                + fx.sp_xml("Right", "b", x_in=5.0, y_in=2.0, w_in=4.0, h_in=1.0))
        self.assertEqual(tv.check_overlaps(self._deck("apart.pptx", body)), [])

    def test_a_touching_edge_is_not_an_overlap(self):
        body = (fx.sp_xml("Top", "a", x_in=1.0, y_in=1.0, w_in=4.0, h_in=1.0)
                + fx.sp_xml("Below", "b", x_in=1.0, y_in=2.0, w_in=4.0, h_in=1.0))
        self.assertEqual(tv.check_overlaps(self._deck("touch.pptx", body)), [])

    def test_a_sliver_overlap_stays_below_the_tolerance(self):
        # Text frames are wider than their glyphs, so a few percent is normal.
        body = (fx.sp_xml("A", "a", x_in=1.0, y_in=1.0, w_in=4.0, h_in=1.0)
                + fx.sp_xml("B", "b", x_in=1.0, y_in=1.95, w_in=4.0, h_in=1.0))
        self.assertEqual(tv.check_overlaps(self._deck("sliver.pptx", body)), [])


class TestPaletteAndSize(unittest.TestCase):
    def test_a_triad_that_differs_only_in_hue_is_flagged(self):
        # #C0392B and #0A7930 sit at the same relative luminance (0.143 / 0.140):
        # red and green of one lightness carry no information for roughly one man
        # in twelve, nor on a washed-out projector.
        warnings = tv.check_palette({"s1": "C0392B", "s2": "0A7930", "s3": "F1C40F"})
        self.assertTrue(any("s1" in w and "s2" in w for w in warnings))

    def test_the_case_deck_triad_is_flagged_and_that_is_a_real_finding(self):
        # Measured on the delivered deck: green 0.155, amber 0.258, red 0.108. The
        # green and the red sit 0.047 apart, so the two classes that matter most
        # (safe against danger) are the pair a colour-blind viewer cannot separate.
        warnings = tv.check_palette({"s1": "2E7D32", "s2": "C57A00", "s3": "B3221F"})
        self.assertTrue(any("s1" in w and "s3" in w for w in warnings))

    def test_the_recommended_triad_passes(self):
        # green 0.155, amber 0.582, red 0.052 - separated in lightness, so the
        # classes survive greyscale, projection and colour blindness.
        self.assertEqual(tv.check_palette({"s1": "2E7D32", "s2": "F1C40F",
                                           "s3": "7B1E1E"}), [])

    def test_a_triad_separated_in_lightness_passes(self):
        self.assertEqual(tv.check_palette({"s1": "2E7D32", "s2": "F1C40F",
                                           "s3": "7B1E1E"}), [])

    def test_an_absent_triad_is_not_an_error(self):
        self.assertEqual(tv.check_palette({}), [])

    def test_an_oversized_deck_is_reported(self):
        path = os.path.join(tempfile.mkdtemp(), "big.pptx")
        fx.build_pptx(path, [{"body": "", "notes": "x"}])
        self.assertEqual(tv.check_size(path), [])
        self.assertTrue(tv.check_size(path, max_mb=0.000001))


class TestMainDispatch(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def test_the_web_mode_exit_code_follows_the_finding(self):
        bad = os.path.join(self.dir, "bad.html")
        with open(bad, "w", encoding="utf8") as fh:
            fh.write('<script src="https://cdn.example/x.js"></script>')
        self.assertEqual(tv.main(["--web", bad]), 1)

    def test_the_beamer_mode_hands_off_to_latex(self):
        self.assertEqual(tv.main(["--beamer", "main.tex"]), 0)

    def test_a_clean_deck_passes_the_builtin_path(self):
        deck = os.path.join(self.dir, "clean.pptx")
        fx.build_pptx(deck, [{"body": fx.pic_xml() + fx.sp_xml(sz=1600), "notes": "x",
                              "media": True}])
        with mock.patch.object(tv, "find_plugin_validator", return_value=None):
            self.assertEqual(tv.main([deck, "--original", "gabarit.pptx"]), 0)

    def test_a_deck_below_the_font_floor_fails(self):
        deck = os.path.join(self.dir, "small.pptx")
        fx.build_pptx(deck, [{"body": fx.pic_xml() + fx.sp_xml("Body 1", "t", sz=1200),
                              "notes": "x", "media": True}])
        with mock.patch.object(tv, "find_plugin_validator", return_value=None):
            self.assertEqual(tv.main([deck, "--audience", "field"]), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
