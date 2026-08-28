"""
test_vault_journal - offline checks for the append-only vault write record and
the undo it enables.

No real vault: every case builds a fake one in tempfile.mkdtemp(). The journal
is the only recovery path the vault has, since it is not under version control,
so the cases that matter are the ones where undo must REFUSE: a path leaving the
vault, and a file already smaller than the size the record claims.
"""
import importlib.util
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
