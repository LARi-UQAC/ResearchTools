"""
Offline tests for paper_extract.py: \\input resolution (including the missing file
and the circular one), section and float extraction, the number inventory and its
normalisation, and the two PDF cases that must be refused rather than half-read.
No network, no PDF library needed for the LaTeX paths.
"""
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import paper_extract as pe  # noqa: E402

MAIN = r"""
\documentclass{article}
\title{Adaptive Safety for Human-Robot Collaboration}
\author{R. Feuku \and M. J.-D. Otis}
\begin{document}
\begin{abstract}
We reach 95.2 \% accuracy on 32 algorithms.
\end{abstract}
\section{Introduction}
Battery disassembly is a shared cell. % a comment mentioning 999
\input{chapters/results}
\input{chapters/missing}
\end{document}
"""

RESULTS = r"""
\section{Results}
The blink interval widens to 941 mm, and the model reaches 95,2 \% on 1 950 samples.
\begin{figure}
  \includegraphics[width=0.8\linewidth]{fig5_evolution.png}
  \caption{Blink interval against fatigue}
  \label{fig:blink-interval-evolution}
\end{figure}
\begin{equation}\label{eq:linear-fatigue-model}
  y = ax + b
\end{equation}
As reported \cite{otis2024diagnosis,feuku2026helmet}.
"""


class TestIncludes(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.dir, "chapters"))
        self.main = os.path.join(self.dir, "main.tex")
        with open(self.main, "w", encoding="utf8") as fh:
            fh.write(MAIN)
        with open(os.path.join(self.dir, "chapters", "results.tex"), "w",
                  encoding="utf8") as fh:
            fh.write(RESULTS)

    def test_an_included_chapter_is_inlined(self):
        text, _ = pe.resolve_includes(self.main)
        self.assertIn("The blink interval widens", text)

    def test_a_missing_include_warns_and_does_not_stop(self):
        text, warnings = pe.resolve_includes(self.main)
        self.assertTrue(any("missing include" in w for w in warnings))
        self.assertIn("Battery disassembly", text)

    def test_a_circular_include_terminates(self):
        loop_a = os.path.join(self.dir, "a.tex")
        loop_b = os.path.join(self.dir, "b.tex")
        with open(loop_a, "w", encoding="utf8") as fh:
            fh.write(r"\section{A}\input{b}")
        with open(loop_b, "w", encoding="utf8") as fh:
            fh.write(r"\section{B}\input{a}")
        text, warnings = pe.resolve_includes(loop_a)
        self.assertIn("A", text)
        self.assertTrue(any("circular" in w or "depth" in w for w in warnings))

    def test_comments_are_dropped_so_their_numbers_are_not_claims(self):
        text, _ = pe.resolve_includes(self.main)
        self.assertNotIn("999", text)


class TestInventory(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.dir, "chapters"))
        self.main = os.path.join(self.dir, "main.tex")
        with open(self.main, "w", encoding="utf8") as fh:
            fh.write(MAIN)
        with open(os.path.join(self.dir, "chapters", "results.tex"), "w",
                  encoding="utf8") as fh:
            fh.write(RESULTS)
        self.inv = pe.extract(self.main)

    def test_meta_is_read(self):
        self.assertIn("Adaptive Safety", self.inv["meta"]["title"])
        self.assertIn("Feuku", self.inv["meta"]["authors"])
        self.assertIn("95.2", self.inv["meta"]["abstract"])

    def test_sections_come_out_in_order(self):
        titles = [s["title"] for s in self.inv["sections"]]
        self.assertEqual(titles, ["Introduction", "Results"])

    def test_floats_carry_their_label_caption_and_asset(self):
        figure = self.inv["floats"][0]
        self.assertEqual(figure["kind"], "figure")
        self.assertEqual(figure["label"], "fig:blink-interval-evolution")
        self.assertIn("Blink interval", figure["caption"])
        self.assertEqual(figure["assets"], ["fig5_evolution.png"])

    def test_equations_carry_their_label(self):
        equation = self.inv["equations"][0]
        self.assertEqual(equation["label"], "eq:linear-fatigue-model")
        self.assertIn("y = ax + b", equation["tex"])

    def test_citation_keys_are_split(self):
        self.assertEqual(self.inv["citations"],
                         ["feuku2026helmet", "otis2024diagnosis"])

    def test_numbers_are_collected(self):
        self.assertIn("95.2", self.inv["numbers"])
        self.assertIn("941", self.inv["numbers"])
        self.assertIn("1950", self.inv["numbers"])

    def test_a_thin_extraction_is_reported(self):
        thin = os.path.join(self.dir, "thin.tex")
        with open(thin, "w", encoding="utf8") as fh:
            fh.write(r"\section{Only}\nnothing much here")
        warnings = pe.extract(thin)["warnings"]
        self.assertTrue(any("incomplete" in w for w in warnings))
        self.assertTrue(any("section(s) found" in w for w in warnings))


class TestNumberNormalisation(unittest.TestCase):
    def test_thousands_marks_and_decimal_commas_collapse_to_one_value(self):
        self.assertEqual(pe.normalise_number("1 950"), "1950")
        self.assertEqual(pe.normalise_number("1 950"), "1950")
        self.assertEqual(pe.normalise_number("95,2"), "95.2")
        self.assertEqual(pe.normalise_number("95.20"), "95.2")
        self.assertEqual(pe.normalise_number("1.234.567"), "1234567")

    def test_a_french_manuscript_and_an_english_slide_agree(self):
        source = set(pe.numbers_of("Nous atteignons 95,2 % sur 1 950 echantillons."))
        self.assertIn(pe.normalise_number("95.2"), source)
        self.assertIn(pe.normalise_number("1950"), source)


class TestPdfGuards(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.pdf = os.path.join(self.dir, "paper.pdf")
        with open(self.pdf, "wb") as fh:
            fh.write(b"%PDF-1.7\n")

    def test_an_encrypted_pdf_is_refused_with_advice(self):
        fake = mock.Mock()
        fake.open.return_value = mock.Mock(is_encrypted=True)
        with mock.patch.dict(sys.modules, {"fitz": fake}):
            with self.assertRaises(RuntimeError) as ctx:
                pe.read_pdf(self.pdf)
        self.assertIn("encrypted", str(ctx.exception))

    def test_a_scan_with_no_text_layer_is_refused(self):
        page = mock.Mock()
        page.get_text.return_value = "  "
        doc = mock.MagicMock(is_encrypted=False)
        doc.__iter__.return_value = iter([page])
        fake = mock.Mock()
        fake.open.return_value = doc
        with mock.patch.dict(sys.modules, {"fitz": fake}):
            with self.assertRaises(RuntimeError) as ctx:
                pe.read_pdf(self.pdf)
        self.assertIn("text layer", str(ctx.exception))

    def test_a_readable_pdf_warns_that_extraction_is_best_effort(self):
        page = mock.Mock()
        page.get_text.return_value = "word " * 600
        doc = mock.MagicMock(is_encrypted=False)
        doc.__iter__.return_value = iter([page])
        fake = mock.Mock()
        fake.open.return_value = doc
        with mock.patch.dict(sys.modules, {"fitz": fake}):
            inventory = pe.extract(self.pdf)
        self.assertTrue(any("best effort" in w for w in inventory["warnings"]))


class TestCli(unittest.TestCase):
    def test_the_inventory_writes_as_json(self):
        d = tempfile.mkdtemp()
        os.makedirs(os.path.join(d, "chapters"))
        main = os.path.join(d, "main.tex")
        with open(main, "w", encoding="utf8") as fh:
            fh.write(MAIN)
        with open(os.path.join(d, "chapters", "results.tex"), "w", encoding="utf8") as fh:
            fh.write(RESULTS)
        out = os.path.join(d, "inventory.json")
        pe.main([main, "--out", out])
        with open(out, encoding="utf8") as fh:
            data = json.load(fh)
        self.assertIn("numbers", data)
        self.assertIn("95.2", data["numbers"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
