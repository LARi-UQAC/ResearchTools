"""
Offline tests for cv_select.py: keyword extraction, scoring, ranking order,
and the empty/no-match edge cases. No network, no inventory file needed for
the pure scoring functions.
"""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import cv_inventory  # noqa: E402
import cv_select  # noqa: E402


class TestExtractKeywords(unittest.TestCase):
    def test_removes_stopwords_and_short_tokens(self):
        keywords = cv_select.extract_keywords("The exoskeleton and the predictive control of a robot")
        self.assertIn("exoskeleton", keywords)
        self.assertIn("predictive", keywords)
        self.assertIn("robot", keywords)
        self.assertNotIn("the", keywords)
        self.assertNotIn("and", keywords)
        self.assertNotIn("of", keywords)

    def test_empty_text_returns_empty_set(self):
        self.assertEqual(cv_select.extract_keywords(""), set())
        self.assertEqual(cv_select.extract_keywords(None), set())


def _item(**overrides):
    base = {
        "id": "x", "source": "scopus", "kind": "publication", "category": "publications",
        "title": "Exoskeleton control", "date": "2024", "role": "author",
        "contribution_summary": "A predictive control law for a lower-limb exoskeleton.",
        "clienteles": ["milieu_academique"], "keywords": ["exoskeleton", "predictive control"],
    }
    base.update(overrides)
    return base


class TestScoreAndRank(unittest.TestCase):
    def test_score_counts_overlap(self):
        score, matched = cv_select.score_item(_item(), {"exoskeleton", "unrelated"})
        self.assertEqual(score, 1)
        self.assertEqual(matched, ["exoskeleton"])

    def test_zero_overlap_scores_zero(self):
        score, matched = cv_select.score_item(_item(), {"quantum", "biology"})
        self.assertEqual(score, 0)
        self.assertEqual(matched, [])

    def test_rank_orders_by_score_descending(self):
        low = _item(id="low", keywords=[])
        high = _item(id="high", keywords=["exoskeleton"])
        ranked = cv_select.rank_items([low, high], {"exoskeleton"})
        self.assertEqual([r["id"] for r in ranked], ["high", "low"])

    def test_ties_break_by_date_descending(self):
        old = _item(id="old", date="2018", keywords=["exoskeleton"])
        new = _item(id="new", date="2024", keywords=["exoskeleton"])
        ranked = cv_select.rank_items([old, new], {"exoskeleton"})
        self.assertEqual([r["id"] for r in ranked], ["new", "old"])

    def test_full_ties_break_by_id_ascending(self):
        b = _item(id="b", date="2024", keywords=["exoskeleton"])
        a = _item(id="a", date="2024", keywords=["exoskeleton"])
        ranked = cv_select.rank_items([b, a], {"exoskeleton"})
        self.assertEqual([r["id"] for r in ranked], ["a", "b"])

    def test_empty_items_returns_empty_list(self):
        self.assertEqual(cv_select.rank_items([], {"exoskeleton"}), [])


class TestSelectIntegration(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "inventory.yaml"
        cv_inventory.add_item(self.path, _item(id="a", date="2020"), yes=True)
        cv_inventory.add_item(self.path, _item(id="b", date="2024"), yes=True)

    def test_select_with_criteria_text_ranks_and_caps(self):
        ranked = cv_select.select(self.path, criteria_text="This program funds exoskeleton research.", top=1)
        self.assertEqual(len(ranked), 1)
        self.assertEqual(ranked[0]["id"], "b")  # same score, most recent wins

    def test_select_with_no_criteria_still_returns_all_items(self):
        ranked = cv_select.select(self.path)
        self.assertEqual(len(ranked), 2)
        self.assertTrue(all(r["score"] == 0 for r in ranked))

    def test_select_on_empty_inventory_path_returns_empty(self):
        ranked = cv_select.select("/no/such/inventory.yaml", criteria_text="anything")
        self.assertEqual(ranked, [])


if __name__ == "__main__":
    unittest.main()
