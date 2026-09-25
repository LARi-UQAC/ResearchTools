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


class TestRenderText(unittest.TestCase):
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
