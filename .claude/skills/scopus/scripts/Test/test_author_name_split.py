"""
test_author_name_split - offline unit test for scopus_api._split_author_name.

Regression guard for the 2026-08-04 defect: `scopus_api.py author "Otis, Martin"` built the query
AUTHLASTNAME(Martin) AND AUTHFIRST(O), because the last whitespace token was taken as the surname.
Scopus then returned real but unrelated authors (Martin, Martins, Martin-Belloso), which reads as
"Scopus cannot identify this person" rather than "the query asked for the wrong surname".

No network, no API key: the function under test is pure string handling.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scopus_api import _split_author_name  # noqa: E402


class TestSplitAuthorName(unittest.TestCase):

    def test_comma_convention_surname_first(self):
        """'Lastname, Firstname' must yield the surname before the comma."""
        self.assertEqual(_split_author_name("Otis, Martin"), ("Otis", "M"))

    def test_comma_convention_with_middle_initials(self):
        """Middle initials after the given name must not shift the surname."""
        self.assertEqual(_split_author_name("Otis, Martin J.-D."), ("Otis", "M"))

    def test_natural_convention_firstname_first(self):
        """'Firstname Lastname' keeps the previous behaviour."""
        self.assertEqual(_split_author_name("Martin Otis"), ("Otis", "M"))

    def test_natural_convention_with_middle_name(self):
        self.assertEqual(_split_author_name("Martin J Otis"), ("Otis", "M"))

    def test_surname_only(self):
        """A bare surname yields no initial, so the caller must not add AUTHFIRST()."""
        self.assertEqual(_split_author_name("Otis"), ("Otis", ""))

    def test_comma_with_empty_given_name(self):
        """A trailing comma must not produce an initial from an empty string."""
        self.assertEqual(_split_author_name("Otis,"), ("Otis", ""))

    def test_compound_surname_with_comma(self):
        """A multi-word surname before the comma is preserved whole."""
        self.assertEqual(_split_author_name("Tchane Djogdom, Gilde Vanel"), ("Tchane Djogdom", "G"))

    def test_surrounding_whitespace_is_stripped(self):
        self.assertEqual(_split_author_name("  Otis ,  Martin  "), ("Otis", "M"))

    def test_the_two_conventions_agree(self):
        """The whole point: both orders must resolve to the same Scopus query."""
        self.assertEqual(_split_author_name("Otis, Martin"), _split_author_name("Martin Otis"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
