"""
test_section_scan.py - offline unit tests for the section scanner used by the
extract-futureworks skill (scan_sections / _heading_lines in extract_text.py).

No network, no PDF, and no Markdown backend is exercised: scan_sections works on
plain text/Markdown strings, so the heavy Docling/MarkItDown imports never load.

Run:
    cd .claude/skills/extract-statistic/scripts
    python Test/test_section_scan.py -v
"""

import sys
import unittest
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_SCRIPTS = _HERE.parent
sys.path.insert(0, str(_SCRIPTS))

import extract_text  # noqa: E402


MARKDOWN_DOC = """# Introduction

We study a nonlinear controller for a robotic arm.

## Results

The controller reduced error by 12 percent.

## Future Work

We will extend the controller to nonlinear systems and validate it on hardware.

## References

[1] Smith et al.
"""

LATEX_DOC = r"""\section{Methodology}
We describe the method.

\section{Conclusion and Limitations}
The approach is limited to single-arm robots and assumes a known model.

\section{Bibliography}
"""

PLAIN_DOC = """Introduction
We present the approach.

Travaux futurs
Nous prevoyons d'etendre la methode a d'autres domaines.

Annexe
"""


class TestHeadingLines(unittest.TestCase):

    def test_markdown_headings_detected(self):
        headings = [h for _, h in extract_text._heading_lines(MARKDOWN_DOC)]
        self.assertIn("Introduction", headings)
        self.assertIn("Future Work", headings)
        self.assertIn("References", headings)

    def test_latex_headings_detected(self):
        headings = [h for _, h in extract_text._heading_lines(LATEX_DOC)]
        self.assertIn("Conclusion and Limitations", headings)


class TestScanSections(unittest.TestCase):

    def test_future_work_extracted_from_markdown(self):
        sections = extract_text.scan_sections(MARKDOWN_DOC)
        labels = {s["label"] for s in sections}
        self.assertIn("future_work", labels)
        fw = next(s for s in sections if s["label"] == "future_work")
        self.assertEqual(fw["heading"], "Future Work")
        self.assertIn("extend the controller", fw["excerpt"])
        # Excerpt stops at the next heading (References must not leak in).
        self.assertNotIn("Smith et al", fw["excerpt"])

    def test_latex_conclusion_and_limitations(self):
        sections = extract_text.scan_sections(LATEX_DOC)
        labels = {s["label"] for s in sections}
        # "Conclusion and Limitations" matches the conclusion cue (first hit).
        self.assertTrue({"conclusion", "limitations"} & labels)
        joined = " ".join(s["excerpt"] for s in sections)
        self.assertIn("single-arm robots", joined)

    def test_french_future_work_plain_heading(self):
        sections = extract_text.scan_sections(PLAIN_DOC)
        labels = {s["label"] for s in sections}
        self.assertIn("future_work", labels)
        fw = next(s for s in sections if s["label"] == "future_work")
        self.assertIn("etendre la methode", fw["excerpt"])

    def test_no_sections_when_absent(self):
        sections = extract_text.scan_sections("# Intro\n\nJust body text.\n\n# Method\n\nMore text.\n")
        self.assertEqual(sections, [])

    def test_dedup_on_label_and_heading(self):
        doc = "## Future Work\n\nA.\n\n## Future Work\n\nB.\n"
        sections = extract_text.scan_sections(doc)
        self.assertEqual(len(sections), 1)


if __name__ == "__main__":
    unittest.main()
