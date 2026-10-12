"""Offline tests for the local Ollama reviewer leg of the deliberation panel.

No daemon, no model, no network: the bridge is replaced by a fake that records every call, so a
test can assert what was NOT sent as well as what was. Everything is fictitious (R34). The shipped
config is read for its shape only, never for a machine-measured value (R21)."""

import json
import os
import re
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(HERE.parents[1] / "scopus" / "scripts"))

import deliberate  # noqa: E402
import ollama_reviewer as reviewer  # noqa: E402

TAG = "fictional-model:test"
WINDOW = reviewer.load_config()["num_ctx"]


def _window_must_come_from_the_config(_tag):
    raise AssertionError("the context window must come from ollama-reviewer.json, never from the bridge's measured table")


class BridgeError(RuntimeError):
    pass


class ReasoningAnomalyError(RuntimeError):
    pass


def fake_bridge(reply='{"a": "ok", "x": []}', prompt_tokens=100, window=WINDOW, post_error=None, done_reason="stop"):
    """A recording stand-in for ollama_bridge with only the seams ollama_reviewer uses."""
    calls = {"post": [], "probe": [], "resolve": []}

    def resolve_model(role=None):
        calls["resolve"].append(role)
        return TAG

    def post(payload, timeout):
        calls["post"].append((payload, timeout))
        if post_error:
            raise post_error
        return {"response": reply, "done_reason": done_reason}

    def probe(prompt, model, num_ctx, timeout=0):
        calls["probe"].append((model, num_ctx))
        return prompt_tokens

    bridge = types.SimpleNamespace(
        BridgeError=BridgeError,
        ReasoningAnomalyError=ReasoningAnomalyError,
        resolve_model=resolve_model,
        _resolve_num_ctx=_window_must_come_from_the_config,
        probe_prompt_tokens=probe,
        build_payload=lambda prompt, model, seed, num_ctx, fmt=None: {
            "model": model, "prompt": prompt, "format": fmt, "options": {"seed": seed, "num_ctx": num_ctx, "num_predict": 1024, "temperature": 0.2}},
        _post_generate=post,
        strip_reasoning=lambda text: text,
    )
    bridge.calls = calls
    return bridge


def run(bridge, **kwargs):
    with mock.patch.object(reviewer, "_bridge", return_value=bridge):
        return reviewer.run_ollama("question", **kwargs)


class TestConfig(unittest.TestCase):
    def test_shipped_config_has_every_key_with_provenance(self):
        raw = json.loads(reviewer.CONFIG_PATH.read_text(encoding="utf-8"))
        keys = {"role", "num_ctx", "request_timeout_s", "reply_tokens", "seed"}
        for key in keys:
            self.assertIn("provenance", raw[key], key)
            self.assertTrue(raw[key]["provenance"].strip(), key)
        self.assertEqual(set(reviewer.load_config()), keys)

    def test_the_reviewer_role_is_a_reasoning_role_not_the_memory_tuned_ones(self):
        # The operator's decision 2026-10-11: ornith is tuned for vault and graph memory work,
        # so the deliberation reviewer must not ride the writer or coder role.
        self.assertNotIn(reviewer.load_config()["role"], ("writer", "coder"))

    def test_the_window_leaves_room_for_the_reply(self):
        config = reviewer.load_config()
        self.assertGreater(config["num_ctx"], config["reply_tokens"])

    def test_a_missing_key_is_named(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "c.json"
            path.write_text(json.dumps({"role": {"value": "writer", "provenance": "t"}}), encoding="utf-8")
            with self.assertRaises(reviewer.ReviewerError) as context:
                reviewer.load_config(path)
            self.assertIn("reply_tokens", str(context.exception))

    def test_an_absent_file_is_a_reviewer_error_not_a_crash(self):
        with self.assertRaises(reviewer.ReviewerError):
            reviewer.load_config(Path("absent.json"))

    def test_the_module_names_no_model_tag(self):
        source = (SCRIPTS.parent.parent / "scopus" / "scripts" / "ollama_reviewer.py").read_text(encoding="utf-8")
        self.assertIsNone(re.search(r"\b[a-z][\w.-]*:\d+(?:\.\d+)?b\b", source, re.IGNORECASE), "a model tag literal is in the module")
        self.assertIsNone(re.search(r"qwen|gemma|(?<!o)llama|mistral", source, re.IGNORECASE), "a model family is named in the module")


class TestRunOllama(unittest.TestCase):
    def test_the_tag_comes_from_the_resolver_with_the_configured_role(self):
        bridge = fake_bridge()
        run(bridge)
        self.assertEqual(bridge.calls["resolve"], [reviewer.load_config()["role"]])
        self.assertEqual(bridge.calls["post"][0][0]["model"], TAG)

    def test_an_explicit_tag_bypasses_the_resolver(self):
        bridge = fake_bridge()
        run(bridge, model="explicit:tag")
        self.assertEqual(bridge.calls["resolve"], [])
        self.assertEqual(bridge.calls["post"][0][0]["model"], "explicit:tag")

    def test_the_reply_is_json_constrained_seeded_and_capped_by_the_configured_reply_tokens(self):
        bridge = fake_bridge()
        run(bridge, max_output_tokens=99999, temperature=0.7)
        payload, timeout = bridge.calls["post"][0]
        config = reviewer.load_config()
        self.assertEqual(payload["format"], "json")
        self.assertEqual(payload["options"]["seed"], config["seed"])
        self.assertEqual(payload["options"]["num_predict"], config["reply_tokens"])
        self.assertEqual(payload["options"]["temperature"], 0.7)
        self.assertEqual(timeout, float(config["request_timeout_s"]))

    def test_a_smaller_requested_cap_wins_over_the_configured_one(self):
        bridge = fake_bridge()
        run(bridge, max_output_tokens=300)
        self.assertEqual(bridge.calls["post"][0][0]["options"]["num_predict"], 300)

    def test_coded_keys_are_expanded_to_the_canonical_schema(self):
        reply = json.dumps({"a": "fine", "x": [{"s": "general", "t": "ti", "m": "tighten", "c": "h", "v": False}]})
        result = run(fake_bridge(reply=reply))
        self.assertEqual(result["overall_assessment"], "fine")
        suggestion = result["suggestions"][0]
        self.assertEqual((suggestion["type"], suggestion["confidence"], suggestion["suggestion"]), ("text_improvement", "high", "tighten"))

    def test_a_prompt_that_does_not_fit_is_refused_and_never_sent(self):
        bridge = fake_bridge(prompt_tokens=WINDOW)
        with self.assertRaises(reviewer.ReviewerError) as context:
            run(bridge)
        self.assertIn(str(WINDOW), str(context.exception))
        self.assertEqual(bridge.calls["post"], [])

    def test_a_prompt_that_just_fits_is_sent(self):
        reply_budget = reviewer.load_config()["reply_tokens"]
        bridge = fake_bridge(prompt_tokens=WINDOW - reply_budget)
        run(bridge)
        self.assertEqual(len(bridge.calls["post"]), 1)

    def test_a_daemon_failure_is_a_reviewer_error(self):
        with self.assertRaises(reviewer.ReviewerError) as context:
            run(fake_bridge(post_error=BridgeError("cannot reach the daemon")))
        self.assertIn("cannot reach", str(context.exception))

    def test_an_empty_reply_names_the_done_reason(self):
        with self.assertRaises(reviewer.ReviewerError) as context:
            run(fake_bridge(reply="   ", done_reason="length"))
        self.assertIn("length", str(context.exception))

    def test_an_unparsable_reply_keeps_the_raw_text_and_does_not_blame_gemini(self):
        with self.assertRaises(reviewer.ReviewerError) as context:
            run(fake_bridge(reply="I cannot comply with that."))
        self.assertEqual(context.exception.raw, "I cannot comply with that.")
        self.assertIn("Ollama", str(context.exception))
        self.assertNotIn("Gemini", str(context.exception))

    def test_a_reply_cut_by_the_cap_is_salvaged_to_its_last_complete_suggestion(self):
        cut = '{"a": "x", "x": [{"s": "g", "t": "ti", "m": "one", "c": "h", "v": false}, {"s": "g", "t": "ti", "m": "tw'
        result = run(fake_bridge(reply=cut))
        self.assertEqual([s["suggestion"] for s in result["suggestions"]], ["one"])

    def test_the_window_is_the_configured_one_and_the_request_carries_it(self):
        config = dict(reviewer.load_config(), num_ctx=5000)
        bridge = fake_bridge(prompt_tokens=100)
        with mock.patch.object(reviewer, "load_config", return_value=config):
            run(bridge)
        self.assertEqual(bridge.calls["probe"], [(TAG, 5000)])
        self.assertEqual(bridge.calls["post"][0][0]["options"]["num_ctx"], 5000)

    def test_a_prompt_over_the_configured_window_is_refused_with_the_configured_number(self):
        config = dict(reviewer.load_config(), num_ctx=1000)
        bridge = fake_bridge(prompt_tokens=900)
        with mock.patch.object(reviewer, "load_config", return_value=config):
            with self.assertRaises(reviewer.ReviewerError) as context:
                run(bridge)
        self.assertIn("1000", str(context.exception))
        self.assertEqual(bridge.calls["post"], [])


class TestAvailabilityAndBudget(unittest.TestCase):
    def test_available_when_the_resolver_names_a_tag(self):
        with mock.patch.object(reviewer, "_bridge", return_value=fake_bridge()):
            self.assertTrue(reviewer.ollama_available())

    def test_unavailable_when_the_resolver_refuses_and_it_never_raises(self):
        bridge = fake_bridge()
        bridge.resolve_model = mock.Mock(side_effect=BridgeError("ollama list exited 1"))
        with mock.patch.object(reviewer, "_bridge", return_value=bridge):
            self.assertFalse(reviewer.ollama_available())

    def test_unavailable_when_the_resolver_names_no_tag(self):
        bridge = fake_bridge()
        bridge.resolve_model = lambda role=None: ""
        with mock.patch.object(reviewer, "_bridge", return_value=bridge):
            self.assertFalse(reviewer.ollama_available())

    def test_input_budget_is_the_configured_window_minus_the_reply_tokens(self):
        config = dict(reviewer.load_config(), num_ctx=20000)
        with mock.patch.object(reviewer, "load_config", return_value=config):
            self.assertEqual(reviewer.input_budget(), 20000 - config["reply_tokens"])


GEM = {"overall_assessment": "g", "suggestions": [
    {"target_section": "H1", "type": "coverage_gap", "suggestion": "state the assumption", "confidence": "high", "requires_scopus_validation": False},
    {"target_section": "H2", "type": "style", "suggestion": "shorten", "confidence": "low", "requires_scopus_validation": False}]}
LOCAL = {"overall_assessment": "l", "suggestions": [
    {"target_section": "H1", "type": "coverage_gap", "suggestion": "name the delay bound", "confidence": "medium", "requires_scopus_validation": False},
    {"target_section": "H3", "type": "structure", "suggestion": "split the lemma", "confidence": "high", "requires_scopus_validation": False}]}


LONG_DRAFT = "\n".join(f"Paragraph {i}: the claim, its definitions and its assumptions, stated in full." for i in range(1, 40))


def panel(second="ollama", run_local=None, available=True, **extra):
    run_local = run_local or mock.Mock(return_value=LOCAL)
    with mock.patch.object(deliberate, "gemini_available", lambda: True), \
         mock.patch.object(deliberate, "count_gemini_tokens", lambda *_a, **_k: -1), \
         mock.patch.object(deliberate, "run_gemini", mock.Mock(return_value=GEM)), \
         mock.patch.object(deliberate, "ollama_available", lambda: available), \
         mock.patch.object(deliberate, "resolve_ollama_model", lambda role=None: TAG), \
         mock.patch.object(deliberate, "run_ollama", run_local):
        envelope = deliberate.deliberate(draft=extra.pop("draft", "d"), topic=extra.pop("topic", "t"), evidence=extra.pop("evidence", ""),
                                         rounds=1, gemini_model="g", copilot_model="c",
                                         temperature=0.3, plan_schema="generic", second=second, **extra)
    return envelope, run_local


class TestPanelWithTheLocalReviewer(unittest.TestCase):
    def test_the_envelope_names_the_local_reviewer_and_the_tag_the_resolver_gave(self):
        env, run_local = panel()
        self.assertEqual(env["second_reviewer"], "ollama")
        self.assertEqual(env["reviewers_available"], ["gemini", "ollama"])
        self.assertEqual(env["models"]["ollama"], TAG)
        self.assertNotIn("copilot", env["models"])
        self.assertIsNotNone(env["round1"]["ollama"])
        self.assertNotIn("copilot", env["round1"])
        self.assertEqual(run_local.call_args[0][1], TAG)

    def test_merge_tags_agreement_with_the_reviewer_name(self):
        env, _ = panel()
        by_section = {m["target_section"]: m for m in env["merged"]}
        self.assertEqual(by_section["H1"]["agreement"], "consensus")
        self.assertEqual(by_section["H1"]["sources"], ["gemini", "ollama"])
        self.assertEqual(by_section["H3"]["agreement"], "ollama_only")
        self.assertEqual(by_section["H2"]["agreement"], "gemini_only")
        self.assertNotIn("copilot_only", [m["agreement"] for m in env["merged"]])

    def test_a_single_high_confidence_local_suggestion_ranks_with_the_single_high_tier(self):
        env, _ = panel()
        ranks = {m["target_section"]: m["rank"] for m in env["merged"]}
        self.assertLess(ranks["H1"], ranks["H3"])
        self.assertLess(ranks["H3"], ranks["H2"])

    def test_a_failing_local_leg_is_marked_unavailable_and_gemini_still_answers(self):
        failing = mock.Mock(side_effect=reviewer.ReviewerError("daemon down"))
        env, _ = panel(run_local=failing)
        self.assertEqual(env["reviewers_unavailable"], ["ollama"])
        self.assertIn("[REVIEWER UNAVAILABLE: Ollama]", env["unavailable_markers"])
        self.assertEqual(env["round1"]["ollama"]["_error"], "daemon down")
        self.assertTrue(env["merged"])

    def test_an_unavailable_local_model_is_not_called(self):
        env, run_local = panel(available=False)
        self.assertEqual(run_local.call_count, 0)
        self.assertEqual(env["reviewers_unavailable"], ["ollama"])

    def test_the_local_reviewer_gets_the_same_untrimmed_prompt_as_gemini(self):
        env, run_local = panel(draft=LONG_DRAFT, topic="a precise topic", evidence="Title One\nclaim\n\nTitle Two\nclaim")
        local_prompt = run_local.call_args[0][0]
        self.assertIn(LONG_DRAFT.splitlines()[0], local_prompt)
        self.assertIn(LONG_DRAFT.splitlines()[-1], local_prompt)
        self.assertFalse(env["context"]["draft_digested"])

    def test_an_unknown_second_reviewer_is_refused(self):
        with self.assertRaises(ValueError):
            panel(second="gpt")

    def test_copilot_remains_the_default_and_keeps_its_envelope_shape(self):
        with mock.patch.object(deliberate, "gemini_available", lambda: True), \
             mock.patch.object(deliberate, "count_gemini_tokens", lambda *_a, **_k: -1), \
             mock.patch.object(deliberate, "copilot_available", lambda: True), \
             mock.patch.object(deliberate, "run_gemini", mock.Mock(return_value=GEM)), \
             mock.patch.object(deliberate, "run_copilot", mock.Mock(return_value=LOCAL)):
            env = deliberate.deliberate(draft="d", topic="t", evidence="", rounds=1, gemini_model="g", copilot_model="c",
                                        temperature=0.3, plan_schema="generic")
        self.assertEqual(env["second_reviewer"], "copilot")
        self.assertEqual(env["reviewers_available"], ["gemini", "copilot"])
        self.assertIn("copilot_provider", env["models"])
        self.assertIn("copilot_only", [m["agreement"] for m in env["merged"]])


class TestInstrumentation(unittest.TestCase):
    """Additive fields every caller of the panel can rely on, whatever the second reviewer."""

    def test_every_merged_item_carries_a_stable_unique_id_in_rank_order(self):
        env, _ = panel()
        ids = [m["id"] for m in env["merged"]]
        self.assertEqual(ids, [f"M{i}" for i in range(1, len(env["merged"]) + 1)])
        self.assertEqual([m["rank"] for m in env["merged"]], list(range(1, len(ids) + 1)))

    def test_an_intact_context_reports_no_reduction_and_no_warning_when_topic_and_evidence_are_given(self):
        env, _ = panel(draft=LONG_DRAFT, topic="a precise topic", evidence="Title One\nclaim")
        context = env["context"]
        self.assertFalse(context["draft_digested"])
        self.assertFalse(context["evidence_squeezed"])
        self.assertEqual(context["warnings"], [])

    def test_a_digested_draft_is_reported_with_both_sizes_never_in_silence(self):
        draft = "# Heading one\n" + LONG_DRAFT + "\n# Heading two"
        env, _ = panel(draft=draft, topic="t", evidence="e", max_input_tokens=50)
        context = env["context"]
        self.assertTrue(context["draft_digested"])
        self.assertGreater(context["draft_chars_in"], context["draft_chars_out"])
        self.assertTrue(any("DIGESTED" in w for w in context["warnings"]))

    def test_a_missing_topic_and_missing_evidence_are_each_warned(self):
        env, _ = panel(draft="d", topic="", evidence="")
        warnings = " ".join(env["context"]["warnings"])
        self.assertIn("no --topic", warnings)
        self.assertIn("no evidence", warnings)

    def test_the_context_record_is_present_on_the_copilot_default_too(self):
        with mock.patch.object(deliberate, "gemini_available", lambda: True), \
             mock.patch.object(deliberate, "count_gemini_tokens", lambda *_a, **_k: -1), \
             mock.patch.object(deliberate, "copilot_available", lambda: True), \
             mock.patch.object(deliberate, "run_gemini", mock.Mock(return_value=GEM)), \
             mock.patch.object(deliberate, "run_copilot", mock.Mock(return_value=LOCAL)):
            env = deliberate.deliberate(draft="d", topic="t", evidence="e", rounds=1, gemini_model="g", copilot_model="c",
                                        temperature=0.3, plan_schema="generic")
        self.assertIn("context", env)
        self.assertIn("id", env["merged"][0])


class TestChoosingTheSecondReviewer(unittest.TestCase):
    def test_an_explicit_choice_is_honoured_with_no_fallback(self):
        self.assertEqual(deliberate.pick_second_reviewer("ollama", ["copilot", "ollama"]), ("ollama", None))
        self.assertEqual(deliberate.pick_second_reviewer("copilot", ["copilot", "ollama"]), ("copilot", None))

    def test_auto_takes_the_first_as_the_second_reviewer_and_the_next_as_the_fallback(self):
        self.assertEqual(deliberate.pick_second_reviewer("auto", ["copilot", "ollama"]), ("copilot", "ollama"))
        self.assertEqual(deliberate.pick_second_reviewer("auto", ["ollama", "copilot"]), ("ollama", "copilot"))

    def test_auto_with_a_single_name_has_no_fallback(self):
        self.assertEqual(deliberate.pick_second_reviewer("auto", ["copilot"]), ("copilot", None))

    def test_the_shipped_order_is_copilot_then_the_local_fallback(self):
        self.assertEqual(deliberate.load_second_reviewer_order(), ["copilot", "ollama"])

    def test_an_unknown_reviewer_in_the_order_is_refused_by_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "c.json"
            path.write_text(json.dumps({"second_reviewer_order": {"value": ["gpt"], "provenance": "t"}}), encoding="utf-8")
            with self.assertRaises(ValueError) as context:
                deliberate.load_second_reviewer_order(path)
            self.assertIn("gpt", str(context.exception))

    def test_a_missing_file_is_a_named_error(self):
        with self.assertRaises(ValueError):
            deliberate.load_second_reviewer_order(Path("absent.json"))


def fallback_panel(copilot_ready=True, copilot=None, ollama_ready=True, local=None, second="copilot", fallback="ollama", **extra):
    """The panel with BOTH second reviewers patched, returning the envelope and the mocks."""
    copilot = copilot or mock.Mock(return_value=LOCAL)
    local = local or mock.Mock(return_value=LOCAL)
    probe = mock.Mock(side_effect=lambda: ollama_ready)
    resolve = mock.Mock(side_effect=lambda role=None: TAG)
    with mock.patch.object(deliberate, "gemini_available", lambda: True), \
         mock.patch.object(deliberate, "count_gemini_tokens", lambda *_a, **_k: -1), \
         mock.patch.object(deliberate, "run_gemini", mock.Mock(return_value=GEM)), \
         mock.patch.object(deliberate, "copilot_available", lambda: copilot_ready), \
         mock.patch.object(deliberate, "run_copilot", copilot), \
         mock.patch.object(deliberate, "resolve_copilot_model", lambda: ("copilot-model", "")), \
         mock.patch.object(deliberate, "ollama_available", probe), \
         mock.patch.object(deliberate, "resolve_ollama_model", resolve), \
         mock.patch.object(deliberate, "run_ollama", local):
        rounds = extra.pop("rounds", 1)
        envelope = deliberate.deliberate(draft=extra.pop("draft", "d"), topic=extra.pop("topic", "t"), evidence=extra.pop("evidence", ""),
                                         rounds=rounds, gemini_model="g", copilot_model="auto",
                                         temperature=0.3, plan_schema="generic", second=second, fallback=fallback, **extra)
    return envelope, copilot, local, probe, resolve


class TestTheLocalModelAsTheFallback(unittest.TestCase):
    def test_copilot_answering_means_the_local_model_is_never_probed_or_resolved(self):
        env, _copilot, local, probe, resolve = fallback_panel()
        self.assertEqual(env["second_reviewer"], "copilot")
        self.assertNotIn("fallback", env)
        self.assertEqual(local.call_count, 0)
        self.assertEqual(probe.call_count, 0)
        self.assertEqual(resolve.call_count, 0)

    def test_copilot_failing_at_the_call_falls_back_to_the_local_model_at_that_moment(self):
        failing = mock.Mock(side_effect=reviewer.ReviewerError("'str' object has no attribute 'choices'"))
        env, copilot, local, _probe, _resolve = fallback_panel(copilot=failing)
        self.assertEqual(copilot.call_count, 1)
        self.assertEqual(local.call_count, 1)
        self.assertEqual(env["second_reviewer"], "ollama")
        self.assertEqual(env["models"]["ollama"], TAG)
        self.assertNotIn("copilot", env["models"])
        self.assertEqual(env["reviewers_available"], ["gemini", "ollama"])
        self.assertEqual(env["reviewers_unavailable"], ["copilot"])
        self.assertIn("[REVIEWER UNAVAILABLE: Copilot]", env["unavailable_markers"])
        self.assertEqual(env["fallback"]["from"], "copilot")
        self.assertEqual(env["fallback"]["to"], "ollama")
        self.assertIn("choices", env["fallback"]["reason"])
        self.assertIsNotNone(env["round1"]["ollama"])
        self.assertNotIn("copilot", env["round1"])
        self.assertIn("ollama_only", [m["agreement"] for m in env["merged"]])

    def test_copilot_unavailable_goes_straight_to_the_local_model_without_calling_copilot(self):
        env, copilot, local, _probe, _resolve = fallback_panel(copilot_ready=False)
        self.assertEqual(copilot.call_count, 0)
        self.assertEqual(local.call_count, 1)
        self.assertEqual(env["second_reviewer"], "ollama")
        self.assertEqual(env["fallback"]["reason"], "unavailable")

    def test_both_second_reviewers_failing_still_returns_gemini_and_names_both(self):
        env, _c, _l, _p, _r = fallback_panel(
            copilot=mock.Mock(side_effect=reviewer.ReviewerError("copilot down")),
            local=mock.Mock(side_effect=reviewer.ReviewerError("daemon down")))
        self.assertEqual(env["second_reviewer"], "copilot")
        self.assertEqual(env["reviewers_available"], ["gemini"])
        self.assertEqual(env["reviewers_unavailable"], ["copilot", "ollama"])
        self.assertEqual(env["round1"]["copilot"]["_error"], "copilot down")
        self.assertTrue(env["merged"])
        self.assertNotIn("fallback", env)

    def test_an_explicit_second_reviewer_never_falls_back(self):
        failing = mock.Mock(side_effect=reviewer.ReviewerError("copilot down"))
        env, _c, local, _p, _r = fallback_panel(copilot=failing, fallback=None)
        self.assertEqual(local.call_count, 0)
        self.assertEqual(env["reviewers_unavailable"], ["copilot"])

    def test_the_fallback_gets_the_identical_prompt_and_the_prompt_is_built_once(self):
        failing = mock.Mock(side_effect=reviewer.ReviewerError("copilot down"))
        with mock.patch.object(deliberate, "_fit_round1_prompt", wraps=deliberate._fit_round1_prompt) as spy:
            _env, copilot, local, _p, _r = fallback_panel(copilot=failing, draft=LONG_DRAFT, max_input_tokens=12000)
        self.assertEqual(spy.call_count, 1)
        self.assertEqual(copilot.call_args[0][0], local.call_args[0][0])

    def test_a_prompt_too_large_for_the_local_window_is_refused_with_the_numbers_never_digested(self):
        failing = mock.Mock(side_effect=reviewer.ReviewerError("copilot down"))
        too_big = mock.Mock(side_effect=reviewer.ReviewerError("the prompt is 20000 tokens and the reply budget 2048, over the 16384-token window"))
        env, _c, local, _p, _r = fallback_panel(copilot=failing, local=too_big, draft=LONG_DRAFT)
        self.assertEqual(too_big.call_count, 1)
        self.assertEqual(env["reviewers_unavailable"], ["copilot", "ollama"])
        self.assertIn("20000", env["unavailable_markers"] and json.dumps(env["round1"]) + json.dumps(env.get("fallback", {})) + str(too_big.side_effect))
        self.assertFalse(env["context"]["draft_digested"])
        # the prompt the local model was handed still holds the whole draft
        self.assertIn(LONG_DRAFT.splitlines()[-1], too_big.call_args[0][0])

    def test_round_two_goes_to_the_reviewer_that_answered(self):
        failing = mock.Mock(side_effect=reviewer.ReviewerError("copilot down"))
        env, copilot, local, _p, _r = fallback_panel(copilot=failing, rounds=2)
        self.assertEqual(copilot.call_count, 1)  # round 1 only: a reviewer that failed is not asked again
        self.assertEqual(local.call_count, 2)
        self.assertEqual(env["rounds_executed"], 2)

    def test_an_unknown_fallback_is_refused(self):
        with self.assertRaises(ValueError):
            fallback_panel(fallback="gpt")


if __name__ == "__main__":
    unittest.main()
