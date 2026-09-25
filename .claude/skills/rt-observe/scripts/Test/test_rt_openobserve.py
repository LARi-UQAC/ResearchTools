"""
test_rt_openobserve - the optional trace/audit journal client.

Offline: `urllib.request.urlopen` is never called for real. Every HTTP-shaped
case injects a fake `opener(request, timeout=...)` returning a context manager
whose `.read()` gives the body, or raising the same urllib exceptions the real
one would.

The confidentiality requirement (Phase 2) gets its own test: redaction happens
BEFORE the payload is serialized, so an account-name-shaped string sent through
send_json must never appear in the bytes handed to the opener.
"""
import io
import json
import sys
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import rt_openobserve  # noqa: E402

HOME = Path("/home/m3otis")


class FakeResponse:
    def __init__(self, body):
        self._body = body.encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return self._body


def fake_opener(body="{}", raise_error=None):
    def opener(request, timeout=None):
        if raise_error is not None:
            raise raise_error
        opener.last_request = request
        opener.last_body = request.data
        opener.last_timeout = timeout
        return FakeResponse(body)
    opener.last_request = None
    return opener


CONFIG = {"openobserve": {"base_url": "http://127.0.0.1:5080", "org": "lar"}}
ENV = {rt_openobserve.USER_ENV_VAR: "lar", rt_openobserve.PASSWORD_ENV_VAR: "pw"}


class LoadConfigTest(unittest.TestCase):
    def test_no_block_is_the_default_zero_service_state(self):
        values, reason = rt_openobserve.load_oo_config({})
        self.assertIsNone(values)
        self.assertIn("optional", reason)

    def test_a_declared_block_missing_a_key_is_an_explicit_error(self):
        with self.assertRaises(rt_openobserve.OpenObserveError) as ctx:
            rt_openobserve.load_oo_config({"openobserve": {"base_url": "http://x"}})
        self.assertIn("'org'", str(ctx.exception))

    def test_a_declared_block_with_no_credentials_is_an_explicit_error(self):
        with self.assertRaises(rt_openobserve.OpenObserveError) as ctx:
            rt_openobserve.load_oo_config(CONFIG, env={})
        self.assertIn(rt_openobserve.USER_ENV_VAR, str(ctx.exception))

    def test_a_complete_block_yields_values_with_default_streams(self):
        values, reason = rt_openobserve.load_oo_config(CONFIG, env=ENV)
        self.assertIsNone(reason)
        self.assertEqual(values["streams"]["audit"], "rt_audit")


class SendJsonTest(unittest.TestCase):
    def setUp(self):
        self.values, _ = rt_openobserve.load_oo_config(CONFIG, env=ENV)

    def test_redaction_happens_before_the_body_is_built(self):
        """Phase 2's confidentiality requirement, load-bearing: the account
        name must never reach the bytes handed to the opener."""
        opener = fake_opener()
        ok, reason = rt_openobserve.send_json(
            self.values, "audit",
            [{"reason": str(HOME / "obsidian-outbox" / "note.md")}],
            HOME, 5, opener=opener)
        self.assertTrue(ok)
        sent = opener.last_body.decode("utf-8")
        self.assertNotIn("m3otis", sent)
        self.assertIn("~", sent)

    def test_an_unconfigured_stream_key_is_a_named_refusal(self):
        ok, reason = rt_openobserve.send_json(
            self.values, "not_a_real_stream", [{"x": 1}], HOME, 5,
            opener=fake_opener())
        self.assertFalse(ok)
        self.assertIn("not_a_real_stream", reason)

    def test_an_http_error_is_reported_never_raised(self):
        error = urllib.error.HTTPError(
            "url", 500, "boom", {}, io.BytesIO(b"server exploded"))
        ok, reason = rt_openobserve.send_json(
            self.values, "audit", [{"x": 1}], HOME, 5,
            opener=fake_opener(raise_error=error))
        self.assertFalse(ok)
        self.assertIn("500", reason)

    def test_a_network_error_is_reported_never_raised(self):
        ok, reason = rt_openobserve.send_json(
            self.values, "audit", [{"x": 1}], HOME, 5,
            opener=fake_opener(raise_error=urllib.error.URLError("timed out")))
        self.assertFalse(ok)
        self.assertIn("timed out", reason)

    def test_the_timeout_is_forwarded_explicitly(self):
        opener = fake_opener()
        rt_openobserve.send_json(self.values, "audit", [{"x": 1}], HOME, 7,
                                 opener=opener)
        self.assertEqual(opener.last_timeout, 7)


class SearchTest(unittest.TestCase):
    def setUp(self):
        self.values, _ = rt_openobserve.load_oo_config(CONFIG, env=ENV)

    def test_one_short_page_stops_without_reading_further(self):
        opener = fake_opener(body=json.dumps({"hits": [{"a": 1}]}))
        ok, rows, reason, truncated = rt_openobserve.search(
            self.values, "traces", "SELECT * ", 5, page_size=100, max_pages=5,
            opener=opener)
        self.assertTrue(ok)
        self.assertEqual(len(rows), 1)
        self.assertFalse(truncated)

    def test_pagination_is_bounded_and_reports_truncation(self):
        """R10: an unbounded read is how a collector hangs on a large stream."""
        full_page = json.dumps({"hits": [{"a": i} for i in range(2)]})
        opener = fake_opener(body=full_page)
        ok, rows, reason, truncated = rt_openobserve.search(
            self.values, "traces", "SELECT * ", 5, page_size=2, max_pages=3,
            opener=opener)
        self.assertTrue(ok)
        self.assertEqual(len(rows), 6)
        self.assertTrue(truncated)

    def test_a_non_json_body_is_a_named_refusal_not_a_crash(self):
        opener = fake_opener(body="not json")
        ok, rows, reason, truncated = rt_openobserve.search(
            self.values, "traces", "SELECT *", 5, page_size=10, max_pages=1,
            opener=opener)
        self.assertFalse(ok)
        self.assertIn("does not parse", reason)


class VerifyIngestWindowTest(unittest.TestCase):
    def test_the_operator_note_names_the_default_and_the_env_var(self):
        note = rt_openobserve.remind_ingest_window()
        self.assertIn("5", note)
        self.assertIn(rt_openobserve.INGEST_WINDOW_ENV_VAR, note)

    def test_verify_reports_absence_on_read_back_as_the_ingest_window_pitfall(self):
        values, _ = rt_openobserve.load_oo_config(CONFIG, env=ENV)
        # send succeeds (200), but the search that reads it back finds nothing -
        # exactly what the plan's pitfall 1 describes.
        send_ok_search_empty = fake_opener(body=json.dumps({"hits": []}))
        verified, detail = rt_openobserve.verify_ingest_window(
            values, "audit", {"_rt_marker": "abc123"}, HOME, 5, 10, 10, 1,
            opener=send_ok_search_empty)
        self.assertFalse(verified)
        self.assertIn(rt_openobserve.INGEST_WINDOW_ENV_VAR, detail)

    def test_verify_confirms_when_the_marker_reads_back(self):
        values, _ = rt_openobserve.load_oo_config(CONFIG, env=ENV)
        opener = fake_opener(body=json.dumps({"hits": [{"_rt_marker": "abc123"}]}))
        verified, detail = rt_openobserve.verify_ingest_window(
            values, "audit", {"_rt_marker": "abc123"}, HOME, 5, 10, 10, 1,
            opener=opener)
        self.assertTrue(verified)

    def test_a_marker_with_no_field_is_a_named_refusal(self):
        values, _ = rt_openobserve.load_oo_config(CONFIG, env=ENV)
        verified, detail = rt_openobserve.verify_ingest_window(
            values, "audit", {}, HOME, 5, 10, 10, 1, opener=fake_opener())
        self.assertFalse(verified)
        self.assertIn("_rt_marker", detail)


if __name__ == "__main__":
    unittest.main()
