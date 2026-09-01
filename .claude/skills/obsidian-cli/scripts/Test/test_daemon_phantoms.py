"""
test_daemon_phantoms - offline checks for the dead-link drain.

No model, no subprocess, no real vault: the deterministic link report and the
bridge's network boundary are patched, and the vault is a fixture tree.

Two properties carry this suite. The model must not be able to invent a target,
which is enforced by the schema built from the report's own suggestions, not by
asking politely. And no substitution happens without a snapshot in the journal
first, because a link rewrite replaces text mid-file and cannot be undone from a
size the way an append can - that asymmetry is why this drain was once refused
outright.
"""
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SCRIPTS = Path(__file__).resolve().parents[1]
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


def _load(name):
    spec = importlib.util.spec_from_file_location(
        f"{name}_under_test", SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


dd = _load("daemon_phantoms")
vj = _load("vault_journal")

WINDOW = 16384
TAG = "a-tag-from-the-resolver"
CONFIG = {"probe": {"request_timeout_s": 5},
          "daemon": {"phantom_max_per_drain": 10}}
SOURCE = "30_Ressources/Ollama/a.md"
REAL = "30_Ressources/Ollama/ollama-clamps-num-ctx.md"


def verdict(action, target=None, why="because"):
    body = {"action": action, "why": why}
    if target:
        body["target"] = target
    return {"response": json.dumps(body)}


class PhantomDrainTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.vault = self.tmp / "Vault"
        (self.vault / "30_Ressources" / "Ollama").mkdir(parents=True)
        (self.vault / REAL).write_text("# la vraie note\n", encoding="utf-8")
        self.source = self.vault / SOURCE
        self.source.write_text(
            "Voir [[ollama-clamp]] pour le detail.\n", encoding="utf-8")
        self.journal = self.tmp / "vault-journal.jsonl"

    def _report(self, suggestions=("ollama-clamps-num-ctx",)):
        return {"ollama-clamp": {
            "sources": [SOURCE],
            "suggestions": [{"target": s, "score": "basename"} for s in suggestions]}}

    def _drain(self, responses, report=None, journal=True):
        with mock.patch.object(dd, "phantom_report",
                               return_value=report if report is not None else self._report()):
            with mock.patch.object(dd.ob, "_post_generate", side_effect=responses):
                return dd.drain_phantoms(
                    self.vault, TAG, WINDOW, CONFIG,
                    self.journal if journal else None, None)

    def test_a_repoint_rewrites_the_link(self):
        report = self._drain([verdict("repoint", "ollama-clamps-num-ctx")])
        self.assertEqual(len(report["repointed"]), 1)
        self.assertIn("[[ollama-clamps-num-ctx]]",
                      self.source.read_text(encoding="utf-8"))
        self.assertNotIn("[[ollama-clamp]]",
                         self.source.read_text(encoding="utf-8"))

    def test_a_drop_kills_the_link_but_keeps_the_words(self):
        """Deleting the sentence would remove an author's meaning to satisfy a
        link count. Backticks stop it being a live link and leave the text."""
        self._drain([verdict("drop", why="points at a folder")])
        text = self.source.read_text(encoding="utf-8")
        self.assertIn("`[[ollama-clamp]]`", text)
        self.assertIn("pour le detail", text)

    def test_a_drop_neutralises_an_ALIASED_link(self):
        """The defect that made the drain loop for hours on 2026-08-28. A
        phantom is named by its TARGET only, so a literal replace of
        "[[target]]" never matches "[[target|label]]". The link survived, the
        next audit reported it again, and the model was asked the same question
        every fifteen minutes."""
        self.source.write_text("Voir [[ollama-clamp|le detail]] ici.\n",
                               encoding="utf-8")
        report = self._drain([verdict("drop", why="points at a folder")])
        text = self.source.read_text(encoding="utf-8")
        self.assertIn("`[[ollama-clamp|le detail]]`", text)
        self.assertEqual(report["neutralised"], [SOURCE])
        self.assertEqual(report["errors"], [])

    def test_a_drop_neutralises_a_link_carrying_a_heading(self):
        self.source.write_text("Voir [[ollama-clamp#Mesure]] ici.\n",
                               encoding="utf-8")
        self._drain([verdict("drop", why="points at a folder")])
        self.assertIn("`[[ollama-clamp#Mesure]]`",
                      self.source.read_text(encoding="utf-8"))

    def test_neutralising_twice_changes_nothing_the_second_time(self):
        """What makes the drain converge. Once wrapped, the link sits in a code
        span, and the code-region walk hands those through untouched."""
        dd.neutralise_links(self.vault, [SOURCE], ["ollama-clamp"])
        once = self.source.read_text(encoding="utf-8")
        again = dd.neutralise_links(self.vault, [SOURCE], ["ollama-clamp"])
        self.assertEqual(again, [], "a second pass must modify nothing")
        self.assertEqual(self.source.read_text(encoding="utf-8"), once)
        self.assertNotIn("``", once, "no double backticking")

    def test_a_drop_that_changes_no_note_is_reported_as_an_error(self):
        """R9: read back the effect, not the verdict. Without this the report
        said 'dropped' while the phantom was still live, which is exactly how
        the loop stayed invisible."""
        self.source.write_text("No link here at all.\n", encoding="utf-8")
        report = self._drain([verdict("drop", why="points at a folder")])
        self.assertEqual(report["neutralised"], [])
        self.assertEqual(len(report["errors"]), 1)
        self.assertIn("the link survives", report["errors"][0]["why"])

    def test_leave_touches_nothing(self):
        before = self.source.read_text(encoding="utf-8")
        report = self._drain([verdict("leave", why="the note is coming")])
        self.assertEqual(len(report["left"]), 1)
        self.assertEqual(self.source.read_text(encoding="utf-8"), before)
        self.assertNotIn("applied", report)

    def test_every_edit_is_snapshotted_before_it_happens(self):
        self._drain([verdict("repoint", "ollama-clamps-num-ctx")])
        records = vj.read_records(self.journal)
        self.assertEqual([r["state"] for r in records], ["SNAPSHOT"])
        self.assertIn("[[ollama-clamp]]", records[0]["content"])

    def test_the_snapshot_undoes_the_rewrite_exactly(self):
        original = self.source.read_text(encoding="utf-8")
        self._drain([verdict("repoint", "ollama-clamps-num-ctx")])
        self.assertNotEqual(self.source.read_text(encoding="utf-8"), original)
        record = vj.read_records(self.journal)[0]
        vj.undo(self.vault, record, write=True)
        self.assertEqual(self.source.read_text(encoding="utf-8"), original)

    def test_without_a_journal_nothing_is_rewritten(self):
        """No snapshot means no undo, and an unundoable rewrite across someone
        else's notes is exactly what this drain was once refused for."""
        before = self.source.read_text(encoding="utf-8")
        report = self._drain([verdict("repoint", "ollama-clamps-num-ctx")],
                             journal=False)
        self.assertEqual(self.source.read_text(encoding="utf-8"), before)
        self.assertIn("unundoable", report["errors"][0]["why"])

    def test_the_schema_admits_only_the_suggested_targets(self):
        with mock.patch.object(dd.ob, "_post_generate",
                               return_value=verdict("leave")) as post:
            dd.judge_phantom("ollama-clamp", self._report()["ollama-clamp"],
                             TAG, WINDOW, 5.0)
        schema = post.call_args[0][0]["format"]
        self.assertEqual(schema["properties"]["target"]["enum"],
                         ["ollama-clamps-num-ctx"])

    def test_with_no_suggestion_the_schema_names_no_target_at_all(self):
        entry = {"sources": [SOURCE], "suggestions": []}
        with mock.patch.object(dd.ob, "_post_generate",
                               return_value=verdict("drop")) as post:
            dd.judge_phantom("nothing-like-this", entry, TAG, WINDOW, 5.0)
        schema = post.call_args[0][0]["format"]
        self.assertNotIn("enum", schema["properties"]["target"])
        self.assertIn("Never invent a target", post.call_args[0][0]["prompt"])

    def test_a_repoint_with_no_target_is_not_applied(self):
        before = self.source.read_text(encoding="utf-8")
        report = self._drain([verdict("repoint")])
        self.assertEqual(report["repointed"], [])
        self.assertEqual(self.source.read_text(encoding="utf-8"), before)

    def test_an_unparsable_verdict_is_an_error_not_an_edit(self):
        before = self.source.read_text(encoding="utf-8")
        report = self._drain([{"response": "I would repoint it, probably."}])
        self.assertEqual(len(report["errors"]), 1)
        self.assertEqual(self.source.read_text(encoding="utf-8"), before)

    def test_the_phantom_count_is_bounded(self):
        report = {f"p{i}": {"sources": [SOURCE], "suggestions": []}
                  for i in range(30)}
        config = {"probe": {"request_timeout_s": 5},
                  "daemon": {"phantom_max_per_drain": 3}}
        with mock.patch.object(dd, "phantom_report", return_value=report):
            with mock.patch.object(dd.ob, "_post_generate",
                                   side_effect=[verdict("leave")] * 3) as post:
                dd.drain_phantoms(self.vault, TAG, WINDOW, config, self.journal, None)
        self.assertEqual(post.call_count, 3)

    def test_a_failing_link_audit_is_refused_not_guessed(self):
        completed = mock.Mock(returncode=1, stdout="", stderr="boom")
        with mock.patch.object(dd.subprocess, "run", return_value=completed):
            with self.assertRaises(dd.ds.EventRefused):
                dd.phantom_report(self.vault, 5.0)

    def test_an_empty_report_is_a_clean_no_op(self):
        report = self._drain([], report={})
        self.assertEqual(report["repointed"], [])
        self.assertEqual(report["errors"], [])
        self.assertFalse(self.journal.exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
