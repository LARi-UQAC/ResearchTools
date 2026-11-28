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

    def test_a_kind_written_with_a_space_or_a_dash_matches_the_enum_value(self):
        for written in ("technical drawing", "Technical-Drawing", "technical_drawing"):
            result = self.run_probe(answer("technical_drawing", ("U1", "GND")),
                                    {"kind": written, "words": ["U1", "GND"]})
            self.assertTrue(result["ok"], written)

    def test_a_different_kind_still_fails_with_both_kinds_in_the_reason(self):
        result = self.run_probe(answer("photo", ("U1", "GND")), {"kind": "technical drawing", "words": ["U1", "GND"]})
        self.assertFalse(result["ok"])
        self.assertIn("technical drawing", result["reason"])
        self.assertIn("photo", result["reason"])

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


SKILLS = Path(__file__).resolve().parents[4] / "skills"
ALIASES = CONFIG["vision.kind_aliases"]

# every family of figure the professor listed (2026-11-15): (a name a professor writes, the schema kind the model
# must answer, the words both prompts must carry so the model can recognise the family)
FAMILIES = [
    ("UML use case", "diagram", "UML"), ("class diagram", "diagram", "UML"), ("sequence diagram", "diagram", "UML"),
    ("SysML", "diagram", "SysML"), ("software architecture", "diagram", "architecture"),
    ("electronic architecture", "diagram", "architecture"), ("PBS", "diagram", "breakdown structure"),
    ("WBS", "diagram", "breakdown structure"), ("flowchart", "flowchart", "flowchart"),
    ("logigram", "flowchart", "logigram"), ("Gantt", "gantt", "Gantt"), ("Kanban", "other", "Kanban"),
    ("budget table", "table", "budget"), ("budget chart", "chart", "budget"), ("S-curve", "chart", "S-curve"),
    ("timesheet", "table", "timesheet"), ("PCB", "technical_drawing", "PCB"), ("CAD", "technical_drawing", "CAD"),
    ("photo", "photo", "photo"),
]


def applicable(kind, criteria):
    """The ids a figure of this kind is judged on, by the rule of ugs_figures (`all` or the kind itself)."""
    return {c["id"] for c in criteria if "all" in c["applies_to"] or kind in c["applies_to"]}


class TestFigureFamilies(unittest.TestCase):
    """Every kind of figure a report can hold is classified, judged on the right criteria and probe-able."""

    @classmethod
    def setUpClass(cls):
        cls.criteria = [c for c in json.loads((SKILLS / "figure-review" / "assets" / "figure_criteria.json"
                                               ).read_text(encoding="utf-8"))["criteria"]
                        if c["scope"] in ("undergraduate", "both")]
        cls.probe_prompt = (PROMPTS / "vision_probe.md").read_text(encoding="utf-8")
        cls.figure_prompt = (SKILLS / "figure-review" / "prompts" / "figure.md").read_text(encoding="utf-8")
        cls.enum = SCHEMAS["vision_probe"]["properties"]["figure_kind"]["enum"]

    def test_every_family_has_a_schema_kind_both_prompts_name_it_and_the_alias_resolves(self):
        for written, kind, word in FAMILIES:
            with self.subTest(family=written):
                self.assertIn(kind, self.enum)
                self.assertEqual(vision_probe.canonical_kind(written, ALIASES), vision_probe.canonical_kind(kind, {}))
                self.assertIn(word.lower(), self.probe_prompt.lower())
                self.assertIn(word.lower(), self.figure_prompt.lower())

    def test_every_alias_points_to_a_schema_kind(self):
        for alias, kind in ALIASES.items():
            self.assertIn(kind, self.enum, alias)

    def test_curve_and_budget_charts_get_the_axis_criteria_and_the_other_families_do_not(self):
        chart_only = {"axis_titles", "units_adequate", "legend_when_multiple_curves", "curves_visible"}
        for written, kind, _ in FAMILIES:
            with self.subTest(family=written):
                judged = applicable(kind, self.criteria)
                if kind == "chart":
                    self.assertTrue(chart_only <= judged)
                else:
                    self.assertFalse(chart_only & judged)
                self.assertIn("caption_self_contained", judged)
                self.assertIn("effective_resolution", judged)

    def test_the_architecture_and_logic_families_get_the_arrow_criteria(self):
        for written, kind, _ in FAMILIES:
            with self.subTest(family=written):
                judged = applicable(kind, self.criteria)
                if kind in ("diagram", "flowchart"):
                    self.assertIn("io_and_arrows", judged)
                else:
                    self.assertNotIn("io_and_arrows", judged)
        self.assertIn("flowchart_symbols", applicable("flowchart", self.criteria))
        self.assertNotIn("flowchart_symbols", applicable("diagram", self.criteria))

    def test_a_gantt_a_kanban_board_and_a_timesheet_get_only_the_general_criteria(self):
        general = applicable("photo", self.criteria)
        for kind in ("gantt", "other"):
            self.assertEqual(applicable(kind, self.criteria), general)

    def test_a_professor_can_write_any_family_as_the_expected_kind(self):
        for written, kind, _ in FAMILIES:
            with self.subTest(family=written):
                result = probe(lambda *a, **k: ({"figure_kind": kind, "visible_text": ["A", "B"]}, {"prompt_tokens": 9}),
                               Path("figure.png"), {"kind": written, "words": ["A", "B"]}, "p", {"type": "object"},
                               0.8, ALIASES)
                self.assertTrue(result["ok"], result["reason"])

    def test_a_wrong_family_still_fails_and_an_unknown_kind_is_refused_by_the_command_line(self):
        result = probe(lambda *a, **k: ({"figure_kind": "chart", "visible_text": ["A"]}, {"prompt_tokens": 9}),
                       Path("figure.png"), {"kind": "UML", "words": ["A"]}, "p", {"type": "object"}, 0.8, ALIASES)
        self.assertFalse(result["ok"])
        self.assertIn("UML", result["reason"])
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        (tmp / "f.png").touch()
        (tmp / "e.json").write_text(json.dumps({"kind": "hologram", "words": ["A"]}), encoding="utf-8")
        with contextlib.redirect_stderr(io.StringIO()):
            code = main(["--work", str(tmp), "--image", str(tmp / "f.png"), "--expected", str(tmp / "e.json")],
                        call_usage=MagicMock(side_effect=AssertionError("no model call for a refusal")))
        self.assertEqual(code, 2)
        self.assertFalse((tmp / "vision_probe.json").exists())

    def test_the_alias_table_ships_with_a_provenance(self):
        data = json.loads(ugs_config.default_path().read_text(encoding="utf-8"))
        self.assertTrue(data["vision.kind_aliases"]["provenance"])
        self.assertIn("vision.kind_aliases", ugs_config.REQUIRED_KEYS)


class TableKindAliasTest(unittest.TestCase):
    """Review H: a table, a budget table or a timesheet is the kind table, not other (figure criteria apply to it)."""

    def setUp(self):
        self.aliases = ugs_config.load(ugs_config.default_path())["vision.kind_aliases"]

    def test_table_like_words_name_the_kind_table(self):
        for word in ("table", "budget", "budget table", "timesheet", "time sheet", "spreadsheet"):
            self.assertEqual(vision_probe.canonical_kind(word, self.aliases), "table", word)

    def test_kanban_and_screenshot_stay_other(self):
        for word in ("kanban", "screenshot"):
            self.assertEqual(vision_probe.canonical_kind(word, self.aliases), "other", word)


class VisionPromptKindsTest(unittest.TestCase):
    """Review 3: the probe prompt names the kinds of the schema, and a budget or a timesheet is a table, not other."""

    PROMPT = Path(__file__).resolve().parent.parent.parent / "prompts" / "vision_probe.md"
    SCHEMA = Path(__file__).resolve().parent.parent.parent / "prompts" / "schemas.json"

    def test_the_kind_list_of_the_prompt_is_the_schema_enum(self):
        import re
        text = self.PROMPT.read_text(encoding="utf-8")
        listed = re.search(r"figure_kind: the kind of the figure, one of ([^.]*)\.", text).group(1)
        enum = json.loads(self.SCHEMA.read_text(encoding="utf-8"))["vision_probe"]["properties"]["figure_kind"]["enum"]
        self.assertEqual([k.strip() for k in listed.split(",")], enum)

    def test_a_table_budget_or_timesheet_is_not_described_as_other(self):
        text = self.PROMPT.read_text(encoding="utf-8")
        self.assertNotIn("other: anything else, including a table", text)
        self.assertIn("table: a grid of rows and columns", text)


if __name__ == "__main__":
    unittest.main()
