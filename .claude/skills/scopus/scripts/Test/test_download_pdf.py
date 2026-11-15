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
import io
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

    def _token_seen(self, env, passed):
        """The token download_one hands to the Elsevier rung, for one environment."""
        seen = {}

        def fake_elsevier(doi, dest, key, tok):
            seen["tok"] = tok
            return False
        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch.dict(os.environ, env), \
             mock.patch.object(download_pdf, "try_elsevier", side_effect=fake_elsevier), \
             mock.patch.object(download_pdf, "try_semantic_scholar", return_value=False), \
             mock.patch.object(download_pdf, "try_publisher_pdf", return_value=False), \
             mock.patch.object(download_pdf, "try_unpaywall", return_value=None), \
             mock.patch.object(download_pdf, "try_arxiv", return_value=None), \
             mock.patch.object(download_pdf, "try_pmc", return_value=None), \
             mock.patch.object(download_pdf, "try_landing_html", return_value=None), \
             mock.patch.object(download_pdf, "s2", None):
            download_pdf.download_one(self.ENTRY, tmp, "KEY", passed)
        return seen.get("tok")

    def test_the_token_comes_from_the_environment_for_a_caller_that_passes_none(self):
        # Review round 1: extract_text.py and extract_locations.py call download_one
        # with the raw flag value, so the environment token never reached rung 1.
        self.assertEqual(self._token_seen({download_pdf.INSTTOKEN_ENV: "TOKEN-FIXTURE"}, None),
                         "TOKEN-FIXTURE")

    def test_an_explicit_token_beats_the_environment(self):
        self.assertEqual(self._token_seen({download_pdf.INSTTOKEN_ENV: "FROM-ENV"}, "FROM-FLAG"),
                         "FROM-FLAG")

    def test_no_token_anywhere_stays_none(self):
        with mock.patch.dict(os.environ):
            os.environ.pop(download_pdf.INSTTOKEN_ENV, None)
            self.assertIsNone(self._token_seen({}, None))

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
            download_pdf.write_failed(tmp)
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


class ManifestMergeTest(unittest.TestCase):
    """write_manifest must never lose an entry it did not write.

    Measured 2026-09-12 on the BuildingGIS corpus: the `doi` subcommand carries
    one result per call, and twelve successive calls took _manifest.json from
    more than sixty entries to one. The files stayed on disk; which tier had
    fetched each of them did not.
    """

    def test_previous_entries_survive_a_single_doi_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "_manifest.json")
            with open(path, "w", encoding="utf-8") as fh:
                json.dump({"old1": {"citekey": "old1", "tier": 1},
                           "old2": {"citekey": "old2", "tier": 3}}, fh)
            download_pdf.write_manifest(tmp, [{"citekey": "new1", "tier": 8}])
            with open(path, encoding="utf-8") as fh:
                got = json.load(fh)
        self.assertEqual(set(got), {"old1", "old2", "new1"})
        self.assertEqual(got["old2"]["tier"], 3)

    def test_a_rerun_of_the_same_key_replaces_only_that_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "_manifest.json")
            with open(path, "w", encoding="utf-8") as fh:
                json.dump({"a": {"citekey": "a", "status": "failed"},
                           "b": {"citekey": "b", "status": "elsevier"}}, fh)
            download_pdf.write_manifest(tmp, [{"citekey": "a", "status": "browser"}])
            with open(path, encoding="utf-8") as fh:
                got = json.load(fh)
        self.assertEqual(got["a"]["status"], "browser")
        self.assertEqual(got["b"]["status"], "elsevier")

    def test_the_previous_manifest_is_kept_as_a_backup(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "_manifest.json")
            with open(path, "w", encoding="utf-8") as fh:
                json.dump({"old": {"citekey": "old"}}, fh)
            download_pdf.write_manifest(tmp, [{"citekey": "new"}])
            backup = os.path.join(tmp, "_manifest.bak.json")
            self.assertTrue(os.path.exists(backup))
            with open(backup, encoding="utf-8") as fh:
                self.assertEqual(set(json.load(fh)), {"old"})

    def test_an_unreadable_manifest_is_backed_up_not_discarded(self):
        # A corrupt manifest may still be the only record of how a corpus was
        # retrieved, so it is preserved rather than overwritten in silence.
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "_manifest.json")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("{ this is not json")
            download_pdf.write_manifest(tmp, [{"citekey": "new"}])
            with open(os.path.join(tmp, "_manifest.bak.json"), encoding="utf-8") as fh:
                self.assertIn("not json", fh.read())
            with open(path, encoding="utf-8") as fh:
                self.assertEqual(set(json.load(fh)), {"new"})

    def test_no_previous_file_still_writes_this_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            download_pdf.write_manifest(tmp, [{"citekey": "only"}])
            with open(os.path.join(tmp, "_manifest.json"), encoding="utf-8") as fh:
                self.assertEqual(set(json.load(fh)), {"only"})
            self.assertFalse(os.path.exists(os.path.join(tmp, "_manifest.bak.json")))


def _pdf_bytes(pages: int) -> bytes:
    """Minimal PDF carrying `pages` /Type /Page objects."""
    body = b"".join(b"%d 0 obj\n<< /Type /Page >>\nendobj\n" % (i + 3)
                    for i in range(pages))
    return b"%PDF-1.4\n" + body + b"trailer\n<< /Root 1 0 R >>\n%%EOF\n"


class PaywallPreviewTest(unittest.TestCase):
    """A one-page publisher preview must not be accepted as a full text.

    Measured 2026-09-12: api.elsevier.com answers HTTP 200 with a ONE-page PDF
    (title, abstract, opening of the introduction) on a DOI the entitlement does
    not cover. The bytes begin with %PDF, so every structural check passed, six
    references were archived as tier-1 successes, and accepting them ended the
    chain before the seven other methods were tried.
    """

    def setUp(self):
        # These fixtures encode the page count in the BYTES only: PyMuPDF does
        # not read them as real documents, so they exercise the FALLBACK path,
        # which is what they were written for in 2026-09-12. The exact
        # measurement added on 2026-09-14 has its own cases in
        # TestPreviewMeasurement, where the two disagree on purpose.
        patcher = mock.patch.object(download_pdf, "pdf_measure", return_value=None)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _write(self, tmp, name, data):
        path = os.path.join(tmp, name)
        with open(path, "wb") as fh:
            fh.write(data)
        return path

    def test_a_one_page_pdf_is_a_preview(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(tmp, "p.pdf", _pdf_bytes(1))
            preview, reason = download_pdf.is_paywall_preview(path)
        self.assertTrue(preview)
        self.assertIn("1 page", reason)

    def test_a_two_page_paper_is_not_a_preview(self):
        # Negative control with teeth: wu2021leafmap, in this very corpus, is a
        # genuine two-page SIGSPATIAL workshop paper. A threshold of two pages
        # would trade one wrong answer for another.
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(tmp, "p.pdf", _pdf_bytes(2))
            preview, _ = download_pdf.is_paywall_preview(path)
        self.assertFalse(preview)

    def test_a_long_paper_is_not_a_preview(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(tmp, "p.pdf", _pdf_bytes(15))
            preview, _ = download_pdf.is_paywall_preview(path)
        self.assertFalse(preview)

    def test_an_unmeasurable_pdf_is_never_rejected(self):
        # R11 / R8: a failed measurement must not throw away a good file. An
        # unknown page count is unknown, not a preview.
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(tmp, "p.pdf", b"%PDF-1.4\nno page objects here\n")
            preview, _ = download_pdf.is_paywall_preview(path)
        self.assertFalse(preview)
        self.assertIsNone(download_pdf.pdf_page_count(os.path.join(tmp, "absent.pdf")))

    def test_rejecting_a_preview_deletes_it_so_the_next_tier_starts_clean(self):
        # The file must go: otherwise the presence gate would later mistake the
        # preview for a retrieved full text and skip the reference entirely.
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(tmp, "p.pdf", _pdf_bytes(1))
            self.assertTrue(download_pdf._reject_preview(path, "Elsevier"))
            self.assertFalse(os.path.exists(path))

    def test_a_real_paper_is_kept_by_the_rejection_helper(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(tmp, "p.pdf", _pdf_bytes(12))
            self.assertFalse(download_pdf._reject_preview(path, "Elsevier"))
            self.assertTrue(os.path.exists(path))

    def test_a_missing_file_is_not_reported_as_a_preview(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertFalse(download_pdf._reject_preview(
                os.path.join(tmp, "nope.pdf"), "Elsevier"))


class BrowserTierSilenceTest(unittest.TestCase):
    """An unavailable tier must say so.

    `--browser` with no playwright package printed nothing at all, so the log
    of a failed retrieval looked identical whether tier 8 had been tried or had
    never existed.
    """

    def _source(self):
        path = os.path.join(os.path.dirname(os.path.abspath(download_pdf.__file__)),
                            "download_pdf.py")
        with open(path, encoding="utf-8") as fh:
            return fh.read()

    def test_every_browser_skip_reason_is_logged(self):
        src = self._source()
        self.assertIn("tier 8 (browser) disabled by --no-browser", src)
        self.assertIn("the playwright package", src)
        self.assertNotIn("no Chromium build was found", src)

    def test_the_unavailable_branches_name_the_remedy(self):
        src = self._source()
        self.assertIn("pip install playwright", src)
        self.assertIn("playwright install chrome", src)

    def test_the_browser_tier_is_also_preview_gated(self):
        # A browser can land on a preview too; the gate is on the artifact, not
        # on the tier that produced it. Behavioural since 2026-11-05: the former
        # source-text check pinned a call spelling the attempts refactor replaced.
        def fake_fetch(doi, dest, override_url=None, headed=True):
            Path(dest).write_bytes(b"%PDF-1.7 x")
            return {"format": "pdf", "source": "browser", "file": os.path.basename(dest)}
        fake_bf = mock.Mock()
        fake_bf.browser_available.return_value = True
        fake_bf.fetch_pdf_via_browser.side_effect = fake_fetch
        tier = TestBrowserTier()
        with mock.patch.object(download_pdf, "is_paywall_preview",
                               return_value=(True, "1 page(s) - publisher preview")):
            res = tier._run(fake_bf, use_browser=True)
        self.assertEqual(res["status"], "failed")
        browser = [a for a in res["attempts"] if a["name"] == "browser"][0]
        self.assertEqual(browser["outcome"], "preview")


class TestPreviewMeasurement(unittest.TestCase):
    """The preview guard has to measure, not guess.

    Measured 2026-09-14 on the live BuildingGIS corpus: pdf_page_count answered
    10, 14, 15 and 30 pages for four documents PyMuPDF reads as exactly ONE page
    carrying about five thousand characters. An Elsevier preview embeds the page
    skeleton of the whole article while rendering its first page, so four of the
    eight previews in that corpus passed the 2026-09-12 guard and were archived
    as `status: elsevier, tier: 1` full texts.
    """

    def test_an_overcounted_preview_is_still_rejected(self):
        # The defect, reproduced: the byte heuristic says many pages, the exact
        # measurement says one.
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "big.pdf")
            Path(path).write_bytes(b"%PDF-1.7\n" + b"/Type /Page " * 14)
            with mock.patch.object(download_pdf, "pdf_measure", return_value=(1, 4829)):
                preview, reason = download_pdf.is_paywall_preview(path)
        self.assertTrue(preview)
        self.assertIn("4829 characters", reason)

    def test_a_genuine_short_paper_is_kept(self):
        # The negative control, taken from the same corpus: wu2021leafmap is a
        # real two-page SIGSPATIAL paper of 8925 characters. Rejecting it would
        # trade one wrong answer for another.
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "short.pdf")
            Path(path).write_bytes(b"%PDF-1.7\n")
            with mock.patch.object(download_pdf, "pdf_measure", return_value=(2, 8925)):
                preview, _ = download_pdf.is_paywall_preview(path)
        self.assertFalse(preview)

    def test_two_pages_with_no_body_are_a_preview(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "thin.pdf")
            Path(path).write_bytes(b"%PDF-1.7\n")
            with mock.patch.object(download_pdf, "pdf_measure", return_value=(2, 1200)):
                preview, reason = download_pdf.is_paywall_preview(path)
        self.assertTrue(preview)
        self.assertIn("only 1200 characters", reason)

    def test_a_real_article_is_kept(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "full.pdf")
            Path(path).write_bytes(b"%PDF-1.7\n")
            with mock.patch.object(download_pdf, "pdf_measure", return_value=(19, 84622)):
                preview, _ = download_pdf.is_paywall_preview(path)
        self.assertFalse(preview)

    def test_without_pymupdf_the_byte_heuristic_still_guards(self):
        # Degradation, not failure: the fallback can only UNDER-report a preview,
        # never invent one, and the reason says which measurement was used.
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "one.pdf")
            Path(path).write_bytes(b"%PDF-1.7\n" + b"/Type /Page ")
            with mock.patch.object(download_pdf, "pdf_measure", return_value=None):
                preview, reason = download_pdf.is_paywall_preview(path)
        self.assertTrue(preview)
        self.assertIn("raw bytes", reason)

    def test_an_unmeasurable_file_is_not_a_preview(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "odd.pdf")
            Path(path).write_bytes(b"%PDF-1.7\nno page objects here")
            with mock.patch.object(download_pdf, "pdf_measure", return_value=None):
                preview, _ = download_pdf.is_paywall_preview(path)
        self.assertFalse(preview)


class TestFailedFromManifest(unittest.TestCase):
    """_failed.md is a view of the merged manifest, not a tally of one call.

    Measured 2026-09-14: eleven `doi` calls in a row meant the last one decided,
    so a successful eleventh erased the record of seven failures and left "All
    references with a DOI were retrieved" in a corpus missing seven papers.
    """

    def test_a_later_success_does_not_erase_an_earlier_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            download_pdf.write_manifest(tmp, [
                {"citekey": "A", "doi": "10.1/a", "file": None, "status": "failed"}])
            download_pdf.write_failed(tmp)
            download_pdf.write_manifest(tmp, [
                {"citekey": "B", "doi": "10.1/b", "file": "b.pdf", "status": "elsevier"}])
            download_pdf.write_failed(tmp)
            failed = Path(os.path.join(tmp, "_failed.md")).read_text(encoding="utf-8")
        self.assertIn("https://doi.org/10.1/a", failed)
        self.assertNotIn("10.1/b", failed)

    def test_an_all_clear_is_written_only_when_nothing_failed(self):
        # The positive control: the reassuring sentence must still be reachable,
        # or the fix would simply never say all is well.
        with tempfile.TemporaryDirectory() as tmp:
            download_pdf.write_manifest(tmp, [
                {"citekey": "A", "doi": "10.1/a", "file": "a.pdf", "status": "elsevier"}])
            download_pdf.write_failed(tmp)
            failed = Path(os.path.join(tmp, "_failed.md")).read_text(encoding="utf-8")
        self.assertIn("All references", failed)

    def test_no_manifest_yields_no_false_all_clear_entry(self):
        with tempfile.TemporaryDirectory() as tmp:
            download_pdf.write_failed(tmp)
            failed = Path(os.path.join(tmp, "_failed.md")).read_text(encoding="utf-8")
        self.assertIn("All references", failed)


class TestAuditPreviews(unittest.TestCase):
    """Revisiting a refs/ the presence gate would never look at again."""

    def _corpus(self, tmp):
        Path(os.path.join(tmp, "good2020key.pdf")).write_bytes(b"%PDF-1.7\n")
        Path(os.path.join(tmp, "prev2020key.pdf")).write_bytes(b"%PDF-1.7\n")
        Path(os.path.join(tmp, "_manifest.bak.json")).write_text("{}", encoding="utf-8")
        download_pdf.write_manifest(tmp, [
            {"citekey": "good2020key", "doi": "10.1/g", "file": "good2020key.pdf",
             "status": "elsevier"},
            {"citekey": "prev2020key", "doi": "10.1/p", "file": "prev2020key.pdf",
             "status": "elsevier"}])

    @staticmethod
    def _measure(path):
        return (1, 4800) if "prev" in os.path.basename(path) else (19, 84622)

    def test_a_dry_run_reports_and_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._corpus(tmp)
            with mock.patch.object(download_pdf, "pdf_measure", self._measure):
                report = download_pdf.audit_previews(tmp)
            still_there = os.path.exists(os.path.join(tmp, "prev2020key.pdf"))
        self.assertEqual([p["citekey"] for p in report["previews"]], ["prev2020key"])
        self.assertEqual(report["checked"], 2)
        self.assertFalse(report["applied"])
        self.assertTrue(still_there)

    def test_applying_quarantines_and_records_the_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._corpus(tmp)
            with mock.patch.object(download_pdf, "pdf_measure", self._measure):
                download_pdf.audit_previews(tmp, apply=True)
            moved = os.path.exists(os.path.join(tmp, "_previews", "prev2020key.pdf"))
            gone = not os.path.exists(os.path.join(tmp, "prev2020key.pdf"))
            kept = os.path.exists(os.path.join(tmp, "good2020key.pdf"))
            manifest = json.loads(
                Path(os.path.join(tmp, "_manifest.json")).read_text(encoding="utf-8"))
            failed = Path(os.path.join(tmp, "_failed.md")).read_text(encoding="utf-8")
        self.assertTrue(moved)
        self.assertTrue(gone)
        self.assertTrue(kept)
        self.assertEqual(manifest["prev2020key"]["status"], "failed")
        self.assertEqual(manifest["good2020key"]["status"], "elsevier")
        self.assertIn("https://doi.org/10.1/p", failed)

    def test_a_paper_retrieved_by_hand_is_no_longer_reported_failed(self):
        # Found by running the audit on the live corpus: three references the
        # operator had just downloaded were still asking to be downloaded,
        # because the manual retrieval never touched the manifest.
        with tempfile.TemporaryDirectory() as tmp:
            self._corpus(tmp)
            download_pdf.write_manifest(tmp, [
                {"citekey": "good2020key", "doi": "10.1/g", "file": None,
                 "status": "failed"}])
            with mock.patch.object(download_pdf, "pdf_measure", self._measure):
                report = download_pdf.audit_previews(tmp, apply=True)
            manifest = json.loads(
                Path(os.path.join(tmp, "_manifest.json")).read_text(encoding="utf-8"))
            failed = Path(os.path.join(tmp, "_failed.md")).read_text(encoding="utf-8")
        self.assertEqual([r["citekey"] for r in report["recovered"]], ["good2020key"])
        self.assertEqual(manifest["good2020key"]["status"], "present")
        self.assertNotIn("10.1/g", failed)

    def test_a_dry_run_reconciles_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._corpus(tmp)
            download_pdf.write_manifest(tmp, [
                {"citekey": "good2020key", "doi": "10.1/g", "file": None,
                 "status": "failed"}])
            with mock.patch.object(download_pdf, "pdf_measure", self._measure):
                report = download_pdf.audit_previews(tmp)
            manifest = json.loads(
                Path(os.path.join(tmp, "_manifest.json")).read_text(encoding="utf-8"))
        self.assertEqual([r["citekey"] for r in report["recovered"]], ["good2020key"])
        self.assertEqual(manifest["good2020key"]["status"], "failed")

    def test_the_bookkeeping_files_are_not_audited(self):
        # A name starting with "_" is the corpus's own record, never a paper.
        with tempfile.TemporaryDirectory() as tmp:
            self._corpus(tmp)
            Path(os.path.join(tmp, "_notes.pdf")).write_bytes(b"%PDF-1.7\n")
            with mock.patch.object(download_pdf, "pdf_measure", self._measure):
                report = download_pdf.audit_previews(tmp)
        self.assertEqual(report["checked"], 2)


def _run_cli(argv, **patches):
    """Drive main() with a patched argv and return the captured download_one call.

    download_one, the key lookup and the manifest writers are replaced, so no
    network call happens and no file is written outside the folder given in argv.
    """
    captured = {}

    def fake_download_one(entry, out_dir, api_key, insttoken, **kwargs):
        captured["entry"] = entry
        captured["insttoken"] = insttoken
        captured["kwargs"] = kwargs
        return {"citekey": entry.get("citekey", ""), "doi": entry.get("doi", ""),
                "file": "x.pdf", "format": "pdf", "source": "elsevier", "tier": 1,
                "status": "elsevier"}

    with contextlib.ExitStack() as stack:
        stack.enter_context(mock.patch.object(sys, "argv", ["download_pdf.py", *argv]))
        stack.enter_context(mock.patch.object(
            download_pdf, "download_one", side_effect=fake_download_one))
        stack.enter_context(mock.patch.object(
            download_pdf, "_scopus_key_optional", return_value="KEY"))
        stack.enter_context(mock.patch.object(download_pdf, "write_manifest"))
        stack.enter_context(mock.patch.object(download_pdf, "write_failed"))
        for name, value in patches.items():
            stack.enter_context(mock.patch.object(download_pdf, name, value))
        with contextlib.redirect_stdout(io.StringIO()):
            download_pdf.main()
    return captured


class TestInsttokenFromEnvironment(unittest.TestCase):
    """The Elsevier institutional token may come from ELSEVIER_INSTTOKEN.

    Measured 2026-11-05: no agent passes --insttoken, so an off-campus run could
    never use the token even when the owner had one configured.
    """

    def test_helper_reads_the_environment_when_the_flag_is_absent(self):
        with mock.patch.dict(os.environ, {"ELSEVIER_INSTTOKEN": "ENVTOKEN"}):
            self.assertEqual(download_pdf._insttoken_optional(None), "ENVTOKEN")

    def test_the_flag_wins_over_the_environment(self):
        with mock.patch.dict(os.environ, {"ELSEVIER_INSTTOKEN": "ENVTOKEN"}):
            self.assertEqual(download_pdf._insttoken_optional("FLAGTOKEN"), "FLAGTOKEN")

    def test_neither_gives_none_and_blank_is_not_a_token(self):
        env = {k: v for k, v in os.environ.items() if k != "ELSEVIER_INSTTOKEN"}
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertIsNone(download_pdf._insttoken_optional(None))
        with mock.patch.dict(os.environ, {"ELSEVIER_INSTTOKEN": "   "}):
            self.assertIsNone(download_pdf._insttoken_optional(None))

    def test_doi_subcommand_passes_the_environment_token(self):
        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch.dict(os.environ, {"ELSEVIER_INSTTOKEN": "ENVTOKEN"}):
            got = _run_cli(["doi", "10.1/x", "--out-dir", tmp])
        self.assertEqual(got["insttoken"], "ENVTOKEN")

    def test_doi_subcommand_flag_beats_the_environment(self):
        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch.dict(os.environ, {"ELSEVIER_INSTTOKEN": "ENVTOKEN"}):
            got = _run_cli(["doi", "10.1/x", "--out-dir", tmp, "--insttoken", "FLAGTOKEN"])
        self.assertEqual(got["insttoken"], "FLAGTOKEN")

    def test_bib_subcommand_passes_the_environment_token(self):
        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch.dict(os.environ, {"ELSEVIER_INSTTOKEN": "ENVTOKEN"}):
            bib = os.path.join(tmp, "r.bib")
            Path(bib).write_text("@article{a2024x,\n  doi = {10.1/x},\n  title = {T}\n}\n",
                                 encoding="utf-8")
            got = _run_cli(["bib", bib, "--out-dir", tmp])
        self.assertEqual(got["insttoken"], "ENVTOKEN")

    def test_the_header_is_sent_only_when_a_token_exists(self):
        seen = {}

        def fake_fetch(url, dest, headers=None):
            seen["headers"] = headers
            return False

        with mock.patch.object(download_pdf, "_fetch_pdf", side_effect=fake_fetch):
            download_pdf.try_elsevier("10.1/x", "d.pdf", "KEY", "TOK")
            self.assertEqual(seen["headers"].get("X-ELS-Insttoken"), "TOK")
            download_pdf.try_elsevier("10.1/x", "d.pdf", "KEY", None)
            self.assertNotIn("X-ELS-Insttoken", seen["headers"])


PII = "S0736584524000206"
SD_URL = "https://www.sciencedirect.com/science/article/pii/" + PII


class TestParsePii(unittest.TestCase):
    """The `url` subcommand accepts a ScienceDirect URL or a bare PII, nothing else."""

    def test_article_url(self):
        self.assertEqual(download_pdf.parse_pii(SD_URL), PII)

    def test_abs_and_pdf_variants(self):
        for variant in ("https://www.sciencedirect.com/science/article/abs/pii/" + PII,
                        "https://www.sciencedirect.com/science/article/pii/" + PII + "/pdfft",
                        "https://www.sciencedirect.com/science/article/pii/" + PII + "?via=ihub"):
            self.assertEqual(download_pdf.parse_pii(variant), PII)

    def test_bare_pii_and_a_trailing_check_letter(self):
        self.assertEqual(download_pdf.parse_pii(PII), PII)
        self.assertEqual(download_pdf.parse_pii("S090657601200063X"), "S090657601200063X")

    def test_refuses_plain_http(self):
        with self.assertRaises(download_pdf.UrlInputError) as ctx:
            download_pdf.parse_pii("http://www.sciencedirect.com/science/article/pii/" + PII)
        self.assertIn("https", str(ctx.exception))

    def test_refuses_another_host_including_a_lookalike(self):
        for host in ("example.org", "www.sciencedirect.com.evil.example",
                     "evil.example/www.sciencedirect.com"):
            with self.assertRaises(download_pdf.UrlInputError):
                download_pdf.parse_pii("https://%s/science/article/pii/%s" % (host, PII))

    def test_refuses_a_malformed_pii(self):
        for bad in ("S07365845240002", "S0736584524000206999", "X0736584524000206",
                    "https://www.sciencedirect.com/science/article/pii/not-a-pii", "", "   "):
            with self.assertRaises(download_pdf.UrlInputError):
                download_pdf.parse_pii(bad)

    def test_refuses_a_url_that_is_not_an_article_path(self):
        with self.assertRaises(download_pdf.UrlInputError):
            download_pdf.parse_pii("https://www.sciencedirect.com/journal/" + PII)


class TestResolvePiiToDoi(unittest.TestCase):

    @staticmethod
    def _resp(status=200, payload=None):
        return mock.Mock(status_code=status, json=mock.Mock(return_value=payload),
                         text="")

    def test_reads_the_doi_from_the_metadata_view_with_key_and_token(self):
        payload = {"full-text-retrieval-response":
                   {"coredata": {"prism:doi": "10.1016/j.rcim.2024.102734"}}}
        with mock.patch.object(download_pdf.requests, "get",
                               return_value=self._resp(payload=payload)) as get:
            doi = download_pdf.resolve_pii_to_doi(PII, "KEY", "TOK")
        self.assertEqual(doi, "10.1016/j.rcim.2024.102734")
        args, kwargs = get.call_args
        self.assertIn("/content/article/pii/" + PII, args[0])
        self.assertEqual(kwargs["params"], {"view": "META"})
        self.assertEqual(kwargs["headers"]["X-ELS-APIKey"], "KEY")
        self.assertEqual(kwargs["headers"]["X-ELS-Insttoken"], "TOK")
        self.assertEqual(kwargs["timeout"], download_pdf.REQUEST_TIMEOUT_S)

    def test_no_token_header_without_a_token(self):
        payload = {"full-text-retrieval-response": {"coredata": {"prism:doi": "10.1/x"}}}
        with mock.patch.object(download_pdf.requests, "get",
                               return_value=self._resp(payload=payload)) as get:
            download_pdf.resolve_pii_to_doi(PII, "KEY", None)
        self.assertNotIn("X-ELS-Insttoken", get.call_args.kwargs["headers"])

    def test_an_answer_without_a_doi_is_refused_by_name(self):
        payload = {"full-text-retrieval-response": {"coredata": {"dc:title": "T"}}}
        with mock.patch.object(download_pdf.requests, "get",
                               return_value=self._resp(payload=payload)):
            with self.assertRaises(download_pdf.UrlInputError) as ctx:
                download_pdf.resolve_pii_to_doi(PII, "KEY", None)
        self.assertIn("DOI", str(ctx.exception))

    def test_http_error_and_network_error_and_bad_json_are_refusals(self):
        with mock.patch.object(download_pdf.requests, "get",
                               return_value=self._resp(status=404)):
            with self.assertRaises(download_pdf.UrlInputError) as ctx:
                download_pdf.resolve_pii_to_doi(PII, "KEY", None)
        self.assertIn("404", str(ctx.exception))
        with mock.patch.object(download_pdf.requests, "get",
                               side_effect=download_pdf.requests.ConnectionError("down")):
            with self.assertRaises(download_pdf.UrlInputError):
                download_pdf.resolve_pii_to_doi(PII, "KEY", None)
        broken = mock.Mock(status_code=200, json=mock.Mock(side_effect=ValueError("x")), text="")
        with mock.patch.object(download_pdf.requests, "get", return_value=broken):
            with self.assertRaises(download_pdf.UrlInputError):
                download_pdf.resolve_pii_to_doi(PII, "KEY", None)

    def test_the_key_is_never_in_the_refusal_text(self):
        with mock.patch.object(download_pdf.requests, "get",
                               return_value=self._resp(status=401)):
            with self.assertRaises(download_pdf.UrlInputError) as ctx:
                download_pdf.resolve_pii_to_doi(PII, "SECRETKEY123", "SECRETTOK456")
        self.assertNotIn("SECRETKEY123", str(ctx.exception))
        self.assertNotIn("SECRETTOK456", str(ctx.exception))


class TestUrlSubcommand(unittest.TestCase):

    def test_resolves_the_doi_then_downloads_with_the_pii_as_citekey(self):
        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch.object(download_pdf, "resolve_pii_to_doi",
                               return_value="10.1016/j.rcim.2024.102734") as res:
            got = _run_cli(["url", SD_URL, "--out-dir", tmp])
        res.assert_called_once()
        self.assertEqual(got["entry"]["doi"], "10.1016/j.rcim.2024.102734")
        self.assertEqual(got["entry"]["citekey"], PII.lower())

    def test_an_explicit_citekey_wins(self):
        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch.object(download_pdf, "resolve_pii_to_doi", return_value="10.1/x"):
            got = _run_cli(["url", PII, "--out-dir", tmp, "--citekey", "kim2024robot"])
        self.assertEqual(got["entry"]["citekey"], "kim2024robot")

    def _refusal(self, argv, **patches):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            with self.assertRaises(SystemExit) as ctx:
                _run_cli(argv, **patches)
        return ctx.exception.code, err.getvalue()

    def test_bad_input_exits_2_with_a_named_reason_and_downloads_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, err = self._refusal(["url", "http://www.sciencedirect.com/x", "--out-dir", tmp])
        self.assertEqual(code, 2)
        self.assertIn("https", err)

    def test_no_api_key_exits_2_naming_the_variable(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, err = self._refusal(["url", SD_URL, "--out-dir", tmp],
                                      _scopus_key_optional=lambda: None)
        self.assertEqual(code, 2)
        self.assertIn("SCOPUS_API_KEY", err)

    def test_a_metadata_answer_with_no_doi_exits_2(self):
        with tempfile.TemporaryDirectory() as tmp:
            def no_doi(pii, key, tok):
                raise download_pdf.UrlInputError("the Elsevier metadata for %s carries no DOI" % pii)
            code, err = self._refusal(["url", SD_URL, "--out-dir", tmp],
                                      resolve_pii_to_doi=no_doi)
        self.assertEqual(code, 2)
        self.assertIn("no DOI", err)

    def test_the_environment_token_reaches_both_the_lookup_and_the_download(self):
        seen = {}

        def fake_resolve(pii, key, tok):
            seen["tok"] = tok
            return "10.1/x"

        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch.dict(os.environ, {"ELSEVIER_INSTTOKEN": "ENVTOKEN"}):
            got = _run_cli(["url", PII, "--out-dir", tmp], resolve_pii_to_doi=fake_resolve)
        self.assertEqual(seen["tok"], "ENVTOKEN")
        self.assertEqual(got["insttoken"], "ENVTOKEN")


class TestAttemptsRecord(unittest.TestCase):
    """Every rung leaves a line: number, outcome, short reason.

    Measured 2026-11-05: a rung's failure reason was only logged, so the agent
    could not tell why the Elsevier rung missed (no key, a 403, or a one-page
    preview) and improvised the Playwright MCP instead.
    """

    ENTRY = {"citekey": "Smith2024", "doi": "10.1/x"}
    OUTCOMES = {"ok", "miss", "preview", "skipped", "error", "listed"}

    def _all_miss(self, **overrides):
        patches = {
            "try_elsevier": mock.patch.object(download_pdf, "try_elsevier", return_value=False),
            "try_semantic_scholar": mock.patch.object(
                download_pdf, "try_semantic_scholar", return_value=False),
            "try_publisher_pdf": mock.patch.object(
                download_pdf, "try_publisher_pdf", return_value=False),
            "try_unpaywall": mock.patch.object(download_pdf, "try_unpaywall", return_value=None),
            "try_arxiv": mock.patch.object(download_pdf, "try_arxiv", return_value=None),
            "try_pmc": mock.patch.object(download_pdf, "try_pmc", return_value=None),
            "try_landing_html": mock.patch.object(
                download_pdf, "try_landing_html", return_value=None),
            "s2": mock.patch.object(download_pdf, "s2", None),
        }
        patches.update(overrides)
        return patches

    def _run(self, patches, api_key="KEY", **kwargs):
        with contextlib.ExitStack() as stack, tempfile.TemporaryDirectory() as tmp:
            for cm in patches.values():
                stack.enter_context(cm)
            return download_pdf.download_one(self.ENTRY, tmp, api_key, None, **kwargs)

    def test_a_failed_run_lists_every_rung_in_order_ending_with_the_manual_list(self):
        res = self._run(self._all_miss(), email="a@b.ca")
        self.assertEqual(res["status"], "failed")
        self.assertEqual([a["rung"] for a in res["attempts"]], [1, 2, 3, 4, 5, 6, 7, 8, 9])
        self.assertEqual([a["name"] for a in res["attempts"]][:3],
                         ["elsevier", "semantic_scholar", "publisher"])
        self.assertEqual(res["attempts"][-1]["name"], "manual")
        self.assertEqual(res["attempts"][-1]["outcome"], "listed")
        for attempt in res["attempts"]:
            self.assertIn(attempt["outcome"], self.OUTCOMES)
            self.assertTrue(attempt["reason"])

    def test_the_chain_stops_at_the_first_full_pdf_and_says_what_came_before(self):
        def fake_s2(doi, dest):
            Path(dest).write_bytes(b"%PDF-1.7 x")
            return True
        patches = self._all_miss(try_semantic_scholar=mock.patch.object(
            download_pdf, "try_semantic_scholar", side_effect=fake_s2))
        with contextlib.ExitStack() as stack:
            for cm in patches.values():
                stack.enter_context(cm)
            publisher = stack.enter_context(
                mock.patch.object(download_pdf, "try_publisher_pdf", return_value=False))
            with tempfile.TemporaryDirectory() as tmp:
                res = download_pdf.download_one(self.ENTRY, tmp, "KEY", None)
        publisher.assert_not_called()
        self.assertEqual([(a["rung"], a["outcome"]) for a in res["attempts"]],
                         [(1, "miss"), (2, "ok")])

    def test_a_preview_is_recorded_as_a_preview_with_its_page_count(self):
        def fake_elsevier(doi, dest, key, tok):
            Path(dest).write_bytes(b"%PDF-1.7 x")
            return True
        patches = self._all_miss(try_elsevier=mock.patch.object(
            download_pdf, "try_elsevier", side_effect=fake_elsevier))
        with mock.patch.object(download_pdf, "is_paywall_preview",
                               return_value=(True, "1 page(s), 263000 bytes - publisher preview")):
            res = self._run(patches)
        first = res["attempts"][0]
        self.assertEqual((first["rung"], first["outcome"]), (1, "preview"))
        self.assertIn("1 page(s)", first["reason"])
        self.assertEqual(res["status"], "failed")
        manual = res["attempts"][-1]
        self.assertEqual(manual["rung"], 9)
        self.assertIn("not entitled", manual["reason"])

    def test_no_key_is_skipped_and_names_the_variable(self):
        res = self._run(self._all_miss(), api_key=None)
        first = res["attempts"][0]
        self.assertEqual(first["outcome"], "skipped")
        self.assertIn("SCOPUS_API_KEY", first["reason"])

    def test_an_http_status_and_a_non_pdf_body_become_the_miss_reason(self):
        patches = self._all_miss()
        del patches["try_elsevier"]
        denied = FakeResponse(status_code=403)
        with mock.patch.object(download_pdf.requests, "get", return_value=denied):
            res = self._run(patches)
        self.assertEqual(res["attempts"][0]["outcome"], "miss")
        self.assertIn("403", res["attempts"][0]["reason"])
        html = FakeResponse(status_code=200, headers={"Content-Type": "text/html"},
                            chunks=[b"<html>sign in</html>"])
        with mock.patch.object(download_pdf.requests, "get", return_value=html):
            res = self._run(patches)
        self.assertIn("not a PDF", res["attempts"][0]["reason"])

    def test_a_reason_never_leaks_into_the_next_rung(self):
        patches = self._all_miss()
        del patches["try_elsevier"]
        with mock.patch.object(download_pdf.requests, "get",
                               return_value=FakeResponse(status_code=403)):
            res = self._run(patches)
        self.assertIn("403", res["attempts"][0]["reason"])
        self.assertNotIn("403", res["attempts"][1]["reason"])

    def test_skips_name_their_precondition(self):
        s2_without_ids = mock.patch.object(
            download_pdf, "s2", mock.Mock(external_ids_for_doi=mock.Mock(return_value={})))
        res = self._run(self._all_miss(s2=s2_without_ids), allow_html=False)  # no email, no ids
        by_name = {a["name"]: a for a in res["attempts"]}
        self.assertEqual(by_name["unpaywall"]["outcome"], "skipped")
        self.assertIn("UNPAYWALL_EMAIL", by_name["unpaywall"]["reason"])
        self.assertEqual(by_name["arxiv"]["outcome"], "skipped")
        self.assertIn("arXiv", by_name["arxiv"]["reason"])
        self.assertEqual(by_name["pmc"]["outcome"], "skipped")
        self.assertEqual(by_name["landing"]["outcome"], "skipped")
        self.assertIn("--no-html", by_name["landing"]["reason"])
        self.assertEqual(by_name["semantic_scholar"]["outcome"], "miss")

    def test_a_missing_semantic_scholar_module_is_a_skip_not_a_miss(self):
        res = self._run(self._all_miss())
        by_name = {a["name"]: a for a in res["attempts"]}
        self.assertEqual(by_name["semantic_scholar"]["outcome"], "skipped")

    def test_reasons_are_one_short_line(self):
        long_reason = "line one\nline two " + "x" * 500
        patches = self._all_miss()
        with mock.patch.object(download_pdf, "_take_reason", return_value=long_reason):
            res = self._run(patches)
        for attempt in res["attempts"]:
            self.assertNotIn("\n", attempt["reason"])
            self.assertLessEqual(len(attempt["reason"]), download_pdf.MAX_REASON_CHARS)

    def test_present_and_no_doi_results_carry_no_attempts(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(os.path.join(tmp, "smith2024.pdf")).write_bytes(b"%PDF-1.7 already")
            present = download_pdf.download_one(self.ENTRY, tmp, "KEY", None)
            nodoi = download_pdf.download_one({"citekey": "y", "doi": ""}, tmp, "KEY", None)
        self.assertNotIn("attempts", present)
        self.assertNotIn("attempts", nodoi)


class TestElsevierEntitlementHeader(unittest.TestCase):
    """Elsevier says why a PDF is a preview; the record quotes it.

    Measured 2026-11-05 on the UQAC VPN (132.212.162.183): both paywalled
    controls answered HTTP 200 with a one-page PDF and the header
    `X-ELS-Status: WARNING - Response limited to first page because requestor
    not entitled to resource`. That is the publisher's verdict, better evidence
    than an inference from a page count.
    """

    WARNING = ("WARNING - Response limited to first page because requestor "
               "not entitled to resource")
    ENTRY = {"citekey": "Smith2024", "doi": "10.1/x"}

    def _run(self, headers):
        chain = TestAttemptsRecord()
        patches = chain._all_miss()
        del patches["try_elsevier"]
        response = FakeResponse(status_code=200, headers=headers, chunks=PDF_CHUNKS)
        with mock.patch.object(download_pdf.requests, "get", return_value=response), \
             mock.patch.object(download_pdf, "is_paywall_preview",
                               return_value=(True, "1 page(s), 2202710 bytes - preview")):
            return chain._run(patches)

    def test_the_publishers_own_words_become_the_rung_reason(self):
        res = self._run({"Content-Type": "application/pdf", "X-ELS-Status": self.WARNING})
        first = res["attempts"][0]
        self.assertEqual(first["outcome"], "preview")
        self.assertIn("not entitled", first["reason"])
        self.assertTrue(first["reason"].startswith("Elsevier:"))

    def test_the_manual_line_then_cites_the_publisher_not_a_guess(self):
        res = self._run({"Content-Type": "application/pdf", "X-ELS-Status": self.WARNING})
        self.assertIn("Elsevier reports", res["attempts"][-1]["reason"])

    def test_without_the_header_the_page_count_reason_is_kept(self):
        res = self._run({"Content-Type": "application/pdf"})
        first = res["attempts"][0]
        self.assertIn("1 page(s)", first["reason"])
        self.assertNotIn("Elsevier reports", res["attempts"][-1]["reason"])

    def test_a_non_warning_status_is_not_quoted(self):
        res = self._run({"Content-Type": "application/pdf", "X-ELS-Status": "OK - Fine"})
        self.assertNotIn("Fine", res["attempts"][0]["reason"])


class TestBrowserRungDefault(unittest.TestCase):
    """The browser rung is part of the chain, not an opt-in.

    Measured 2026-11-05: tier 8 ran only with --browser and no agent passed it,
    so the chain silently ended at tier 7.
    """

    def test_it_runs_by_default_on_every_subcommand(self):
        with tempfile.TemporaryDirectory() as tmp:
            bib = os.path.join(tmp, "r.bib")
            Path(bib).write_text("@article{a2024x,\n  doi = {10.1/x},\n  title = {T}\n}\n",
                                 encoding="utf-8")
            for argv in (["doi", "10.1/x", "--out-dir", tmp],
                         ["bib", bib, "--out-dir", tmp],
                         ["url", PII, "--out-dir", tmp]):
                with self.subTest(mode=argv[0]), \
                     mock.patch.object(download_pdf, "resolve_pii_to_doi", return_value="10.1/x"):
                    got = _run_cli(argv)
                    self.assertTrue(got["kwargs"]["use_browser"])

    def test_browser_stays_accepted_as_a_no_op_alias(self):
        with tempfile.TemporaryDirectory() as tmp:
            got = _run_cli(["doi", "10.1/x", "--out-dir", tmp, "--browser"])
        self.assertTrue(got["kwargs"]["use_browser"])

    def test_no_browser_turns_the_rung_off_on_every_subcommand(self):
        with tempfile.TemporaryDirectory() as tmp:
            bib = os.path.join(tmp, "r.bib")
            Path(bib).write_text("@article{a2024x,\n  doi = {10.1/x},\n  title = {T}\n}\n",
                                 encoding="utf-8")
            for argv in (["doi", "10.1/x", "--out-dir", tmp, "--no-browser"],
                         ["bib", bib, "--out-dir", tmp, "--no-browser"],
                         ["url", PII, "--out-dir", tmp, "--no-browser"]):
                with self.subTest(mode=argv[0]), \
                     mock.patch.object(download_pdf, "resolve_pii_to_doi", return_value="10.1/x"):
                    got = _run_cli(argv)
                    self.assertFalse(got["kwargs"]["use_browser"])

    def test_the_two_flags_together_are_a_refusal(self):
        with tempfile.TemporaryDirectory() as tmp, \
             contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as ctx:
                _run_cli(["doi", "10.1/x", "--out-dir", tmp, "--browser", "--no-browser"])
        self.assertEqual(ctx.exception.code, 2)

    def test_a_disabled_rung_is_recorded_as_skipped_and_names_the_flag(self):
        tier = TestBrowserTier()
        fake_bf = mock.Mock()
        fake_bf.browser_available.return_value = True
        res = tier._run(fake_bf, use_browser=False)
        browser = [a for a in res["attempts"] if a["name"] == "browser"][0]
        self.assertEqual(browser["outcome"], "skipped")
        self.assertIn("--no-browser", browser["reason"])

    def test_playwright_absent_is_a_recorded_skip_with_the_remedy_not_a_crash(self):
        tier = TestBrowserTier()
        res = tier._run(None, use_browser=True)
        self.assertEqual(res["status"], "failed")
        browser = [a for a in res["attempts"] if a["name"] == "browser"][0]
        self.assertEqual(browser["outcome"], "skipped")
        self.assertIn("pip install playwright", browser["reason"])

    def test_a_missing_playwright_package_names_pip_and_not_a_chromium_build(self):
        # Review round 1: browser_available() is False only when the playwright
        # package cannot be imported. The old reason said "no Chromium build found" and
        # told the user to run `playwright install chromium`, which fixes nothing.
        tier = TestBrowserTier()
        fake_bf = mock.Mock()
        fake_bf.browser_available.return_value = False
        res = tier._run(fake_bf, use_browser=True)
        browser = [a for a in res["attempts"] if a["name"] == "browser"][0]
        self.assertEqual(browser["outcome"], "skipped")
        self.assertIn("pip install playwright", browser["reason"])
        self.assertNotIn("no Chromium build", browser["reason"])
        fake_bf.fetch_pdf_via_browser.assert_not_called()

    def test_a_disabled_rung_says_a_caller_may_leave_it_off_too(self):
        # Review round 1: callers other than the CLI have no --no-browser flag, so the
        # reason must not blame a flag they never had.
        tier = TestBrowserTier()
        fake_bf = mock.Mock()
        fake_bf.browser_available.return_value = True
        res = tier._run(fake_bf, use_browser=False)
        browser = [a for a in res["attempts"] if a["name"] == "browser"][0]
        self.assertIn("--no-browser", browser["reason"])
        self.assertIn("caller", browser["reason"])


class TestSharedBrowserSession(unittest.TestCase):
    """One browser session serves every paper of a CLI run (sign in once)."""

    def _bib(self, tmp):
        bib = os.path.join(tmp, "r.bib")
        Path(bib).write_text(
            "@article{a2024x,\n  doi = {10.1/x},\n  title = {T}\n}\n"
            "@article{b2024y,\n  doi = {10.1/y},\n  title = {U}\n}\n", encoding="utf-8")
        return bib

    def _fake_bf(self):
        import browser_fetch as real_bf
        fake = mock.Mock()
        fake.browser_available.return_value = True
        fake.BrowserRungError = real_bf.BrowserRungError
        fake.BrowserSession.return_value = mock.Mock(name="session")
        return fake

    def test_bib_creates_one_session_for_all_papers_and_closes_it_once(self):
        fake = self._fake_bf()
        with tempfile.TemporaryDirectory() as tmp:
            got_sessions = []
            real = _run_cli

            with mock.patch.object(download_pdf, "browser_fetch", fake):
                got = real(["bib", self._bib(tmp), "--out-dir", tmp])
        session = fake.BrowserSession.return_value
        fake.BrowserSession.assert_called_once()
        self.assertIs(got["kwargs"]["browser_session"], session)
        session.close.assert_called_once()

    def test_the_session_follows_the_headless_flag(self):
        fake = self._fake_bf()
        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch.object(download_pdf, "browser_fetch", fake):
            _run_cli(["doi", "10.1/x", "--out-dir", tmp, "--headless"])
        self.assertIs(fake.BrowserSession.call_args.kwargs["headed"], False)

    def test_no_browser_creates_no_session(self):
        fake = self._fake_bf()
        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch.object(download_pdf, "browser_fetch", fake):
            got = _run_cli(["doi", "10.1/x", "--out-dir", tmp, "--no-browser"])
        fake.BrowserSession.assert_not_called()
        self.assertIsNone(got["kwargs"]["browser_session"])

    def test_playwright_absent_creates_no_session(self):
        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch.object(download_pdf, "browser_fetch", None):
            got = _run_cli(["doi", "10.1/x", "--out-dir", tmp])
        self.assertIsNone(got["kwargs"]["browser_session"])

    def test_the_session_is_closed_even_when_a_download_raises(self):
        fake = self._fake_bf()
        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch.object(download_pdf, "browser_fetch", fake), \
             mock.patch.object(download_pdf, "download_one", side_effect=RuntimeError("boom")), \
             mock.patch.object(sys, "argv", ["download_pdf.py", "doi", "10.1/x",
                                             "--out-dir", tmp]):
            with self.assertRaises(RuntimeError):
                download_pdf.main()
        fake.BrowserSession.return_value.close.assert_called_once()

    def test_a_config_error_at_session_creation_does_not_stop_the_run(self):
        fake = self._fake_bf()
        fake.BrowserSession.side_effect = fake.BrowserRungError("bad config")
        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch.object(download_pdf, "browser_fetch", fake):
            got = _run_cli(["doi", "10.1/x", "--out-dir", tmp])
        self.assertIsNone(got["kwargs"]["browser_session"])

    def test_download_one_hands_the_session_to_the_browser_rung(self):
        seen = {}

        def fake_fetch(doi, dest, override_url=None, headed=True, session=None):
            seen["session"] = session
            return None
        fake_bf = mock.Mock()
        fake_bf.browser_available.return_value = True
        fake_bf.fetch_pdf_via_browser.side_effect = fake_fetch
        marker = object()
        TestBrowserTier()._run(fake_bf, use_browser=True, browser_session=marker)
        self.assertIs(seen["session"], marker)

    def test_without_a_session_the_call_is_unchanged(self):
        def old_signature(doi, dest, override_url=None, headed=True):
            return None
        fake_bf = mock.Mock()
        fake_bf.browser_available.return_value = True
        fake_bf.fetch_pdf_via_browser.side_effect = old_signature
        res = TestBrowserTier()._run(fake_bf, use_browser=True)
        self.assertEqual(res["status"], "failed")


class TestBrowserMissDetail(unittest.TestCase):

    def _run(self, detail):
        fake_bf = mock.Mock()
        fake_bf.browser_available.return_value = True
        fake_bf.fetch_pdf_via_browser.return_value = None
        fake_bf.last_outcome.return_value = detail
        res = TestBrowserTier()._run(fake_bf, use_browser=True)
        return [a for a in res["attempts"] if a["name"] == "browser"][0]

    def test_what_the_browser_saw_becomes_the_reason(self):
        attempt = self._run("no PDF captured; last page host=www.example.org title='Sign in'")
        self.assertEqual(attempt["outcome"], "miss")
        self.assertIn("host=www.example.org", attempt["reason"])

    def test_nothing_to_say_keeps_the_generic_reason(self):
        self.assertEqual(self._run("")["reason"], "no PDF returned")
        self.assertEqual(self._run(object())["reason"], "no PDF returned")   # not a string


class TestBrowserRungRefusal(unittest.TestCase):
    """A named refusal inside rung 8 is an `error` attempt, never a crash (R8, R11)."""

    def _run_with(self, error):
        import browser_fetch as real_bf
        fake_bf = mock.Mock()
        fake_bf.browser_available.return_value = True
        fake_bf.BrowserRungError = real_bf.BrowserRungError
        fake_bf.fetch_pdf_via_browser.side_effect = error
        return TestBrowserTier()._run(fake_bf, use_browser=True)

    def test_a_config_or_provider_refusal_is_recorded_with_its_text(self):
        import browser_fetch as real_bf
        res = self._run_with(real_bf.BrowserRungError(
            "browser-fetch.json: key 'poll_s' must be a positive number"))
        self.assertEqual(res["status"], "failed")
        browser = [a for a in res["attempts"] if a["name"] == "browser"][0]
        self.assertEqual(browser["outcome"], "error")
        self.assertIn("poll_s", browser["reason"])
        self.assertEqual(res["attempts"][-1]["rung"], 9)

    def test_any_other_exception_still_propagates(self):
        with self.assertRaises(KeyError):
            self._run_with(KeyError("a real defect must not be swallowed"))


class TestAttemptsInReports(unittest.TestCase):

    def test_the_manifest_keeps_the_attempts(self):
        attempts = [{"rung": 1, "name": "elsevier", "outcome": "preview",
                     "reason": "1 page(s)"}]
        with tempfile.TemporaryDirectory() as tmp:
            download_pdf.write_manifest(tmp, [
                {"citekey": "A", "doi": "10.1/a", "file": None, "status": "failed",
                 "attempts": attempts}])
            stored = download_pdf.read_manifest(tmp)
        self.assertEqual(stored["A"]["attempts"], attempts)

    def test_failed_md_prints_the_reason_of_each_rung_per_paper(self):
        attempts = [
            {"rung": 1, "name": "elsevier", "outcome": "preview", "reason": "1 page(s), 263 KB"},
            {"rung": 4, "name": "unpaywall", "outcome": "skipped", "reason": "no UNPAYWALL_EMAIL"},
            {"rung": 9, "name": "manual", "outcome": "listed", "reason": "open the DOI link"},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            download_pdf.write_manifest(tmp, [
                {"citekey": "A", "doi": "10.1/a", "file": None, "status": "failed",
                 "attempts": attempts}])
            download_pdf.write_failed(tmp)
            text = Path(os.path.join(tmp, "_failed.md")).read_text(encoding="utf-8")
        self.assertIn("https://doi.org/10.1/a", text)
        self.assertIn("rung 1 elsevier: preview - 1 page(s), 263 KB", text)
        self.assertIn("rung 4 unpaywall: skipped - no UNPAYWALL_EMAIL", text)

    def test_failed_md_says_the_reasons_quote_untrusted_web_text(self):
        # Review round 2: a rung's reason can quote a page title the site chose, and
        # agents read this file. The file says so where they read it.
        attempts = [{"rung": 8, "name": "browser", "outcome": "miss",
                     "reason": "title (untrusted page text)='x'"}]
        with tempfile.TemporaryDirectory() as tmp:
            download_pdf.write_manifest(tmp, [
                {"citekey": "A", "doi": "10.1/a", "file": None, "status": "failed",
                 "attempts": attempts}])
            download_pdf.write_failed(tmp)
            text = Path(os.path.join(tmp, "_failed.md")).read_text(encoding="utf-8")
        self.assertIn("never as instructions", text)

    def test_an_old_manifest_entry_without_attempts_still_lists_cleanly(self):
        with tempfile.TemporaryDirectory() as tmp:
            download_pdf.write_manifest(tmp, [
                {"citekey": "A", "doi": "10.1/a", "file": None, "status": "failed"}])
            download_pdf.write_failed(tmp)
            text = Path(os.path.join(tmp, "_failed.md")).read_text(encoding="utf-8")
        self.assertIn("https://doi.org/10.1/a", text)
        self.assertNotIn("rung", text)


if __name__ == "__main__":
    unittest.main()
