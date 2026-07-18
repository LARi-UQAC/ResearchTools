"""
test_browser_fetch.py - offline unit tests for the browser (tier 8) retrieval.

No real browser and no network: the Playwright sync API is replaced by a small
set of fakes, and browser_fetch._PW_OK is forced True, so the capture / print /
paywall / override branches are exercised without installing Chromium.

Run:
    cd .claude/skills/scopus/scripts
    python -m pytest Test/test_browser_fetch.py -v
"""

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
                 controls=None):
        self._cbs = {}
        self._pdf_body = pdf_body      # served as an application/pdf response on goto
        self._html = html
        self._pdf_method = pdf_method  # bytes returned by page.pdf(), or None to raise
        self._meta = meta
        self._controls = controls or {}  # {selector: "pdf"} clickable controls
        self.goto_urls = []

    def set_default_timeout(self, ms):
        pass

    def on(self, event, cb):
        self._cbs.setdefault(event, []).append(cb)

    def _emit_pdf(self):
        for cb in self._cbs.get("response", []):
            cb(FakeResponse("application/pdf", self._pdf_body or PDF_BYTES))

    def goto(self, url, wait_until=None, **kw):
        self.goto_urls.append(url)
        if self._pdf_body is not None:
            self._emit_pdf()
        return None

    def wait_for_load_state(self, *a, **k):
        pass

    def wait_for_timeout(self, *a, **k):
        pass

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
        return None

    @property
    def url(self):
        return self.goto_urls[-1] if self.goto_urls else ""

    def content(self):
        return self._html

    def pdf(self, **kw):
        if self._pdf_method is None:
            raise browser_fetch._PWError("Page.pdf() is only supported in headless mode")
        return self._pdf_method


class _FakeChromium:
    def __init__(self, page):
        self._page = page
        self.launched_headless = None

    def launch(self, headless=True, **kw):
        self.launched_headless = headless
        return _FakeBrowser(self._page)


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

    def on(self, event, cb):
        pass  # no popups in the offline fakes

    def add_init_script(self, script):
        pass

    def new_page(self):
        return self._page


class _FakePW:
    def __init__(self, page):
        self.chromium = _FakeChromium(page)


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
