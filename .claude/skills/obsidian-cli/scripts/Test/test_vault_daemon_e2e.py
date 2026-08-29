"""
test_vault_daemon_e2e - offline checks for the end-to-end drill's own harness.

The drill runs against the real vault, so what can be tested offline is its
refusals and its plumbing: that it writes nothing without --yes, that it stops
when no vault is configured, that its drops carry the identifying prefix, and
that its waits are bounded. The steps themselves are proved only by running it.
"""
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SCRIPTS = Path(__file__).resolve().parents[1]
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

spec = importlib.util.spec_from_file_location(
    "e2e_under_test", SCRIPTS / "vault_daemon_e2e.py")
e2e = importlib.util.module_from_spec(spec)
spec.loader.exec_module(e2e)


class HarnessTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.vault = self.tmp / "Vault"
        (self.vault / "30_Ressources" / "Ollama").mkdir(parents=True)
        self.outbox = self.tmp / "outbox"

    def test_without_yes_it_writes_nothing(self):
        """A drill that mutates the vault must not do so because someone ran it
        to see what it does."""
        with mock.patch.object(e2e.outbox_io, "resolve_vault", return_value=self.vault):
            with mock.patch.object(e2e.outbox_io, "load_config", return_value={}):
                with mock.patch("sys.stdout", new=io.StringIO()) as out:
                    code = e2e.main(["--outbox", str(self.outbox)])
                printed = json.loads(out.getvalue())
        self.assertEqual(code, 0)
        self.assertIn("would_run", printed)
        self.assertFalse((self.outbox / "raw").exists())

    def test_no_vault_is_a_stop_not_a_guess(self):
        with mock.patch.object(e2e.outbox_io, "resolve_vault", return_value=None):
            self.assertEqual(e2e.main(["--yes"]), 1)

    def test_an_unknown_step_is_reported_and_does_not_abort_the_run(self):
        with mock.patch.object(e2e.outbox_io, "resolve_vault", return_value=self.vault):
            with mock.patch.object(e2e.outbox_io, "load_config", return_value={}):
                with mock.patch("sys.stdout", new=io.StringIO()) as out:
                    code = e2e.main(["--yes", "--only", "nosuchstep",
                                     "--outbox", str(self.outbox)])
                printed = json.loads(out.getvalue())
        self.assertEqual(code, 1)
        self.assertEqual(printed["results"][0]["why"], "unknown step")

    def test_a_step_that_raises_is_recorded_rather_than_crashing_the_drill(self):
        with mock.patch.object(e2e.outbox_io, "resolve_vault", return_value=self.vault):
            with mock.patch.object(e2e.outbox_io, "load_config", return_value={}):
                with mock.patch.object(e2e, "check_undo",
                                       side_effect=RuntimeError("boom")):
                    with mock.patch("sys.stdout", new=io.StringIO()) as out:
                        code = e2e.main(["--yes", "--only", "undo",
                                         "--outbox", str(self.outbox)])
                    printed = json.loads(out.getvalue())
        self.assertEqual(code, 1)
        self.assertIn("boom", printed["results"][0]["why"])

    def test_every_drop_carries_the_identifying_prefix(self):
        """An interrupted run leaves drops behind; they have to be recognisable
        as the drill's rather than a real learning."""
        staged = e2e.drop(self.outbox, "sample", "a subject", "a body")
        self.assertTrue(staged.name.startswith(e2e.PREFIX))
        self.assertEqual(staged.parent.name, "raw")
        text = staged.read_text(encoding="utf-8")
        self.assertIn(f"source: {e2e.PREFIX}", text)
        self.assertNotIn("obsidian:", text, "a raw drop carries no directive")

    def test_wait_for_gives_up_instead_of_hanging(self):
        started = e2e.time.monotonic()
        self.assertIsNone(e2e.wait_for(lambda: None, timeout_s=0.2, poll_s=0.05))
        self.assertLess(e2e.time.monotonic() - started, 5)

    def test_wait_for_returns_the_elapsed_time_and_the_find(self):
        result = e2e.wait_for(lambda: ["found"], timeout_s=1, poll_s=0.01)
        self.assertIsNotNone(result)
        elapsed, found = result
        self.assertEqual(found, ["found"])
        self.assertGreaterEqual(elapsed, 0)

    def test_the_collision_step_says_so_when_there_is_nothing_to_collide_with(self):
        report = e2e.check_collision(self.vault, self.outbox, timeout_s=0.1)
        self.assertIsNone(report["pass"], "an unrunnable step is not a failure")
        self.assertIn("run step 1 first", report["why"])

    def _filed(self, archived_names, journal_records):
        """Run check_filed with the daemon simulated: `archived_names` is what
        reached raw/sent, `journal_records` what the journal holds."""
        (self.outbox / "raw" / "sent").mkdir(parents=True, exist_ok=True)
        for name in archived_names:
            (self.outbox / "raw" / "sent" / name).write_text("x", encoding="utf-8")
        with mock.patch.object(e2e, "journal_records", return_value=journal_records):
            with mock.patch.object(e2e.time, "sleep"):
                return e2e.check_filed(self.vault, self.outbox,
                                       self.tmp / "j.jsonl", 0, timeout_s=0.05)

    def test_step_one_fails_when_only_one_of_the_two_drops_is_filed(self):
        """The gate that lied on 2026-08-28. One drop filed, the other pushed
        onto the wrong shelf, and the step still printed pass true, because
        'at least one write and at least one archive' were both satisfied."""
        report = self._filed(
            ["e2e-drill-project.md"],
            [{"state": e2e.vault_journal.STATE_WRITE, "path": "30_Ressources/a.md"}])
        self.assertFalse(report["pass"])
        self.assertIn("e2e-drill-reusable.md", report["why"])

    def test_step_one_passes_only_when_both_drops_are_filed(self):
        report = self._filed(
            ["e2e-drill-project.md", "e2e-drill-reusable.md"],
            [{"state": e2e.vault_journal.STATE_WRITE, "path": "30_Ressources/a.md"},
             {"state": e2e.vault_journal.STATE_WRITE, "path": "30_Ressources/b.md"}])
        self.assertTrue(report["pass"])
        self.assertNotIn("why", report)

    def test_containment_reports_anything_created_beside_the_vault(self):
        with mock.patch.object(e2e.time, "sleep"):
            report = e2e.check_containment(self.vault, self.outbox, timeout_s=0)
        self.assertTrue(report["pass"])
        self.assertEqual(report["created_outside_vault"], [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
