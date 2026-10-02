"""
test_render.py - offline tests for render.py.

Proves: RenderSettings validation (D10 - no hardcoded ref_year/window),
window_caption, the financement cumul driven by settings, non-mutation of
caller data, extras read only from the data folder (never WP_SKILL_DIR),
section exclusions covering every section including services and
distinctions (fixing the defect where only financement/implications could
be excluded), the D2 phq refusal inside render_entry, the D12 media-link
placement fix, and the render_phq contract (numbering, six-year window,
alumni ordering, owner_name parameter, required-key refusal).
"""
import copy
import tempfile
import unittest
from pathlib import Path

import _fixtures  # noqa: F401
from _fixtures import make_data_dir

import wp_errors
import render


def _settings(ref_year=2026, window=6, label="Six dernières années", excluded=()):
    return render.RenderSettings(
        ref_year=ref_year, window=window, recent_label=label, excluded_funding_statuses=tuple(excluded)
    )


def _grant(titre="Projet fictif A", debut="2024/1", fin="2026/1", statut="Obtenu", montant="100000"):
    return {
        "titre": titre,
        "type": "Subvention",
        "statut": statut,
        "role": "Chercheur principal",
        "debut": debut,
        "fin": fin,
        "sources": [{"organisme": "Organisme Fictif", "programme": "Programme Fictif", "montant_total": montant, "portion_recue": "", "competitif": "Oui"}],
        "cochercheurs": [],
    }


def _implication(nom="Comité Fictif Alpha", organisation="", categorie="comite", debut="2020/1", fin=""):
    return {
        "categorie": categorie,
        "nom": nom,
        "role": "Membre",
        "organisation": organisation,
        "debut": debut,
        "fin": fin,
        "description": "",
    }


def _media(sujet="Entrevue fictive https://example.org/a", diffuseur="Emission Fictive", date="2024/3"):
    return {"type": "media", "sujet": sujet, "diffuseur": diffuseur, "chaine": "Chaîne Fictive", "date": date}


def _entreprise(organisation="Entreprise Fictif Gamma", role="Responsable", debut="2023/1", fin="2023/6"):
    return {"type": "entreprise", "role": role, "activite": "Atelier", "organisation": organisation, "resultat": "Succès", "retombees": "Adoption", "debut": debut, "fin": fin}


def _evenement(nom="Évènement Fictif Delta", debut="2022/1", fin="2022/1"):
    return {"type": "evenement", "role": "Organisateur", "nom": nom, "debut": debut, "fin": fin}


def _prix(nom="Prix Fictif Epsilon", organisation="Organisation Fictive Zeta", fin="2024/1", montant=""):
    return {"nom": nom, "organisation": organisation, "debut": "2024/1", "fin": fin, "montant": montant, "description": ""}


def _contribution_cle(titre="Contribution fictive clé", description="Description fictive"):
    return {"titre": titre, "date": "2020/1", "description": description}


def _student(
    etudiant="Étudiant Fictif Un",
    type_diplome="Doctorat",
    statut="En cours",
    debut="2022/9",
    fin="",
    role="Directeur de recherche",
    titre_projet="Projet fictif",
    **extra,
):
    rec = {
        "etudiant": etudiant,
        "type_diplome": type_diplome,
        "statut": statut,
        "debut": debut,
        "fin": fin,
        "role": role,
        "titre_projet": titre_projet,
    }
    rec.update(extra)
    return rec


class TestRenderSettings(unittest.TestCase):
    def test_settings_required(self):
        mapping = {
            "ref_year": 2026,
            "recent_window": 6,
            "recent_label": "Six dernières années",
            "excluded_funding_statuses": [],
        }
        for key in list(mapping.keys()):
            partial = {k: v for k, v in mapping.items() if k != key}
            with self.assertRaises(wp_errors.WpRefusal) as ctx:
                render.load_render_settings(partial, "mapping.yaml")
            self.assertIn(key, str(ctx.exception))

    def test_settings_types(self):
        base = {
            "ref_year": 2026,
            "recent_window": 6,
            "recent_label": "Six dernières années",
            "excluded_funding_statuses": [],
        }
        bad_window = dict(base, recent_window=0)
        with self.assertRaises(wp_errors.WpRefusal):
            render.load_render_settings(bad_window, "mapping.yaml")
        bad_year = dict(base, ref_year="2026")
        with self.assertRaises(wp_errors.WpRefusal):
            render.load_render_settings(bad_year, "mapping.yaml")

    def test_window_caption(self):
        settings = _settings(ref_year=2030, window=5, label="Cinq dernières années")
        self.assertEqual(render.window_caption(settings), "Cinq dernières années (2026–2030)")


class TestFinancementCumul(unittest.TestCase):
    def test_cumul_counts_and_amounts(self):
        items = [_grant("Projet fictif A", "2024/1", "2026/1", "Obtenu", "100000"),
                 _grant("Projet fictif B", "2010/1", "2015/1", "Terminé", "50000")]
        recent_html, history_html = render.render_financement(items, _settings())
        self.assertIn("2 subventions au total", recent_html)
        self.assertIn("150 000", recent_html)
        self.assertIn("1 subventions", recent_html)
        self.assertIn("Projet fictif A", recent_html)
        self.assertIn("Projet fictif B", history_html)

    def test_caption_follows_settings(self):
        items = [_grant()]
        recent_html, _ = render.render_financement(items, _settings(ref_year=2030, window=6))
        self.assertIn("(2025–2030)", recent_html)
        self.assertNotIn("2021", recent_html)

    def test_no_hardcoded_window_in_source(self):
        source = Path(render.__file__).read_text(encoding="utf-8")
        self.assertNotIn("2021–2026", source)
        self.assertNotIn("2026 - 6", source)


class TestEditorialOptIn(unittest.TestCase):
    def test_editorial_texts_applied_when_opted_in(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = make_data_dir(
                tmp,
                {
                    "config/contributions.yaml": "contributions:\n  Projet fictif A: 'Texte éditorial fictif.'\n"
                },
            )
            data = {"financement": [_grant("Projet fictif A")]}
            entry = {"cv_path": "financement", "renderer": "financement", "editorial_texts": True}
            recent, _, notes = render.render_entry(entry, data, data_dir, _settings())
            self.assertIn("Texte éditorial fictif", recent)

    def test_editorial_on_without_file_notes(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = make_data_dir(tmp, {})
            data = {"financement": [_grant("Projet fictif A")]}
            entry = {"cv_path": "financement", "renderer": "financement", "editorial_texts": True}
            _, _, notes = render.render_entry(entry, data, data_dir, _settings())
            self.assertTrue(any("contributions.yaml" in n for n in notes))


class TestExtrasAndMutation(unittest.TestCase):
    def test_extras_from_data_dir_only(self):
        import unittest.mock as mock

        with tempfile.TemporaryDirectory() as tmp:
            data_dir = make_data_dir(
                tmp,
                {
                    "config/implications_extra.yaml": "- categorie: comite\n  nom: Comité Extra Fictif\n  role: Membre\n  organisation: ''\n  debut: '2020/1'\n  fin: ''\n  description: ''\n"
                },
            )
            decoy_dir = Path(tmp) / "decoy"
            decoy_dir.mkdir()
            (decoy_dir / "config").mkdir()
            (decoy_dir / "config" / "implications_extra.yaml").write_text(
                "- categorie: comite\n  nom: Decoy\n  role: Membre\n  organisation: ''\n  debut: ''\n  fin: ''\n  description: ''\n",
                encoding="utf-8",
            )
            data = {"implications": [_implication("Comité Fictif Alpha")]}
            entry = {"cv_path": "implications", "renderer": "implications"}
            with mock.patch.dict("os.environ", {"WP_SKILL_DIR": str(decoy_dir)}):
                recent, history, notes = render.render_entry(entry, data, data_dir, _settings())
            combined = recent + history
            self.assertIn("Comité Extra Fictif", combined)
            self.assertNotIn("Decoy", combined)

    def test_input_not_mutated(self):
        settings = _settings()
        for fn, items in (
            (render.render_financement, [_grant()]),
            (render.render_implications, [_implication()]),
            (render.render_services, [_media(), _entreprise(), _evenement()]),
        ):
            snapshot = copy.deepcopy(items)
            fn(items, settings)
            self.assertEqual(items, snapshot)
        distinctions_data = {"prix": [_prix()], "contributions_cles": [_contribution_cle()]}
        snapshot = copy.deepcopy(distinctions_data)
        render.render_distinctions(distinctions_data, "prix", settings)
        self.assertEqual(distinctions_data, snapshot)
        students = [_student()]
        snapshot = copy.deepcopy(students)
        render.render_phq(students, settings, "Professeure Exemple")
        self.assertEqual(students, snapshot)


class TestExclusions(unittest.TestCase):
    def test_exclusions_services_each_type(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = make_data_dir(
                tmp,
                {
                    "config/exclusions.yaml": (
                        "services_communaute:\n"
                        "  - Entrevue fictive\n"
                        "  - Entreprise Fictif Gamma\n"
                        "  - Évènement Fictif Delta\n"
                    )
                },
            )
            data = {"services_communaute": [_media(), _entreprise(), _evenement()]}
            entry = {"cv_path": "services_communaute", "renderer": "services"}
            recent, history, notes = render.render_entry(entry, data, data_dir, _settings())
            self.assertNotIn("Entrevue fictive", recent + history)
            self.assertNotIn("Entreprise Fictif Gamma", recent + history)
            self.assertNotIn("Évènement Fictif Delta", recent + history)
            self.assertTrue(any("3 dossier" in n for n in notes))

    def test_exclusions_distinctions(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = make_data_dir(
                tmp, {"config/exclusions.yaml": "distinctions:\n  - Prix Fictif Epsilon\n"}
            )
            data = {"distinctions": {"prix": [_prix()], "contributions_cles": []}}
            entry = {"cv_path": "distinctions", "renderer": "distinctions", "subkey": "prix"}
            recent, history, notes = render.render_entry(entry, data, data_dir, _settings())
            self.assertNotIn("Prix Fictif Epsilon", recent + history)

    def test_excluded_funding_status(self):
        data = {"financement": [_grant("Projet fictif A", statut="Obtenu"), _grant("Projet fictif B", statut="En cours d'évaluation")]}
        entry = {"cv_path": "financement", "renderer": "financement"}
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = make_data_dir(tmp, {})
            recent, history, notes = render.render_entry(
                entry, data, data_dir, _settings(excluded=["En cours d'évaluation"])
            )
            self.assertNotIn("Projet fictif B", recent + history)


class TestRenderEntryGuards(unittest.TestCase):
    def test_phq_refused_in_entry(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = make_data_dir(tmp, {})
            entry = {"cv_path": "financement", "renderer": "phq"}
            with self.assertRaises(wp_errors.WpRefusal) as ctx:
                render.render_entry(entry, {"financement": []}, data_dir, _settings())
            self.assertIn("ThesisTracker", str(ctx.exception))

    def test_unknown_renderer_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = make_data_dir(tmp, {})
            entry = {"cv_path": "financement", "renderer": "bogus"}
            with self.assertRaises(wp_errors.WpRefusal):
                render.render_entry(entry, {"financement": []}, data_dir, _settings())

    def test_missing_cv_path_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = make_data_dir(tmp, {})
            entry = {"cv_path": "nope", "renderer": "financement"}
            with self.assertRaises(wp_errors.WpSyncError):
                render.render_entry(entry, {"financement": []}, data_dir, _settings())

    def test_history_static_escape_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = make_data_dir(tmp, {})
            entry = {"cv_path": "financement", "renderer": "financement", "history_static": "../x.md"}
            with self.assertRaises(wp_errors.WpRefusal):
                render.render_entry(entry, {"financement": []}, data_dir, _settings())


class TestServicesMediaLink(unittest.TestCase):
    def test_media_link_outside_strong(self):
        recent, _ = render.render_services([_media()], _settings())
        self.assertNotIn('<strong><a', recent)
        import re

        for match in re.finditer(r"<strong>.*?</strong>", recent, re.DOTALL):
            self.assertNotIn("<a", match.group(0))
        self.assertIn('</strong> <a href="https://example.org/a">lien</a>', recent)


class TestPhq(unittest.TestCase):
    def test_phq_numbering_with_interrupted_gap(self):
        students = [
            _student("Étudiante Témoin Un", debut="2018/1", statut="Interrompu"),
            _student("Étudiante Témoin Deux", debut="2019/1", statut="En cours"),
        ]
        recent, history, notes = render.render_phq(students, _settings(), "Professeure Exemple")
        self.assertIn("Étudiante Témoin Deux", recent)
        self.assertNotIn("Étudiante Témoin Un", recent)
        self.assertNotIn("Étudiante Témoin Un", history)
        self.assertTrue(any("Interrompu" in n for n in notes))

    def test_phq_cumul_counts(self):
        students = [_student("Un", type_diplome="Doctorat"), _student("Deux", type_diplome="Maîtrise avec mémoire", statut="Terminé", fin="2025/1")]
        recent, _, _ = render.render_phq(students, _settings(), "Professeure Exemple")
        self.assertIn("2 supervisions au total", recent)

    def test_phq_six_year_excludes_interrupted(self):
        students = [_student("Un", statut="Interrompu", fin="2025/1")]
        recent, _, _ = render.render_phq(students, _settings(), "Professeure Exemple")
        self.assertIn("0 supervisions", recent)

    def test_phq_alumni_chronological(self):
        students = [
            _student("Récent", debut="2019/1", statut="Terminé", fin="2025/1"),
            _student("Ancien", debut="2015/1", statut="Terminé", fin="2025/2"),
        ]
        recent, _, _ = render.render_phq(students, _settings(), "Professeure Exemple")
        self.assertLess(recent.index("Ancien"), recent.index("Récent"))

    def test_phq_owner_name_parameter(self):
        students = [_student()]
        recent, _, _ = render.render_phq(students, _settings(), "Professeure Exemple")
        self.assertIn("Professeure Exemple", recent)
        source = Path(render.__file__).read_text(encoding="utf-8")
        self.assertNotIn("Otis", source)

    def test_phq_titre_professionnel_only_without_degree_title(self):
        students = [_student(type_diplome="Baccalauréat", titre_professionnel="ing.")]
        recent, _, _ = render.render_phq(students, _settings(), "Professeure Exemple")
        self.assertIn("ing.", recent)

    def test_phq_codirecteur_shown(self):
        students = [_student(codirecteur="Collègue Fictif")]
        recent, _, _ = render.render_phq(students, _settings(), "Professeure Exemple")
        self.assertIn("codirection : Collègue Fictif", recent)

    def test_phq_missing_key_refused(self):
        bad = [{"etudiant": "Sans Titre"}]
        with self.assertRaises(wp_errors.WpSyncError) as ctx:
            render.render_phq(bad, _settings(), "Professeure Exemple")
        self.assertIn("type_diplome", str(ctx.exception))
        self.assertIn("0", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
