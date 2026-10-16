"""Tests for outbox_io.py's set-property directive and the function behind
it, set_frontmatter_property.

Added 2026-10-02 after a real failure: a staged note meant to add a `repo:`
key to an EXISTING vault note was written as an `append` directive. append
(and create-on-an-existing-file, which degrades to append) always tacks the
whole new block onto the END of the file, producing a SECOND `---`
frontmatter block - never read as frontmatter by anything (Obsidian itself,
or daemon_graph.read_repo_property, which only matches the block at the
very start of the file). There was no existing operation that could add one
key to an existing note's frontmatter without this corruption; this is it.
"""
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


class SetFrontmatterPropertyCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def _note(self, name, text):
        path = self.tmp / name
        path.write_text(text, encoding="utf-8")
        return path

    def test_adds_a_new_key_preserving_every_existing_one(self):
        import outbox_io
        note = self._note("n.md",
                          "---\ntype: projet\ndomaine: logiciel\n"
                          "statut: actif\ntags: [x, y]\n---\n\n"
                          "# Title\n\nBody text.\n")
        ok, before, after = outbox_io.set_frontmatter_property(
            note, "repo", r"C:\Martin Otis\OutilsLogiciels\Demo")
        self.assertTrue(ok)
        text = note.read_text(encoding="utf-8")
        # Exactly ONE frontmatter block - the fix this test exists for.
        self.assertEqual(text.count("---"), 2)
        self.assertIn("type: projet", text)
        self.assertIn("domaine: logiciel", text)
        self.assertIn("statut: actif", text)
        self.assertIn("tags: [x, y]", text)
        self.assertIn(r"repo: C:\Martin Otis\OutilsLogiciels\Demo", text)
        self.assertIn("# Title", text)
        self.assertIn("Body text.", text)

    def test_replaces_an_existing_keys_value_rather_than_duplicating_it(self):
        import outbox_io
        note = self._note("n.md",
                          "---\ntype: projet\nrepo: old-value\n---\n\nbody\n")
        ok, before, after = outbox_io.set_frontmatter_property(
            note, "repo", "new-value")
        self.assertTrue(ok)
        text = note.read_text(encoding="utf-8")
        self.assertEqual(text.count("repo:"), 1)
        self.assertIn("repo: new-value", text)
        self.assertNotIn("old-value", text)

    def test_ok_is_verified_by_reading_back_not_by_a_size_delta(self):
        """A replacement value SHORTER than the original shrinks the file -
        a size-delta heuristic (as write_note's `after > before` uses for
        append) would misread success as failure here."""
        import outbox_io
        note = self._note("n.md",
                          "---\nrepo: a-very-long-previous-value-indeed\n"
                          "---\n\nbody\n")
        ok, before, after = outbox_io.set_frontmatter_property(
            note, "repo", "x")
        self.assertTrue(ok)
        self.assertLess(after, before)

    def test_a_multiline_value_is_refused_before_writing(self):
        """A staged directive's body can carry more than one content line (a
        malformed stage, or a future caller forgetting the one-line rule).
        Embedding it verbatim would insert extra frontmatter lines; refuse
        before the file is touched rather than after a corrupting write that
        the outbox would then replay forever."""
        import outbox_io
        note = self._note("n.md", "---\ntype: projet\n---\n\nbody\n")
        original = note.read_text(encoding="utf-8")
        with self.assertRaises(outbox_io.FrontmatterError):
            outbox_io.set_frontmatter_property(
                note, "repo", "first-line\nsecond-line")
        self.assertEqual(note.read_text(encoding="utf-8"), original)

    def test_a_cr_only_value_is_also_refused(self):
        import outbox_io
        note = self._note("n.md", "---\ntype: projet\n---\n\nbody\n")
        with self.assertRaises(outbox_io.FrontmatterError):
            outbox_io.set_frontmatter_property(note, "repo", "a\rb")

    def test_missing_file_raises_rather_than_creating_one(self):
        import outbox_io
        absent = self.tmp / "absent.md"
        with self.assertRaises(outbox_io.FrontmatterError):
            outbox_io.set_frontmatter_property(absent, "repo", "x")
        self.assertFalse(absent.exists())

    def test_a_value_starting_with_hash_or_colon_round_trips_verbatim(self):
        """PR #49 re-review M8: a value beginning with # or : is still a
        single line (no CR/LF), so it is written and read back verbatim by
        this module's own regex-based reader - a real YAML engine (Obsidian's
        own) might read a leading # as a comment, which is a presentation
        difference from Obsidian's rendering, not a corruption of what this
        module itself writes or reads."""
        import daemon_graph
        import outbox_io
        for value in ("#not-a-comment-here", ":looks-like-a-mapping"):
            with self.subTest(value=value):
                note = self._note("n.md", "---\ntype: projet\n---\n\nbody\n")
                ok, before, after = outbox_io.set_frontmatter_property(
                    note, "repo", value)
                self.assertTrue(ok)
                self.assertEqual(
                    daemon_graph.read_repo_property(note), value)

    def test_a_file_with_no_frontmatter_block_raises(self):
        import outbox_io
        note = self._note("n.md", "# Title\n\nno frontmatter at all\n")
        with self.assertRaises(outbox_io.FrontmatterError):
            outbox_io.set_frontmatter_property(note, "repo", "x")

    def test_idempotent_replay_is_a_true_noop(self):
        import outbox_io
        note = self._note("n.md",
                          "---\ntype: projet\n---\n\nbody\n")
        outbox_io.set_frontmatter_property(note, "repo", "fixed-value")
        text_once = note.read_text(encoding="utf-8")
        ok, before, after = outbox_io.set_frontmatter_property(
            note, "repo", "fixed-value")
        self.assertTrue(ok)
        self.assertEqual(before, after)
        self.assertEqual(text_once, note.read_text(encoding="utf-8"))

    def test_body_and_line_order_are_otherwise_untouched(self):
        import outbox_io
        original = ("---\na: 1\nb: 2\nc: 3\n---\n\n"
                   "# Heading\n\nParagraph one.\n\nParagraph two.\n"
                   "- a list item\n- another\n")
        note = self._note("n.md", original)
        outbox_io.set_frontmatter_property(note, "repo", "x")
        text = note.read_text(encoding="utf-8")
        body_start = text.index("# Heading")
        self.assertEqual(text[body_start:], original[original.index("# Heading"):])


class ParseDirectiveSetPropertyCase(unittest.TestCase):
    def test_parses_the_set_property_directive(self):
        import outbox_io
        action, rel, content, key = outbox_io.parse_directive(
            '<!-- obsidian: set-property path="10_Projets/X/index.md" '
            'key="repo" -->\nC:\\some\\path\n')
        self.assertEqual(action, "set-property")
        self.assertEqual(rel, "10_Projets/X/index.md")
        self.assertEqual(key, "repo")
        self.assertEqual(content.strip(), "C:\\some\\path")

    def test_create_and_append_still_return_a_none_key(self):
        import outbox_io
        action, rel, content, key = outbox_io.parse_directive(
            '<!-- obsidian: create path="x.md" -->\nbody\n')
        self.assertEqual(action, "create")
        self.assertIsNone(key)

    def test_a_non_directive_first_line_returns_all_none(self):
        import outbox_io
        self.assertEqual(outbox_io.parse_directive("no directive here\n"),
                         (None, None, None, None))


class FlushOneSetPropertyJournalCase(unittest.TestCase):
    """flush_one journals a set-property write as a SNAPSHOT (full pre-edit
    text), not a size-based WRITE record. vault_journal.undo() reverses a
    WRITE by truncating to the old byte count, which only reverses an
    append; a set-property edit happens in the MIDDLE of the file and can
    shrink it (a shorter value replacing a longer one), so a WRITE record
    would make undo() either corrupt the note (chop bytes off the body
    while leaving the new value in place) or refuse outright."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.vault = self.tmp / "vault"
        self.vault.mkdir()
        self.outbox = self.tmp / "outbox"
        self.sent = self.outbox / "sent"
        self.journal = self.tmp / "journal.jsonl"

    def _note(self, rel, text):
        path = self.vault / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def _stage(self, directive, content):
        self.outbox.mkdir(parents=True, exist_ok=True)
        path = self.outbox / "item.md"
        path.write_text(f"{directive}\n{content}", encoding="utf-8")
        return path

    def test_set_property_is_journaled_as_a_snapshot_not_a_write(self):
        import outbox_io
        import vault_journal
        self._note("n.md",
                  "---\nrepo: a-very-long-previous-value-indeed\n---\n\nbody\n")
        md = self._stage(
            '<!-- obsidian: set-property path="n.md" key="repo" -->', "x")
        ok = outbox_io.flush_one(md, self.vault, self.sent, self.journal)
        self.assertTrue(ok)
        records = vault_journal.read_records(self.journal)
        states = [r["state"] for r in records]
        self.assertIn(vault_journal.STATE_SNAPSHOT, states)
        self.assertNotIn(vault_journal.STATE_WRITE, states)

    def test_undo_restores_the_exact_text_even_when_the_edit_shrank_the_file(self):
        """The failure mode a size-based record would reproduce: the
        replacement ("x") is shorter than the original value, so a
        before/after byte count and a truncate-based undo land on the wrong
        bytes. The snapshot-based undo must restore byte-for-byte."""
        import outbox_io
        import vault_journal
        original = "---\nrepo: a-very-long-previous-value-indeed\n---\n\nbody\n"
        note = self._note("n.md", original)
        md = self._stage(
            '<!-- obsidian: set-property path="n.md" key="repo" -->', "x")
        ok = outbox_io.flush_one(md, self.vault, self.sent, self.journal)
        self.assertTrue(ok)
        self.assertNotEqual(note.read_text(encoding="utf-8"), original)

        records = vault_journal.read_records(self.journal)
        snapshot = next(r for r in records
                        if r["state"] == vault_journal.STATE_SNAPSHOT)
        report = vault_journal.undo(self.vault, snapshot, write=True)
        self.assertEqual(report["action"], "restore")
        self.assertEqual(note.read_text(encoding="utf-8"), original)


if __name__ == "__main__":
    unittest.main(verbosity=2)
