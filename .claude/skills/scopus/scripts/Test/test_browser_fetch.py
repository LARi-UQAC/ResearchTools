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


class _FakeHandle:
    """An ElementHandle: bound to the document it was taken from."""

    def __init__(self, page, selector):
        self._page = page
        self._selector = selector
        self._epoch = page.epoch

    def _live(self):
        if self._page.epoch != self._epoch:
            raise browser_fetch._PWError("Element is not attached to the DOM")

    def fill(self, value, **kw):
        self._live()
        self._page.filled.append((self._selector, value))

    def click(self, **kw):
        self._live()
        self._page.click(self._selector)


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
                 controls=None, redirects=None, login=None, present=None,
                 challenge_waits=0, challenge_selector_waits=0):
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
        self.challenge_waits = challenge_waits      # the Cloudflare page shows (by title)
        self.challenge_selector_waits = challenge_selector_waits   # ... by iframe selector
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
        return _FakeHandle(self, selector)

    epoch = 0   # bumped by a navigation; an element handle taken earlier is then stale

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

    def evaluate(self, script, *a, **k):
        return "UA-FIXTURE/157"

    def title(self):
        return "Just a moment..." if len(self.waits_ms) < self.challenge_waits else "Article"

    def query_selector(self, selector):
        if "challenges.cloudflare.com" in selector:
            if len(self.waits_ms) < self.challenge_selector_waits:
                return _FakeElement(self, None)
            return None
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
        self.dead = False   # the user closed the window: new_page then raises
        self.closed = False
        self.close_count = 0
        self.listeners = 0

    def on(self, event, cb):
        self.listeners += 1   # no popups are ever emitted by the offline fakes

    def remove_listener(self, event, cb):
        self.listeners -= 1

    cookie_jar = None   # {host: [{"name": ..., "value": ...}]}; set by a test

    def cookies(self, urls=None):
        from urllib.parse import urlparse as _u
        jar = self.cookie_jar or {}
        out = []
        for url in (urls if isinstance(urls, list) else [urls]):
            out += jar.get(_u(url).hostname, [])
        return out

    def add_init_script(self, script):
        pass

    new_page_error = None   # a test sets a message to make new_page raise it

    def new_page(self):
        if self.dead:
            raise browser_fetch._PWError(
                "BrowserContext.new_page: Target page, context or browser has been closed")
        if self.new_page_error:
            raise browser_fetch._PWError(self.new_page_error)
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
    "challenge_title_markers", "challenge_selectors", "curl_impersonate", "max_redirects",
    "stream_chunk_bytes", "title_chars", "reason_chars",
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
        "challenge_title_markers": ["just a moment"],
        "challenge_selectors": ["iframe[src*='challenges.cloudflare.com']"],
        "curl_impersonate": "chrome", "max_redirects": 5,
        "stream_chunk_bytes": 16384, "title_chars": 80, "reason_chars": 160,
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
        # the click-through attempt).
        # A challenge that never clears keeps the human window open in full:
        # int(window / poll) polls per settle.
        page = FakePage(html=ARTICLE_HTML, challenge_waits=999)
        self._fetch(page, {"human_window_s": 6, "poll_s": 2, "headless_wait_s": 1},
                    headed=True)
        self.assertEqual(page.waits_ms.count(2000), 2 * 3)
        # Headless has no human: the short budget, whatever the page shows.
        page = FakePage(html=ARTICLE_HTML, challenge_waits=999)
        self._fetch(page, {"human_window_s": 6, "poll_s": 2, "headless_wait_s": 4},
                    headed=False)
        self.assertEqual(page.waits_ms.count(2000), 2 * 2)

    def test_the_human_window_lasts_only_while_a_challenge_is_showing(self):
        # Measured live 2026-11-05: after the owner clicked the Turnstile box the run
        # still waited out the whole 120 s window (three times), because only a
        # captured PDF ended the wait. The window now ends a short quiet period
        # (headless_wait_s) after the challenge is gone.
        page = FakePage(html=ARTICLE_HTML, challenge_waits=4)   # clears after 4 polls
        self._fetch(page, {"human_window_s": 60, "poll_s": 2, "headless_wait_s": 2},
                    headed=True)
        # first settle: 4 polls while the challenge shows + the quiet period
        # (headless_wait_s / poll_s = 1 poll); the second settle finds no challenge:
        # one quiet poll. Far below the 2 x 30 polls of the full window.
        self.assertEqual(page.waits_ms.count(2000), 4 + 1 + 1)

    def test_a_page_that_never_shows_a_challenge_does_not_wait_for_a_human(self):
        page = FakePage(html=ARTICLE_HTML)
        self._fetch(page, {"human_window_s": 60, "poll_s": 2, "headless_wait_s": 2},
                    headed=True)
        self.assertEqual(page.waits_ms.count(2000), 2)         # one quiet poll per settle

    def test_a_challenge_selector_counts_too(self):
        page = FakePage(html=ARTICLE_HTML, challenge_selector_waits=3)
        self._fetch(page, {"human_window_s": 60, "poll_s": 2, "headless_wait_s": 2},
                    headed=True)
        self.assertEqual(page.waits_ms.count(2000), 3 + 1 + 1)  # 3 polls + quiet, then quiet

    def test_challenge_markers_must_be_lists_of_non_empty_strings(self):
        for key in ("challenge_title_markers", "challenge_selectors"):
            for bad in ("just a moment", [], [""], [5], None):
                with tempfile.TemporaryDirectory() as tmp, self.subTest(key=key, bad=bad):
                    path = self._write(tmp, _config_dict(**{key: bad}))
                    with self.assertRaises(browser_fetch.BrowserConfigError) as ctx:
                        browser_fetch.load_config(path)
                    self.assertIn(key, str(ctx.exception))

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

    def test_a_navigation_while_the_secret_is_being_read_is_caught(self):
        # Security review 2026-11-05 (second finding): the secret is read by a
        # subprocess of up to provider_timeout_s, long enough for a meta-refresh
        # or a script redirect. The origin is checked again after the read.
        h = _SignInHarness(self)
        page = h.page()

        def navigating_password(item, provider, **kw):
            h.password_calls.append((item, provider, kw))
            page._current = "https://evil.example.net/phish"   # the page moved meanwhile
            page.epoch += 1
            return PW_SECRET
        with mock.patch.dict(os.environ, {"RT_TEST_LOGIN_USER": "someone"}), \
             mock.patch.object(browser_fetch, "_PW_OK", True), \
             mock.patch.object(browser_fetch, "sync_playwright",
                               lambda: _FakePWCtxFrom(_FakePW(page))), \
             mock.patch.object(browser_fetch.browser_login, "get_password",
                               navigating_password):
            with tempfile.TemporaryDirectory() as tmp, \
                 self.assertRaises(browser_fetch.BrowserRungError) as ctx:
                browser_fetch.fetch_pdf_via_browser(
                    "10.9999/x", str(Path(tmp) / "p.pdf"), config=h.config())
        self.assertIn("evil.example.net", str(ctx.exception))
        self.assertNotIn(("#pass", PW_SECRET), page.filled)
        self.assertNotIn(PW_SECRET, str(ctx.exception))

    def test_a_navigation_on_the_same_host_leaves_a_stale_element_that_cannot_be_filled(self):
        # The fill goes through the element handle taken BEFORE the secret was read,
        # so a document that was replaced in the meantime cannot receive it even
        # when the new page is on an allowed host.
        h = _SignInHarness(self)
        page = h.page()

        def navigating_password(item, provider, **kw):
            page.epoch += 1                                    # same URL, new document
            return PW_SECRET
        with mock.patch.dict(os.environ, {"RT_TEST_LOGIN_USER": "someone"}), \
             mock.patch.object(browser_fetch, "_PW_OK", True), \
             mock.patch.object(browser_fetch, "sync_playwright",
                               lambda: _FakePWCtxFrom(_FakePW(page))), \
             mock.patch.object(browser_fetch.browser_login, "get_password",
                               navigating_password):
            with tempfile.TemporaryDirectory() as tmp, \
                 self.assertRaises(browser_fetch.BrowserRungError) as ctx:
                browser_fetch.fetch_pdf_via_browser(
                    "10.9999/x", str(Path(tmp) / "p.pdf"), config=h.config())
        self.assertIn("#pass", str(ctx.exception))
        self.assertNotIn(("#pass", PW_SECRET), page.filled)
        self.assertNotIn(PW_SECRET, str(ctx.exception))

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


class _CffiResponse:
    """A streamed curl_cffi response: the body is only available through iter_content."""

    def __init__(self, status=200, headers=None, content=b""):
        self.status_code = status
        self.headers = headers or {}
        self._content = content
        self.read_bytes = 0
        self.closed = False

    @property
    def content(self):
        raise AssertionError("the whole body must never be read at once")

    def iter_content(self, chunk_size=None):
        step = chunk_size or 8192
        for i in range(0, len(self._content), step):
            chunk = self._content[i:i + step]
            self.read_bytes += len(chunk)
            yield chunk

    def close(self):
        self.closed = True


class _FakeCffi:
    """Stand-in for curl_cffi.requests: serves queued responses, records every call."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, headers=None, cookies=None, impersonate=None, timeout=None,
            allow_redirects=True, stream=False, **kw):
        self.calls.append(dict(url=url, headers=headers, cookies=cookies,
                               impersonate=impersonate, timeout=timeout,
                               allow_redirects=allow_redirects, stream=stream))
        return self.responses.pop(0)


JAR = {"www.example.org": [{"name": "cf_clearance", "value": "CLEAR-FIXTURE"}],
       "assets.example.org": [{"name": "asset", "value": "A-FIXTURE"}]}
PDF_URL = "https://www.example.org/science/pdfft"


class TestHybridFetch(unittest.TestCase):
    """After the owner clears the challenge, the PDF is downloaded by curl_cffi with the
    browser's cookies and user agent and Chrome's TLS fingerprint (issue #11, option B).
    Cookies are re-scoped on every redirect hop and never logged."""

    def _setup(self, *responses, cfg_values=None):
        page = FakePage(html=ARTICLE_HTML)
        context = _FakeContext(page)
        context.cookie_jar = JAR
        cffi = _FakeCffi(*responses)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cfg.json"
            path.write_text(__import__("json").dumps(_config_dict(**(cfg_values or {}))),
                            encoding="utf-8")
            cfg = browser_fetch.load_config(path)
        return page, context, cffi, cfg

    def _fetch(self, context, page, cffi, cfg, url=PDF_URL, ok=True):
        with mock.patch.object(browser_fetch, "_cffi_requests", cffi), \
             mock.patch.object(browser_fetch, "_CFFI_OK", ok):
            return browser_fetch._hybrid_fetch(context, page, url, cfg)

    def test_it_sends_the_browsers_cookies_user_agent_and_tls_profile(self):
        page, context, cffi, cfg = self._setup(
            _CffiResponse(200, {"Content-Type": "application/pdf"}, PDF_BYTES))
        self.assertEqual(self._fetch(context, page, cffi, cfg), PDF_BYTES)
        call = cffi.calls[0]
        self.assertEqual(call["headers"]["User-Agent"], "UA-FIXTURE/157")
        self.assertEqual(call["cookies"], {"cf_clearance": "CLEAR-FIXTURE"})
        self.assertEqual(call["impersonate"], "chrome")
        self.assertEqual(call["timeout"], cfg["nav_timeout_s"])
        self.assertIs(call["allow_redirects"], False)         # hops are followed here, scoped

    def test_cookies_are_rescoped_on_every_redirect_hop(self):
        page, context, cffi, cfg = self._setup(
            _CffiResponse(302, {"Location": "https://assets.example.org/f.pdf"}),
            _CffiResponse(200, {}, PDF_BYTES))
        self.assertEqual(self._fetch(context, page, cffi, cfg), PDF_BYTES)
        self.assertEqual(cffi.calls[1]["url"], "https://assets.example.org/f.pdf")
        self.assertEqual(cffi.calls[1]["cookies"], {"asset": "A-FIXTURE"})   # not cf_clearance

    def test_a_plain_http_start_or_redirect_is_refused(self):
        page, context, cffi, cfg = self._setup()
        self.assertIsNone(self._fetch(context, page, cffi, cfg, url="http://www.example.org/x"))
        self.assertEqual(cffi.calls, [])
        page, context, cffi, cfg = self._setup(
            _CffiResponse(302, {"Location": "http://assets.example.org/f.pdf"}))
        self.assertIsNone(self._fetch(context, page, cffi, cfg))
        self.assertEqual(len(cffi.calls), 1)

    def test_redirect_hops_are_capped_by_the_config(self):
        page, context, cffi, cfg = self._setup(
            *[_CffiResponse(302, {"Location": "https://www.example.org/next"})] * 9,
            cfg_values={"max_redirects": 2})
        self.assertIsNone(self._fetch(context, page, cffi, cfg))
        self.assertEqual(len(cffi.calls), 3)                  # first request + 2 hops

    def test_a_challenge_page_a_truncated_pdf_and_an_error_status_are_rejected(self):
        for response in (_CffiResponse(200, {"Content-Type": "text/html"},
                                       b"<html>Just a moment</html>"),
                         _CffiResponse(200, {}, b"%PDF-1.7 partial body no trailer"),
                         _CffiResponse(403, {}, b"")):
            page, context, cffi, cfg = self._setup(response)
            with self.subTest(status=response.status_code):
                self.assertIsNone(self._fetch(context, page, cffi, cfg))

    def test_the_body_is_streamed_and_capped_by_the_config(self):
        # Security review 2026-11-05: reading response.content whole let a hostile or
        # broken host exhaust memory. The size cap now applies while streaming.
        big = b"%PDF-1.7\n" + b"x" * 50_000 + b"\n%%EOF"
        page, context, cffi, cfg = self._setup(
            _CffiResponse(200, {}, big), cfg_values={"max_pdf_bytes": 20_000})
        response = cffi.responses[0]
        self.assertIsNone(self._fetch(context, page, cffi, cfg))
        self.assertIs(cffi.calls[0]["stream"], True)
        self.assertLess(response.read_bytes, 20_000 + 16_384)    # stopped at the cap, not at 50 000
        self.assertTrue(response.closed)

    def test_a_declared_length_over_the_cap_is_refused_before_any_byte_is_read(self):
        page, context, cffi, cfg = self._setup(
            _CffiResponse(200, {"Content-Length": "999999999"}, PDF_BYTES),
            cfg_values={"max_pdf_bytes": 20_000})
        response = cffi.responses[0]
        self.assertIsNone(self._fetch(context, page, cffi, cfg))
        self.assertEqual(response.read_bytes, 0)
        self.assertTrue(response.closed)

    def test_a_malformed_content_length_does_not_disable_the_cap(self):
        big = b"%PDF-1.7\n" + b"x" * 50_000 + b"\n%%EOF"
        page, context, cffi, cfg = self._setup(
            _CffiResponse(200, {"Content-Length": "not a number"}, big),
            cfg_values={"max_pdf_bytes": 20_000})
        self.assertIsNone(self._fetch(context, page, cffi, cfg))

    def test_a_body_exactly_at_the_cap_is_kept_and_the_response_is_always_closed(self):
        body = PDF_BYTES
        page, context, cffi, cfg = self._setup(
            _CffiResponse(200, {}, body), cfg_values={"max_pdf_bytes": len(body)})
        response = cffi.responses[0]
        self.assertEqual(self._fetch(context, page, cffi, cfg), body)
        self.assertTrue(response.closed)
        for redirect in (_CffiResponse(302, {"Location": "https://www.example.org/n"}),
                         _CffiResponse(403, {}, b"")):
            page, context, cffi, cfg = self._setup(redirect, _CffiResponse(200, {}, body))
            self._fetch(context, page, cffi, cfg)
            self.assertTrue(redirect.closed)

    def test_curl_cffi_absent_degrades_without_raising(self):
        page, context, cffi, cfg = self._setup()
        self.assertIsNone(self._fetch(context, page, cffi, cfg, ok=False))
        self.assertEqual(cffi.calls, [])

    def test_without_the_browsers_user_agent_nothing_is_sent(self):
        # A clearance cookie is bound to the user agent that earned it.
        page, context, cffi, cfg = self._setup()

        def no_agent(*a, **k):
            raise browser_fetch._PWError("page closed")
        page.evaluate = no_agent
        self.assertIsNone(self._fetch(context, page, cffi, cfg))
        self.assertEqual(cffi.calls, [])

    def test_a_network_error_is_a_miss_not_a_crash(self):
        page, context, cffi, cfg = self._setup()
        cffi.get = mock.Mock(side_effect=RuntimeError("connection reset"))
        self.assertIsNone(self._fetch(context, page, cffi, cfg))

    def test_cookie_values_never_reach_a_log(self):
        page, context, cffi, cfg = self._setup(_CffiResponse(200, {}, PDF_BYTES))
        logs = _capture_logs(browser_fetch.logger)
        try:
            self._fetch(context, page, cffi, cfg)
        finally:
            logs.close()
        self.assertFalse(any("CLEAR-FIXTURE" in m for m in logs.messages))

    def test_the_flow_downloads_the_discovered_pdf_link_through_curl_cffi(self):
        page = FakePage(html=ARTICLE_HTML, meta=PDF_URL, redirects={DOI_ENTRY: ARTICLE_URL})
        cffi = _FakeCffi(_CffiResponse(200, {}, PDF_BYTES))
        with mock.patch.object(_FakeContext, "cookie_jar", JAR), \
             mock.patch.object(browser_fetch, "_cffi_requests", cffi), \
             mock.patch.object(browser_fetch, "_CFFI_OK", True):
            res, on_disk = TestBrowserFetch()._run(page)
        self.assertIsNotNone(res)
        self.assertTrue(on_disk.startswith(b"%PDF"))
        self.assertEqual(cffi.calls[0]["url"], PDF_URL)
        self.assertNotIn(PDF_URL, page.goto_urls)             # no second browser navigation

    def test_a_blocked_curl_cffi_falls_back_to_navigating_the_link(self):
        page = FakePage(html=ARTICLE_HTML, meta=PDF_URL, redirects={DOI_ENTRY: ARTICLE_URL})
        cffi = _FakeCffi(_CffiResponse(403, {}, b""))
        with mock.patch.object(_FakeContext, "cookie_jar", JAR), \
             mock.patch.object(browser_fetch, "_cffi_requests", cffi), \
             mock.patch.object(browser_fetch, "_CFFI_OK", True):
            TestBrowserFetch()._run(page)
        self.assertIn(PDF_URL, page.goto_urls)

    def test_a_ranged_reader_response_is_completed_through_curl_cffi(self):
        # The reader streams only a chunk (no %%EOF); the full file is fetched from the
        # same URL with the browser's session instead of Playwright's own request client.
        page = FakePage(pdf_body=b"%PDF-1.7 partial chunk")
        cffi = _FakeCffi(_CffiResponse(200, {}, PDF_BYTES))
        with mock.patch.object(_FakeContext, "cookie_jar", {"host": [{"name": "c", "value": "v"}]}), \
             mock.patch.object(browser_fetch, "_cffi_requests", cffi), \
             mock.patch.object(browser_fetch, "_CFFI_OK", True):
            res, on_disk = TestBrowserFetch()._run(page)
        self.assertIsNotNone(res)
        self.assertTrue(on_disk.endswith(b"%%EOF"))


class TestLastOutcome(unittest.TestCase):
    """A failed run says what the browser saw. Measured live 2026-11-05: a six-minute
    run ended with 'no PDF returned' and nobody could tell a paywall from a challenge."""

    def _fail(self, **page_kw):
        h = _SignInHarness(self, hosts={})
        page = h.page(**page_kw)
        res, _ = h.run(page)
        self.assertIsNone(res)
        return browser_fetch.last_outcome()

    def test_it_names_the_host_and_title_of_the_last_page(self):
        out = self._fail()
        self.assertIn("www.example.org", out)
        self.assertIn("Article", out)

    def test_it_says_when_a_challenge_was_still_showing(self):
        out = self._fail(challenge_waits=999)
        self.assertIn("challenge", out)
        self.assertNotIn("no challenge", out)

    def test_it_says_when_no_challenge_was_showing(self):
        self.assertIn("no challenge", self._fail())

    def test_no_path_or_query_is_recorded(self):
        out = self._fail(redirects={DOI_ENTRY: ARTICLE_URL + "/secret/path?token=abc"})
        self.assertNotIn("secret", out)
        self.assertNotIn("token", out)

    def test_a_success_clears_it(self):
        self._fail()
        h = _SignInHarness(self, hosts={})
        page = h.page(login=dict(LOGIN, pdf_requires_login=False))
        res, _ = h.run(page)
        self.assertIsNotNone(res)
        self.assertEqual(browser_fetch.last_outcome(), "")


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


class _FillTimingPage(FakePage):
    """Remembers how many waits had happened when the sign-in form was first looked up."""

    waits_at_first_fill = None

    def wait_for_selector(self, selector, timeout=None, **kw):
        if self.waits_at_first_fill is None:
            self.waits_at_first_fill = len(self.waits_ms)
        return super().wait_for_selector(selector, timeout=timeout, **kw)


class TestReviewRound1(unittest.TestCase):
    """Findings of the first local code review (R35) on the browser rung."""

    def test_a_failed_sign_in_is_not_repeated_for_the_next_paper_on_that_host(self):
        # Without a memory, a 40-paper run repeats the failing sign-in 40 times, each
        # re-reading the secret and waiting the human window, and can lock the account.
        h = _SignInHarness(self)
        page = h.page(login=dict(LOGIN, ready_after_waits=99))
        fake = _FakePW(page)
        session = browser_fetch.BrowserSession(config=h.config(), headed=True)
        with self.assertRaises(browser_fetch.BrowserRungError):
            h.run(page, session=session, fake=fake)
        with self.assertRaises(browser_fetch.BrowserRungError) as ctx:
            h.run(page, session=session, fake=fake)
        self.assertIn("already failed", str(ctx.exception))
        self.assertIn("www.example.org", str(ctx.exception))
        self.assertEqual(len(h.password_calls), 1)
        self.assertEqual(page.goto_urls.count(GOOD_HOST["entry_url"]), 1)
        session.close()

    def test_the_memory_of_a_failed_sign_in_belongs_to_one_session(self):
        h = _SignInHarness(self)
        page = h.page(login=dict(LOGIN, ready_after_waits=99))
        for _ in range(2):
            session = browser_fetch.BrowserSession(config=h.config(), headed=True)
            with self.assertRaises(browser_fetch.BrowserRungError):
                h.run(page, session=session, fake=_FakePW(page))
            session.close()
        self.assertEqual(len(h.password_calls), 2)

    def test_the_challenge_is_cleared_before_the_sign_in_starts(self):
        # A listed host that answers with the challenge page sent the flow into the
        # sign-in before the human window that exists to clear that challenge.
        h = _SignInHarness(self)
        page = _FillTimingPage(pdf_body=PDF_BYTES, login=dict(LOGIN),
                               redirects={DOI_ENTRY: ARTICLE_URL}, challenge_waits=2)
        res, _ = h.run(page)
        self.assertIsNotNone(res)
        self.assertIsNotNone(page.waits_at_first_fill)
        self.assertGreaterEqual(page.waits_at_first_fill, 2)

    def test_without_a_challenge_the_sign_in_starts_at_once(self):
        # Control: no extra wait is added when nothing is showing.
        h = _SignInHarness(self)
        page = _FillTimingPage(pdf_body=PDF_BYTES, login=dict(LOGIN),
                               redirects={DOI_ENTRY: ARTICLE_URL})
        h.run(page)
        self.assertEqual(page.waits_at_first_fill, 0)

    def test_a_closed_window_is_replaced_for_the_next_paper(self):
        # The owner closes the headed window, or Chrome crashes: the shared context
        # is dead and every later paper of the run used to fail with no hint.
        h = _SignInHarness(self)
        page = h.page(login=dict(LOGIN, pdf_requires_login=False), redirects={})
        fake = _FakePW(page)
        session = browser_fetch.BrowserSession(config=h.config(), headed=True)
        first, _ = h.run(page, session=session, fake=fake)
        self.assertIsNotNone(first)
        fake.chromium.contexts[0].dead = True
        second, _ = h.run(page, session=session, fake=fake)
        self.assertIsNotNone(second)
        self.assertEqual(len(fake.chromium.persistent_calls), 2)
        session.close()

    def test_another_page_error_does_not_relaunch_the_browser(self):
        # Control: only a closed target is retried; any other error stays a miss.
        h = _SignInHarness(self)
        page = h.page(login=dict(LOGIN, pdf_requires_login=False), redirects={})
        fake = _FakePW(page)
        session = browser_fetch.BrowserSession(config=h.config(), headed=True)
        h.run(page, session=session, fake=fake)
        fake.chromium.contexts[0].new_page_error = "Timeout 30000ms exceeded"
        second, _ = h.run(page, session=session, fake=fake)
        self.assertIsNone(second)
        self.assertEqual(len(fake.chromium.persistent_calls), 1)
        session.close()

    def test_a_block_page_is_not_treated_as_a_challenge_to_wait_on(self):
        # "Attention Required" is Cloudflare's hard block (address or firewall). A
        # person cannot clear it, so waiting the human window on it only costs time.
        markers = browser_fetch.load_config()["challenge_title_markers"]
        self.assertNotIn("attention required", [m.lower() for m in markers])
        self.assertIn("just a moment", [m.lower() for m in markers])


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
