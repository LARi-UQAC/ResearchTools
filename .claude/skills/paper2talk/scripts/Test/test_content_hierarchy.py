"""
Offline tests for the content-hierarchy enforcement: a slide of rounded rectangles
holding bullets is text-only, the same slide passes once a chart is added, a matrix
of shapes counts as an exhibit while a decorative chip row does not, and exhibit
coverage matches subject keywords rather than filenames.
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _fixtures as fx  # noqa: E402

import talk_model as tm  # noqa: E402
import talk_notes as tn  # noqa: E402
import talk_validate as tv  # noqa: E402

CARDS_OF_BULLETS = (
    fx.sp_xml("Card 1", "first point", sz=1600)
    + fx.sp_xml("Card 2", "second point", sz=1600)
    + fx.sp_xml("Card 3", "third point", sz=1600)
)


class TestTextOnlySlides(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def _deck(self, name, body):
        path = os.path.join(self.dir, name)
        fx.build_pptx(path, [{"body": body, "notes": "x"}])
        return path

    def test_a_deck_of_tidy_cards_is_flagged(self):
        deck = self._deck("cards.pptx", CARDS_OF_BULLETS)
        warnings = tv.check_text_only(deck)
        self.assertTrue(any("text-only content slide" in w for w in warnings))

    def test_the_same_slide_passes_once_a_chart_is_added(self):
        deck = self._deck("chart.pptx", CARDS_OF_BULLETS + fx.graphic_frame_xml())
        self.assertEqual(tv.check_text_only(deck), [])

    def test_a_picture_counts(self):
        deck = self._deck("pic.pptx", CARDS_OF_BULLETS + fx.pic_xml())
        self.assertEqual(tv.check_text_only(deck), [])

    def test_an_equation_run_counts(self):
        deck = self._deck("eq.pptx", CARDS_OF_BULLETS + fx.equation_run_xml())
        self.assertEqual(tv.check_text_only(deck), [])

    def test_chrome_slides_are_not_judged(self):
        path = os.path.join(self.dir, "chrome.pptx")
        fx.build_pptx(path, [{"body": CARDS_OF_BULLETS, "notes": "x"}])
        model = fx.model([{"n": 1, "kind": "title", "title": "T", "blocks": [],
                           "notes": ""}])
        self.assertEqual(tv.check_text_only(path, model), [])


class TestModelLevelHierarchy(unittest.TestCase):
    def test_a_matrix_is_an_exhibit_and_a_chip_row_is_not(self):
        matrix_slide = {"n": 1, "kind": "content", "title": "Confusion",
                        "blocks": [{"kind": "matrix", "rows": [[0.9, 0.1]],
                                    "keywords": ["confusion"]}],
                        "notes": "the confusion matrix is nearly diagonal"}
        chips_slide = {"n": 2, "kind": "content", "title": "States",
                       "blocks": [{"kind": "chips",
                                   "items": [{"label": "low", "color": "2E7D32"}]}],
                       "notes": "three states"}
        problems = tm.validate_model(fx.model([matrix_slide]))
        self.assertEqual(problems, [])
        problems = tm.validate_model(fx.model([chips_slide]))
        self.assertTrue(any("text-only content slide" in p for p in problems))

    def test_prose_is_the_last_resort_in_the_ranking(self):
        import talk_rules as rules
        self.assertEqual(rules.CONTENT_HIERARCHY[-1], "prose")
        self.assertEqual(rules.CONTENT_HIERARCHY[0], "figure")


class TestExhibitCoverage(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def test_coverage_fails_when_no_keyword_appears_in_the_notes(self):
        model = fx.model([{"n": 1, "kind": "content", "title": "A",
                           "blocks": [{"kind": "figure", "asset": "fig5_evolution.png",
                                       "keywords": ["blink", "interval"]}],
                           "notes": "we then move to the results"}])
        problems = tm.validate_model(model)
        self.assertTrue(any("never discussed" in p for p in problems))

    def test_a_filename_in_the_notes_does_not_count_as_coverage(self):
        deck = os.path.join(self.dir, "fn.pptx")
        fx.build_pptx(deck, [{"body": fx.pic_xml(), "notes": "fig5_evolution.png"}])
        model = fx.model([{"n": 1, "kind": "content", "title": "A",
                           "blocks": [{"kind": "figure", "asset": "fig5_evolution.png",
                                       "keywords": ["blink", "interval"]}],
                           "notes": "fig5_evolution.png"}])
        warnings = tn.coverage_warnings(tn.notes_by_slide(deck),
                                        tn.exhibits_by_slide(deck), model)
        self.assertTrue(any("never discussed" in w for w in warnings))

    def test_an_exhibit_without_keywords_is_reported_as_uncheckable(self):
        model = fx.model([{"n": 1, "kind": "content", "title": "A",
                           "blocks": [{"kind": "figure", "asset": "f.png"}],
                           "notes": "we discuss the figure at length"}])
        self.assertTrue(any("declares no keywords" in p for p in tm.validate_model(model)))


if __name__ == "__main__":
    unittest.main(verbosity=2)
