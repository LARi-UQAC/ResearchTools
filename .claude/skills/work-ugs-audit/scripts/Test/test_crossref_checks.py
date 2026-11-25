"""
Purpose: Offline tests for crossref_checks (Issue 122, plan 8 task 1, spec R9).
Pipeline stage: last step and annex of the work-ugs-audit pipeline.
Fictitious PDFs and text are built in each test with PyMuPDF (R34, R21). Nothing is read from a
report folder. Run as: python <this file>
"""

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent.parent
FIGURE_REVIEW_SCRIPTS = SCRIPTS_DIR.parent.parent / "figure-review" / "scripts"
FIGURE_REVIEW_ASSETS = SCRIPTS_DIR.parent.parent / "figure-review" / "assets"
CONFIG_PATH = SCRIPTS_DIR.parent / "assets" / "ugs_config.json"
for _folder in (SCRIPTS_DIR, FIGURE_REVIEW_SCRIPTS):
    if str(_folder) not in sys.path:
        sys.path.insert(0, str(_folder))

import fitz  # noqa: E402
import element_labels  # noqa: E402
import crossref_checks  # noqa: E402

MARKERS_PATH = FIGURE_REVIEW_ASSETS / "element_markers.json"
PAGE_WIDTH = 595.0
PAGE_HEIGHT = 842.0
ZONE = 0.8
MAX_GAP = 50
MAX_NUMBER = 100000
SETTINGS = {"right_zone_ratio": ZONE, "max_gap_numbers": MAX_GAP, "max_number": MAX_NUMBER}
RUN_IDS = ["figures_cited", "tables_cited", "figure_order", "table_order", "equation_order"]


def make_element(kind: str, title_text, page: int = 1) -> dict:
    """
    Purpose: Build an element record shaped like figure-review's extract_elements output.
    Inputs:
        kind: str - "figure", "table" or "logo".
        title_text: str or None - the title text, None for an element without a title.
        page: int - the 1-based page of the element.
    Outputs:
        dict - an element record with the keys the checks read.
    Raises:
        None.
    """
    title = None
    if title_text is not None:
        title = {"text": title_text, "position": "below", "alignment": "center"}
    return {
        "element_id": f"{kind[:1].upper()}{page:02d}",
        "element_type": kind,
        "page": page,
        "rect": [50.0, 100.0, 300.0, 250.0],
        "file": "x.png",
        "title": title,
        "legend": "",
        "notes": [],
        "caption": title_text,
    }


def make_pdf(path: Path, pages: list) -> Path:
    """
    Purpose: Write a fictitious PDF whose pages carry text at known positions.
    Inputs:
        path: Path - the PDF file to write.
        pages: list - one list per page of (x, y, text) tuples in points.
    Outputs:
        Path - the file written.
    Raises:
        None.
    """
    doc = fitz.open()
    for items in pages:
        page = doc.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
        for x, y, text in items:
            page.insert_text((x, y), text, fontsize=11)
    doc.save(str(path))
    doc.close()
    return path


class CrossrefBase(unittest.TestCase):
    """Shared temporary folder and marker data for the crossref tests."""

    def setUp(self) -> None:
        """
        Purpose: Create a temporary folder and load the element markers.
        Inputs: None.
        Outputs: None. Sets self.tmp and self.markers.
        Raises: None.
        """
        self.tmp = Path(tempfile.mkdtemp(prefix="crossref_"))
        self.markers = element_labels.load_markers(MARKERS_PATH)

    def tearDown(self) -> None:
        """
        Purpose: Remove the temporary folder.
        Inputs: None.
        Outputs: None.
        Raises: None.
        """
        shutil.rmtree(self.tmp, ignore_errors=True)


class TestParseAndOrder(CrossrefBase):
    """Number parsing, tuple comparison and the figure and table order checks."""

    def test_chapter_numbers_compare_as_tuples(self) -> None:
        """
        Purpose: 2.1 < 2.2 < 3 and 2.9 < 2.10 compare as number tuples, not as text.
        Inputs: None.
        Outputs: None.
        Raises: AssertionError on a failed comparison.
        """
        self.assertEqual(crossref_checks.parse_number("2.3"), (2, 3))
        self.assertEqual(crossref_checks.parse_number("3"), (3,))
        self.assertLess(crossref_checks.parse_number("2.1"), crossref_checks.parse_number("2.2"))
        self.assertLess(crossref_checks.parse_number("2.2"), crossref_checks.parse_number("3"))
        self.assertLess(crossref_checks.parse_number("2.9"), crossref_checks.parse_number("2.10"))

    def test_figure_numbers_read_from_titles_in_document_order(self) -> None:
        """
        Purpose: element_numbers returns the figure numbers of the titles in document order and
            reads the marker word from the figure-review markers file (Fig. included).
        Inputs: None.
        Outputs: None.
        Raises: AssertionError on a wrong list.
        """
        elements = [
            make_element("figure", "Figure 2.1 Architecture"),
            make_element("table", "Tableau 2.1 Budget"),
            make_element("figure", "Fig. 2.2 Flux"),
            make_element("figure", None),
        ]
        self.assertEqual(crossref_checks.element_numbers(elements, "figure"), [(2, 1), (2, 2)])
        self.assertEqual(crossref_checks.element_numbers(elements, "table"), [(2, 1)])

    def test_no_figure_is_not_applicable(self) -> None:
        """
        Purpose: With no figure and no equation in the report, figure and equation checks are
            not_applicable, never ok or not_ok.
        Inputs: None.
        Outputs: None.
        Raises: AssertionError on a wrong status.
        """
        pdf = make_pdf(self.tmp / "plain.pdf", [[(72, 100, "Plain body text.")]])
        checks = crossref_checks.run_checks(pdf, ["Plain body text."], [], self.markers, SETTINGS, [])
        by_id = {c["id"]: c for c in checks}
        self.assertEqual(by_id["figures_cited"]["status"], "not_applicable")
        self.assertEqual(by_id["figure_order"]["status"], "not_applicable")
        self.assertEqual(by_id["tables_cited"]["status"], "not_applicable")
        self.assertEqual(by_id["table_order"]["status"], "not_applicable")
        self.assertEqual(by_id["equation_order"]["status"], "not_applicable")

    def test_skipped_and_repeated_numbers_are_listed(self) -> None:
        """
        Purpose: Figures numbered 1, 2, 2, 4 give not_ok and the detail lists the repeated
            and the skipped numbers.
        Inputs: None.
        Outputs: None.
        Raises: AssertionError on a wrong status or detail.
        """
        elements = [make_element("figure", f"Figure {n} Title") for n in ("1", "2", "2", "4")]
        pdf = make_pdf(self.tmp / "order.pdf", [[(72, 100, "Plain body text.")]])
        checks = crossref_checks.run_checks(pdf, ["Plain body text."], elements, self.markers, SETTINGS, [])
        order = {c["id"]: c for c in checks}["figure_order"]
        self.assertEqual(order["status"], "not_ok")
        self.assertEqual(order["detail"]["repeated"], [(2,)])
        self.assertEqual(order["detail"]["skipped"], [(3,)])

    def test_increasing_chapter_numbers_are_ok(self) -> None:
        """
        Purpose: 2.1, 2.2, 3.1 in document order give figure_order ok with empty lists.
        Inputs: None.
        Outputs: None.
        Raises: AssertionError on a wrong status.
        """
        elements = [make_element("figure", t) for t in ("Figure 2.1 A", "Figure 2.2 B", "Figure 3.1 C")]
        pdf = make_pdf(self.tmp / "ok.pdf", [[(72, 100, "Plain body text.")]])
        checks = crossref_checks.run_checks(pdf, ["Plain body text."], elements, self.markers, SETTINGS, [])
        order = {c["id"]: c for c in checks}["figure_order"]
        self.assertEqual(order["status"], "ok")
        self.assertEqual(order["detail"]["repeated"], [])
        self.assertEqual(order["detail"]["skipped"], [])


class TestCitations(CrossrefBase):
    """Citation detection in the text of the pages."""

    def test_title_line_alone_is_not_a_citation(self) -> None:
        """
        Purpose: A figure number that appears only in its own title line is not cited; the same
            number cited in a sentence is.
        Inputs: None.
        Outputs: None.
        Raises: AssertionError on a wrong set.
        """
        prefixes = self.markers["figure_prefixes"]
        self.assertEqual(crossref_checks.cited_numbers(["Figure 2.1 Architecture of the system"], prefixes), set())
        cited = crossref_checks.cited_numbers(
            ["Figure 2.1 Architecture of the system", "The layout, as shown in Figure 2.2, is simple."],
            prefixes,
        )
        self.assertEqual(cited, {(2, 2)})

    def test_figure_cited_check_reports_missing(self) -> None:
        """
        Purpose: A figure titled 2.1 and never cited in the text gives figures_cited not_ok with
            the number listed; citing it removes the finding.
        Inputs: None.
        Outputs: None.
        Raises: AssertionError on a wrong status or detail.
        """
        elements = [make_element("figure", "Figure 2.1 Architecture")]
        pdf = make_pdf(self.tmp / "cite.pdf", [[(72, 100, "Plain body text.")]])
        checks = crossref_checks.run_checks(pdf, ["Plain body text."], elements, self.markers, SETTINGS, [])
        cited = {c["id"]: c for c in checks}["figures_cited"]
        self.assertEqual(cited["status"], "not_ok")
        self.assertEqual(cited["detail"]["missing"], [(2, 1)])
        checks = crossref_checks.run_checks(
            pdf, ["Figure 2.1 Architecture", "See Figure 2.1 for details."], elements, self.markers, SETTINGS, []
        )
        self.assertEqual({c["id"]: c for c in checks}["figures_cited"]["status"], "ok")

    def test_table_cited_check_uses_table_prefixes(self) -> None:
        """
        Purpose: A table titled 1 is cited with the Table or Tableau word; the check is ok.
        Inputs: None.
        Outputs: None.
        Raises: AssertionError on a wrong status.
        """
        elements = [make_element("table", "Table 1 Results")]
        pdf = make_pdf(self.tmp / "tab.pdf", [[(72, 100, "Plain body text.")]])
        checks = crossref_checks.run_checks(
            pdf, ["Table 1 Results", "Tableau 1 montre les resultats."], elements, self.markers, SETTINGS, []
        )
        by_id = {c["id"]: c for c in checks}
        self.assertEqual(by_id["tables_cited"]["status"], "ok")
        self.assertEqual(by_id["table_order"]["status"], "ok")


class TestEquations(CrossrefBase):
    """Equation numbers found in the right zone of the pages."""

    def test_equation_numbers_found_in_the_right_zone(self) -> None:
        """
        Purpose: (1) and (2.1) placed beyond the right zone are found, in document order.
        Inputs: None.
        Outputs: None.
        Raises: AssertionError on a wrong list.
        """
        pdf = make_pdf(self.tmp / "eq.pdf", [[(100, 100, "x = y + z"), (520, 100, "(1)"),
                                              (100, 200, "a = b"), (520, 200, "(2.1)")]])
        self.assertEqual(crossref_checks.equation_numbers(pdf, [], SETTINGS), [(1,), (2, 1)])

    def test_year_in_parentheses_is_ignored(self) -> None:
        """
        Purpose: A year such as (2023) in body text, left of the zone, is not an equation number.
        Inputs: None.
        Outputs: None.
        Raises: AssertionError when the year is found.
        """
        pdf = make_pdf(self.tmp / "year.pdf", [[(100, 100, "As reported (2023) the flow rises."),
                                                (520, 150, "(3)")]])
        self.assertEqual(crossref_checks.equation_numbers(pdf, [], SETTINGS), [(3,)])

    def test_excluded_pages_are_not_searched(self) -> None:
        """
        Purpose: An equation on an excluded page (1-based) is not searched; without the exclusion
            it is found.
        Inputs: None.
        Outputs: None.
        Raises: AssertionError when the excluded page is searched.
        """
        pdf = make_pdf(self.tmp / "skip.pdf", [[(72, 100, "Cover text.")],
                                               [(520, 100, "(5)")]])
        self.assertEqual(crossref_checks.equation_numbers(pdf, [2], SETTINGS), [])
        self.assertEqual(crossref_checks.equation_numbers(pdf, [], SETTINGS), [(5,)])

    def test_equation_order_is_checked(self) -> None:
        """
        Purpose: Equation numbers 1, 3 give equation_order not_ok with 2 skipped.
        Inputs: None.
        Outputs: None.
        Raises: AssertionError on a wrong status or detail.
        """
        pdf = make_pdf(self.tmp / "eqorder.pdf", [[(520, 100, "(1)"), (520, 200, "(3)")]])
        checks = crossref_checks.run_checks(pdf, [""], [], self.markers, SETTINGS, [])
        eq = {c["id"]: c for c in checks}["equation_order"]
        self.assertEqual(eq["status"], "not_ok")
        self.assertEqual(eq["detail"]["skipped"], [(2,)])


class TestRunChecksContract(CrossrefBase):
    """The shape of the run_checks result and the configuration."""

    def test_detail_holds_numbers_only(self) -> None:
        """
        Purpose: Every entry has the ids in order, a status from the three allowed values, and a
            detail whose values are lists of number tuples; the result is JSON-serialisable.
        Inputs: None.
        Outputs: None.
        Raises: AssertionError on a shape violation.
        """
        elements = [make_element("figure", "Figure 1 A"), make_element("figure", "Figure 3 B"),
                    make_element("table", "Table 1 C")]
        pdf = make_pdf(self.tmp / "shape.pdf", [[(520, 100, "(1)")]])
        checks = crossref_checks.run_checks(pdf, ["Figure 1 shows A."], elements, self.markers, SETTINGS, [])
        self.assertEqual([c["id"] for c in checks], RUN_IDS)
        for check in checks:
            self.assertIn(check["status"], ("ok", "not_ok", "not_applicable"))
            self.assertIsInstance(check["detail"], dict)
            for values in check["detail"].values():
                self.assertIsInstance(values, list)
                for number in values:
                    self.assertIsInstance(number, tuple)
                    self.assertTrue(all(isinstance(part, int) for part in number))
        json.dumps(checks)

    def test_shipped_configuration_holds_the_ratio_with_provenance(self) -> None:
        """
        Purpose: checks.right_zone_ratio is in the shipped configuration, between 0 and 1, with a
            provenance text.
        Inputs: None.
        Outputs: None.
        Raises: AssertionError on a missing key or a bad value.
        """
        ratio = crossref_checks.load_settings(CONFIG_PATH)["right_zone_ratio"]
        self.assertTrue(0 < ratio < 1)
        raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        self.assertTrue(raw["checks.right_zone_ratio"]["provenance"])

    def test_missing_ratio_key_is_a_named_error(self) -> None:
        """
        Purpose: A configuration without checks.right_zone_ratio raises a named error naming the
            key and the file (R3); equation_numbers refuses settings without the key.
        Inputs: None.
        Outputs: None.
        Raises: AssertionError when no error is raised or the message is not named.
        """
        config = self.tmp / "config.json"
        config.write_text(json.dumps({"other.key": {"value": 1, "provenance": "x"}}), encoding="utf-8")
        with self.assertRaises(crossref_checks.CrossrefConfigError) as caught:
            crossref_checks.load_settings(config)
        self.assertIn("checks.right_zone_ratio", str(caught.exception))
        self.assertIn(str(config), str(caught.exception))
        pdf = make_pdf(self.tmp / "nokey.pdf", [[(520, 100, "(1)")]])
        with self.assertRaises(crossref_checks.CrossrefConfigError) as caught:
            crossref_checks.equation_numbers(pdf, [], {})
        self.assertIn("right_zone_ratio", str(caught.exception))


class TestGapAndNumberLimits(CrossrefBase):
    """The configured limits on a listed gap and on a number read from a title or a citation (proposal 2026-11-17)."""

    def test_huge_gap_is_capped_and_counted(self) -> None:
        """
        Purpose: Figures titled 1 and 99999, both under checks.max_number, leave a gap of 99997 numbers. The
            run finishes, the list holds at most checks.max_gap_numbers numbers, the first ones, and
            skipped_omitted holds the count of the numbers left out.
        Inputs: None.
        Outputs: None.
        Raises: AssertionError on a list longer than the cap or a wrong count.
        """
        elements = [make_element("figure", "Figure 1 A"), make_element("figure", "Figure 99999 B")]
        pdf = make_pdf(self.tmp / "gap.pdf", [[(72, 100, "Plain body text.")]])
        checks = crossref_checks.run_checks(pdf, ["Plain body text."], elements, self.markers, SETTINGS, [])
        order = {c["id"]: c for c in checks}["figure_order"]
        self.assertEqual(order["status"], "not_ok")
        self.assertLessEqual(len(order["detail"]["skipped"]), MAX_GAP)
        self.assertEqual(len(order["detail"]["skipped"]), MAX_GAP)
        self.assertEqual(order["detail"]["skipped"][0], (2,))
        self.assertEqual(order["detail"]["skipped"][-1], (MAX_GAP + 1,))
        self.assertEqual(order["detail"]["skipped_omitted"], (99999 - 1 - 1) - MAX_GAP)

    def test_small_gap_has_no_omitted_count(self) -> None:
        """
        Purpose: A gap that fits under checks.max_gap_numbers lists every number and carries no
            skipped_omitted key.
        Inputs: None.
        Outputs: None.
        Raises: AssertionError when the key is present or a number is lost.
        """
        elements = [make_element("figure", "Figure 1 A"), make_element("figure", "Figure 4 B")]
        pdf = make_pdf(self.tmp / "small.pdf", [[(72, 100, "Plain body text.")]])
        checks = crossref_checks.run_checks(pdf, ["Plain body text."], elements, self.markers, SETTINGS, [])
        order = {c["id"]: c for c in checks}["figure_order"]
        self.assertEqual(order["detail"]["skipped"], [(2,), (3,)])
        self.assertNotIn("skipped_omitted", order["detail"])

    def test_number_above_max_is_refused(self) -> None:
        """
        Purpose: A number above checks.max_number is refused: parse_number returns None for it, also for a
            digit string too long to convert, and a title or a citation holding it contributes no number.
        Inputs: None.
        Outputs: None.
        Raises: AssertionError when a refused number is read or when the run fails.
        """
        self.assertIsNone(crossref_checks.parse_number("1000000", MAX_NUMBER))
        self.assertIsNone(crossref_checks.parse_number(f"2.{MAX_NUMBER + 1}", MAX_NUMBER))
        self.assertIsNone(crossref_checks.parse_number("9" * 5000, MAX_NUMBER))
        self.assertEqual(crossref_checks.parse_number(str(MAX_NUMBER), MAX_NUMBER), (MAX_NUMBER,))
        prefixes = self.markers["figure_prefixes"]
        self.assertEqual(crossref_checks.cited_numbers(["See Figure 1000000."], prefixes, MAX_NUMBER), set())
        elements = [make_element("figure", "Figure 1 A"), make_element("figure", "Figure 1000000 B")]
        pdf = make_pdf(self.tmp / "refused.pdf", [[(72, 100, "Plain body text.")]])
        checks = crossref_checks.run_checks(pdf, ["Plain body text."], elements, self.markers, SETTINGS, [])
        by_id = {c["id"]: c for c in checks}
        self.assertEqual(by_id["figure_order"]["status"], "ok")
        self.assertEqual(by_id["figures_cited"]["detail"]["missing"], [(1,)])

    def test_missing_max_gap_key_is_named(self) -> None:
        """
        Purpose: A configuration without checks.max_gap_numbers raises a named CrossrefConfigError naming the
            key and the file (R3); run_checks refuses settings without it.
        Inputs: None.
        Outputs: None.
        Raises: AssertionError when no error is raised or the message is not named.
        """
        config = self.tmp / "config_no_gap.json"
        config.write_text(json.dumps({
            "checks.right_zone_ratio": {"value": ZONE, "provenance": "x"},
            "checks.max_number": {"value": MAX_NUMBER, "provenance": "x"},
        }), encoding="utf-8")
        with self.assertRaises(crossref_checks.CrossrefConfigError) as caught:
            crossref_checks.load_settings(config)
        self.assertIn("checks.max_gap_numbers", str(caught.exception))
        self.assertIn(str(config), str(caught.exception))
        pdf = make_pdf(self.tmp / "nogap.pdf", [[(72, 100, "Plain body text.")]])
        settings_without_gap = {"right_zone_ratio": ZONE, "max_number": MAX_NUMBER}
        with self.assertRaises(crossref_checks.CrossrefConfigError) as caught:
            crossref_checks.run_checks(pdf, [""], [], self.markers, settings_without_gap, [])
        self.assertIn("max_gap_numbers", str(caught.exception))

    def test_shipped_limits_are_positive_integers_with_provenance(self) -> None:
        """
        Purpose: checks.max_gap_numbers and checks.max_number are in the shipped configuration as positive
            integers, each with a provenance text.
        Inputs: None.
        Outputs: None.
        Raises: AssertionError on a missing key, a bad value or an empty provenance.
        """
        settings = crossref_checks.load_settings(CONFIG_PATH)
        self.assertGreater(settings["max_gap_numbers"], 0)
        self.assertGreater(settings["max_number"], 0)
        raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        self.assertTrue(raw["checks.max_gap_numbers"]["provenance"])
        self.assertTrue(raw["checks.max_number"]["provenance"])


class TestMisplacedCitations(unittest.TestCase):
    """N5: a numeric citation after the sentence's period is a finding; before the period it is correct."""

    ABBREVIATIONS = ["et al.", "al.", "etc.", "p.", "pp.", "fig.", "vol.", "no."]

    def _found(self, text):
        return crossref_checks.misplaced_citations([text], self.ABBREVIATIONS)

    def test_period_then_citation_is_found(self):
        found = self._found("The loop is stable. [5] Then it holds.")
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["page"], 1)
        self.assertEqual(found[0]["quote"], "stable. [5]")

    def test_citation_before_period_is_ok(self):
        self.assertEqual(self._found("The loop is stable [5]. Then it holds."), [])

    def test_no_space_and_list_and_ranges_are_found(self):
        for text in ("stable.[5]", "stable. [3, 4]", "stable. [2-4]", "stable. [2–4]"):
            with self.subTest(text=text):
                self.assertEqual(len(self._found(text)), 1)

    def test_abbreviation_before_citation_is_ok(self):
        self.assertEqual(self._found("As shown by Smith et al. [5] in the study."), [])
        self.assertEqual(self._found("Such cases, etc. [5] remain open."), [])

    def test_decimal_number_is_ok(self):
        self.assertEqual(self._found("The gain was 3.5 [2] in the test."), [])

    def test_quote_is_found_in_page_text(self):
        text = "First sentence. Second one ends here. [7] Third."
        found = self._found(text)
        self.assertEqual(len(found), 1)
        self.assertIn(found[0]["quote"], text)

    def test_each_occurrence_is_listed_with_its_page(self):
        found = crossref_checks.misplaced_citations(["A stable. [1]", "B ok [2].", "C stable. [3]"], self.ABBREVIATIONS)
        self.assertEqual([(f["page"], f["quote"]) for f in found], [(1, "stable. [1]"), (3, "stable. [3]")])

    def test_line_break_before_the_bracket_is_a_finding(self):
        """F6: a citation on the next line after the period is still after the period."""
        self.assertEqual(len(self._found("The loop is stable.\n[5] Then it holds.")), 1)

    def test_long_token_without_spaces_is_fast_and_clean(self):
        """F4: a 20000-character token with no space gives no finding, quickly (no quadratic scan)."""
        import time
        token = "a" * 20000
        started = time.perf_counter()
        found = self._found(token)
        self.assertLess(time.perf_counter() - started, 1.0)
        self.assertEqual(found, [])

    def test_missing_language_is_named(self):
        path = Path(tempfile.mkdtemp()) / "citation_rules.json"
        path.write_text('{"fr": {"value": ["al."], "provenance": "t"}}', encoding="utf-8")
        with self.assertRaises(crossref_checks.CrossrefConfigError) as ctx:
            crossref_checks.load_citation_rules("en", path)
        self.assertIn("en", str(ctx.exception))
        self.assertIn("citation_rules.json", str(ctx.exception))

    def test_shipped_rules_load_for_both_languages(self):
        self.assertIn("et al.", crossref_checks.load_citation_rules("en"))
        self.assertIn("p.", crossref_checks.load_citation_rules("fr"))


class TestAppendixCheck(unittest.TestCase):
    """Issue 126 plan 15 N4 and review round 1 I3: appendices listed in the contents are found after the references
    (fictitious text, R34). The settings are the data of front_matter.json: words, plural words and the id pattern."""

    SETTINGS = {"markers": ["Annexe", "Annexes", "Appendice", "Appendix", "Appendices"],
                "plural": ["Annexes", "Appendices"], "id_pattern": r"[A-Z]{1,4}|\d{1,2}"}

    def test_names_ignore_case_and_dash(self):
        toc = ["Table des matieres\nAnnexe A - Plans ........ 40"]
        end = ["References\nSource A.", "ANNEXE A\nPlans detailles"]
        result = crossref_checks.appendix_check(toc + end, [1], 2, self.SETTINGS)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["listed"], ["A"])
        self.assertEqual(result["present"], ["A"])

    def test_listed_but_missing_at_the_end(self):
        toc = ["Table des matieres\nAnnexe A - Plans ........ 40\nAnnexe B - Tableaux ........ 44"]
        end = ["References\nSource.", "Annexe A\nPlans"]
        result = crossref_checks.appendix_check(toc + end, [1], 2, self.SETTINGS)
        self.assertEqual(result["status"], "not_ok")
        self.assertEqual(result["listed_missing"], ["B"])

    def test_present_at_the_end_but_not_listed(self):
        toc = ["Table des matieres\nAnnexe A - Plans ........ 40"]
        end = ["References\nSource.", "Annexe A\nPlans", "Annexe C\nNotes"]
        result = crossref_checks.appendix_check(toc + end, [1], 2, self.SETTINGS)
        self.assertEqual(result["status"], "not_ok")
        self.assertEqual(result["unlisted_present"], ["C"])

    def test_none_listed_none_found_is_not_applicable(self):
        result = crossref_checks.appendix_check(["Table des matieres\n1 Intro ........ 3", "References\nSource."],
                                                [1], 2, self.SETTINGS)
        self.assertEqual(result["status"], "not_applicable")

    def test_body_mention_is_not_a_heading(self):
        toc = ["Table des matieres\nAnnexe A - Plans ........ 40"]
        body = ["Introduction. Voir l'annexe A pour les details."]
        end = ["References\nSource."]
        result = crossref_checks.appendix_check(toc + body + end, [1], 3, self.SETTINGS)
        self.assertEqual(result["status"], "not_ok")
        self.assertEqual(result["present"], [])
        self.assertEqual(result["listed_missing"], ["A"])

    def test_no_contents_found_is_not_applicable_with_reason(self):
        result = crossref_checks.appendix_check(["References\nSource.", "Annexe A\nPlans"], None, 1, self.SETTINGS)
        self.assertEqual(result["status"], "not_applicable")
        self.assertIn("contents", result["reason"])

    def test_no_reference_heading_is_not_applicable_with_reason(self):
        result = crossref_checks.appendix_check(["Table des matieres\nAnnexe A ........ 4"], [1], None, self.SETTINGS)
        self.assertEqual(result["status"], "not_applicable")
        self.assertIn("reference", result["reason"])

    def test_numbered_bold_heading_at_the_end_is_found(self):
        """Regression (Issue 126, real report): the heading reads '## **11. ANNEXE A: Plans**' or '## **Annexe 1**'."""
        toc = ["Table des matieres\nAnnexe A - Plans ........ 40\nAnnexe 1 ........ 41"]
        end = ["## **10. References**\nSource.", "## **11. ANNEXE A: Plans**\nDetail.", "## **Annexe 1**\nNotes."]
        result = crossref_checks.appendix_check(toc + end, [1], 2, self.SETTINGS)
        self.assertEqual(result["present"], ["A", "1"])
        self.assertEqual(result["status"], "ok")

    def test_mid_page_heading_in_a_joined_text_layer_is_found(self):
        """Review round 1 I3 (Issue 126): the text layer is one joined line; a heading inside it, followed by a title,
        is an appendix."""
        toc = ["Table des matieres Annexe A - Plans ........ 40 Annexe B - Notes ........ 44"]
        end = ["References Source. 11. ANNEXE A: Plans detailles 12. ANNEXE B : Notes sur les mesures"]
        result = crossref_checks.appendix_check(toc + end, [1], 2, self.SETTINGS)
        self.assertEqual(result["present"], ["A", "B"])
        self.assertEqual(result["status"], "ok")

    def test_a_mention_after_a_lowercase_word_is_not_a_heading(self):
        """Review round 1 I3 (Issue 126): 'voir l'annexe A' is a mention, even in a joined line."""
        toc = ["Table des matieres Annexe A - Plans ........ 40"]
        end = ["References Source. Le lecteur consultera l'annexe A: Plans fictifs pour verifier."]
        result = crossref_checks.appendix_check(toc + end, [1], 2, self.SETTINGS)
        self.assertEqual(result["present"], [])

    def test_plural_marker_with_a_page_number_lists_nothing(self):
        """Review round 1 I3 (Issue 126): 'Annexes 45' on the contents page is a page number, not an appendix id."""
        toc = ["Table des matieres\nAnnexes 45\nAnnexe A - Plans ........ 40"]
        end = ["References\nSource.", "Annexe A\nPlans"]
        result = crossref_checks.appendix_check(toc + end, [1], 2, self.SETTINGS)
        self.assertEqual(result["listed"], ["A"])
        self.assertEqual(result["status"], "ok")

    def test_the_id_pattern_is_read_from_the_settings(self):
        """Review round 1 I3 (Issue 126): the id pattern is data; a letters-only pattern refuses 'Annexe 1'."""
        settings = dict(self.SETTINGS, id_pattern=r"[A-Z]{1,4}")
        toc = ["Table des matieres\nAnnexe 1 ........ 41"]
        end = ["References\nSource.", "Annexe 1\nNotes"]
        result = crossref_checks.appendix_check(toc + end, [1], 2, settings)
        self.assertEqual(result["listed"], [])
        self.assertEqual(result["status"], "not_applicable")

if __name__ == "__main__":
    unittest.main()
