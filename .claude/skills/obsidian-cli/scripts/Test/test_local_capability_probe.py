"""
test_local_capability_probe - offline checks for the Stage 1 capability probe.

No daemon, no model, no network: the sole network boundary of the bridge
(_post_generate) is patched, and the resolver and the measured window are
injected. The cases that matter are the refusals, since a probe that reports a
capability the daemon does not have is worse than no probe at all.
"""
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SCRIPTS = Path(__file__).resolve().parents[1]
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

spec = importlib.util.spec_from_file_location(
    "probe_under_test", SCRIPTS / "local_capability_probe.py")
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)

WINDOW = 8192          # injected fixture, never the machine's measured value (R21)
TAG = "a-tag-from-the-resolver"
TIMEOUT_S = 5.0
REPEAT = 2


def reply(body, **extra):
    out = {"response": body}
    out.update(extra)
    return out


class StructuredOutputProbeTest(unittest.TestCase):
    def _run(self, response):
        with mock.patch.object(probe.ob, "_post_generate", return_value=response):
            return probe.probe_structured_output(TAG, WINDOW, TIMEOUT_S)

    def test_a_valid_constrained_object_is_honoured(self):
        result = self._run(reply('{"scope": "reusable", "confidence": 0.9}'))
        self.assertTrue(result["honoured"])
        self.assertEqual(result["parsed"]["scope"], "reusable")

    def test_prose_instead_of_json_is_not_honoured(self):
        result = self._run(reply("I think this learning is reusable."))
        self.assertFalse(result["honoured"])
        self.assertIn("not JSON", result["why"])

    def test_json_that_is_not_the_requested_object_is_not_honoured(self):
        result = self._run(reply('["reusable"]'))
        self.assertFalse(result["honoured"])
        self.assertIn("not the requested object", result["why"])

    def test_a_value_outside_the_enum_is_not_honoured(self):
        """The whole reason for constraining at the sampler. A value the schema
        forbids must be reported, never accepted because the reply parsed."""
        result = self._run(reply('{"scope": "maybe", "confidence": 0.4}'))
        self.assertFalse(result["honoured"])
        self.assertIn("enum violated", result["why"])

    def test_the_schema_travels_in_the_request(self):
        with mock.patch.object(probe.ob, "_post_generate",
                               return_value=reply('{"scope": "project", "confidence": 1}')) as post:
            probe.probe_structured_output(TAG, WINDOW, TIMEOUT_S)
        payload = post.call_args[0][0]
        self.assertEqual(payload["format"], probe.CLASSIFY_SCHEMA)
        self.assertEqual(payload["options"]["num_ctx"], WINDOW)


class PrefixCacheProbeTest(unittest.TestCase):
    """Three calls: the same prefix twice, then a control on a prefix never seen.
    Measured 2026-08-28 on Ollama 0.33.0: prompt_eval_count is billed in full even
    on a cache hit (2186 on both calls), so only prefill DURATION carries the
    signal, and only the control call separates that signal from machine load."""

    RATIO_MAX = 0.5

    def _run(self, shared_ns, control_ns, warm_ns=2600):
        responses = [
            reply("a", prompt_eval_count=2186, prompt_eval_duration=warm_ns),
            reply("b", prompt_eval_count=2186, prompt_eval_duration=shared_ns),
            reply("c", prompt_eval_count=2186, prompt_eval_duration=control_ns),
        ]
        with mock.patch.object(probe.ob, "_post_generate", side_effect=responses):
            return probe.probe_prefix_cache(TAG, WINDOW, TIMEOUT_S, REPEAT,
                                            self.RATIO_MAX)

    def test_a_collapsed_prefill_against_the_control_means_reuse(self):
        result = self._run(shared_ns=634, control_ns=2612)
        self.assertTrue(result["reused"])
        self.assertAlmostEqual(result["ratio"], 634 / 2612, places=3)

    def test_an_identical_prefill_is_not_reuse(self):
        self.assertFalse(self._run(shared_ns=2600, control_ns=2612)["reused"])

    def test_a_control_as_fast_as_the_shared_call_is_not_reuse(self):
        """The case duration alone would misread: the whole machine got faster,
        so the control collapsed too and nothing was actually cached."""
        self.assertFalse(self._run(shared_ns=600, control_ns=620)["reused"])

    def test_a_missing_duration_is_not_read_as_reuse(self):
        result = self._run(shared_ns=600, control_ns=None)
        self.assertFalse(result["reused"])
        self.assertIsNone(result["ratio"])
        self.assertIn("no usable prefill duration", result["why"])

    def test_the_control_call_uses_a_different_prefix(self):
        responses = [reply(str(i), prompt_eval_count=2186, prompt_eval_duration=d)
                     for i, d in enumerate((2600, 600, 2610))]
        with mock.patch.object(probe.ob, "_post_generate",
                               side_effect=responses) as post:
            probe.probe_prefix_cache(TAG, WINDOW, TIMEOUT_S, REPEAT, self.RATIO_MAX)
        prompts = [call[0][0]["prompt"] for call in post.call_args_list]
        shared = probe.PREFIX_PARAGRAPH * REPEAT
        self.assertTrue(prompts[0].startswith(shared))
        self.assertTrue(prompts[1].startswith(shared))
        self.assertFalse(prompts[2].startswith(shared))
        self.assertTrue(prompts[2].startswith(probe.CONTROL_PARAGRAPH * REPEAT))


class ReportTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.report = self.tmp / "local-capability-probe.json"
        self.config = {"probe": {"prefix_paragraph_repeat": REPEAT,
                                 "request_timeout_s": TIMEOUT_S,
                                 "prefix_cache_duration_ratio_max": 0.5}}

    def _patched(self):
        return [
            mock.patch.object(probe.outbox_io, "load_config", return_value=self.config),
            mock.patch.object(probe.ob, "resolve_model", return_value=TAG),
            mock.patch.object(probe.context_budget, "read_retained_num_ctx",
                              return_value=WINDOW),
            mock.patch.object(probe.ob, "_post_generate", side_effect=[
                reply('{"scope": "reusable", "confidence": 0.8}'),
                reply("a", prompt_eval_count=2186, prompt_eval_duration=2600),
                reply("b", prompt_eval_count=2186, prompt_eval_duration=600),
                reply("c", prompt_eval_count=2186, prompt_eval_duration=2610),
            ]),
        ]

    def test_the_report_carries_both_verdicts_and_the_window(self):
        with mock.patch.object(probe.outbox_io, "load_config", return_value=self.config):
            for patcher in self._patched()[1:]:
                patcher.start()
                self.addCleanup(patcher.stop)
            self.assertEqual(probe.main(["--report", str(self.report)]), 0)
        written = json.loads(self.report.read_text(encoding="utf-8"))
        self.assertTrue(written["structured_output"]["honoured"])
        self.assertTrue(written["prefix_cache"]["reused"])
        self.assertEqual(written["num_ctx"], WINDOW)
        self.assertEqual(written["role"], "writer")
        self.assertTrue(written["measured_at"])
        self.assertNotIn(TAG, self.report.read_text(encoding="utf-8"),
                         "the report states a role, never a model tag")

    def test_dry_run_writes_nothing(self):
        with mock.patch.object(probe.outbox_io, "load_config", return_value=self.config):
            for patcher in self._patched()[1:]:
                patcher.start()
                self.addCleanup(patcher.stop)
            self.assertEqual(
                probe.main(["--dry-run", "--report", str(self.report)]), 0)
        self.assertFalse(self.report.exists())

    def test_a_resolver_naming_no_model_stops_instead_of_measuring(self):
        """R8. There is no fallback tag, and a weaker model's answer to a
        capability question looks exactly like a correct one."""
        with mock.patch.object(probe.outbox_io, "load_config", return_value=self.config):
            with mock.patch.object(probe.ob, "resolve_model",
                                   side_effect=probe.ob.BridgeError("no tag")):
                self.assertEqual(probe.main(["--report", str(self.report)]), 1)
        self.assertFalse(self.report.exists())

    def test_a_missing_measured_window_stops_instead_of_assuming_one(self):
        with mock.patch.object(probe.outbox_io, "load_config", return_value=self.config):
            with mock.patch.object(probe.ob, "resolve_model", return_value=TAG):
                with mock.patch.object(
                        probe.context_budget, "read_retained_num_ctx",
                        side_effect=probe.context_budget.ConfigError("no window")):
                    self.assertEqual(probe.main(["--report", str(self.report)]), 1)
        self.assertFalse(self.report.exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
