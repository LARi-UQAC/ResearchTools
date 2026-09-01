"""
Offline tests for optimize_ollama.py - Task 4 of the local-bridge pipeline, the
measure-first GPU budget tuner.

The whole point of the sweep is that no number in local-model-config.json is
inferred, so the one failure that matters here is a rung ACCEPTED on numbers that
describe a window the daemon never actually granted. That is what happened on
2026-08-27 with qwen2.5-coder:7b-gpu: Ollama silently clamps options.num_ctx to a
model's own native maximum instead of erroring, so rung 65536 cost exactly the
memory of rung 32768, passed every threshold, and was retained. The retained
window then feeds ollama_bridge.check_budget, which would have admitted a ~64k
prompt into the num_ctx // 2 + 2 truncation this repository keeps a measured
signature for (see ollama_bridge's R56 note).

No network, no GPU, no Ollama daemon: timed_generate_with_sample is patched, so
these tests exercise the acceptance predicate itself.
"""

import sys
import unittest
from pathlib import Path
from unittest import mock

_SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_SCRIPTS))

import optimize_ollama as oo  # noqa: E402


def _run(context_reported: int, free_mib: int = 617, gpu_percent: int = 100,
         elapsed_s: float = 5.0) -> dict:
    """One fake timed run, shaped like timed_generate_with_sample's return value."""
    return {
        "elapsed_s": elapsed_s,
        "response": {},
        "sample": {
            "size_str": "5.5 GB",
            "processor_field": f"{gpu_percent}% GPU",
            "gpu_percent": gpu_percent,
            "context": context_reported,
            "used_mib": 6144 - free_mib,
            "free_mib": free_mib,
        },
    }


class TestClampedRungIsRejected(unittest.TestCase):
    def test_rung_above_the_model_native_maximum_is_rejected(self):
        # Reproduces the measured qwen2.5-coder:7b-gpu case: 65536 requested,
        # 'ollama ps' reports CONTEXT 32768 on every run, memory and residency
        # otherwise perfect. Must NOT be accepted.
        with mock.patch.object(oo, "timed_generate_with_sample",
                               side_effect=lambda *a, **k: _run(context_reported=32768)):
            record = oo.evaluate_rung("qwen2.5-coder:7b-gpu", 65536, "p", 8, None)

        self.assertTrue(record["clamped_by_model_maximum"])
        self.assertEqual(record["observed_contexts"], [32768])
        self.assertFalse(record["accepted"])
        # The thresholds it would otherwise have passed on, so the test proves the
        # clamp is what rejected it and not some incidental threshold failure.
        self.assertEqual(record["min_gpu_percent"], 100)
        self.assertGreaterEqual(record["min_free_mib"], oo.MIN_FREE_MIB)
        self.assertFalse(record["regressed_past_baseline"])


class TestHonestRungIsStillAccepted(unittest.TestCase):
    def test_rung_the_daemon_actually_granted_is_accepted(self):
        with mock.patch.object(oo, "timed_generate_with_sample",
                               side_effect=lambda *a, **k: _run(context_reported=32768)):
            record = oo.evaluate_rung("qwen2.5-coder:7b-gpu", 32768, "p", 8, None)

        self.assertFalse(record["clamped_by_model_maximum"])
        self.assertEqual(record["observed_contexts"], [32768])
        self.assertTrue(record["accepted"])


class TestPartialClampIsRejected(unittest.TestCase):
    def test_one_run_out_of_three_reporting_a_different_window_rejects_the_rung(self):
        # A rung is honest only if EVERY run got the window that was asked for;
        # the same "worst observed value decides" rule the residency thresholds use.
        contexts = iter([16384, 8192, 16384])
        with mock.patch.object(oo, "timed_generate_with_sample",
                               side_effect=lambda *a, **k: _run(context_reported=next(contexts))):
            record = oo.evaluate_rung("some:tag", 16384, "p", 8, None)

        self.assertTrue(record["clamped_by_model_maximum"])
        self.assertEqual(record["observed_contexts"], [8192, 16384])
        self.assertFalse(record["accepted"])


class TestFreeVramFloorStillRejects(unittest.TestCase):
    def test_a_rung_under_the_free_vram_floor_is_still_rejected(self):
        # Non-regression: the clamp check is additional, it does not replace the
        # 300 MiB floor that rejected every rung of a 9B model whose vision projector left it 9 MiB free.
        with mock.patch.object(oo, "timed_generate_with_sample",
                               side_effect=lambda *a, **k: _run(context_reported=16384, free_mib=85)):
            record = oo.evaluate_rung("vendor:7b", 16384, "p", 8, None)

        self.assertFalse(record["clamped_by_model_maximum"])
        self.assertFalse(record["accepted"])


class TestApiPsRow(unittest.TestCase):
    def test_residency_ratio_comes_from_size_vram_over_size(self):
        # /api/ps reports size and size_vram as numbers, so residency is arithmetic
        # rather than a string parsed out of the PROCESSOR column of `ollama ps`.
        body = {"models": [{
            "name": "some:tag", "model": "some:tag",
            "size": 5526813409, "size_vram": 5526813409, "context_length": 16384,
        }]}
        with mock.patch.object(oo, "_api_ps_body", return_value=body):
            row = oo.api_ps_row("some:tag")

        self.assertEqual(row["context_length"], 16384)
        self.assertAlmostEqual(row["residency_ratio"], 1.0, places=6)

    def test_partial_offload_is_a_ratio_below_the_floor(self):
        body = {"models": [{
            "name": "some:tag", "model": "some:tag",
            "size": 5_000_000_000, "size_vram": 4_000_000_000, "context_length": 16384,
        }]}
        with mock.patch.object(oo, "_api_ps_body", return_value=body):
            row = oo.api_ps_row("some:tag")

        self.assertAlmostEqual(row["residency_ratio"], 0.8, places=6)
        self.assertLess(row["residency_ratio"], oo.GPU_RESIDENCY_MIN_RATIO)

    def test_absent_tag_is_none_not_an_exception(self):
        with mock.patch.object(oo, "_api_ps_body", return_value={"models": []}):
            self.assertIsNone(oo.api_ps_row("some:tag"))


class TestRungRecordCarriesResidencyRatioAndDecodeTps(unittest.TestCase):
    def test_record_reports_worst_residency_and_median_decode_tps(self):
        # The rung must carry the two numbers the driver ranks on. Residency
        # takes the WORST run, like every other threshold in this module;
        # decode throughput takes the median, like elapsed time.
        tps = iter([28.0, 30.0, 32.0])
        ratios = iter([1.0, 0.999, 1.0])

        def one_run(*_args, **_kwargs):
            return {
                "elapsed_s": 5.0,
                "response": {"eval_count": 160, "eval_duration": int(160 / next(tps) * 1e9)},
                "sample": {
                    "size_str": "5.5 GB", "processor_field": "100% GPU", "gpu_percent": 100,
                    "context": 16384, "used_mib": 5000, "free_mib": 1144,
                    "residency_ratio": next(ratios),
                },
            }

        with mock.patch.object(oo, "timed_generate_with_sample", side_effect=one_run):
            record = oo.evaluate_rung("some:tag", 16384, "p", 160, None)

        self.assertAlmostEqual(record["residency_ratio"], 0.999, places=6)
        self.assertAlmostEqual(record["decode_tps"], 30.0, places=1)
        self.assertTrue(record["accepted"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
