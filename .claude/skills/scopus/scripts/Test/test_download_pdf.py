"""
test_download_pdf.py — offline unit tests for the PDF retrieval script.

All network is patched: requests.get is replaced by a FakeResponse factory and
the source-chain helpers are monkeypatched, so no API key, no Semantic Scholar
install, and no real download occur.

Run:
    cd .claude/skills/scopus/scripts
    python -m pytest Test/test_download_pdf.py -v
"""

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


if __name__ == "__main__":
    unittest.main()
