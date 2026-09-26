"""Tests for daemon_ask.py, the vault daemon's read-only ask queue."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

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


class AnswerCase(unittest.TestCase):
    def setUp(self):
        self.vault = Path(tempfile.mkdtemp())
        (self.vault / "30_Ressources" / "Python").mkdir(parents=True)
        (self.vault / "30_Ressources" / "Python" / "note.md").write_text(
            "type: apprentissage\n\ncontext budget clamps num_ctx silently.\n",
            encoding="utf-8")
        self.config = {"daemon": {
            "ask_request_ttl_s": 90, "ask_max_vault_notes": 5,
            "ask_note_excerpt_chars": 1200,
            "ask_context_snapshot_max_chars": 4000}}

    def _request(self, asked_at="2026-09-26T12:00:00+00:00"):
        return {"id": "abc123", "from": "rt-dashboard", "asked_at": asked_at,
                "question": "why does context budget clamp num_ctx",
                "context_snapshot": {"repo_green": "green"}}

    def test_answers_ok_with_the_model_reply(self):
        import daemon_ask
        with mock.patch("daemon_ask.daemon_states.call_model",
                        return_value="It clamps to avoid an oversized prompt."):
            result = daemon_ask.answer(
                self._request(), self.vault, "a-tag", 16384, 5.0,
                self.config, today="2026-09-26T12:00:03+00:00")
        self.assertEqual(result["status"], "ok")
        self.assertIn("clamps", result["answer_text"])
        self.assertIn("30_Ressources/Python/note.md",
                      result["sources"]["vault_notes"])

    def test_expires_a_stale_request(self):
        import daemon_ask
        result = daemon_ask.answer(
            self._request(asked_at="2026-09-26T10:00:00+00:00"),
            self.vault, "a-tag", 16384, 5.0, self.config,
            today="2026-09-26T12:00:00+00:00")
        self.assertEqual(result["status"], "expired")

    def test_reports_bridge_error_as_status_error(self):
        import daemon_ask
        with mock.patch("daemon_ask.daemon_states.call_model",
                        side_effect=daemon_ask.daemon_states.ob.BridgeError(
                            "no qualified model")):
            result = daemon_ask.answer(
                self._request(), self.vault, "a-tag", 16384, 5.0,
                self.config, today="2026-09-26T12:00:03+00:00")
        self.assertEqual(result["status"], "error")
        self.assertIn("no qualified model", result["reason"])

    def test_truncates_an_oversized_context_snapshot(self):
        import daemon_ask
        big = {"repo_green": "x" * 10000}
        request = self._request()
        request["context_snapshot"] = big
        captured = {}

        def fake_call_model(prompt, *a, **kw):
            captured["prompt"] = prompt
            return "answer"

        with mock.patch("daemon_ask.daemon_states.call_model",
                        side_effect=fake_call_model):
            daemon_ask.answer(request, self.vault, "a-tag", 16384, 5.0,
                              self.config, today="2026-09-26T12:00:03+00:00")
        self.assertLess(len(captured["prompt"]), 10500)

    def test_language_selection_reaches_the_prompt(self):
        import daemon_ask
        request = self._request()
        request["language"] = "fr"
        captured = {}

        def fake_call_model(prompt, *a, **kw):
            captured["prompt"] = prompt
            return "reponse"

        with mock.patch("daemon_ask.daemon_states.call_model",
                        side_effect=fake_call_model):
            daemon_ask.answer(request, self.vault, "a-tag", 16384, 5.0,
                              self.config, today="2026-09-26T12:00:03+00:00")
        self.assertIn("Reponds en francais", captured["prompt"])


class RunAskOnceCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.vault = self.tmp / "Vault"
        (self.vault / "30_Ressources" / "Python").mkdir(parents=True)
        self.outbox = self.tmp / "outbox"
        (self.outbox / "ask" / "requests").mkdir(parents=True)
        (self.outbox / "ask" / "answers").mkdir(parents=True)
        self.config = {
            "lock": {"acquire_timeout_s": 1, "stale_after_s": 300,
                     "poll_interval_s": 0.01},
            "probe": {"request_timeout_s": 5},
            "daemon": {"poll_interval_s": 0.01, "classify_confidence_min": 0.7,
                      "draft_max_attempts": 2, "drain_idle_s": 900,
                      "consolidate_top_n": 15, "judge_edge_max_pairs": 15,
                      "queue_max_entries": 500, "phantom_max_per_drain": 10,
                      "ask_poll_interval_s": 1, "ask_request_ttl_s": 90,
                      "ask_max_vault_notes": 5, "ask_note_excerpt_chars": 1200,
                      "ask_context_snapshot_max_chars": 4000},
        }
        import vault_daemon
        self.daemon = vault_daemon.VaultDaemon(
            self.vault, self.outbox, self.config, today="2026-09-26T12:00:00+00:00")

    def _request(self, name="abc123", from_="rt-dashboard"):
        path = self.outbox / "ask" / "requests" / f"{name}.json"
        path.write_text(json.dumps({
            "id": name, "from": from_,
            "asked_at": "2026-09-26T12:00:00+00:00",
            "question": "is this repo stale", "context_snapshot": {}}),
            encoding="utf-8")
        return path

    def test_answers_a_valid_request_and_removes_it(self):
        self._request()
        with mock.patch("daemon_ask.daemon_states.call_model",
                        return_value="No, the suite is green."):
            self.daemon.run_ask_once("a-tag", 16384)
        self.assertFalse(
            (self.outbox / "ask" / "requests" / "abc123.json").exists())
        answer_path = self.outbox / "ask" / "answers" / "abc123.json"
        self.assertTrue(answer_path.exists())
        answer = json.loads(answer_path.read_text(encoding="utf-8"))
        self.assertEqual(answer["status"], "ok")

    def test_refused_request_still_gets_an_answer_file(self):
        self._request(from_="someone-else")
        self.daemon.run_ask_once("a-tag", 16384)
        answer = json.loads(
            (self.outbox / "ask" / "answers" / "abc123.json")
            .read_text(encoding="utf-8"))
        self.assertEqual(answer["status"], "refused")

    def test_a_malformed_request_does_not_block_a_good_one(self):
        (self.outbox / "ask" / "requests" / "bad.json").write_text(
            "{not json", encoding="utf-8")
        self._request(name="good1")
        with mock.patch("daemon_ask.daemon_states.call_model",
                        return_value="fine"):
            self.daemon.run_ask_once("a-tag", 16384)
        self.assertTrue(
            (self.outbox / "ask" / "answers" / "good1.json").exists())
        self.assertTrue(
            (self.outbox / "ask" / "answers" / "bad.json").exists())


if __name__ == "__main__":
    unittest.main()
