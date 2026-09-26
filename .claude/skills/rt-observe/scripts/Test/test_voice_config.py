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
                    "language"):
            rt_state.config_value(self.config, "voice", "stt", key)

    def test_ask_wait_and_question_cap_are_declared(self):
        import rt_state
        rt_state.config_value(self.config, "timeouts_seconds",
                              "voice_ask_wait")
        rt_state.config_value(self.config, "caps", "voice_question_chars")


if __name__ == "__main__":
    unittest.main()
