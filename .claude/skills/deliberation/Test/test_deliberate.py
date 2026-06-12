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
sys.path.insert(0, str(_SCRIPTS))

import deliberate  # noqa: E402

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


if __name__ == "__main__":
    unittest.main(verbosity=2)
