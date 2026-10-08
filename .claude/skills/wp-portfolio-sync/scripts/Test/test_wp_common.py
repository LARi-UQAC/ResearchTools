"""
test_wp_common.py - offline tests for wp_common.py.

Proves: the 6-year split with no defaults (D10), the formatters, the
Markdown-to-HTML converter, site_base's single-source/disagreement/scheme
refusals (D9), the bounded HTTP client's retry/no-retry rules, and that the
module never imports requests at module scope (lazy import only).
"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import _fixtures  # noqa: F401
from _fixtures import SCRIPTS, FakeResponse, FakeSession

import wp_errors
import wp_common


class ConnectionError_(Exception):
    """Stand-in exception used as the injected retryable type in these tests."""


class TestSplitRecentHistory(unittest.TestCase):
    def test_split_requires_year_and_window(self):
        with self.assertRaises(TypeError):
            wp_common.split_recent_history([{"fin": "2020"}], "fin")

    def test_split_boundaries(self):
        items = [{"fin": "2021"}, {"fin": "2020"}, {"fin": ""}]
        recent, history = wp_common.split_recent_history(items, "fin", 2026, 6)
        self.assertEqual(recent, [items[0], items[2]])
        self.assertEqual(history, [items[1]])


class TestFormatters(unittest.TestCase):
    def test_formatters(self):
        self.assertEqual(wp_common.fmt_ym("2025/5"), "05/2025")
        self.assertEqual(wp_common.fmt_ym("2017-08-07"), "08/2017")
        self.assertEqual(wp_common.fmt_amount("185000"), "185 000 $")
        self.assertEqual(wp_common.fmt_amount("abc"), "abc")

    def test_md_to_html_table_and_list(self):
        html_out = wp_common.md_to_html("| **Projet** | 2020 |\n- item un\n**gras**")
        self.assertIn("<tr><td>", html_out)
        self.assertIn("<li>", html_out)
        self.assertIn("<strong>gras</strong>", html_out)


class TestSiteBase(unittest.TestCase):
    def test_site_base_single_source(self):
        mapping = {"site": "https://portfolio.example.org/researcher/"}
        self.assertEqual(
            wp_common.site_base(mapping, {}), "https://portfolio.example.org/researcher"
        )

    def test_site_base_disagreement_refused(self):
        mapping = {"site": "https://portfolio.example.org/researcher"}
        environ = {"WP_BASE": "https://other.example.org"}
        with self.assertRaises(wp_errors.WpRefusal) as ctx:
            wp_common.site_base(mapping, environ)
        message = str(ctx.exception)
        self.assertIn("portfolio.example.org/researcher", message)
        self.assertIn("other.example.org", message)

    def test_site_base_http_refused(self):
        with self.assertRaises(wp_errors.WpRefusal):
            wp_common.site_base({"site": "http://portfolio.example.org"}, {})

    def test_site_base_none_refused(self):
        with self.assertRaises(wp_errors.WpRefusal):
            wp_common.site_base(None, {})


class TestWpClient(unittest.TestCase):
    def test_get_retries_then_succeeds(self):
        session = FakeSession(
            [ConnectionError_(), ConnectionError_(), FakeResponse(200, json_data={"ok": True})]
        )
        client = wp_common.WpClient(session, "https://site", 5, 2, retryable=(ConnectionError_,))
        result = client.get_json("/route", {"a": 1})
        self.assertEqual(result, {"ok": True})
        self.assertEqual(len(session.calls), 3)

    def test_get_exhausts_retries(self):
        session = FakeSession([ConnectionError_(), ConnectionError_(), ConnectionError_()])
        client = wp_common.WpClient(session, "https://site", 5, 2, retryable=(ConnectionError_,))
        with self.assertRaises(wp_errors.WpSyncError):
            client.get_json("/route", {})
        self.assertEqual(len(session.calls), 3)

    def test_get_401_not_retried(self):
        session = FakeSession([FakeResponse(401)])
        client = wp_common.WpClient(session, "https://site", 5, 2, retryable=(ConnectionError_,))
        with self.assertRaises(wp_errors.WpSyncError) as ctx:
            client.get_json("/route", {})
        self.assertIn("WP_APP_PASSWORD", str(ctx.exception))
        self.assertEqual(len(session.calls), 1)
        self.assertEqual(ctx.exception.status_code, 401)

    def test_get_4xx_carries_status_code(self):
        session = FakeSession([FakeResponse(400)])
        client = wp_common.WpClient(session, "https://site", 5, 2, retryable=(ConnectionError_,))
        with self.assertRaises(wp_errors.WpSyncError) as ctx:
            client.get_json("/route", {})
        self.assertEqual(ctx.exception.status_code, 400)

    def test_get_5xx_retried(self):
        session = FakeSession([FakeResponse(503), FakeResponse(200, json_data={"ok": True})])
        client = wp_common.WpClient(session, "https://site", 5, 2, retryable=(ConnectionError_,))
        result = client.get_json("/route", {})
        self.assertEqual(result, {"ok": True})
        self.assertEqual(len(session.calls), 2)

    def test_timeout_forwarded(self):
        session = FakeSession([FakeResponse(200, json_data={})])
        client = wp_common.WpClient(session, "https://site", 7.5, 0, retryable=(ConnectionError_,))
        client.get_json("/route", {})
        self.assertEqual(session.calls[0][3], 7.5)

    def test_put_never_retried(self):
        session = FakeSession([ConnectionError_()])
        client = wp_common.WpClient(session, "https://site", 5, 2, retryable=(ConnectionError_,))
        with self.assertRaises(wp_errors.WpWriteUnconfirmed):
            client.put_json("/route", {"content": "x"})
        self.assertEqual(len(session.calls), 1)

    def test_get_bad_json_body_raises(self):
        session = FakeSession([FakeResponse(200, json_data=None)])
        client = wp_common.WpClient(session, "https://site", 5, 0, retryable=(ConnectionError_,))
        with self.assertRaises(wp_errors.WpSyncError):
            client.get_json("/route", {})


class TestMakeSession(unittest.TestCase):
    def test_session_app_password(self):
        class FakeFactorySession:
            def __init__(self):
                self.auth = None
                self.cookies = None

        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            session = wp_common.make_session(
                data_dir,
                {"WP_APP_USER": "alice", "WP_APP_PASSWORD": "S3CRET-XYZ"},
                session_factory=FakeFactorySession,
            )
            self.assertEqual(session.auth, ("alice", "S3CRET-XYZ"))

    def test_session_cookie_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            config_dir = data_dir / "config"
            config_dir.mkdir()
            (config_dir / "cookies.json").write_text(
                json.dumps([{"name": "sess", "value": "abc", "domain": "example.org"}]),
                encoding="utf-8",
            )
            session = wp_common.make_session(data_dir, {}, session_factory=_FakeSessionFactory)
            self.assertEqual(session.cookies.set_calls, [("sess", "abc", "example.org", "/")])

    def test_session_no_credentials_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            with self.assertRaises(wp_errors.WpRefusal):
                wp_common.make_session(data_dir, {}, session_factory=_FakeSessionFactory)

    def test_secret_never_in_message(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            config_dir = data_dir / "config"
            config_dir.mkdir()
            (config_dir / "cookies.json").write_text("{not json", encoding="utf-8")
            try:
                wp_common.make_session(
                    data_dir,
                    {"WP_APP_PASSWORD": "S3CRET-XYZ"},
                    session_factory=_FakeSessionFactory,
                )
                self.fail("expected WpRefusal")
            except wp_errors.WpRefusal as exc:
                self.assertNotIn("S3CRET-XYZ", str(exc))

    def test_requests_not_imported(self):
        code = (
            "import sys; sys.path.insert(0, r'%s'); import wp_common; "
            "print('requests' in sys.modules)" % str(SCRIPTS)
        )
        result = subprocess.run(
            [sys.executable, "-c", code], capture_output=True, text=True, timeout=30
        )
        self.assertEqual(result.stdout.strip(), "False", result.stderr)


class _FakeCookieJar:
    def __init__(self):
        self.set_calls = []

    def set(self, name, value, domain="", path="/"):
        self.set_calls.append((name, value, domain, path))


class _FakeSessionFactory:
    def __init__(self):
        self.auth = None
        self.cookies = _FakeCookieJar()


if __name__ == "__main__":
    unittest.main()
