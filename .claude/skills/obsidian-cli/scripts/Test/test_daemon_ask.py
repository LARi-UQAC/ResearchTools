"""Tests for daemon_ask.py, the vault daemon's read-only ask queue."""
import json
import sys
import tempfile
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


class ReadRequestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def _write(self, payload):
        path = self.tmp / "req.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def test_reads_a_well_formed_request(self):
        import daemon_ask
        path = self._write({
            "id": "abc123", "from": "rt-dashboard",
            "asked_at": "2026-09-26T12:00:00+00:00",
            "question": "is this repo stale",
            "context_snapshot": {"repo_green": "green"},
        })
        request = daemon_ask.read_request(path)
        self.assertEqual(request["question"], "is this repo stale")
        self.assertEqual(request["context_snapshot"]["repo_green"], "green")

    def test_refuses_a_request_not_from_rt_dashboard(self):
        import daemon_ask
        path = self._write({
            "id": "abc123", "from": "some-other-caller",
            "asked_at": "2026-09-26T12:00:00+00:00",
            "question": "anything",
        })
        with self.assertRaises(daemon_ask.AskRefused):
            daemon_ask.read_request(path)

    def test_refuses_a_request_with_no_question(self):
        import daemon_ask
        path = self._write({"id": "abc123", "from": "rt-dashboard",
                            "asked_at": "2026-09-26T12:00:00+00:00"})
        with self.assertRaises(daemon_ask.AskRefused):
            daemon_ask.read_request(path)

    def test_refuses_unparsable_json(self):
        import daemon_ask
        path = self.tmp / "bad.json"
        path.write_text("{not json", encoding="utf-8")
        with self.assertRaises(daemon_ask.AskRefused):
            daemon_ask.read_request(path)

    def test_defaults_to_auto_when_language_is_absent(self):
        import daemon_ask
        path = self._write({"id": "abc123", "from": "rt-dashboard",
                            "asked_at": "2026-09-26T12:00:00+00:00",
                            "question": "anything"})
        self.assertEqual(daemon_ask.read_request(path)["language"], "auto")

    def test_refuses_an_unsupported_language(self):
        import daemon_ask
        path = self._write({"id": "abc123", "from": "rt-dashboard",
                            "asked_at": "2026-09-26T12:00:00+00:00",
                            "question": "anything", "language": "de"})
        with self.assertRaises(daemon_ask.AskRefused):
            daemon_ask.read_request(path)


class SearchVaultCase(unittest.TestCase):
    def setUp(self):
        self.vault = Path(tempfile.mkdtemp())
        (self.vault / "30_Ressources" / "Python").mkdir(parents=True)
        (self.vault / "30_Ressources" / "Python" / "context-budget.md").write_text(
            "type: apprentissage\n\ncontext budget truncation was measured "
            "against Ollama num_ctx clamping silently.\n", encoding="utf-8")
        (self.vault / "30_Ressources" / "Python" / "unrelated.md").write_text(
            "type: apprentissage\n\nsomething about pip-audit and CVE scans.\n",
            encoding="utf-8")

    def test_scores_the_note_sharing_more_keywords_higher(self):
        import daemon_ask
        hits = daemon_ask.search_vault(
            self.vault, "why does context budget truncation clamp num_ctx",
            max_notes=5, excerpt_chars=200)
        self.assertGreaterEqual(len(hits), 1)
        self.assertEqual(hits[0]["rel"], "30_Ressources/Python/context-budget.md")

    def test_bounds_the_result_count(self):
        import daemon_ask
        for i in range(10):
            (self.vault / "30_Ressources" / "Python" / f"note{i}.md").write_text(
                "type: apprentissage\n\ncontext budget note number "
                f"{i}.\n", encoding="utf-8")
        hits = daemon_ask.search_vault(self.vault, "context budget",
                                       max_notes=3, excerpt_chars=200)
        self.assertLessEqual(len(hits), 3)

    def test_no_vault_folder_returns_empty(self):
        import daemon_ask
        empty = Path(tempfile.mkdtemp())
        hits = daemon_ask.search_vault(empty, "anything", max_notes=5,
                                       excerpt_chars=200)
        self.assertEqual(hits, [])

    def test_zero_overlap_scores_nothing(self):
        import daemon_ask
        hits = daemon_ask.search_vault(
            self.vault, "zzzznonexistentword qqqqanotherword",
            max_notes=5, excerpt_chars=200)
        self.assertEqual(hits, [])


if __name__ == "__main__":
    unittest.main()
