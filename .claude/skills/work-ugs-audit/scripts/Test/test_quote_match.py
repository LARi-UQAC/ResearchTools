"""
Tests of quote_match.py (review round 2, item 1): the three tiers of quote verification, each failing case the
reviewer listed, and the negative control. Every text is synthetic (R34); no model runs (R21).
"""

import sys
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS))

import quote_match  # noqa: E402

SETTINGS = {"min_chars": 12, "min_words": 3, "min_word_share": 0.9, "window_factor": 1.3, "page_window": 1,
            "max_words": 24}


def check(quote, page, settings=SETTINGS):
    """Verify a quote against one synthetic page, named as page 1."""
    return quote_match.verify_element(quote, 1, [page], settings)


class TestKeyTier(unittest.TestCase):
    def test_identical_text_is_verified_by_the_key_tier(self):
        result = check("La méthode retenue est décrite ici.", "La méthode retenue est décrite ici.")
        self.assertTrue(result["verified"])
        self.assertEqual(result["tier"], "key")

    def test_bold_and_italic_markup_in_the_page_is_ignored(self):
        result = check("the method was chosen here", "The **method** was *chosen* here")
        self.assertEqual(result["tier"], "key")

    def test_backslash_escapes_are_ignored(self):
        result = check("the value is 3 units", "the value is 3 \\* units")
        self.assertEqual(result["tier"], "key")

    def test_table_pipes_against_plain_text(self):
        result = check("temperature moteur mesurée", "| temperature | moteur | mesurée |")
        self.assertEqual(result["tier"], "key")

    def test_bullets_and_list_markers_are_ignored(self):
        result = check("premier point retenu", "- premier point\n- retenu")
        self.assertEqual(result["tier"], "key")

    def test_html_line_breaks_are_ignored(self):
        result = check("premier point retenu", "premier point<br>retenu")
        self.assertEqual(result["tier"], "key")

    def test_ligatures_match_their_letters(self):
        result = check("the first final proof", "the ﬁrst ﬁnal proof")
        self.assertEqual(result["tier"], "key")

    def test_case_is_ignored(self):
        result = check("the method was chosen", "THE METHOD WAS CHOSEN")
        self.assertEqual(result["tier"], "key")

    def test_soft_hyphen_and_zero_width_characters_are_ignored(self):
        result = check("the method was chosen", "the me­thod was​ chosen")
        self.assertEqual(result["tier"], "key")

    def test_a_real_hyphen_at_a_line_wrap_is_ignored(self):
        result = check("the experiment was repeated", "the experi-\nment was repeated")
        self.assertEqual(result["tier"], "key")

    def test_en_and_em_dashes_are_ignored(self):
        result = check("temps et coût fixes", "temps – et — coût fixes")
        self.assertEqual(result["tier"], "key")

    def test_guillemets_are_ignored(self):
        result = check("le modèle retenu", "« le modèle retenu »")
        self.assertEqual(result["tier"], "key")

    def test_the_micro_sign_matches_the_greek_mu(self):
        result = check("the sample is 10 μm wide", "the sample is 10 µm wide")
        self.assertEqual(result["tier"], "key")

    def test_a_quote_below_the_minimum_length_is_not_a_key_match(self):
        result = quote_match.verify_element("the", 1, ["the cat"], SETTINGS)
        self.assertNotEqual(result["tier"], "key")


class TestElisionTier(unittest.TestCase):
    def test_an_ellipsis_joins_fragments_found_in_order(self):
        page = "Premier passage du texte, puis un long développement, enfin le troisième passage retenu."
        result = check("Premier passage du texte ... troisième passage retenu", page)
        self.assertEqual(result["tier"], "elision")

    def test_the_ellipsis_character_and_brackets_are_elisions(self):
        page = "alpha beta gamma delta fictive middle epsilon zeta eta theta"
        self.assertEqual(check("alpha beta gamma delta … epsilon zeta eta theta", page)["tier"], "elision")
        self.assertEqual(check("alpha beta gamma delta [...] epsilon zeta eta theta", page)["tier"], "elision")

    def test_fragments_out_of_order_are_refused(self):
        page = "troisième passage retenu puis premier passage du texte"
        result = check("Premier passage du texte ... troisième passage retenu", page)
        self.assertFalse(result["verified"])


class TestFuzzyTier(unittest.TestCase):
    def test_dropped_accents_are_matched_by_the_fuzzy_tier(self):
        result = check("le réseau de capteurs est calibré", "le reseau de capteurs est calibre")
        self.assertEqual(result["tier"], "fuzzy")

    def test_a_missing_word_within_the_share_is_matched(self):
        # 12 of 13 words, 0.92 of the quote: at least 0.9.
        result = check("one two three four five six seven eight nine ten eleven twelve thirteen",
                       "one two three four five six seven eight nine ten eleven twelve")
        self.assertEqual(result["tier"], "fuzzy")

    def test_words_out_of_order_are_not_fuzzy_matched(self):
        page = "alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu nu"
        result = check("nu mu lambda kappa iota theta eta zeta epsilon delta gamma beta alpha", page)
        self.assertFalse(result["verified"])


class TestPageSearch(unittest.TestCase):
    def test_a_quote_on_the_next_page_is_found_and_the_page_corrected(self):
        pages = ["Page un texte fictif.", "Page deux : la conclusion fictive retient ce point."]
        result = quote_match.verify_element("la conclusion fictive retient ce point", 1, pages, SETTINGS)
        self.assertTrue(result["verified"])
        self.assertEqual(result["page"], 2)
        self.assertTrue(result["page_corrected"])

    def test_a_quote_spanning_two_pages_is_found_in_the_join(self):
        pages = ["le début de la phrase fictive se", "termine ici sans autre texte"]
        result = quote_match.verify_element("le début de la phrase fictive se termine ici", 1, pages, SETTINGS)
        self.assertTrue(result["verified"])
        self.assertEqual(result["page"], 1)

    def test_the_named_page_wins_when_it_holds_the_quote(self):
        pages = ["texte fictif identique", "texte fictif identique"]
        result = quote_match.verify_element("texte fictif identique", 2, pages, SETTINGS)
        self.assertEqual(result["page"], 2)
        self.assertFalse(result["page_corrected"])


class TestRoundTwoLimits(unittest.TestCase):
    """Review round 2, item 2 and 3: a minimum word count in every tier, the page window, the quote cap."""

    def test_a_two_word_quote_never_verifies_by_fuzzy(self):
        result = check("fictive engine", "The fictive engine is described here.")
        self.assertFalse(result["verified"])
        self.assertIsNone(result["tier"])

    def test_a_two_word_quote_never_verifies_by_the_key_tier_either(self):
        result = check("fictiveengine", "fictiveengine")
        self.assertFalse(result["verified"])

    def test_a_quote_found_five_pages_away_is_not_accepted(self):
        pages = ["p%d filler" % n for n in range(1, 7)]
        pages[5] = "the target sentence about the fictive engine test is here"
        far = quote_match.verify_element("the target sentence about the fictive engine test", 1, pages, SETTINGS)
        self.assertFalse(far["verified"])
        near = quote_match.verify_element("the target sentence about the fictive engine test", 5, pages, SETTINGS)
        self.assertTrue(near["verified"])
        self.assertEqual(near["page"], 6)

    def test_an_over_long_quote_skips_the_fuzzy_tier(self):
        words = ["w%d" % n for n in range(30)]
        page = " ".join(words[:-1] + ["changed"])  # every word but the last one is on the page: fuzzy would match
        result = check(" ".join(words), page)
        self.assertNotIn("fuzzy", result["tiers_tried"])
        self.assertFalse(result["verified"])

    def test_an_over_long_quote_is_still_verified_by_the_key_tier(self):
        words = ["w%d" % n for n in range(30)]
        result = check(" ".join(words), " ".join(words))
        self.assertEqual(result["tier"], "key")


class TestNegativeControl(unittest.TestCase):
    def test_an_invented_sentence_is_refused_at_every_tier(self):
        page = "Le rapport décrit une mesure de température sur le moteur à deux temps."
        result = check("La conclusion affirme qu'un robot quantique a gagné la compétition mondiale", page)
        self.assertFalse(result["verified"])
        self.assertIsNone(result["tier"])
        self.assertEqual(result["tiers_tried"], ["key", "elision", "fuzzy"])


class TestSettings(unittest.TestCase):
    def test_the_settings_are_read_from_the_configuration(self):
        settings = quote_match.read_quote_settings(quote_match.default_config_path())
        self.assertEqual(settings["min_word_share"], 0.9)
        self.assertEqual(settings["window_factor"], 1.3)
        self.assertEqual(settings["min_words"], 3)
        self.assertEqual(settings["page_window"], 1)
        self.assertEqual(settings["max_words"], 24)
        self.assertGreater(settings["min_chars"], 0)

    def test_a_missing_key_is_named(self):
        import json
        import tempfile
        path = Path(tempfile.mkdtemp()) / "ugs_config.json"
        shipped = json.loads(quote_match.default_config_path().read_text(encoding="utf-8"))
        del shipped["grade.quote_min_word_share"]
        path.write_text(json.dumps(shipped), encoding="utf-8")
        with self.assertRaises(ValueError) as raised:
            quote_match.read_quote_settings(path)
        self.assertIn("grade.quote_min_word_share", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
