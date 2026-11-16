"""
Offline tests for vision_probe (Issue 120, plan 3): the probe is kind-neutral. It passes on the text the model reads
in any figure (a Gantt chart, a PCB layout, a photo as well as a chart) and its verdict always says why.
Fictitious data only (R34), no model, no network (R21).
"""
import io
import contextlib
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import ugs_config
import vision_probe
from vision_probe import probe, main, NotRun

PROMPTS = Path(__file__).resolve().parent.parent.parent / "prompts"
SCHEMAS = json.loads((PROMPTS / "schemas.json").read_text(encoding="utf-8"))
CONFIG = ugs_config.load(ugs_config.default_path())
GANTT = {"kind": "gantt", "words": ["Phase 1", "Conception", "Revue", "Livraison"]}


def answer(kind="gantt", text=("Phase 1", "Conception detaillee", "Revue", "Livraison finale")):
    return {"figure_kind": kind, "visible_text": list(text)}


class TestVisionProbe(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = Path(tempfile.mkdtemp())
        self.image_path = self.tmp_dir / "figure.png"
        self.image_path.touch()
        self.prompt = "Describe the figure."
        self.schema = {"type": "object"}

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def make_call_usage(self, responses):
        calls = iter(responses)

        def _call(prompt, schema, images=None):
            try:
                item = next(calls)
            except StopIteration:
                raise AssertionError("Too many calls")
            if isinstance(item, Exception):
                raise item
            return item
        return _call

    def run_probe(self, model_answer, expected=GANTT, share=0.8, with_cost=150, without_cost=50):
        call = self.make_call_usage([(model_answer, {"prompt_tokens": with_cost}),
                                     ({}, {"prompt_tokens": without_cost})])
        return probe(call, self.image_path, expected, self.prompt, self.schema, share)

    # --- the verdict on any kind of figure ---

    def test_a_gantt_chart_with_no_axis_passes_on_its_text(self):
        result = self.run_probe(answer())
        self.assertTrue(result["ok"])
        self.assertEqual(result["figure_kind"], "gantt")
        self.assertEqual(result["missing_words"], [])
        self.assertEqual(result["image_tokens"], 100)
        self.assertIn("4 of 4", result["reason"])

    def test_a_pcb_layout_and_a_photo_pass_with_their_own_words(self):
        pcb = self.run_probe(answer("technical_drawing", ("U1", "R12 10k", "GND")),
                             {"kind": "technical_drawing", "words": ["U1", "R12", "GND"]})
        self.assertTrue(pcb["ok"])
        photo = self.run_probe(answer("photo", ("MARQUE-X",)), {"words": ["marque-x"]})
        self.assertTrue(photo["ok"])

    def test_one_misread_word_of_five_still_passes_at_the_configured_share(self):
        words = ["a1", "b2", "c3", "d4", "e5"]
        result = self.run_probe(answer("other", ("a1", "b2", "c3", "d4")), {"words": words})
        self.assertTrue(result["ok"])
        self.assertEqual(result["missing_words"], ["e5"])

    def test_too_few_words_fail_and_the_reason_names_the_missing_ones(self):
        result = self.run_probe(answer("gantt", ("Phase 1",)))
        self.assertFalse(result["ok"])
        self.assertIn("1 of 4", result["reason"])
        for word in ("Conception", "Revue", "Livraison"):
            self.assertIn(word, result["reason"])
        self.assertEqual(result["found_words"], ["Phase 1"])

    def test_a_wrong_expected_kind_fails_with_its_reason(self):
        result = self.run_probe(answer("chart"))
        self.assertFalse(result["ok"])
        self.assertIn("gantt", result["reason"])
        self.assertIn("chart", result["reason"])

    def test_no_kind_expected_checks_the_words_only(self):
        self.assertTrue(self.run_probe(answer("diagram"), {"words": ["Phase 1", "Revue"]})["ok"])

    def test_comparison_ignores_case_accents_and_spaces(self):
        result = self.run_probe(answer("gantt", ("PHASE  1", "conception", "Revué", "livraison")))
        self.assertTrue(result["ok"])

    def test_a_short_expected_word_is_not_found_inside_another_word(self):
        result = self.run_probe(answer("other", ("extra mixture of letters",)), {"words": ["x"]})
        self.assertFalse(result["ok"])
        self.assertTrue(self.run_probe(answer("other", ("x axis",)), {"words": ["x"]})["ok"])

    def test_one_long_blob_does_not_make_every_word_found(self):
        blob = ("Phase 1Conceptionx",)
        self.assertFalse(self.run_probe(answer("gantt", blob), GANTT)["ok"])

    def test_a_missing_token_count_is_said_in_the_reason(self):
        call = self.make_call_usage([(answer(), {}), ({}, {"prompt_tokens": 50})])
        result = probe(call, self.image_path, GANTT, self.prompt, self.schema, 0.8)
        self.assertTrue(result["ok"])
        self.assertIn("image cost is unknown", result["reason"])

    def test_an_answer_without_the_two_keys_fails_with_a_reason(self):
        for bad in ({"x_title": "t"}, {"figure_kind": "gantt"}, {"figure_kind": "gantt", "visible_text": "text"}, []):
            result = self.run_probe(bad)
            self.assertFalse(result["ok"])
            self.assertIn("figure_kind", result["reason"])

    # --- failures of the call, and the image cost ---

    def test_not_run_on_the_first_call_is_not_ok_with_its_kind_and_a_reason(self):
        call = self.make_call_usage([NotRun("unreachable", "no daemon")])
        result = probe(call, self.image_path, GANTT, self.prompt, self.schema, 0.8)
        self.assertFalse(result["ok"])
        self.assertEqual(result["kind"], "unreachable")
        self.assertIn("unreachable", result["reason"])
        self.assertIsNone(result["image_tokens"])
        self.assertEqual(result["missing_words"], GANTT["words"])

    def test_an_unexpected_error_is_reported_as_unreachable_with_its_class(self):
        call = self.make_call_usage([ValueError("boom")])
        result = probe(call, self.image_path, GANTT, self.prompt, self.schema, 0.8)
        self.assertEqual(result["kind"], "unreachable")
        self.assertIn("ValueError", result["reason"])

    def test_a_failing_second_call_keeps_the_verdict_and_says_the_cost_is_unknown(self):
        call = self.make_call_usage([(answer(), {"prompt_tokens": 100}), NotRun("unreachable", "gone")])
        result = probe(call, self.image_path, GANTT, self.prompt, self.schema, 0.8)
        self.assertTrue(result["ok"])
        self.assertIsNone(result["image_tokens"])
        self.assertIn("could not be measured", result["reason"])

    def test_a_missing_token_count_gives_none(self):
        call = self.make_call_usage([(answer(), {}), ({}, {"prompt_tokens": 50})])
        self.assertIsNone(probe(call, self.image_path, GANTT, self.prompt, self.schema, 0.8)["image_tokens"])

    # --- the command line ---

    def write_expected(self, content):
        path = self.tmp_dir / "expected.json"
        path.write_text(json.dumps(content), encoding="utf-8")
        return path

    def run_main(self, expected, call=None, extra=()):
        argv = ["--work", str(self.tmp_dir), "--image", str(self.image_path),
                "--expected", str(self.write_expected(expected)), *extra]
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer), contextlib.redirect_stderr(io.StringIO()):
            code = main(argv, call_usage=call)
        return code, buffer.getvalue()

    def test_main_writes_the_verdict_file_and_prints_the_same_line(self):
        call = self.make_call_usage([(answer(), {"prompt_tokens": 150}), ({}, {"prompt_tokens": 50})])
        code, printed = self.run_main(GANTT, call)
        self.assertEqual(code, 0)
        written = json.loads((self.tmp_dir / "vision_probe.json").read_text(encoding="utf-8"))
        self.assertEqual(json.loads(printed), written)
        for key in ("ok", "reason", "image_tokens", "kind", "figure_kind", "expected_words", "found_words",
                    "missing_words"):
            self.assertIn(key, written)
        self.assertTrue(written["ok"])

    def test_a_failed_probe_is_written_and_printed_with_its_reason_and_exits_zero(self):
        call = self.make_call_usage([(answer("gantt", ()), {"prompt_tokens": 150}), ({}, {"prompt_tokens": 50})])
        code, printed = self.run_main(GANTT, call)
        self.assertEqual(code, 0)
        line = json.loads(printed)
        self.assertFalse(line["ok"])
        self.assertTrue(line["reason"])

    def test_an_empty_or_missing_word_list_is_refused_naming_the_key(self):
        for expected in ({"kind": "gantt"}, {"words": []}, {"words": [""]}, {"words": "Phase"}, []):
            code, printed = self.run_main(expected)
            self.assertEqual(code, 2)
            self.assertEqual(printed, "")
        self.assertFalse((self.tmp_dir / "vision_probe.json").exists())

    def test_main_refuses_a_path_outside_the_work_folder(self):
        outside = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, outside, True)
        image = outside / "figure.png"
        image.touch()
        argv = ["--work", str(self.tmp_dir), "--image", str(image), "--expected", str(self.write_expected(GANTT))]
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main(argv), 2)

    def test_dry_run_writes_nothing_and_calls_no_model(self):
        call = MagicMock(side_effect=AssertionError("no model call in a dry run"))
        code, printed = self.run_main(GANTT, call, ["--dry-run"])
        self.assertEqual(code, 0)
        self.assertTrue(json.loads(printed)["dry_run"])
        self.assertFalse((self.tmp_dir / "vision_probe.json").exists())

    def test_a_missing_configuration_key_is_a_refusal_naming_it(self):
        original = vision_probe.load_config

        def refusing(path):
            raise vision_probe.ConfigError("missing required key 'vision.min_word_share'")

        vision_probe.load_config = refusing
        try:
            code, _ = self.run_main(GANTT)
        finally:
            vision_probe.load_config = original
        self.assertEqual(code, 2)

    def test_a_share_outside_zero_to_one_is_refused(self):
        original = vision_probe.load_config
        for bad in (0, 1.5, True):
            vision_probe.load_config = lambda path, bad=bad: dict(CONFIG, **{"vision.min_word_share": bad})
            try:
                code, _ = self.run_main(GANTT)
            finally:
                vision_probe.load_config = original
            self.assertEqual(code, 2)


class TestProbeData(unittest.TestCase):

    def test_the_shipped_share_is_a_valid_number_with_a_provenance(self):
        share = CONFIG["vision.min_word_share"]
        self.assertTrue(0 < share <= 1)
        data = json.loads(ugs_config.default_path().read_text(encoding="utf-8"))
        self.assertTrue(data["vision.min_word_share"]["provenance"])

    def test_the_probe_schema_asks_the_kind_and_the_text_and_no_chart_field(self):
        schema = SCHEMAS["vision_probe"]
        self.assertEqual(schema["required"], ["figure_kind", "visible_text"])
        self.assertEqual(set(schema["properties"]), {"figure_kind", "visible_text"})

    def test_the_figure_schema_and_the_probe_schema_accept_gantt_and_technical_drawing(self):
        for name, path in (("figure", "kind"), ("vision_probe", "figure_kind")):
            kinds = SCHEMAS[name]["properties"][path]["enum"]
            self.assertIn("gantt", kinds)
            self.assertIn("technical_drawing", kinds)
        self.assertEqual(SCHEMAS["figure"]["properties"]["kind"]["enum"],
                         SCHEMAS["vision_probe"]["properties"]["figure_kind"]["enum"])

    def test_the_probe_prompt_names_no_chart_field(self):
        text = (PROMPTS / "vision_probe.md").read_text(encoding="utf-8")
        for old in ("x_title", "y_title", "curve_count", "unit:"):
            self.assertNotIn(old, text)
        self.assertIn("visible_text", text)

    def test_the_figure_prompt_names_the_new_kinds(self):
        text = (Path(__file__).resolve().parents[4] / "skills" / "figure-review" / "prompts" / "figure.md"
                ).read_text(encoding="utf-8")
        self.assertIn("gantt", text)
        self.assertIn("technical_drawing", text)

    def test_every_chart_only_criterion_stays_chart_only(self):
        criteria = json.loads((Path(__file__).resolve().parents[4] / "skills" / "figure-review" / "assets"
                               / "figure_criteria.json").read_text(encoding="utf-8"))["criteria"]
        by_id = {c["id"]: c["applies_to"] for c in criteria}
        for cid in ("axis_titles", "units_adequate", "legend_when_multiple_curves", "curves_visible"):
            self.assertEqual(by_id[cid], ["chart"])


if __name__ == "__main__":
    unittest.main()
