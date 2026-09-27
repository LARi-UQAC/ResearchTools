"""The engine registry and the shipped stt-bench-config.json.

Two cannot-disagree checks carry the weight: the benchmark must transcribe with the same
options the voice panel uses (VAD, no conditioning), and judge speed against the same live
refresh the panel runs at. Both live in rt-observe's observe-config.json; a second copy
here that drifted would measure a configuration nobody runs.
"""
import importlib.util
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

SCRIPTS = Path(__file__).resolve().parents[1]
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import bench_config  # noqa: E402
import engines  # noqa: E402

PANEL = json.loads((SCRIPTS.parents[1] / "rt-observe" / "observe-config.json")
                   .read_text(encoding="utf-8"))


def _numeric_entries(node, path=()):
    if isinstance(node, dict):
        if "value" in node and isinstance(node["value"], (int, float)) \
                and not isinstance(node["value"], bool):
            yield path, node
        for k, v in node.items():
            if k != "value":
                yield from _numeric_entries(v, path + (k,))


class ShippedConfigCase(unittest.TestCase):
    def setUp(self):
        self.config = bench_config.load_config()

    def test_every_numeric_value_carries_provenance(self):
        for path, entry in _numeric_entries(self.config):
            self.assertTrue(entry.get("provenance"), f"{'.'.join(path)} has no provenance (R4)")

    def test_default_candidates_are_name_colon_compute(self):
        for spec in bench_config.value(self.config, "default_candidates"):
            name, _, compute = spec.partition(":")
            self.assertTrue(name and compute, spec)

    def test_live_budget_is_the_panel_refresh(self):
        self.assertEqual(bench_config.value(self.config, "live_budget_ms"),
                         PANEL["voice"]["partial_refresh_ms"]["value"])

    def test_transcription_options_are_the_panel_options(self):
        for key in ("vad_filter", "vad_min_silence_ms", "condition_on_previous_text"):
            self.assertEqual(bench_config.value(self.config, "transcribe", key),
                             PANEL["voice"]["stt"][key]["value"], key)

    def test_a_missing_key_is_named(self):
        with self.assertRaises(KeyError) as ctx:
            bench_config.value(self.config, "gate", "no_such_key")
        self.assertIn("gate.no_such_key", str(ctx.exception))


class RegistryCase(unittest.TestCase):
    def setUp(self):
        self.config = bench_config.load_config()

    def test_every_declared_engine_has_a_complete_adapter(self):
        for name in self.config["engines"]:
            adapter = engines.adapter_module(name, self.config)
            for fn in ("available", "download", "load", "transcribe"):
                self.assertTrue(callable(getattr(adapter, fn, None)), f"{name}.{fn}")

    def test_an_unknown_engine_names_the_known_ones(self):
        with self.assertRaises(engines.EngineUnavailable) as ctx:
            engines.get_engine("whisperx", self.config)
        self.assertIn("faster-whisper", str(ctx.exception))

    def test_nemo_is_declared_but_never_claims_to_run(self):
        with self.assertRaises(engines.EngineUnavailable) as ctx:
            engines.get_engine("nemo", self.config)
        self.assertIn("not implemented", str(ctx.exception))

    def test_faster_whisper_absent_names_its_install_command(self):
        real = importlib.util.find_spec

        def no_whisper(name, *a, **k):
            return None if name == "faster_whisper" else real(name, *a, **k)
        with mock.patch("importlib.util.find_spec", side_effect=no_whisper):
            with self.assertRaises(engines.EngineUnavailable) as ctx:
                engines.get_engine("faster-whisper", self.config)
        self.assertIn("requirements-voice", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
