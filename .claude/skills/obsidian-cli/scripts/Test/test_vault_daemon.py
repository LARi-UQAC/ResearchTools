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
import sys
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


class UnreachableOllamaTest(DaemonCase):
    """Diagnosed 2026-10-01 from vault-daemon.log: 11 daemon deaths, each a
    ResolverError ('ollama list' exited 1, connection refused) because Ollama
    was not listening yet at login. The loop must wait and keep polling."""

    LOOP_CONFIG = {
        "lock": CONFIG["lock"], "probe": CONFIG["probe"],
        "daemon": {**CONFIG["daemon"], "ask_poll_interval_s": 1},
    }
    ITERATIONS = 2  # a second pass proves the loop survived the first

    def setUp(self):
        super().setUp()
        sys.path.insert(0, str(Path(vd.ob.__file__).resolve().parent))
        self.addCleanup(sys.path.remove, str(Path(vd.ob.__file__).resolve().parent))
        import model_resolver
        self.mr = model_resolver
        vd._STOP["requested"] = False
        self.addCleanup(vd._STOP.update, requested=False)
        self.sleeps = 0

    def _daemon(self, drain_idle_s, bridge_error_log_interval_s=None):
        daemon_cfg = {**self.LOOP_CONFIG["daemon"], "drain_idle_s": drain_idle_s}
        if bridge_error_log_interval_s is not None:
            daemon_cfg["bridge_error_log_interval_s"] = bridge_error_log_interval_s
        config = {**self.LOOP_CONFIG, "daemon": daemon_cfg}
        return vd.VaultDaemon(self.vault, self.outbox, config, today=TODAY)

    def _fake_sleep(self, _seconds):
        self.sleeps += 1
        if self.sleeps >= self.ITERATIONS:
            vd._STOP["requested"] = True

    def _run_loop(self, daemon):
        down = self.mr.ResolverError(
            "[RESOLVER] 'ollama list' exited 1: connection refused")
        with mock.patch.object(self.mr, "resolve",
                               side_effect=down) as resolve, \
                mock.patch.object(vd.time, "sleep",
                                  side_effect=self._fake_sleep), \
                mock.patch.object(vd.ob, "_post_generate",
                                  side_effect=AssertionError):
            rc = daemon.run_forever()
        return rc, resolve

    def test_a_pending_drop_survives_an_unreachable_ollama(self):
        drop = self._drop()
        rc, resolve = self._run_loop(self._daemon(drain_idle_s=900))
        self.assertEqual(rc, 0)
        self.assertTrue(drop.exists(), "the drop must wait in raw/, unfiled")
        self.assertGreaterEqual(self.sleeps, self.ITERATIONS)
        self.assertGreaterEqual(resolve.call_count, self.ITERATIONS,
                                "the loop must retry resolution on each pass")

    def test_the_idle_drain_survives_an_unreachable_ollama(self):
        rc, resolve = self._run_loop(self._daemon(drain_idle_s=0))
        self.assertEqual(rc, 0)
        self.assertGreaterEqual(self.sleeps, self.ITERATIONS)
        self.assertGreaterEqual(resolve.call_count, self.ITERATIONS)

    def test_a_missing_measured_window_is_a_bridge_error(self):
        missing = vd.context_budget.ConfigError("no retained_num_ctx for tag")
        with mock.patch.object(vd.context_budget, "read_retained_num_ctx",
                               side_effect=missing):
            with self.assertRaises(vd.ob.BridgeError) as caught:
                vd.context_window(TAG)
        self.assertIs(caught.exception.__cause__, missing)
        self.assertIn("no retained_num_ctx", str(caught.exception))

    def test_an_unexpected_error_is_still_not_swallowed(self):
        """Negative control: the loop catches the two named refusals only. A
        bug (here a KeyError out of the resolver) must still surface."""
        self._drop()
        with mock.patch.object(self.mr, "resolve",
                               side_effect=KeyError("bug")), \
                mock.patch.object(vd.time, "sleep",
                                  side_effect=self._fake_sleep):
            with self.assertRaises(KeyError):
                self._daemon(drain_idle_s=900).run_forever()

    # ---------- PR #42 review (Medium): the log must not grow unbounded ----

    def test_an_identical_bridge_error_is_rate_limited(self):
        """poll_interval_s is 5s in production; five identical failures in a
        row used to write five identical lines. With the interval set wide,
        only the first is printed."""
        drop = self._drop()
        daemon = self._daemon(drain_idle_s=900,
                              bridge_error_log_interval_s=3600)
        buf = io.StringIO()
        with mock.patch("sys.stderr", buf):
            rc, _resolve = self._run_loop(daemon)
        self.assertEqual(rc, 0)
        self.assertEqual(buf.getvalue().count("connection refused"), 1)

    def test_a_changed_bridge_error_message_still_logs_immediately(self):
        """Negative control: suppression must key on the MESSAGE, or a
        genuinely new failure (Ollama came back with a different error)
        would be silently hidden behind an older, unrelated one."""
        self._drop()
        daemon = self._daemon(drain_idle_s=900,
                              bridge_error_log_interval_s=3600)
        down_a = self.mr.ResolverError("[RESOLVER] connection refused")
        down_b = self.mr.ResolverError("[RESOLVER] a different failure")
        buf = io.StringIO()
        with mock.patch.object(self.mr, "resolve",
                               side_effect=[down_a, down_b, down_b, down_b]), \
                mock.patch.object(vd.time, "sleep",
                                  side_effect=self._fake_sleep), \
                mock.patch.object(vd.ob, "_post_generate",
                                  side_effect=AssertionError), \
                mock.patch("sys.stderr", buf):
            daemon.run_forever()
        out = buf.getvalue()
        self.assertEqual(out.count("connection refused"), 1)
        self.assertEqual(out.count("a different failure"), 1,
                         "the changed message must print once, not be "
                         "suppressed by the interval the OLD message set")


class OnceAndDrainRefusalTest(DaemonCase):
    """PR #42 review (Low): --once and --drain used to let an unreachable
    Ollama propagate as a bare traceback instead of the exit-2 refusal
    run_forever's own loop already gives the same failure. resolve_model
    itself is patched (rather than the resolver underneath it) because the
    contract under test is main()'s own except clause, and resolve_model
    always hands its caller a BridgeError - never the resolver's raw
    ResolverError - per ollama_bridge.py's own wrapping."""

    def _drop(self):
        path = self.outbox / "raw" / "evt.md"
        path.write_text("Some content.\n", encoding="utf-8")
        return path

    def test_once_exits_2_on_an_unreachable_ollama_rather_than_a_traceback(self):
        self._drop()
        down = vd.ob.BridgeError("[RESOLVER] connection refused")
        buf = io.StringIO()
        with mock.patch.object(vd.ob, "resolve_model", side_effect=down), \
                mock.patch.object(vd.outbox_io, "resolve_vault",
                                  return_value=self.vault), \
                mock.patch.object(vd.outbox_io, "load_config",
                                  return_value=CONFIG), \
                mock.patch("sys.stderr", buf):
            rc = vd.main(["--outbox", str(self.outbox), "--once"])
        self.assertEqual(rc, 2)
        self.assertIn("connection refused", buf.getvalue())

    def test_drain_exits_2_on_an_unreachable_ollama_rather_than_a_traceback(self):
        down = vd.ob.BridgeError("[RESOLVER] connection refused")
        buf = io.StringIO()
        with mock.patch.object(vd.ob, "resolve_model", side_effect=down), \
                mock.patch.object(vd.outbox_io, "resolve_vault",
                                  return_value=self.vault), \
                mock.patch.object(vd.outbox_io, "load_config",
                                  return_value=CONFIG), \
                mock.patch("sys.stderr", buf):
            rc = vd.main(["--outbox", str(self.outbox), "--drain"])
        self.assertEqual(rc, 2)
        self.assertIn("connection refused", buf.getvalue())


if __name__ == "__main__":
    unittest.main(verbosity=2)
