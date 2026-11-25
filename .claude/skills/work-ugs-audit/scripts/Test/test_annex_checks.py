"""
test_annex_checks - the cross-reference checks in the annex and in the assemble step (Issue 122, plan 8 task 2, R9).

Offline: every PDF is built in the test with PyMuPDF from fictitious text (R34, R21). No report, no grade and
no student file is read. The labels are read from the shipped annex_labels.json, so the wording is checked
without being copied here.
"""
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(SCRIPTS.parent.parent / "figure-review" / "scripts" / "Test"))

import fitz  # noqa: E402
import pdf_annex  # noqa: E402
import ugs_assemble  # noqa: E402
from _pdf_fixtures import make_report  # noqa: E402

CHECK_IDS = ["figures_cited", "tables_cited", "figure_order", "table_order", "equation_order"]


def _labels(language: str) -> dict:
    """
    Purpose: Load the annex labels of one language from the shipped labels file.
    Inputs:
        language: str - "fr" or "en".
    Outputs:
        dict - the labels of that language, as pdf_annex.load_labels returns them.
    Raises:
        None.
    """
    return pdf_annex.load_labels(pdf_annex.DEFAULT_LABELS, language)


def _flat(text: str) -> str:
    """
    Purpose: Collapse whitespace so a label wrapped over two lines still matches.
    Inputs:
        text: str - text read from a page or an HTML string.
    Outputs:
        str - the text with every run of whitespace replaced by one space.
    Raises:
        None.
    """
    return " ".join(text.split())


class TestChecksTable(unittest.TestCase):
    """
    Purpose: The table of the five checks in the annex, in both languages, numbers only.
    """

    def test_checks_table_in_french_and_english(self):
        """
        Purpose: The check label and the status label come from the labels of the report language only.
        Inputs: none.
        Outputs: none (assertions).
        Raises: AssertionError when a label of the other language appears or the label is missing.
        """
        checks = [{"id": "figures_cited", "status": "not_ok",
                   "detail": {"missing": [[2, 1], [2, 3]], "repeated": [], "skipped": []}}]
        for language, other in (("fr", "en"), ("en", "fr")):
            labels = _labels(language)
            html = pdf_annex.render_checks(checks, labels)
            self.assertIn(labels["check_values"]["figures_cited"], html)
            self.assertIn(labels["check_status_values"]["not_ok"], html)
            self.assertNotIn(_labels(other)["check_values"]["figures_cited"], html)

    def test_not_applicable_label(self):
        """
        Purpose: A check with no element is shown with the not-applicable label, never ok or not ok.
        Inputs: none.
        Outputs: none (assertions).
        Raises: AssertionError when the label is absent or another status label appears.
        """
        checks = [{"id": "tables_cited", "status": "not_applicable", "detail": {"missing": []}}]
        labels = _labels("en")
        html = pdf_annex.render_checks(checks, labels)
        self.assertIn(labels["check_status_values"]["not_applicable"], html)
        self.assertNotIn(labels["check_status_values"]["ok"], html)
        self.assertNotIn(labels["check_status_values"]["not_ok"], html)

    def test_numbers_only_in_the_table(self):
        """
        Purpose: The table prints the numbers of the detail, formatted with dots, and nothing else from it.
            A detail key with no label is a named refusal, and its text is not echoed.
        Inputs: none.
        Outputs: none (assertions).
        Raises: AssertionError when a number is printed wrongly or the secret text reaches the output.
        """
        labels = _labels("en")
        checks = [{"id": "figures_cited", "status": "not_ok",
                   "detail": {"missing": [[2, 1], (2, 3)], "repeated": [], "skipped": []}}]
        html = pdf_annex.render_checks(checks, labels)
        self.assertIn("2.1, 2.3", html)
        leaking = [{"id": "figures_cited", "status": "not_ok",
                    "detail": {"missing": [[2, 1]], "quote": "SECRET WORDING OF THE REPORT"}}]
        with self.assertRaises(pdf_annex.AnnexError) as ctx:
            pdf_annex.render_checks(leaking, labels)
        self.assertNotIn("SECRET", str(ctx.exception))

    def test_unknown_check_id_is_refused(self):
        """
        Purpose: A check id with no label is a named refusal (R3), not a blank row.
        Inputs: none.
        Outputs: none (assertions).
        Raises: AssertionError when no AnnexError is raised.
        """
        with self.assertRaises(pdf_annex.AnnexError):
            pdf_annex.render_checks([{"id": "unknown_check", "status": "ok", "detail": {}}], _labels("en"))

    def test_build_html_fills_the_checks_placeholder(self):
        """
        Purpose: build_html puts the checks table in the CHECKS placeholder and keeps the old call unchanged.
        Inputs: none.
        Outputs: none (assertions).
        Raises: AssertionError when the placeholder is not filled or the old call changes.
        """
        labels = _labels("en")
        template = "A {{ROWS}} B {{CHECKS}} C {{TOTAL}}"
        html = pdf_annex.build_html(template, "rows", "R01", 1, "1", labels, checks_html="<p>X</p>")
        self.assertIn("<p>X</p>", html)
        self.assertNotIn("{{CHECKS}}", html)
        old = pdf_annex.build_html("T {{ROWS}} {{TOTAL}}", "rows", "R01", 1, "1")
        self.assertEqual(old, "T rows 1")


class TestAssembleChecks(unittest.TestCase):
    """
    Purpose: The assemble step writes checks.json in the loop folder and passes the checks to the annex.
    """

    def setUp(self):
        """
        Purpose: Build a work folder: <work>/R01 holds the element and metadata files, <work>/loop-1/R01 the loop.
        Inputs: none.
        Outputs: none (sets self.work, self.source, self.loop_dir, self.src_pdf, self.settings).
        Raises: None.
        """
        self.tmp = Path(tempfile.mkdtemp())
        self.work = self.tmp / "work"
        self.source = self.work / "R01"
        self.loop_dir = self.work / "loop-1" / "R01"
        self.source.mkdir(parents=True)
        self.loop_dir.mkdir(parents=True)
        self.src_pdf = self.loop_dir / "source.pdf"
        make_report(self.src_pdf, [{"text": "Figure 2.1 shows the layout."}])
        self.rubric = {
            "assessment_type": "lab_report",
            "total_points": 100,
            "items": [
                {"id": "I01", "title": "Intro", "max_points": 50, "criteria": [], "checklist": []},
                {"id": "I02", "title": "Body", "max_points": 50, "criteria": [], "checklist": []},
            ],
        }
        grade = {"report_id": "R01", "loop": 1, "items": [
            {"item_id": "I01", "status": "rated", "score": 45.0, "comment": "Good", "evidence": []},
            {"item_id": "I02", "status": "rated", "score": 40.0, "comment": "Fine", "evidence": []},
        ]}
        (self.loop_dir / "grade.json").write_text(json.dumps(grade), encoding="utf-8")
        self.settings = {
            "colors": {"technical": "#0000ff", "figure": "#00ff00", "reference": "#ff0000", "language": "#000000"},
            "author": "Fictitious Author",
            "quote_chars": 10,
            "url_timeout_s": 5,
            "max_retries": 2,
            "patterns": [],
            "ref_comments": {},
            "annex_template": pdf_annex.DEFAULT_TEMPLATE.read_text(encoding="utf-8"),
        }

    def tearDown(self):
        """
        Purpose: Remove the temporary folders of the test.
        Inputs: none.
        Outputs: none.
        Raises: None.
        """
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write_source_files(self, with_element: bool, excluded: list):
        """
        Purpose: Write the element file and the metadata of the fictitious report in the source folder.
        Inputs:
            with_element: bool - when True, one figure titled "Figure 2.1" is written.
            excluded: list - the excluded pages written in the metadata, as {"page", "reason"} records.
        Outputs: none.
        Raises: None.
        """
        if with_element:
            elements = [{
                "element_id": "F01", "element_type": "figure", "page": 1, "rect": [72, 72, 300, 300],
                "file": "F01.png", "title": {"text": "Figure 2.1 Layout", "position": "below",
                                              "alignment": "center"},
                "legend": "", "notes": [], "caption": "Figure 2.1 Layout",
            }]
            (self.source / "elements.json").write_text(json.dumps(elements), encoding="utf-8")
        meta = {"language": "en", "excluded_pages": excluded, "text_quality": {}}
        (self.source / "report_meta.json").write_text(json.dumps(meta), encoding="utf-8")

    def _assemble(self, pages: list) -> dict:
        """
        Purpose: Run the assemble step on the fictitious report with the given page texts.
        Inputs:
            pages: list - the text of each page.
        Outputs:
            dict - the summary returned by ugs_assemble.assemble_report.
        Raises: None (errors propagate to the test).
        """
        return ugs_assemble.assemble_report(
            self.src_pdf, self.loop_dir, "R01", 1, self.rubric, pages, "en", self.settings, fetch=None)

    def _checks(self) -> list:
        """
        Purpose: Read the checks file written in the loop folder.
        Inputs: none.
        Outputs:
            list - the five check entries.
        Raises: None.
        """
        return json.loads((self.loop_dir / "checks.json").read_text(encoding="utf-8"))

    def test_assemble_writes_checks_file_and_annex_section(self):
        """
        Purpose: checks.json holds the five entries and the annex prints the check labels.
        Inputs: none.
        Outputs: none (assertions).
        Raises: AssertionError when the file or the annex section is missing.
        """
        self._write_source_files(with_element=True, excluded=[])
        self._assemble(["Figure 2.1 shows the layout."])
        checks = self._checks()
        # N5 adds the citation_placement row after the five cross-reference checks.
        self.assertEqual([c["id"] for c in checks], list(CHECK_IDS) + ["citation_placement"])
        self.assertEqual(checks[0]["status"], "ok")
        labels = _labels("en")
        with fitz.open(str(self.loop_dir / "annotated.pdf")) as doc:
            text = _flat(" ".join(doc[i].get_text() for i in range(doc.page_count)))
        self.assertIn(_flat(labels["check_values"]["figures_cited"]), text)

    def test_assemble_without_element_file_marks_checks_not_applicable(self):
        """
        Purpose: With no element file the figure and table checks are not applicable and the step still runs.
        Inputs: none.
        Outputs: none (assertions).
        Raises: AssertionError when a figure check is not not_applicable or checks.json is missing.
        """
        self._write_source_files(with_element=False, excluded=[])
        self._assemble(["A body page without any figure."])
        checks = {c["id"]: c for c in self._checks()}
        self.assertEqual(checks["figures_cited"]["status"], "not_applicable")
        self.assertEqual(checks["tables_cited"]["status"], "not_applicable")
        self.assertEqual(checks["figure_order"]["status"], "not_applicable")

    def test_excluded_page_is_not_searched_by_assemble(self):
        """
        Purpose: A figure cited only on an excluded page is not found in the text, so the citation check fails.
        Inputs: none.
        Outputs: none (assertions).
        Raises: AssertionError when the citation on the excluded page still counts.
        """
        self._write_source_files(with_element=True, excluded=[{"page": 1, "reason": "cover"}])
        self._assemble(["Figure 2.1 shows the layout.", "A body page that cites nothing."])
        checks = {c["id"]: c for c in self._checks()}
        self.assertEqual(checks["figures_cited"]["status"], "not_ok")
        self.assertEqual(checks["figures_cited"]["detail"]["missing"], [[2, 1]])

    def test_excluded_note_names_pages_and_translated_reasons(self):
        """
        Purpose: The excluded-pages note lists each page with its reason in the report language.
        Inputs: none.
        Outputs: none (assertions).
        Raises: AssertionError when a page or a reason is missing from the note, or a raw code appears.
        """
        labels = _labels("fr")
        excluded = [{"page": 1, "reason": "cover"}, {"page": 5, "reason": "signature_table"}]
        note = ugs_assemble.build_excluded_note(excluded, labels)
        self.assertIn("1", note)
        self.assertIn("5", note)
        self.assertIn(labels["excluded_reason_values"]["cover"], note)
        self.assertIn(labels["excluded_reason_values"]["signature_table"], note)
        self.assertNotIn("signature_table", note)
        self.assertEqual(ugs_assemble.build_excluded_note([], labels), "")


class TestCitationPlacement(unittest.TestCase):
    """N5: a row of checks.json and one annotation per misplaced citation, labels in the report language."""

    PAGES = ["Plain text with a claim. [1] and another. [2, 3].", "Clean text [4]. Also fine (see 3.5 [5])."]

    def test_citation_placement_row_counts_occurrences(self):
        row = ugs_assemble.citation_placement_row(self.PAGES, "en")
        self.assertEqual(row["id"], "citation_placement")
        self.assertEqual(row["status"], "not_ok")
        self.assertEqual(row["detail"], {"count": 2})

    def test_citation_placement_row_ok_without_occurrence(self):
        row = ugs_assemble.citation_placement_row(["Clean text [4]."], "en")
        self.assertEqual(row["status"], "ok")
        self.assertEqual(row["detail"], {"count": 0})

    def test_citation_row_renders_in_the_annex_with_its_label(self):
        row = ugs_assemble.citation_placement_row(self.PAGES, "fr")
        labels = pdf_annex.load_labels(pdf_annex.DEFAULT_LABELS, "fr")
        html_text = pdf_annex.render_checks([row], labels)
        self.assertIn(labels["check_values"]["citation_placement"], html_text)
        self.assertIn("2", html_text)

    def test_body_text_before_the_reference_heading_is_kept(self):
        """F6: the page holding the reference heading keeps its body text before the heading."""
        pages = ["Intro page text. [1]", "Body claim here. [2] ends.\nReferences\n[1] Fictitious Author, Title."]
        body = ugs_assemble._body_pages(pages)
        self.assertEqual(len(body), 2)
        self.assertIn("Body claim here. [2] ends.", body[1])
        self.assertNotIn("Fictitious Author", body[1])

    def test_each_misplaced_citation_is_annotated(self):
        annotations = ugs_assemble.citation_annotations(self.PAGES, "fr")
        self.assertEqual([(a["page"], a["quote"]) for a in annotations],
                         [(1, "claim. [1]"), (1, "another. [2, 3]")])
        for annotation in annotations:
            self.assertEqual(annotation["kind"], "citation")
            self.assertEqual(annotation["code"], "CIT")
            self.assertTrue(annotation["comment"])


class TestNoDuplicateKeys(unittest.TestCase):
    """N2: every JSON data file of the skill loads with no duplicate key, which json would otherwise keep silently."""

    def test_every_assets_json_has_no_duplicate_key(self):
        import json
        assets = SCRIPTS.parent / "assets"
        refused = []

        def make_hook(name):
            def refuse_duplicates(pairs):
                seen = {}
                for key, value in pairs:
                    if key in seen:
                        refused.append(f"{name}: {key}")
                    seen[key] = value
                return seen
            return refuse_duplicates

        for path in sorted(assets.glob("*.json")):
            with self.subTest(file=path.name):
                json.loads(path.read_text(encoding="utf-8-sig"), object_pairs_hook=make_hook(path.name))
        self.assertEqual(refused, [])


if __name__ == "__main__":
    unittest.main()
