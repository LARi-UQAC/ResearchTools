"""
test_parse_cache.py - Offline unit tests for parse_cache.py.

No network, no model load, no PDF backend: the reader is injected in most
cases, so the heavy Docling and PyMuPDF imports never run. The default-reader
tests patch extract_text.pymupdf directly rather than importing a real PDF
backend. Run with the project Python:
    python .claude/skills/extract-statistic/scripts/Test/test_parse_cache.py
"""

import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import parse_cache  # noqa: E402


class TestParseCache(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.pdf = os.path.join(self.tmp.name, "otis2025diagnosis.pdf")
        with open(self.pdf, "wb") as handle:
            handle.write(b"%PDF-1.7\noriginal content\n%%EOF")
        self.calls: list = []

        def reader(path: str):
            self.calls.append(path)
            return ("# Introduction\n\nBody text.\n", [[["a", "b"]]],
                    {"backend": "fake", "page_offsets": [0, 16]})
        self.reader = reader

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_the_first_parse_is_a_miss_and_writes_the_cache(self) -> None:
        result = parse_cache.parse_cached(self.pdf, reader=self.reader)
        self.assertFalse(result["cache_hit"])
        md, meta = parse_cache.cache_paths(self.pdf)
        self.assertTrue(os.path.isfile(md))
        self.assertTrue(os.path.isfile(meta))

    def test_the_second_parse_is_a_hit_and_never_calls_the_reader(self) -> None:
        parse_cache.parse_cached(self.pdf, reader=self.reader)
        result = parse_cache.parse_cached(self.pdf, reader=self.reader)
        self.assertTrue(result["cache_hit"])
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(result["text"], "# Introduction\n\nBody text.\n")

    def test_a_changed_source_invalidates_the_cache(self) -> None:
        parse_cache.parse_cached(self.pdf, reader=self.reader)
        with open(self.pdf, "wb") as handle:
            handle.write(b"%PDF-1.7\nDIFFERENT content\n%%EOF")
        result = parse_cache.parse_cached(self.pdf, reader=self.reader)
        self.assertFalse(result["cache_hit"])
        self.assertEqual(len(self.calls), 2)

    def test_the_meta_records_the_source_hash_and_the_backend(self) -> None:
        parse_cache.parse_cached(self.pdf, reader=self.reader)
        _md, meta_path = parse_cache.cache_paths(self.pdf)
        with open(meta_path, encoding="utf-8") as handle:
            meta = json.load(handle)
        self.assertEqual(meta["source_sha256"], parse_cache.source_hash(self.pdf))
        self.assertEqual(meta["backend"], "fake")
        self.assertEqual(meta["page_offsets"], [0, 16])
        self.assertEqual(meta["pages"], 2)

    def test_an_explicit_cache_dir_is_honoured(self) -> None:
        elsewhere = os.path.join(self.tmp.name, "cache")
        parse_cache.parse_cached(self.pdf, cache_dir=elsewhere, reader=self.reader)
        self.assertTrue(os.listdir(elsewhere))
        md, _meta = parse_cache.cache_paths(self.pdf)
        self.assertFalse(os.path.exists(md))

    def test_a_corrupt_meta_file_is_treated_as_a_miss_not_a_crash(self) -> None:
        parse_cache.parse_cached(self.pdf, reader=self.reader)
        _md, meta_path = parse_cache.cache_paths(self.pdf)
        with open(meta_path, "w", encoding="utf-8") as handle:
            handle.write("{not json")
        result = parse_cache.parse_cached(self.pdf, reader=self.reader)
        self.assertFalse(result["cache_hit"])

    def test_tables_survive_the_round_trip(self) -> None:
        parse_cache.parse_cached(self.pdf, reader=self.reader)
        result = parse_cache.parse_cached(self.pdf, reader=self.reader)
        self.assertEqual(result["tables"], [[["a", "b"]]])

    def test_source_hash_is_stable(self) -> None:
        self.assertEqual(parse_cache.source_hash(self.pdf), parse_cache.source_hash(self.pdf))
        self.assertEqual(len(parse_cache.source_hash(self.pdf)), 64)


class TestDefaultReader(unittest.TestCase):
    """Exercises _default_reader itself, since the cache-hit tests above inject
    a fake reader and never touch it. This is where a naive PyMuPDF import
    would have gone uncaught (see the module docstring)."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_a_textlike_file_reports_the_textlike_backend_and_no_offsets(self) -> None:
        path = os.path.join(self.tmp.name, "note.txt")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("plain text body")
        text, tables, extra = parse_cache._default_reader(path)
        self.assertEqual(text, "plain text body")
        self.assertEqual(tables, [])
        self.assertEqual(extra, {"backend": "textlike", "page_offsets": None})

    def test_a_pdf_with_no_pymupdf_available_reports_no_offsets(self) -> None:
        path = os.path.join(self.tmp.name, "doc.pdf")
        with open(path, "wb") as handle:
            handle.write(b"%PDF-1.7\nx\n%%EOF")
        with patch("extract_text.pymupdf", None), \
             patch("extract_text.read_pdf", return_value=("body", [])):
            _text, _tables, extra = parse_cache._default_reader(path)
        self.assertIsNone(extra["page_offsets"])

    def test_a_pdf_with_pymupdf_resolved_via_the_fitz_fallback_still_gets_offsets(self) -> None:
        # extract_text.py aliases `import fitz as pymupdf` when the package
        # only exposes the legacy name; _default_reader must go through that
        # same resolved reference rather than a fresh bare `import pymupdf`,
        # which would raise ModuleNotFoundError on such a machine.
        path = os.path.join(self.tmp.name, "doc.pdf")
        with open(path, "wb") as handle:
            handle.write(b"%PDF-1.7\nx\n%%EOF")

        class _FakePage:
            def get_text(self) -> str:
                return "abcdefgh"

        class _FakeDoc:
            def __enter__(self):
                return [_FakePage(), _FakePage()]

            def __exit__(self, *exc):
                return False

        fake_pymupdf = type("FakePyMuPDF", (), {"open": staticmethod(lambda _p: _FakeDoc())})()
        with patch("extract_text.pymupdf", fake_pymupdf), \
             patch("extract_text.read_pdf", return_value=("abcdefgh" * 2, [])):
            _text, _tables, extra = parse_cache._default_reader(path)
        self.assertEqual(extra["page_offsets"], [0, 9])


if __name__ == "__main__":
    unittest.main(verbosity=2)
