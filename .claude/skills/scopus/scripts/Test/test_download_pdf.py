"""
test_download_pdf.py — offline unit tests for the PDF retrieval script.

All network is patched: requests.get is replaced by a FakeResponse factory and
the source-chain helpers are monkeypatched, so no API key, no Semantic Scholar
install, and no real download occur.

Run:
    cd .claude/skills/scopus/scripts
    python -m pytest Test/test_download_pdf.py -v
"""

import contextlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_HERE = Path(__file__).resolve().parent
_SCRIPTS = _HERE.parent
sys.path.insert(0, str(_SCRIPTS))

import download_pdf  # noqa: E402


class FakeResponse:
    """Minimal stand-in for requests.Response in streaming mode."""

    def __init__(self, status_code=200, headers=None, chunks=None, location=None):
        self.status_code = status_code
        self.headers = headers or {}
        if location:
            self.headers["Location"] = location
        self._chunks = chunks or []

    def iter_content(self, chunk_size):  # noqa: D401 - signature mirrors requests
        for chunk in self._chunks:
            yield chunk

    def close(self):
        pass


PDF_CHUNKS = [b"%PDF-1.7\n", b"body-bytes", b"%%EOF"]
HTML_CHUNKS = [b"<!DOCTYPE html><html>Access denied</html>"]

# A long, marker-free HTML article body (clears MIN_HTML_BYTES, no block markers).
_ARTICLE_BODY = (
    b"<!DOCTYPE html><html><head><title>An Engineering Paper</title></head><body>"
    + b"<h1>Introduction</h1><p>" + (b"This is the article body text. " * 200)
    + b"</p><h2>Future Work</h2><p>We will extend the controller.</p></body></html>"
)
HTML_ARTICLE_CHUNKS = [_ARTICLE_BODY[i:i + 64] for i in range(0, len(_ARTICLE_BODY), 64)]

# A paywall/login stub: long enough to pass the length floor, but a block marker
# sits in the head window so it must be rejected.
_STUB_BODY = (
    b"<!DOCTYPE html><html><head><title>Sign in</title></head><body>"
    + b"Please sign in to view this article. " + (b"padding text. " * 200)
    + b"</body></html>"
)
HTML_STUB_CHUNKS = [_STUB_BODY[i:i + 64] for i in range(0, len(_STUB_BODY), 64)]


class TestHelpers(unittest.TestCase):

    def test_slugify_has_no_path_separators(self):
        slug = download_pdf._slugify("Foo/Bar\\..\\Baz Qux!")
        self.assertNotIn("/", slug)
        self.assertNotIn("\\", slug)
        self.assertNotIn("..", slug)

    def test_slugify_empty_falls_back(self):
        self.assertEqual(download_pdf._slugify("   "), "ref")

    def test_clean_doi_strips_prefixes(self):
        self.assertEqual(download_pdf._clean_doi("https://doi.org/10.1/x"), "10.1/x")
        self.assertEqual(download_pdf._clean_doi("DOI:10.2/y"), "10.2/y")

    def test_target_filename_prefers_citekey(self):
        name = download_pdf.target_filename({"citekey": "Smith2024", "author": "A", "year": "2024"})
        self.assertEqual(name, "smith2024.pdf")

    def test_target_filename_fallback(self):
        name = download_pdf.target_filename({"author": "Dupont", "year": "2020", "title": "Deep Control"})
        self.assertEqual(name, "dupont_2020_deep_control.pdf")


class TestBibParsing(unittest.TestCase):

    SAMPLE = (
        "@article{Smith2024,\n"
        "  author = {Smith, John and Doe, Jane},\n"
        "  title = {A Great Paper},\n"
        "  year = {2024},\n"
        "  doi = {10.1109/TRO.2024.1}\n"
        "}\n\n"
        "@inproceedings{NoDoi2023,\n"
        "  author = {Lee, Kim},\n"
        "  title = {No DOI Here},\n"
        "  year = {2023}\n"
        "}\n"
    )

    def test_extract_only_keeps_doi_entries(self):
        with tempfile.TemporaryDirectory() as tmp:
            bib = os.path.join(tmp, "refs.bib")
            Path(bib).write_text(self.SAMPLE, encoding="utf-8")
            entries = download_pdf.extract_bib_entries(bib)
        self.assertEqual(len(entries), 1)
        e = entries[0]
        self.assertEqual(e["citekey"], "Smith2024")
        self.assertEqual(e["doi"], "10.1109/TRO.2024.1")
        self.assertEqual(e["author"], "Smith")
        self.assertEqual(e["year"], "2024")

    def test_find_bib_from_latex(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "assets").mkdir()
            bib = Path(tmp) / "assets" / "references.bib"
            bib.write_text("@article{a, doi={10.1/x}}", encoding="utf-8")
            tex = Path(tmp) / "main.tex"
            tex.write_text(r"\bibliography{assets/references}", encoding="utf-8")
            found = download_pdf.find_bib_from_latex(str(tex))
        self.assertEqual(os.path.normpath(found), os.path.normpath(str(bib)))

    def test_resolve_out_dir_from_latex(self):
        with tempfile.TemporaryDirectory() as tmp:
            tex = os.path.join(tmp, "main.tex")
            Path(tex).write_text("x", encoding="utf-8")
            out = download_pdf.resolve_out_dir(None, tex)
        self.assertEqual(os.path.basename(out), "refs")
        self.assertEqual(os.path.dirname(out), os.path.abspath(tmp))


class TestWriteValidated(unittest.TestCase):

    def test_accepts_real_pdf(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = os.path.join(tmp, "ok.pdf")
            resp = FakeResponse(headers={"Content-Type": "application/pdf"}, chunks=PDF_CHUNKS)
            ok = download_pdf._write_validated(resp, dest)
        self.assertTrue(ok)

    def test_rejects_html_as_pdf(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = os.path.join(tmp, "bad.pdf")
            resp = FakeResponse(headers={"Content-Type": "text/html"}, chunks=HTML_CHUNKS)
            ok = download_pdf._write_validated(resp, dest)
            self.assertFalse(ok)
            self.assertFalse(os.path.exists(dest))
            self.assertFalse(os.path.exists(dest + ".part"))

    def test_size_cap_aborts(self):
        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch.object(download_pdf, "MAX_PDF_BYTES", 5):
            dest = os.path.join(tmp, "big.pdf")
            resp = FakeResponse(headers={"Content-Type": "application/pdf"},
                                chunks=[b"%PDF-1.7", b"xxxxxxxxxx"])
            ok = download_pdf._write_validated(resp, dest)
            self.assertFalse(ok)
            self.assertFalse(os.path.exists(dest))


class TestFetchPdf(unittest.TestCase):

    def test_refuses_non_https(self):
        with tempfile.TemporaryDirectory() as tmp:
            ok = download_pdf._fetch_pdf("http://x/y.pdf", os.path.join(tmp, "f.pdf"))
        self.assertFalse(ok)

    def test_follows_redirect_to_pdf(self):
        seq = [
            FakeResponse(status_code=302, location="https://final/y.pdf"),
            FakeResponse(status_code=200, headers={"Content-Type": "application/pdf"}, chunks=PDF_CHUNKS),
        ]
        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch.object(download_pdf.requests, "get", side_effect=seq) as g:
            ok = download_pdf._fetch_pdf("https://start/x.pdf", os.path.join(tmp, "f.pdf"))
        self.assertTrue(ok)
        self.assertEqual(g.call_count, 2)


class TestDownloadOne(unittest.TestCase):

    ENTRY = {"citekey": "Smith2024", "doi": "10.1/x", "author": "Smith", "year": "2024"}

    def test_skip_when_present(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(os.path.join(tmp, "smith2024.pdf")).write_bytes(b"%PDF-1.7 already")
            with mock.patch.object(download_pdf, "try_elsevier") as els, \
                 mock.patch.object(download_pdf, "try_semantic_scholar") as s2f:
                res = download_pdf.download_one(self.ENTRY, tmp, "KEY", None)
        self.assertEqual(res["status"], "present")
        els.assert_not_called()
        s2f.assert_not_called()

    def test_elsevier_first_short_circuits_s2(self):
        with tempfile.TemporaryDirectory() as tmp:
            def fake_elsevier(doi, dest, key, tok):
                Path(dest).write_bytes(b"%PDF-1.7 x")
                return True
            with mock.patch.object(download_pdf, "try_elsevier", side_effect=fake_elsevier), \
                 mock.patch.object(download_pdf, "try_semantic_scholar") as s2f:
                res = download_pdf.download_one(self.ENTRY, tmp, "KEY", None)
        self.assertEqual(res["status"], "elsevier")
        s2f.assert_not_called()

    def test_falls_back_to_semantic_scholar(self):
        with tempfile.TemporaryDirectory() as tmp:
            def fake_s2(doi, dest):
                Path(dest).write_bytes(b"%PDF-1.7 x")
                return True
            with mock.patch.object(download_pdf, "try_elsevier", return_value=False), \
                 mock.patch.object(download_pdf, "try_semantic_scholar", side_effect=fake_s2):
                res = download_pdf.download_one(self.ENTRY, tmp, "KEY", None)
        self.assertEqual(res["status"], "semantic_scholar")

    def test_no_doi(self):
        with tempfile.TemporaryDirectory() as tmp:
            res = download_pdf.download_one({"citekey": "x", "doi": ""}, tmp, "KEY", None)
        self.assertEqual(res["status"], "no-doi")

    def test_failed_all_sources(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(download_pdf, "try_elsevier", return_value=False), \
                 mock.patch.object(download_pdf, "try_semantic_scholar", return_value=False):
                res = download_pdf.download_one(self.ENTRY, tmp, "KEY", None)
        self.assertEqual(res["status"], "failed")


class TestTargetFilename(unittest.TestCase):

    def test_extension_is_applied(self):
        entry = {"citekey": "Smith2024"}
        self.assertEqual(download_pdf.target_filename(entry, "html"), "smith2024.html")
        self.assertEqual(download_pdf.target_filename(entry, "md"), "smith2024.md")
        self.assertEqual(download_pdf.target_filename(entry), "smith2024.pdf")

    def test_extension_normalized(self):
        entry = {"citekey": "Smith2024"}
        self.assertEqual(download_pdf.target_filename(entry, ".HTML"), "smith2024.html")


class TestWriteValidatedHtml(unittest.TestCase):

    def test_accepts_article_html(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = os.path.join(tmp, "ok.html")
            resp = FakeResponse(headers={"Content-Type": "text/html; charset=utf-8"},
                                chunks=HTML_ARTICLE_CHUNKS)
            ok = download_pdf._write_validated_html(resp, dest)
        self.assertTrue(ok)

    def test_rejects_non_html_content_type(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = os.path.join(tmp, "bad.html")
            resp = FakeResponse(headers={"Content-Type": "application/json"},
                                chunks=HTML_ARTICLE_CHUNKS)
            ok = download_pdf._write_validated_html(resp, dest)
            self.assertFalse(ok)
            self.assertFalse(os.path.exists(dest))

    def test_rejects_paywall_stub_marker(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = os.path.join(tmp, "stub.html")
            resp = FakeResponse(headers={"Content-Type": "text/html"}, chunks=HTML_STUB_CHUNKS)
            ok = download_pdf._write_validated_html(resp, dest)
            self.assertFalse(ok)
            self.assertFalse(os.path.exists(dest))

    def test_rejects_too_thin(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = os.path.join(tmp, "thin.html")
            resp = FakeResponse(headers={"Content-Type": "text/html"},
                                chunks=[b"<html>tiny</html>"])
            ok = download_pdf._write_validated_html(resp, dest)
            self.assertFalse(ok)

    def test_size_cap_aborts(self):
        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch.object(download_pdf, "MAX_HTML_BYTES", 50):
            dest = os.path.join(tmp, "big.html")
            resp = FakeResponse(headers={"Content-Type": "text/html"},
                                chunks=[b"<html>", b"x" * 100])
            ok = download_pdf._write_validated_html(resp, dest)
            self.assertFalse(ok)
            self.assertFalse(os.path.exists(dest))


class TestFetchHtml(unittest.TestCase):

    def test_refuses_non_https(self):
        with tempfile.TemporaryDirectory() as tmp:
            ok = download_pdf._fetch_html("http://x/y", os.path.join(tmp, "f.html"))
        self.assertFalse(ok)

    def test_follows_redirect_to_html(self):
        seq = [
            FakeResponse(status_code=302, location="https://final/article"),
            FakeResponse(status_code=200, headers={"Content-Type": "text/html"},
                         chunks=HTML_ARTICLE_CHUNKS),
        ]
        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch.object(download_pdf.requests, "get", side_effect=seq) as g:
            ok = download_pdf._fetch_html("https://start/x", os.path.join(tmp, "f.html"))
        self.assertTrue(ok)
        self.assertEqual(g.call_count, 2)


class TestAnyFormatTiers(unittest.TestCase):

    ENTRY = {"citekey": "Smith2024", "doi": "10.1/x"}

    def test_unpaywall_pdf_first(self):
        with tempfile.TemporaryDirectory() as tmp:
            def fake_pdf(url, dest):
                Path(dest).write_bytes(b"%PDF-1.7 x")
                return True
            with mock.patch.object(download_pdf, "_http_json",
                                   return_value={"best_oa_location": {"url_for_pdf": "https://h/p.pdf"}}), \
                 mock.patch.object(download_pdf, "_fetch_pdf", side_effect=fake_pdf):
                res = download_pdf.try_unpaywall("10.1/x", tmp, self.ENTRY, "a@b.ca", True)
        self.assertEqual(res["format"], "pdf")
        self.assertEqual(res["source"], "unpaywall")

    def test_unpaywall_html_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            def fake_html(url, dest):
                Path(dest).write_text("<html>article</html>", encoding="utf-8")
                return True
            with mock.patch.object(download_pdf, "_http_json",
                                   return_value={"best_oa_location": {"url": "https://h/landing"}}), \
                 mock.patch.object(download_pdf, "_fetch_html", side_effect=fake_html):
                res = download_pdf.try_unpaywall("10.1/x", tmp, self.ENTRY, "a@b.ca", True)
        self.assertEqual(res["format"], "html")

    def test_unpaywall_skipped_without_email(self):
        with tempfile.TemporaryDirectory() as tmp:
            res = download_pdf.try_unpaywall("10.1/x", tmp, self.ENTRY, None, True)
        self.assertIsNone(res)

    def test_arxiv_pdf(self):
        with tempfile.TemporaryDirectory() as tmp:
            def fake_pdf(url, dest):
                Path(dest).write_bytes(b"%PDF-1.7 x")
                return True
            with mock.patch.object(download_pdf, "_fetch_pdf", side_effect=fake_pdf):
                res = download_pdf.try_arxiv("10.1/x", tmp, self.ENTRY,
                                             {"ArXiv": "2401.00001"}, True)
        self.assertEqual(res["format"], "pdf")
        self.assertEqual(res["source"], "arxiv")

    def test_arxiv_skipped_without_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            res = download_pdf.try_arxiv("10.1/x", tmp, self.ENTRY, {}, True)
        self.assertIsNone(res)

    def test_pmc_html(self):
        with tempfile.TemporaryDirectory() as tmp:
            def fake_html(url, dest):
                Path(dest).write_text("<html>article</html>", encoding="utf-8")
                return True
            with mock.patch.object(download_pdf, "_fetch_html", side_effect=fake_html):
                res = download_pdf.try_pmc("10.1/x", tmp, self.ENTRY,
                                           {"PubMedCentral": "123456"}, True)
        self.assertEqual(res["format"], "html")
        self.assertEqual(res["source"], "pmc")

    def test_html_tiers_skipped_when_disallowed(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(download_pdf.try_pmc("10.1/x", tmp, self.ENTRY,
                                                   {"PubMedCentral": "123456"}, False))
            self.assertIsNone(download_pdf.try_landing_html("10.1/x", tmp, self.ENTRY, False))


class TestDownloadOneTiers(unittest.TestCase):

    ENTRY = {"citekey": "Smith2024", "doi": "10.1/x"}

    def test_unpaywall_tier_when_pdf_sources_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            def fake_unpaywall(doi, out_dir, entry, email, allow_html):
                Path(os.path.join(out_dir, "smith2024.html")).write_text("<html>x</html>", encoding="utf-8")
                return {"format": "html", "source": "unpaywall", "file": "smith2024.html"}
            with mock.patch.object(download_pdf, "try_elsevier", return_value=False), \
                 mock.patch.object(download_pdf, "try_semantic_scholar", return_value=False), \
                 mock.patch.object(download_pdf, "try_publisher_pdf", return_value=False), \
                 mock.patch.object(download_pdf, "try_unpaywall", side_effect=fake_unpaywall):
                res = download_pdf.download_one(self.ENTRY, tmp, "KEY", None, email="a@b.ca")
        self.assertEqual(res["status"], "unpaywall")
        self.assertEqual(res["format"], "html")
        self.assertEqual(res["tier"], 4)

    def test_publisher_tier_mdpi_pdf_url(self):
        """MDPI landing URL is reconstructed to <landing>/pdf and fetched with
        browser headers; validates the anti-bot bypass path (no network: both
        requests.get and _fetch_pdf are patched)."""
        seen = {}

        class FakeResponse:
            url = "https://www.mdpi.com/2411-9660/9/5/122"
            headers = {"Content-Type": "text/html"}
            text = "<html><body>article</body></html>"

        def fake_fetch_pdf(url, dest, headers=None):
            seen["url"] = url
            seen["ua"] = (headers or {}).get("User-Agent", "")
            Path(dest).write_bytes(b"%PDF-1.4 fake")
            return True

        with tempfile.TemporaryDirectory() as tmp:
            dest = os.path.join(tmp, "smith2024.pdf")
            # Pin the requests fallback path (curl_cffi tier tested separately).
            with mock.patch.object(download_pdf, "_CFFI_OK", False), \
                 mock.patch.object(download_pdf.requests, "get", return_value=FakeResponse()), \
                 mock.patch.object(download_pdf, "_fetch_pdf", side_effect=fake_fetch_pdf):
                ok = download_pdf.try_publisher_pdf("10.3390/designs9050122", dest)
        self.assertTrue(ok)
        self.assertEqual(seen["url"], "https://www.mdpi.com/2411-9660/9/5/122/pdf")
        self.assertIn("Chrome", seen["ua"])

    def test_publisher_tier_citation_pdf_meta(self):
        """Generic path: the citation_pdf_url meta tag on the landing page gives
        the direct PDF URL for non-MDPI publishers."""
        seen = {}

        class FakeResponse:
            url = "https://link.springer.com/article/10.1007/x"
            headers = {"Content-Type": "text/html"}
            text = ('<html><head><meta name="citation_pdf_url" '
                    'content="https://link.springer.com/content/pdf/10.1007/x.pdf">'
                    "</head></html>")

        def fake_fetch_pdf(url, dest, headers=None):
            seen["url"] = url
            Path(dest).write_bytes(b"%PDF-1.4 fake")
            return True

        with tempfile.TemporaryDirectory() as tmp:
            dest = os.path.join(tmp, "smith2024.pdf")
            with mock.patch.object(download_pdf, "_CFFI_OK", False), \
                 mock.patch.object(download_pdf.requests, "get", return_value=FakeResponse()), \
                 mock.patch.object(download_pdf, "_fetch_pdf", side_effect=fake_fetch_pdf):
                ok = download_pdf.try_publisher_pdf("10.1007/x", dest)
        self.assertTrue(ok)
        self.assertEqual(seen["url"], "https://link.springer.com/content/pdf/10.1007/x.pdf")

    def test_akamai_interstitial_solver(self):
        """The bm-verify PoW is parsed and posted to /_sec/verify; a 200 there
        means the session cookie is cleared for the retry."""
        challenge = ('<html><script> var i = 1000; '
                     'var j = i + Number("2501" + "60305"); </script>'
                     'xhr.open("POST", "/_sec/verify?provider=interstitial");'
                     'xhr.send(JSON.stringify({"bm-verify": "TOKEN123", "pow": j}));</html>')
        posted = {}

        class FakeSession:
            def post(self, url, json=None, headers=None, timeout=None):
                posted.update(url=url, json=json)
                return mock.Mock(status_code=200)

        resp = mock.Mock(text=challenge)
        ok = download_pdf._solve_akamai_interstitial(
            FakeSession(), resp, "https://www.mdpi.com")
        self.assertTrue(ok)
        self.assertIn("/_sec/verify", posted["url"])
        self.assertEqual(posted["json"]["bm-verify"], "TOKEN123")
        self.assertEqual(posted["json"]["pow"], 1000 + 250160305)

    def test_akamai_solver_noop_without_challenge(self):
        """A normal page (no bm-verify) is not treated as a challenge."""
        resp = mock.Mock(text="<html>real article</html>")
        self.assertFalse(download_pdf._solve_akamai_interstitial(
            mock.Mock(), resp, "https://host"))

    def test_cffi_get_pdf_disabled_when_lib_absent(self):
        """With curl_cffi unavailable the tier degrades to False, never raises."""
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(download_pdf, "_CFFI_OK", False):
                self.assertFalse(download_pdf._cffi_get_pdf(
                    "https://host/x.pdf", os.path.join(tmp, "x.pdf"), "https://host/x"))

    def test_curl_fallback_rejects_non_pdf(self):
        """The curl fallback never keeps a payload that fails the %PDF magic
        check (an HTML error page must be deleted, not stored as .pdf)."""
        with tempfile.TemporaryDirectory() as tmp:
            dest = os.path.join(tmp, "x.pdf")

            def fake_run(cmd, capture_output, timeout):
                Path(dest).write_bytes(b"<html>blocked</html>")
                return mock.Mock(returncode=0)

            with mock.patch("subprocess.run", side_effect=fake_run):
                ok = download_pdf._curl_pdf_fallback("https://host/x.pdf", dest)
        self.assertFalse(ok)
        self.assertFalse(os.path.exists(dest))

    def test_present_detects_html(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(os.path.join(tmp, "smith2024.html")).write_text("<html>x</html>", encoding="utf-8")
            res = download_pdf.download_one(self.ENTRY, tmp, "KEY", None)
        self.assertEqual(res["status"], "present")
        self.assertEqual(res["format"], "html")

    def test_failed_when_all_tiers_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(download_pdf, "try_elsevier", return_value=False), \
                 mock.patch.object(download_pdf, "try_semantic_scholar", return_value=False), \
                 mock.patch.object(download_pdf, "try_unpaywall", return_value=None), \
                 mock.patch.object(download_pdf, "try_arxiv", return_value=None), \
                 mock.patch.object(download_pdf, "try_pmc", return_value=None), \
                 mock.patch.object(download_pdf, "try_landing_html", return_value=None):
                res = download_pdf.download_one(self.ENTRY, tmp, "KEY", None, email="a@b.ca")
        self.assertEqual(res["status"], "failed")
        self.assertIsNone(res["format"])


class TestReports(unittest.TestCase):

    def test_manifest_and_failed_written(self):
        results = [
            {"citekey": "A", "doi": "10.1/a", "file": "a.pdf", "source": "elsevier", "status": "elsevier"},
            {"citekey": "B", "doi": "10.1/b", "file": "b.pdf", "source": None, "status": "failed"},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            download_pdf.write_manifest(tmp, results)
            download_pdf.write_failed(tmp, results)
            manifest = json.loads(Path(os.path.join(tmp, "_manifest.json")).read_text(encoding="utf-8"))
            failed = Path(os.path.join(tmp, "_failed.md")).read_text(encoding="utf-8")
        self.assertIn("A", manifest)
        self.assertIn("B", manifest)
        self.assertIn("https://doi.org/10.1/b", failed)
        self.assertNotIn("10.1/a", failed)


class TestBrowserTier(unittest.TestCase):
    """Tier 8 wiring: skip rules, invocation, and override forwarding.
    browser_fetch is replaced by a mock so no real browser is launched."""

    ENTRY = {"citekey": "cong2022firework", "doi": "10.1115/1.4056572",
             "author": "Cong", "year": "2022", "title": "firework"}

    def _lower_tiers_fail(self):
        """Context managers forcing tiers 1-7 (and the S2 id lookup) to yield
        nothing, so control reaches tier 8."""
        return [
            mock.patch.object(download_pdf, "try_elsevier", return_value=False),
            mock.patch.object(download_pdf, "try_semantic_scholar", return_value=False),
            mock.patch.object(download_pdf, "try_publisher_pdf", return_value=False),
            mock.patch.object(download_pdf, "try_unpaywall", return_value=None),
            mock.patch.object(download_pdf, "try_arxiv", return_value=None),
            mock.patch.object(download_pdf, "try_pmc", return_value=None),
            mock.patch.object(download_pdf, "try_landing_html", return_value=None),
            mock.patch.object(download_pdf, "s2", None),
        ]

    def _run(self, fake_bf, **kwargs):
        with contextlib.ExitStack() as stack, tempfile.TemporaryDirectory() as tmp:
            for cm in self._lower_tiers_fail():
                stack.enter_context(cm)
            stack.enter_context(mock.patch.object(download_pdf, "browser_fetch", fake_bf))
            return download_pdf.download_one(self.ENTRY, tmp, "KEY", None, **kwargs)

    def test_tier8_skipped_when_browser_disabled(self):
        fake_bf = mock.Mock()
        fake_bf.browser_available.return_value = True
        res = self._run(fake_bf, use_browser=False)
        self.assertEqual(res["status"], "failed")
        fake_bf.fetch_pdf_via_browser.assert_not_called()

    def test_tier8_skipped_when_unavailable(self):
        fake_bf = mock.Mock()
        fake_bf.browser_available.return_value = False
        res = self._run(fake_bf, use_browser=True)
        self.assertEqual(res["status"], "failed")
        fake_bf.fetch_pdf_via_browser.assert_not_called()

    def test_tier8_invoked_returns_browser(self):
        def fake_fetch(doi, dest, override_url=None, headed=True):
            Path(dest).write_bytes(b"%PDF-1.7 x")
            return {"format": "pdf", "source": "browser", "file": os.path.basename(dest)}
        fake_bf = mock.Mock()
        fake_bf.browser_available.return_value = True
        fake_bf.fetch_pdf_via_browser.side_effect = fake_fetch
        res = self._run(fake_bf, use_browser=True)
        self.assertEqual(res["status"], "browser")
        self.assertEqual(res["tier"], 8)
        self.assertEqual(res["format"], "pdf")

    def test_tier8_override_forwarded_and_marked(self):
        captured = {}
        def fake_fetch(doi, dest, override_url=None, headed=True):
            captured["override_url"] = override_url
            Path(dest).write_bytes(b"%PDF-1.7 x")
            return {"format": "pdf", "source": "override", "file": os.path.basename(dest)}
        fake_bf = mock.Mock()
        fake_bf.browser_available.return_value = True
        fake_bf.fetch_pdf_via_browser.side_effect = fake_fetch
        url = "https://www.researchgate.net/publication/366555290_x"
        res = self._run(fake_bf, use_browser=True, override_url=url)
        self.assertEqual(captured["override_url"], url)
        self.assertEqual(res["status"], "override")
        self.assertEqual(res["tier"], 8)


class TestLoadSources(unittest.TestCase):

    def test_missing_file_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(download_pdf._load_sources(tmp), {})

    def test_object_and_string_forms(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = {
                "a": {"url": "https://x/a.pdf", "note": "n"},
                "b": "https://y/b.pdf",
            }
            Path(os.path.join(tmp, "_sources.json")).write_text(
                json.dumps(data), encoding="utf-8")
            self.assertEqual(download_pdf._load_sources(tmp),
                             {"a": "https://x/a.pdf", "b": "https://y/b.pdf"})

    def test_non_https_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(os.path.join(tmp, "_sources.json")).write_text(
                json.dumps({"a": "http://x/a.pdf"}), encoding="utf-8")
            self.assertEqual(download_pdf._load_sources(tmp), {})

    def test_malformed_json_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(os.path.join(tmp, "_sources.json")).write_text(
                "{ not valid json", encoding="utf-8")
            self.assertEqual(download_pdf._load_sources(tmp), {})


if __name__ == "__main__":
    unittest.main()
