"""
Offline tests for the audience parameterisation: the three profiles resolve to the
right font floor, the right equation allowance and the right content-slide count for
the same duration, and the legibility gate that replaces the bullet cap fails a 14 pt
body run under `field` while letting the same size through in a caption frame.
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _fixtures as fx  # noqa: E402

import talk_rules as rules  # noqa: E402
import talk_validate as tv  # noqa: E402


class TestProfiles(unittest.TestCase):
    def test_font_floors(self):
        self.assertEqual(rules.audience_profile("field")["font_floor_pt"], 16.0)
        self.assertEqual(rules.audience_profile("academic")["font_floor_pt"], 16.0)
        self.assertEqual(rules.audience_profile("public")["font_floor_pt"], 20.0)

    def test_captions_may_go_to_fourteen_for_an_academic_audience(self):
        self.assertEqual(rules.audience_profile("field")["caption_floor_pt"], 14.0)
        self.assertEqual(rules.audience_profile("public")["caption_floor_pt"], 18.0)

    def test_equation_allowance_differs(self):
        self.assertIn("quantity", rules.audience_profile("field")["equations"])
        self.assertIn("one or two", rules.audience_profile("academic")["equations"])
        self.assertIn("none", rules.audience_profile("public")["equations"])

    def test_only_the_public_column_caps_bullets(self):
        self.assertIsNone(rules.audience_profile("field")["bullet_cap"])
        self.assertEqual(rules.audience_profile("public")["bullet_cap"], 5)

    def test_an_unknown_audience_raises_rather_than_defaulting(self):
        with self.assertRaises(ValueError):
            rules.audience_profile("executives")

    def test_the_public_audience_speaks_fewer_words_per_slide(self):
        self.assertEqual(rules.audience_profile("field")["words_per_content_slide"], 130.0)
        self.assertLess(rules.audience_profile("public")["words_per_content_slide"], 130.0)

    def test_the_public_ranking_drops_the_equation(self):
        self.assertIn("equation", rules.audience_profile("field")["preferred_form"])
        self.assertNotIn("equation", rules.audience_profile("public")["preferred_form"])
        self.assertEqual(rules.preferred_form("field", ["prose", "equation"]), "equation")
        self.assertEqual(rules.preferred_form("public", ["prose", "equation"]), "prose")
        self.assertEqual(rules.preferred_form("field", ["prose", "table", "figure"]),
                         "figure")


class TestContract(unittest.TestCase):
    def test_the_same_duration_gives_the_same_content_count_across_audiences(self):
        # The cadence formula is audience-independent; what the audience changes is
        # how much fits ON a slide, not how many slides the slot affords.
        field = rules.build_contract("field", 13, "pptx", "4:3", "a4", n_thanks=0)
        public = rules.build_contract("public", 13, "pptx", "4:3", "a4", n_thanks=0)
        self.assertEqual(field["shape"]["n_content"], public["shape"]["n_content"])
        self.assertNotEqual(field["font_floor_pt"], public["font_floor_pt"])

    def test_a_longer_slot_buys_more_content_slides_and_more_words(self):
        short = rules.build_contract("field", 13, "pptx", "16:9", "slide")
        long = rules.build_contract("field", 20, "pptx", "16:9", "slide")
        self.assertGreater(long["shape"]["n_content"], short["shape"]["n_content"])
        self.assertGreater(long["budget"]["target_words"], short["budget"]["target_words"])

    def test_the_contract_block_states_the_numbers_it_computed(self):
        text = rules.format_contract(
            rules.build_contract("field", 13, "pptx", "4:3", "a4", n_thanks=0)
        )
        self.assertIn("n_content   = 12", text)
        self.assertIn("16 pt body", text)
        self.assertIn("figure > table > equation > prose", text)

    def test_the_canvas_comes_from_the_aspect_answer(self):
        self.assertEqual(rules.aspect_size_in("4:3"), (10.0, 7.5))
        self.assertEqual(rules.aspect_size_in("16:9"), (13.333, 7.5))
        # 9:16 is portrait, not a typo for 16:9.
        self.assertEqual(rules.aspect_size_in("9:16"), (7.5, 13.333))


class TestLegibilityGate(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def _deck(self, name, body):
        path = os.path.join(self.dir, name)
        fx.build_pptx(path, [{"body": body, "notes": "x"}])
        return path

    def test_fourteen_point_body_fails_under_field(self):
        deck = self._deck("small.pptx", fx.sp_xml("Body 1", "dense text", sz=1400))
        problems, _ = tv.check_legibility(deck, "field")
        self.assertTrue(any("below the 16 pt floor" in p for p in problems))

    def test_the_same_size_passes_in_a_caption_frame(self):
        deck = self._deck("cap.pptx", fx.sp_xml("Figure caption", "Fig. 1", sz=1400))
        problems, _ = tv.check_legibility(deck, "field")
        self.assertEqual(problems, [])

    def test_sixteen_point_fails_for_a_public_audience(self):
        deck = self._deck("pub.pptx", fx.sp_xml("Body 1", "text", sz=1600))
        self.assertEqual(tv.check_legibility(deck, "field")[0], [])
        problems, _ = tv.check_legibility(deck, "public")
        self.assertTrue(any("below the 20 pt floor" in p for p in problems))

    def test_an_italic_run_is_treated_as_a_caption(self):
        # A generator names its shapes automatically ("Text 7"), so the exemption
        # cannot rest on the name; the design system sets captions in italic.
        body = fx.sp_xml("Text 7", "Fig. 1  station layout", sz=1400).replace(
            'b="0"', 'b="0" i="1"'
        )
        deck = self._deck("italic.pptx", body)
        problems, _ = tv.check_legibility(deck, "field")
        self.assertEqual(problems, [])

    def test_the_slide_number_placeholder_is_not_body_text(self):
        body = (
            '<p:sp><p:nvSpPr><p:cNvPr id="8" name="Slide Number Placeholder 0"/>'
            '<p:nvPr><p:ph type="sldNum"/></p:nvPr></p:nvSpPr><p:txBody><a:p>'
            '<a:r><a:rPr sz="1400"/><a:t>3</a:t></a:r></a:p></p:txBody></p:sp>'
        )
        deck = self._deck("sldnum.pptx", body)
        problems, _ = tv.check_legibility(deck, "field")
        self.assertEqual(problems, [])

    def test_autofit_shrinking_is_flagged_for_a_visual_check(self):
        deck = self._deck("fit.pptx", fx.sp_xml("Body 1", "text", sz=1800, autofit=True))
        problems, warnings = tv.check_legibility(deck, "field")
        self.assertEqual(problems, [])
        self.assertTrue(any("autofit" in w for w in warnings))


if __name__ == "__main__":
    unittest.main(verbosity=2)
