"""
Offline tests of ugs_figures.py (Issue #104): a fixture PDF built with PyMuPDF, the shipped figure criteria
and the real figure prompt, a fake model call that answers from the criteria ids found in the prompt. Fictitious
data only (R34).
"""
import copy
import json
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

    def report(self, call, vision_ok=True, existing=None, on_figure=None, criteria=None, language="en"):
        return ugs_figures.figures_report(self.pdf, self.report_dir, "R01", self.pages, call, self.ctx,
                                          criteria or self.criteria, language, vision_ok, existing, on_figure)

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


if __name__ == "__main__":
    unittest.main()
