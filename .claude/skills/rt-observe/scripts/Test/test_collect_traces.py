"""
test_collect_traces - the trace panel over rt_openobserve, offline.

Proves the collector contract holds (unavailable-with-reason when OpenObserve is
not configured or does not answer) and that it never recomputes a token total -
that stays owned by collect_usage.py.
"""
import json
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import collect_traces  # noqa: E402
import rt_openobserve  # noqa: E402

NOW = datetime(2026, 9, 24, 12, 0, 0, tzinfo=timezone.utc)

CONFIG = {
    "openobserve": {"base_url": "http://127.0.0.1:5080", "org": "lar"},
    "timeouts_seconds": {"openobserve_search": {"value": 10}},
    "caps": {"traces_page_size": {"value": 100}, "traces_max_pages": {"value": 2}},
}
ENV = {rt_openobserve.USER_ENV_VAR: "lar", rt_openobserve.PASSWORD_ENV_VAR: "pw"}


class FakeResponse:
    def __init__(self, body):
        self._body = body.encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return self._body


def fake_opener(pages):
    """pages: list of hit-lists, one per expected request."""
    calls = {"n": 0}

    def opener(request, timeout=None):
        index = min(calls["n"], len(pages) - 1)
        calls["n"] += 1
        return FakeResponse(json.dumps({"hits": pages[index]}))
    return opener


class CollectTracesTest(unittest.TestCase):
    def test_unconfigured_is_unavailable_with_a_reason(self):
        state = collect_traces.collect(Path("/repo"), Path("/home"), {}, now=NOW)
        self.assertEqual(state["status"], "unavailable")
        self.assertTrue(state["reason"])

    def test_a_declared_but_incomplete_block_is_unavailable_not_a_crash(self):
        config = {"openobserve": {"base_url": "http://x"}}
        state = collect_traces.collect(Path("/repo"), Path("/home"), config,
                                       now=NOW, env={})
        self.assertEqual(state["status"], "unavailable")

    def test_configured_and_reachable_reports_counts_not_tokens(self):
        rows = [{"session_id": "s1", "_timestamp": "2026-09-24T10:00:00Z"},
                {"session_id": "s2", "_timestamp": "2026-09-24T11:00:00Z"}]
        state = collect_traces.collect(
            Path("/repo"), Path("/home"), CONFIG, now=NOW, env=ENV,
            opener=fake_opener([rows]))
        self.assertEqual(state["status"], "ok")
        self.assertEqual(state["rows"], 2)
        self.assertEqual(state["distinct_sessions"], 2)
        self.assertEqual(state["newest_event"], "2026-09-24T11:00:00Z")
        self.assertNotIn("tokens", state)

    def test_an_unreachable_openobserve_is_unavailable_with_reason(self):
        """A refusal path (R20): the server is configured but down."""
        import urllib.error

        def opener(request, timeout=None):
            raise urllib.error.URLError("connection refused")
        state = collect_traces.collect(Path("/repo"), Path("/home"), CONFIG,
                                       now=NOW, env=ENV, opener=opener)
        self.assertEqual(state["status"], "unavailable")
        self.assertIn("connection refused", state["reason"])


if __name__ == "__main__":
    unittest.main()
