"""Config-key presence for the voice panel (observe-config.json)."""
import sys
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


class VoiceConfigCase(unittest.TestCase):
    def setUp(self):
        import rt_state
        self.config = rt_state.load_config(SCRIPTS.parent)

    def test_stt_keys_are_declared(self):
        import rt_state
        for key in ("engine", "model_size", "compute_type", "device",
                    "language", "vad_filter", "vad_min_silence_ms",
                    "condition_on_previous_text"):
            rt_state.config_value(self.config, "voice", "stt", key)

    def test_stt_runs_on_the_gpu(self):
        """Operator decision 2026-09-26: 'no CPU, all on GPU'."""
        import rt_state
        self.assertEqual(
            rt_state.config_value(self.config, "voice", "stt", "device"),
            "cuda")

    def test_stt_model_is_the_measured_winner(self):
        """Operator choice 2026-09-26 from the scored comparison (4 Whisper
        variants on the operator's 3 dictated recordings, beside the resident
        writer model): large-v3-turbo int8_float16 scored 98.8 - 2.5% word
        error, a 19.5 s buffer in 0.74 s (under the 1 s live refresh), 7% of
        the LLM demoted from VRAM against large-v3's 24%."""
        import rt_state
        self.assertEqual(
            rt_state.config_value(self.config, "voice", "stt", "model_size"),
            "large-v3-turbo")
        self.assertEqual(
            rt_state.config_value(self.config, "voice", "stt",
                                  "compute_type"), "int8_float16")

    def test_the_dashboard_never_outwaits_the_daemon_ttl(self):
        """A dashboard waiting longer than the daemon keeps a request would
        wait on an answer that can only ever say 'expired'."""
        import json
        import rt_state
        wait = rt_state.config_value(self.config, "timeouts_seconds",
                                     "voice_ask_wait")
        daemon_cfg = json.loads(
            (SCRIPTS.parents[1] / "obsidian-cli" / "daemon-config.json")
            .read_text(encoding="utf-8"))
        self.assertLess(wait, daemon_cfg["daemon"]["ask_request_ttl_s"])

    def test_ask_wait_and_question_cap_are_declared(self):
        import rt_state
        rt_state.config_value(self.config, "timeouts_seconds",
                              "voice_ask_wait")
        rt_state.config_value(self.config, "caps", "voice_question_chars")


if __name__ == "__main__":
    unittest.main()
