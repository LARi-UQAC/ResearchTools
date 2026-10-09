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


class TestFindSensitiveKeys(unittest.TestCase):
    def test_nested_sensitive_key_found(self):
        node = {"supervision": {"doctorat": [{"etudiant": "Fictif"}]}}
        hits = verify_titles.find_sensitive_keys(node, ["supervis", "etudiant"])
        self.assertTrue(any("supervision" in h for h in hits))
        self.assertTrue(any("etudiant" in h for h in hits))

    def test_clean_node_no_hits(self):
        node = {"financement": [{"titre": "Projet A", "montant": 1000}]}
        hits = verify_titles.find_sensitive_keys(node, ["supervis", "etudiant"])
        self.assertEqual(hits, [])

    def test_none_node_no_hits(self):
        self.assertEqual(verify_titles.find_sensitive_keys(None, ["supervis"]), [])


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

    def test_markers_entry_with_sensitive_key_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = make_data_dir(tmp, {})
            data = {"supervision": {"doctorat": ["Etudiant Fictif"]}}
            mapping = {
                "entries": [{"cv_path": "supervision", "page_id": 104, "mode": "markers", "marker": "sup"}]
            }
            report = verify_titles.verify_mapping(data, mapping, data_dir, _settings())
            self.assertEqual(report["not_covered"], ["supervision"])
            flagged_cv_paths = [cv_path for cv_path, _text in report["unapproved"]]
            self.assertEqual(flagged_cv_paths, ["supervision"])
            self.assertIn("doctorat", report["unapproved"][0][1])

    def test_replace_entry_with_sensitive_key_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = make_data_dir(tmp, {})
            data = {"profil": {"matricule": "A1234567"}}
            mapping = {"entries": [{"cv_path": "profil", "page_id": 105, "mode": "replace"}]}
            report = verify_titles.verify_mapping(data, mapping, data_dir, _settings())
            self.assertEqual(len(report["unapproved"]), 1)

    def test_markers_entry_with_no_sensitive_key_still_clean(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = make_data_dir(tmp, {})
            data = {"cv": {"notes": "x"}}
            mapping = {"entries": [{"cv_path": "cv.notes", "page_id": 103, "mode": "markers", "marker": "notes"}]}
            report = verify_titles.verify_mapping(data, mapping, data_dir, _settings())
            self.assertEqual(report["unapproved"], [])

    def test_denylist_missing_file_is_a_refusal(self):
        with self.assertRaises(wp_errors.WpRefusal):
            verify_titles._load_denylist(Path("/does/not/exist/sensitive_keys.json"))


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

    def test_json_report_on_refusal(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = verify_titles.main(
                ["--data-dir", str(self.data_dir), "--mapping", "config/nope.yaml", "--json"]
            )
        self.assertEqual(code, 2)
        report = json.loads(buf.getvalue())
        self.assertEqual(report["exit_code"], 2)


if __name__ == "__main__":
    unittest.main()
