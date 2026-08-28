"""
Offline tests for vram_optimizer.py.

The objective function decides which measured configuration is retained, so it is tested on
records alone, with no daemon, no GPU and no restart. The driver's two early exits are tested
with the probe and every side effect patched.
"""

import sys
import unittest
from pathlib import Path
from unittest import mock

_SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_SCRIPTS))

import vram_optimizer as vo  # noqa: E402


def _rec(num_ctx, kv, tps, ratio=1.0, free=617, clamped=False):
    return {"num_ctx": num_ctx, "kv_cache_type": kv, "residency_ratio": ratio,
            "min_free_mib": free, "clamped_by_model_maximum": clamped, "decode_tps": tps}


_CARD = {"name": "NVIDIA RTX A1000 6GB Laptop GPU", "memory_total_mib": 6144,
         "driver_version": "556.12"}
_EMPTY_CONFIG = {"template": None, "system": None, "renderer": None, "parser": None,
                 "stop": []}


class TestObjectiveKeepsTheLargestAdmissibleWindow(unittest.TestCase):
    def test_context_wins_when_throughput_is_flat(self):
        # The case measured 2026-08-27: decode throughput barely moves along the ladder, so
        # the largest window is effectively free and must be taken.
        result = vo.select_configuration([
            _rec(8192, "q8_0", 29.5), _rec(16384, "q8_0", 30.1), _rec(32768, "q8_0", 30.1),
        ])

        self.assertEqual(result["retained"]["num_ctx"], 32768)


class TestThroughputFloorRejectsASlowLargeWindow(unittest.TestCase):
    def test_a_window_below_the_floor_is_dropped_with_its_reason(self):
        # Doubling the window at half the speed must NOT win.
        result = vo.select_configuration([
            _rec(16384, "q8_0", 30.0), _rec(32768, "q4_0", 15.0),
        ], throughput_floor=0.90)

        self.assertEqual(result["retained"]["num_ctx"], 16384)
        dropped = {r["num_ctx"]: reason for r, reason in result["dropped"]}
        self.assertIn(32768, dropped)
        self.assertIn("decode", dropped[32768])

    def test_the_floor_is_relative_to_the_best_ADMISSIBLE_throughput(self):
        result = vo.select_configuration([
            _rec(8192, "f16", 40.0), _rec(32768, "q4_0", 37.0),
        ], throughput_floor=0.90)

        self.assertAlmostEqual(result["best_decode_tps"], 40.0, places=3)
        self.assertEqual(result["retained"]["num_ctx"], 32768)


class TestInadmissibleRecords(unittest.TestCase):
    def test_a_spilled_configuration_is_never_retained_however_fast(self):
        # Rule 1 outranks throughput: a spill is refused even when it measured faster,
        # because that speed stops being reproducible once anything else touches the card.
        # This case also pins the throughput reference: 99 tok/s belongs to the SPILLED
        # configuration, and if it were allowed to set the floor it would disqualify the
        # only usable window and the tool would retain nothing.
        result = vo.select_configuration([
            _rec(16384, "q8_0", 30.0), _rec(65536, "q4_0", 99.0, ratio=0.82),
        ])

        self.assertEqual(result["retained"]["num_ctx"], 16384)
        self.assertAlmostEqual(result["best_decode_tps"], 30.0, places=3)
        dropped = {r["num_ctx"]: reason for r, reason in result["dropped"]}
        self.assertIn("residency", dropped[65536])

    def test_a_configuration_under_the_free_vram_floor_is_dropped(self):
        # The incumbent coder tag measured 47 MiB free against a 300 MiB floor.
        result = vo.select_configuration([
            _rec(8192, "q8_0", 30.0, free=47), _rec(8192, "q4_0", 29.0, free=400),
        ])

        self.assertEqual(result["retained"]["kv_cache_type"], "q4_0")
        dropped = {r["kv_cache_type"]: reason for r, reason in result["dropped"]}
        self.assertIn("free VRAM", dropped["q8_0"])

    def test_a_clamped_rung_is_dropped(self):
        result = vo.select_configuration([
            _rec(32768, "q8_0", 30.0), _rec(65536, "q8_0", 30.0, clamped=True),
        ])

        self.assertEqual(result["retained"]["num_ctx"], 32768)

    def test_nothing_admissible_retains_nothing_and_says_why(self):
        # The expected outcome for a model whose weights nearly fill the card. A legitimate
        # answer, not an error to work around.
        result = vo.select_configuration([_rec(8192, "q8_0", 28.0, free=47)])

        self.assertIsNone(result["retained"])
        self.assertEqual(len(result["dropped"]), 1)

    def test_no_records_at_all_raises(self):
        self.assertRaises(vo.OptimizerError, vo.select_configuration, [])


class TestTieBreak(unittest.TestCase):
    def test_equal_windows_break_on_throughput(self):
        result = vo.select_configuration([
            _rec(32768, "q4_0", 28.0), _rec(32768, "q8_0", 31.0),
        ])

        self.assertEqual(result["retained"]["kv_cache_type"], "q8_0")


class TestDryRun(unittest.TestCase):
    def test_dry_run_prints_the_modelfile_and_touches_nothing(self):
        # --dry-run must reach neither Ollama nor the daemon: it is the safe way to see what
        # the tool WOULD do to a tag before letting it restart anything.
        facts = {
            "layers": [{"kind": "model", "size": 4683075040, "digest": "sha256:eee"}],
            "native_max_context": 32768, "card": _CARD,
            "daemon_kv_cache_type": "q8_0", "base_config": _EMPTY_CONFIG,
        }
        with mock.patch.object(vo, "probe_base", return_value=facts), \
             mock.patch.object(vo.vram_daemon, "set_kv_cache_type") as axis, \
             mock.patch.object(vo, "ollama_create") as create, \
             mock.patch.object(vo, "sweep_axis_value") as sweep:
            rc = vo.run(base_tag="vendor:7b", role="coder", throughput_floor=0.90,
                        kv_types=("q8_0",), keep_vision=False, dry_run=True)

        self.assertEqual(rc, 0)
        axis.assert_not_called()
        create.assert_not_called()
        sweep.assert_not_called()


class TestWeightsExceedingTheCardRefuseEarly(unittest.TestCase):
    def test_a_model_larger_than_the_card_is_refused_before_anything_is_built(self):
        facts = {
            "layers": [{"kind": "model", "size": 8_000_000_000, "digest": "sha256:fff"}],
            "native_max_context": 32768, "card": _CARD,
            "daemon_kv_cache_type": "q8_0", "base_config": _EMPTY_CONFIG,
        }
        with mock.patch.object(vo, "probe_base", return_value=facts), \
             mock.patch.object(vo, "ollama_create") as create:
            rc = vo.run(base_tag="vendor:70b", role="coder", throughput_floor=0.90,
                        kv_types=("q8_0",), keep_vision=False, dry_run=False)

        self.assertEqual(rc, 1)
        create.assert_not_called()


class TestCli(unittest.TestCase):
    def test_an_unknown_kv_cache_type_is_refused_by_name(self):
        rc = vo.main(["vendor:7b", "--role", "coder", "--kv", "q2_0"])
        self.assertEqual(rc, 1)

    def test_role_is_required(self):
        with self.assertRaises(SystemExit):
            vo.main(["vendor:7b"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
