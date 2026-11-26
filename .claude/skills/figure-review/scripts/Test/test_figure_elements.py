"""
Purpose: Offline tests of extract_elements (spec R1, R2, R3; plan 3 task 1). Every PDF is built in the test
    with PyMuPDF from fictitious text (R34), in a temporary folder, so no report is read.
Pipeline stage: figure-review, element extraction (issue 122).
Expected runtime: a few seconds (rendering of small pages only).
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import fitz  # noqa: E402
import element_labels  # noqa: E402
import figure_extract  # noqa: E402

CRITERIA_PATH = Path(__file__).resolve().parent.parent.parent / "assets" / "figure_criteria.json"
MARKERS = element_labels.load_markers(element_labels.DEFAULT_MARKERS_PATH)
SETTINGS = {
    "min_area_pt2": 2500,
    "background_threshold": 200,
    "fragment_gap_pt": 24,
    "table_overlap_ratio": 0.6,
    "logo_max_area_pt2": 20000,
    "header_band_pt": 70,
    "repeat_min_pages": 3,
    "table_image_min_height_pt": 24,
    "logo_size_tolerance_pt": 1.0,
    "merge_max_text_words": 12,
    "text_box_min_area_ratio": 0.95,
    "text_box_min_spans": 6,
    "running_band_pt": 80,
    "group_max_gap_pt": 150,
}
ELEMENT_SETTING_KEYS = tuple(SETTINGS)


def _filled(page, x0, y0, x1, y1, grey=0.75):
    """
    Purpose: Draw a filled grey rectangle, the drawing of a figure.
    Inputs:
        page: fitz.Page - the page to draw on.
        x0, y0, x1, y1: float - the rectangle in points.
        grey: float - the grey level from 0 to 1.
    Outputs:
        None. The page is changed in place.
    Raises:
        None.
    """
    page.draw_rect(fitz.Rect(x0, y0, x1, y1), color=None, fill=(grey, grey, grey))


def _centred_text(page, centre_x, baseline_y, text):
    """
    Purpose: Write one line of text centred on a given x coordinate, with the Helvetica base font.
    Inputs:
        page: fitz.Page - the page to write on.
        centre_x: float - the horizontal centre of the line.
        baseline_y: float - the baseline of the line.
        text: str - the text, ASCII only.
    Outputs:
        None. The page is changed in place.
    Raises:
        None.
    """
    width = fitz.get_text_length(text, fontname="helv", fontsize=10)
    page.insert_text((centre_x - width / 2, baseline_y), text, fontsize=10, fontname="helv")


def _ruled_table(page, x0, y0, col_w, row_h, cells):
    """
    Purpose: Draw a table with ruled borders and write its cell text, the form a PDF table finder reads.
    Inputs:
        page: fitz.Page - the page to draw on.
        x0: float - left edge of the table.
        y0: float - top edge of the table.
        col_w: float - width of one column.
        row_h: float - height of one row.
        cells: List[List[str]] - the cell text, row by row.
    Outputs:
        None. The page is changed in place.
    Raises:
        None.
    """
    rows = len(cells)
    cols = len(cells[0])
    for i in range(rows + 1):
        y = y0 + i * row_h
        page.draw_line((x0, y), (x0 + cols * col_w, y))
    for j in range(cols + 1):
        x = x0 + j * col_w
        page.draw_line((x, y0), (x, y0 + rows * row_h))
    for r, row in enumerate(cells):
        for c, text in enumerate(row):
            page.insert_text((x0 + c * col_w + 5, y0 + r * row_h + row_h * 0.7), text, fontsize=10)


def _logo_png():
    """
    Purpose: Build a small red PNG image used as a fictitious logo.
    Inputs:
        None.
    Outputs:
        bytes - the PNG file content, 100 by 80 pixels.
    Raises:
        None.
    """
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 100, 80), False)
    pix.set_rect(pix.irect, (200, 30, 30))
    return pix.tobytes("png")


def _grid_png():
    """
    Purpose: Build a small PNG of a grid of black lines, the picture of a table with no vector border.
    Inputs:
        None.
    Outputs:
        bytes - the PNG file content, 200 by 120 pixels.
    Raises:
        None.
    """
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 200, 120), False)
    pix.set_rect(pix.irect, (255, 255, 255))
    for x in range(0, 200, 40):
        pix.set_rect(fitz.IRect(x, 0, x + 2, 120), (0, 0, 0))
    for y in range(0, 120, 30):
        pix.set_rect(fitz.IRect(0, y, 200, y + 2), (0, 0, 0))
    return pix.tobytes("png")


class TestExtractElements(unittest.TestCase):
    """Behaviour of extract_elements on fictitious PDFs (R1 tables, R2 labels, R3 merged fragments)."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tmpdir.name)
        self.pdf = self.root / "fixture.pdf"
        self.out = self.root / "out"
        self.out.mkdir()

    def tearDown(self):
        self.tmpdir.cleanup()

    def _save(self, doc):
        """
        Purpose: Write a built document to the temporary PDF path and close it.
        Inputs:
            doc: fitz.Document - the document to save.
        Outputs:
            Path - the saved PDF path.
        Raises:
            None.
        """
        doc.save(str(self.pdf))
        doc.close()
        return self.pdf

    def _extract(self, skip_pages=()):
        """
        Purpose: Run extract_elements on the temporary PDF with the test settings and markers.
        Inputs:
            skip_pages: Iterable[int] - 1-based pages to leave out.
        Outputs:
            List[Dict] - the element records.
        Raises:
            None.
        """
        return figure_extract.extract_elements(self.pdf, self.out, SETTINGS, MARKERS, skip_pages)

    def test_ruled_table_is_a_table_not_a_figure(self):
        doc = fitz.open()
        page = doc.new_page(width=612, height=792)
        _ruled_table(page, 72, 200, 120, 25, [["Mesure", "Valeur", "Unite"],
                                               ["Masse", "12.5", "kg"],
                                               ["Longueur", "3.2", "m"]])
        self._save(doc)
        records = self._extract()
        self.assertEqual([r["element_type"] for r in records], ["table"])
        self.assertEqual(records[0]["element_id"], "T-u01")

    def test_table_markdown_holds_the_cells(self):
        doc = fitz.open()
        page = doc.new_page(width=612, height=792)
        _ruled_table(page, 72, 200, 120, 25, [["Mesure", "Valeur", "Unite"],
                                               ["Masse", "12.5", "kg"],
                                               ["Longueur", "3.2", "m"]])
        self._save(doc)
        table = self._extract()[0]
        self.assertIn("12.5", table["markdown"])
        self.assertIn("Longueur", table["markdown"])
        self.assertEqual(table["legend"], "")

    def test_disconnected_diagram_is_one_figure(self):
        doc = fitz.open()
        page = doc.new_page(width=612, height=792)
        # Four boxes in two rows, joined by connectors that stop 8 points short of each box.
        _filled(page, 100, 100, 180, 140, 0.85)
        _filled(page, 200, 100, 280, 140, 0.85)
        _filled(page, 100, 200, 180, 240, 0.85)
        _filled(page, 200, 200, 280, 240, 0.85)
        page.draw_line((190, 120), (200, 120))
        page.draw_line((140, 148), (140, 192))
        page.draw_line((230, 148), (230, 192))
        _centred_text(page, 190, 260, "Figure 1: Schema du systeme")
        self._save(doc)
        records = self._extract()
        figures = [r for r in records if r["element_type"] == "figure"]
        self.assertEqual(len(figures), 1)
        self.assertEqual(figures[0]["element_id"], "F1")
        self.assertEqual([r["element_type"] for r in records], ["figure"])

    def test_title_between_figures_blocks_the_merge(self):
        doc = fitz.open()
        page = doc.new_page(width=612, height=792)
        # The gap between the two figures is 20 points, under the 24 point fragment gap,
        # and the title of the first figure lies in that gap.
        _filled(page, 100, 100, 300, 200)
        _centred_text(page, 200, 214, "Figure 1: Premier schema")
        _filled(page, 100, 220, 300, 320)
        _centred_text(page, 200, 336, "Figure 2: Second schema")
        self._save(doc)
        figures = [r for r in self._extract() if r["element_type"] == "figure"]
        self.assertEqual(len(figures), 2)
        self.assertEqual([f["element_id"] for f in figures], ["F1", "F2"])

    def test_repeated_header_image_is_a_logo(self):
        doc = fitz.open()
        for _ in range(3):
            page = doc.new_page(width=612, height=792)
            page.insert_image(fitz.Rect(40, 10, 140, 90), stream=_logo_png())
            _filled(page, 100, 300, 400, 500)
        self._save(doc)
        records = self._extract()
        logos = [r for r in records if r["element_type"] == "logo"]
        self.assertEqual([r["element_id"] for r in logos], ["L01", "L02", "L03"])
        self.assertEqual(sum(1 for r in records if r["element_type"] == "figure"), 3)

    def test_single_header_image_is_a_figure_not_a_logo(self):
        doc = fitz.open()
        page = doc.new_page(width=612, height=792)
        page.insert_image(fitz.Rect(40, 10, 140, 90), stream=_logo_png())
        self._save(doc)
        records = self._extract()
        self.assertEqual([r["element_type"] for r in records], ["figure"])

    def test_titled_table_image_is_not_a_figure(self):
        # Plan 7 (E4): a table pasted as a picture with no ruled border, under a table title.
        doc = fitz.open()
        page = doc.new_page(width=612, height=792)
        page.insert_image(fitz.Rect(100, 300, 300, 420), stream=_grid_png())
        _centred_text(page, 200, 286, "Tableau 1 : Mesures")
        self._save(doc)
        records = self._extract()
        self.assertEqual([r["element_type"] for r in records], ["table_image"])
        self.assertEqual(records[0]["element_id"], "T1")
        self.assertEqual(records[0]["title"]["text"], "Tableau 1 : Mesures")
        self.assertEqual(records[0]["legend"], "")

    def test_ruled_table_is_not_duplicated_by_a_table_image(self):
        doc = fitz.open()
        page = doc.new_page(width=612, height=792)
        _centred_text(page, 200, 186, "Tableau 1 : Mesures")
        _ruled_table(page, 72, 200, 120, 25, [["Mesure", "Valeur"],
                                               ["Masse", "12.5"]])
        self._save(doc)
        records = self._extract()
        self.assertEqual([r["element_type"] for r in records], ["table"])

    def test_untitled_thin_band_does_not_steal_a_ruled_table_title(self):
        # Review I1 (series C): a 19 point vector band with no title, directly above a ruled table whose
        # title lies between them. The table claims its title first; the band is too thin for a table_image.
        doc = fitz.open()
        page = doc.new_page(width=612, height=792)
        _filled(page, 100, 300, 300, 319)
        _centred_text(page, 200, 334, "Tableau 2 : Essais")
        _ruled_table(page, 72, 340, 120, 25, [["Mesure", "Valeur"],
                                               ["Masse", "12.5"]])
        self._save(doc)
        records = self._extract()
        table = next(r for r in records if r["element_type"] == "table")
        self.assertEqual(table["title"]["text"], "Tableau 2 : Essais")
        self.assertNotIn("table_image", [r["element_type"] for r in records])
        self.assertEqual([r["element_type"] for r in records], ["figure", "table"])

    def test_figure_title_keeps_a_figure(self):
        doc = fitz.open()
        page = doc.new_page(width=612, height=792)
        page.insert_image(fitz.Rect(100, 300, 300, 420), stream=_grid_png())
        _centred_text(page, 200, 436, "Figure 3: Trame")
        self._save(doc)
        records = self._extract()
        self.assertEqual([r["element_type"] for r in records], ["figure"])
        self.assertEqual(records[0]["element_id"], "F3")

    def test_skipped_page_gives_no_element(self):
        doc = fitz.open()
        for _ in range(3):
            page = doc.new_page(width=612, height=792)
            _filled(page, 100, 300, 400, 500)
        self._save(doc)
        records = self._extract(skip_pages=(2,))
        self.assertEqual([r["page"] for r in records], [1, 3])
        self.assertEqual([r["element_id"] for r in records], ["F-u01", "F-u02"])

    def test_titles_legend_notes_are_attached(self):
        doc = fitz.open()
        page = doc.new_page(width=612, height=792)
        _filled(page, 100, 100, 300, 250)
        page.insert_text((120, 140), "Serie A", fontsize=10, fontname="helv")
        page.insert_text((120, 160), "Serie B", fontsize=10, fontname="helv")
        _centred_text(page, 200, 266, "Figure 1: Courbes testees")
        _centred_text(page, 200, 380, "Tableau 1 : Mesures")
        _ruled_table(page, 72, 400, 120, 25, [["Mesure", "Valeur"],
                                               ["Masse", "12.5"]])
        page.insert_text((72, 462), "Note: valeurs moyennes", fontsize=10, fontname="helv")
        self._save(doc)
        records = self._extract()
        figure = next(r for r in records if r["element_type"] == "figure")
        table = next(r for r in records if r["element_type"] == "table")
        self.assertEqual(figure["title"]["text"], "Figure 1: Courbes testees")
        self.assertEqual(figure["title"]["position"], "below")
        self.assertEqual(figure["title"]["alignment"], "center")
        self.assertEqual(figure["caption"], "Figure 1: Courbes testees")
        self.assertIn("Serie A", figure["legend"])
        self.assertIn("Serie B", figure["legend"])
        self.assertEqual(table["title"]["text"], "Tableau 1 : Mesures")
        self.assertEqual(table["title"]["position"], "above")
        self.assertEqual(table["notes"], ["Note: valeurs moyennes"])

    def test_each_title_is_attached_once(self):
        doc = fitz.open()
        page = doc.new_page(width=612, height=792)
        # Figure A owns the title "Figure 1", which lies below it and 32 points above figure B.
        # Figure B has no title below it, so the same title must not be given to it a second time.
        _filled(page, 100, 100, 300, 240)
        _centred_text(page, 200, 256, "Figure 1: Alpha")
        _filled(page, 100, 290, 300, 430)
        self._save(doc)
        figures = [r for r in self._extract() if r["element_type"] == "figure"]
        self.assertEqual(len(figures), 2)
        self.assertEqual(figures[0]["title"]["text"], "Figure 1: Alpha")
        self.assertIsNone(figures[1]["title"])
        titles = [f["title"]["text"] for f in figures if f["title"]]
        self.assertEqual(len(titles), len(set(titles)))

    def test_old_extract_is_unchanged(self):
        doc = fitz.open()
        page = doc.new_page(width=612, height=792)
        _filled(page, 100, 300, 400, 500)
        _centred_text(page, 250, 520, "Figure 1: Ancien")
        self._save(doc)
        records = figure_extract.extract(self.pdf, self.out, 2500, 200)
        self.assertEqual(len(records), 1)
        self.assertEqual(
            set(records[0]),
            {"figure_id", "page", "rect", "file", "source", "drawing_area_ratio", "caption", "text_sizes"},
        )
        self.assertEqual(records[0]["caption"], "Figure 1: Ancien")

    def test_uml_fragments_with_short_labels_are_one_figure(self):
        # Plan 12 Task 1: six boxes 40 points apart, short labels between them, one title below the union.
        doc = fitz.open()
        page = doc.new_page(width=612, height=792)
        for x in (100, 220, 340):
            for y in (100, 200):
                _filled(page, x, y, x + 80, y + 40, 0.85)
        for x in (180, 300):
            for y in (120, 220):
                page.draw_line((x, y), (x + 40, y))
        page.insert_text((190, 118), "in", fontsize=8, fontname="helv")
        _centred_text(page, 260, 262, "Figure 1: Diagramme de classes")
        self._save(doc)
        figures = [r for r in self._extract() if r["element_type"] == "figure"]
        self.assertEqual(len(figures), 1)
        self.assertEqual(figures[0]["title"]["text"], "Figure 1: Diagramme de classes")

    def test_side_by_side_figures_with_titles_below_are_two_figures(self):
        doc = fitz.open()
        page = doc.new_page(width=612, height=792)
        _filled(page, 100, 100, 290, 200)
        _centred_text(page, 195, 216, "Figure 1: Premier")
        _filled(page, 300, 100, 490, 200)
        _centred_text(page, 395, 216, "Figure 2: Second")
        self._save(doc)
        figures = [r for r in self._extract() if r["element_type"] == "figure"]
        self.assertEqual(len(figures), 2)
        self.assertEqual([f["element_id"] for f in figures], ["F1", "F2"])

    def test_long_paragraph_between_figures_separates_them(self):
        doc = fitz.open()
        page = doc.new_page(width=612, height=792)
        _filled(page, 100, 100, 300, 200)
        _centred_text(page, 200, 240, "Le texte courant de ce paragraphe decrit la figure precedente en detail complet ici.")
        _filled(page, 100, 290, 300, 390)
        self._save(doc)
        figures = [r for r in self._extract() if r["element_type"] == "figure"]
        self.assertEqual(len(figures), 2)

    def test_untitled_text_box_is_not_a_figure(self):
        # Series B review: a full-width untitled band that holds running text is a text box.
        doc = fitz.open()
        page = doc.new_page(width=612, height=792)
        _filled(page, 100, 400, 500, 465, 0.75)
        page.insert_text((110, 420), "Lorem ipsum dolor sit amet consectetur", fontsize=10, fontname="helv")
        page.insert_text((110, 440), "adipiscing elit sed do eiusmod tempor", fontsize=10, fontname="helv")
        self._save(doc)
        self.assertEqual(self._extract(), [])

    def test_repeated_footer_frame_is_nothing(self):
        # Series B review: an untitled frame of 470 by 60 points at the same place on three pages is no element.
        doc = fitz.open()
        for _ in range(3):
            page = doc.new_page(width=612, height=792)
            _filled(page, 70, 722, 540, 782)
        self._save(doc)
        self.assertEqual(self._extract(), [])

    def test_repeated_footer_ruled_table_is_nothing(self):
        doc = fitz.open()
        for _ in range(3):
            page = doc.new_page(width=612, height=792)
            _ruled_table(page, 72, 735, 120, 15, [["Pied", "de page"], ["Cadre", "fixe"]])
        self._save(doc)
        self.assertEqual(self._extract(), [])

    def test_untitled_table_next_to_titled_one_is_its_continuation(self):
        doc = fitz.open()
        page = doc.new_page(width=612, height=792)
        _centred_text(page, 200, 186, "Tableau 1 : Mesures")
        _ruled_table(page, 72, 200, 120, 25, [["Mesure", "Valeur"], ["Masse", "12.5"]])
        _ruled_table(page, 72, 262, 120, 25, [["Longueur", "3.2"], ["Largeur", "4.1"]])
        self._save(doc)
        records = self._extract()
        self.assertEqual([r["element_type"] for r in records], ["table"])
        self.assertIn("Masse", records[0]["markdown"])
        self.assertIn("Largeur", records[0]["markdown"])
        self.assertEqual(records[0]["title"]["text"], "Tableau 1 : Mesures")

    def test_thin_band_above_a_table_is_part_of_the_table(self):
        doc = fitz.open()
        page = doc.new_page(width=612, height=792)
        _filled(page, 72, 300, 522, 319, 0.75)
        _ruled_table(page, 72, 321, 120, 25, [["Mesure", "Valeur"], ["Masse", "12.5"]])
        self._save(doc)
        records = self._extract()
        self.assertEqual([r["element_type"] for r in records], ["table"])
        self.assertLessEqual(records[0]["rect"][1], 301)

    def test_figure_file_named_by_printed_number(self):
        doc = fitz.open()
        page = doc.new_page(width=612, height=792)
        _filled(page, 100, 100, 300, 200)
        _centred_text(page, 200, 216, "Figure 2.3: Schema")
        self._save(doc)
        record = self._extract()[0]
        self.assertEqual(record["element_id"], "F2.3")
        self.assertEqual(record["file"], "F2.3.png")
        self.assertTrue((self.out / "F2.3.png").exists())

    def test_table_image_file_named_by_number(self):
        doc = fitz.open()
        page = doc.new_page(width=612, height=792)
        page.insert_image(fitz.Rect(100, 300, 300, 420), stream=_grid_png())
        _centred_text(page, 200, 286, "Tableau 4 : Mesures")
        self._save(doc)
        record = self._extract()[0]
        self.assertEqual(record["element_type"], "table_image")
        self.assertEqual(record["element_id"], "T4")
        self.assertEqual(record["file"], "T4.png")
        self.assertTrue((self.out / "T4.png").exists())

    def test_untitled_figure_named_u(self):
        doc = fitz.open()
        page = doc.new_page(width=612, height=792)
        _filled(page, 100, 300, 400, 500)
        self._save(doc)
        record = self._extract()[0]
        self.assertEqual(record["element_id"], "F-u01")
        self.assertEqual(record["file"], "F-u01.png")

    def test_duplicate_number_gets_suffix(self):
        doc = fitz.open()
        page = doc.new_page(width=612, height=792)
        _filled(page, 100, 100, 300, 200)
        _centred_text(page, 200, 216, "Figure 1: A")
        _filled(page, 100, 260, 300, 360)
        _centred_text(page, 200, 376, "Figure 1: B")
        self._save(doc)
        ids = [r["element_id"] for r in self._extract()]
        self.assertEqual(ids, ["F1", "F1-b"])

    def test_ruled_table_writes_no_file(self):
        doc = fitz.open()
        page = doc.new_page(width=612, height=792)
        _centred_text(page, 200, 186, "Tableau 1 : Mesures")
        _ruled_table(page, 72, 200, 120, 25, [["Mesure", "Valeur"], ["Masse", "12.5"]])
        self._save(doc)
        record = self._extract()[0]
        self.assertEqual(record["element_id"], "T1")
        self.assertIsNone(record["file"])
        self.assertFalse((self.out / "T1.png").exists())

    def test_logo_writes_no_file(self):
        doc = fitz.open()
        for _ in range(3):
            page = doc.new_page(width=612, height=792)
            page.insert_image(fitz.Rect(40, 10, 140, 90), stream=_logo_png())
            _filled(page, 100, 300, 400, 500)
        self._save(doc)
        logos = [r for r in self._extract() if r["element_type"] == "logo"]
        self.assertEqual(len(logos), 3)
        self.assertTrue(all(r["file"] is None for r in logos))
        self.assertFalse((self.out / "L01.png").exists())

    def test_title_overlapping_the_bottom_edge_is_still_below(self):
        # Plan 17 (real check on R01 page 17): the drawing's box reaches 8 points into its caption line, so the
        # caption overlaps the box by a little. It is still the caption below the drawing, not an untitled region.
        doc = fitz.open()
        page = doc.new_page(width=612, height=792)
        _filled(page, 100, 100, 300, 208)
        _centred_text(page, 200, 214, "Figure 1: Recouvrement")
        self._save(doc)
        figures = [r for r in self._extract() if r["element_type"] == "figure"]
        self.assertEqual(len(figures), 1)
        self.assertEqual(figures[0]["title"]["text"], "Figure 1: Recouvrement")
        self.assertEqual(figures[0]["title"]["position"], "below")

    def test_header_logo_near_a_figure_stays_a_logo(self):
        # Review I3: a logo 100 points above a figure is within group_max_gap_pt but must not join the figure.
        doc = fitz.open()
        for _ in range(3):
            page = doc.new_page(width=612, height=792)
            page.insert_image(fitz.Rect(40, 10, 140, 90), stream=_logo_png())
            _filled(page, 100, 190, 400, 290)
        self._save(doc)
        records = self._extract()
        self.assertEqual(sum(1 for r in records if r["element_type"] == "logo"), 3)
        self.assertEqual(sum(1 for r in records if r["element_type"] == "figure"), 3)

    def test_numbered_section_heading_between_figures_splits_them(self):
        # Review I3: a numbered heading "3.2 Resultats" between two untitled figures is a barrier.
        doc = fitz.open()
        page = doc.new_page(width=612, height=792)
        _filled(page, 100, 100, 300, 200)
        page.insert_text((100, 240), "3.2 Resultats", fontsize=12, fontname="helv")
        _filled(page, 100, 260, 300, 360)
        self._save(doc)
        figures = [r for r in self._extract() if r["element_type"] == "figure"]
        self.assertEqual(len(figures), 2)

    def test_extraction_block_holds_the_element_settings(self):
        block = json.loads(CRITERIA_PATH.read_text(encoding="utf-8"))["extraction"]
        for key in ELEMENT_SETTING_KEYS:
            self.assertIn(key, block, f"extraction block lacks {key}")
            self.assertIn("value", block[key])
            self.assertTrue(block[key]["provenance"].strip())
        self.assertEqual(block["fragment_gap_pt"]["value"], 24)
        self.assertEqual(block["table_overlap_ratio"]["value"], 0.6)


if __name__ == "__main__":
    unittest.main()
