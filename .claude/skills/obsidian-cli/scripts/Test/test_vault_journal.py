"""
test_vault_journal - offline checks for the append-only vault write record and
the undo it enables.

No real vault: every case builds a fake one in tempfile.mkdtemp(). The journal
is the only recovery path the vault has, since it is not under version control,
so the cases that matter are the ones where undo must REFUSE: a path leaving the
vault, and a file already smaller than the size the record claims.
"""
import contextlib
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "vault_journal.py"
spec = importlib.util.spec_from_file_location("vault_journal_under_test", SCRIPT)
vj = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vj)

STAMP = "2026-08-28T14:02:11+00:00"   # injected, never the wall clock (R19)


class VaultJournalTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.vault = self.tmp / "Vault"
        (self.vault / "30_Ressources" / "Ollama").mkdir(parents=True)
        self.journal = self.tmp / "vault-journal.jsonl"

    def _note(self, rel, body):
        target = self.vault / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8", newline="")
        return target

    def test_record_shape_and_append_only(self):
        vj.record(self.journal, "30_Ressources/Ollama/x.md", 0, 1843,
                  "raw/x.md", vj.STATE_WRITE, at=STAMP)
        vj.record(self.journal, "30_Ressources/Ollama/y.md", 12, 40,
                  "raw/y.md", vj.STATE_EDGE, at=STAMP)
        lines = self.journal.read_text(encoding="utf-8").strip().splitlines()
        self.assertEqual(len(lines), 2)
        first = json.loads(lines[0])
        self.assertEqual(
            sorted(first), ["after", "at", "before", "path", "source", "state"])
        self.assertEqual(first["at"], STAMP)
        self.assertEqual(first["after"], 1843)

    def test_a_pending_record_carries_a_null_after(self):
        entry = vj.record(self.journal, "30_Ressources/Ollama/x.md", 7, None,
                          "raw/x.md", vj.STATE_PENDING, at=STAMP)
        self.assertIsNone(entry["after"])
        self.assertEqual(vj.read_records(self.journal)[0]["state"],
                         vj.STATE_PENDING)

    def test_a_corrupt_line_does_not_hide_the_history(self):
        vj.record(self.journal, "a.md", 0, 5, "s", vj.STATE_WRITE, at=STAMP)
        with self.journal.open("a", encoding="utf-8") as handle:
            handle.write("{ truncated\n")
        vj.record(self.journal, "b.md", 0, 5, "s", vj.STATE_WRITE, at=STAMP)
        self.assertEqual([r["path"] for r in vj.read_records(self.journal)],
                         ["a.md", "b.md"])

    def test_undo_of_an_append_restores_the_byte_size(self):
        rel = "30_Ressources/Ollama/x.md"
        target = self._note(rel, "first entry\n")
        before = target.stat().st_size
        target.write_text("first entry\n\nsecond entry appended\n",
                          encoding="utf-8", newline="")
        entry = vj.record(self.journal, rel, before, target.stat().st_size,
                          "raw/x.md", vj.STATE_WRITE, at=STAMP)

        preview = vj.undo(self.vault, entry, write=False)
        self.assertEqual(preview["action"], "truncate")
        self.assertGreater(target.stat().st_size, before, "dry run must not write")

        vj.undo(self.vault, entry, write=True)
        self.assertEqual(target.stat().st_size, before)
        self.assertEqual(target.read_text(encoding="utf-8"), "first entry\n")

    def test_undo_of_a_create_removes_the_file(self):
        rel = "30_Ressources/Ollama/new.md"
        target = self._note(rel, "a brand new note\n")
        entry = vj.record(self.journal, rel, 0, target.stat().st_size,
                          "raw/new.md", vj.STATE_WRITE, at=STAMP)
        self.assertEqual(vj.undo(self.vault, entry, write=False)["action"], "delete")
        self.assertTrue(target.exists(), "dry run must not delete")
        vj.undo(self.vault, entry, write=True)
        self.assertFalse(target.exists())

    def test_undo_refuses_a_path_outside_the_vault(self):
        outside = self.tmp / "escape.md"
        outside.write_text("payload\n", encoding="utf-8")
        entry = {"path": "../escape.md", "before": 0, "after": 8,
                 "source": "s", "state": vj.STATE_WRITE, "at": STAMP}
        report = vj.undo(self.vault, entry, write=True)
        self.assertEqual(report["action"], "refused")
        self.assertIn("outside the vault", report["reason"])
        self.assertTrue(outside.exists())

    def test_undo_refuses_when_the_file_is_already_smaller(self):
        rel = "30_Ressources/Ollama/x.md"
        self._note(rel, "tiny\n")
        entry = {"path": rel, "before": 9999, "after": 10050,
                 "source": "s", "state": vj.STATE_WRITE, "at": STAMP}
        report = vj.undo(self.vault, entry, write=True)
        self.assertEqual(report["action"], "refused")
        self.assertIn("already smaller", report["reason"])

    def test_undo_of_a_vanished_note_is_a_noop(self):
        entry = {"path": "30_Ressources/Ollama/gone.md", "before": 5, "after": 9,
                 "source": "s", "state": vj.STATE_WRITE, "at": STAMP}
        self.assertEqual(vj.undo(self.vault, entry, write=True)["action"], "noop")

    def _drill_like_history(self):
        """A baseline of one earlier write, then two the 'drill' added: an
        append onto the earlier note and a fresh create."""
        kept = self._note("30_Ressources/Ollama/kept.md", "older learning\n")
        vj.record(self.journal, "30_Ressources/Ollama/kept.md", 0,
                  kept.stat().st_size, "raw/kept.md", vj.STATE_WRITE, at=STAMP)
        baseline = len(vj.read_records(self.journal))

        before = kept.stat().st_size
        kept.write_text("older learning\nappended by the drill\n",
                        encoding="utf-8", newline="")
        vj.record(self.journal, "30_Ressources/Ollama/kept.md", before,
                  kept.stat().st_size, "raw/d1.md", vj.STATE_WRITE, at=STAMP)

        made = self._note("30_Ressources/Ollama/drill.md", "drill note\n")
        vj.record(self.journal, "30_Ressources/Ollama/drill.md", 0,
                  made.stat().st_size, "raw/d2.md", vj.STATE_WRITE, at=STAMP)
        return kept, made, baseline

    def test_undo_since_removes_only_what_came_after_the_baseline(self):
        """The teardown the drill never had. Everything at or after the
        baseline index goes; the note that existed before it is returned to its
        earlier size, not deleted."""
        kept, made, baseline = self._drill_like_history()
        report = vj.undo_since(self.vault, vj.read_records(self.journal),
                               baseline, write=True)
        self.assertEqual(report["refused"], 0)
        self.assertFalse(made.exists(), "a note the drill created must go")
        self.assertEqual(kept.read_text(encoding="utf-8"), "older learning\n")

    def test_undo_since_walks_newest_first(self):
        """Not a preference. An append is undone by truncating to a journalled
        size, so undoing an older record first leaves the file shorter than the
        newer record's baseline and that newer undo is then refused. The order
        is what lets a run of undos compose."""
        _, _, baseline = self._drill_like_history()
        report = vj.undo_since(self.vault, vj.read_records(self.journal),
                               baseline, write=True)
        self.assertEqual([r["index"] for r in report["undone"]], [2, 1])

    def test_undo_since_is_dry_run_without_write(self):
        kept, made, baseline = self._drill_like_history()
        report = vj.undo_since(self.vault, vj.read_records(self.journal),
                               baseline, write=False)
        self.assertFalse(report["applied"])
        self.assertTrue(made.exists(), "a preview must touch nothing")
        self.assertIn("appended by the drill", kept.read_text(encoding="utf-8"))

    def test_undo_since_at_the_end_is_a_clean_no_op(self):
        """A drill that filed nothing must not make the teardown do anything."""
        _, _, _ = self._drill_like_history()
        total = len(vj.read_records(self.journal))
        report = vj.undo_since(self.vault, vj.read_records(self.journal),
                               total, write=True)
        self.assertEqual(report["undone"], [])
        self.assertEqual(report["refused"], 0)

    def test_cli_count_prints_the_undoable_baseline(self):
        """What the launcher captures before the drill runs. Printed bare so a
        shell can read it without parsing JSON."""
        self._drill_like_history()
        with io.StringIO() as out, contextlib.redirect_stdout(out):
            code = vj.main(["--journal", str(self.journal), "--count"])
            printed = out.getvalue().strip()
        self.assertEqual(code, 0)
        self.assertEqual(printed, "3")

    def test_cli_undo_since_needs_a_vault(self):
        self._drill_like_history()
        self.assertEqual(
            vj.main(["--journal", str(self.journal), "--undo-since", "1"]), 1)

    def test_cli_undo_is_dry_run_without_yes(self):
        rel = "30_Ressources/Ollama/x.md"
        target = self._note(rel, "one\n")
        before = target.stat().st_size
        target.write_text("one\n\ntwo\n", encoding="utf-8", newline="")
        vj.record(self.journal, rel, before, target.stat().st_size, "raw/x.md",
                  vj.STATE_WRITE, at=STAMP)
        argv = ["--journal", str(self.journal), "--vault", str(self.vault),
                "--undo", "last"]
        self.assertEqual(vj.main(argv), 0)
        self.assertGreater(target.stat().st_size, before)
        self.assertEqual(vj.main(argv + ["--yes"]), 0)
        self.assertEqual(target.stat().st_size, before)

    def test_cli_refuses_an_index_that_does_not_exist(self):
        vj.record(self.journal, "a.md", 0, 5, "s", vj.STATE_WRITE, at=STAMP)
        self.assertEqual(vj.main(["--journal", str(self.journal),
                                  "--vault", str(self.vault), "--undo", "7"]), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
