"""
test_stream_and_mupdf.py - offline tests for the two output defects measured on
2026-09-13, both of which corrupted the JSON report rather than the parsing.

No PDF, no network, no model: the streams are fakes and PyMuPDF's TOOLS object
is replaced, so nothing here opens a document.

Defect 1, stdout. The Windows console is cp1252. davis2021upzonings contains
U+2212, so emitting the report raised UnicodeEncodeError, which is a subclass of
ValueError and was therefore caught by main's handler and printed as
"ERROR: 'charmap' codec can't encode character '\\u2212' in position 3576".
The run exited 1 having written nothing, and the message named the paper rather
than the console, which sends the reader to the wrong remedy.

Defect 2, MuPDF. The C library writes its parser complaints to the process
stdout, INSIDE the JSON. agbossou2026nolandtake produced 14 lines of
"MuPDF error: format error: No common ancestor in structure tree" ahead of the
report, so json.load raised "Expecting value: line 1 column 1". Redirecting
sys.stdout does not help: that rebinds the Python object while MuPDF writes to
the file descriptor underneath it.

Run:
    cd .claude/skills/extract-statistic/scripts
    python Test/test_stream_and_mupdf.py -v
"""

import sys
import unittest
from pathlib import Path
from unittest import mock

_HERE = Path(__file__).resolve().parent
_SCRIPTS = _HERE.parent
sys.path.insert(0, str(_SCRIPTS))

import extract_text as et  # noqa: E402


class FakeStream:
    """A stream that records how it was reconfigured."""

    def __init__(self, refuse_encoding=False):
        self.calls = []
        self._refuse_encoding = refuse_encoding

    def reconfigure(self, **kwargs):
        self.calls.append(kwargs)
        if self._refuse_encoding and "encoding" in kwargs:
            raise LookupError("unknown encoding")


class NoReconfigureStream:
    """An exotic stream, such as a StringIO standing in for stdout."""


class ConfigureStreamsTest(unittest.TestCase):
    """stdout must be able to carry a publisher's glyphs."""

    def test_utf8_and_replace_are_requested(self):
        out, err = FakeStream(), FakeStream()
        with mock.patch.object(sys, "stdout", out), mock.patch.object(sys, "stderr", err):
            et.configure_streams()
        self.assertEqual(out.calls, [{"encoding": "utf-8", "errors": "replace"}])
        self.assertEqual(err.calls, [{"encoding": "utf-8", "errors": "replace"}])

    def test_a_stream_refusing_utf8_still_gets_replace(self):
        # The point of the fallback: a substituted character is a degraded
        # report, while an unencodable one is no report at all (R8).
        out = FakeStream(refuse_encoding=True)
        with mock.patch.object(sys, "stdout", out), mock.patch.object(sys, "stderr", FakeStream()):
            et.configure_streams()
        self.assertEqual(out.calls[-1], {"errors": "replace"})

    def test_a_stream_without_reconfigure_is_skipped_silently(self):
        with mock.patch.object(sys, "stdout", NoReconfigureStream()), \
             mock.patch.object(sys, "stderr", NoReconfigureStream()):
            et.configure_streams()          # must not raise

    def test_the_minus_sign_that_caused_the_failure_encodes_after_replace(self):
        # Negative control on the premise, not on the code: U+2212 really is
        # outside cp1252, so the defect was not a mis-diagnosis.
        with self.assertRaises(UnicodeEncodeError):
            "−".encode("cp1252")
        self.assertEqual("−".encode("cp1252", errors="replace"), b"?")


class FakeTools:
    def __init__(self, raises=False):
        self.calls = []
        self._raises = raises

    def mupdf_display_errors(self, value):
        self.calls.append(value)
        if self._raises:
            raise RuntimeError("no such handle")


class ToolsWithoutTheApi:
    """An older PyMuPDF."""


class SilenceMupdfTest(unittest.TestCase):
    """The C library's complaints must leave stdout, without being lost."""

    def test_display_errors_is_turned_off(self):
        tools = FakeTools()
        with mock.patch.object(et, "pymupdf", mock.Mock(TOOLS=tools)):
            self.assertTrue(et._silence_mupdf())
        self.assertEqual(tools.calls, [False])

    def test_an_older_pymupdf_changes_nothing_and_does_not_raise(self):
        with mock.patch.object(et, "pymupdf", mock.Mock(TOOLS=ToolsWithoutTheApi())):
            self.assertFalse(et._silence_mupdf())

    def test_no_pymupdf_at_all_is_reported_false(self):
        with mock.patch.object(et, "pymupdf", None):
            self.assertFalse(et._silence_mupdf())

    def test_a_raising_api_is_reported_false_rather_than_propagated(self):
        # A silenced logger is never worth a crash: this runs at import time,
        # so raising here would take down every caller of the module (R11).
        tools = FakeTools(raises=True)
        with mock.patch.object(et, "pymupdf", mock.Mock(TOOLS=tools)):
            self.assertFalse(et._silence_mupdf())

    def test_the_module_silenced_mupdf_at_import_when_it_could(self):
        tools = getattr(et.pymupdf, "TOOLS", None) if et.pymupdf is not None else None
        if tools is None or not hasattr(tools, "mupdf_display_errors"):
            self.skipTest("PyMuPDF without the TOOLS API on this machine")
        self.assertTrue(et._MUPDF_SILENCED)


if __name__ == "__main__":
    unittest.main()
