"""
test_browser_fetch.py - offline unit tests for the browser (tier 8) retrieval.

No real browser and no network: the Playwright sync API is replaced by a small
set of fakes, and browser_fetch._PW_OK is forced True, so the capture / print /
paywall / override branches are exercised without installing Chromium.

Run:
    cd .claude/skills/scopus/scripts
    python -m pytest Test/test_browser_fetch.py -v
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_HERE = Path(__file__).resolve().parent
_SCRIPTS = _HERE.parent
sys.path.insert(0, str(_SCRIPTS))

import browser_fetch  # noqa: E402


# --------------------------------------------------------------------------- #
# Playwright fakes - only the surface browser_fetch actually touches.
# --------------------------------------------------------------------------- #
class FakeResponse:
    def __init__(self, content_type, body, url="https://host/stream.pdf"):
        self.headers = {"content-type": content_type}
        self.url = url
        self._body = body

    def body(self):
        return self._body


class _FakeElement:
    """A clickable control; a 'pdf' action streams a PDF response on click."""

    def __init__(self, page, action):
        self._page = page
        self._action = action

    def click(self):
        if self._action == "pdf":
            self._page._emit_pdf()

    def get_attribute(self, name):
        return None


class _RaiseOnExit:
    """Stand-in for page.expect_popup()/expect_download(): raises a Playwright
    error on exit so the caller's `except _PWError` treats it as 'no popup'."""

    class _Info:
        @property
        def value(self):
            raise browser_fetch._PWError("none")

    def __enter__(self):
        return _RaiseOnExit._Info()

    def __exit__(self, *exc):
        raise browser_fetch._PWError("timeout")


class FakePage:
    """Drives the registered 'response' callback on goto (or on a control click)
    to simulate a PDF, and returns configurable content()/pdf()/meta/controls."""

    def __init__(self, *, pdf_body=None, html="", pdf_method=None, meta=None,
                 controls=None, redirects=None, login=None, present=None):
        self._cbs = {}
        self._pdf_body = pdf_body      # served as an application/pdf response on goto
        self._html = html
        self._pdf_method = pdf_method  # bytes returned by page.pdf(), or None to raise
        self._meta = meta
        self._controls = controls or {}  # {selector: "pdf"} clickable controls
        self.goto_urls = []
        self.waits_ms = []             # every wait_for_timeout argument, in order
        self.default_timeout_ms = None
        self._redirects = redirects or {}   # {requested url: final url}, as doi.org does
        self._current = ""
        # A sign-in form. login = {"submit": css, "logged_in": css, "ready_after_waits": n,
        # "pdf_requires_login": bool, "pdf_on_click": bool}. Clicking `submit` signs in;
        # the logged_in marker shows only once n waits have passed since the click, which
        # is how the owner's MFA approval is simulated.
        self._login = login
        self._signed_in = False
        self._waits_at_click = 0
        self._present = present        # selectors wait_for_selector accepts; None = all
        self.filled = []               # (selector, value) of every fill
        self.clicked = []              # every clicked selector
        self.closed = False

    def set_default_timeout(self, ms):
        self.default_timeout_ms = ms

    def on(self, event, cb):
        self._cbs.setdefault(event, []).append(cb)

    def _emit_pdf(self):
        for cb in self._cbs.get("response", []):
            cb(FakeResponse("application/pdf", self._pdf_body or PDF_BYTES))

    def goto(self, url, wait_until=None, **kw):
        self.goto_urls.append(url)
        self._current = self._redirects.get(url, url)
        gated = bool(self._login and self._login.get("pdf_requires_login"))
        if self._pdf_body is not None and (not gated or self._signed_in_visible()):
            self._emit_pdf()
        return None

    # --- sign-in simulation ------------------------------------------------
    def _signed_in_visible(self):
        if not (self._login and self._signed_in):
            return False
        return len(self.waits_ms) - self._waits_at_click >= self._login.get("ready_after_waits", 0)

    def expire_login(self):
        self._signed_in = False

    def fill(self, selector, value, **kw):
        self.filled.append((selector, value))

    def click(self, selector, **kw):
        self.clicked.append(selector)
        if self._login and selector == self._login.get("submit"):
            self._signed_in = True
            self._waits_at_click = len(self.waits_ms)
            if self._login.get("pdf_on_click"):
                self._emit_pdf()

    def wait_for_selector(self, selector, timeout=None, **kw):
        if self._present is not None and selector not in self._present:
            raise browser_fetch._PWError("Timeout waiting for selector %s" % selector)

    def close(self):
        self.closed = True

    def wait_for_load_state(self, *a, **k):
        pass

    def wait_for_timeout(self, ms=0, *a, **k):
        self.waits_ms.append(ms)

    def expect_popup(self, timeout=None):
        return _RaiseOnExit()

    def expect_download(self, timeout=None):
        return _RaiseOnExit()

    def get_attribute(self, selector, attr):
        if "citation_pdf_url" in selector:
            return self._meta
        return None

    def query_selector(self, selector):
        if selector in self._controls:
            return _FakeElement(self, self._controls[selector])
        if self._login and selector == self._login.get("logged_in") and self._signed_in_visible():
            return _FakeElement(self, None)
        return None

    @property
    def url(self):
        return self._current

    def content(self):
        return self._html

    def pdf(self, **kw):
        if self._pdf_method is None:
            raise browser_fetch._PWError("Page.pdf() is only supported in headless mode")
        return self._pdf_method


class _FakeChromium:
    def __init__(self, page, name="chromium", chrome_missing=False):
        self._page = page
        self.launched_headless = None
        self.profile_dir = None
        self.launch_called = False
        self.chrome_missing = chrome_missing   # installed Chrome absent: channel launch raises
        self.persistent_calls = []             # (user_data_dir, kwargs) of every launch attempt
        self.contexts = []                     # every context actually opened
        self.name = name

    def launch(self, headless=True, **kw):
        # Kept so a regression back to the non-persistent launch is visible to
        # test_persistent_profile_is_used rather than silently passing.
        self.launch_called = True
        self.launched_headless = headless
        return _FakeBrowser(self._page)

    def launch_persistent_context(self, user_data_dir, headless=True, **kw):
        # A persistent context IS the context: no browser object is returned,
        # which is the contract browser_fetch now depends on for its cleanup.
        self.persistent_calls.append((user_data_dir, dict(kw, headless=headless)))
        if kw.get("channel") and self.chrome_missing:
            raise browser_fetch._PWError(
                "BrowserType.launch_persistent_context: Chromium distribution "
                "'chrome' is not found at C:\\Program Files\\Google\\Chrome\\Application\\"
                "chrome.exe\nRun \"playwright install chrome\"")
        self.launched_headless = headless
        self.profile_dir = user_data_dir
        context = _FakeContext(self._page)
        self.contexts.append(context)
        return context


class _FakeBrowser:
    def __init__(self, page):
        self._page = page
        self.closed = False

    def new_context(self, **kw):
        return _FakeContext(self._page)

    def close(self):
        self.closed = True


class _FakeContext:
    def __init__(self, page):
        self._page = page
        self.closed = False
        self.close_count = 0
        self.listeners = 0

    def on(self, event, cb):
        self.listeners += 1   # no popups are ever emitted by the offline fakes

    def remove_listener(self, event, cb):
        self.listeners -= 1

    def add_init_script(self, script):
        pass

    def new_page(self):
        return self._page

    def close(self):
        # A persistent context is closed directly, standing in for the browser
        # close the non-persistent path used to perform.
        self.closed = True
        self.close_count += 1


class _FakePW:
    def __init__(self, page, chrome_missing=False):
        self.chromium = _FakeChromium(page, chrome_missing=chrome_missing)


class _FakePWCtx:
    def __init__(self, page):
        self._page = page

    def __enter__(self):
        return _FakePW(self._page)

    def __exit__(self, *exc):
        return False


def _fake_sync_playwright(page):
    """Return a callable usable as browser_fetch.sync_playwright."""
    return lambda: _FakePWCtx(page)


class _FakePWCtxFrom:
    """Yield a Playwright fake the caller already holds.

    _FakePWCtx builds a new _FakePW on every enter, so what the code under test
    launched cannot be inspected afterwards. This variant hands back the exact
    object the test kept a reference to.
    """

    def __init__(self, fake_pw):
        self._fake = fake_pw

    def __enter__(self):
        return self._fake

    def __exit__(self, *exc):
        return False


PDF_BYTES = b"%PDF-1.7\n" + b"real-article-body " * 50 + b"\n%%EOF"
PRINT_BYTES = b"%PDF-1.4\n" + b"printed-page " * 50 + b"\n%%EOF"
ARTICLE_HTML = (
    "<!DOCTYPE html><html><head><title>An Engineering Paper</title></head>"
    "<body><h1>Introduction</h1><p>" + ("body text " * 200) + "</p></body></html>"
)
PAYWALL_HTML = (
    "<!DOCTYPE html><html><head><title>Sign in</title></head>"
    "<body>Please sign in to view this article.</body></html>"
)


class TestBrowserFetch(unittest.TestCase):

    def _run(self, page, *, doi="10.9999/x", override_url=None, headed=True):
        with mock.patch.object(browser_fetch, "_PW_OK", True), \
             mock.patch.object(browser_fetch, "sync_playwright",
                               _fake_sync_playwright(page)):
            with tempfile.TemporaryDirectory() as tmp:
                dest = str(Path(tmp) / "paper.pdf")
                res = browser_fetch.fetch_pdf_via_browser(
                    doi, dest, override_url=override_url, headed=headed)
                on_disk = Path(dest).read_bytes() if Path(dest).exists() else None
        return res, on_disk

    def test_captures_real_pdf_response(self):
        page = FakePage(pdf_body=PDF_BYTES)
        res, on_disk = self._run(page)
        self.assertIsNotNone(res)
        self.assertEqual(res["format"], "pdf")
        self.assertEqual(res["source"], "browser")
        self.assertTrue(on_disk.startswith(b"%PDF"))

    def test_html_only_never_saves_print(self):
        # No real PDF captured -> the tier must NOT print the page to PDF (that
        # produced blank/landing-page false positives). Even a page that could be
        # printed yields None and writes nothing.
        page = FakePage(html=ARTICLE_HTML, pdf_method=PRINT_BYTES)
        res, on_disk = self._run(page, headed=False)
        self.assertIsNone(res)
        self.assertIsNone(on_disk)

    def test_paywall_page_returns_none(self):
        page = FakePage(html=PAYWALL_HTML)
        res, on_disk = self._run(page, headed=False)
        self.assertIsNone(res)
        self.assertIsNone(on_disk)

    def test_click_through_view_pdf_captures(self):
        # No PDF on initial load; a "View PDF" control click streams the PDF
        # (the Taylor & Francis flow). Click-through must capture it.
        page = FakePage(html=ARTICLE_HTML,
                        controls={'a:has-text("View PDF")': "pdf"})
        res, on_disk = self._run(page, headed=True)
        self.assertIsNotNone(res)
        self.assertEqual(res["source"], "browser")
        self.assertTrue(on_disk.startswith(b"%PDF"))

    def test_override_url_used_and_marked(self):
        page = FakePage(pdf_body=PDF_BYTES)
        override = "https://www.researchgate.net/publication/366555290_x"
        res, on_disk = self._run(page, override_url=override)
        self.assertIsNotNone(res)
        self.assertEqual(res["source"], "override")
        self.assertEqual(page.goto_urls[0], override)  # went to override, not doi.org
        self.assertTrue(on_disk.startswith(b"%PDF"))

    def test_persistent_profile_is_used_not_a_fresh_browser(self):
        # Measured 2026-09-17: ScienceDirect refused a plain Playwright Chromium
        # with a Cloudflare interstitial. A persistent profile keeps the solved
        # challenge and the institutional session across papers, which a fresh
        # context throws away every time. Asserted in BOTH directions, since a
        # regression to chromium.launch() would otherwise still pass every other
        # test in this file.
        page = FakePage(pdf_body=PDF_BYTES)
        fake = _FakePW(page)

        with mock.patch.object(browser_fetch, "_PW_OK", True), \
             mock.patch.object(browser_fetch, "sync_playwright",
                               lambda: _FakePWCtxFrom(fake)):
            with tempfile.TemporaryDirectory() as tmp:
                dest = str(Path(tmp) / "paper.pdf")
                browser_fetch.fetch_pdf_via_browser("10.9999/x", dest, headed=False)

        self.assertEqual(fake.chromium.profile_dir,
                         browser_fetch.profile_dir(browser_fetch.load_config()))
        self.assertFalse(fake.chromium.launch_called,
                         "must not fall back to a fresh non-persistent browser")

    def test_profile_dir_is_outside_the_repository(self):
        # The profile holds session cookies for the operator's institutional
        # access, so it must never land in the clone and be committed.
        prof = os.path.abspath(browser_fetch.profile_dir(browser_fetch.load_config()))
        repo = os.path.abspath(os.path.join(os.path.dirname(browser_fetch.__file__),
                                            "..", "..", "..", ".."))
        self.assertFalse(prof.startswith(repo + os.sep),
                         f"profile {prof} sits inside the repository {repo}")

    def test_no_anti_detect_library_is_imported(self):
        # Owner ruling 2026-11-05: no stealth / anti-detect library. A human
        # clicks the challenge in a real Chrome window; nothing hides the
        # automation. The module used to import playwright_stealth when present.
        src = Path(browser_fetch.__file__).read_text(encoding="utf-8")
        self.assertNotIn("import playwright_stealth", src)
        self.assertNotIn("from playwright_stealth", src)
        self.assertFalse(hasattr(browser_fetch, "Stealth"))
        self.assertFalse(hasattr(browser_fetch, "_STEALTH_OK"))
        reqs = (_SCRIPTS / "requirements.txt").read_text(encoding="utf-8")
        self.assertNotIn("playwright-stealth==", reqs)

    def test_non_https_override_rejected(self):
        page = FakePage(pdf_body=PDF_BYTES)
        res, on_disk = self._run(page, override_url="http://insecure.example/x.pdf")
        self.assertIsNone(res)
        self.assertIsNone(on_disk)
        self.assertEqual(page.goto_urls, [])  # never navigated

    def test_browser_available_reflects_flag(self):
        with mock.patch.object(browser_fetch, "_PW_OK", False):
            self.assertFalse(browser_fetch.browser_available())
        with mock.patch.object(browser_fetch, "_PW_OK", True):
            self.assertTrue(browser_fetch.browser_available())

    def test_skipped_when_playwright_absent(self):
        with mock.patch.object(browser_fetch, "_PW_OK", False):
            with tempfile.TemporaryDirectory() as tmp:
                dest = str(Path(tmp) / "paper.pdf")
                res = browser_fetch.fetch_pdf_via_browser("10.1/x", dest)
        self.assertIsNone(res)


SHIPPED_CONFIG = _SCRIPTS / "browser-fetch.json"

REQUIRED_KEYS = (
    "nav_timeout_s", "idle_timeout_s", "human_window_s", "headless_wait_s", "poll_s",
    "popup_wait_s", "viewer_settle_s", "download_wait_s", "download_retry_pause_s",
    "step_timeout_s", "max_pdf_bytes", "channel", "profile_dir", "user_agent",
    "secret_provider", "allow_totp_from_vault", "provider_timeout_s", "hosts",
)

GOOD_HOST = {
    "entry_url": "https://login.example.org/start",
    "login_hosts": ["login.example.org"],
    "username_env": "RT_TEST_LOGIN_USER",
    "vault_item": "example-institution",
    "steps": [
        {"action": "fill_username", "selector": "#user"},
        {"action": "fill_password", "selector": "#pass"},
        {"action": "click", "selector": "button[type=submit]"},
    ],
    "logged_in_selector": "#account-menu",
}


def _config_dict(**overrides):
    """A complete raw config ({value, provenance} per key) with a test override."""
    values = {
        "nav_timeout_s": 60, "idle_timeout_s": 20, "human_window_s": 6,
        "headless_wait_s": 3, "poll_s": 2, "popup_wait_s": 8, "viewer_settle_s": 2.5,
        "download_wait_s": 15, "download_retry_pause_s": 1.5, "step_timeout_s": 15,
        "max_pdf_bytes": 104857600, "channel": "chrome",
        "profile_dir": "~/.claude/scopus-browser-profile", "user_agent": None,
        "secret_provider": "keyring", "allow_totp_from_vault": False,
        "provider_timeout_s": 15, "hosts": {},
    }
    values.update(overrides)
    return {k: {"value": v, "provenance": "test fixture"} for k, v in values.items()}


class TestBrowserConfig(unittest.TestCase):
    """Every timeout, limit and host setting lives in browser-fetch.json (R0, R3, R4)."""

    def _write(self, tmp, raw):
        path = Path(tmp) / "cfg.json"
        path.write_text(__import__("json").dumps(raw), encoding="utf-8")
        return path

    def test_the_shipped_file_loads_and_carries_every_key(self):
        cfg = browser_fetch.load_config()
        for key in REQUIRED_KEYS:
            self.assertIn(key, cfg)
        self.assertEqual(cfg["secret_provider"], "keyring")
        self.assertEqual(cfg["channel"], "chrome")
        self.assertIs(cfg["allow_totp_from_vault"], False)

    def test_every_shipped_value_has_a_provenance(self):
        raw = __import__("json").loads(SHIPPED_CONFIG.read_text(encoding="utf-8"))
        for key in REQUIRED_KEYS:
            self.assertIn("provenance", raw[key], key)
            self.assertTrue(str(raw[key]["provenance"]).strip(), key)

    def test_a_missing_key_is_a_named_error(self):
        raw = _config_dict()
        del raw["human_window_s"]
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(tmp, raw)
            with self.assertRaises(browser_fetch.BrowserConfigError) as ctx:
                browser_fetch.load_config(path)
        self.assertIn("human_window_s", str(ctx.exception))
        self.assertIn("cfg.json", str(ctx.exception))

    def test_a_value_without_provenance_is_refused(self):
        for bad in ({"value": 5}, {"value": 5, "provenance": "  "}, 5):
            raw = _config_dict()
            raw["poll_s"] = bad
            with tempfile.TemporaryDirectory() as tmp, self.subTest(bad=bad):
                with self.assertRaises(browser_fetch.BrowserConfigError) as ctx:
                    browser_fetch.load_config(self._write(tmp, raw))
                self.assertIn("poll_s", str(ctx.exception))

    def test_numbers_must_be_positive_numbers(self):
        for key in ("nav_timeout_s", "poll_s", "max_pdf_bytes", "provider_timeout_s"):
            for bad in ("60", 0, -1, True, None):
                raw = _config_dict(**{key: bad})
                with tempfile.TemporaryDirectory() as tmp, self.subTest(key=key, bad=bad):
                    with self.assertRaises(browser_fetch.BrowserConfigError) as ctx:
                        browser_fetch.load_config(self._write(tmp, raw))
                    self.assertIn(key, str(ctx.exception))

    def test_secret_provider_must_be_a_known_backend(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(tmp, _config_dict(secret_provider="lastpass"))
            with self.assertRaises(browser_fetch.BrowserConfigError) as ctx:
                browser_fetch.load_config(path)
        self.assertIn("secret_provider", str(ctx.exception))
        for ok in ("keyring", "bitwarden", "keepassxc"):
            with tempfile.TemporaryDirectory() as tmp:
                path = self._write(tmp, _config_dict(secret_provider=ok))
                self.assertEqual(browser_fetch.load_config(path)["secret_provider"], ok)

    def test_channel_is_a_name_or_null_and_totp_flag_is_a_bool(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(browser_fetch.load_config(
                self._write(tmp, _config_dict(channel=None)))["channel"])
            for key, bad in (("channel", 5), ("allow_totp_from_vault", "yes")):
                path = self._write(tmp, _config_dict(**{key: bad}))
                with self.subTest(key=key), self.assertRaises(browser_fetch.BrowserConfigError):
                    browser_fetch.load_config(path)

    def test_a_good_host_entry_is_accepted(self):
        raw = _config_dict(hosts={"www.example.org": GOOD_HOST})
        with tempfile.TemporaryDirectory() as tmp:
            cfg = browser_fetch.load_config(self._write(tmp, raw))
        self.assertEqual(cfg["hosts"]["www.example.org"]["vault_item"], "example-institution")

    def test_a_bad_host_entry_is_refused_naming_the_host_and_the_field(self):
        cases = {
            "entry_url": dict(GOOD_HOST, entry_url="http://login.example.org/"),
            "username_env": {k: v for k, v in GOOD_HOST.items() if k != "username_env"},
            "vault_item": dict(GOOD_HOST, vault_item=""),
            "steps": dict(GOOD_HOST, steps=[{"action": "run_script", "selector": "x"}]),
            "logged_in_selector": dict(GOOD_HOST, logged_in_selector=""),
            "login_hosts": {k: v for k, v in GOOD_HOST.items() if k != "login_hosts"},
        }
        for bad in ([], "login.example.org", [""], [5], ["https://login.example.org/"],
                    ["login.example.org/path"]):
            cases["login_hosts (%r)" % (bad,)] = dict(GOOD_HOST, login_hosts=bad)
        for field, host in cases.items():
            raw = _config_dict(hosts={"www.example.org": host})
            with tempfile.TemporaryDirectory() as tmp, self.subTest(field=field):
                with self.assertRaises(browser_fetch.BrowserConfigError) as ctx:
                    browser_fetch.load_config(self._write(tmp, raw))
                self.assertIn("www.example.org", str(ctx.exception))
                self.assertIn(field.split(" ")[0], str(ctx.exception))

    def test_a_step_needs_a_selector(self):
        host = dict(GOOD_HOST, steps=[{"action": "click", "selector": ""}])
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(browser_fetch.BrowserConfigError):
                browser_fetch.load_config(
                    self._write(tmp, _config_dict(hosts={"h.example.org": host})))

    def test_no_file_and_bad_json_are_named_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "nope.json"
            with self.assertRaises(browser_fetch.BrowserConfigError) as ctx:
                browser_fetch.load_config(missing)
            self.assertIn("nope.json", str(ctx.exception))
            bad = Path(tmp) / "bad.json"
            bad.write_text("{not json", encoding="utf-8")
            with self.assertRaises(browser_fetch.BrowserConfigError) as ctx:
                browser_fetch.load_config(bad)
            self.assertIn("bad.json", str(ctx.exception))

    def test_the_old_module_constants_are_gone(self):
        for name in ("NAV_TIMEOUT_S", "IDLE_TIMEOUT_S", "ASSIST_WAIT_S", "POLL_S",
                     "MAX_PDF_BYTES", "BROWSER_UA"):
            self.assertFalse(hasattr(browser_fetch, name), name)

    def _fetch(self, page, cfg_values, headed):
        raw = _config_dict(**cfg_values)
        with tempfile.TemporaryDirectory() as tmp:
            cfg = browser_fetch.load_config(self._write(tmp, raw))
            with mock.patch.object(browser_fetch, "_PW_OK", True), \
                 mock.patch.object(browser_fetch, "sync_playwright",
                                   _fake_sync_playwright(page)):
                dest = str(Path(tmp) / "paper.pdf")
                return browser_fetch.fetch_pdf_via_browser(
                    "10.9999/x", dest, headed=headed, config=cfg)

    def test_the_navigation_timeout_comes_from_the_config(self):
        page = FakePage(pdf_body=PDF_BYTES)
        self._fetch(page, {"nav_timeout_s": 7}, headed=False)
        self.assertEqual(page.default_timeout_ms, 7000)

    def test_the_human_window_and_poll_interval_come_from_the_config(self):
        # No PDF is ever served, so the flow settles twice (entry page, then after
        # the click-through attempt). Each settle polls int(window / poll) times.
        page = FakePage(html=ARTICLE_HTML)
        self._fetch(page, {"human_window_s": 6, "poll_s": 2, "headless_wait_s": 1},
                    headed=True)
        self.assertEqual(page.waits_ms.count(2000), 2 * 3)
        page = FakePage(html=ARTICLE_HTML)
        self._fetch(page, {"human_window_s": 6, "poll_s": 2, "headless_wait_s": 4},
                    headed=False)
        self.assertEqual(page.waits_ms.count(2000), 2 * 2)

    def test_the_profile_directory_comes_from_the_config(self):
        page = FakePage(pdf_body=PDF_BYTES)
        fake = _FakePW(page)
        raw = _config_dict(profile_dir="~/some-other-profile")
        with tempfile.TemporaryDirectory() as tmp:
            cfg = browser_fetch.load_config(self._write(tmp, raw))
            with mock.patch.object(browser_fetch, "_PW_OK", True), \
                 mock.patch.object(browser_fetch, "sync_playwright",
                                   lambda: _FakePWCtxFrom(fake)):
                browser_fetch.fetch_pdf_via_browser(
                    "10.9999/x", str(Path(tmp) / "p.pdf"), headed=False, config=cfg)
        self.assertEqual(fake.chromium.profile_dir,
                         os.path.expanduser("~/some-other-profile"))


class _capture_logs:
    """Collect formatted log messages of one logger; unlike assertLogs it does not
    fail when nothing was logged, which is the case several tests assert."""

    def __init__(self, logger):
        import logging
        self._logger = logger
        self.messages = []
        outer = self

        class _H(logging.Handler):
            def emit(self, record):
                outer.messages.append(record.getMessage())
        self._handler = _H(level=logging.DEBUG)
        self._old_level = logger.level
        logger.setLevel(logging.DEBUG)
        logger.addHandler(self._handler)

    def close(self):
        self._logger.removeHandler(self._handler)
        self._logger.setLevel(self._old_level)


class TestChromeChannel(unittest.TestCase):
    """Rung 8 asks for the installed Chrome and says so when it falls back.

    Measured 2026-11-05: real Chrome 157 shows an interactive Turnstile checkbox a
    human can click, while the bundled Chromium never clears the interstitial.
    """

    def _launch(self, chrome_missing, **cfg_values):
        page = FakePage(pdf_body=PDF_BYTES)
        fake = _FakePW(page, chrome_missing=chrome_missing)
        raw = _config_dict(**cfg_values)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cfg.json"
            path.write_text(__import__("json").dumps(raw), encoding="utf-8")
            cfg = browser_fetch.load_config(path)
            with mock.patch.object(browser_fetch, "_PW_OK", True), \
                 mock.patch.object(browser_fetch, "sync_playwright",
                                   lambda: _FakePWCtxFrom(fake)):
                records = _capture_logs(browser_fetch.logger)
                try:
                    res = browser_fetch.fetch_pdf_via_browser(
                        "10.9999/x", str(Path(tmp) / "p.pdf"), headed=False, config=cfg)
                finally:
                    records.close()
        return res, fake.chromium, "\n".join(records.messages)

    def test_it_launches_the_installed_chrome_by_default(self):
        res, chromium, _ = self._launch(chrome_missing=False)
        self.assertIsNotNone(res)
        self.assertEqual(len(chromium.persistent_calls), 1)
        self.assertEqual(chromium.persistent_calls[0][1].get("channel"), "chrome")

    def test_a_missing_chrome_falls_back_to_the_bundled_chromium_and_says_so(self):
        res, chromium, log = self._launch(chrome_missing=True)
        self.assertIsNotNone(res)
        self.assertEqual(len(chromium.persistent_calls), 2)
        self.assertEqual(chromium.persistent_calls[0][1].get("channel"), "chrome")
        self.assertNotIn("channel", chromium.persistent_calls[1][1])
        self.assertIn("falling back to the bundled Chromium", log)

    def test_the_fallback_uses_its_own_profile_folder(self):
        # A profile written by Chrome is not safe to open with an older bundled
        # Chromium, so the fallback never shares the Chrome profile folder.
        _, chromium, _ = self._launch(chrome_missing=True)
        first, second = chromium.persistent_calls[0][0], chromium.persistent_calls[1][0]
        self.assertNotEqual(first, second)
        self.assertTrue(second.startswith(first))

    def test_a_null_channel_goes_straight_to_the_bundled_chromium_without_a_warning(self):
        res, chromium, log = self._launch(chrome_missing=True, channel=None)
        self.assertIsNotNone(res)
        self.assertEqual(len(chromium.persistent_calls), 1)
        self.assertNotIn("channel", chromium.persistent_calls[0][1])
        self.assertNotIn("falling back", log)

    def test_another_launch_failure_is_not_read_as_a_missing_chrome(self):
        # A locked profile or a crash must not silently switch browsers.
        page = FakePage(pdf_body=PDF_BYTES)
        fake = _FakePW(page)

        def boom(user_data_dir, headless=True, **kw):
            fake.chromium.persistent_calls.append((user_data_dir, kw))
            raise browser_fetch._PWError("the profile is locked by another process")
        fake.chromium.launch_persistent_context = boom
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(browser_fetch, "_PW_OK", True), \
                 mock.patch.object(browser_fetch, "sync_playwright",
                                   lambda: _FakePWCtxFrom(fake)):
                res = browser_fetch.fetch_pdf_via_browser(
                    "10.9999/x", str(Path(tmp) / "p.pdf"), headed=False)
        self.assertIsNone(res)
        self.assertEqual(len(fake.chromium.persistent_calls), 1)

    def test_the_forced_chrome_124_user_agent_is_gone(self):
        # With the real Chrome channel the old fixed UA would contradict the
        # browser's own client hints. It is only sent when the config names one.
        _, chromium, _ = self._launch(chrome_missing=False)
        self.assertNotIn("user_agent", chromium.persistent_calls[0][1])
        _, chromium, _ = self._launch(chrome_missing=False, user_agent="TestAgent/1.0")
        self.assertEqual(chromium.persistent_calls[0][1]["user_agent"], "TestAgent/1.0")


PW_SECRET = "S3cr3t-Pw-FIXTURE!"
DOI_ENTRY = "https://doi.org/10.9999/x"
ARTICLE_URL = "https://www.example.org/article/x"
LOGIN = {"submit": "button[type=submit]", "logged_in": "#account-menu",
         "ready_after_waits": 0, "pdf_requires_login": True}


class _SignInHarness:
    """Run fetch_pdf_via_browser against a fake host that has a sign-in form."""

    def __init__(self, testcase, **cfg_values):
        self.test = testcase
        self.cfg_values = dict(human_window_s=6, poll_s=2, hosts={"www.example.org": GOOD_HOST})
        self.cfg_values.update(cfg_values)
        self.password_calls = []
        self.totp_calls = []

    def page(self, **kw):
        kw.setdefault("pdf_body", PDF_BYTES)
        kw.setdefault("login", dict(LOGIN))
        kw.setdefault("redirects", {DOI_ENTRY: ARTICLE_URL})
        return FakePage(**kw)

    def config(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cfg.json"
            path.write_text(__import__("json").dumps(_config_dict(**self.cfg_values)),
                            encoding="utf-8")
            return browser_fetch.load_config(path)

    def run(self, page, *, user="someone", headed=True, session=None, fake=None):
        env = {"RT_TEST_LOGIN_USER": user} if user is not None else {}
        fake = fake or _FakePW(page)

        def fake_password(item, provider, **kw):
            self.password_calls.append((item, provider, kw))
            return PW_SECRET

        def fake_totp(item, provider, **kw):
            self.totp_calls.append((item, provider, kw))
            return "424242"

        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch.dict(os.environ, env), \
             mock.patch.object(browser_fetch, "_PW_OK", True), \
             mock.patch.object(browser_fetch, "sync_playwright", lambda: _FakePWCtxFrom(fake)), \
             mock.patch.object(browser_fetch.browser_login, "get_password", fake_password), \
             mock.patch.object(browser_fetch.browser_login, "get_totp", fake_totp):
            if user is None:
                os.environ.pop("RT_TEST_LOGIN_USER", None)
            logs = _capture_logs(browser_fetch.logger)
            self.logs = logs.messages          # bound now, so a raising call still leaves it
            try:
                res = browser_fetch.fetch_pdf_via_browser(
                    "10.9999/x", str(Path(tmp) / "p.pdf"), headed=headed,
                    config=self.config(), session=session)
            finally:
                logs.close()
        return res, fake


class TestInstitutionalSignIn(unittest.TestCase):
    """Rung 8 signs in for a listed host, fills only the configured fields, waits
    for the human's MFA and stops the moment a full PDF is captured."""

    def test_a_listed_host_signs_in_then_returns_to_the_article_and_gets_the_pdf(self):
        h = _SignInHarness(self)
        page = h.page()
        res, _ = h.run(page)
        self.assertIsNotNone(res)
        self.assertEqual(page.goto_urls, [DOI_ENTRY, GOOD_HOST["entry_url"], DOI_ENTRY])

    def test_only_the_configured_fields_are_filled_and_clicked(self):
        h = _SignInHarness(self)
        page = h.page()
        h.run(page)
        self.assertEqual(page.filled, [("#user", "someone"), ("#pass", PW_SECRET)])
        self.assertEqual(page.clicked, ["button[type=submit]"])

    def test_the_password_comes_from_the_configured_provider_with_a_bounded_timeout(self):
        h = _SignInHarness(self, secret_provider="bitwarden", provider_timeout_s=11)
        h.run(h.page())
        item, provider, kw = h.password_calls[0]
        self.assertEqual((item, provider), ("example-institution", "bitwarden"))
        self.assertEqual(kw["timeout_s"], 11)
        self.assertEqual(kw["username"], "someone")

    def test_it_waits_for_the_human_mfa_approval_then_continues(self):
        h = _SignInHarness(self)
        login = dict(LOGIN, ready_after_waits=2)          # the marker shows after 2 polls
        page = h.page(login=login)
        res, _ = h.run(page)
        self.assertIsNotNone(res)
        self.assertGreaterEqual(page.waits_ms.count(2000), 2)

    def test_a_sign_in_that_never_completes_is_a_named_refusal(self):
        h = _SignInHarness(self)
        page = h.page(login=dict(LOGIN, ready_after_waits=99))
        with self.assertRaises(browser_fetch.BrowserRungError) as ctx:
            h.run(page)
        self.assertIn("www.example.org", str(ctx.exception))
        self.assertIn("did not complete", str(ctx.exception))
        self.assertIn("6 s", str(ctx.exception))

    def test_polling_stops_the_moment_a_pdf_is_captured(self):
        h = _SignInHarness(self, human_window_s=60, poll_s=2)
        page = h.page(login=dict(LOGIN, ready_after_waits=99, pdf_on_click=True,
                                 pdf_requires_login=False), pdf_body=None)
        res, _ = h.run(page)
        self.assertIsNotNone(res)                          # captured on the submit click
        self.assertLess(len(page.waits_ms), 5)             # not 30 polls

    def test_a_host_that_is_not_listed_keeps_the_flow_without_sign_in(self):
        h = _SignInHarness(self, hosts={"www.other.org": GOOD_HOST})
        page = h.page(login=dict(LOGIN, pdf_requires_login=False))
        res, _ = h.run(page)
        self.assertIsNotNone(res)
        self.assertEqual(page.filled, [])
        self.assertEqual(page.goto_urls, [DOI_ENTRY])
        self.assertEqual(h.password_calls, [])

    def test_an_already_signed_in_session_is_not_signed_in_again(self):
        h = _SignInHarness(self)
        page = h.page(login=dict(LOGIN))
        page._signed_in = True                             # the profile still holds the cookie
        res, _ = h.run(page)
        self.assertIsNotNone(res)
        self.assertEqual(page.filled, [])
        self.assertEqual(h.password_calls, [])
        self.assertEqual(page.goto_urls, [DOI_ENTRY])

    def test_a_missing_user_name_variable_is_refused_before_any_secret_is_read(self):
        h = _SignInHarness(self)
        with self.assertRaises(browser_fetch.BrowserRungError) as ctx:
            h.run(h.page(), user=None)
        self.assertIn("RT_TEST_LOGIN_USER", str(ctx.exception))
        self.assertEqual(h.password_calls, [])

    def test_a_provider_refusal_becomes_the_rung_error_with_its_text(self):
        h = _SignInHarness(self)

        def locked(item, provider, **kw):
            raise browser_fetch.browser_login.LoginError("the Bitwarden vault is locked")
        with mock.patch.object(browser_fetch.browser_login, "get_password", locked), \
             self.assertRaises(browser_fetch.BrowserRungError) as ctx:
            with mock.patch.dict(os.environ, {"RT_TEST_LOGIN_USER": "someone"}), \
                 mock.patch.object(browser_fetch, "_PW_OK", True), \
                 mock.patch.object(browser_fetch, "sync_playwright",
                                   lambda: _FakePWCtxFrom(_FakePW(h.page()))):
                with tempfile.TemporaryDirectory() as tmp:
                    browser_fetch.fetch_pdf_via_browser(
                        "10.9999/x", str(Path(tmp) / "p.pdf"), config=h.config())
        self.assertIn("locked", str(ctx.exception))

    def test_a_missing_form_field_is_a_refusal_naming_the_selector(self):
        h = _SignInHarness(self)
        page = h.page(present={"#user"})                   # #pass never appears
        with self.assertRaises(browser_fetch.BrowserRungError) as ctx:
            h.run(page)
        self.assertIn("#pass", str(ctx.exception))
        self.assertIn("www.example.org", str(ctx.exception))

    def test_the_password_is_never_logged_or_in_an_error(self):
        h = _SignInHarness(self)
        h.run(h.page())
        self.assertFalse(any(PW_SECRET in m for m in h.logs))
        h = _SignInHarness(self)
        page = h.page(login=dict(LOGIN, ready_after_waits=99))
        with self.assertRaises(browser_fetch.BrowserRungError) as ctx:
            h.run(page)
        self.assertNotIn(PW_SECRET, str(ctx.exception))
        self.assertFalse(any(PW_SECRET in m for m in h.logs))

    def test_a_secret_is_never_typed_into_a_page_outside_the_login_hosts(self):
        # Security review 2026-11-05: an open redirect on the entry URL must not
        # lead the password to a look-alike page. The origin is checked BEFORE
        # the secret is read, and again at every password step.
        h = _SignInHarness(self)
        page = h.page(redirects={DOI_ENTRY: ARTICLE_URL,
                                 GOOD_HOST["entry_url"]: "https://evil.example.net/phish?t=1"})
        with self.assertRaises(browser_fetch.BrowserRungError) as ctx:
            h.run(page)
        self.assertIn("evil.example.net", str(ctx.exception))
        self.assertIn("login_hosts", str(ctx.exception))
        self.assertNotIn("phish", str(ctx.exception))       # no path or query in the text
        self.assertEqual(h.password_calls, [])              # the secret was never read
        self.assertNotIn(("#pass", PW_SECRET), page.filled)
        self.assertFalse(any(PW_SECRET in m for m in h.logs))

    def test_a_look_alike_host_and_a_plain_http_page_are_refused_too(self):
        for final in ("https://login.example.org.evil.example.net/start",
                      "https://evil.example.net/login.example.org",
                      "http://login.example.org/start"):
            h = _SignInHarness(self)
            page = h.page(redirects={DOI_ENTRY: ARTICLE_URL, GOOD_HOST["entry_url"]: final})
            with self.subTest(final=final), self.assertRaises(browser_fetch.BrowserRungError):
                h.run(page)
            self.assertEqual(h.password_calls, [])

    def test_the_check_is_case_insensitive_and_accepts_any_listed_host(self):
        host = dict(GOOD_HOST, login_hosts=["idp.example.org", "LOGIN.example.org"])
        h = _SignInHarness(self, hosts={"www.example.org": host})
        page = h.page(redirects={DOI_ENTRY: ARTICLE_URL,
                                 GOOD_HOST["entry_url"]: "https://Login.Example.org/start"})
        res, _ = h.run(page)
        self.assertIsNotNone(res)

    def test_a_one_time_code_is_checked_the_same_way(self):
        host = dict(GOOD_HOST, steps=[{"action": "fill_totp", "selector": "#otp"}])
        h = _SignInHarness(self, hosts={"www.example.org": host}, allow_totp_from_vault=True)
        page = h.page(redirects={DOI_ENTRY: ARTICLE_URL,
                                 GOOD_HOST["entry_url"]: "https://evil.example.net/x"})
        with self.assertRaises(browser_fetch.BrowserRungError):
            h.run(page)
        self.assertEqual(h.totp_calls, [])

    def test_the_user_name_may_be_typed_on_any_page_but_secrets_may_not(self):
        # Only the secrets are origin-checked: the user name is not a secret and
        # an identity provider often asks for it on its own host.
        host = dict(GOOD_HOST, steps=[GOOD_HOST["steps"][0]])
        h = _SignInHarness(self, hosts={"www.example.org": host})
        page = h.page(pdf_body=None, login=dict(LOGIN),
                      redirects={DOI_ENTRY: ARTICLE_URL,
                                 GOOD_HOST["entry_url"]: "https://elsewhere.example.net/"})
        with self.assertRaises(browser_fetch.BrowserRungError):
            h.run(page)                                     # it fails later (no sign-in marker) ...
        self.assertIn(("#user", "someone"), page.filled)    # ... but the user name was typed

    def test_a_totp_step_needs_the_flag_and_then_reads_the_code_from_the_vault(self):
        host = dict(GOOD_HOST, steps=GOOD_HOST["steps"][:2] + [
            {"action": "fill_totp", "selector": "#otp"}, GOOD_HOST["steps"][2]])
        h = _SignInHarness(self, hosts={"www.example.org": host})
        with self.assertRaises(browser_fetch.BrowserRungError) as ctx:
            h.run(h.page())
        self.assertIn("allow_totp_from_vault", str(ctx.exception))
        h = _SignInHarness(self, hosts={"www.example.org": host}, allow_totp_from_vault=True)
        page = h.page()
        res, _ = h.run(page)
        self.assertIsNotNone(res)
        self.assertIn(("#otp", "424242"), page.filled)
        self.assertTrue(h.totp_calls[0][2]["allow"])


class TestSessionReuse(unittest.TestCase):
    """One browser session serves a whole run: the second paper does not sign in again."""

    def _two_papers(self, h, page, fake, session):
        first, _ = h.run(page, session=session, fake=fake)
        second, _ = h.run(page, session=session, fake=fake)
        return first, second

    def test_the_second_paper_does_not_reopen_the_login_page(self):
        h = _SignInHarness(self)
        page = h.page()
        fake = _FakePW(page)
        with mock.patch.object(browser_fetch, "_PW_OK", True), \
             mock.patch.object(browser_fetch, "sync_playwright", lambda: _FakePWCtxFrom(fake)):
            session = browser_fetch.BrowserSession(config=h.config(), headed=True)
        first, second = self._two_papers(h, page, fake, session)
        self.assertIsNotNone(first)
        self.assertIsNotNone(second)
        self.assertEqual(page.goto_urls.count(GOOD_HOST["entry_url"]), 1)
        self.assertEqual(len(h.password_calls), 1)
        session.close()

    def test_one_browser_is_launched_and_closed_once_for_the_run(self):
        h = _SignInHarness(self)
        page = h.page()
        fake = _FakePW(page)
        session = browser_fetch.BrowserSession(config=h.config(), headed=True)
        self.assertEqual(fake.chromium.persistent_calls, [])    # lazy: nothing launched yet
        self._two_papers(h, page, fake, session)
        self.assertEqual(len(fake.chromium.persistent_calls), 1)
        self.assertEqual(fake.chromium.contexts[0].close_count, 0)   # still open between papers
        session.close()
        self.assertEqual(fake.chromium.contexts[0].close_count, 1)
        session.close()                                          # idempotent
        self.assertEqual(fake.chromium.contexts[0].close_count, 1)

    def test_without_a_session_each_call_opens_and_closes_its_own_browser(self):
        h = _SignInHarness(self)
        page = h.page(login=dict(LOGIN, pdf_requires_login=False), redirects={})
        fake = _FakePW(page)
        h.run(page, fake=fake)
        h.run(page, fake=fake)
        self.assertEqual(len(fake.chromium.contexts), 2)
        self.assertTrue(all(c.close_count == 1 for c in fake.chromium.contexts))

    def test_an_expired_session_signs_in_again_once(self):
        h = _SignInHarness(self)
        page = h.page()
        fake = _FakePW(page)
        session = browser_fetch.BrowserSession(config=h.config(), headed=True)
        h.run(page, session=session, fake=fake)
        page.expire_login()                                      # the cookie went stale
        second, _ = h.run(page, session=session, fake=fake)
        self.assertIsNotNone(second)
        self.assertEqual(page.goto_urls.count(GOOD_HOST["entry_url"]), 2)
        session.close()

    def test_a_per_paper_page_is_closed_and_popup_listeners_do_not_pile_up(self):
        h = _SignInHarness(self)
        page = h.page()
        fake = _FakePW(page)
        session = browser_fetch.BrowserSession(config=h.config(), headed=True)
        self._two_papers(h, page, fake, session)
        self.assertTrue(page.closed)
        self.assertEqual(fake.chromium.contexts[0].listeners, 0)
        session.close()

    def test_a_session_works_as_a_context_manager(self):
        h = _SignInHarness(self)
        page = h.page()
        fake = _FakePW(page)
        with mock.patch.object(browser_fetch, "_PW_OK", True), \
             mock.patch.object(browser_fetch, "sync_playwright", lambda: _FakePWCtxFrom(fake)):
            with browser_fetch.BrowserSession(config=h.config(), headed=True) as session:
                session.context()
        self.assertEqual(fake.chromium.contexts[0].close_count, 1)


class TestSavePdfBytes(unittest.TestCase):

    def test_rejects_non_pdf(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = str(Path(tmp) / "p.pdf")
            self.assertFalse(browser_fetch._save_pdf_bytes(b"<html>nope", dest))
            self.assertFalse(Path(dest).exists())

    def test_writes_valid_pdf_atomically(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = str(Path(tmp) / "p.pdf")
            self.assertTrue(browser_fetch._save_pdf_bytes(PDF_BYTES, dest))
            self.assertTrue(Path(dest).read_bytes().startswith(b"%PDF"))
            self.assertFalse(Path(dest + ".part").exists())


if __name__ == "__main__":
    unittest.main()
