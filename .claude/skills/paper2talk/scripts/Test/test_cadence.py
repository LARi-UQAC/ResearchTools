"""
Offline tests for the three-tier cadence formula: the two worked 13-minute deck
shapes, what a mis-declared tier costs, and the fact that backup slides never enter
the budget.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import talk_rules as rules  # noqa: E402


class TestWorkedShapes(unittest.TestCase):
    def test_no_dividers_gives_twelve_content_and_fifteen_total(self):
        # title + thanks + references: 13 - 1.0 = 12 content, 15 slides in all.
        shape = rules.deck_shape(13, n_title=1, n_thanks=1, n_dividers=0, n_backup=1)
        self.assertEqual(shape["n_content"], 12)
        self.assertEqual(shape["n_total"], 15)

    def test_five_dividers_gives_ten_content_and_eighteen_total(self):
        # 13 - 1.0 - 5 x 0.33 = 10 content, and 18 slides in all: the divider-bearing
        # deck runs FEWER content slides and MORE slides overall.
        shape = rules.deck_shape(13, n_title=1, n_thanks=1, n_dividers=5, n_backup=1)
        self.assertEqual(shape["n_content"], 10)
        self.assertEqual(shape["n_total"], 18)

    def test_dropping_the_thank_you_buys_back_half_a_minute(self):
        with_thanks = rules.deck_shape(13.4, n_title=1, n_thanks=1)
        without = rules.deck_shape(13.4, n_title=1, n_thanks=0)
        self.assertEqual(with_thanks["n_content"], 12)
        self.assertEqual(without["n_content"], 12)
        self.assertEqual(without["chrome_minutes"], 0.5)


class TestTierCosts(unittest.TestCase):
    def test_a_divider_costs_a_third_of_a_minute(self):
        self.assertAlmostEqual(rules.TIER_MINUTES["divider"], 1 / 3, places=6)
        self.assertAlmostEqual(rules.TIER_MINUTES["title"], 0.5, places=6)
        self.assertEqual(rules.TIER_MINUTES["backup"], 0.0)

    def test_declaring_a_divider_as_a_title_costs_the_difference(self):
        # 0.5 - 0.33 = 0.17 min of chrome, which is what a mis-declaration buys or
        # loses; it is why the tier is read from the model rather than guessed.
        as_divider = rules.deck_shape(13, n_title=1, n_thanks=1, n_dividers=1)
        as_title = rules.deck_shape(13, n_title=2, n_thanks=1, n_dividers=0)
        self.assertAlmostEqual(
            as_title["chrome_minutes"] - as_divider["chrome_minutes"], 0.1667, places=3
        )

    def test_backup_slides_never_enter_the_budget(self):
        none = rules.deck_shape(13, n_title=1, n_thanks=1, n_dividers=0, n_backup=0)
        many = rules.deck_shape(13, n_title=1, n_thanks=1, n_dividers=0, n_backup=6)
        self.assertEqual(none["n_content"], many["n_content"])
        self.assertEqual(none["chrome_minutes"], many["chrome_minutes"])
        self.assertEqual(many["n_total"] - none["n_total"], 6)

    def test_tier_word_targets_follow_the_rate(self):
        self.assertEqual(rules.tier_words("content"), 130.0)
        self.assertEqual(rules.tier_words("title"), 65.0)
        self.assertAlmostEqual(rules.tier_words("divider"), 43.33, places=2)
        self.assertEqual(rules.tier_words("backup"), 0.0)

    def test_an_unknown_tier_raises(self):
        with self.assertRaises(ValueError):
            rules.tier_words("interlude")


class TestWordBudget(unittest.TestCase):
    def test_the_rate_is_130_not_150(self):
        self.assertEqual(rules.DEFAULT_WPM, 130.0)
        budget = rules.word_budget(13, safety_margin_min=0)
        self.assertEqual(budget["slot_words"], 1690.0)
        # The same notes read at 150 wpm would claim 11.3 min for 1690 words, which
        # is the two minutes the CASE session budgeted and did not have.
        self.assertAlmostEqual(1690 / 150, 11.27, places=2)

    def test_the_default_aims_a_minute_and_a_half_under_the_slot(self):
        budget = rules.word_budget(13)
        self.assertAlmostEqual(budget["target_minutes"], 11.5, places=6)
        self.assertAlmostEqual(budget["target_words"], 1495.0, places=6)
        self.assertAlmostEqual(budget["slot_words"], 1690.0, places=6)

    def test_a_slot_shorter_than_the_margin_does_not_go_negative(self):
        self.assertEqual(rules.word_budget(1.0)["target_words"], 0.0)


class TestCadenceOverrun(unittest.TestCase):
    def test_the_case_deck_shape_is_over_and_the_number_says_so(self):
        # v2 ran 18 content slides in the same slot the formula allows 12.
        allowed = rules.content_slide_allowance(13, n_title=1, n_thanks=1, n_dividers=0)
        self.assertEqual(allowed, 12)
        self.assertGreater(18, allowed)


if __name__ == "__main__":
    unittest.main(verbosity=2)
