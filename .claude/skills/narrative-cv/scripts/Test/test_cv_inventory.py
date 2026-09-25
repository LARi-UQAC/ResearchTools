"""
Offline tests for cv_inventory.py: validation, dedup, dry-run vs --yes writes,
filters, and staleness stats. No network, every inventory a tempfile fixture.
"""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import cv_inventory  # noqa: E402


def _item(**overrides):
    base = {
        "id": "otis2024exo",
        "source": "scopus",
        "kind": "publication",
        "category": "publications",
        "title": "An exoskeleton control paper",
        "doi": "10.1109/example.2024",
        "date": "2024-06",
        "role": "corresponding author",
        "contribution_summary": "Proposed a predictive control law for a lower-limb exoskeleton.",
        "clienteles": ["milieu_academique"],
    }
    base.update(overrides)
    return base


class TestValidateItem(unittest.TestCase):
    def setUp(self):
        self.categories = {"publications", "mentorat"}
        self.clienteles = {"milieu_academique", "grand_public"}

    def test_valid_item_passes(self):
        cv_inventory.validate_item(_item(), self.categories, self.clienteles)

    def test_missing_key_raises(self):
        item = _item()
        del item["title"]
        with self.assertRaises(cv_inventory.InventoryError):
            cv_inventory.validate_item(item, self.categories, self.clienteles)

    def test_unknown_category_raises(self):
        item = _item(category="not-a-real-category")
        with self.assertRaises(cv_inventory.InventoryError):
            cv_inventory.validate_item(item, self.categories, self.clienteles)

    def test_malformed_date_raises(self):
        item = _item(date="June 2024")
        with self.assertRaises(cv_inventory.InventoryError):
            cv_inventory.validate_item(item, self.categories, self.clienteles)

    def test_unknown_clientele_raises(self):
        item = _item(clienteles=["not-a-real-clientele"])
        with self.assertRaises(cv_inventory.InventoryError):
            cv_inventory.validate_item(item, self.categories, self.clienteles)

    def test_empty_clienteles_raises(self):
        item = _item(clienteles=[])
        with self.assertRaises(cv_inventory.InventoryError):
            cv_inventory.validate_item(item, self.categories, self.clienteles)


class TestAddItem(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "inventory.yaml"

    def test_dry_run_does_not_write(self):
        result = cv_inventory.add_item(self.path, _item(), yes=False)
        self.assertEqual(result["status"], "dry_run")
        self.assertFalse(self.path.exists())

    def test_yes_writes_and_is_loadable(self):
        cv_inventory.add_item(self.path, _item(), yes=True)
        inventory = cv_inventory.load_inventory(self.path)
        self.assertEqual(len(inventory["items"]), 1)
        self.assertEqual(inventory["items"][0]["id"], "otis2024exo")

    def test_duplicate_id_is_reported_not_appended(self):
        cv_inventory.add_item(self.path, _item(), yes=True)
        result = cv_inventory.add_item(self.path, _item(), yes=True)
        self.assertEqual(result["status"], "duplicate")
        inventory = cv_inventory.load_inventory(self.path)
        self.assertEqual(len(inventory["items"]), 1)

    def test_duplicate_doi_with_different_id_is_still_caught(self):
        cv_inventory.add_item(self.path, _item(id="a"), yes=True)
        result = cv_inventory.add_item(self.path, _item(id="b"), yes=True)
        self.assertEqual(result["status"], "duplicate")

    def test_invalid_item_raises_before_touching_the_file(self):
        with self.assertRaises(cv_inventory.InventoryError):
            cv_inventory.add_item(self.path, _item(category="bogus"), yes=True)
        self.assertFalse(self.path.exists())


class TestListAndStats(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "inventory.yaml"
        cv_inventory.add_item(self.path, _item(id="pub2022", date="2022", added="2022-01-01"), yes=True)
        cv_inventory.add_item(
            self.path,
            _item(
                id="mentor2024", doi=None, kind="non_publication", category="mentorat",
                date="2024", source="manual", clienteles=["grand_public"],
            ),
            yes=True,
        )

    def test_list_filters_by_category(self):
        items = cv_inventory.list_items(self.path, category="mentorat")
        self.assertEqual([i["id"] for i in items], ["mentor2024"])

    def test_list_filters_by_clientele(self):
        items = cv_inventory.list_items(self.path, clientele="grand_public")
        self.assertEqual([i["id"] for i in items], ["mentor2024"])

    def test_list_filters_by_since(self):
        items = cv_inventory.list_items(self.path, since="2023")
        self.assertEqual([i["id"] for i in items], ["mentor2024"])

    def test_stats_counts_by_kind_and_category(self):
        summary = cv_inventory.stats(self.path)
        self.assertEqual(summary["total"], 2)
        self.assertEqual(summary["by_kind"]["publication"], 1)
        self.assertEqual(summary["by_kind"]["non_publication"], 1)
        # pub2022 is the only scopus-sourced item in this fixture, added 2022-01-01.
        self.assertEqual(summary["most_recent_scopus_added"], "2022-01-01")
        self.assertGreater(summary["days_since_scopus_refresh"], 365)

    def test_stats_reports_no_scopus_refresh_when_none_recorded(self):
        # both items above have source overridden to manual/scopus but with a
        # forced "added" for the scopus one via the fixture default (today);
        # this test targets the pure "no scopus item at all" branch.
        path = Path(self.tmp.name) / "manual_only.yaml"
        cv_inventory.add_item(
            path,
            _item(id="m1", doi=None, kind="non_publication", category="mentorat", source="manual"),
            yes=True,
        )
        summary = cv_inventory.stats(path)
        self.assertIsNone(summary["most_recent_scopus_added"])
        self.assertIsNone(summary["days_since_scopus_refresh"])


class TestMarkUsed(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "inventory.yaml"
        cv_inventory.add_item(self.path, _item(), yes=True)

    def test_unknown_id_raises(self):
        with self.assertRaises(cv_inventory.InventoryError):
            cv_inventory.mark_used(self.path, "no-such-id", "FRQNT-etablissement-2026", yes=True)

    def test_dry_run_does_not_write(self):
        result = cv_inventory.mark_used(self.path, "otis2024exo", "FRQNT-etablissement-2026", yes=False)
        self.assertEqual(result["status"], "dry_run")
        inventory = cv_inventory.load_inventory(self.path)
        self.assertEqual(inventory["items"][0]["used_in"], [])

    def test_marking_twice_is_idempotent(self):
        cv_inventory.mark_used(self.path, "otis2024exo", "FRQNT-etablissement-2026", yes=True)
        result = cv_inventory.mark_used(self.path, "otis2024exo", "FRQNT-etablissement-2026", yes=True)
        self.assertEqual(result["status"], "already_marked")
        inventory = cv_inventory.load_inventory(self.path)
        self.assertEqual(inventory["items"][0]["used_in"], ["FRQNT-etablissement-2026"])


class TestLoadInventoryRobustness(unittest.TestCase):
    def test_missing_file_returns_empty_inventory(self):
        inventory = cv_inventory.load_inventory("/no/such/inventory.yaml")
        self.assertEqual(inventory["items"], [])

    def test_malformed_inventory_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.yaml"
            path.write_text("- just\n- a\n- list\n", encoding="utf-8")
            with self.assertRaises(cv_inventory.InventoryError):
                cv_inventory.load_inventory(path)


if __name__ == "__main__":
    unittest.main()
