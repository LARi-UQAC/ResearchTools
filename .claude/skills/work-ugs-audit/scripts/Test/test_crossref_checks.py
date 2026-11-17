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
SETTINGS = {"right_zone_ratio": ZONE}
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


if __name__ == "__main__":
    unittest.main()
