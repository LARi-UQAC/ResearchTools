"""
Offline unit tests for bib_batch.py (no network, no API key): title matching,
venue grading, and BibTeX generation invariants learned in production
(no '@' in excluded blocks, forbidden typographic characters normalized).
Run with the project Python: python .claude/skills/scopus/scripts/Test/test_bib_batch.py
"""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import bib_batch  # noqa: E402


class TestTitleMatch(unittest.TestCase):

    def test_exact_prefix_matches(self):
        title = "Energy Minimization for Disassembly of End-of-Life Electric Vehicle Batteries"
        self.assertTrue(bib_batch.title_match(title, title + " extended"))

    def test_unrelated_titles_do_not_match(self):
        self.assertFalse(bib_batch.title_match(
            "Energy Minimization for Disassembly of Electric Vehicle Batteries",
            "Feature fusion-enhanced multi-agent reinforcement learning for job shop scheduling"))

    def test_punctuation_robust(self):
        self.assertTrue(bib_batch.title_match(
            "Human-robot collaboration disassembly planning for end-of-life power batteries",
            "Human robot collaboration disassembly planning for end of life power batteries"))


class TestGradeVenue(unittest.TestCase):

    def test_ieee_transactions_grade_a(self):
        grade, publisher, approved = bib_batch.grade_venue(
            "IEEE Transactions on Automation Science and Engineering")
        self.assertEqual((grade, publisher, approved), ("A", "IEEE", True))

    def test_mdpi_grade_b(self):
        grade, _, approved = bib_batch.grade_venue("Batteries")
        self.assertEqual((grade, approved), ("B", True))

    def test_frontiers_not_approved(self):
        _, _, approved = bib_batch.grade_venue("Frontiers in Robotics and AI")
        self.assertFalse(approved)

    def test_unknown_venue_flagged(self):
        grade, _, approved = bib_batch.grade_venue("Journal of Obscure Studies")
        self.assertEqual((grade, approved), ("?", False))


class TestGenerateBib(unittest.TestCase):

    CORPUS = {
        "smith2024energy": {
            "found": True, "doi": "10.1109/TASE.2024.1", "source": "API",
            "title": "Energy-aware planning – a study…",  # en dash + ellipsis
            "authors": [{"display": "Smith, Jane"}, {"display": "Doe, John"}],
            "journal": "IEEE Transactions on Automation Science and Engineering",
            "year": "2024", "grade": "A", "citations": "10",
        },
        "conf2023paper": {
            "found": True, "doi": "10.1016/j.procir.2023.1", "source": "API",
            "title": "A conference study", "authors": "Roe, R.",
            "journal": "Procedia CIRP", "year": "2023", "grade": "B", "citations": "2",
        },
    }

    def test_entry_has_doi_and_url(self):
        bib = bib_batch.generate_bib(self.CORPUS)
        self.assertIn("doi     = {10.1109/TASE.2024.1}", bib)
        self.assertIn("url     = {https://doi.org/10.1109/TASE.2024.1}", bib)

    def test_forbidden_characters_normalized(self):
        bib = bib_batch.generate_bib(self.CORPUS)
        self.assertNotIn("–", bib)   # en dash
        self.assertNotIn("…", bib)   # ellipsis character
        self.assertIn("Energy-aware planning - a study...", bib)

    def test_conference_entry_type(self):
        bib = bib_batch.generate_bib(self.CORPUS)
        self.assertIn("@inproceedings{conf2023paper,", bib)
        self.assertIn("booktitle = {Procedia CIRP}", bib)

    def test_excluded_block_contains_no_at_sign(self):
        bib = bib_batch.generate_bib(
            self.CORPUS, excluded={"smith2024energy": "[CHECK PUBLISHER] test"})
        block = bib.split("\n\n")[0] if "EXCLUDED" in bib.split("\n\n")[0] else \
            next(b for b in bib.split("\n\n") if "EXCLUDED" in b)
        self.assertNotIn("@", block)
        self.assertIn("[at]article", block)

    def test_authors_list_flattened(self):
        bib = bib_batch.generate_bib(self.CORPUS)
        self.assertIn("author  = {Smith, Jane and Doe, John}", bib)


class TestResolveNoWeakFallback(unittest.TestCase):

    def test_non_matching_hit_stays_miss(self):
        candidates = [{"key": "k1", "source": "S", "title": "A very specific target title"}]
        fake = {"results": [{"title": "Completely different recent paper",
                             "doi": "10.9/wrong"}]}
        with mock.patch.object(bib_batch, "_run_scopus", return_value=fake), \
             mock.patch.object(bib_batch.time, "sleep"):
            corpus = bib_batch.resolve_titles(candidates)
        self.assertFalse(corpus["k1"]["found"])
        self.assertNotIn("doi", corpus["k1"])


if __name__ == "__main__":
    unittest.main(verbosity=1)