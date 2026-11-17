"""test_text_quality - offline suite for the text repair and the OCR preflight (Issue 122, plan 5, task 1).

Every fixture is fictitious (R34). The OCR call and the environment are injected, so the suite depends on the
machine only where a test says so. One optional test runs the real preflight and is skipped when TESSDATA_PREFIX
is not set in the environment. No file under a report or course folder is ever opened here.
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS))
import text_quality as tq  # noqa: E402
from text_quality import OcrUnavailable, QualityConfigError  # noqa: E402

REPLACEMENT = "�"
PDF = Path("fictitious_report.pdf")


def _settings(min_chars=3):
    """Return fictitious settings: a threshold and the language map."""
    return {
        "min_replacement_chars": min_chars,
        "language_codes": {"fr": ["fra"], "en": ["eng"], "ambiguous": ["fra", "eng"]},
    }


def _ocr_settings():
    """Return fictitious OCR probe settings, the keys the preflight reads."""
    return {
        "language_codes": {"fr": ["fra"], "en": ["eng"], "ambiguous": ["fra", "eng"]},
        "tessdata_env_var": "TESSDATA_PREFIX",
        "tesseract_tool_name": "Tesseract",
        "ocr_probe_word": "Test",
        "ocr_probe_font_size": 48,
        "ocr_probe_dpi": 300,
    }


class _Folder(unittest.TestCase):
    """Base class giving each test a temporary folder that is removed afterwards."""

    def setUp(self):
        """Create the temporary folder."""
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.folder = Path(self._tmp.name)

    def _traineddata(self, *codes):
        """Write empty traineddata files for the given codes and return the folder."""
        for code in codes:
            (self.folder / f"{code}.traineddata").write_bytes(b"")
        return str(self.folder)


class PreflightTests(_Folder):
    """The OCR preflight proves that OCR works and names what is missing."""

    def test_preflight_names_a_missing_language(self):
        """A language with no traineddata file is refused, and the file name is in the message."""
        environ = {"TESSDATA_PREFIX": self._traineddata("eng")}

        def ocr_run(language, tessdata):
            raise AssertionError("OCR must not run when a language file is missing")

        with self.assertRaises(OcrUnavailable) as ctx:
            tq.ocr_preflight(["fra", "eng"], environ=environ, ocr_run=ocr_run, settings=_ocr_settings())
        self.assertIn("fra.traineddata", str(ctx.exception))

    def test_preflight_names_a_missing_tool(self):
        """An OCR call that raises is refused, and the message names the tool."""
        environ = {"TESSDATA_PREFIX": self._traineddata("fra", "eng")}

        def ocr_run(language, tessdata):
            raise RuntimeError("no OCR engine behind the call")

        with self.assertRaises(OcrUnavailable) as ctx:
            tq.ocr_preflight(["fra"], environ=environ, ocr_run=ocr_run, settings=_ocr_settings())
        message = str(ctx.exception)
        self.assertIn("Tesseract", message)
        self.assertIn("fra", message)

    def test_preflight_refuses_when_tessdata_is_unset(self):
        """With TESSDATA_PREFIX unset the preflight refuses and names the variable."""
        with self.assertRaises(OcrUnavailable) as ctx:
            tq.ocr_preflight(["eng"], environ={}, ocr_run=lambda l, t: "Test", settings=_ocr_settings())
        self.assertIn("TESSDATA_PREFIX", str(ctx.exception))

    def test_preflight_refuses_when_the_probe_word_is_not_read(self):
        """An OCR that returns text without the probe word is refused, not taken as working."""
        environ = {"TESSDATA_PREFIX": self._traineddata("eng")}
        with self.assertRaises(OcrUnavailable):
            tq.ocr_preflight(["eng"], environ=environ, ocr_run=lambda l, t: "Ceci", settings=_ocr_settings())

    def test_preflight_passes_when_the_probe_word_is_read(self):
        """A working OCR returns the probe word for each language, and the preflight returns None."""
        environ = {"TESSDATA_PREFIX": self._traineddata("fra", "eng")}
        seen = []

        def ocr_run(language, tessdata):
            seen.append((language, tessdata))
            return "test"

        result = tq.ocr_preflight(["fra", "eng"], environ=environ, ocr_run=ocr_run, settings=_ocr_settings())
        self.assertIsNone(result)
        self.assertEqual(seen, [("fra", environ["TESSDATA_PREFIX"]), ("eng", environ["TESSDATA_PREFIX"])])

    def test_preflight_refuses_an_empty_language_list(self):
        """An empty list of languages is refused rather than passing with nothing checked."""
        with self.assertRaises(tq.TextQualityError):
            tq.ocr_preflight([], environ={"TESSDATA_PREFIX": str(self.folder)},
                             ocr_run=lambda l, t: "Test", settings=_ocr_settings())

    @unittest.skipUnless(os.environ.get("TESSDATA_PREFIX"), "TESSDATA_PREFIX is not set")
    def test_real_preflight_runs_when_tessdata_is_set(self):
        """Optional: the real OCR of the shipped settings reads the probe word in English."""
        tq.ocr_preflight(["eng"])


class NormalizeTests(unittest.TestCase):
    """normalize_text makes NFC and expands ligature letters, and leaves plain text alone."""

    def test_normalize_makes_nfc_and_expands_ligatures(self):
        """A decomposed e-acute becomes one code point, and a fi ligature becomes two letters."""
        self.assertEqual(tq.normalize_text("étﬁ"), "étfi")
        self.assertEqual(tq.normalize_text("ﬀ"), "ff")

    def test_plain_text_is_unchanged(self):
        """Text with no ligature and no decomposed letter comes back identical."""
        self.assertEqual(tq.normalize_text("Rapport fictif, 2 pages."), "Rapport fictif, 2 pages.")


class ReplacementCountTests(unittest.TestCase):
    """replacement_count counts the Unicode replacement character and nothing else."""

    def test_counts_replacement_characters(self):
        """Two replacement characters in the text give a count of two."""
        self.assertEqual(tq.replacement_count("a" + REPLACEMENT + "b" + REPLACEMENT), 2)
        self.assertEqual(tq.replacement_count(""), 0)


class RepairTests(unittest.TestCase):
    """repair_pages calls OCR only on damaged pages and never replaces a sound one."""

    def test_repair_only_pages_over_the_threshold(self):
        """Only the page whose count reaches the threshold is OCR'd; the others keep their text."""
        texts = ["clean text", "one " + REPLACEMENT, REPLACEMENT * 3 + "x"]
        calls = []

        def ocr_page(pdf, page_number, tesseract_language):
            calls.append((page_number, tesseract_language))
            return "OCR page"

        new, quality = tq.repair_pages(PDF, texts, "fr", _settings(3), ocr_page)
        self.assertEqual(calls, [(3, "fra")])
        self.assertEqual(new, ["clean text", "one " + REPLACEMENT, "OCR page"])
        self.assertEqual(quality[0], {"page": 1, "replacement_chars": 0, "ocr": False, "ocr_empty": False})
        self.assertEqual(quality[1], {"page": 2, "replacement_chars": 1, "ocr": False, "ocr_empty": False})
        self.assertEqual(quality[2], {"page": 3, "replacement_chars": 3, "ocr": True, "ocr_empty": False})

    def test_empty_ocr_keeps_the_original_text(self):
        """An OCR that returns only blanks keeps the original text and flags the page."""
        original = REPLACEMENT * 4 + "abc"
        new, quality = tq.repair_pages(PDF, [original], "en", _settings(3), lambda p, n, t: "   ")
        self.assertEqual(new, [original])
        self.assertEqual(quality[0]["ocr"], False)
        self.assertEqual(quality[0]["ocr_empty"], True)
        self.assertEqual(quality[0]["replacement_chars"], 4)

    def test_english_document_uses_the_english_code(self):
        """An English document asks OCR for the English code, never the French one."""
        seen = []
        tq.repair_pages(PDF, [REPLACEMENT * 5], "en", _settings(3),
                        lambda p, n, t: seen.append(t) or "Text")
        self.assertEqual(seen, ["eng"])

    def test_ambiguous_language_asks_for_both_codes(self):
        """The ambiguous language asks OCR for both codes joined, as Tesseract expects."""
        seen = []
        tq.repair_pages(PDF, [REPLACEMENT * 5], "ambiguous", _settings(3),
                        lambda p, n, t: seen.append(t) or "Text")
        self.assertEqual(seen, ["fra+eng"])

    def test_zero_threshold_never_replaces_a_sound_page(self):
        """With a threshold of zero, a page with no replacement character is still never OCR'd."""

        def ocr_page(pdf, page_number, tesseract_language):
            raise AssertionError("OCR must not run on a sound page")

        new, quality = tq.repair_pages(PDF, ["sound text"], "fr", _settings(0), ocr_page)
        self.assertEqual(new, ["sound text"])
        self.assertEqual(quality[0]["ocr"], False)

    def test_pages_not_ocrd_keep_their_text_layer_unnormalized(self):
        """A page below the threshold keeps its original characters, even a decomposed accent."""
        decomposed = "é fictif"
        new, _ = tq.repair_pages(PDF, [decomposed], "fr", _settings(3), lambda p, n, t: "x")
        self.assertEqual(new, [decomposed])

    def test_missing_threshold_is_named(self):
        """A settings dict with no threshold key raises a named error."""
        settings = _settings(3)
        del settings["min_replacement_chars"]
        with self.assertRaises(QualityConfigError) as ctx:
            tq.repair_pages(PDF, ["x"], "fr", settings, lambda p, n, t: "x")
        self.assertIn("min_replacement_chars", str(ctx.exception))


class LanguageCodeTests(_Folder):
    """Language codes come from the data file; ambiguous means both codes; a missing key is named."""

    def test_language_mapping_both_for_ambiguous(self):
        """fr gives fra, en gives eng, and ambiguous gives both, read from the shipped file."""
        codes = tq.load_ocr_settings()["language_codes"]
        self.assertEqual(tq.tesseract_codes("fr", codes), ["fra"])
        self.assertEqual(tq.tesseract_codes("en", codes), ["eng"])
        self.assertEqual(tq.tesseract_codes("ambiguous", codes), ["fra", "eng"])

    def test_unknown_language_is_named(self):
        """A language with no entry is refused and the language is named."""
        codes = _settings()["language_codes"]
        with self.assertRaises(QualityConfigError) as ctx:
            tq.tesseract_codes("de", codes)
        self.assertIn("de", str(ctx.exception))

    def test_shipped_file_entries_carry_provenance(self):
        """Every entry of the shipped data file has a non-empty provenance string (R4)."""
        raw = json.loads((SCRIPTS.parent / "assets" / "ocr_languages.json").read_text(encoding="utf-8"))
        self.assertTrue(raw)
        for key, entry in raw.items():
            self.assertIn("value", entry, key)
            self.assertIsInstance(entry.get("provenance"), str, key)
            self.assertTrue(entry["provenance"].strip(), key)

    def test_missing_key_in_data_file_is_named(self):
        """A data file without one required key is refused and the key is named (R3)."""
        raw = json.loads((SCRIPTS.parent / "assets" / "ocr_languages.json").read_text(encoding="utf-8"))
        del raw["tessdata_env_var"]
        path = self.folder / "ocr_languages.json"
        path.write_text(json.dumps(raw), encoding="utf-8")
        with self.assertRaises(QualityConfigError) as ctx:
            tq.load_ocr_settings(path)
        self.assertIn("tessdata_env_var", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
