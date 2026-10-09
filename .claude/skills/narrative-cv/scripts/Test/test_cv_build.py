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
        source = cv_build.render_latex(_item_model("**Otis, M.**, Tarasov, V.*, & **Wick, J.** (2024)."))
        self.assertIn(r"\textbf{Otis, M.}", source)
        self.assertIn(r"\textbf{Wick, J.}", source)
        self.assertIn("Tarasov, V.*", source)
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
            ["**Otis, M.** (2024). Titre A. https://doi.org/10.1/a", "Tarasov, V.* (2023). Titre B."]))
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
        model["sections"]["2"]["items"][0]["references"] = ["Wick, H.*, & **Otis, M.** (2025). Titre."]
        return model

    def test_bold_name_in_a_tri_agency_reference_is_flagged(self):
        warnings = cv_build.citation_warnings(self._bold_ref("tri_agency"))
        self.assertEqual(len(warnings), 1)
        self.assertIn("Otis, M.", warnings[0])

    def test_bold_name_under_the_frq_rule_is_not_flagged(self):
        self.assertEqual(cv_build.citation_warnings(self._bold_ref("frq_old_portal")), [])

    def test_tri_agency_reference_without_bold_is_clean(self):
        model = _model(portal_variant="tri_agency")
        model["sections"]["2"]["items"][0]["references"] = ["Wick, H.*, & Otis, M. (2025). Titre."]
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
        text = cv_build.render_text(_item_model("**Otis, M.** et Tarasov, V.* (2024)."))
        self.assertIn("Otis, M. et Tarasov, V.*", text)
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


def _row(**overrides):
    base = {
        "name": "Étudiante Alpha",
        "cycle": "Maîtrise",
        "start": "2022-09",
        "end": "2024-08",
        "consent_cv": "2026-09-01",
    }
    base.update(overrides)
    return base


def _hqp_model(**overrides):
    model = _model(**overrides)
    model["sections"]["3"]["hqp_list"] = True
    return model


class TestHqp(unittest.TestCase):
    def test_no_hqp_is_byte_identical(self):
        self.assertEqual(cv_build.render_latex(_model()), cv_build.render_latex(_model(), hqp=None))
        self.assertEqual(cv_build.render_text(_model()), cv_build.render_text(_model(), hqp=None))

    def test_rules_shipped_with_provenance(self):
        types = cv_build.load_contribution_types()
        rules = cv_build.load_hqp_rules(types, "tri_agency")
        self.assertEqual(rules["window_years"], 6)
        for language in ("fr", "en"):
            labels = rules["labels"][language]
            for key in ("recent_heading", "archive_heading", "ongoing", "none"):
                self.assertTrue(labels[key])
        self.assertTrue(types["hqp"]["_provenance"])

    def test_window_is_per_funder(self):
        # NSERC/tri-agency: 6 years. FRQ (both portals): 5 years. Operator,
        # 2026-10-08: one fixed window_years was wrong, the CV window
        # depends on which funder's template is being built.
        types = cv_build.load_contribution_types()
        self.assertEqual(cv_build.load_hqp_rules(types, "tri_agency")["window_years"], 6)
        self.assertEqual(cv_build.load_hqp_rules(types, "frq_old_portal")["window_years"], 5)
        self.assertEqual(cv_build.load_hqp_rules(types, "frq_new_portal")["window_years"], 5)

    def test_rules_missing_key_named(self):
        types = {}
        with self.assertRaises(CvDataError) as ctx:
            cv_build.load_hqp_rules(types, "tri_agency")
        self.assertIn("hqp", str(ctx.exception))

    def test_rules_unknown_portal_variant_named(self):
        types = cv_build.load_contribution_types()
        with self.assertRaises(CvDataError) as ctx:
            cv_build.load_hqp_rules(types, "not-a-real-variant")
        self.assertIn("not-a-real-variant", str(ctx.exception))

    def test_window_split(self):
        rows = [
            _row(start="2019-09", end="2021-06", consent_cv="2026-01-01"),
            _row(start="2018-09", end="2020-01", consent_cv="2026-01-01"),
            _row(end=None, consent_cv="2026-01-01"),
        ]
        validated = cv_build.validate_hqp_rows(rows, reference_year=2026, window_years=6)
        recent = [r for r in validated if r["in_window"]]
        archive = [r for r in validated if not r["in_window"]]
        self.assertEqual(len(recent), 2)
        self.assertEqual(len(archive), 1)

    def test_consent_required_in_window(self):
        rows = [_row(end="2024-08", consent_cv=None)]
        with self.assertRaises(CvDataError) as ctx:
            cv_build.validate_hqp_rows(rows, reference_year=2026, window_years=6)
        message = str(ctx.exception)
        self.assertIn("row 0", message)
        self.assertNotIn("Étudiante Alpha", message)

    def test_archive_without_consent_now_refused(self):
        # C6 revised, operator 2026-10-08: consent is mandatory for EVERY
        # row regardless of the window. The window only decides whether a
        # row is listed as recent or archive, never whether consent is
        # required.
        rows = [_row(start="2013-09", end="2015-06", consent_cv=None)]
        with self.assertRaises(CvDataError) as ctx:
            cv_build.validate_hqp_rows(rows, reference_year=2026, window_years=6)
        self.assertIn("row 0", str(ctx.exception))

    def test_archive_with_consent_still_accepted(self):
        rows = [_row(start="2013-09", end="2015-06", consent_cv="2015-07-01")]
        validated = cv_build.validate_hqp_rows(rows, reference_year=2026, window_years=6)
        self.assertFalse(validated[0]["in_window"])

    def test_reference_year_out_of_bounds_refused(self):
        with self.assertRaises(CvDataError):
            cv_build.validate_hqp_rows([_row()], reference_year=9999, window_years=6)
        with self.assertRaises(CvDataError):
            cv_build.validate_hqp_rows([_row()], reference_year=0, window_years=6)
        with self.assertRaises(CvDataError):
            cv_build.validate_hqp_rows([_row()], reference_year=-5, window_years=6)

    def test_reference_year_bound_is_exact(self):
        # Reviewer, 2026-10-08 (mutation survivor): 9999/0/-5 are far enough
        # out that an unrelated check could coincidentally catch them too.
        # Pin the exact boundary instead: 1999 and 2101 are each one year
        # outside the [2000, 2100] bound and nothing else about them is
        # malformed. A SECOND mutation-survivor round (same date) found that
        # the 1999 case still used the plain `_row()` default (end="2024-08"),
        # so it raised via "end must not be after reference_year" instead of
        # the bound itself - the exact failure mode this test exists to
        # catch. Every case now uses a row whose own dates are valid for
        # EVERY reference_year under test, so only the bound can fire.
        early_row = _row(start="1999-01", end=None, consent_cv="1999-06-01")
        with self.assertRaises(CvDataError):
            cv_build.validate_hqp_rows([early_row], reference_year=1999, window_years=6)
        with self.assertRaises(CvDataError):
            cv_build.validate_hqp_rows([early_row], reference_year=2101, window_years=6)
        cv_build.validate_hqp_rows([early_row], reference_year=2000, window_years=6)
        cv_build.validate_hqp_rows([early_row], reference_year=2100, window_years=6)

    def test_start_after_end_refused(self):
        rows = [_row(start="2024-08", end="2020-01")]
        with self.assertRaises(CvDataError):
            cv_build.validate_hqp_rows(rows, reference_year=2026, window_years=6)

    def test_end_after_reference_year_refused(self):
        rows = [_row(start="2024-01", end="2031-01")]
        with self.assertRaises(CvDataError):
            cv_build.validate_hqp_rows(rows, reference_year=2026, window_years=6)

    def test_impossible_month_refused(self):
        with self.assertRaises(CvDataError):
            cv_build.validate_hqp_rows(
                [_row(start="2024-13")], reference_year=2026, window_years=6)
        with self.assertRaises(CvDataError):
            cv_build.validate_hqp_rows(
                [_row(end="2024-00")], reference_year=2026, window_years=6)

    def test_impossible_start_month_refused_on_its_own(self):
        # Reviewer, 2026-10-08 (mutation survivor): the previous case paired
        # a bad start with a later default end, so removing JUST the
        # start-side calendar check still raised - through the start>end
        # ordering check instead, for the wrong reason. end=None removes
        # that side effect, so only the start calendar check can catch it.
        with self.assertRaises(CvDataError):
            cv_build.validate_hqp_rows(
                [_row(start="2024-13", end=None)], reference_year=2026, window_years=6)

    def test_future_dated_consent_refused(self):
        rows = [_row(end="2024-08", consent_cv="2031-01-01")]
        with self.assertRaises(CvDataError):
            cv_build.validate_hqp_rows(rows, reference_year=2026, window_years=6)

    def test_no_row_value_leaks_into_any_row_error(self):
        # Reviewer, 2026-10-08: only the missing-consent and unknown-key
        # messages were proven name-free. Parametrise over every malformed
        # field so a future edit cannot quietly put a value back into ONE
        # of the others.
        name = "Étudiante Alpha"
        bad_rows = {
            # "name" itself is excluded: making it invalid (empty) and then
            # overwriting it with the fictitious name for the leak probe
            # would make the row valid again, defeating the case.
            "cycle": _row(cycle=""),
            "start": _row(start="not-a-date"),
            "end": _row(end="not-a-date"),
            "consent_cv_future": _row(end="2024-08", consent_cv="2031-01-01"),
            "position_type": _row(current_position=123),
            "employer_type": _row(current_employer=123),
        }
        for label, row in bad_rows.items():
            row["name"] = name
            with self.assertRaises(CvDataError) as ctx:
                cv_build.validate_hqp_rows([row], reference_year=2026, window_years=6)
            self.assertNotIn(name, str(ctx.exception), label)

    def test_language_must_be_fr_or_en(self):
        # F1 (reviewer, 2026-10-08): render_hqp does a bare labels[language]
        # lookup that raises KeyError, not CvDataError, for anything else -
        # assert_inline_model is the route's only check (cv_bridge.build_cv
        # calls it before either renderer), so it has to catch this, not
        # render_latex itself (the local CLI's `render` calls render_latex
        # directly, with no assert_inline_model gate, by design).
        model = _model(language="de")
        with self.assertRaises(CvDataError):
            cv_build.assert_inline_model(model)
        with self.assertRaises(CvDataError):
            cv_build.assert_inline_model(_model(language=3))

    def test_item_description_type_refused(self):
        model = _model()
        model["sections"]["2"]["items"][0]["description"] = 12345
        with self.assertRaises(CvDataError):
            cv_build.assert_inline_model(model)

    def test_item_clienteles_type_refused(self):
        model = _model()
        model["sections"]["2"]["items"][0]["clienteles"] = "not-a-list"
        with self.assertRaises(CvDataError):
            cv_build.assert_inline_model(model)

    def test_unknown_key_refused(self):
        rows = [_row(email="alpha@example.org")]
        with self.assertRaises(CvDataError) as ctx:
            cv_build.validate_hqp_rows(rows, reference_year=2026, window_years=6)
        message = str(ctx.exception)
        self.assertIn("row 0", message)
        self.assertNotIn("Étudiante Alpha", message)

    def test_unknown_key_name_itself_is_not_echoed(self):
        # The unknown KEY, not only the row's name field, must never reach the
        # message: a caller could put a free-form value in the key position.
        rows = [_row(**{"Étudiante Alpha": True})]
        with self.assertRaises(CvDataError) as ctx:
            cv_build.validate_hqp_rows(rows, reference_year=2026, window_years=6)
        message = str(ctx.exception)
        self.assertIn("row 0", message)
        self.assertNotIn("Étudiante Alpha", message)

    def test_bad_dates_refused(self):
        with self.assertRaises(CvDataError):
            cv_build.validate_hqp_rows([_row(start="2024/5")], reference_year=2026, window_years=6)
        with self.assertRaises(CvDataError):
            cv_build.validate_hqp_rows([_row(consent_cv="02-10-2026")], reference_year=2026, window_years=6)

    def test_consent_cv_impossible_calendar_date_refused(self):
        # "2026-99-99" matches the \d{4}-\d{2}-\d{2} shape but is not a real
        # date; a shape-only check would wrongly treat this row as consenting.
        rows = [_row(end="2024-08", consent_cv="2026-99-99")]
        with self.assertRaises(CvDataError):
            cv_build.validate_hqp_rows(rows, reference_year=2026, window_years=6)

    def test_position_and_employer_type_refused(self):
        with self.assertRaises(CvDataError):
            cv_build.validate_hqp_rows(
                [_row(current_position=12345)], reference_year=2026, window_years=6)
        with self.assertRaises(CvDataError):
            cv_build.validate_hqp_rows(
                [_row(current_employer=["not", "a", "string"])],
                reference_year=2026, window_years=6)

    def test_rows_without_hqp_list_refused(self):
        model = _model()  # no hqp_list flag on section 3
        with self.assertRaises(CvDataError):
            cv_build.render_latex(model, hqp={"rows": [_row()], "reference_year": 2026})

    def test_prose_file_refused(self):
        model = _model()
        model["sections"]["1"] = {"title": "X", "prose_file": "../x.tex"}
        with self.assertRaises(CvDataError) as ctx:
            cv_build.assert_inline_model(model)
        self.assertNotIn("../x.tex", str(ctx.exception))

    def test_prose_file_refusal_does_not_echo_the_section_key_either(self):
        # N3 (reviewer, 2026-10-08): the section KEY can be caller-controlled
        # free text too, same class as the row-key finding already fixed.
        model = _model()
        del model["sections"]["1"]
        model["sections"]["Étudiante Alpha"] = {"title": "X", "prose_file": "y.tex"}
        with self.assertRaises(CvDataError) as ctx:
            cv_build.assert_inline_model(model)
        self.assertNotIn("Étudiante Alpha", str(ctx.exception))

    def test_section_items_not_a_list_refused(self):
        model = _model()
        model["sections"]["2"]["items"] = "not-a-list"
        with self.assertRaises(CvDataError):
            cv_build.assert_inline_model(model)

    def test_section_prose_not_a_string_refused(self):
        model = _model()
        model["sections"]["1"] = {"title": "X", "prose": ["not", "a", "string"]}
        with self.assertRaises(CvDataError):
            cv_build.assert_inline_model(model)

    def test_language_explicit_null_refused(self):
        # M1 (reviewer, 2026-10-08): model.get("language") cannot tell "key
        # absent" from "key present with value None" apart, and the earlier
        # fix (`if language is not None and ...`) let an explicit null
        # through, which then crashed deeper in render_hqp's labels[None]
        # lookup. "language" in model is checked instead, so this must be
        # refused here rather than reaching that KeyError.
        model = _model()
        model["language"] = None
        with self.assertRaises(CvDataError):
            cv_build.assert_inline_model(model)

    def test_item_clienteles_element_type_refused(self):
        # M2: the existing test only covers the whole field being the wrong
        # type (a string instead of a list); a list carrying a non-string
        # element must be refused too.
        model = _model()
        model["sections"]["2"]["items"][0]["clienteles"] = ["milieu_academique", 123]
        with self.assertRaises(CvDataError):
            cv_build.assert_inline_model(model)

    def test_consent_on_december_31_of_reference_year_accepted(self):
        # Q1a: the full-date boundary, upper edge.
        rows = [_row(end="2024-08", consent_cv="2026-12-31")]
        validated = cv_build.validate_hqp_rows(rows, reference_year=2026, window_years=6)
        self.assertTrue(validated[0]["in_window"])

    def test_consent_on_january_1_of_next_year_refused(self):
        # Q1a: one day past the December 31 boundary must still be refused.
        rows = [_row(end="2024-08", consent_cv="2027-01-01")]
        with self.assertRaises(CvDataError):
            cv_build.validate_hqp_rows(rows, reference_year=2026, window_years=6)

    def test_consent_on_first_day_of_start_month_accepted(self):
        # Mutation survivor (reviewer, 2026-10-09): the consent-before-start
        # check uses a strict "<"; consent dated exactly on the first day of
        # the start month must be the boundary's accepted side.
        rows = [_row(start="2022-09", end="2024-08", consent_cv="2022-09-01")]
        validated = cv_build.validate_hqp_rows(rows, reference_year=2026, window_years=6)
        self.assertTrue(validated[0]["in_window"])

    def test_consent_before_start_refused(self):
        # Q1b: consent_cv predating the row's own start is refused even
        # though it is not "after reference_year" - a consent form signed
        # before the training period began cannot be valid for it.
        rows = [_row(start="2022-09", end="2024-08", consent_cv="2020-01-01")]
        with self.assertRaises(CvDataError):
            cv_build.validate_hqp_rows(rows, reference_year=2026, window_years=6)

    def test_section2_item_cap_exceeded_refused(self):
        # Q2: contribution_types.json caps section 2 at 10 items.
        model = _model()
        model["sections"]["2"]["items"] = [
            dict(model["sections"]["2"]["items"][0], date=str(year)) for year in range(2015, 2026)
        ]
        self.assertEqual(len(model["sections"]["2"]["items"]), 11)
        with self.assertRaises(CvDataError):
            cv_build.assert_inline_model(model)

    def test_section2_exactly_ten_items_accepted(self):
        # Mutation survivor (reviewer, 2026-10-09): the existing cap test
        # only proves 11 is refused; exactly 10 (the cap itself) must stay
        # on the accepted side of the ">" comparison.
        model = _model()
        model["sections"]["2"]["items"] = [
            dict(model["sections"]["2"]["items"][0], date=str(year)) for year in range(2015, 2025)
        ]
        self.assertEqual(len(model["sections"]["2"]["items"]), 10)
        cv_build.assert_inline_model(model)  # must not raise

    def test_unknown_top_level_model_key_named(self):
        # Q3a: a stray top-level key (not caller-controlled free text - the
        # model's top level is a fixed schema) is named in the refusal.
        model = _model()
        model["funder"] = "nserc"
        with self.assertRaises(CvDataError) as ctx:
            cv_build.assert_inline_model(model)
        self.assertIn("funder", str(ctx.exception))

    def test_section_as_int_refused_not_500(self):
        # R1 (reviewer, 2026-10-09, regression from the Q3 fix): the
        # isinstance(dict) check ran AFTER set(section), so a truthy
        # non-dict section reached set()/join() and crashed with a bare
        # TypeError instead of a clean CvDataError.
        model = _model()
        model["sections"]["1"] = 1
        with self.assertRaises(CvDataError):
            cv_build.assert_inline_model(model)

    def test_section_as_list_refused_not_500(self):
        model = _model()
        model["sections"]["1"] = [1]
        with self.assertRaises(CvDataError):
            cv_build.assert_inline_model(model)

    def test_section_as_bool_refused_not_500(self):
        model = _model()
        model["sections"]["1"] = True
        with self.assertRaises(CvDataError):
            cv_build.assert_inline_model(model)

    def test_section_as_string_refused_without_echoing_its_characters(self):
        # The measured 500-adjacent defect: set("Jean Tremblay") iterates
        # the string's CHARACTERS, and the old check order let that reach
        # the "unknown key(s): ..." message - caller free text, scrambled
        # but recoverable, echoed through a section value.
        model = _model()
        model["sections"]["1"] = "Jean Tremblay"
        with self.assertRaises(CvDataError) as ctx:
            cv_build.assert_inline_model(model)
        self.assertNotIn("Jean", str(ctx.exception))
        self.assertNotIn("Tremblay", str(ctx.exception))

    def test_section_as_falsy_int_refused_not_silently_dropped(self):
        # Low-3 (reviewer, 2026-10-09, owner decision: refuse falsy non-dict
        # too). `0`/`False`/""/[]/{} used to be read as "no section" by the
        # old `if not section: continue` and silently dropped the section
        # from the rendered CV with no error - only an absent key or an
        # explicit null is "no section" now.
        for falsy in (0, False, "", [], {}):
            model = _model()
            model["sections"]["1"] = falsy
            with self.assertRaises(CvDataError):
                cv_build.assert_inline_model(model)

    def test_section_absent_or_null_still_skipped(self):
        # The companion control: a section key that is entirely absent, or
        # explicitly null, is still read as "no section" rather than
        # refused - unchanged behaviour, not a new requirement.
        model = _model()
        del model["sections"]["3"]
        cv_build.assert_inline_model(model)  # must not raise
        model["sections"]["3"] = None
        cv_build.assert_inline_model(model)  # must not raise

    def test_mixed_digit_and_free_text_section_keys_names_only_the_digit(self):
        # Low-1 (reviewer, 2026-10-09, mutation M8 survivor): `all(...)` at
        # the digit-shaped check must stay `all`, not `any` - a request
        # carrying BOTH a digit-shaped typo and a free-text key must not
        # let the digit case license naming the free-text one too.
        model = _model()
        model["sections"]["4"] = model["sections"].pop("3")
        model["sections"]["SECRET"] = {"title": "X"}
        with self.assertRaises(CvDataError) as ctx:
            cv_build.assert_inline_model(model)
        self.assertNotIn("SECRET", str(ctx.exception))

    def test_unknown_numeric_section_key_two_digits_named(self):
        # L1 (reviewer, 2026-10-09): the digit-shaped exception is capped
        # at two ASCII digits, not any length `str.isdigit()` would accept.
        model = _model()
        model["sections"]["12"] = model["sections"].pop("3")
        with self.assertRaises(CvDataError) as ctx:
            cv_build.assert_inline_model(model)
        self.assertIn("12", str(ctx.exception))

    def test_unknown_section_key_three_digits_not_named(self):
        # L1: three ASCII digits is past the 1-2 digit cap, so it is read
        # the same as free text and stays unnamed.
        model = _model()
        model["sections"]["123"] = model["sections"].pop("3")
        with self.assertRaises(CvDataError) as ctx:
            cv_build.assert_inline_model(model)
        self.assertNotIn("123", str(ctx.exception))

    def test_unknown_section_key_long_digit_string_not_named(self):
        # L1: a long digit string (a student number, say) must not be
        # read as a structural typo just because it is all digits.
        model = _model()
        model["sections"]["123456789"] = model["sections"].pop("3")
        with self.assertRaises(CvDataError) as ctx:
            cv_build.assert_inline_model(model)
        self.assertNotIn("123456789", str(ctx.exception))

    def test_unknown_section_key_unicode_digit_not_named(self):
        # L1: str.isdigit() accepted non-ASCII digits (Extended Arabic-Indic
        # "4" below); the ASCII-only regex does not.
        model = _model()
        model["sections"]["۴"] = model["sections"].pop("3")
        with self.assertRaises(CvDataError) as ctx:
            cv_build.assert_inline_model(model)
        self.assertNotIn("۴", str(ctx.exception))

    def test_unknown_key_inside_section_named(self):
        # Q3, section level (distinct from an unknown SECTION key like "4"
        # above): a field inside a present section, not caller-controlled
        # free text - the section's own fixed vocabulary - so it is named.
        model = _model()
        model["sections"]["1"]["funding_source"] = "CRSNG"
        with self.assertRaises(CvDataError) as ctx:
            cv_build.assert_inline_model(model)
        self.assertIn("funding_source", str(ctx.exception))

    def test_unknown_numeric_section_key_named(self):
        # Q3b: a plain structural typo ("4" instead of "1"/"2"/"3") is a
        # digit-shaped key, safe to name - the companion test
        # test_prose_file_refusal_does_not_echo_the_section_key_either pins
        # the opposite case, where the stray key is free text and must not
        # be named.
        model = _model()
        model["sections"]["4"] = model["sections"].pop("3")
        with self.assertRaises(CvDataError) as ctx:
            cv_build.assert_inline_model(model)
        self.assertIn("4", str(ctx.exception))

    def test_unknown_item_key_named(self):
        # Q3d: an item field name is part of the caller's own fixed
        # vocabulary, not free text, so it is named.
        model = _model()
        model["sections"]["2"]["items"][0]["funding_source"] = "CRSNG"
        with self.assertRaises(CvDataError) as ctx:
            cv_build.assert_inline_model(model)
        self.assertIn("funding_source", str(ctx.exception))

    def test_hqp_list_non_bool_refused(self):
        # A truthy non-bool such as "no" would otherwise read as True.
        model = _model()
        model["sections"]["3"]["hqp_list"] = "no"
        with self.assertRaises(CvDataError):
            cv_build.assert_inline_model(model)

    def test_item_missing_description_refused(self):
        # F2 residue: the existing test covers a wrong-typed description;
        # a missing key must be refused the same way.
        model = _model()
        del model["sections"]["2"]["items"][0]["description"]
        with self.assertRaises(CvDataError):
            cv_build.assert_inline_model(model)

    def test_item_empty_description_refused(self):
        model = _model()
        model["sections"]["2"]["items"][0]["description"] = "   "
        with self.assertRaises(CvDataError):
            cv_build.assert_inline_model(model)

    def test_item_not_a_dict_refused(self):
        # M-A: an item list carrying a bare string rather than an object.
        model = _model()
        model["sections"]["2"]["items"] = ["not-an-object"]
        with self.assertRaises(CvDataError):
            cv_build.assert_inline_model(model)

    def test_start_with_unicode_digit_refused(self):
        # L1: Python's \d matches non-ASCII digit characters (e.g.
        # Arabic-Indic) under default Unicode mode; the date regexes use
        # the ASCII-only [0-9] class instead.
        rows = [_row(start="۲۰۲۲-09")]  # Extended Arabic-Indic "2022"
        with self.assertRaises(CvDataError):
            cv_build.validate_hqp_rows(rows, reference_year=2026, window_years=6)

    def test_consent_with_trailing_newline_refused(self):
        # L1: .fullmatch() anchors to the whole string, so a value carrying
        # a trailing newline must not slip through a $-anchored pattern.
        rows = [_row(end="2024-08", consent_cv="2026-09-01\n")]
        with self.assertRaises(CvDataError):
            cv_build.validate_hqp_rows(rows, reference_year=2026, window_years=6)

    def test_end_with_trailing_newline_refused(self):
        # Mutation survivor (reviewer, 2026-10-09): the trailing-newline
        # case was proven for `start` only; `end` shares the same regex
        # and must be checked the same way.
        rows = [_row(end="2024-08\n")]
        with self.assertRaises(CvDataError):
            cv_build.validate_hqp_rows(rows, reference_year=2026, window_years=6)

    def test_reference_year_bounds_come_from_config_not_hardcoded(self):
        # C7 (reviewer, 2026-10-09; Low-2, SAME finding re-raised 2026-10-09
        # round 5, mutation N4 survived the first version of this test): a
        # row whose OWN dates are far in the future (start="2049-09") is
        # refused by the "start must not be after reference_year" check
        # REGARDLESS of which reference_year bound is in effect, so the
        # first version of this test passed under BOTH the real code and a
        # mutant that hardcodes the module's fallback [2000, 2100] instead
        # of reading `contribution_types.json` - proving nothing. The row
        # below is valid for reference_year 2026 under EVERY other check
        # (start/end ordering, consent), so the only thing that can make
        # reference_year=2026 fail is the reference_year BOUND itself: the
        # configured [2050, 2050] refuses it, the module's own [2000, 2100]
        # fallback would not.
        import json
        import tempfile

        types = json.loads(
            Path(cv_build.__file__).with_name("contribution_types.json").read_text(encoding="utf-8"))
        types["reference_year_bounds"] = {"min": 2050, "max": 2050}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "types.json"
            path.write_text(json.dumps(types), encoding="utf-8")
            model = _hqp_model()
            rows = [_row(start="2020-09", end=None, consent_cv="2020-09-01")]
            with self.assertRaises(CvDataError):
                cv_build.render_latex(model, types_path=path, hqp={"rows": rows, "reference_year": 2026})
            cv_build.render_latex(model, types_path=path, hqp={"rows": rows, "reference_year": 2050})

    def test_latex_escaping(self):
        model = _hqp_model()
        source = cv_build.render_latex(
            model, hqp={"rows": [_row(name="A & B_C")], "reference_year": 2026})
        self.assertIn(r"\textbf{A \& B\_C}", source)

    def test_position_rendered(self):
        model = _hqp_model()
        rows = [
            _row(name="Étudiante Beta", end="2024-08",
                 current_position="Poste fictif", current_employer="Employeur fictif"),
            _row(name="Étudiant Gamma", end=None),
        ]
        source = cv_build.render_latex(model, hqp={"rows": rows, "reference_year": 2026})
        self.assertIn("Poste fictif, Employeur fictif", source)
        self.assertIn("en cours", source)

    def test_order_deterministic(self):
        rows_a = [_row(name="Étudiante Beta", end="2024-08"), _row(name="Étudiante Alpha", end="2023-01")]
        rows_b = list(reversed(rows_a))
        model = _hqp_model()
        source_a = cv_build.render_latex(model, hqp={"rows": rows_a, "reference_year": 2026})
        source_b = cv_build.render_latex(model, hqp={"rows": rows_b, "reference_year": 2026})
        self.assertEqual(source_a, source_b)

    def test_english_labels(self):
        model = _hqp_model(language="en")  # default portal_variant: frq_old_portal, 5-year window
        source = cv_build.render_latex(model, hqp={"rows": [_row(end=None)], "reference_year": 2026})
        self.assertIn("ongoing", source)
        self.assertIn("HQP trained in the last 5 years", source)

    def test_recent_heading_shows_the_funder_specific_window(self):
        model = _hqp_model(portal_variant="tri_agency")
        source = cv_build.render_latex(model, hqp={"rows": [_row(end=None)], "reference_year": 2026})
        self.assertIn("PHQ formés au cours des 6 dernières années", source)

    def test_empty_lists_use_none_label(self):
        model = _hqp_model()
        source = cv_build.render_latex(model, hqp={"rows": [_row(end="2024-08")], "reference_year": 2026})
        archive_idx = source.index("Archive")
        self.assertIn("s.o.", source[archive_idx:])

    def test_hqp_headings_render_as_subsections_of_section_3(self):
        # The recent/archive lists are section-3 content: rendering them as
        # \section* would give the document five top-level sections instead
        # of the format's required three.
        model = _hqp_model()
        source = cv_build.render_latex(model, hqp={"rows": [_row()], "reference_year": 2026})
        self.assertEqual(source.count(r"\section*{"), 3)
        self.assertIn(r"\subsection*{", source)

    def test_render_model_missing_portal_variant_refused(self):
        with self.assertRaises(CvDataError) as ctx:
            cv_build.assert_inline_model({"sections": {}})
        self.assertIn("portal_variant", str(ctx.exception))

    def test_render_model_missing_section_title_refused(self):
        model = _model()
        model["sections"]["1"] = {"prose": "no title here"}
        with self.assertRaises(CvDataError) as ctx:
            cv_build.assert_inline_model(model)
        self.assertIn("1", str(ctx.exception))


class TestInline(unittest.TestCase):
    def _write(self, tmp, model, files):
        import json as _json

        for name, content in files.items():
            (Path(tmp) / name).write_text(content, encoding="utf-8")
        path = Path(tmp) / "cv_model.json"
        path.write_text(_json.dumps(model), encoding="utf-8")
        return path

    def test_inline_resolves_prose_file(self):
        import tempfile

        model = _model()
        model["sections"]["1"] = {"title": "Déclaration personnelle", "prose_file": "s1.tex"}
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(tmp, model, {"s1.tex": r"\textbf{Parcours.} Texte."})
            result = cv_build.inline_model(path)
        self.assertEqual(result["sections"]["1"]["prose"], r"\textbf{Parcours.} Texte.")
        self.assertNotIn("prose_file", result["sections"]["1"])
        cv_build.assert_inline_model(result)

    def test_inline_escape_refused(self):
        import tempfile

        model = _model()
        model["sections"]["1"] = {"title": "X", "prose_file": "../x.tex"}
        with tempfile.TemporaryDirectory() as tmp:
            inner = Path(tmp) / "inner"
            inner.mkdir()
            (Path(tmp) / "x.tex").write_text("secret", encoding="utf-8")
            model_path = self._write(inner, model, {})
            out_path = inner / "out.json"
            with patch.object(sys, "argv", [
                    "cv_build.py", "inline", "--model", str(model_path), "--out", str(out_path)]):
                code = cv_build.main()
        self.assertEqual(code, 1)
        self.assertFalse(out_path.exists())

    def test_inline_refuses_student_rows(self):
        import tempfile

        model = _model()
        model["sections"]["3"]["hqp_rows"] = []
        with tempfile.TemporaryDirectory() as tmp:
            model_path = self._write(tmp, model, {})
            out_path = Path(tmp) / "out.json"
            with patch.object(sys, "argv", [
                    "cv_build.py", "inline", "--model", str(model_path), "--out", str(out_path)]):
                code = cv_build.main()
        self.assertEqual(code, 2)
        self.assertFalse(out_path.exists())

    def test_inline_same_path_refused(self):
        import tempfile

        model = _model()
        with tempfile.TemporaryDirectory() as tmp:
            model_path = self._write(tmp, model, {})
            with patch.object(sys, "argv", [
                    "cv_build.py", "inline", "--model", str(model_path), "--out", str(model_path)]):
                code = cv_build.main()
        self.assertEqual(code, 2)

    def test_inline_overwrite_refused_without_yes(self):
        import tempfile

        model = _model()
        with tempfile.TemporaryDirectory() as tmp:
            model_path = self._write(tmp, model, {})
            out_path = Path(tmp) / "out.json"
            out_path.write_text("original content", encoding="utf-8")
            with patch.object(sys, "argv", [
                    "cv_build.py", "inline", "--model", str(model_path), "--out", str(out_path)]):
                code = cv_build.main()
            self.assertEqual(code, 2)
            self.assertEqual(out_path.read_text(encoding="utf-8"), "original content")

    def test_inline_overwrite_allowed_with_yes(self):
        import tempfile

        model = _model()
        with tempfile.TemporaryDirectory() as tmp:
            model_path = self._write(tmp, model, {})
            out_path = Path(tmp) / "out.json"
            out_path.write_text("original content", encoding="utf-8")
            with patch.object(sys, "argv", [
                    "cv_build.py", "inline", "--model", str(model_path), "--out", str(out_path),
                    "--yes"]):
                code = cv_build.main()
            self.assertEqual(code, 0)
            self.assertNotEqual(out_path.read_text(encoding="utf-8"), "original content")

    def test_render_cli_unchanged(self):
        import tempfile

        model = _model()
        with tempfile.TemporaryDirectory() as tmp:
            model_path = self._write(tmp, model, {})
            out_base = Path(tmp) / "out"
            with patch.object(sys, "argv", [
                    "cv_build.py", "render", "--model", str(model_path), "--out", str(out_base),
                    "--target", "both"]):
                code = cv_build.main()
            self.assertEqual(code, 0)
            self.assertTrue(out_base.with_suffix(".tex").is_file())
            self.assertTrue(out_base.with_suffix(".txt").is_file())


if __name__ == "__main__":
    unittest.main()
