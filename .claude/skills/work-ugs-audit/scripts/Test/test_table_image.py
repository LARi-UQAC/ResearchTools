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
        markdown = table_image.words_to_markdown(words, GAP, MIN_ROWS)
        self.assertEqual(
            markdown,
            "| Mesure | Valeur | Unite |\n| --- | --- | --- |\n| Masse | 12.5 | kg |",
        )

    def test_small_gap_merges_columns(self):
        words = [_w(10, 100, "Essai"), _w(44, 100, "un")]
        self.assertEqual(table_image.words_to_rows(words, GAP), [["Essai un"]])

    def test_pipe_in_cell_is_escaped(self):
        words = [_w(10, 100, "a|b"), _w(100, 100, "c"),
                 _w(10, 120, "d"), _w(100, 120, "e")]
        markdown = table_image.words_to_markdown(words, GAP, MIN_ROWS)
        self.assertIn("a\\|b", markdown)
        self.assertNotIn("a|b", markdown)

    def test_short_row_is_padded(self):
        words = [_w(10, 100, "Mesure"), _w(100, 100, "Valeur"), _w(200, 100, "Unite"),
                 _w(10, 120, "Masse"), _w(100, 120, "12.5")]
        markdown = table_image.words_to_markdown(words, GAP, MIN_ROWS)
        self.assertIn("| Masse | 12.5 |  |", markdown)

    def test_close_baselines_are_one_row(self):
        words = [_w(10, 100, "Masse"), _w(100, 102, "12.5")]
        self.assertEqual(table_image.words_to_rows(words, GAP), [["Masse", "12.5"]])

    def test_no_words_raises_unreadable(self):
        with self.assertRaises(table_image.TableImageUnreadable):
            table_image.words_to_markdown([], GAP, MIN_ROWS)

    def test_blank_words_only_raises_unreadable(self):
        with self.assertRaises(table_image.TableImageUnreadable):
            table_image.words_to_markdown([_w(10, 100, "   ")], GAP, MIN_ROWS)

    def test_too_few_rows_raises_unreadable(self):
        words = [_w(10, 100, "Seule"), _w(100, 100, "ligne")]
        with self.assertRaises(table_image.TableImageUnreadable) as ctx:
            table_image.words_to_markdown(words, GAP, MIN_ROWS)
        self.assertIn("rows", str(ctx.exception))


class TestSettings(unittest.TestCase):
    """The two configuration keys, read with a named error when absent (R0, R3)."""

    def test_shipped_config_has_both_keys(self):
        gap, min_rows = table_image.load_image_settings()
        self.assertIsInstance(gap, (int, float))
        self.assertGreater(gap, 0)
        self.assertIsInstance(min_rows, int)
        self.assertGreater(min_rows, 0)

    def test_missing_key_is_named_with_its_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            path.write_text(json.dumps({"tables.image_column_gap_pt": {"value": 12, "provenance": "t"}}),
                            encoding="utf-8")
            with self.assertRaises(table_image.TableImageError) as ctx:
                table_image.load_image_settings(path)
            self.assertIn("tables.image_min_rows", str(ctx.exception))
            self.assertIn("config.json", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
