"""
Offline tests for cv_build.py: LaTeX/text rendering from a cv_model.json,
page-budget checking with pypdf patched out, and compile_latex with an
injected fake subprocess runner. No real pdflatex or pypdf call is made.
"""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import cv_build  # noqa: E402
from cv_common import CvDataError  # noqa: E402


def _model(**overrides):
    base = {
        "language": "fr",
        "portal_variant": "frq_old_portal",
        "candidate_name": "Martin Otis",
        "document_title": "CV descriptif",
        "sections": {
            "1": {"title": "Parcours et compétences", "prose": "Texte de parcours."},
            "2": {
                "title": "Contributions et expériences les plus importantes",
                "items": [
                    {
                        "description": "Développement d'une commande prédictive & 90% de précision",
                        "role": "chercheur principal",
                        "date": "2024",
                        "clienteles": ["milieu_academique"],
                    }
                ],
            },
            "3": {"title": "Activités de supervision et de mentorat", "prose": "s.o."},
        },
    }
    base.update(overrides)
    return base


class TestRenderLatex(unittest.TestCase):
    def test_includes_all_three_section_titles(self):
        source = cv_build.render_latex(_model())
        self.assertIn("Parcours et comp", source)
        self.assertIn("Contributions et exp", source)
        self.assertIn("supervision et de mentorat", source)

    def test_escapes_latex_special_characters(self):
        source = cv_build.render_latex(_model())
        self.assertIn(r"\&", source)
        self.assertIn(r"\%", source)
        self.assertNotIn("90% de", source)  # the raw unescaped form must not survive

    def test_uses_times_new_roman_substitute_for_frq_old_portal(self):
        source = cv_build.render_latex(_model(portal_variant="frq_old_portal"))
        self.assertIn(r"\usepackage{mathptmx}", source)

    def test_uses_helvetica_substitute_for_tri_agency(self):
        source = cv_build.render_latex(_model(portal_variant="tri_agency"))
        self.assertIn(r"\usepackage{helvet}", source)

    def test_unknown_portal_variant_raises(self):
        with self.assertRaises(CvDataError):
            cv_build.render_latex(_model(portal_variant="not-a-real-variant"))

    def test_empty_items_render_as_sans_objet(self):
        model = _model()
        model["sections"]["2"]["items"] = []
        source = cv_build.render_latex(model)
        self.assertIn("s.o.", source)


def _item_model(description, **overrides):
    model = _model(**overrides)
    model["sections"]["2"]["items"][0]["description"] = description
    return model


class TestItemMarkup(unittest.TestCase):
    """
    The funder's citation rules (candidate and co-researchers in bold, `*` after
    each supervised person) cannot be met if every section-2 item is escaped
    wholesale. Measured 2026-09-27 on a CRSNG Alliance CV: `\\textbf{...}` came
    out as `\\textbf\\{...\\}`, so no name could ever be bolded.
    """

    def test_double_star_markup_becomes_textbf_and_single_star_survives(self):
        source = cv_build.render_latex(_item_model("**Otis, M.**, Djogdom, G.*, & **Wick, J.** (2024)."))
        self.assertIn(r"\textbf{Otis, M.}", source)
        self.assertIn(r"\textbf{Wick, J.}", source)
        self.assertIn("Djogdom, G.*", source)
        self.assertNotIn("**", source)

    def test_unbalanced_markup_is_left_literal_and_does_not_raise(self):
        source = cv_build.render_latex(_item_model("**Otis sans fermeture"))
        self.assertNotIn(r"\textbf{Otis", source)
        self.assertIn("**Otis sans fermeture", source)

    def test_doi_url_becomes_clickable_and_trailing_period_stays_outside(self):
        source = cv_build.render_latex(_item_model("Voir https://doi.org/10.1016/j.rcim.2024.102734."))
        self.assertIn(r"\url{https://doi.org/10.1016/j.rcim.2024.102734}.", source)
        self.assertIn("hyperref", source)

    def test_backslash_in_plain_text_cannot_inject_a_command(self):
        source = cv_build.render_latex(_item_model(r"texte \input{secret} fin"))
        self.assertNotIn(r"\input{secret}", source)
        self.assertIn(r"\textbackslash{}", source)

    def test_item_line_carries_no_double_dash_separator(self):
        body = cv_build.render_latex(_model()).split(r"\begin{document}")[1]
        self.assertNotIn(" -- ", body)
        self.assertNotIn("---", body)

    def test_item_labels_follow_the_model_language(self):
        french = cv_build.render_latex(_model(language="fr"))
        english = cv_build.render_latex(_model(language="en"))
        self.assertIn("Rôle", french)
        self.assertIn("milieu académique", french)
        self.assertIn("Role", english)
        self.assertIn("academic community", english)
        self.assertNotIn("milieu académique", english)

    def test_missing_item_labels_block_is_named_not_defaulted(self):
        import json
        import tempfile

        types = json.loads(Path(cv_build.__file__).with_name("contribution_types.json").read_text(encoding="utf-8"))
        del types["item_labels"]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "types.json"
            path.write_text(json.dumps(types), encoding="utf-8")
            with self.assertRaises(CvDataError) as ctx:
                cv_build.render_latex(_model(), types_path=path)
        self.assertIn("item_labels", str(ctx.exception))


class TestItemReferences(unittest.TestCase):
    """
    A grouped section-2 entry cites one to three publications before its
    description. Measured 2026-09-27: written inside `description`, each
    citation ran straight into the next sentence after its DOI, which is the
    opposite of the scannable layout the funder's instructions ask for.
    """

    def _with_refs(self, refs):
        model = _model()
        model["sections"]["2"]["items"][0]["references"] = refs
        return model

    def test_each_reference_gets_its_own_line_before_the_description(self):
        source = cv_build.render_latex(self._with_refs(
            ["**Otis, M.** (2024). Titre A. https://doi.org/10.1/a", "Djogdom, G.* (2023). Titre B."]))
        first, second = source.index("Titre A"), source.index("Titre B")
        description = source.index("Développement d'une commande")
        self.assertLess(first, second)
        self.assertLess(second, description)
        self.assertIn(r"\url{https://doi.org/10.1/a}\newline", source)
        self.assertIn(r"\textbf{Otis, M.}", source)

    def test_item_without_references_renders_as_before(self):
        source = cv_build.render_latex(_model())
        self.assertIn(r"\item D", source)

    def test_references_must_be_a_list_of_strings(self):
        with self.assertRaises(CvDataError):
            cv_build.render_latex(self._with_refs("une seule chaine"))

    def test_text_companion_lists_references(self):
        text = cv_build.render_text(self._with_refs(["**Otis, M.** (2024). Titre A."]))
        self.assertIn("Otis, M. (2024). Titre A.", text)
        self.assertLess(text.index("Titre A"), text.index("Développement"))


class TestCitationRules(unittest.TestCase):
    """
    The FRQ bolds the candidate and co-researchers. The tri-agency CV bolds
    only a lead author who is not listed first (NSERC instructions, page dated
    2026-01-27). Measured 2026-09-27: a CRSNG CV drafted with the FRQ rule
    bolded a third author, which a reviewer reads as the lead author.
    """

    def _bold_ref(self, variant):
        model = _model(portal_variant=variant)
        model["sections"]["2"]["items"][0]["references"] = ["Nabli, S.*, & **Otis, M.** (2025). Titre."]
        return model

    def test_bold_name_in_a_tri_agency_reference_is_flagged(self):
        warnings = cv_build.citation_warnings(self._bold_ref("tri_agency"))
        self.assertEqual(len(warnings), 1)
        self.assertIn("Otis, M.", warnings[0])

    def test_bold_name_under_the_frq_rule_is_not_flagged(self):
        self.assertEqual(cv_build.citation_warnings(self._bold_ref("frq_old_portal")), [])

    def test_tri_agency_reference_without_bold_is_clean(self):
        model = _model(portal_variant="tri_agency")
        model["sections"]["2"]["items"][0]["references"] = ["Nabli, S.*, & Otis, M. (2025). Titre."]
        self.assertEqual(cv_build.citation_warnings(model), [])

    def test_shipped_variants_all_declare_their_citation_rules(self):
        import json

        types = json.loads(Path(cv_build.__file__).with_name("contribution_types.json").read_text(encoding="utf-8"))
        for name, variant in types["portal_variants"].items():
            self.assertIn("citation_rules", variant, name)
        self.assertFalse(types["portal_variants"]["tri_agency"]["citation_rules"]["bold_candidate_and_coresearchers"])


class TestPageSetup(unittest.TestCase):
    def test_letter_paper_is_declared_explicitly(self):
        self.assertIn("letterpaper", cv_build.render_latex(_model()))

    def test_tri_agency_prints_template_heading_and_name_line_without_running_header(self):
        source = cv_build.render_latex(_model(portal_variant="tri_agency"))
        self.assertIn("CV des trois organismes", source)
        self.assertIn("Nom", source)
        self.assertNotIn(r"\lhead{Martin Otis}", source)

    def test_frq_old_portal_keeps_the_mandatory_header_and_footer(self):
        source = cv_build.render_latex(_model(portal_variant="frq_old_portal"))
        self.assertIn(r"\lhead{Martin Otis}", source)
        self.assertIn(r"\rfoot{CV descriptif}", source)
        self.assertNotIn("CV des trois organismes", source)


class TestLoadModel(unittest.TestCase):
    """
    Section prose is raw LaTeX, and raw LaTeX inside a JSON string doubles every
    backslash. `prose_file` lets the prose live in a .tex file beside the model,
    so the content stays data in the project folder and no throwaway script is
    needed to assemble it (measured 2026-09-27: two such scripts were written).
    """

    def _write(self, tmp, model, files):
        import json

        for name, content in files.items():
            (Path(tmp) / name).write_text(content, encoding="utf-8")
        path = Path(tmp) / "cv_model.json"
        path.write_text(json.dumps(model), encoding="utf-8")
        return path

    def test_prose_file_is_read_relative_to_the_model(self):
        import tempfile

        model = _model()
        model["sections"]["1"] = {"title": "Déclaration personnelle", "prose_file": "s1.tex"}
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(tmp, model, {"s1.tex": r"\textbf{Parcours.} Texte."})
            loaded = cv_build.load_model(path)
        self.assertEqual(loaded["sections"]["1"]["prose"], r"\textbf{Parcours.} Texte.")
        self.assertIn(r"\textbf{Parcours.}", cv_build.render_latex(loaded))

    def test_missing_prose_file_is_named(self):
        import tempfile

        model = _model()
        model["sections"]["3"] = {"title": "Supervision", "prose_file": "absent.tex"}
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(tmp, model, {})
            with self.assertRaises(CvDataError) as ctx:
                cv_build.load_model(path)
        self.assertIn("absent.tex", str(ctx.exception))

    def test_prose_file_leaving_the_model_folder_is_refused(self):
        import tempfile

        model = _model()
        model["sections"]["1"] = {"title": "X", "prose_file": "../outside.tex"}
        with tempfile.TemporaryDirectory() as tmp:
            inner = Path(tmp) / "inner"
            inner.mkdir()
            (Path(tmp) / "outside.tex").write_text("secret", encoding="utf-8")
            path = self._write(inner, model, {})
            with self.assertRaises(CvDataError):
                cv_build.load_model(path)


class TestRenderText(unittest.TestCase):
    def test_bold_markers_are_stripped_and_no_double_dash_is_emitted(self):
        text = cv_build.render_text(_item_model("**Otis, M.** et Djogdom, G.* (2024)."))
        self.assertIn("Otis, M. et Djogdom, G.*", text)
        self.assertNotIn("**", text)
        self.assertNotIn(" -- ", text)

    def test_includes_section_titles_and_items(self):
        text = cv_build.render_text(_model())
        self.assertIn("Parcours et compétences", text)
        self.assertIn("chercheur principal", text)

    def test_no_latex_markup_leaks_into_text_output(self):
        text = cv_build.render_text(_model())
        self.assertNotIn("\\textbf", text)
        self.assertNotIn("\\section", text)


class TestPageBudget(unittest.TestCase):
    @patch("cv_build.count_pdf_pages", return_value=5)
    def test_within_budget_for_french(self, _mock):
        report = cv_build.check_page_budget("fake.pdf", "fr")
        self.assertEqual(report["max_pages"], 6)
        self.assertFalse(report["over_budget"])

    @patch("cv_build.count_pdf_pages", return_value=6)
    def test_over_budget_for_english(self, _mock):
        report = cv_build.check_page_budget("fake.pdf", "en")
        self.assertEqual(report["max_pages"], 5)
        self.assertTrue(report["over_budget"])

    def test_missing_pypdf_or_unreadable_pdf_raises(self):
        with patch("builtins.__import__", side_effect=ImportError("no pypdf")):
            with self.assertRaises(CvDataError):
                cv_build.count_pdf_pages("fake.pdf")


class _FakeCompletedProcess:
    def __init__(self, returncode):
        self.returncode = returncode


class TestCompileLatex(unittest.TestCase):
    def test_runs_pdflatex_twice_and_reports_pdf_path(self):
        calls = []

        def fake_runner(cmd, **kwargs):
            calls.append(cmd)
            return _FakeCompletedProcess(returncode=0)

        result = cv_build.compile_latex("out/main.tex", outdir="out", runner=fake_runner)
        self.assertEqual(len(calls), 2)
        self.assertEqual(result["returncode"], 0)
        self.assertTrue(result["pdf_path"].endswith("main.pdf"))

    def test_nonzero_returncode_propagates(self):
        def failing_runner(cmd, **kwargs):
            return _FakeCompletedProcess(returncode=1)

        result = cv_build.compile_latex("out/main.tex", outdir="out", runner=failing_runner)
        self.assertEqual(result["returncode"], 1)


if __name__ == "__main__":
    unittest.main()
