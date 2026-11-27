"""
Purpose: Offline tests of element_labels.py (title, legend and notes of a figure or a table, spec R2).
Every page is built in the test with PyMuPDF from fictitious text (R34). No network, no model (R21).
Run as: python .claude/skills/figure-review/scripts/Test/test_element_labels.py
"""
import json
import os
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


IMAGE_RECT = fitz.Rect(100, 100, 500, 400)
IN_IMAGE_BAND = 0.15


def _line(x0, y0, x1, y1, text, line_no):
    """
    Purpose: Build the word tuples of one OCR line, the words spread evenly over its width.
    Inputs:
        x0, y0, x1, y1: float - the line box.
        text: str - the fictitious words, separated by spaces.
        line_no: int - the line number, stored as the block and line fields of each word.
    Outputs:
        list[tuple] - (x0, y0, x1, y1, word, block, line, word_no) per word.
    Raises:
        None.
    """
    words = text.split()
    step = (x1 - x0) / len(words)
    return [(x0 + index * step, y0, x0 + (index + 1) * step, y1, word, 0, line_no, index)
            for index, word in enumerate(words)]


class InImageTitleTest(unittest.TestCase):
    """
    Purpose: A title drawn inside a raster element is found in its top or bottom band (plan 24, Task 1).
    Details: Word boxes are fictitious tuples; no page is opened (R21).
    """

    def setUp(self):
        """
        Purpose: Load the shipped markers once for the class.
        Inputs:
            None.
        Outputs:
            None. Sets self.markers.
        Raises:
            None.
        """
        self.markers = el.load_markers(MARKERS_PATH)

    def test_figure_title_in_the_bottom_band_is_found_centred(self):
        """
        Purpose: A centred line starting with a figure marker in the bottom band is the title, below.
        Inputs:
            None.
        Outputs:
            None. Asserts text, position and alignment.
        Raises:
            AssertionError: If the title is missed or misplaced.
        """
        words = _line(150, 370, 450, 382, "Figure 4 Temperature", 1)
        found = el.find_in_image_title(words, IMAGE_RECT, "figure", self.markers, IN_IMAGE_BAND)
        self.assertEqual(found["position"], "in_image_bottom")
        self.assertEqual(found["alignment"], "center")
        self.assertEqual(found["text"], "Figure 4 Temperature")

    def test_table_title_in_the_top_band_is_found_left(self):
        """
        Purpose: A line starting with a table marker at the left of the top band is the title, above, left.
        Inputs:
            None.
        Outputs:
            None. Asserts position and alignment.
        Raises:
            AssertionError: If the title is missed or misplaced.
        """
        words = _line(100, 104, 220, 116, "Tableau 2 Budget", 1)
        found = el.find_in_image_title(words, IMAGE_RECT, "table", self.markers, IN_IMAGE_BAND)
        self.assertEqual(found["position"], "in_image_top")
        self.assertEqual(found["alignment"], "left")

    def test_marker_word_in_the_middle_of_the_image_is_not_a_title(self):
        """
        Purpose: A figure marker in the middle of the drawing, an axis label, is not a title.
        Inputs:
            None.
        Outputs:
            None. Asserts None.
        Raises:
            AssertionError: If the middle line is taken for a title.
        """
        words = _line(150, 200, 300, 212, "Figure of merit", 1)
        self.assertIsNone(el.find_in_image_title(words, IMAGE_RECT, "figure", self.markers, IN_IMAGE_BAND))

    def test_a_line_not_opening_with_a_marker_is_not_a_title(self):
        """
        Purpose: A bottom line that only mentions a figure later on is not a title.
        Inputs:
            None.
        Outputs:
            None. Asserts None.
        Raises:
            AssertionError: If the line is taken for a title.
        """
        words = _line(150, 370, 450, 382, "Note see Figure 4", 1)
        self.assertIsNone(el.find_in_image_title(words, IMAGE_RECT, "figure", self.markers, IN_IMAGE_BAND))

    def test_the_band_ratio_decides_the_reach_of_the_band(self):
        """
        Purpose: With a band of 5 percent (15 points) the bottom line at 370 is outside the band and is not found.
        Inputs:
            None.
        Outputs:
            None. Asserts None with the narrow band and a title with the wide one.
        Raises:
            AssertionError: If the band ratio does not change the answer.
        """
        words = _line(150, 370, 450, 382, "Figure 4 Temperature", 1)
        self.assertIsNone(el.find_in_image_title(words, IMAGE_RECT, "figure", self.markers, 0.05))
        self.assertIsNotNone(el.find_in_image_title(words, IMAGE_RECT, "figure", self.markers, IN_IMAGE_BAND))

    def test_a_figure_marker_is_not_a_table_title(self):
        """
        Purpose: The element type picks its marker words: a Figure line is no title of a table.
        Inputs:
            None.
        Outputs:
            None. Asserts None.
        Raises:
            AssertionError: If the marker of the other type is accepted.
        """
        words = _line(150, 370, 450, 382, "Figure 4 Temperature", 1)
        self.assertIsNone(el.find_in_image_title(words, IMAGE_RECT, "table", self.markers, IN_IMAGE_BAND))

    def test_unknown_element_type_and_bad_band_are_refused(self):
        """
        Purpose: An unknown element type and a band outside 0 to one half are refused with ValueError.
        Inputs:
            None.
        Outputs:
            None. Asserts both refusals.
        Raises:
            AssertionError: If a refusal is not raised.
        """
        words = _line(150, 370, 450, 382, "Figure 4 Temperature", 1)
        with self.assertRaises(ValueError):
            el.find_in_image_title(words, IMAGE_RECT, "logo", self.markers, IN_IMAGE_BAND)
        with self.assertRaises(ValueError):
            el.find_in_image_title(words, IMAGE_RECT, "figure", self.markers, 0.9)


class TextColumnAlignmentTest(unittest.TestCase):
    """
    Purpose: A title centred on the page text column is centred even when the figure sits off that column (plan 24,
        Task 2). Blocks are fictitious tuples; no page is opened (R21).
    """

    def setUp(self):
        """
        Purpose: Load the shipped markers and a figure 100 to 200 wide, under a text column 300 to 500 wide.
        Inputs:
            None.
        Outputs:
            None. Sets self.markers, self.rect and self.column.
        Raises:
            None.
        """
        self.markers = el.load_markers(MARKERS_PATH)
        self.rect = fitz.Rect(100, 100, 200, 300)
        self.column = (300.0, 500.0)

    def block(self, x0, x1, text="Figure 4 Temperature", y0=310):
        """
        Purpose: Build one title block on a fictitious line below the figure.
        Inputs:
            x0, x1 (float): the block extent.
            text (str): the fictitious text.
            y0 (float): the top of the block.
        Outputs:
            tuple: a text block tuple (x0, y0, x1, y1, text, block_no, block_type).
        Raises:
            None.
        """
        return (x0, y0, x1, y0 + 12, text, 0, 0)

    def test_a_title_centred_on_the_column_is_center(self):
        """
        Purpose: A title centred on the text column (centre 400) under a figure centred at 150 is centred.
        Inputs:
            None.
        Outputs:
            None. Asserts center with the column and right without it.
        Raises:
            AssertionError: If the column reference is not used.
        """
        title = self.block(340, 460)
        self.assertEqual(el._alignment(title, self.rect, 0.1, self.column), "center")
        self.assertEqual(el._alignment(title, self.rect, 0.1), "right")

    def test_the_figure_centre_still_decides_first(self):
        """
        Purpose: A title centred on the figure stays centred whatever the column.
        Inputs:
            None.
        Outputs:
            None. Asserts center.
        Raises:
            AssertionError: If the figure reference is lost.
        """
        self.assertEqual(el._alignment(self.block(120, 180), self.rect, 0.1, self.column), "center")

    def test_text_column_is_the_median_of_the_body_blocks(self):
        """
        Purpose: Three long blocks at 300-500, 310-510 and 320-520 give the column 310 to 510; a short caption is
            not part of it.
        Inputs:
            None.
        Outputs:
            None. Asserts the median column.
        Raises:
            AssertionError: If the median or the word filter is wrong.
        """
        long_text = " ".join(["mot"] * 8)
        blocks = [(300, 0, 500, 9, long_text, 0, 0), (310, 0, 510, 9, long_text, 0, 0),
                  (320, 0, 520, 9, long_text, 0, 0), (50, 0, 90, 9, "Note", 0, 0)]
        self.assertEqual(el.text_column(blocks, self.markers), (310.0, 510.0))

    def test_no_body_block_gives_no_column(self):
        """
        Purpose: A page with only short blocks has no column, and the rule falls back to the figure.
        Inputs:
            None.
        Outputs:
            None. Asserts None.
        Raises:
            AssertionError: If a column is invented.
        """
        self.assertIsNone(el.text_column([(10, 0, 20, 9, "Note", 0, 0)], self.markers))

    def test_the_word_count_comes_from_the_markers(self):
        """
        Purpose: A missing column_min_words key is a named error (R3).
        Inputs:
            None.
        Outputs:
            None. Asserts the MarkerError names the key.
        Raises:
            AssertionError: If the key is not required.
        """
        markers = dict(self.markers)
        markers.pop("column_min_words")
        with self.assertRaises(el.MarkerError) as raised:
            el.text_column([], markers)
        self.assertIn("column_min_words", str(raised.exception))


class TitleLineAlignmentTest(unittest.TestCase):
    """Alignment is measured on the title lines against the element edges (owner, 2026-11-27, plan 28).

    The tolerance is centre_tolerance_ratio of the element width (the shipped key, element_markers.json); the plan
    named a title_alignment_tolerance_pt key that is not in any configuration file.
    """

    RATIO = 0.1  # the shipped centre_tolerance_ratio of element_markers.json, value only for the fictitious cases

    def align(self, lines, rect):
        """Return the alignment of fictitious title lines (x0, y0, x1, y1) against an element rectangle."""
        return el.lines_alignment(lines, rect, self.RATIO)

    def test_a_two_line_left_title_whose_first_line_fills_the_width_is_left(self):
        rect = fitz.Rect(100, 100, 500, 400)
        lines = [(100, 420, 480, 432), (100, 436, 260, 448)]
        self.assertEqual(self.align(lines, rect), "left")

    def test_a_centred_short_title_above_a_wide_figure_is_center(self):
        rect = fitz.Rect(100, 100, 500, 400)
        self.assertEqual(self.align([(240, 420, 360, 432)], rect), "center")

    def test_a_centred_title_on_a_narrow_element_is_center(self):
        rect = fitz.Rect(200, 100, 400, 300)
        self.assertEqual(self.align([(240, 320, 360, 332)], rect), "center")

    def test_f11_reproduction_is_left(self):
        # Fictitious coordinates equal to the measured ones of R01: element 85.1 to 527.5, title line 85.1 to 343.2.
        rect = fitz.Rect(85.1, 409.0, 527.5, 697.0)
        self.assertEqual(self.align([(85.1, 527.5, 343.2, 539.5)], rect), "left")

    def test_f12_reproduction_is_center(self):
        rect = fitz.Rect(85.1, 292.0, 527.0, 527.0)
        self.assertEqual(self.align([(195.6, 540.0, 419.4, 552.0)], rect), "center")

    def test_f10_reproduction_is_left(self):
        rect = fitz.Rect(85.1, 84.3, 527.5, 372.4)
        self.assertEqual(self.align([(85.1, 340.0, 342.5, 352.0)], rect), "left")

    def test_a_title_that_is_neither_centred_nor_at_the_left_edge_is_right(self):
        rect = fitz.Rect(100, 100, 500, 400)
        self.assertEqual(self.align([(380, 420, 490, 432)], rect), "right")

    def test_find_title_returns_its_rectangle_and_lines_for_elements_json(self):
        doc = fitz.open()
        page = doc.new_page()
        _write_text(page, fitz.Rect(100, 402, 500, 422), "Figure 1 fictitious title", "left")
        blocks = page.get_text("blocks")
        line_boxes = [tuple(line["bbox"]) for block in page.get_text("dict")["blocks"]
                      for line in block.get("lines", [])]
        title = el.find_title(blocks, FIGURE_RECT, "figure", el.load_markers(MARKERS_PATH), None, line_boxes)
        doc.close()
        self.assertIsNotNone(title)
        self.assertEqual(title["position"], "below")
        self.assertEqual(len(title["lines"]), 1)
        self.assertEqual(len(title["rect"]), 4)
        self.assertEqual(title["alignment"], "left")

    def test_no_lines_gives_no_line_alignment(self):
        self.assertIsNone(el.lines_alignment([], fitz.Rect(100, 100, 500, 400), self.RATIO))


REAL_WORK = os.environ.get("UGS_REAL_WORK")
REAL_PDF = os.environ.get("UGS_REAL_R01")


@unittest.skipUnless(REAL_WORK and REAL_PDF, "UGS_REAL_WORK and UGS_REAL_R01 not set: real R01 not read")
class RealR01TitleAlignmentTest(unittest.TestCase):
    """The owner's reading of four figure titles of R01 (ids only, no title text is printed)."""

    EXPECTED = {"F10": "left", "F11": "left", "F12": "center", "F15": "center"}

    def test_the_four_titles_are_aligned_as_the_owner_reads_them(self):
        import json
        import re
        elements = {e["element_id"]: e for e in json.loads(
            (Path(REAL_WORK) / "R01" / "elements.json").read_text(encoding="utf-8"))}
        doc = fitz.open(REAL_PDF)
        for element_id, expected in self.EXPECTED.items():
            record = elements[element_id]
            page = doc[record["page"] - 1]
            title = re.sub(r"\s+", " ", record["title"]["text"]).strip().lower()
            lines, seen = [], set()
            for block in page.get_text("dict")["blocks"]:
                for line in block.get("lines", []):
                    text = re.sub(r"\s+", " ", "".join(s["text"] for s in line["spans"])).strip().lower()
                    box = tuple(round(v, 1) for v in line["bbox"])
                    if text and text in title and box not in seen:
                        seen.add(box)
                        lines.append(line["bbox"])
            rect = fitz.Rect(record["rect"])
            self.assertEqual(el.lines_alignment(lines, rect, 0.1), expected, element_id)
        doc.close()


if __name__ == "__main__":
    unittest.main()
