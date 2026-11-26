import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from ugs_ledger import (
    LedgerError,
    MARKS,
    new_ledger,
    add_report,
    add_figures,
    parse,
    set_mark,
    first_open,
    counts,
    reopen_all,
    add_note,
    read,
    write,
)


class TestUgsLedger(unittest.TestCase):

    def test_add_report_writes_the_step_lines_in_order(self):
        text = new_ledger("Test Ledger")
        text = add_report(text, "R01", ["I01", "I02"])
        parsed = parse(text)
        labels = [p["label"] for p in parsed]
        expected = ["prepare", "grade I01", "grade I02", "language", "figures", "audit", "assemble"]
        self.assertEqual(labels, expected)
        self.assertTrue(all(p["mark"] == " " for p in parsed))

    def test_add_report_twice_changes_nothing(self):
        text = new_ledger("Test Ledger")
        text1 = add_report(text, "R01", ["I01"])
        text2 = add_report(text1, "R01", ["I02"])
        self.assertEqual(text1, text2)

    def test_a_report_id_that_begins_another_id_is_still_added(self):
        text = add_report(new_ledger("Test Ledger"), "R10", ["I01"])
        text = add_report(text, "R1", ["I01"])
        self.assertEqual([l for l in text.splitlines() if l.startswith("## R")], ["## R10", "## R1"])
        self.assertEqual(text.count("- [ ] prepare"), 2)

    def test_add_figures_after_the_figures_line_and_not_twice(self):
        text = new_ledger("Test Ledger")
        text = add_report(text, "R01", ["I01"])
        text = add_figures(text, "R01", ["F01", "F02"])
        parsed = parse(text)
        labels = [p["label"] for p in parsed]
        self.assertEqual(labels, ["prepare", "grade I01", "language", "figures", "figure F01", "figure F02", "audit", "assemble"])
        
        text2 = add_figures(text, "R01", ["F01"])
        self.assertEqual(text, text2)

    def test_parse_reads_marks_and_notes(self):
        text = new_ledger("Test Ledger")
        text = add_report(text, "R01", ["I01"])
        text = set_mark(text, "R01", "grade I01", "x", "note 1")
        parsed = parse(text)
        self.assertEqual(parsed[1]["mark"], "x")
        self.assertEqual(parsed[1]["note"], "note 1")

    def test_set_mark_changes_exactly_one_line(self):
        text = new_ledger("Test Ledger")
        text = add_report(text, "R01", ["I01"])
        text = add_report(text, "R02", ["I01"])
        text = set_mark(text, "R01", "grade I01", "x")
        parsed = parse(text)
        self.assertEqual(parsed[1]["mark"], "x")
        self.assertEqual(parsed[4]["mark"], " ")

    def test_unknown_label_report_or_mark_raises(self):
        text = new_ledger("Test Ledger")
        text = add_report(text, "R01", ["I01"])
        with self.assertRaises(LedgerError):
            set_mark(text, "R01", "unknown", "x")
        with self.assertRaises(LedgerError):
            set_mark(text, "R02", "grade I01", "x")
        with self.assertRaises(LedgerError):
            set_mark(text, "R01", "grade I01", "y")

    def test_note_with_accents_newline_or_61_characters_is_refused(self):
        text = new_ledger("Test Ledger")
        text = add_report(text, "R01", ["I01"])
        with self.assertRaises(LedgerError):
            set_mark(text, "R01", "grade I01", "x", "accent é")
        with self.assertRaises(LedgerError):
            set_mark(text, "R01", "grade I01", "x", "line1\nline2")
        with self.assertRaises(LedgerError):
            set_mark(text, "R01", "grade I01", "x", "a" * 61)

    def test_first_open_follows_file_order(self):
        text = new_ledger("Test Ledger")
        text = add_report(text, "R01", ["I01"])
        text = add_report(text, "R02", ["I01"])
        text = set_mark(text, "R02", "prepare", "x")
        self.assertEqual(first_open(text), ("R01", "prepare"))

    def test_first_open_is_none_when_nothing_is_open(self):
        text = new_ledger("Test Ledger")
        text = add_report(text, "R01", ["I01"])
        for line in parse(text):
            text = set_mark(text, "R01", line["label"], "x")
        self.assertIsNone(first_open(text))

    def test_counts(self):
        text = new_ledger("Test Ledger")
        text = add_report(text, "R01", ["I01"])
        text = set_mark(text, "R01", "prepare", "x")
        text = set_mark(text, "R01", "grade I01", "!")
        c = counts(text)
        self.assertEqual(c["done"], 1)
        self.assertEqual(c["blocked"], 1)
        self.assertEqual(c["open"], 4)

    def test_reopen_all_keeps_the_named_labels(self):
        text = new_ledger("Test Ledger")
        text = add_report(text, "R01", ["I01"])
        text = set_mark(text, "R01", "prepare", "x", "note")
        text = set_mark(text, "R01", "grade I01", "x")
        text = reopen_all(text, ["prepare"])
        parsed = parse(text)
        self.assertEqual(parsed[0]["mark"], "x")
        self.assertEqual(parsed[0]["note"], "note")
        self.assertEqual(parsed[1]["mark"], " ")
        self.assertIsNone(parsed[1]["note"])

    def test_add_note_is_checked_like_a_note(self):
        text = new_ledger("Test Ledger")
        text = add_note(text, "valid note")
        self.assertIn("valid note", text)
        with self.assertRaises(LedgerError):
            add_note(text, "invalid é")

    def test_write_is_atomic_and_read_round_trips(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "ledger.md"
            text = new_ledger("Test Ledger")
            write(path, text)
            self.assertEqual(read(path), text)


class TestFiguresLineAnyMark(unittest.TestCase):
    """Review fix: a new figure id is added even when the figures line was already settled by an earlier run."""

    def test_a_new_figure_is_added_when_the_figures_line_is_done(self):
        from ugs_ledger import add_report, add_figures, set_mark
        text = add_report("", "R01", ["grade I01", "figures"])
        text = set_mark(text, "R01", "figures", "x")
        text = add_figures(text, "R01", ["F1", "T-i03"])
        self.assertIn("- [ ] figure T-i03", text)
        self.assertIn("- [ ] figure F1", text)

    def test_a_new_figure_is_added_when_the_figures_line_is_blocked(self):
        from ugs_ledger import add_report, add_figures, set_mark
        text = add_report("", "R01", ["grade I01", "figures"])
        text = set_mark(text, "R01", "figures", "!", "error")
        text = add_figures(text, "R01", ["T-i03"])
        self.assertIn("- [ ] figure T-i03", text)


if __name__ == "__main__":
    unittest.main()
