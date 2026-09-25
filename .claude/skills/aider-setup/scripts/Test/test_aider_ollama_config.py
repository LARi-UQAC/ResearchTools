"""
Offline tests for aider-ollama-config.py. No Ollama, no model, no network: the
subprocess runner and the PATH lookup are injected, so this suite runs on a
machine that has never installed Ollama.

The cases that matter are the refusals and the two judgements. A configurator
that guesses is worse than one that stops, because a wrong num_gpu is acted on
rather than noticed:

  - a budget key absent must be NAMED, not defaulted;
  - a window no rung can hold must be refused with the arithmetic, not rounded
    up to the largest rung available;
  - the fastest thread rung is not the right one, and a rung whose request the
    daemon ignored is not a measurement at all;
  - `ollama create` exiting 0 is not evidence the parameters took.
"""

import importlib.util
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

HERE = pathlib.Path(__file__).resolve().parent
SCRIPT = HERE.parent / "aider-ollama-config.py"


def load_by_path(path: pathlib.Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


cfg = load_by_path(SCRIPT, "aider_ollama_config_under_test")


def fixture_budget() -> dict:
    return {
        "reserve": {"reply_tokens": 8192, "harness_overhead_tokens": 3072},
        "repo_map_tokens": 4096,
        "ceilings": {
            "conventions.md": 2500, "rules.md": 3500, "spec.md": 4000,
            "progress.md": 2048, "plan.md": 4000, "audit.md": 4096,
            "code_file": 16000, "code_file_output": 4000, "test_file_output": 4000,
        },
        "report": {"tie_tolerance_pct": 3.0},
        "audit": {"model": "ollama_chat/fixture-model:test"},
    }


def fixture_skills() -> dict:
    return {"stages": {
        "write": {"ceiling": 2500}, "audit": {"ceiling": 2000},
        "reopen": {"ceiling": 2000}, "_comment": "ignored"}}


def thread_row(requested, granted, tps, cpu, effect="honoured"):
    return {"num_thread_requested": requested, "num_thread_granted": granted,
            "decode_tps": tps, "cpu_pct_mean": cpu, "thread_effect": effect}


def layer_row(layers, tps, num_ctx=8192):
    return {"layers_offloaded": layers, "decode_tps": tps, "num_ctx": num_ctx,
            "n_ctx_granted": num_ctx}


class FakeCompleted:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode, self.stdout, self.stderr = returncode, stdout, stderr


class TestFloor(unittest.TestCase):

    def test_the_floor_is_the_sum_of_its_stated_terms(self):
        t = cfg.compute_floor(fixture_budget(), "b", fixture_skills(), "s")
        self.assertEqual(t["reserves"], 8192 + 3072 + 4096)
        self.assertEqual(t["always_on"], 2500 + 3500)
        self.assertEqual(t["protocol"], 4000 + 2048 + 4000)
        self.assertEqual(t["skills"], 2500)
        self.assertEqual(t["floor"], 15360 + 6000 + 10048 + 2500)
        self.assertEqual(t["working_minimum"], t["floor"] + 8000)

    def test_only_the_largest_skill_stage_is_counted(self):
        # One stage is active per call. Summing them would reserve window for
        # skills that are never loaded together.
        t = cfg.compute_floor(fixture_budget(), "b", fixture_skills(), "s")
        self.assertEqual(t["skills"], 2500)
        self.assertNotEqual(t["skills"], 2500 + 2000 + 2000)

    def test_the_read_worst_case_is_reported_but_is_not_the_minimum(self):
        t = cfg.compute_floor(fixture_budget(), "b", fixture_skills(), "s")
        self.assertEqual(t["read_worst_case"], t["floor"] + 32000)
        self.assertLess(t["working_minimum"], t["read_worst_case"])

    def test_a_missing_budget_key_is_named(self):
        b = fixture_budget()
        del b["ceilings"]["progress.md"]
        with self.assertRaises(cfg.Refusal) as caught:
            cfg.compute_floor(b, "the-budget-file", fixture_skills(), "s")
        self.assertIn("progress.md", str(caught.exception))
        self.assertIn("the-budget-file", str(caught.exception))

    def test_a_missing_reserve_is_named(self):
        b = fixture_budget()
        del b["reserve"]["reply_tokens"]
        with self.assertRaises(cfg.Refusal) as caught:
            cfg.compute_floor(b, "origin", fixture_skills(), "s")
        self.assertIn("reply_tokens", str(caught.exception))

    def test_skills_with_no_ceiling_is_refused_by_name(self):
        with self.assertRaises(cfg.Refusal) as caught:
            cfg.compute_floor(fixture_budget(), "b", {"stages": {}}, "skills-file")
        self.assertIn("skills-file", str(caught.exception))


class TestWindowChoice(unittest.TestCase):

    def test_the_smallest_rung_clearing_the_minimum_plus_headroom_wins(self):
        self.assertEqual(cfg.choose_window(41908, [32768, 49152, 65536, 131072], 16000),
                         65536)

    def test_a_smaller_rung_wins_when_less_headroom_is_demanded(self):
        # Negative control for the headroom term: without it the assertion
        # above would pass on a function that always returns the largest rung.
        self.assertEqual(cfg.choose_window(41908, [32768, 49152, 65536, 131072], 4000),
                         49152)

    def test_a_rung_equal_to_the_requirement_is_accepted(self):
        self.assertEqual(cfg.choose_window(40000, [49152], 9152), 49152)

    def test_no_rung_large_enough_is_refused_with_the_arithmetic(self):
        with self.assertRaises(cfg.Refusal) as caught:
            cfg.choose_window(200000, [32768, 65536], 16000)
        message = str(caught.exception)
        self.assertIn("200000", message)
        self.assertIn("65536", message)
        # It must not silently take the largest rung and carry on.
        self.assertIn("lower the ceilings", message)

    def test_rungs_are_considered_in_order_whatever_order_they_arrive_in(self):
        self.assertEqual(cfg.choose_window(41908, [131072, 32768, 65536, 49152], 4000),
                         49152)


class TestPicks(unittest.TestCase):

    def test_the_lowest_rung_within_tolerance_wins_not_the_fastest(self):
        # The measured case: 20 threads at 3.41 and 99.4 percent CPU against 14
        # at 3.39 and 81.3. Taking the maximum buys 0.6 percent and costs every
        # remaining core.
        report = {"sweep": [thread_row(14, 14, 3.39, 81.3),
                            thread_row(20, 20, 3.41, 99.4)]}
        picks = cfg.pick_from_report(report, 3.0)
        self.assertEqual(picks["num_thread"], 14)
        self.assertIn("fastest was 20", picks["notes"]["num_thread"])

    def test_a_genuinely_faster_rung_outside_tolerance_does_win(self):
        # Negative control: without it the rule above would always pick the
        # lowest rung regardless of what it measured.
        report = {"sweep": [thread_row(4, 4, 2.21, 36.5),
                            thread_row(20, 20, 3.41, 99.4)]}
        self.assertEqual(cfg.pick_from_report(report, 3.0)["num_thread"], 20)

    def test_a_rung_the_daemon_ignored_is_not_a_measurement(self):
        report = {"sweep": [thread_row(16, 10, 9.99, 50.0,
                                       effect="IGNORED: asked 16, ran 10")]}
        picks = cfg.pick_from_report(report, 3.0)
        self.assertIsNone(picks["num_thread"])
        self.assertIn("honoured", picks["notes"]["num_thread"])

    def test_num_gpu_takes_the_best_measured_placement(self):
        report = {"gpu_layers": [layer_row(5, 3.02), layer_row(8, 4.01),
                                 layer_row(14, 3.19)]}
        self.assertEqual(cfg.pick_from_report(report, 3.0)["num_gpu"], 8)

    def test_repeated_settings_are_averaged_not_maximised(self):
        # The defect: setting 4 has the single best run (5.00) but the worse
        # mean (3.33); setting 3 is worse at its best and better on average.
        # Comparing best-single-run hands the win to whichever setting happened
        # to be measured on the machine's quietest moment.
        report = {"gpu_layers": [
            layer_row(3, 3.90), layer_row(3, 3.80), layer_row(3, 3.70),
            layer_row(4, 5.00), layer_row(4, 2.50), layer_row(4, 2.50)]}
        picks = cfg.pick_from_report(report, 3.0)
        self.assertEqual(picks["num_gpu"], 3)
        self.assertIn("mean of 3 runs", picks["notes"]["num_gpu"])

    def test_a_repeated_thread_setting_is_averaged_too(self):
        report = {"sweep": [
            thread_row(14, 14, 3.90, 80.0), thread_row(14, 14, 3.80, 80.0),
            thread_row(20, 20, 5.00, 99.0), thread_row(20, 20, 2.40, 99.0)]}
        picks = cfg.pick_from_report(report, 3.0)
        # 14 means 3.85, 20 means 3.70, so 14 wins on the mean AND is the lower
        # rung; the single 5.00 must not carry 20 threads.
        self.assertEqual(picks["num_thread"], 14)

    def test_group_means_reports_how_many_runs_it_averaged(self):
        groups = cfg.group_means([layer_row(3, 4.0), layer_row(3, 2.0),
                                  layer_row(8, 3.0)], "layers_offloaded")
        self.assertEqual([g["key"] for g in groups], [3, 8])
        self.assertEqual(groups[0]["mean"], 3.0)
        self.assertEqual(groups[0]["n"], 2)
        self.assertEqual(groups[1]["n"], 1)

    def test_an_empty_report_yields_no_values_and_states_why(self):
        picks = cfg.pick_from_report({}, 3.0)
        self.assertIsNone(picks["num_thread"])
        self.assertIsNone(picks["num_gpu"])
        self.assertTrue(picks["notes"]["num_gpu"])

    def test_a_num_gpu_measured_at_another_window_is_warned_about(self):
        # The trap this exists for: KV cache grows with the window and takes the
        # VRAM those layers need. Measured 272 MiB at 8192 and 2432 at 65536.
        picks = cfg.pick_from_report({"gpu_layers": [layer_row(8, 4.01, 8192)]}, 3.0)
        warning = cfg.warn_window_mismatch(picks, 65536)
        self.assertIsNotNone(warning)
        self.assertIn("8192", warning)
        self.assertIn("65536", warning)

    def test_no_warning_when_the_window_matches(self):
        picks = cfg.pick_from_report({"gpu_layers": [layer_row(2, 3.48, 65536)]}, 3.0)
        self.assertIsNone(cfg.warn_window_mismatch(picks, 65536))


class TestModelfile(unittest.TestCase):

    def _render(self, picks):
        terms = cfg.compute_floor(fixture_budget(), "b", fixture_skills(), "s")
        return cfg.render_modelfile("fixture-model:test", 65536, picks,
                                    terms["reply"], terms)

    def test_the_measured_parameters_are_emitted(self):
        text = self._render({"num_gpu": 8, "num_thread": 14,
                             "notes": {"num_gpu": "m", "num_thread": "m"}})
        self.assertIn("FROM fixture-model:test", text)
        self.assertIn("PARAMETER num_ctx 65536", text)
        self.assertIn("PARAMETER num_predict 8192", text)
        self.assertIn("PARAMETER num_gpu 8", text)
        self.assertIn("PARAMETER num_thread 14", text)

    def test_an_unmeasured_parameter_is_omitted_and_explained(self):
        text = self._render({"num_gpu": None, "num_thread": None,
                             "notes": {"num_gpu": "nothing was measured",
                                       "num_thread": "nothing was measured"}})
        self.assertNotIn("PARAMETER num_gpu", text)
        self.assertNotIn("PARAMETER num_thread", text)
        self.assertIn("nothing was measured", text)

    def test_the_window_carries_its_derivation_in_a_comment(self):
        text = self._render({"num_gpu": 2, "num_thread": 14,
                             "notes": {"num_gpu": "m", "num_thread": "m"}})
        self.assertIn("33908", text.replace(" ", ""))
        self.assertIn("KV cache displaces weights", text)


class TestApply(unittest.TestCase):

    def test_an_absent_ollama_is_refused_and_nothing_is_written(self):
        with tempfile.TemporaryDirectory() as scratch:
            with self.assertRaises(cfg.Refusal) as caught:
                cfg.apply_tag("m:test", "FROM m:test\n", pathlib.Path(scratch),
                              which=lambda n: None)
            self.assertIn("PATH", str(caught.exception))
            self.assertEqual(list(pathlib.Path(scratch).iterdir()), [])

    def test_a_failed_create_is_refused_with_the_tool_output(self):
        def runner(argv, **kw):
            return FakeCompleted(1, "", "out of memory")
        with tempfile.TemporaryDirectory() as scratch:
            with self.assertRaises(cfg.Refusal) as caught:
                cfg.apply_tag("m:test", "FROM m:test\n", pathlib.Path(scratch),
                              runner=runner, which=lambda n: "ollama")
            self.assertIn("out of memory", str(caught.exception))

    def test_the_tuned_name_keeps_the_tag_portion(self):
        self.assertEqual(cfg.tuned_name("qwen-x:latest"), "qwen-x:latest-aider")
        self.assertEqual(cfg.tuned_name("ornith:9b-gpu"), "ornith:9b-gpu-aider")
        self.assertEqual(cfg.tuned_name("plain"), "plain-aider")

    def test_two_variants_of_one_family_do_not_collide(self):
        # The defect this replaced: dropping everything after the colon made
        # `ornith:9b` and `ornith:9b-gpu` both `ornith-aider`, so tuning the
        # second silently overwrote the first.
        self.assertNotEqual(cfg.tuned_name("ornith:9b"),
                            cfg.tuned_name("ornith:9b-gpu"))

    def test_the_tag_can_be_named_explicitly(self):
        calls = []
        def runner(argv, **kw):
            calls.append(argv)
            return FakeCompleted(0, "PARAMETER num_ctx 65536")
        with tempfile.TemporaryDirectory() as scratch:
            out = cfg.apply_tag("ornith:9b-gpu", "FROM ornith:9b-gpu\n",
                                pathlib.Path(scratch), runner=runner,
                                which=lambda n: "ollama", tag="ornith:9b-aider")
        self.assertEqual(out["tag"], "ornith:9b-aider")
        self.assertIn("ornith:9b-aider", calls[0])
        self.assertEqual(calls[0][1], "create")
        self.assertEqual(calls[1][1], "show")

    def test_a_parameter_missing_from_the_readback_is_reported(self):
        # `ollama create` exiting 0 is not evidence the parameters took.
        missing = cfg.verify_readback("PARAMETER num_ctx 65536\n",
                                      {"num_ctx": 65536, "num_gpu": 8})
        self.assertEqual(missing, ["num_gpu 8"])

    def test_a_complete_readback_reports_nothing_missing(self):
        missing = cfg.verify_readback(
            "PARAMETER num_ctx 65536\nPARAMETER num_gpu 8\n",
            {"num_ctx": 65536, "num_gpu": 8})
        self.assertEqual(missing, [])

    def test_an_unmeasured_parameter_is_not_expected_in_the_readback(self):
        self.assertEqual(cfg.verify_readback("PARAMETER num_ctx 100\n",
                                             {"num_ctx": 100, "num_gpu": None}), [])


class TestWiring(unittest.TestCase):
    """
    The two writers that make tuning take effect (G5). Every case is on a
    string or a dict, so nothing here reads or writes a real configuration
    file: the suite must pass on a machine that has never run the tuner.
    """

    NL = chr(10)

    def yaml_with(self, *entries):
        head = ("# hand-written header, with a measurement in it" + self.NL +
                "# num_ctx 262144 -> 0 of 66 layers on the card" + self.NL + self.NL)
        return head + self.NL.join(entries)

    def entry(self, tag, num_ctx=None, comment="# a comment nobody may discard"):
        body = [comment,
                "- name: ollama_chat/" + tag,
                "  edit_format: diff",
                "  extra_params:"]
        if num_ctx is not None:
            body.append("    num_ctx: " + str(num_ctx))
        body.append("    top_p: 0.95")
        return self.NL.join(body) + self.NL

    # --- model-settings.yml -------------------------------------------------

    def test_an_absent_entry_is_added(self):
        text = self.yaml_with(self.entry("base:latest", 262144))
        out, did = cfg.upsert_settings(text, "base:latest-aider", 65536, 8192)
        self.assertEqual(did, "added")
        self.assertIn("- name: ollama_chat/base:latest-aider", out)
        self.assertIn("num_ctx: 65536", out)
        self.assertIn("- name: ollama_chat/base:latest", out)

    def test_a_wrong_num_ctx_is_corrected_and_nothing_else_moves(self):
        # The fault this whole writer exists for: a tuned tag whose entry sends
        # the base window on every request runs at the base window, and the
        # tuning is invisible rather than absent.
        text = self.yaml_with(self.entry("base:latest", 262144),
                              self.entry("base:latest-aider", 262144))
        out, did = cfg.upsert_settings(text, "base:latest-aider", 65536, 8192)
        self.assertEqual(did, "corrected 262144 -> 65536")
        self.assertEqual(out.count("num_ctx: 262144"), 1,
                         "the BASE entry's window was rewritten too")
        self.assertEqual(out.count("num_ctx: 65536"), 1)
        self.assertIn("# a comment nobody may discard", out)
        self.assertIn("# num_ctx 262144 -> 0 of 66 layers on the card", out,
                      "the hand-written header carries measurements")

    def test_a_correct_entry_is_returned_byte_identical(self):
        # The caller writes nothing on "already correct", so this is what makes
        # a second run a genuine no-op rather than a rewrite that happens to
        # produce the same bytes.
        text = self.yaml_with(self.entry("base:latest-aider", 65536))
        out, did = cfg.upsert_settings(text, "base:latest-aider", 65536, 8192)
        self.assertEqual(did, "already correct")
        self.assertEqual(out, text)

    def test_an_entry_with_no_num_ctx_gets_one(self):
        text = self.yaml_with(self.entry("base:latest-aider", None))
        out, did = cfg.upsert_settings(text, "base:latest-aider", 65536, 8192)
        self.assertEqual(did, "inserted num_ctx 65536")
        self.assertIn("    num_ctx: 65536", out)

    def test_the_tag_is_matched_exactly_not_by_prefix(self):
        # ornith:9b-aider and ornith:9b-aider-v2 are two models. A prefix match
        # would tune one and rewrite the other, which is the collision
        # tuned_name() was already fixed for once.
        text = self.yaml_with(self.entry("ornith:9b-aider-v2", 262144))
        out, did = cfg.upsert_settings(text, "ornith:9b-aider", 65536, 8192)
        self.assertEqual(did, "added")
        self.assertIn("num_ctx: 262144", out, "the other model was rewritten")

    def test_a_new_entry_says_why_num_ctx_is_there(self):
        block = cfg.settings_block("t:1-aider", 65536, 8192)
        self.assertIn("OVERRIDES", block,
                      "an entry with no reason invites its own deletion")
        self.assertIn("8192", block)

    def test_a_new_entry_sends_num_predict_as_well_as_num_ctx(self):
        # Both, and for the same reason: a value in the REQUEST overrides the
        # tag's Modelfile, and relying on the Modelfile is what left a reply
        # truncated at ~2104 tokens on 2026-09-05 while the tag declared 8192.
        block = cfg.settings_block("t:1-aider", 65536, 8192)
        self.assertIn("num_ctx: 65536", block)
        self.assertIn("num_predict: 8192", block,
                      "without it the tag's own value governs, and it did not")

    # --- the litellm metadata ----------------------------------------------

    def test_metadata_is_added_with_the_window_and_the_reserve(self):
        out, did = cfg.upsert_metadata({}, "base:latest-aider", 65536, 8192)
        self.assertEqual(did, "added")
        entry = out["ollama_chat/base:latest-aider"]
        self.assertEqual(entry["max_input_tokens"], 65536)
        self.assertEqual(entry["max_output_tokens"], 8192)
        self.assertEqual(entry["litellm_provider"], "ollama_chat")
        self.assertIn("_comment", out)
        self.assertIn("num_ctx // 2 + 2", out["_comment"],
                      "the file has to say why it exists or it gets deleted")

    def test_a_stale_window_is_corrected(self):
        before = {"ollama_chat/t-aider": {"max_input_tokens": 262144,
                                          "max_output_tokens": 8192,
                                          "input_cost_per_token": 0.0,
                                          "output_cost_per_token": 0.0,
                                          "litellm_provider": "ollama_chat",
                                          "mode": "chat"}}
        out, did = cfg.upsert_metadata(before, "t-aider", 65536, 8192)
        self.assertEqual(did, "corrected max_input_tokens 262144 -> 65536")
        self.assertEqual(out["ollama_chat/t-aider"]["max_input_tokens"], 65536)

    def test_other_tags_and_a_hand_written_comment_survive(self):
        before = {"_comment": "mine, do not touch",
                  "ollama_chat/other": {"max_input_tokens": 4096}}
        out, _ = cfg.upsert_metadata(before, "t-aider", 65536, 8192)
        self.assertEqual(out["_comment"], "mine, do not touch")
        self.assertEqual(out["ollama_chat/other"]["max_input_tokens"], 4096)

    def test_a_correct_metadata_entry_is_already_correct(self):
        out, _ = cfg.upsert_metadata({}, "t-aider", 65536, 8192)
        again, did = cfg.upsert_metadata(out, "t-aider", 65536, 8192)
        self.assertEqual(did, "already correct")
        self.assertEqual(again, out)

    def test_the_input_mapping_is_never_mutated(self):
        # The caller decides whether to write. A writer that edited its argument
        # in place would have already changed the caller's view of the file by
        # the time it reported "already correct".
        before = {"ollama_chat/t-aider": {"max_input_tokens": 262144}}
        snapshot = json.loads(json.dumps(before))
        cfg.upsert_metadata(before, "t-aider", 65536, 8192)
        self.assertEqual(before, snapshot)


class TestCli(unittest.TestCase):

    def _run(self, extra, budget=None, skills=None):
        with tempfile.TemporaryDirectory() as scratch:
            root = pathlib.Path(scratch)
            (root / "context-budget.json").write_text(
                json.dumps(budget or fixture_budget()), encoding="utf-8")
            (root / "skills.json").write_text(
                json.dumps(skills or fixture_skills()), encoding="utf-8")
            argv = [sys.executable, str(SCRIPT),
                    "--budget", str(root / "context-budget.json"),
                    "--skills", str(root / "skills.json")] + extra
            done = subprocess.run(argv, capture_output=True, text=True, timeout=120)
            created = sorted(p.name for p in root.iterdir())
            return done, created

    def test_without_yes_it_prints_the_decision_and_creates_nothing(self):
        done, created = self._run(["--model", "fixture-model:test"])
        self.assertEqual(done.returncode, cfg.EXIT_OK, done.stderr)
        self.assertIn("num_ctx", done.stdout)
        self.assertIn("Nothing created", done.stdout)
        self.assertEqual(created, ["context-budget.json", "skills.json"])

    def test_a_missing_budget_file_exits_two(self):
        done = subprocess.run(
            [sys.executable, str(SCRIPT), "--budget", "nope.json",
             "--skills", "nope.json", "--model", "m:test"],
            capture_output=True, text=True, timeout=120)
        self.assertEqual(done.returncode, cfg.EXIT_REFUSED)
        self.assertIn("REFUSED", done.stderr)

    def test_no_model_anywhere_is_a_refusal(self):
        budget = fixture_budget()
        del budget["audit"]
        done, _ = self._run([], budget=budget)
        self.assertEqual(done.returncode, cfg.EXIT_REFUSED)
        self.assertIn("--model", done.stderr)

    def test_a_report_that_does_not_exist_is_a_refusal(self):
        done, _ = self._run(["--model", "m:test", "--report", "absent.json"])
        self.assertEqual(done.returncode, cfg.EXIT_REFUSED)
        self.assertIn("absent.json", done.stderr)

    def test_the_script_names_no_model_tag_of_its_own(self):
        # R2: exactly one place names a tag, and it is configuration.
        source = SCRIPT.read_text(encoding="utf-8")
        for tag in ("qwen3.8", "gemma4", "qwen2.5-coder", "ornith"):
            self.assertNotIn(tag, source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
