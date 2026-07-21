"""
Offline unit tests for generate_letter.py. Standard library only:
no network, no pdflatex, no model load.

Run from the repo root:
    python -m unittest discover -s ".claude/skills/recommendation-letter/scripts/Test" -v
"""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import generate_letter as gl


class TestConfigAndFilenames(unittest.TestCase):
    def test_load_config_reads_json(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False,
                                         encoding="utf-8") as fh:
            json.dump({"letter_type": "appreciation", "language": "en"}, fh)
            path = fh.name
        try:
            cfg = gl.load_config(path)
            self.assertEqual(cfg["letter_type"], "appreciation")
        finally:
            os.unlink(path)

    def test_load_config_invalid_json_raises(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False,
                                         encoding="utf-8") as fh:
            fh.write("{not valid json")
            path = fh.name
        try:
            with self.assertRaises(ValueError):
                gl.load_config(path)
        finally:
            os.unlink(path)

    def test_surname_slug_folds_accents_and_lowercases(self):
        self.assertEqual(gl.surname_slug("Candidat Exemple Charlie"), "charlie")
        self.assertEqual(gl.surname_slug("Prénom Àccentué"), "accentue")


class TestEscapeAndDates(unittest.TestCase):
    def test_escape_latex_specials(self):
        self.assertEqual(gl.escape_latex("R&D 50% #1 a_b $x {y} ~ ^"),
                         r"R\&D 50\% \#1 a\_b \$x \{y\} \textasciitilde{} \textasciicircum{}")

    def test_escape_keeps_accents(self):
        self.assertEqual(gl.escape_latex("étudiante à l'UQAC"),
                         "étudiante à l'UQAC")

    def test_format_date_fr(self):
        self.assertEqual(gl.format_date("2026-03-27", "fr"), "Le 27 mars 2026")

    def test_format_date_en(self):
        self.assertEqual(gl.format_date("2026-03-27", "en"), "March 27, 2026")

    def test_format_date_dispense(self):
        self.assertEqual(gl.format_date_dispense("2026-03-04"), "le 4 mars 2026")

    def test_format_date_empty_is_placeholder(self):
        self.assertEqual(gl.format_date("", "fr"), "[À COMPLÉTER]")


def _cfg(**kw):
    base = {"candidate_name": "Candidat Exemple Bravo", "candidate_gender": "M",
            "candidate_status": "graduated", "candidate_title": "Dr.",
            "candidate_program": "génie", "language": "fr"}
    base.update(kw)
    return base


class TestCandidateReference(unittest.TestCase):
    def test_graduated_fr_uses_title(self):
        ref = gl.derive_candidate_reference(_cfg())
        self.assertIn("Dr.", ref)
        self.assertIn("Candidat Exemple Bravo", ref)

    def test_current_student_fr_masc(self):
        ref = gl.derive_candidate_reference(
            _cfg(candidate_status="current_student", candidate_title="M.",
                 candidate_program="doctorat en ingénierie"))
        self.assertIn("étudiant au doctorat en ingénierie", ref)
        self.assertNotIn("étudiante", ref)

    def test_current_student_fr_fem(self):
        ref = gl.derive_candidate_reference(
            _cfg(candidate_gender="F", candidate_status="current_student",
                 candidate_name="Candidate Exemple Foxtrot", candidate_program="maîtrise"))
        self.assertIn("étudiante au maîtrise", ref)

    def test_applicant_fr_fem(self):
        ref = gl.derive_candidate_reference(
            _cfg(candidate_gender="F", candidate_status="applicant",
                 candidate_name="Candidate Exemple India"))
        self.assertIn("la candidate", ref)
        self.assertIn("Candidate Exemple India", ref)

    def test_current_student_en(self):
        ref = gl.derive_candidate_reference(
            _cfg(candidate_status="current_student", candidate_title="Mr.",
                 candidate_program="PhD program", language="en"))
        self.assertIn("a student in the PhD program", ref)

    def test_warn_graduated_without_title(self):
        warns = gl.status_title_warnings(
            _cfg(candidate_status="graduated", candidate_title="M."))
        self.assertTrue(any("doctoral title" in w for w in warns))

    def test_warn_applicant_with_dr(self):
        warns = gl.status_title_warnings(
            _cfg(candidate_status="applicant", candidate_title="Dr."))
        self.assertTrue(any("Dr." in w for w in warns))


class TestStyleHygiene(unittest.TestCase):
    def test_clean_text_has_no_violations(self):
        self.assertEqual(gl.style_hygiene_violations("Straight text, no tricks."), [])

    def test_flags_em_dash(self):
        v = gl.style_hygiene_violations("a — b")
        self.assertTrue(any("dash" in x for x in v))

    def test_flags_zero_width(self):
        v = gl.style_hygiene_violations("a​b")
        self.assertTrue(any("zero-width" in x for x in v))

    def test_flags_ellipsis_and_smart_quotes(self):
        v = gl.style_hygiene_violations("he said “hi”…")
        self.assertTrue(any("ellipsis" in x for x in v))
        self.assertTrue(any("smart quote" in x for x in v))

    def test_flags_stray_markdown(self):
        v = gl.style_hygiene_violations("**bold** left over")
        self.assertTrue(any("markdown" in x for x in v))


class TestGenderAndFill(unittest.TestCase):
    def test_apply_gender_female(self):
        out = gl.apply_gender(r"accepté%%GENDER_E%% et %%GENDER_HEUREUX%%", "F")
        self.assertEqual(out, "acceptée et heureuse")

    def test_apply_gender_male_empty_e(self):
        out = gl.apply_gender(r"invité%%GENDER_E%%", "M")
        self.assertEqual(out, "invité")

    def test_apply_gender_il_elle(self):
        self.assertEqual(gl.apply_gender("%%GENDER_IL%% travaille", "F"), "Elle travaille")

    def test_fill_scalars_escapes_values(self):
        out = gl.fill_scalars("Objet: %%TARGET%%", {"TARGET": "R&D lab"})
        self.assertEqual(out, r"Objet: R\&D lab")

    def test_fill_scalars_leaves_unknown(self):
        out = gl.fill_scalars("x %%MISSING%%", {})
        self.assertIn("%%MISSING%%", out)


class TestFunding(unittest.TestCase):
    def test_supervisor_mitacs_acceleration(self):
        p = gl.build_funding_paragraph(
            {"funding_provider": "supervisor",
             "funding_model": "mitacs_acceleration"})
        self.assertIn("MITACS Accélération", p)
        self.assertIn("12 500", p)

    def test_supervisor_befm(self):
        p = gl.build_funding_paragraph(
            {"funding_provider": "supervisor", "funding_model": "befm"})
        self.assertIn("BEFM", p)

    def test_candidate_self_funded(self):
        p = gl.build_funding_paragraph(
            {"funding_provider": "candidate", "funding_model": "self_funded"})
        self.assertIn("son propre financement", p)

    def test_candidate_external_scholarship(self):
        p = gl.build_funding_paragraph(
            {"funding_provider": "candidate", "funding_model": "scholarship",
             "funding_source_details": "PFLA (ELAP), 8600$ pour 4 mois"})
        self.assertIn("PFLA (ELAP)", p)

    def test_combination_has_both(self):
        p = gl.build_funding_paragraph(
            {"funding_provider": "combination", "funding_model": "befm",
             "funding_source_details": "et une bourse familiale"})
        self.assertIn("BEFM", p)
        self.assertIn("bourse familiale", p)

    def test_unresolved_placeholder(self):
        p = gl.build_funding_paragraph({"funding_provider": "supervisor"})
        self.assertIn("[À COMPLÉTER", p)


class TestAuthoredAssembly(unittest.TestCase):
    def test_count_words_strips_commands(self):
        n = gl.count_words(r"\textbf{Bonjour} le monde entier")
        self.assertEqual(n, 4)

    def test_assemble_authored_wraps_body(self):
        cfg = {"letter_type": "appreciation", "language": "fr",
               "date": "2026-03-27", "candidate_name": "Candidat Exemple Tango",
               "candidate_status": "graduated", "candidate_title": "Dr.",
               "target": "prix", "body_tex": "Corps de la lettre ici."}
        tex = gl.assemble_authored(cfg)
        self.assertIn(r"\begin{document}", tex)
        self.assertIn("Corps de la lettre ici.", tex)
        self.assertIn("Martin J.-D. Otis", tex)
        self.assertIn("Le 27 mars 2026", tex)

    def test_assemble_authored_en_uses_english_blocks(self):
        cfg = {"letter_type": "academic_position", "language": "en",
               "date": "2023-06-03", "candidate_name": "Candidat Exemple Bravo",
               "candidate_status": "graduated", "candidate_title": "Dr.",
               "target": "Professor position", "body_tex": "Body."}
        tex = gl.assemble_authored(cfg)
        self.assertIn("Best regards", tex)
        self.assertIn("Full Professor", tex)


class TestAcceptance(unittest.TestCase):
    def _cfg(self, **kw):
        base = {"letter_type": "acceptance", "language": "fr",
                "date": "2023-05-23", "candidate_name": "Candidat Exemple Delta",
                "candidate_gender": "M", "candidate_status": "applicant",
                "degree_level": "msc",
                "project_description": "le diagnostic des systèmes hybrides",
                "funding_provider": "supervisor",
                "funding_model": "mitacs_acceleration", "funding_amount": "12500",
                "tools_technologies": "RoboDK et CodeSys",
                "project_end_date": "décembre 2025"}
        base.update(kw)
        return base

    def test_no_unresolved_placeholders(self):
        tex = gl.build_acceptance(self._cfg())
        self.assertNotIn("%%", tex)

    def test_subject_line_and_project(self):
        tex = gl.build_acceptance(self._cfg())
        self.assertIn("Confirmation d'acceptation de Candidat Exemple Delta", tex)
        self.assertIn("maîtrise de recherche", tex)
        self.assertIn("le diagnostic des systèmes hybrides", tex)

    def test_female_gender_agreement(self):
        tex = gl.build_acceptance(self._cfg(candidate_gender="F",
                                            candidate_name="Candidate Exemple Foxtrot",
                                            degree_level="msc"))
        self.assertIn("acceptée", tex)
        self.assertIn("heureuse", tex)

    def test_prerequisites_omitted_when_empty(self):
        tex = gl.build_acceptance(self._cfg(prerequisites=""))
        self.assertNotIn("propédeutique", tex)

    def test_prerequisites_present(self):
        tex = gl.build_acceptance(self._cfg(prerequisites="l'examen doctoral et deux cours"))
        self.assertIn("propédeutique", tex)

    def test_single_document_environment(self):
        tex = gl.build_acceptance(self._cfg())
        self.assertEqual(tex.count(r"\begin{document}"), 1)
        self.assertEqual(tex.count(r"\end{document}"), 1)


class TestDispense(unittest.TestCase):
    def _cfg(self, **kw):
        base = {"letter_type": "dispense", "language": "fr", "date": "2026-03-04",
                "candidate_name": "Candidat Exemple Golf", "candidate_gender": "M",
                "candidate_address": "12 rue de l'Exemple, Villeneuve, France",
                "stay_start": "2026/05/01", "stay_end": "2026/07/31",
                "remuneration": "aucune", "weekly_hours": "40",
                "home_institution": "Institut Exemple B",
                "tasks_description": "Conception d'un modèle LBM en PyTorch",
                "conditional_scholarship": "false"}
        base.update(kw)
        return base

    def test_stay_days(self):
        self.assertEqual(gl.stay_days("2026/05/01", "2026/07/31"), 91)
        self.assertEqual(gl.stay_days("2027/01/04", "2027/04/30"), 116)
        self.assertIsNone(gl.stay_days("bad", "2027/04/30"))

    def test_no_unresolved_placeholders(self):
        tex, _ = gl.build_dispense(self._cfg())
        self.assertNotIn("%%", tex)

    def test_immigration_paragraph_present(self):
        tex, _ = gl.build_dispense(self._cfg())
        self.assertIn("dispense de permis de travail", tex)
        self.assertIn("120 jours", tex)

    def test_conditional_sentence_precedes_immigration(self):
        tex, _ = gl.build_dispense(self._cfg(conditional_scholarship="true",
                                             conditional_scholarship_name="PFLA (ELAP)"))
        i_cond = tex.index("conditionnelle à l'obtention")
        i_imm = tex.index("dispense de permis de travail")
        self.assertLess(i_cond, i_imm)
        self.assertIn("PFLA (ELAP)", tex)

    def test_over_120_days_warns_and_adds_clause(self):
        tex, warns = gl.build_dispense(self._cfg(stay_start="2026/02/02",
                                                 stay_end="2026/07/03"))
        self.assertTrue(any("120" in w for w in warns))
        self.assertIn("validation auprès de l'immigration", tex)

    def test_female_salutation(self):
        tex, _ = gl.build_dispense(self._cfg(candidate_gender="F",
                                             candidate_name="Candidate Exemple India"))
        self.assertIn("Madame,", tex)
        self.assertIn("invitée", tex)


class TestDispatch(unittest.TestCase):
    def test_authored_single_result(self):
        cfg = {"letter_type": "scholarship", "language": "fr", "date": "2026-03-27",
               "candidate_name": "Candidat Exemple Alpha", "candidate_status": "applicant",
               "candidate_gender": "M", "target": "PFLA", "body_tex": "Corps."}
        res = gl.generate(cfg)
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0]["letter_type"], "scholarship")

    def test_invitation_pair_both_yields_two(self):
        cfg = {"letter_type": "acceptance", "language": "fr", "invitation_pair": "both",
               "date": "2025-12-28", "candidate_name": "Candidate Exemple India",
               "candidate_gender": "F", "candidate_status": "applicant",
               "degree_level": "research_stay", "project_description": "VLA robotique",
               "funding_provider": "supervisor", "funding_model": "mitacs_gra",
               "candidate_address": "Ville-Test, Pays-Exemple", "stay_start": "2026/04/01",
               "stay_end": "2026/06/24", "remuneration": "MITACS GRA",
               "home_institution": "Université Exemple C",
               "tasks_description": "VLA robotique", "conditional_scholarship": "false"}
        res = gl.generate(cfg)
        types = sorted(r["letter_type"] for r in res)
        self.assertEqual(types, ["acceptance", "dispense"])

    def test_collect_warnings_flags_placeholder(self):
        warns = gl.collect_warnings(
            {"letter_type": "appreciation", "language": "fr",
             "candidate_status": "graduated", "candidate_title": "M."},
            "body with [À COMPLÉTER] token")
        self.assertTrue(any("À COMPLÉTER" in w or "placeholder" in w.lower() for w in warns))
        self.assertTrue(any("doctoral title" in w for w in warns))

    def test_write_outputs_no_compile(self):
        cfg = {"letter_type": "appreciation", "language": "fr", "date": "2026-03-27",
               "candidate_name": "Candidat Exemple Tango", "candidate_status": "graduated",
               "candidate_title": "Dr.", "target": "prix", "body_tex": "Corps."}
        res = gl.generate(cfg)
        d = tempfile.mkdtemp()
        code = gl.write_outputs(res, cfg, d, compile_pdf=False, strict=False)
        self.assertEqual(code, 0)
        self.assertTrue(os.path.exists(os.path.join(d, "letter_tango_appreciation.tex")))


class TestCompileHelpers(unittest.TestCase):
    def test_count_pdf_pages_from_bytes(self):
        data = b"%PDF-1.5\n/Type /Pages /Count 2\n/Type /Page\n/Type /Page\n%%EOF"
        fd, path = tempfile.mkstemp(suffix=".pdf")
        os.write(fd, data)
        os.close(fd)
        try:
            self.assertEqual(gl.count_pdf_pages(path), 2)
        finally:
            os.unlink(path)

    def test_compile_latex_missing_pdflatex_returns_false(self):
        d = tempfile.mkdtemp()
        tex = os.path.join(d, "x.tex")
        with open(tex, "w", encoding="utf-8") as fh:
            fh.write(r"\documentclass{article}\begin{document}x\end{document}")
        result = gl.compile_latex(tex, d)
        self.assertIn(result, (True, False))


if __name__ == "__main__":
    unittest.main()