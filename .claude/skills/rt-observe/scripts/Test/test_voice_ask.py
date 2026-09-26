"""Tests for voice_ask.py: the context digest, and the request/answer files."""
import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

NOW = datetime(2026, 9, 26, 12, 0, 0, tzinfo=timezone.utc)


class ContextSnapshotCase(unittest.TestCase):
    def test_trims_to_the_locked_fields(self):
        import voice_ask
        state = {
            "generated": "2026-09-26T12:00:00+00:00",
            "mirrors": {"status": "ok", "totals": {"lost": 2, "stale": 0, "ok": 130}},
            "repo_state": {"status": "ok", "green": {"value": "green"},
                          "branch": {"value": "main"}},
            "progress": {"status": "ok", "phases": [{"label": "x", "state": "done"}]},
            "services": {"status": "ok", "vault_daemon": {"running": True}},
            "graph": {"status": "ok", "nodes": 5311, "links": 7312, "stale": False},
            "usage": {"status": "ok", "totals": {"input": 999}},
        }
        digest = voice_ask.build_context_snapshot(state)
        self.assertEqual(digest["mirrors_totals"]["lost"], 2)
        self.assertEqual(digest["repo_green"], "green")
        self.assertEqual(digest["repo_branch"], "main")
        self.assertTrue(digest["services_daemon_running"])
        self.assertEqual(digest["graph_summary"]["nodes"], 5311)
        self.assertNotIn("usage", digest)

    def test_an_unavailable_section_degrades_rather_than_raises(self):
        import voice_ask
        digest = voice_ask.build_context_snapshot({
            "mirrors": {"status": "unavailable", "reason": "x"}})
        self.assertIsNone(digest["mirrors_totals"])


class WriteRequestCase(unittest.TestCase):
    def setUp(self):
        self.outbox = Path(tempfile.mkdtemp())

    def test_writes_a_request_matching_plan1s_shape(self):
        import voice_ask
        request_id = voice_ask.write_ask_request(
            self.outbox, "is this repo stale", {"repo_green": "green"},
            language="fr", ident=lambda: "fixedid", clock=lambda: NOW)
        self.assertEqual(request_id, "fixedid")
        path = self.outbox / "ask" / "requests" / "fixedid.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(payload["from"], "rt-dashboard")
        self.assertEqual(payload["question"], "is this repo stale")
        self.assertEqual(payload["language"], "fr")
        self.assertEqual(payload["context_snapshot"]["repo_green"], "green")

    def test_language_defaults_to_auto(self):
        import voice_ask
        voice_ask.write_ask_request(self.outbox, "q", {},
                                    ident=lambda: "id2", clock=lambda: NOW)
        payload = json.loads((self.outbox / "ask" / "requests" / "id2.json")
                             .read_text(encoding="utf-8"))
        self.assertEqual(payload["language"], "auto")

    def test_two_requests_get_different_ids(self):
        import voice_ask
        first = voice_ask.write_ask_request(self.outbox, "a", {})
        second = voice_ask.write_ask_request(self.outbox, "b", {})
        self.assertNotEqual(first, second)


class PollAnswerCase(unittest.TestCase):
    def setUp(self):
        self.outbox = Path(tempfile.mkdtemp())
        (self.outbox / "ask" / "answers").mkdir(parents=True)

    def test_returns_the_answer_once_it_appears_and_removes_it(self):
        import voice_ask
        answer_path = self.outbox / "ask" / "answers" / "req1.json"
        ticks = {"n": 0}

        def fake_sleep(_seconds):
            ticks["n"] += 1
            if ticks["n"] == 2:
                answer_path.write_text(
                    json.dumps({"id": "req1", "status": "ok",
                               "answer_text": "fine"}), encoding="utf-8")

        result = voice_ask.poll_answer(self.outbox, "req1", timeout_s=5,
                                       poll_interval_s=0.01, sleep=fake_sleep)
        self.assertEqual(result["status"], "ok")
        self.assertFalse(answer_path.exists())

    def test_gives_up_after_the_timeout(self):
        import voice_ask
        result = voice_ask.poll_answer(
            self.outbox, "never-answered", timeout_s=0.05,
            poll_interval_s=0.01, sleep=lambda s: None)
        self.assertEqual(result["status"], "timeout")


if __name__ == "__main__":
    unittest.main()
