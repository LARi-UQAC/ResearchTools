"""
test_vault_daemon - the write path of the vault event daemon.

No daemon process, no model, no real vault: the bridge's sole network boundary
is patched, the resolver and the measured window are injected, and the vault is
a fixture tree. What the model is ASKED, and the refusals built on its answer,
live in test_daemon_classify; the shared harness in _daemon_fixtures.

What is proved here is everything after the decision: the note reaching disk,
a name collision becoming a dated note rather than an append into an unrelated
one, a replay writing nothing twice, the deferred queues, the in-flight state
file, and the two ways an event ends without a write - a crash, and lock
contention, which must return the drop to raw/ rather than strand it.
"""
import io
import json
import unittest
from pathlib import Path
from unittest import mock

from _daemon_fixtures import CONFIG, DaemonCase, GOOD_NOTE, TAG, TODAY, WINDOW, ds, reply, vd  # noqa: F401


class DaemonWriteTest(DaemonCase):
    # ---------- the happy paths, one per scope ----------

    def test_a_reusable_drop_is_filed_under_its_technology(self):
        drop = self._drop()
        report = self._run(drop, {"scope": "reusable", "technology": "Ollama",
                                  "confidence": 0.9})
        self.assertIsNone(report["parked"])
        self.assertEqual(report["states"],
                         ["READ", "CLASSIFY", "ROUTE", "DRAFT", "WRITE", "ENQUEUE"])
        self.assertEqual(report["model_calls"], 2)
        written = self.vault / "30_Ressources/Ollama/a-lock-was-left-behind.md"
        self.assertTrue(written.exists())
        self.assertFalse(drop.exists(), "the source must leave raw/ last")
        self.assertTrue((self.outbox / "raw" / "sent" / drop.name).exists())

    def test_a_project_drop_is_appended_to_its_decision_log(self):
        drop = self._drop(project="ResearchTools")
        self._run(drop, {"scope": "project", "technology": "Ollama",
                         "project": "ResearchTools", "confidence": 0.95})
        log = self.vault / "10_Projets/Logiciels/ResearchTools/Decisions.md"
        self.assertTrue(log.exists())

    # ---------- everything the daemon must refuse ----------

    def test_a_drop_without_a_subject_is_parked(self):
        path = self.outbox / "raw" / "bare.md"
        path.write_text("---\nsource: local-coder\n---\nbody\n", encoding="utf-8")
        with mock.patch.object(vd.ob, "_post_generate", side_effect=AssertionError):
            report = self.daemon.handle(path, TAG, WINDOW)
        self.assertIn("names no subject", report["parked"])

    def test_a_hygiene_violation_retries_and_then_parks_rather_than_patching(self):
        """A patched body would hide that the model ignores the style rules; a
        retry measures it, and a finite budget stops the loop."""
        dirty = "---\ntype: apprentissage\n---\n\n## Contexte\nUn tiret — long.\n"
        responses = [reply(json.dumps({"scope": "reusable", "technology": "Ollama",
                                       "confidence": 0.9})),
                     reply(dirty), reply(dirty)]
        with mock.patch.object(vd.ob, "_post_generate", side_effect=responses) as post:
            report = self.daemon.handle(self._drop(), TAG, WINDOW)
        self.assertIn("style hygiene", report["parked"])
        self.assertEqual(post.call_count, 3, "one classify plus two draft attempts")

    def test_a_prompt_over_the_window_is_parked_not_truncated(self):
        """Ollama does not reject an oversized prompt, it truncates it and
        answers anyway, so the budget check is the only thing standing between
        a long drop and an answer written without its own instruction."""
        drop = self._drop(body="x " * 40000)
        with mock.patch.object(vd.ob, "_post_generate", side_effect=AssertionError):
            report = self.daemon.handle(drop, TAG, WINDOW)
        self.assertIn("parked, not truncated", report["parked"])

    # ---------- collision, replay, queues ----------

    def test_a_name_collision_produces_a_dated_note_not_an_append(self):
        existing = self._note("30_Ressources/Ollama/a-lock-was-left-behind.md",
                              "an unrelated older learning\n")
        report = self._run(self._drop(), {"scope": "reusable", "technology": "Ollama",
                                          "confidence": 0.9})
        self.assertEqual(report["rel"],
                         f"30_Ressources/Ollama/a-lock-was-left-behind-{TODAY}.md")
        self.assertEqual(existing.read_text(encoding="utf-8"),
                         "an unrelated older learning\n")

    def test_a_second_collision_adds_a_counter(self):
        self._note("30_Ressources/Ollama/s.md")
        self._note(f"30_Ressources/Ollama/s-{TODAY}.md")
        self.assertEqual(
            ds.unique_note_path(self.vault, "30_Ressources/Ollama", "s", TODAY),
            f"30_Ressources/Ollama/s-{TODAY}-2.md")

    def test_replaying_a_completed_event_writes_nothing_twice(self):
        first = self._run(self._drop(), {"scope": "reusable", "technology": "Ollama",
                                         "confidence": 0.9})
        written = self.vault / first["rel"]
        size = written.stat().st_size
        again = self._drop()          # the same drop arrives again
        self._run(again, {"scope": "reusable", "technology": "Ollama",
                          "confidence": 0.9})
        self.assertEqual(written.stat().st_size, size)

    def test_both_queues_are_filled_and_neither_is_drained_on_the_event_path(self):
        with mock.patch.object(vd, "ds", wraps=ds):
            report = self._run(self._drop(), {"scope": "reusable",
                                              "technology": "Ollama",
                                              "confidence": 0.9})
        for name in ("consolidate", "graphify"):
            queued = (self.outbox / "queue" / name).read_text(encoding="utf-8")
            self.assertEqual(queued.strip(), report["rel"])

    def test_the_state_file_exists_during_the_write_and_not_after(self):
        """The state file is the in-flight marker, so it must be readable while
        the write is happening and gone once the event completes. One that
        survives means a crash, which is what makes the recovery sweep's report
        worth reading."""
        seen = {}
        real_flush = vd.outbox_io.flush_one

        def spy(staged, vault, sent, journal):
            state = self.outbox / "state" / f"{staged.stem}.json"
            seen["during"] = json.loads(state.read_text(encoding="utf-8"))
            return real_flush(staged, vault, sent, journal)

        with mock.patch.object(vd.outbox_io, "flush_one", spy):
            report = self._run(self._drop(), {"scope": "reusable",
                                              "technology": "Ollama",
                                              "confidence": 0.9})
        self.assertEqual(seen["during"]["state"], "WRITE")
        self.assertEqual(seen["during"]["rel"], report["rel"])
        self.assertFalse((self.outbox / "state" / f"{report['event']}.json").exists())

    def test_a_crash_before_the_write_leaves_the_drop_for_the_next_poll(self):
        drop = self._drop()
        responses = [reply(json.dumps({"scope": "reusable", "technology": "Ollama",
                                       "confidence": 0.9})),
                     reply(GOOD_NOTE)]
        with mock.patch.object(vd.ob, "_post_generate", side_effect=responses):
            with mock.patch.object(vd.outbox_io, "flush_one", return_value=False):
                report = self.daemon.handle(drop, TAG, WINDOW)
        self.assertIn("no effect on disk", report["parked"])

    def test_lock_contention_defers_the_drop_instead_of_parking_it(self):
        """Contention is not a defect of the drop, so it must not be parked.
        The drop is CLAIMED first, as run_once does: passing the raw/ path
        straight to handle() is what hid the defect until the live drill of
        2026-08-28, where the deferred drop stayed in working/ for over an
        hour while the daemon polled an empty raw/ beside it."""
        drop = self._drop()
        claimed = self.daemon.claim(drop)
        self.assertIsNotNone(claimed)
        self.assertFalse(drop.exists(), "claim moves the drop out of raw/")
        responses = [reply(json.dumps({"scope": "reusable", "technology": "Ollama",
                                       "confidence": 0.9})),
                     reply(GOOD_NOTE)]
        holder = vd.vault_lock.VaultLock(self.outbox.parent / "obsidian-outbox.lock",
                                         acquire_timeout_s=1, stale_after_s=300,
                                         poll_interval_s=0.01)
        holder.acquire()
        self.addCleanup(holder.release)
        with mock.patch.object(vd.ob, "_post_generate", side_effect=responses):
            report = self.daemon.handle(claimed, TAG, WINDOW)
        self.assertTrue(report["parked"].startswith("deferred"))
        self.assertTrue(drop.exists(), "the drop returns to raw/ for the next poll")
        self.assertFalse(claimed.exists(), "nothing may be stranded in working/")
        self.assertFalse((self.outbox / "needs-review" / drop.name).exists())

    def test_a_path_escaping_the_vault_is_refused_by_the_write_path(self):
        """The classification is model output, so it is untrusted input. The
        containment check lives in outbox_io and is exercised here end to end."""
        report = self._run(self._drop(), {"scope": "reusable",
                                          "technology": "../../escape",
                                          "confidence": 0.99})
        self.assertIn("not a live folder", report["parked"])
        self.assertFalse((self.tmp / "escape").exists())

    def test_dry_run_touches_nothing(self):
        self._drop()
        with mock.patch.object(vd.outbox_io, "load_config", return_value=CONFIG):
            with mock.patch.object(vd.outbox_io, "resolve_vault",
                                   return_value=self.vault):
                with mock.patch.object(vd.ob, "_post_generate",
                                       side_effect=AssertionError):
                    self.assertEqual(
                        vd.main(["--outbox", str(self.outbox), "--dry-run"]), 0)
        self.assertEqual(len(self.daemon.pending()), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
