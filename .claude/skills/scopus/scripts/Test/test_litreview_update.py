"""
Offline unit tests for litreview_update.py (no network, no API key): DOI
normalization, .bib parsing, next-update-date extraction, baseline fingerprint,
delta dedup (DOI exact + title Jaccard reused from bib_batch, plus within-list
dedup), dated output paths, and the CHANGELOG scaffold (empty delta note and the
REVIEW REQUIRED gates). Run with the project Python:
  python .claude/skills/scopus/scripts/Test/test_litreview_update.py
"""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import litreview_update as lu  # noqa: E402


class TestNormDoi(unittest.TestCase):

    def test_strips_resolver_prefix_and_lowercases(self):
        self.assertEqual(lu._norm_doi("https://doi.org/10.1109/TASE.2024.1"),
                         "10.1109/tase.2024.1")

    def test_bare_doi_unchanged_but_lowered(self):
        self.assertEqual(lu._norm_doi("10.1016/J.X.2023.5"), "10.1016/j.x.2023.5")

    def test_none_is_empty(self):
        self.assertEqual(lu._norm_doi(None), "")


class TestParseBibAndDate(unittest.TestCase):

    BIB = (
        "@article{smith2024energy,\n"
        "  author = {Smith, Jane},\n"
        "  title  = {Energy-aware disassembly planning},\n"
        "  doi    = {10.1109/TASE.2024.1},\n"
        "}\n\n"
        "@inproceedings{roe2023conf,\n"
        '  title  = {A conference study},\n'
        "  doi    = {10.1016/j.procir.2023.1},\n"
        "}\n")

    def test_parse_bib_extracts_keys_dois_titles(self):
        with tempfile.NamedTemporaryFile("w", suffix=".bib", delete=False,
                                         encoding="utf-8") as handle:
            handle.write(self.BIB)
            path = handle.name
        try:
            parsed = lu.parse_bib(path)
        finally:
            os.unlink(path)
        self.assertEqual(set(parsed["citekeys"]), {"smith2024energy", "roe2023conf"})
        self.assertIn("10.1109/tase.2024.1", parsed["dois"])
        self.assertIn("Energy-aware disassembly planning", parsed["titles"])

    def test_missing_bib_is_empty(self):
        parsed = lu.parse_bib("no_such_file_here.bib")
        self.assertEqual(parsed, {"citekeys": [], "dois": [], "titles": []})

    def test_next_update_date_extracted(self):
        tex = r"\subsection*{Metadonnees} Prochaine mise a jour recommandee : 2027-01-15."
        self.assertEqual(lu.extract_next_update_date(tex), "2027-01-15")

    def test_next_update_date_absent_is_none(self):
        self.assertIsNone(lu.extract_next_update_date("no date here"))


class TestBuildBaseline(unittest.TestCase):

    def _write(self, name, text):
        path = os.path.join(self.dir.name, name)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)
        return path

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.dir.cleanup()

    def test_baseline_merges_corpus_and_bib(self):
        corpus = {"smith2024energy": {"doi": "10.1109/TASE.2024.1",
                                      "title": "Energy-aware disassembly planning"}}
        corpus_path = self._write("corpus.json", json.dumps(corpus))
        bib_path = self._write(
            "review.bib",
            "@article{roe2023conf,\n  title = {A conference study},\n"
            "  doi = {10.1016/j.procir.2023.1},\n}\n")
        tex_path = self._write("review.tex",
                               "Prochaine mise a jour recommandee : 2027-01-15")
        baseline = lu.build_baseline(tex_path, corpus_path, bib_path)
        self.assertIn("10.1109/tase.2024.1", baseline["dois"])
        self.assertIn("10.1016/j.procir.2023.1", baseline["dois"])
        self.assertIn("smith2024energy", baseline["citekeys"])
        self.assertIn("roe2023conf", baseline["citekeys"])
        self.assertEqual(baseline["next_update_date"], "2027-01-15")


class TestComputeDelta(unittest.TestCase):

    BASELINE = {
        "dois": ["10.1109/tase.2024.1"],
        "titles": ["Human-robot collaboration disassembly planning for end-of-life power batteries"],
    }

    def test_doi_duplicate_dropped(self):
        cands = [{"key": "k1", "source": "S", "title": "Different",
                  "doi": "https://doi.org/10.1109/TASE.2024.1"}]
        self.assertEqual(lu.compute_delta(cands, self.BASELINE), [])

    def test_title_duplicate_dropped_via_jaccard(self):
        # Same paper, punctuation/casing variant, no DOI -> caught by title_match.
        cands = [{"key": "k2", "source": "S",
                  "title": "Human robot collaboration disassembly planning for end of life power batteries"}]
        self.assertEqual(lu.compute_delta(cands, self.BASELINE), [])

    def test_genuinely_new_kept(self):
        cands = [{"key": "k3", "source": "S", "title": "A brand new unrelated topic",
                  "doi": "10.1000/new.1"}]
        delta = lu.compute_delta(cands, self.BASELINE)
        self.assertEqual([c["key"] for c in delta], ["k3"])

    def test_within_list_duplicate_collapsed(self):
        cands = [
            {"key": "k3", "source": "S", "title": "A brand new topic", "doi": "10.1000/new.1"},
            {"key": "k3bis", "source": "S", "title": "Any", "doi": "10.1000/NEW.1"},
        ]
        delta = lu.compute_delta(cands, self.BASELINE)
        self.assertEqual([c["key"] for c in delta], ["k3"])


class TestPathsAndChangelog(unittest.TestCase):

    def test_dated_paths_naming(self):
        paths = lu.dated_paths(os.path.join("out", "review.tex"), date="20260721")
        self.assertTrue(paths["updated_tex"].endswith("review_up_20260721.tex"))
        self.assertTrue(paths["changelog"].endswith("review_up_20260721_CHANGELOG.md"))

    def test_changelog_empty_delta_says_no_update(self):
        text = lu.build_changelog({}, os.path.join("out", "review.tex"), date="20260721")
        self.assertIn("No new papers", text)

    def test_changelog_flags_non_approved_and_unresolved(self):
        delta = {
            "good2026paper": {"found": True, "doi": "10.1/g", "grade": "A",
                              "publisher_guess": "IEEE", "publisher_approved": True, "year": "2026"},
            "front2026paper": {"found": True, "doi": "10.2/f", "grade": "B",
                               "publisher_guess": "Frontiers", "publisher_approved": False, "year": "2026"},
            "lost2026paper": {"found": False, "doi": "", "grade": "?",
                              "publisher_approved": False, "year": "2026"},
        }
        text = lu.build_changelog(delta, os.path.join("out", "review.tex"), date="20260721")
        self.assertIn("REVIEW REQUIRED", text)
        self.assertIn("front2026paper", text)
        self.assertIn("lost2026paper", text)
        # An approved, resolved paper is not a REVIEW-REQUIRED gate item.
        review_section = text.split("## REVIEW REQUIRED", 1)[1].split("## Preemption", 1)[0]
        self.assertNotIn("good2026paper", review_section)


if __name__ == "__main__":
    unittest.main(verbosity=1)