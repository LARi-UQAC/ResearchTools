"""
Offline tests of ugs_tables.py and of the `elements` parameter of ugs_figures.figures_report (Issue #122,
plan 4). Fictitious element records and a fixture PDF built with PyMuPDF (R34). No model call: vision is off.
"""
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import fitz

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent / "figure-review" / "scripts" / "Test"))

import ugs_figures
import ugs_tables
from _pdf_fixtures import make_report
from ugs_text import StepContext

FIGURE_SKILL = Path(__file__).resolve().parent.parent.parent.parent / "figure-review"
FIGURE_PROMPT = (FIGURE_SKILL / "prompts" / "figure.md").read_text(encoding="utf-8")
REAL_EXTRACT = ugs_figures.extract

PAGES = [
    {"text": "Figure 1 shows the plant and how it reacts.\n\nMore text.", "image": True, "caption": "Figure 1: The plant."},
    {"text": "Figure 2 shows the loop.\n\nMore text.", "image": True, "caption": "Figure 2: The loop."},
]

MARKDOWN_ALPHA = "| Name | Value |\n|---|---|\n| Alpha | 12 |\n| Beta | 13 |"
MARKDOWN_GAMMA = "| Name | Value |\n| :--- | ---: |\n| Gamma | 7 |"
MARKDOWN_LONG = "| Name | Value |\n|---|---|\n| Alphabetical trial | 12 |"
MARKDOWN_NUMERIC = "| Count | Total |\n|---|---|\n| 2 | 3 |"


def make_ctx():
    """Return a StepContext carrying the real figure prompt; no model is called with vision off."""
    return StepContext(prompts={"figure": FIGURE_PROMPT}, schemas={"figure": {}, "figure_set": {}}, levels={},
                       window_tokens=1000, reserve_tokens=100, count=lambda s: 10, grade_retries=1,
                       audit_retries=1, min_word_len=3)


def table(element_id, page, top, markdown):
    """Return a fictitious table element record."""
    return {"element_id": element_id, "element_type": "table", "page": page,
            "rect": [72.0, top, 500.0, top + 80.0], "file": f"{element_id}.png", "title": None,
            "legend": "", "notes": [], "caption": None, "markdown": markdown}


def figure(element_id, page, top, caption):
    """Return a fictitious figure element record."""
    return {"element_id": element_id, "element_type": "figure", "page": page,
            "rect": [72.0, top, 500.0, top + 200.0], "file": f"{element_id}.png", "title": None,
            "legend": "", "notes": [], "caption": caption, "markdown": None}


class TestUgsTables(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_enrich_adds_a_missing_table(self):
        tables = [table("T01", 1, 100.0, MARKDOWN_ALPHA)]
        out = ugs_tables.enrich_page_text("Some prose about the study.", tables)
        self.assertNotEqual(out, "Some prose about the study.")
        self.assertIn("## Table T01 (detected)", out)
        self.assertIn(MARKDOWN_ALPHA, out)
        self.assertIn("Some prose about the study.", out)

    def test_enrich_skips_a_table_already_in_the_text(self):
        # The anchor row must be long enough to prove the table is in the text (tables.min_anchor_chars).
        text = "The results were Alphabetical trial 12 and Beta 13 in the first trial."
        tables = [table("T01", 1, 100.0, MARKDOWN_LONG)]
        self.assertEqual(ugs_tables.enrich_page_text(text, tables, min_anchor_chars=12), text)

    def test_short_numeric_anchor_still_adds_the_table(self):
        text = "The sample of 23 students completed the trial."
        tables = [table("T01", 1, 100.0, MARKDOWN_NUMERIC)]
        out = ugs_tables.enrich_page_text(text, tables, min_anchor_chars=12)
        self.assertIn("## Table T01 (detected)", out)
        self.assertIn(MARKDOWN_NUMERIC, out)

    def test_missing_min_anchor_key_is_named(self):
        path = self.tmp / "ugs_config.json"
        path.write_text(json.dumps({"other.key": {"value": 1, "provenance": "fictitious"}}), encoding="utf-8")
        with self.assertRaises(ugs_tables.TablesError) as ctx:
            ugs_tables.load_min_anchor_chars(path)
        self.assertIn("tables.min_anchor_chars", str(ctx.exception))
        self.assertIn("ugs_config.json", str(ctx.exception))

    def test_shipped_min_anchor_key_is_read_with_provenance(self):
        value = ugs_tables.load_min_anchor_chars()
        self.assertIsInstance(value, int)
        self.assertGreater(value, 0)

    def test_enrich_empty_markdown_adds_nothing(self):
        text = "Prose only."
        self.assertEqual(ugs_tables.enrich_page_text(text, [table("T01", 1, 100.0, "")]), text)
        self.assertEqual(ugs_tables.enrich_page_text(text, [table("T02", 1, 100.0, "  \n ")]), text)

    def test_two_tables_in_reading_order(self):
        page_tables = [table("T02", 1, 500.0, MARKDOWN_GAMMA), table("T01", 1, 100.0, MARKDOWN_ALPHA),
                       table("T09", 2, 50.0, MARKDOWN_GAMMA)]
        on_page = ugs_tables.tables_on_page(page_tables, 1)
        self.assertEqual([t["element_id"] for t in on_page], ["T01", "T02"])
        out = ugs_tables.enrich_page_text("Prose.", on_page)
        self.assertIn("## Table T01 (detected)", out)
        self.assertIn("## Table T02 (detected)", out)
        self.assertLess(out.index("## Table T01"), out.index("## Table T02"))
        self.assertNotIn("T09", out)

    def test_figure_records_keep_only_figures_and_add_figure_id(self):
        elements = [figure("F02", 2, 100.0, "Figure 2: The loop."), table("T01", 1, 50.0, MARKDOWN_ALPHA),
                    figure("F01", 1, 300.0, "Figure 1: The plant."),
                    {"element_id": "L01", "element_type": "logo", "page": 1, "rect": [0.0, 0.0, 10.0, 10.0]}]
        records = ugs_tables.figure_records(elements)
        self.assertEqual([r["element_id"] for r in records], ["F01", "F02"])
        self.assertEqual([r["figure_id"] for r in records], ["F01", "F02"])
        self.assertTrue(all(r["element_type"] == "figure" for r in records))

    def test_load_elements_missing_file_is_empty(self):
        self.assertEqual(ugs_tables.load_elements(self.tmp / "elements.json"), [])

    def test_load_elements_bad_json_is_named(self):
        path = self.tmp / "elements.json"
        path.write_text("[{\"element_id\": ", encoding="utf-8")
        with self.assertRaises(ugs_tables.TablesError) as ctx:
            ugs_tables.load_elements(path)
        self.assertIn("elements.json", str(ctx.exception))

    def test_load_elements_not_a_list_is_named(self):
        path = self.tmp / "elements.json"
        path.write_text(json.dumps({"elements": []}), encoding="utf-8")
        with self.assertRaises(ugs_tables.TablesError):
            ugs_tables.load_elements(path)

    def test_figures_report_with_elements_never_extracts(self):
        pdf = make_report(self.tmp / "report.pdf", PAGES)
        with fitz.open(str(pdf)) as doc:
            pages = [page.get_text() for page in doc]
        elements = [figure("F01", 1, 300.0, "Figure 1: The plant."), table("T01", 1, 100.0, MARKDOWN_ALPHA),
                    {"element_id": "L01", "element_type": "logo", "page": 2, "rect": [0.0, 0.0, 10.0, 10.0]},
                    figure("F02", 2, 300.0, "Figure 2: The loop.")]
        report_dir = self.tmp / "R01"
        report_dir.mkdir()
        criteria_doc = json.loads((FIGURE_SKILL / "assets" / "figure_criteria.json").read_text(encoding="utf-8"))
        with mock.patch.object(ugs_figures, "extract", side_effect=AssertionError("extract must not run")) as spy:
            result = ugs_figures.figures_report(pdf, report_dir, "R01", pages, lambda *a: {}, make_ctx(),
                                                criteria_doc, "en", False, elements=elements)
        self.assertFalse(spy.called)
        self.assertEqual([f["figure_id"] for f in result["figures"]], ["F01", "F02"])

    def test_figures_report_without_elements_is_unchanged(self):
        pdf = make_report(self.tmp / "report.pdf", PAGES)
        with fitz.open(str(pdf)) as doc:
            pages = [page.get_text() for page in doc]
        report_dir = self.tmp / "R01"
        report_dir.mkdir()
        criteria_doc = json.loads((FIGURE_SKILL / "assets" / "figure_criteria.json").read_text(encoding="utf-8"))
        with mock.patch.object(ugs_figures, "extract", wraps=REAL_EXTRACT) as spy:
            result = ugs_figures.figures_report(pdf, report_dir, "R01", pages, lambda *a: {}, make_ctx(),
                                                criteria_doc, "en", False)
        self.assertEqual(spy.call_count, 1)
        self.assertEqual(len(result["figures"]), 2)


if __name__ == "__main__":
    unittest.main()
