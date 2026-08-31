"""
test_deliberate.py — offline unit tests for the deliberation panel.

The Gemini and Copilot cores are patched (mock.patch.object on the deliberate module), so no
API keys, no google-genai/openai install, and no network are needed. Two CLI tests run the
script as a subprocess to verify exit codes and the both-unavailable regression guard.

Run:
    cd .claude/skills/deliberation
    python -m pytest Test/test_deliberate.py -v
    # or: python Test/test_deliberate.py
"""

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

_HERE = Path(__file__).resolve().parent
_SCRIPTS = _HERE.parent / "scripts"
# The reviewer cores and the shared schema module live in the sibling scopus skill.
_SCOPUS_SCRIPTS = _HERE.parents[1] / "scopus" / "scripts"
sys.path.insert(0, str(_SCRIPTS))
sys.path.insert(0, str(_SCOPUS_SCRIPTS))

import copilot_providers  # noqa: E402
import deliberate  # noqa: E402
import gemini_reviewer  # noqa: E402
import github_reviewer  # noqa: E402
import reviewer_schema  # noqa: E402

_SCRIPT = _SCRIPTS / "deliberate.py"

# --- fixtures -------------------------------------------------------------------------------

GEM_R1 = {
    "overall_assessment": "g1",
    "suggestions": [
        {"target_section": "B2", "type": "reference_issue", "suggestion": "add ref X",
         "confidence": "high", "requires_scopus_validation": True},
        {"target_section": "C", "type": "style", "suggestion": "tighten prose",
         "confidence": "low", "requires_scopus_validation": False},
    ],
}
COP_R1 = {
    "overall_assessment": "c1",
    "suggestions": [
        {"target_section": "B2", "type": "reference_issue", "suggestion": "cite Y",
         "confidence": "medium", "requires_scopus_validation": True},
        {"target_section": "E", "type": "coverage_gap", "suggestion": "missing baseline",
         "confidence": "high", "requires_scopus_validation": True},
    ],
}
GEM_R2 = {
    "overall_assessment": "g2",
    "suggestions": [
        {"target_section": "B2", "type": "reference_issue", "suggestion": "add ref X (revised)",
         "confidence": "high", "requires_scopus_validation": True},
        {"target_section": "M", "type": "methodology", "suggestion": "justify model",
         "confidence": "medium", "requires_scopus_validation": False},
        {"target_section": "C", "type": "style", "suggestion": "tighten prose",
         "confidence": "low", "requires_scopus_validation": False},
    ],
    "responses_to_other": [
        {"target_section": "B2", "stance": "disagree", "reason": "the ref is wrong"}],
}
COP_R2 = {
    "overall_assessment": "c2",
    "suggestions": [
        {"target_section": "B2", "type": "reference_issue", "suggestion": "cite Y instead",
         "confidence": "medium", "requires_scopus_validation": True},
        {"target_section": "M", "type": "methodology", "suggestion": "add ablation",
         "confidence": "high", "requires_scopus_validation": False},
        {"target_section": "E", "type": "coverage_gap", "suggestion": "missing baseline",
         "confidence": "high", "requires_scopus_validation": True},
    ],
    "responses_to_other": [{"target_section": "M", "stance": "agree", "reason": "ok"}],
}


class TestDeliberateMerge(unittest.TestCase):

    def test_both_keys_debate_round(self):
        with mock.patch.object(deliberate, "gemini_available", lambda: True), \
             mock.patch.object(deliberate, "copilot_available", lambda: True), \
             mock.patch.object(deliberate, "run_gemini", mock.Mock(side_effect=[GEM_R1, GEM_R2])) as rg, \
             mock.patch.object(deliberate, "run_copilot", mock.Mock(side_effect=[COP_R1, COP_R2])) as rc:
            env = deliberate.deliberate(
                draft="draft", topic="t", evidence="ev", rounds=2,
                gemini_model="g", copilot_model="c", temperature=0.3, plan_schema="auditor")

        self.assertEqual(env["reviewers_available"], ["gemini", "copilot"])
        self.assertEqual(env["reviewers_unavailable"], [])
        self.assertEqual(env["rounds_executed"], 2)
        self.assertIsNotNone(env["round2"]["gemini"])
        self.assertIsNotNone(env["round2"]["copilot"])
        self.assertEqual(rg.call_count, 2)
        self.assertEqual(rc.call_count, 2)

        merged = env["merged"]
        self.assertEqual(len(merged), 4)
        by_section = {m["target_section"]: m for m in merged}

        self.assertEqual(by_section["M"]["agreement"], "consensus")
        self.assertEqual(by_section["M"]["confidence"], "high")  # best of medium/high
        self.assertEqual(by_section["B2"]["agreement"], "conflict")
        self.assertIn("gemini:", by_section["B2"]["conflict_notes"])
        self.assertIn("copilot:", by_section["B2"]["conflict_notes"])
        self.assertEqual(by_section["C"]["agreement"], "gemini_only")
        self.assertEqual(by_section["E"]["agreement"], "copilot_only")

        # ranking: consensus first, then single-high, then conflict, then single-low
        self.assertEqual(merged[0]["target_section"], "M")
        self.assertEqual([m["rank"] for m in merged], [1, 2, 3, 4])
        self.assertIn("1 consensus", env["overall_assessment"])
        self.assertIn("1 conflict", env["overall_assessment"])

    def test_one_key_only_gemini(self):
        with mock.patch.object(deliberate, "gemini_available", lambda: True), \
             mock.patch.object(deliberate, "copilot_available", lambda: False), \
             mock.patch.object(deliberate, "run_gemini", mock.Mock(side_effect=[GEM_R1, GEM_R2])), \
             mock.patch.object(deliberate, "run_copilot", mock.Mock()) as rc:
            env = deliberate.deliberate(
                draft="draft", topic="t", evidence="", rounds=2,
                gemini_model="g", copilot_model="c", temperature=0.3, plan_schema="generic")

        self.assertEqual(env["reviewers_available"], ["gemini"])
        self.assertEqual(env["reviewers_unavailable"], ["copilot"])
        self.assertIn("[REVIEWER UNAVAILABLE: Copilot]", env["unavailable_markers"])
        self.assertEqual(rc.call_count, 0)
        self.assertTrue(env["merged"])
        self.assertTrue(all(m["agreement"] == "gemini_only" for m in env["merged"]))
        self.assertIsNotNone(env["round2"]["gemini"])

    def test_neither_key_is_noop_not_abort(self):
        with mock.patch.object(deliberate, "gemini_available", lambda: False), \
             mock.patch.object(deliberate, "copilot_available", lambda: False):
            env = deliberate.deliberate(
                draft="draft", topic="t", evidence="", rounds=2,
                gemini_model="g", copilot_model="c", temperature=0.3, plan_schema="generic")

        self.assertEqual(env["merged"], [])
        self.assertEqual(env["reviewers_unavailable"], ["gemini", "copilot"])
        self.assertIn("[REVIEWER UNAVAILABLE: Gemini]", env["unavailable_markers"])
        self.assertIn("[REVIEWER UNAVAILABLE: Copilot]", env["unavailable_markers"])
        self.assertTrue(env["overall_assessment"].startswith("Deliberation skipped"))
        self.assertEqual(env["rounds_executed"], 0)

    def test_rounds_one_skips_rebuttal(self):
        with mock.patch.object(deliberate, "gemini_available", lambda: True), \
             mock.patch.object(deliberate, "copilot_available", lambda: True), \
             mock.patch.object(deliberate, "run_gemini", mock.Mock(side_effect=[GEM_R1])) as rg, \
             mock.patch.object(deliberate, "run_copilot", mock.Mock(side_effect=[COP_R1])) as rc:
            env = deliberate.deliberate(
                draft="draft", topic="t", evidence="", rounds=1,
                gemini_model="g", copilot_model="c", temperature=0.3, plan_schema="generic")

        self.assertEqual(rg.call_count, 1)
        self.assertEqual(rc.call_count, 1)
        self.assertIsNone(env["round2"]["gemini"])
        self.assertIsNone(env["round2"]["copilot"])
        self.assertEqual(env["rounds_executed"], 1)
        by_section = {m["target_section"]: m for m in env["merged"]}
        # B2 shared, no responses_to_other in round 1 -> consensus
        self.assertEqual(by_section["B2"]["agreement"], "consensus")

    def test_model_api_failure_marks_unavailable(self):
        with mock.patch.object(deliberate, "gemini_available", lambda: True), \
             mock.patch.object(deliberate, "copilot_available", lambda: True), \
             mock.patch.object(deliberate, "run_gemini", mock.Mock(side_effect=[GEM_R1, GEM_R2])), \
             mock.patch.object(deliberate, "run_copilot",
                               mock.Mock(side_effect=RuntimeError("429 quota"))):
            env = deliberate.deliberate(
                draft="draft", topic="t", evidence="", rounds=2,
                gemini_model="g", copilot_model="c", temperature=0.3, plan_schema="generic")

        self.assertEqual(env["reviewers_available"], ["gemini"])
        self.assertIn("copilot", env["reviewers_unavailable"])
        self.assertIn("[REVIEWER UNAVAILABLE: Copilot]", env["unavailable_markers"])
        self.assertTrue(all(m["agreement"] == "gemini_only" for m in env["merged"]))


class TestDeliberateCLI(unittest.TestCase):

    def _env_no_keys(self):
        env = dict(os.environ)
        env.pop("GEMINI_API_KEY", None)
        env.pop("GITHUB_TOKEN", None)
        return env

    def test_empty_stdin_exits_1(self):
        proc = subprocess.run(
            [sys.executable, str(_SCRIPT), "--stdin"],
            input="", capture_output=True, text=True, env=self._env_no_keys())
        self.assertEqual(proc.returncode, 1)
        self.assertIn("empty", proc.stderr.lower())

    def test_unreadable_evidence_file_exits_1(self):
        proc = subprocess.run(
            [sys.executable, str(_SCRIPT), "some draft text",
             "--evidence-file", str(_HERE / "does_not_exist_xyz.txt")],
            capture_output=True, text=True, env=self._env_no_keys())
        self.assertEqual(proc.returncode, 1)
        self.assertIn("evidence-file", proc.stderr.lower())

    def test_both_unavailable_cli_exits_0_with_skip(self):
        # No keys + google-genai/openai absent -> both unavailable -> no-op envelope, exit 0.
        proc = subprocess.run(
            [sys.executable, str(_SCRIPT), "--stdin", "--topic", "x"],
            input="a real draft", capture_output=True, text=True, env=self._env_no_keys())
        self.assertEqual(proc.returncode, 0)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["merged"], [])
        self.assertTrue(payload["overall_assessment"].startswith("Deliberation skipped"))


_LATEX_DRAFT = (
    "\\documentclass{article}\n"
    "\\begin{document}\n"
    "\\section{Intro} % inline comment\n"
    "Ordinary prose dropped in a digest.\n"
    "- A1 fix the gap\n"
    "Issue: missing baseline\n"
    "```code\nx=1\n```\n"
    "\\end{document}\n"
)
_EVIDENCE = ("Title One\nlong abstract line\nmore detail\n\n"
             "Title Two\nabs two\n\nTitle Three\nx\n\nTitle Four\ny")


class TestCompressionHelpers(unittest.TestCase):

    def test_strip_source_drops_format_noise_keeps_claims(self):
        out = deliberate._strip_source(_LATEX_DRAFT)
        self.assertIn("\\section{Intro}", out)
        self.assertNotIn("% inline comment", out)   # LaTeX comment stripped
        self.assertNotIn("x=1", out)                # code fence dropped
        self.assertNotIn("documentclass", out)      # preamble dropped
        self.assertIn("Ordinary prose", out)        # prose kept (only digested when over budget)

    def test_digest_keeps_signal_lines_only(self):
        digest = deliberate._digest_draft(deliberate._strip_source(_LATEX_DRAFT))
        self.assertNotIn("Ordinary prose", digest)
        self.assertIn("\\section{Intro}", digest)
        self.assertIn("- A1 fix the gap", digest)
        self.assertIn("Issue: missing baseline", digest)

    def test_trim_evidence_caps_items_and_lines(self):
        out = deliberate._trim_evidence(_EVIDENCE, 2)
        self.assertIn("Title One", out)
        self.assertIn("Title Two", out)
        self.assertNotIn("Title Three", out)        # capped to top-2 items
        self.assertNotIn("more detail", out)        # only first 2 lines per item kept

    def test_expand_schema_round_trips_coded(self):
        coded = {"a": "oa",
                 "x": [{"s": "B2", "t": "ri", "m": "add", "c": "h", "v": True}],
                 "r": [{"s": "B2", "st": "d", "rs": "why"}]}
        exp = deliberate._expand_schema(coded)
        self.assertEqual(exp["overall_assessment"], "oa")
        sug = exp["suggestions"][0]
        self.assertEqual(sug["target_section"], "B2")
        self.assertEqual(sug["type"], "reference_issue")
        self.assertEqual(sug["confidence"], "high")
        self.assertIs(sug["requires_scopus_validation"], True)
        self.assertEqual(exp["responses_to_other"][0]["stance"], "disagree")

    def test_expand_schema_is_idempotent_on_canonical(self):
        self.assertEqual(deliberate._expand_schema(GEM_R1), GEM_R1)

    def test_round1_prompt_respects_terse_and_coded_flags(self):
        on = deliberate._round1_prompt("d", "t", "e", "hint", terse=True, coded=True)
        self.assertIn("caveman-terse", on)
        self.assertIn('"x":', on)                   # coded schema key
        off = deliberate._round1_prompt("d", "t", "e", "hint", terse=False, coded=False)
        self.assertNotIn("caveman-terse", off)
        self.assertIn('"suggestions"', off)         # canonical schema


class TestBudgetFit(unittest.TestCase):

    def test_digests_when_over_budget(self):
        with mock.patch.object(deliberate, "count_gemini_tokens", lambda text, model: 999999):
            p = deliberate._fit_round1_prompt(
                _LATEX_DRAFT, "t", _EVIDENCE, "hint", "g",
                max_input_tokens=50, max_evidence_items=6, terse=True, coded=True,
                max_suggestions=10, report_tokens=False)
        self.assertNotIn("Ordinary prose", p)       # draft digested away
        self.assertIn("- A1 fix the gap", p)        # signal line survived

    def test_keeps_full_draft_under_budget(self):
        with mock.patch.object(deliberate, "count_gemini_tokens", lambda text, model: 1):
            p = deliberate._fit_round1_prompt(
                _LATEX_DRAFT, "t", _EVIDENCE, "hint", "g",
                max_input_tokens=100000, max_evidence_items=6, terse=True, coded=True,
                max_suggestions=10, report_tokens=False)
        self.assertIn("Ordinary prose", p)


class TestSlimRound2(unittest.TestCase):

    def test_round2_omits_draft_and_threads_output_cap(self):
        marker = "UNIQUE_DRAFT_MARKER prose body"
        rg = mock.Mock(side_effect=[GEM_R1, GEM_R2])
        rc = mock.Mock(side_effect=[COP_R1, COP_R2])
        with mock.patch.object(deliberate, "gemini_available", lambda: True), \
             mock.patch.object(deliberate, "copilot_available", lambda: True), \
             mock.patch.object(deliberate, "count_gemini_tokens", lambda text, model: 1), \
             mock.patch.object(deliberate, "run_gemini", rg), \
             mock.patch.object(deliberate, "run_copilot", rc):
            deliberate.deliberate(
                draft=marker, topic="t", evidence="ev", rounds=2,
                gemini_model="g", copilot_model="c", temperature=0.3, plan_schema="auditor",
                max_output_tokens=777)

        r1_prompt = rg.call_args_list[0].args[0]
        r2_prompt = rg.call_args_list[1].args[0]
        self.assertIn("UNIQUE_DRAFT_MARKER", r1_prompt)      # round 1 carries the draft
        self.assertNotIn("UNIQUE_DRAFT_MARKER", r2_prompt)   # round 2 is slim
        self.assertEqual(rg.call_args_list[0].args[3], 777)  # max_output_tokens threaded


class TestReviewerSchemaTolerance(unittest.TestCase):
    """The two legs must survive a model that answers in coded keys or in nothing parsable.
    Cases 1-3 of docs/superpowers/plans/done/2026-08-04-deliberation-gemini-fix."""

    def test_strict_json_canonical_keys_parses_unchanged(self):
        rg = mock.Mock(side_effect=[GEM_R1, GEM_R2])
        with mock.patch.object(deliberate, "gemini_available", lambda: True), \
             mock.patch.object(deliberate, "copilot_available", lambda: False), \
             mock.patch.object(deliberate, "run_gemini", rg):
            env = deliberate.deliberate(
                draft="draft", topic="t", evidence="", rounds=2,
                gemini_model="g", copilot_model="c", temperature=0.3, plan_schema="generic")

        self.assertEqual(len(env["round1"]["gemini"]["suggestions"]), 2)
        self.assertEqual(env["round1"]["gemini"]["suggestions"][0]["type"], "reference_issue")
        self.assertEqual(len(env["merged"]), 3)  # the three sections of GEM_R2

    def test_coded_keys_are_expanded_to_canonical(self):
        coded_r1 = {"a": "oa", "x": [{"s": "B2", "t": "cg", "m": "gap", "c": "h", "v": True}]}
        with mock.patch.object(deliberate, "gemini_available", lambda: True), \
             mock.patch.object(deliberate, "copilot_available", lambda: False), \
             mock.patch.object(deliberate, "run_gemini", mock.Mock(side_effect=[coded_r1])):
            env = deliberate.deliberate(
                draft="draft", topic="t", evidence="", rounds=1,
                gemini_model="g", copilot_model="c", temperature=0.3, plan_schema="generic")

        logged = env["round1"]["gemini"]
        self.assertEqual(logged["overall_assessment"], "oa")
        self.assertEqual(logged["suggestions"][0]["type"], "coverage_gap")
        self.assertEqual(env["merged"][0]["target_section"], "B2")
        self.assertEqual(env["merged"][0]["confidence"], "high")

    def test_unparsable_gemini_keeps_raw_and_other_leg_continues(self):
        broken = gemini_reviewer.ReviewerError(
            "Gemini returned non-JSON response: I cannot", raw="I cannot comply with that.")
        with mock.patch.object(deliberate, "gemini_available", lambda: True), \
             mock.patch.object(deliberate, "copilot_available", lambda: True), \
             mock.patch.object(deliberate, "run_gemini", mock.Mock(side_effect=broken)), \
             mock.patch.object(deliberate, "run_copilot", mock.Mock(side_effect=[COP_R1, COP_R2])):
            env = deliberate.deliberate(
                draft="draft", topic="t", evidence="", rounds=2,
                gemini_model="g", copilot_model="c", temperature=0.3, plan_schema="generic")

        logged = env["round1"]["gemini"]
        self.assertIn("_error", logged)                       # the failure is reported...
        self.assertEqual(logged["_raw"], "I cannot comply with that.")  # ...with the raw text
        self.assertEqual(logged["suggestions"], [])
        self.assertEqual(env["reviewers_unavailable"], ["gemini"])
        self.assertTrue(env["merged"])                        # the panel did not die
        self.assertTrue(all(m["agreement"] == "copilot_only" for m in env["merged"]))

    def test_salvage_json_attaches_raw_to_the_error(self):
        with self.assertRaises(gemini_reviewer.ReviewerError) as ctx:
            gemini_reviewer._salvage_json("not json at all")
        self.assertIn("not json at all", ctx.exception.raw)

    def test_expand_is_opt_out_so_a_free_key_schema_is_not_renamed(self):
        # gemini_table.py's cells are keyed by the table's own concept names. A column called
        # 'c' or 'type' must survive; run_gemini(expand=False) is what protects it.
        table = {"rows": [{"parameter": "p", "cells": {"c": "v1", "t": "sy"}}], "notes": "n"}
        # What expansion WOULD do to it: the column 'c' becomes 'confidence', 't' becomes
        # 'type', and that cell's value 'sy' is coerced to the enum 'style'.
        self.assertEqual(reviewer_schema.expand_schema(table)["rows"][0]["cells"],
                         {"confidence": "v1", "type": "style"})
        self.assertEqual(table["rows"][0]["cells"], {"c": "v1", "t": "sy"})  # opt-out keeps it

    def test_error_object_truncates_raw(self):
        obj = reviewer_schema.error_object("boom", "x" * 900)
        self.assertEqual(obj["suggestions"], [])
        self.assertEqual(len(obj["_raw"]), 500)


class TestCopilotProviderChain(unittest.TestCase):
    """Endpoint failover and run-time model resolution. Cases 4-5 of the same plan, plus the
    'select the latest model, never a hardcoded one' requirement."""

    def setUp(self):
        copilot_providers.reset_cache()

    def tearDown(self):
        copilot_providers.reset_cache()

    def test_first_endpoint_404_falls_back_to_second(self):
        calls = []

        class _FakeClient:
            def __init__(self, base_url, api_key, default_headers=None):
                self.base_url = base_url
                self.chat = mock.Mock()
                self.chat.completions = mock.Mock()
                self.chat.completions.create = self._create

            def _create(self, **kwargs):
                calls.append((self.base_url, kwargs["model"]))
                if "models.github.ai" in self.base_url:
                    raise RuntimeError("Error code: 404 - not found")
                message = mock.Mock()
                message.content = json.dumps(COP_R1)
                choice = mock.Mock()
                choice.message = message
                return mock.Mock(choices=[choice])

        with mock.patch.dict(os.environ, {"GITHUB_TOKEN": "t", "COPILOT_TOKEN": ""}, clear=False), \
             mock.patch.object(github_reviewer, "_OPENAI_OK", True), \
             mock.patch.object(github_reviewer, "OpenAI", _FakeClient):
            result = github_reviewer.run_copilot("prompt", model="gpt-4o-mini")

        self.assertEqual(result, COP_R1)                      # identical result after failover
        self.assertEqual([c[0] for c in calls],
                         ["https://models.github.ai/inference",
                          "https://models.inference.ai.azure.com"])
        self.assertEqual(calls[0][1], "openai/gpt-4o-mini")   # publisher-qualified host
        self.assertEqual(calls[1][1], "gpt-4o-mini")          # bare-id host

    def test_every_endpoint_failing_raises_with_last_error_and_never_kills_the_panel(self):
        class _FakeClient:
            def __init__(self, base_url, api_key, default_headers=None):
                self.chat = mock.Mock()
                self.chat.completions = mock.Mock()
                self.chat.completions.create = mock.Mock(
                    side_effect=RuntimeError("Error code: 410 - retired"))

        with mock.patch.dict(os.environ, {"GITHUB_TOKEN": "t"}, clear=False), \
             mock.patch.object(github_reviewer, "_OPENAI_OK", True), \
             mock.patch.object(github_reviewer, "OpenAI", _FakeClient):
            with self.assertRaises(github_reviewer.ReviewerError) as ctx:
                github_reviewer.run_copilot("prompt", model="gpt-4o")
            self.assertIn("410", str(ctx.exception))

            # And through the panel: an empty critique, an unavailable marker, no exception.
            with mock.patch.object(deliberate, "gemini_available", lambda: False), \
                 mock.patch.object(deliberate, "copilot_available", lambda: True), \
                 mock.patch.object(deliberate, "run_copilot", github_reviewer.run_copilot):
                env = deliberate.deliberate(
                    draft="draft", topic="t", evidence="", rounds=1,
                    gemini_model="g", copilot_model="gpt-4o", temperature=0.3,
                    plan_schema="generic")

        self.assertEqual(env["merged"], [])
        self.assertIn("_error", env["round1"]["copilot"])
        self.assertEqual(env["round1"]["copilot"]["suggestions"], [])
        self.assertIn("[REVIEWER UNAVAILABLE: Copilot]", env["unavailable_markers"])

    def test_resolver_picks_the_newest_catalog_entry(self):
        # A fresher DATE on an older family must not win: that is the trap a date-first rank
        # falls into, and it is how a leg silently keeps running last year's model.
        catalog = [
            {"id": "openai/gpt-4o", "version": "2026-08-01", "task": "chat-completion"},
            {"id": "openai/gpt-5.2", "version": "2026-06-01", "task": "chat-completion"},
            {"id": "openai/gpt-5.3-preview", "version": "2026-06-01", "task": "chat-completion"},
            {"id": "openai/text-embedding-3-large", "version": "2026-07-01",
             "task": "embeddings"},
            {"id": "cohere/command-r-12", "version": "2026-08-01", "task": "chat-completion"},
        ]
        with mock.patch.dict(os.environ, {"GITHUB_TOKEN": "t", "COPILOT_TOKEN": ""}, clear=False), \
             mock.patch.object(copilot_providers, "fetch_catalog", lambda p, t, timeout=30: catalog):
            model, source = copilot_providers.resolve_latest_model("openai")

        # Newest generation wins, preview included; the preferred publisher keeps the
        # cross-publisher comparison (command-r-12) out of the ranking.
        self.assertEqual(model, "openai/gpt-5.3-preview")
        self.assertEqual(source, "github-models")   # first provider holding a token
        self.assertNotIn("embedding", model)        # non-chat entries excluded

    def test_stable_wins_only_at_equal_version(self):
        catalog = [
            {"id": "openai/gpt-5.2-preview", "version": "2026-06-01", "task": "chat-completion"},
            {"id": "openai/gpt-5.2", "version": "2026-06-01", "task": "chat-completion"},
        ]
        with mock.patch.dict(os.environ, {"GITHUB_TOKEN": "t", "COPILOT_TOKEN": ""}, clear=False), \
             mock.patch.object(copilot_providers, "fetch_catalog", lambda p, t, timeout=30: catalog):
            self.assertEqual(copilot_providers.resolve_latest_model("openai")[0], "openai/gpt-5.2")

    def test_newer_release_of_the_same_family_wins_on_date(self):
        catalog = [
            {"id": "openai/gpt-5.2", "version": "2026-06-01", "task": "chat-completion"},
            {"id": "openai/gpt-5.2-0815", "version": "2026-08-15", "task": "chat-completion"},
        ]
        with mock.patch.dict(os.environ, {"GITHUB_TOKEN": "t", "COPILOT_TOKEN": ""}, clear=False), \
             mock.patch.object(copilot_providers, "fetch_catalog", lambda p, t, timeout=30: catalog):
            self.assertEqual(copilot_providers.resolve_latest_model("openai")[0],
                             "openai/gpt-5.2-0815")

    def test_resolver_falls_back_when_no_catalog_answers(self):
        with mock.patch.dict(os.environ, {"GITHUB_TOKEN": "t"}, clear=False), \
             mock.patch.object(copilot_providers, "fetch_catalog", lambda p, t, timeout=30: []):
            model, source = copilot_providers.resolve_latest_model()

        self.assertEqual(model, copilot_providers.FALLBACK_MODEL)
        self.assertEqual(source, "")                # empty source flags a failed resolution

    def test_provider_without_token_is_skipped(self):
        seen = []

        def _fake_fetch(provider, token, timeout=30):
            seen.append(provider["name"])
            return [{"id": "openai/gpt-6", "version": "2026-08-10", "task": "chat-completion"}]

        env = {k: "" for k in ("COPILOT_TOKEN", "GITHUB_COPILOT_TOKEN", "GH_OAUTH_TOKEN",
                               "GITHUB_OAUTH_TOKEN")}
        env["GITHUB_TOKEN"] = "t"
        with mock.patch.dict(os.environ, env, clear=False), \
             mock.patch.object(copilot_providers, "fetch_catalog", _fake_fetch):
            model, source = copilot_providers.resolve_latest_model()

        self.assertEqual(seen, ["github-models"])   # the tokenless copilot provider is skipped
        self.assertEqual(model, "openai/gpt-6")
        self.assertEqual(source, "github-models")

    def test_panel_records_the_resolved_model_ids(self):
        with mock.patch.object(deliberate, "gemini_available", lambda: True), \
             mock.patch.object(deliberate, "copilot_available", lambda: False), \
             mock.patch.object(deliberate, "resolve_gemini_model", lambda: "gemini-9-pro"), \
             mock.patch.object(deliberate, "resolve_copilot_model",
                               lambda: ("openai/gpt-9", "copilot")), \
             mock.patch.object(deliberate, "run_gemini", mock.Mock(side_effect=[GEM_R1])):
            env = deliberate.deliberate(
                draft="draft", topic="t", evidence="", rounds=1,
                gemini_model="auto", copilot_model="auto", temperature=0.3,
                plan_schema="generic")

        self.assertEqual(env["models"]["gemini"], "gemini-9-pro")
        self.assertEqual(env["models"]["copilot"], "openai/gpt-9")
        self.assertEqual(env["models"]["copilot_provider"], "copilot")


if __name__ == "__main__":
    unittest.main(verbosity=2)
