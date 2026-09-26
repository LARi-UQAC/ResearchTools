"""Tests for daemon_ask.py, the vault daemon's read-only ask queue."""
import json
import sys
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


class DaemonConfigCase(unittest.TestCase):
    def test_ask_keys_are_declared_in_daemon_config(self):
        config_path = SCRIPTS.parent / "daemon-config.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        daemon = config["daemon"]
        for key in ("ask_poll_interval_s", "ask_request_ttl_s",
                    "ask_max_vault_notes", "ask_note_excerpt_chars",
                    "ask_context_snapshot_max_chars"):
            self.assertIn(key, daemon, f"daemon-config.json is missing {key}")


if __name__ == "__main__":
    unittest.main()
