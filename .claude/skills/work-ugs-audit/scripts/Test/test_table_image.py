"""
Purpose: Offline tests of table_image.py (plan 8 task 1, spec E3): word boxes of a table drawn as an image become
    Markdown rows. Words are plain tuples built in the test (R34), no OCR and no PDF is needed.
Pipeline stage: work-ugs-audit, page text preparation (issue 126).
Expected runtime: under one second.
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import table_image  # noqa: E402

GAP = 12
MIN_ROWS = 2
OVERLAP = 0.5


def _w(x0, y0, text, width=30, height=10):
    """
    Purpose: Build one word tuple as PyMuPDF returns it from get_text("words").
    Inputs:
        x0: float - left edge in points.
        y0: float - top edge in points.
        text: str - the word.
        width: float - the word width in points.
        height: float - the word height in points.
    Outputs:
        tuple - (x0, y0, x1, y1, text, block_no, line_no, word_no).
    Raises:
        None.
    """
    return (x0, y0, x0 + width, y0 + height, text, 0, 0, 0)


class TestWordsToRows(unittest.TestCase):
    """Rows and cells from word boxes, without OCR."""

    def test_two_rows_three_columns_become_markdown(self):
        words = [_w(10, 100, "Mesure"), _w(100, 100, "Valeur"), _w(200, 100, "Unite"),
                 _w(10, 120, "Masse"), _w(100, 120, "12.5"), _w(200, 120, "kg")]
        markdown = table_image.words_to_markdown(words, GAP, MIN_ROWS, OVERLAP)
        self.assertEqual(
            markdown,
            "| Mesure | Valeur | Unite |\n| --- | --- | --- |\n| Masse | 12.5 | kg |",
        )

    def test_small_gap_merges_columns(self):
        words = [_w(10, 100, "Essai"), _w(44, 100, "un")]
        self.assertEqual(table_image.words_to_rows(words, GAP, OVERLAP), [["Essai un"]])

    def test_pipe_in_cell_is_escaped(self):
        words = [_w(10, 100, "a|b"), _w(100, 100, "c"),
                 _w(10, 120, "d"), _w(100, 120, "e")]
        markdown = table_image.words_to_markdown(words, GAP, MIN_ROWS, OVERLAP)
        self.assertIn("a\\|b", markdown)
        self.assertNotIn("a|b", markdown)

    def test_short_row_is_padded(self):
        words = [_w(10, 100, "Mesure"), _w(100, 100, "Valeur"), _w(200, 100, "Unite"),
                 _w(10, 120, "Masse"), _w(100, 120, "12.5")]
        markdown = table_image.words_to_markdown(words, GAP, MIN_ROWS, OVERLAP)
        self.assertIn("| Masse | 12.5 |  |", markdown)

    def test_close_baselines_are_one_row(self):
        words = [_w(10, 100, "Masse"), _w(100, 102, "12.5")]
        self.assertEqual(table_image.words_to_rows(words, GAP, OVERLAP), [["Masse", "12.5"]])

    def test_overlap_ratio_from_configuration_changes_the_rows(self):
        # Review M2: boxes offset by 6 points overlap by 4 of 10. One row at 0.3 (4 >= 3), two at 0.5 (4 < 5).
        words = [_w(10, 100, "Masse"), _w(100, 106, "12.5")]
        self.assertEqual(table_image.words_to_rows(words, GAP, 0.3), [["Masse", "12.5"]])
        self.assertEqual(len(table_image.words_to_rows(words, GAP, 0.5)), 2)

    def test_no_words_raises_unreadable(self):
        with self.assertRaises(table_image.TableImageUnreadable):
            table_image.words_to_markdown([], GAP, MIN_ROWS, OVERLAP)

    def test_blank_words_only_raises_unreadable(self):
        with self.assertRaises(table_image.TableImageUnreadable):
            table_image.words_to_markdown([_w(10, 100, "   ")], GAP, MIN_ROWS, OVERLAP)

    def test_too_few_rows_raises_unreadable(self):
        words = [_w(10, 100, "Seule"), _w(100, 100, "ligne")]
        with self.assertRaises(table_image.TableImageUnreadable) as ctx:
            table_image.words_to_markdown(words, GAP, MIN_ROWS, OVERLAP)
        self.assertIn("rows", str(ctx.exception))
        self.assertNotIn("Seule", str(ctx.exception))


class TestSettings(unittest.TestCase):
    """The configuration keys, read with a named error when absent or invalid (R0, R3)."""

    def _write(self, tmp, entries):
        """
        Purpose: Write a fictitious configuration file holding the given entries.
        Inputs:
            tmp: str - the temporary folder.
            entries: dict - the configuration entries.
        Outputs:
            Path - the file written.
        Raises:
            None.
        """
        path = Path(tmp) / "config.json"
        path.write_text(json.dumps(entries), encoding="utf-8")
        return path

    def test_shipped_config_has_every_key(self):
        settings = table_image.load_image_settings()
        self.assertGreater(settings.column_gap_pt, 0)
        self.assertIsInstance(settings.min_rows, int)
        self.assertGreater(settings.min_rows, 0)
        self.assertGreater(settings.row_overlap_ratio, 0)
        self.assertLessEqual(settings.row_overlap_ratio, 1)

    def test_missing_key_is_named_with_its_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(tmp, {"tables.image_column_gap_pt": {"value": 12, "provenance": "t"},
                                     "tables.image_min_rows": {"value": 2, "provenance": "t"}})
            with self.assertRaises(table_image.TableImageError) as ctx:
                table_image.load_image_settings(path)
            self.assertIn("tables.image_row_overlap_ratio", str(ctx.exception))
            self.assertIn("config.json", str(ctx.exception))

    def test_overlap_ratio_outside_zero_one_is_named(self):
        # Review M2: a ratio above 1 can never be reached, so it is refused by name.
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(tmp, {"tables.image_column_gap_pt": {"value": 12, "provenance": "t"},
                                     "tables.image_min_rows": {"value": 2, "provenance": "t"},
                                     "tables.image_row_overlap_ratio": {"value": 2, "provenance": "t"}})
            with self.assertRaises(table_image.TableImageError) as ctx:
                table_image.load_image_settings(path)
            self.assertIn("tables.image_row_overlap_ratio", str(ctx.exception))




class UntitledClassificationTests(unittest.TestCase):
    """Plan 11 E5: an untitled region is a table_image only when its OCR rebuilds a grid of the configured size."""

    GAP = 12
    OVERLAP = 0.5

    @staticmethod
    def _grid(rows, cols):
        """
        Purpose: Build fictitious word boxes laid out as a grid of rows by cols words, 60 points apart per column.
        Inputs:
            rows: int - number of rows.
            cols: int - number of columns.
        Outputs:
            list[tuple] - PyMuPDF-shaped word tuples.
        Raises:
            None.
        """
        words = []
        for r in range(rows):
            for c in range(cols):
                x0 = 100 + c * 100
                y0 = 100 + r * 15
                words.append((x0, y0, x0 + 40, y0 + 10, f"w{r}{c}", 0, 0, 0))
        return words

    def test_untitled_grid_is_table_image(self):
        self.assertEqual(table_image.classify_untitled(self._grid(3, 3), self.GAP, 2, 3, self.OVERLAP), "table_image")

    def test_untitled_diagram_labels_stay_figure(self):
        labels = self._grid(2, 2)
        self.assertEqual(table_image.classify_untitled(labels, self.GAP, 2, 3, self.OVERLAP), "figure")

    def test_no_words_is_figure(self):
        self.assertEqual(table_image.classify_untitled([], self.GAP, 2, 3, self.OVERLAP), "figure")

    def test_below_min_cols_is_figure(self):
        self.assertEqual(table_image.classify_untitled(self._grid(3, 2), self.GAP, 2, 3, self.OVERLAP), "figure")

    def test_below_min_rows_is_figure(self):
        self.assertEqual(table_image.classify_untitled(self._grid(1, 3), self.GAP, 2, 3, self.OVERLAP), "figure")


if __name__ == "__main__":
    unittest.main()
