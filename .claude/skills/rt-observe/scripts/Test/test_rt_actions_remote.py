"""
test_rt_actions_remote - the action-audit journal's second sink (Phase 2).

Additive-only, tested apart from the existing rt_actions suite on purpose: this
is a distinct concern (an outbound network call) with its own owner
(rt_openobserve.py), and the regression control that matters most here is that a
Runner built with no remote_sink - which is every call site and every test that
predates 2026-09-24 - gets a payload with no "remote" key at all, i.e. is
byte-for-byte what it always was.
"""
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import rt_actions  # noqa: E402
import rt_openobserve  # noqa: E402

VALUES = {"timeout_s": 5, "action_log": "~/rt-state-actions.jsonl",
         "inbox_root": "~/rt-inbox", "message_chars": 100,
         "output_tail_chars": 100}


class RunnerFixture(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.home = Path(self._tmp.name)

    def _runner(self, remote_sink=None):
        return rt_actions.Runner(
            self.home, self.home, VALUES,
            catalog={"actions": []}, remote_sink=remote_sink)

    def _log_lines(self):
        path = self.home / "rt-state-actions.jsonl"
        if not path.exists():
            return []
        with io.open(path, encoding="utf-8") as handle:
            return [json.loads(line) for line in handle if line.strip()]


class DefaultBehaviourUnchangedTest(RunnerFixture):
    """Regression control: every call site before 2026-09-24 passes no
    remote_sink, and its payload must be exactly what it was."""

    def test_no_remote_sink_means_no_remote_key(self):
        runner = self._runner()
        payload = runner._record({"status": "ok", "id": "x"})
        self.assertNotIn("remote", payload)

    def test_the_jsonl_fallback_is_still_written(self):
        runner = self._runner()
        runner._record({"status": "ok", "id": "x"})
        lines = self._log_lines()
        self.assertEqual(1, len(lines))
        self.assertEqual(lines[0]["id"], "x")


class RemoteSinkWiredTest(RunnerFixture):
    def test_a_successful_sink_is_recorded_alongside_the_local_write(self):
        runner = self._runner(remote_sink=lambda payload: (True, "accepted"))
        payload = runner._record({"status": "ok", "id": "x"})
        self.assertEqual(payload["remote"], {"ok": True, "detail": "accepted"})
        self.assertEqual(1, len(self._log_lines()))

    def test_a_failing_sink_still_leaves_the_jsonl_fallback_intact(self):
        """The plan's own requirement (section 2.2): the JSONL survives a sink
        outage. A refusal path (R20)."""
        runner = self._runner(
            remote_sink=lambda payload: (False, "connection refused"))
        payload = runner._record({"status": "ok", "id": "x"})
        self.assertEqual(payload["remote"]["ok"], False)
        self.assertIn("connection refused", payload["remote"]["detail"])
        lines = self._log_lines()
        self.assertEqual(1, len(lines))
        self.assertEqual(lines[0]["id"], "x")

    def test_a_sink_that_raises_is_caught_never_crashes_the_action(self):
        def bad_sink(payload):
            raise RuntimeError("boom")
        runner = self._runner(remote_sink=bad_sink)
        payload = runner._record({"status": "ok", "id": "x"})
        self.assertFalse(payload["remote"]["ok"])
        self.assertIn("boom", payload["remote"]["detail"])


class BuildRemoteSinkTest(unittest.TestCase):
    def test_none_values_yields_no_sink(self):
        self.assertIsNone(rt_actions.build_remote_sink(None, Path("/home"), 5))

    def test_configured_values_yield_a_callable_that_calls_send_json(self):
        values = {"base_url": "http://127.0.0.1:5080", "org": "lar",
                 "user": "lar", "password": "pw",
                 "streams": {"audit": "rt_audit"}}
        seen = {}

        def fake_opener(request, timeout=None):
            seen["body"] = request.data
            seen["timeout"] = timeout

            class Resp:
                def __enter__(self): return self
                def __exit__(self, *e): return False
                def read(self): return b"{}"
            return Resp()

        sink = rt_actions.build_remote_sink(values, Path("/home"), 5,
                                            opener=fake_opener)
        ok, detail = sink({"id": "x", "status": "ok"})
        self.assertTrue(ok)
        self.assertEqual(seen["timeout"], 5)
        self.assertIn(b'"id": "x"', seen["body"])


if __name__ == "__main__":
    unittest.main()
