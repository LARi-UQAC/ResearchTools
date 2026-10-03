"""
test_verify_titles.py - offline tests for verify_titles.py, the
anti-fabrication gate (incident 2026-09-30).

Proves: cumul labels are never mistaken for fabricated titles, extras are
scoped to their own renderer (the historical bug: a student name approving
a grant title), seed titles must match exactly, media is covered by the
D12 fix, markers/replace entries are reported not_covered rather than
checked, and the CLI's three exit codes.
"""
import contextlib
import io
import json
import tempfile
import unittest
import unittest.mock
from pathlib import Path

import _fixtures  # noqa: F401
from _fixtures import make_data_dir, settings as _settings, grant, media, implication

import wp_errors
import verify_titles


class TestSeedTitles(unittest.TestCase):
    def test_seed_exact_titles(self):
        seed = verify_titles.seed_titles("| **Projet Ancien X** | 2009 |\n")
        self.assertIn("Projet Ancien X", seed)
        self.assertNotIn("Projet", seed)


class TestFindUnapproved(unittest.TestCase):
    def test_fabrication_caught(self):
        html = "<p><strong>Centre Fictif Alpha</strong> — un texte</p><p><strong>Entreprise Inventée inc.</strong></p>"
        approved = {"Centre Fictif Alpha"}
        bad = verify_titles.find_unapproved(html, approved)
        self.assertEqual(bad, ["Entreprise Inventée inc."])

    def test_cumul_labels_ignored(self):
        html = "<p><strong>Cumul :</strong> 2 subventions au total.</p>"
        bad = verify_titles.find_unapproved(html, set())
        self.assertEqual(bad, [])


class TestApprovedTitlesScoping(unittest.TestCase):
    def test_approvals_scoped(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = make_data_dir(
                tmp,
                {
                    "config/implications_extra.yaml": "- categorie: comite\n  nom: Nom Hors Financement\n  role: Membre\n  organisation: ''\n  debut: ''\n  fin: ''\n  description: ''\n"
                },
            )
            data = {"financement": [grant()]}
            entry = {"cv_path": "financement", "renderer": "financement", "mode": "split"}
            approved = verify_titles.approved_titles(data, entry, data_dir)
            self.assertNotIn("Nom Hors Financement", approved)

    def test_services_covered(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = make_data_dir(tmp, {})
            data = {"services_communaute": [media()]}
            entry = {"cv_path": "services_communaute", "renderer": "services", "mode": "split"}
            approved = verify_titles.approved_titles(data, entry, data_dir)
            recent, history, _ = verify_titles.render_entry(entry, data, data_dir, _settings())
            bad = verify_titles.find_unapproved(recent + history, approved)
            self.assertEqual(bad, [])
            # a fabricated title in a media <strong> must still be reported
            fabricated_html = '<li><strong>Titre Inventé</strong> — lien</li>'
            self.assertEqual(verify_titles.find_unapproved(fabricated_html, approved), ["Titre Inventé"])


class TestVerifyMapping(unittest.TestCase):
    def test_verify_mapping_clean(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = make_data_dir(tmp, {})
            data = {"financement": [grant()], "implications": [implication()]}
            mapping = {
                "site": "https://portfolio.example.org/researcher",
                "ref_year": 2026,
                "recent_window": 6,
                "recent_label": "Six dernières années",
                "excluded_funding_statuses": [],
                "entries": [
                    {"cv_path": "financement", "page_id": 101, "mode": "split", "renderer": "financement", "recent_marker": "fin-r", "history_marker": "fin-h"},
                    {"cv_path": "implications", "page_id": 102, "mode": "split", "renderer": "implications", "recent_marker": "imp-r", "history_marker": "imp-h"},
                ],
            }
            report = verify_titles.verify_mapping(data, mapping, data_dir, _settings())
            self.assertEqual(report["unapproved"], [])
            self.assertEqual(report["not_covered"], [])

    def test_markers_entry_not_covered(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = make_data_dir(tmp, {})
            data = {"cv": {"notes": "x"}}
            mapping = {"entries": [{"cv_path": "cv.notes", "page_id": 103, "mode": "markers", "marker": "notes"}]}
            report = verify_titles.verify_mapping(data, mapping, data_dir, _settings())
            self.assertEqual(report["not_covered"], ["cv.notes"])
            self.assertEqual(report["unapproved"], [])


class TestCli(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.data_dir = Path(self.tmp.name) / "data"
        self.data_dir.mkdir()
        (self.data_dir / "config").mkdir()
        (self.data_dir / "config" / "mapping.yaml").write_text(
            "site: https://portfolio.example.org/researcher\n"
            "ref_year: 2026\n"
            "recent_window: 6\n"
            "recent_label: Six dernières années\n"
            "excluded_funding_statuses: []\n"
            "entries:\n"
            "  - cv_path: financement\n"
            "    page_id: 101\n"
            "    mode: split\n"
            "    renderer: financement\n"
            "    recent_marker: fin-r\n"
            "    history_marker: fin-h\n",
            encoding="utf-8",
        )
        (self.data_dir / "cihr.json").write_text(
            json.dumps({"financement": [grant()]}, ensure_ascii=False), encoding="utf-8"
        )

    def test_cli_exit_codes(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = verify_titles.main(["--data-dir", str(self.data_dir), "--json"])
        self.assertEqual(code, 0)

        with unittest.mock.patch(
            "verify_titles.render_entry",
            return_value=("<strong>Titre Inventé</strong>", "", []),
        ):
            code = verify_titles.main(["--data-dir", str(self.data_dir)])
        self.assertEqual(code, 1)

        code = verify_titles.main(
            ["--data-dir", str(self.data_dir), "--mapping", "config/nope.yaml"]
        )
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
