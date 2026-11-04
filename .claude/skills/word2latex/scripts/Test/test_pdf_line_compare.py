"""
Offline tests for pdf_line_compare.py (word2latex, step 5 visual verification).

The PDFs are built in a temporary folder with PyMuPDF from fictitious text, so no Word,
no LaTeX and no network are needed. The suite is skipped, not failed, when PyMuPDF is
absent, which is how run-offline-tests.ps1 grades a missing third-party package.
"""
from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))

import pdf_line_compare as plc  # noqa: E402

try:
    import fitz  # noqa: F401
    HAVE_FITZ = True
except ImportError:
    HAVE_FITZ = False


def make_pdf(path: Path, lines: list[tuple[float, float, str]], fontsize: float = 10) -> None:
    """
    --------------------------------------------------------------------------
    Purpose:
        Write a one-page letter PDF holding the given lines.

    Inputs:
        path (Path): output file.
        lines (list of (x_pt, baseline_pt, text)): one entry per line.
        fontsize (float): size of every line, in points.

    Outputs:
        None. Writes the PDF.
    --------------------------------------------------------------------------
    """
    import fitz
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    for x, y, text in lines:
        page.insert_text((x, y), text, fontsize=fontsize, fontname="helv")
    doc.save(path)
    doc.close()


@unittest.skipUnless(HAVE_FITZ, "PyMuPDF is not installed")
class ExtractAndCompare(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.config = plc.load_config()
        self.base = [(72, 100, "Veuillez fournir la liste des références"),
                     (72, 120, "Cliquez ou appuyez ici pour saisir du texte."),
                     (72, 140, "Cliquez ou appuyez ici pour saisir du texte.")]

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _run(self, ref_lines, cand_lines, *extra):
        ref, cand = self.dir / "ref.pdf", self.dir / "cand.pdf"
        make_pdf(ref, ref_lines)
        make_pdf(cand, cand_lines)
        out = io.StringIO()
        with redirect_stdout(out):
            code = plc.main([str(ref), str(cand), *extra])
        return code, out.getvalue()

    def test_identical_pdfs_exit_zero(self):
        code, text = self._run(self.base, self.base)
        self.assertEqual(code, 0)
        self.assertIn("flagged 0, missing 0, extra 0", text)

    def test_shifted_line_is_flagged_with_its_delta(self):
        moved = [self.base[0], (72, 125, self.base[1][2]), self.base[2]]  # 5 pt lower
        code, out = self._run(self.base, moved, "--json")
        self.assertEqual(code, 1)
        report = json.loads(out)
        flagged = [p for p in report["pairs"] if p["flagged"]]
        self.assertEqual(len(flagged), 1)
        self.assertAlmostEqual(flagged[0]["d_baseline_cm"], 5 / 72 * 2.54, places=2)

    def test_shift_under_tolerance_is_not_flagged(self):
        nudged = [(72.2, 100, self.base[0][2])] + self.base[1:]  # 0.007 cm, under 0.02
        code, _ = self._run(self.base, nudged)
        self.assertEqual(code, 0)

    def test_repeated_lines_pair_in_reading_order(self):
        # The second placeholder moved; the first must still pair with the first.
        moved = [self.base[0], self.base[1], (72, 150, self.base[2][2])]
        _, out = self._run(self.base, moved, "--json")
        report = json.loads(out)
        flags = [p["flagged"] for p in report["pairs"]]
        self.assertEqual(flags, [False, False, True])

    def test_missing_and_extra_lines_are_reported(self):
        cand = [self.base[0], self.base[1], (72, 160, "Une ligne ajoutée")]
        code, out = self._run(self.base[:2] + [(72, 140, "Ligne absente du candidat")], cand, "--json")
        self.assertEqual(code, 1)
        report = json.loads(out)
        self.assertEqual([m["text"].strip() for m in report["missing"]], ["Ligne absente du candidat"])
        self.assertEqual([e["text"].strip() for e in report["extra"]], ["Une ligne ajoutée"])

    def test_trailing_space_does_not_move_the_right_edge(self):
        with_space = [(72, 100, self.base[0][2] + "   ")] + self.base[1:]
        code, _ = self._run(self.base, with_space)
        self.assertEqual(code, 0)


class KeysAndRefusals(unittest.TestCase):
    def setUp(self) -> None:
        self.config = plc.load_config()

    def test_key_normalises_apostrophes_spaces_and_labels(self):
        a = plc.match_key("a) l’élaboration  et", self.config)
        b = plc.match_key("l'élaboration et", self.config)
        self.assertEqual(a, b)

    def test_key_drops_fallback_symbols(self):
        self.assertEqual(plc.match_key("☐   Rapports", self.config), "Rapports")

    def test_missing_pdf_is_a_refusal(self):
        err = io.StringIO()
        with redirect_stderr(err), redirect_stdout(io.StringIO()):
            code = plc.main(["absent_ref.pdf", "absent_cand.pdf"])
        self.assertEqual(code, 2)
        self.assertIn("refused", err.getvalue())

    def test_missing_config_key_is_named(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = Path(tmp) / "c.json"
            cfg.write_text(json.dumps({"tolerance_cm": {"value": 0.02, "provenance": "x"}}), encoding="utf-8")
            with self.assertRaises(plc.CompareError) as ctx:
                plc.load_config(cfg)
            self.assertIn("match_prefix_chars", str(ctx.exception))

    def _config_with(self, tmp: str, key: str, value) -> Path:
        raw = json.loads(plc.CONFIG_FILE.read_text(encoding="utf-8"))
        raw[key]["value"] = value
        cfg = Path(tmp) / "c.json"
        cfg.write_text(json.dumps(raw), encoding="utf-8")
        return cfg

    def test_invalid_regex_is_a_refusal_not_a_difference(self):
        # Review round 1 (2026-11-04): a broken regex raised re.error later, exit 1,
        # which reads as "the PDFs differ" instead of a broken configuration.
        with tempfile.TemporaryDirectory() as tmp:
            cfg = self._config_with(tmp, "list_label_regex", "^\\s*([a-d]")
            with self.assertRaises(plc.CompareError) as ctx:
                plc.load_config(cfg)
            self.assertIn("list_label_regex", str(ctx.exception))

    def test_non_numeric_values_are_refused(self):
        for key, bad in (("tolerance_cm", "0.02cm"), ("match_prefix_chars", "x"),
                         ("max_extra_reported", None), ("tolerance_cm", True),
                         # Round 3: a zero prefix makes every key empty and a NaN tolerance
                         # never compares, so both reported two different PDFs identical.
                         ("match_prefix_chars", 0), ("tolerance_cm", float("nan"))):
            with self.subTest(key=key, bad=bad), tempfile.TemporaryDirectory() as tmp:
                with self.assertRaises(plc.CompareError) as ctx:
                    plc.load_config(self._config_with(tmp, key, bad))
                self.assertIn(key, str(ctx.exception))

    def test_shipped_config_carries_provenance(self):
        raw = json.loads(plc.CONFIG_FILE.read_text(encoding="utf-8"))
        for key in plc.CONFIG_KEYS:
            self.assertTrue(raw[key].get("provenance"), key)


if __name__ == "__main__":
    unittest.main()
