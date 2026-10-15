"""Offline tests for pdf2md_refs, using real reference entries verbatim
from the bibliography of the 162-page UQAC thesis converted this session."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pdf2md_refs import _first_author_surname, parse_numbered_references, render_ref_md

REAL_BIBLIOGRAPHY_BLOCK = """\
[171] Lin Xiao and Stephen Boyd. Fast linear iterations for distributed averaging. Systems & Control Letters, 53(1) :65–78, 2004.

[172] Jiaxin Xie. On inexact admms with relative error criteria. Computational Optimization and Applications, 71(3) :743–765, 2018.

[176] Tao Yang, Xinlei Yi, Junfeng Wu, Ye Yuan, Di Wu, Ziyang Meng, Yiguang Hong, Hong Wang, Zongli Lin, and Karl H Johansson. A survey of distributed optimization. Annual Reviews in Control, 47 :278–305, 2019."""


class TestParseNumberedReferences(unittest.TestCase):
    def test_entry_count_matches_bracket_count(self):
        entries = parse_numbered_references(REAL_BIBLIOGRAPHY_BLOCK)
        self.assertEqual(len(entries), 3)

    def test_first_entry_authors_and_title_split_correctly(self):
        entries = parse_numbered_references(REAL_BIBLIOGRAPHY_BLOCK)
        first = entries[0]
        self.assertEqual(first.number, "171")
        self.assertIn("Lin Xiao", first.authors)
        self.assertIn("Fast linear iterations", first.title)
        self.assertIn("2004", first.venue_year)

    def test_key_uses_first_author_surname_and_year(self):
        # "Lin Xiao" is Firstname=Lin, Surname=Xiao (the researcher is
        # conventionally cited as "Xiao, L."); the key must use the
        # SURNAME, not whichever name token comes first in the rendering.
        entries = parse_numbered_references(REAL_BIBLIOGRAPHY_BLOCK)
        first = entries[0]
        self.assertTrue(first.key.startswith("xiao"))
        self.assertIn("2004", first.key)

    def test_order_is_preserved_not_resorted_by_number(self):
        entries = parse_numbered_references(REAL_BIBLIOGRAPHY_BLOCK)
        self.assertEqual([e.number for e in entries], ["171", "172", "176"])

    def test_entry_with_no_second_sentence_boundary_still_returned(self):
        # Negative control: a malformed/truncated entry (no title/venue
        # split found) must still produce a partial entry, not be dropped.
        entries = parse_numbered_references("[99] A single run-on sentence with no clean split")
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].number, "99")

    def test_empty_text_yields_no_entries(self):
        self.assertEqual(parse_numbered_references(""), [])

    def test_multiline_entry_is_joined(self):
        text = "[1] Jane Author and John Coauthor.\nTitle spanning\ntwo lines. Venue, 2021."
        entries = parse_numbered_references(text)
        self.assertEqual(len(entries), 1)
        self.assertIn("Title spanning two lines", entries[0].title)

    def test_middle_initial_without_period_does_not_cause_a_false_split(self):
        # Matches mineru's own real rendering style (a middle initial has
        # no trailing period, e.g. "Karl H Johansson") -- confirmed in the
        # real bibliography fixture above, so there is nothing to misparse.
        entries = parse_numbered_references("[1] Karl H Johansson. A survey. Venue, 2019.")
        self.assertEqual(entries[0].authors, "Karl H Johansson")
        self.assertEqual(entries[0].title, "A survey")


class TestFirstAuthorSurname(unittest.TestCase):
    """Regression: mineru renders "Firstname Lastname" with no comma, so a
    naive first-token match returned the given name instead of the surname
    for every real entry in the 162-page thesis bibliography."""

    def test_two_word_first_author_uses_the_last_token_as_surname(self):
        self.assertEqual(
            _first_author_surname("Javier Alonso-Mora, Eduardo Montijano, and Daniela Rus"), "alonso-mora"
        )

    def test_three_word_first_author_with_middle_initial(self):
        self.assertEqual(_first_author_surname("Necdet Serhat Aybat, Zi Wang"), "aybat")

    def test_initials_concatenated_first_name(self):
        self.assertEqual(_first_author_surname("PG Balaji and D Srinivasan"), "balaji")

    def test_single_author_no_separator(self):
        self.assertEqual(_first_author_surname("Dimitri P Bertsekas"), "bertsekas")

    def test_two_authors_joined_only_by_and_no_comma(self):
        self.assertEqual(_first_author_surname("Nicola Bastianello and Emiliano Dall'Anese"), "bastianello")

    def test_accented_surname_preserved(self):
        self.assertEqual(_first_author_surname("Hédy Attouch, Jérôme Bolte"), "attouch")

    def test_empty_authors_is_unknown(self):
        self.assertEqual(_first_author_surname(""), "unknown")

    def test_key_uses_surname_not_given_name(self):
        entries = parse_numbered_references("[1] Javier Alonso-Mora and Daniela Rus. A paper. Venue, 2020.")
        self.assertTrue(entries[0].key.startswith("alonso-mora2020"))


class TestRenderRefMd(unittest.TestCase):
    def test_renders_one_block_per_entry_with_labeled_fields(self):
        entries = parse_numbered_references(REAL_BIBLIOGRAPHY_BLOCK)
        rendered = render_ref_md(entries)
        self.assertIn("### [171]", rendered)
        self.assertIn("**Authors:**", rendered)
        self.assertIn("**Title:**", rendered)
        self.assertIn("**Venue/Year:**", rendered)

    def test_empty_entry_list_renders_without_error(self):
        self.assertEqual(render_ref_md([]), "\n")


if __name__ == "__main__":
    unittest.main()
