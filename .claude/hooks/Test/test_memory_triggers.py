"""
Offline suite for the table in .claude/rules/workflows.md that says when memory is read and
written through `local-writer` (plan5 of the docs-site-links effort). Documentation only, standard
library, no vault read.

Origin: the owner doubted, 2026-10-17, that memory writes happen every time. Read the same day: the
three upkeep dispatches that day each produced a note, so the gap was not a failing write. No
single rule said WHEN to dispatch, a dispatch runs in the background so the session never saw its
outcome, and the triggers lived in several files. This suite pins one table.

Proves the table is written, complete and consistent. Does not prove a model obeys it.
"""

import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
RULES = REPO / ".claude" / "rules" / "workflows.md"
HEADING = "### When memory is read and written"
COLUMNS = ("Event", "Action", "Target", "Verified by")
# Events the table must name, as a substring of the Event cell, with the action expected.
EVENTS = (
    ("before brainstorming or planning", "Read"),
    ("loop start", "Read"),
    ("checkpoint", "Read"),
    ("error recovery", "Read"),
    ("failure with a root cause", "Write"),
    ("loop checkpoint", "Write"),
    ("significant review finding", "Write"),
    ("gate reached or loop finished", "Write"),
    ("correction or new method", "Write"),
    ("code added or changed", "Write"),
    ("end of the task", "Write"),
)
MUST_NOT = ("executing-plans", "cloud review", "local-coder")


def read_table(text: str) -> list:
    """
    --------------------------------------------------------------------------
    Purpose:
        Parse the Markdown table that follows the memory-trigger heading.

    Inputs:
        text (str): the whole workflows.md text.

    Outputs:
        rows (list[list[str]]): the body rows, cells stripped; the header and separator dropped.

    Raises:
        AssertionError: the heading is missing.
    --------------------------------------------------------------------------
    """
    assert HEADING in text, f"missing heading: {HEADING}"
    block = text.split(HEADING, 1)[1].split("\n#", 1)[0]
    lines = [ln for ln in block.splitlines() if ln.strip().startswith("|")]
    rows = [[c.strip() for c in ln.strip().strip("|").split("|")] for ln in lines]
    return rows[2:]


def empty_cells(rows: list) -> list:
    """The (row number, column) of every empty or missing cell."""
    return [
        (i, COLUMNS[j])
        for i, row in enumerate(rows, 1)
        for j in range(len(COLUMNS))
        if j >= len(row) or not row[j]
    ]


class TriggerTable(unittest.TestCase):
    def setUp(self):
        self.text = RULES.read_text(encoding="utf-8")

    def test_the_table_exists_with_four_columns(self):
        rows = read_table(self.text)
        self.assertGreaterEqual(len(rows), len(EVENTS))
        self.assertTrue(all(len(r) == len(COLUMNS) for r in rows), rows)

    def test_no_cell_is_empty(self):
        self.assertEqual([], empty_cells(read_table(self.text)))

    def test_every_event_is_named_with_its_action(self):
        rows = read_table(self.text)
        for event, action in EVENTS:
            hits = [r for r in rows if event in r[0].lower()]
            self.assertTrue(hits, f"no row for: {event}")
            self.assertTrue(any(r[1].startswith(action) for r in hits), (event, action))

    def test_who_must_not_read_is_stated(self):
        rows = read_table(self.text)
        for who in MUST_NOT:
            hits = [r for r in rows if who in r[0].lower()]
            self.assertTrue(hits, f"no row for: {who}")
            self.assertTrue(all(r[1].startswith("Never") for r in hits), who)

    def test_the_graph_refresh_names_the_repository_root(self):
        rows = read_table(self.text)
        row = next(r for r in rows if "code added or changed" in r[0].lower())
        self.assertIn("repository root", " ".join(row))

    def test_dispatch_mode_and_result_form_are_stated_under_the_table(self):
        after = self.text.split(HEADING, 1)[1]
        for phrase in ("background", "one line", "one agent, sequential"):
            self.assertIn(phrase, after)

    def test_finder_negative_controls(self):
        bad = f"{HEADING}\n\n| Event | Action | Target | Verified by |\n|---|---|---|---|\n| x | Read | | y |\n"
        self.assertEqual([(1, "Target")], empty_cells(read_table(bad)))
        with self.assertRaises(AssertionError):
            read_table("no heading here")


if __name__ == "__main__":
    unittest.main()
