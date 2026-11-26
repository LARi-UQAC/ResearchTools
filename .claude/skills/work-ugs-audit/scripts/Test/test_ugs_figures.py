"""
Offline tests of ugs_figures.py (Issue #104): a fixture PDF built with PyMuPDF, the shipped figure criteria
and the real figure prompt, a fake model call that answers from the criteria ids found in the prompt. Fictitious
data only (R34).
"""
import copy
import json
import os
import re
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
from _pdf_fixtures import make_report
from figure_checks import load_criteria
from ugs_bridge import NotRun
from ugs_text import StepContext

FIGURE_SKILL = Path(__file__).resolve().parent.parent.parent.parent / "figure-review"
CRITERIA = load_criteria(FIGURE_SKILL / "assets" / "figure_criteria.json")
FIGURE_PROMPT = (FIGURE_SKILL / "prompts" / "figure.md").read_text(encoding="utf-8")
SENT_LINE = re.compile(r"^(\w+) \| .* \| applies to: ", re.M)

PAGES = [
    {"text": "Figure 1 shows the plant and how it reacts.\n\nMore text.", "image": True, "caption": "Figure 1: The plant."},
    {"text": "Figure 2 shows the loop.\n\nMore text.", "image": True, "caption": "Figure 2: The loop."},
]


class FakeModel:
    """A call that answers every criterion sent in the prompt, recording prompts and image sizes."""

    def __init__(self, kind="chart", verdict="pass", style="pass", script=None):
        self.kind, self.verdict, self.style, self.script = kind, verdict, style, script
        self.calls = []
        self.sizes = []

    def __call__(self, prompt, schema, images=None):
        self.calls.append(prompt)
        for path in images or []:
            pix = fitz.Pixmap(path)
            self.sizes.append(max(pix.width, pix.height))
        if self.script:
            reply = self.script.pop(0)
            if isinstance(reply, Exception):
                raise reply
            if callable(reply):
                return reply(prompt)
            return reply
        if "set of" in prompt:
            return {"verdict": self.style, "reason": "same style", "figures_involved": []}
        return {"kind": self.kind,
                "criteria": [{"id": i, "verdict": self.verdict, "reason": "r"} for i in SENT_LINE.findall(prompt)]}


def make_ctx(retries=1):
    return StepContext(prompts={"figure": FIGURE_PROMPT}, schemas={"figure": {}, "figure_set": {}}, levels={},
                       window_tokens=1000, reserve_tokens=100, count=lambda s: 10, grade_retries=retries,
                       audit_retries=retries, min_word_len=3)


class TestUgsFigures(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.report_dir = self.tmp / "R01"
        self.report_dir.mkdir()
        self.pdf = make_report(self.tmp / "report.pdf", PAGES)
        with fitz.open(str(self.pdf)) as doc:
            self.pages = [page.get_text() for page in doc]
        self.ctx = make_ctx()
        self.criteria = copy.deepcopy(CRITERIA)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def report(self, call, vision_ok=True, existing=None, on_figure=None, criteria=None, language="en", elements=None):
        return ugs_figures.figures_report(self.pdf, self.report_dir, "R01", self.pages, call, self.ctx,
                                          criteria or self.criteria, language, vision_ok, existing, on_figure,
                                          elements=elements)

    def test_script_verdicts_are_recorded_without_any_model_call_when_vision_is_not_ok(self):
        model = FakeModel()
        result = self.report(model, vision_ok=False)
        self.assertEqual(model.calls, [])
        self.assertEqual(len(result["figures"]), 2)
        record = result["figures"][0]
        self.assertEqual(record["kind"], "other")
        self.assertIn(record["criteria"]["space_used_over_70"]["verdict"], ("pass", "fail"))
        self.assertEqual(record["criteria"]["axis_titles"], {"verdict": "not_run", "reason": "vision_not_validated"})
        self.assertEqual(result["report_criteria"], {})

    def test_one_fresh_call_per_figure(self):
        model = FakeModel()
        result = self.report(model)
        figure_calls = [c for c in model.calls if "set of" not in c]
        self.assertEqual(len(figure_calls), 2)
        self.assertEqual(result["figures"][0]["kind"], "chart")

    def test_only_model_criteria_are_sent_and_the_script_ones_are_explained(self):
        model = FakeModel()
        self.report(model)
        prompt = model.calls[0]
        sent = SENT_LINE.findall(prompt)
        self.assertIn("axis_titles", sent)
        self.assertNotIn("space_used_over_70", sent)
        self.assertIn("space_used_over_70: ", prompt)
        research_only = {c["id"] for c in self.criteria["criteria"] if c["scope"] == "research"}
        self.assertTrue(research_only)
        self.assertEqual(research_only & set(sent), set(), "a research-only criterion is never sent")
        for text in model.calls:
            self.assertFalse(any(rid in text for rid in research_only))

    def test_a_criterion_not_applicable_to_the_named_kind_is_forced_not_applicable(self):
        model = FakeModel(kind="photo", verdict="fail")
        result = self.report(model)
        criteria = result["figures"][0]["criteria"]
        self.assertEqual(criteria["axis_titles"]["verdict"], "not_applicable")
        self.assertEqual(criteria["cited_with_content"]["verdict"], "fail")

    def test_an_id_that_was_not_sent_is_refused_and_repeated(self):
        good = lambda prompt: {"kind": "chart", "criteria": [
            {"id": i, "verdict": "pass", "reason": "r"} for i in SENT_LINE.findall(prompt)]}
        bad = {"kind": "chart", "criteria": [{"id": "tikz_anchored_positioning", "verdict": "pass", "reason": "r"}]}
        model = FakeModel(script=[bad, good, good, {"verdict": "pass", "reason": "r"}])
        result = self.report(model)
        self.assertEqual(len([c for c in model.calls if "set of" not in c]), 3)
        self.assertNotIn("tikz_anchored_positioning", result["figures"][0]["criteria"])
        self.assertEqual(result["figures"][0]["criteria"]["axis_titles"]["verdict"], "pass")

    def test_an_invalid_answer_after_every_retry_makes_the_model_criteria_not_run(self):
        bad = {"kind": "chart", "criteria": [{"id": "bogus", "verdict": "pass", "reason": "r"}]}
        model = FakeModel(script=[bad, bad, bad, bad, {"verdict": "pass", "reason": "r"}])
        result = self.report(model)
        self.assertEqual(result["figures"][0]["criteria"]["axis_titles"], {"verdict": "not_run", "reason": "invalid_answer"})
        self.assertEqual(result["figures"][1]["criteria"]["axis_titles"]["reason"], "invalid_answer")

    def test_a_missing_answer_is_not_run_no_answer(self):
        def partial(prompt):
            ids = SENT_LINE.findall(prompt)
            return {"kind": "chart", "criteria": [{"id": i, "verdict": "pass", "reason": "r"} for i in ids if i != "axis_titles"]}
        model = FakeModel(script=[partial, partial, {"verdict": "pass", "reason": "r"}])
        result = self.report(model)
        self.assertEqual(result["figures"][0]["criteria"]["axis_titles"], {"verdict": "not_run", "reason": "no_answer"})

    def test_a_failed_criterion_carries_the_ready_comment_and_the_reason(self):
        def failing(prompt):
            return {"kind": "chart", "criteria": [{"id": i, "verdict": "fail" if i == "axis_titles" else "pass",
                                                   "reason": "x axis unnamed"} for i in SENT_LINE.findall(prompt)]}
        model = FakeModel(script=[failing, failing, {"verdict": "pass", "reason": "r"}])
        result = self.report(model, language="fr")
        entry = result["figures"][0]["criteria"]["axis_titles"]
        self.assertEqual(entry["verdict"], "fail")
        ready = next(c["comment_fr"] for c in self.criteria["criteria"] if c["id"] == "axis_titles")
        self.assertEqual(entry["comment"], ready + " x axis unnamed")

    def test_every_image_sent_is_within_max_long_edge(self):
        self.criteria["extraction"]["max_long_edge"]["value"] = 200
        model = FakeModel()
        self.report(model)
        self.assertTrue(model.sizes)
        self.assertLessEqual(max(model.sizes), 200)

    def test_style_consistency_is_one_call_per_report_and_never_in_a_figure(self):
        model = FakeModel(style="fail")
        result = self.report(model)
        self.assertEqual(len([c for c in model.calls if "set of" in c]), 1)
        self.assertEqual(result["report_criteria"]["style_consistency"]["verdict"], "fail")
        for record in result["figures"]:
            self.assertNotIn("style_consistency", record["criteria"])

    def test_one_figure_makes_no_style_call(self):
        make_report(self.pdf, PAGES[:1])
        with fitz.open(str(self.pdf)) as doc:
            self.pages = [page.get_text() for page in doc]
        model = FakeModel()
        result = self.report(model)
        self.assertEqual(len(result["figures"]), 1)
        self.assertEqual(result["report_criteria"], {})
        self.assertFalse(any("set of" in c for c in model.calls))

    def test_citing_text_finds_the_paragraph_and_ignores_the_caption(self):
        pages = ["Figure 3: The caption itself.\n\nAs Figure 3 shows, the loop is stable.\n\nEnd."]
        self.assertEqual(ugs_figures.citing_text(pages, 3), "As Figure 3 shows, the loop is stable.")
        self.assertEqual(ugs_figures.citing_text(["Figure 3: only the caption."], 3), "")
        self.assertEqual(ugs_figures.citing_text(["See Fig. 4 here."], 4), "See Fig. 4 here.")
        self.assertEqual(ugs_figures.citing_text(["Figure 33 is another figure."], 3), "")

    def test_body_sentence_starting_with_figure_is_a_citation(self):
        self.assertTrue(ugs_figures.citing_text(["Figure 2 shows the measured response."], 2))

    def test_caption_is_not_a_citation(self):
        self.assertEqual(ugs_figures.citing_text(["Figure 2: Response curve."], 2), "")
        self.assertEqual(ugs_figures.citing_text(["Figure 2 - Response curve."], 2), "")

    def test_two_part_number_is_not_the_one_part(self):
        self.assertEqual(ugs_figures.citing_text(["As Figure 2.1 shows, the loop is stable."], 2), "")
        self.assertTrue(ugs_figures.citing_text(["As Figure 2.1 shows, the loop is stable."], "2.1"))

    def test_existing_figures_are_not_judged_again(self):
        first = self.report(FakeModel())
        saved = {f["figure_id"]: f for f in first["figures"][:1]}
        model = FakeModel()
        result = self.report(model, existing=saved)
        self.assertEqual(len([c for c in model.calls if "set of" not in c]), 1)
        self.assertEqual(result["figures"][0], first["figures"][0])

    def test_on_figure_is_called_per_figure(self):
        seen = []
        self.report(FakeModel(), on_figure=lambda fid, record: seen.append(fid))
        self.assertEqual(seen, ["F01", "F02"])

    def test_unreachable_propagates(self):
        model = FakeModel(script=[NotRun("unreachable", "down")])
        with self.assertRaises(NotRun):
            self.report(model)

    def test_a_retryable_kind_is_repeated_and_the_next_answer_is_used(self):
        good = lambda prompt: {"kind": "chart", "criteria": [
            {"id": i, "verdict": "pass", "reason": "r"} for i in SENT_LINE.findall(prompt)]}
        model = FakeModel(script=[NotRun("unparsable", "bad json"), good, good, {"verdict": "pass", "reason": "r"}])
        result = self.report(model)
        self.assertEqual(result["figures"][0]["criteria"]["axis_titles"]["verdict"], "pass")

    def element_records(self, titles):
        """
        Fictitious element records built from the real extraction of the fixture PDF, in reading order.
        `titles` gives one entry per figure: its title text, or None for an untitled decorative drawing.
        """
        settings = self.criteria["extraction"]
        figures_dir = self.report_dir / "figures"
        figures_dir.mkdir(parents=True, exist_ok=True)
        raw = ugs_figures.extract(self.pdf, figures_dir, settings["min_area_pt2"]["value"],
                                  settings["background_threshold"]["value"])
        return [dict(record, element_type="figure", element_id="F%02d" % (index + 1),
                     title={"text": title} if title else None)
                for index, (record, title) in enumerate(zip(raw, titles))]

    def test_printed_number_not_element_counter(self):
        # The first drawing is untitled, so the element counter F02 belongs to the figure printed as "Figure 1".
        elements = self.element_records([None, "Figure 1 - The plant."])
        # Citing sentences open with "As Figure N", since a paragraph opening with "Figure N" is a caption.
        pages = ["Figure 1: The plant.\n\nAs Figure 1 shows, the plant reacts.\n\nMore text.",
                 "Figure 2: The loop.\n\nAs Figure 2 shows, the loop is stable."]
        model = FakeModel()
        result = ugs_figures.figures_report(self.pdf, self.report_dir, "R01", pages, model, self.ctx,
                                            self.criteria, "en", True, elements=elements)
        figure_prompts = [c for c in model.calls if "set of" not in c]
        self.assertEqual(len(figure_prompts), 2)
        self.assertEqual(result["figures"][0]["cited_in_text"], "not_applicable")
        self.assertTrue(result["figures"][1]["cited_in_text"])
        self.assertIn("As Figure 1 shows, the plant reacts.", figure_prompts[1])
        self.assertNotIn("As Figure 2 shows", figure_prompts[1])

    def test_untitled_element_has_no_citing_search(self):
        elements = self.element_records([None, None])
        with mock.patch.object(ugs_figures, "citing_text", wraps=ugs_figures.citing_text) as spy:
            result = ugs_figures.figures_report(self.pdf, self.report_dir, "R01", self.pages, lambda *a: {},
                                                self.ctx, self.criteria, "en", False, elements=elements)
        spy.assert_not_called()
        self.assertEqual([f["cited_in_text"] for f in result["figures"]], ["not_applicable", "not_applicable"])

    def test_effective_dpi_is_given_for_a_raster_and_a_missing_extraction_key_is_named(self):
        result = self.report(FakeModel(), vision_ok=False)
        self.assertIsInstance(result["figures"][0]["effective_dpi"], float)
        broken = copy.deepcopy(self.criteria)
        del broken["extraction"]["jpeg_quality"]
        with self.assertRaises(KeyError) as ctx:
            self.report(FakeModel(), criteria=broken)
        self.assertIn("jpeg_quality", str(ctx.exception))


    # --- N7 signal 2 (plan 20): the vision role says an element is a table ---

    def test_a_vision_only_table_under_a_figure_title_is_a_candidate_and_not_flagged(self):
        # Review B: the vision answer is a candidate only; the script decides the flag.
        elements = self.element_records(["Figure 1 - The plant.", None])
        result = self.report(FakeModel(kind="table"), elements=elements)
        record = result["figures"][0]
        self.assertEqual(record["kind"], "table")
        self.assertEqual(record["title_kind_candidate"], "table_titled_figure")
        self.assertIsNone(record["title_kind_mismatch"])
        self.assertIsNone(record["title_kind_source"])

    def test_an_untitled_element_is_never_a_candidate_or_a_flag(self):
        # Review B: an element without a printed title is never flagged, whatever the vision says.
        elements = self.element_records([None, None])
        result = self.report(FakeModel(kind="table"), elements=elements)
        for record in result["figures"]:
            self.assertIsNone(record["title_kind_candidate"])
            self.assertIsNone(record["title_kind_mismatch"])

    def test_a_script_flagged_table_is_judged_as_kind_table_with_general_criteria_only(self):
        # Review H: a flagged table_titled_figure is judged as a table, so chart-only criteria are not applicable.
        elements = self.element_records(["Figure 1 - The plant.", None])
        elements[0].update(title_kind_mismatch="table_titled_figure", title_kind_source="script")
        result = self.report(FakeModel(kind="chart"), elements=elements)
        record = result["figures"][0]
        self.assertEqual(record["kind"], "table")
        self.assertEqual(record["criteria"]["axis_titles"]["verdict"], "not_applicable")
        self.assertEqual(record["title_kind_source"], "script")

    def test_a_table_image_with_a_non_table_vision_kind_and_no_grid_is_flagged_by_vision(self):
        # Review C: a table_image is sent to vision; a kind other than table or other, with no grid, is a mismatch.
        elements = self.element_records(["Figure 1 - The plant.", None])
        elements.append(self.table_image_record("T-i01", title="Tableau 2: Mesures", title_grid=False))
        result = self.report(FakeModel(kind="chart"), elements=elements)
        record = next(f for f in result["figures"] if f["figure_id"] == "T-i01")
        self.assertEqual(record["element_type"], "table_image")
        self.assertEqual(record["title_kind_mismatch"], "figure_titled_table")
        self.assertEqual(record["title_kind_source"], "vision")

    def test_a_table_image_whose_grid_reading_is_a_grid_is_not_flagged(self):
        # Review C: the grid rule says grid, so a vision chart answer does not flag it.
        elements = self.element_records(["Figure 1 - The plant.", None])
        elements.append(self.table_image_record("T-i01", title="Tableau 2: Mesures", title_grid=True))
        result = self.report(FakeModel(kind="chart"), elements=elements)
        record = next(f for f in result["figures"] if f["figure_id"] == "T-i01")
        self.assertIsNone(record["title_kind_mismatch"])

    def test_a_table_image_judged_as_a_table_is_not_flagged(self):
        elements = self.element_records(["Figure 1 - The plant.", None])
        elements.append(self.table_image_record("T-i01", title="Tableau 2: Mesures", title_grid=False))
        result = self.report(FakeModel(kind="table"), elements=elements)
        record = next(f for f in result["figures"] if f["figure_id"] == "T-i01")
        self.assertIsNone(record["title_kind_mismatch"])

    def test_the_figures_document_says_whether_vision_was_validated(self):
        result = self.report(FakeModel(), vision_ok=False, elements=self.element_records([None, None]))
        self.assertIs(result["vision_validated"], False)
        result = self.report(FakeModel(), elements=self.element_records([None, None]))
        self.assertIs(result["vision_validated"], True)

    def table_image_record(self, element_id, title, title_grid):
        """A table_image element record as extract_elements writes it, with its file in the figures folder."""
        figures = self.report_dir / "figures"
        figures.mkdir(parents=True, exist_ok=True)
        pixmap = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 60, 40), False)
        pixmap.clear_with(200)
        pixmap.save(str(figures / f"{element_id}.png"))
        return {"element_id": element_id, "element_type": "table_image", "page": 1, "rect": [50, 400, 400, 500],
                "file": f"{element_id}.png", "title": {"text": title}, "title_grid": title_grid,
                "title_kind_mismatch": None, "title_kind_source": None, "legend": "", "notes": [],
                "caption": title, "source": "vector"}

    def test_a_chart_judged_under_a_figure_title_is_not_flagged(self):
        elements = self.element_records(["Figure 1 - The plant.", None])
        result = self.report(FakeModel(kind="chart"), elements=elements)
        self.assertIsNone(result["figures"][0]["title_kind_mismatch"])
        self.assertIsNone(result["figures"][0]["title_kind_source"])

    def test_a_script_flag_is_never_overwritten_by_a_vision_answer(self):
        elements = self.element_records(["Figure 1 - The plant.", None])
        elements[0].update(title_kind_mismatch="table_titled_figure", title_kind_source="script")
        result = self.report(FakeModel(kind="chart"), elements=elements)
        record = result["figures"][0]
        self.assertEqual(record["title_kind_mismatch"], "table_titled_figure")
        self.assertEqual(record["title_kind_source"], "script")

    def test_without_vision_the_script_flag_stays_and_vision_adds_nothing(self):
        elements = self.element_records([None, None])
        result = self.report(FakeModel(kind="table"), vision_ok=False, elements=elements)
        self.assertIsNone(result["figures"][0]["title_kind_mismatch"])
        elements = self.element_records(["Figure 1 - The plant.", None])
        elements[0].update(title_kind_mismatch="table_titled_figure", title_kind_source="script")
        result = self.report(FakeModel(), vision_ok=False, elements=elements)
        self.assertEqual(result["figures"][0]["title_kind_source"], "script")

    def test_the_figure_schema_and_the_probe_schema_accept_the_kind_table(self):
        schemas = json.loads((Path(__file__).resolve().parent.parent.parent / "prompts" / "schemas.json")
                             .read_text(encoding="utf-8"))
        self.assertIn("table", schemas["figure"]["properties"]["kind"]["enum"])
        self.assertIn("table", schemas["vision_probe"]["properties"]["figure_kind"]["enum"])

    def test_the_figure_prompt_names_the_kind_table(self):
        self.assertIn("table (a grid of rows and columns", FIGURE_PROMPT)


class TestTitleKindFromAnswer(unittest.TestCase):
    """N7 (plan 20): the mapping from an element type and a vision kind to the title mismatch."""

    def test_the_four_combinations(self):
        self.assertEqual(ugs_figures.title_kind_from_answer("figure", "table"), "table_titled_figure")
        self.assertIsNone(ugs_figures.title_kind_from_answer("figure", "chart"))
        self.assertEqual(ugs_figures.title_kind_from_answer("table_image", "chart"), "figure_titled_table")
        self.assertIsNone(ugs_figures.title_kind_from_answer("table_image", "table"))

    def test_other_is_never_a_mismatch_for_a_table_image(self):
        self.assertIsNone(ugs_figures.title_kind_from_answer("table_image", "other"))

    def test_a_diagram_under_a_table_title_is_a_mismatch(self):
        self.assertEqual(ugs_figures.title_kind_from_answer("table_image", "diagram"), "figure_titled_table")


class TestCitingParagraph(unittest.TestCase):
    """D5: a body sentence opening "Figure N shows" is a citation; a caption line is not, whatever its dash."""

    def test_body_sentence_starting_with_figure_is_a_citation(self):
        self.assertEqual(ugs_figures.citing_text(["Figure 2 shows the response."], 2), "Figure 2 shows the response.")

    def test_abbreviated_marker_at_the_start_is_a_citation(self):
        self.assertTrue(ugs_figures.citing_text(["Fig. 2 shows the response."], 2))

    def test_caption_with_colon_is_not_a_citation(self):
        self.assertEqual(ugs_figures.citing_text(["Figure 2: Response curve."], 2), "")

    def test_caption_with_hyphen_is_not_a_citation(self):
        self.assertEqual(ugs_figures.citing_text(["Figure 2 - Response curve."], 2), "")

    def test_caption_with_en_dash_is_not_a_citation(self):
        self.assertEqual(ugs_figures.citing_text(["Figure 2 – Response curve."], 2), "")

    def test_two_part_number_is_not_one_part(self):
        self.assertEqual(ugs_figures.citing_text(["Figure 2.1 shows the loop."], 2), "")


class RealR01AcceptanceTest(unittest.TestCase):
    """
    Real-data acceptance on the owner's R01 report (review D, 2026-11-26). Skipped unless UGS_REAL_WORK names the
    check work folder of a completed figures step (loop-1/R01/figures.json). Only ids and counts are asserted (R34).
    The expected set is the owner's list, exactly: a flag outside it, or a missing one, is a failure.
    """

    EXPECTED = {"F%d" % n for n in range(1, 8)} | {"F16", "F17", "F18"}

    def setUp(self):
        work = os.environ.get("UGS_REAL_WORK", "")
        if not work:
            self.skipTest("UGS_REAL_WORK is not set (owner's real-data check)")
        self.figures_path = Path(work) / "loop-1" / "R01" / "figures.json"
        if not self.figures_path.is_file():
            self.skipTest("no figures.json for R01 in UGS_REAL_WORK yet")

    def test_the_flagged_set_is_the_owner_list_exactly(self):
        document = json.loads(self.figures_path.read_text(encoding="utf-8"))
        self.assertTrue(document.get("vision_validated"), "the acceptance run must validate the vision role")
        flagged = {f["figure_id"] for f in document["figures"] if f.get("title_kind_mismatch")}
        self.assertEqual(flagged, self.EXPECTED)

    def test_every_flag_carries_its_source_and_no_candidate_is_flagged(self):
        document = json.loads(self.figures_path.read_text(encoding="utf-8"))
        for record in document["figures"]:
            if record.get("title_kind_mismatch"):
                self.assertIn(record.get("title_kind_source"), ("script", "vision"))
            else:
                self.assertIsNone(record.get("title_kind_source"))


if __name__ == "__main__":
    unittest.main()
