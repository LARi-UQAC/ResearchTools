"""
Purpose: Offline tests of element_labels.py (title, legend and notes of a figure or a table, spec R2).
Every page is built in the test with PyMuPDF from fictitious text (R34). No network, no model (R21).
Run as: python .claude/skills/figure-review/scripts/Test/test_element_labels.py
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

import fitz

sys.path.insert(0, str(Path(__file__).parent.parent))

import element_labels as el  # noqa: E402

MARKERS_PATH = Path(__file__).parent.parent.parent / "assets" / "element_markers.json"
TITLE_BOX_HEIGHT = 20
FIGURE_RECT = fitz.Rect(100, 100, 500, 400)
TABLE_RECT = fitz.Rect(100, 300, 500, 500)


def _write_text(page, rect, text, align):
    """
    Purpose: Insert a text block that fits its box, so the block bounding box is the text extent.
    Inputs:
        page: fitz.Page - the page to write on.
        rect: fitz.Rect - the box.
        text: str - the fictitious text.
        align: int - a fitz.TEXT_ALIGN_* constant.
    Outputs:
        None. The text is written on the page.
    Raises:
        AssertionError: If the text does not fit its box (the test would otherwise measure nothing).
    """
    result = page.insert_textbox(rect, text, fontsize=10, fontname="helv", align=align)
    assert result >= 0, f"text does not fit its box: {text!r}"


class ElementLabelsTest(unittest.TestCase):
    """Tests of the title, legend and notes finders on fictitious pages."""

    def setUp(self):
        self.doc = fitz.open()
        self.page = self.doc.new_page(width=595, height=842)
        self.markers = el.load_markers(MARKERS_PATH)

    def tearDown(self):
        self.doc.close()

    def _blocks(self, page=None):
        """
        Purpose: Return the text blocks of a page in the form element_labels expects.
        Inputs:
            page: fitz.Page or None - the page, the test page when None.
        Outputs:
            list - the tuples of page.get_text("blocks").
        Raises:
            None.
        """
        return (page or self.page).get_text("blocks")

    def test_figure_title_below_centered(self):
        """A figure title centred below the figure is found below, centred."""
        _write_text(self.page, fitz.Rect(100, 410, 500, 430),
                    "Figure 2 Architecture du systeme", fitz.TEXT_ALIGN_CENTER)
        title = el.find_title(self._blocks(), FIGURE_RECT, "figure", self.markers)
        self.assertIsNotNone(title)
        self.assertTrue(title["text"].startswith("Figure 2"))
        self.assertEqual(title["position"], "below")
        self.assertEqual(title["alignment"], "center")

    def test_table_title_above_left(self):
        """A table title left aligned above the table is found above, left aligned."""
        _write_text(self.page, fitz.Rect(100, 280, 500, 300),
                    "Tableau 3 Resultats", fitz.TEXT_ALIGN_LEFT)
        title = el.find_title(self._blocks(), TABLE_RECT, "table", self.markers)
        self.assertIsNotNone(title)
        self.assertTrue(title["text"].startswith("Tableau 3"))
        self.assertEqual(title["position"], "above")
        self.assertEqual(title["alignment"], "left")

    def test_alignment_is_measured_from_the_block(self):
        """Left and right alignments are read from the block, not assumed from the position."""
        for align, expected in ((fitz.TEXT_ALIGN_LEFT, "left"), (fitz.TEXT_ALIGN_RIGHT, "right")):
            page = self.doc.new_page(width=595, height=842)
            _write_text(page, fitz.Rect(100, 410, 500, 430), "Figure 4 Bilan", align)
            title = el.find_title(self._blocks(page), FIGURE_RECT, "figure", self.markers)
            self.assertIsNotNone(title, expected)
            self.assertEqual(title["alignment"], expected)

    def test_no_title_beyond_the_distance(self):
        """A title far from the element is not attached; a near one is (the control)."""
        _write_text(self.page, fitz.Rect(100, 410, 500, 430), "Figure 9 Tout pres", fitz.TEXT_ALIGN_CENTER)
        self.assertIsNotNone(el.find_title(self._blocks(), FIGURE_RECT, "figure", self.markers))
        far = self.doc.new_page(width=595, height=842)
        _write_text(far, fitz.Rect(100, 500, 500, 520), "Figure 9 Trop loin", fitz.TEXT_ALIGN_CENTER)
        self.assertIsNone(el.find_title(self._blocks(far), FIGURE_RECT, "figure", self.markers))

    def test_legend_is_text_inside_the_region(self):
        """Words inside the element rectangle form the legend; words outside it do not."""
        self.page.insert_text((120, 130), "Series A", fontsize=10)
        self.page.insert_text((120, 150), "Series B", fontsize=10)
        self.page.insert_text((120, 600), "outside", fontsize=10)
        legend = el.find_legend(self.page.get_text("words"), FIGURE_RECT, None)
        words = legend.split()
        self.assertIn("Series", words)
        self.assertIn("A", words)
        self.assertIn("B", words)
        self.assertNotIn("outside", words)

    def test_legend_excludes_the_words_of_the_title(self):
        """A title lying inside the rectangle is not repeated in the legend."""
        self.page.insert_text((120, 115), "Figure 2 Architecture", fontsize=10)
        self.page.insert_text((120, 140), "Series A", fontsize=10)
        legend = el.find_legend(self.page.get_text("words"), FIGURE_RECT, "Figure 2 Architecture")
        words = legend.split()
        self.assertIn("Series", words)
        self.assertNotIn("Figure", words)
        self.assertNotIn("Architecture", words)

    def test_notes_stop_at_first_non_note(self):
        """Notes under a table are taken until the first block that is not a note."""
        table = fitz.Rect(100, 100, 500, 300)
        _write_text(self.page, fitz.Rect(100, 305, 500, 325), "Note: donnees 2026", fitz.TEXT_ALIGN_LEFT)
        _write_text(self.page, fitz.Rect(100, 325, 500, 345), "Source: DGA", fitz.TEXT_ALIGN_LEFT)
        _write_text(self.page, fitz.Rect(100, 345, 500, 365), "Figure 5 Un autre element", fitz.TEXT_ALIGN_LEFT)
        _write_text(self.page, fitz.Rect(100, 365, 500, 385), "Note: apres la rupture", fitz.TEXT_ALIGN_LEFT)
        notes = el.find_notes(self._blocks(), table, self.markers)
        self.assertEqual(len(notes), 2)
        self.assertTrue(notes[0].startswith("Note"))
        self.assertTrue(notes[1].startswith("Source"))

    def test_marker_words_french_and_english(self):
        """French and English marker words are both recognised, for figures, tables and notes."""
        self.assertIn("Figure", self.markers["figure_prefixes"])
        self.assertIn("Fig.", self.markers["figure_prefixes"])
        self.assertIn("Tableau", self.markers["table_prefixes"])
        self.assertIn("Table", self.markers["table_prefixes"])
        self.assertIn("Note", self.markers["note_prefixes"])
        self.assertIn("Source", self.markers["note_prefixes"])
        _write_text(self.page, fitz.Rect(100, 410, 500, 430), "Fig. 2 Schema", fitz.TEXT_ALIGN_CENTER)
        title = el.find_title(self._blocks(), FIGURE_RECT, "figure", self.markers)
        self.assertIsNotNone(title)
        self.assertTrue(title["text"].startswith("Fig. 2"))

    def test_missing_key_is_named(self):
        """A missing key in the data file raises a named error naming the key and the file (R3)."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "broken_markers.json"
            data = json.loads(MARKERS_PATH.read_text(encoding="utf-8"))
            del data["note_prefixes"]
            path.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaises(el.MarkerError) as ctx:
                el.load_markers(path)
            self.assertIn("note_prefixes", str(ctx.exception))
            self.assertIn("broken_markers.json", str(ctx.exception))

    def test_missing_distance_value_is_named(self):
        """A distance without its value or provenance is a named error (R4)."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "no_value.json"
            data = json.loads(MARKERS_PATH.read_text(encoding="utf-8"))
            data["max_note_distance_pt"] = {"provenance": "x"}
            path.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaises(el.MarkerError) as ctx:
                el.load_markers(path)
            self.assertIn("max_note_distance_pt", str(ctx.exception))

    def test_unknown_element_type_is_refused(self):
        """An element type other than figure or table is refused, not guessed."""
        with self.assertRaises(ValueError):
            el.find_title(self._blocks(), FIGURE_RECT, "logo", self.markers)


if __name__ == "__main__":
    unittest.main()
