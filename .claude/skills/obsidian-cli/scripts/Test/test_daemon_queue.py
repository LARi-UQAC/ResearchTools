"""
test_daemon_queue - offline checks for the outbox layout the daemon runs on.

The filesystem is the queue, so these cases are about who owns what: the
singleton lock that admits one daemon per machine, the claim that hands one
drop to one owner, the sweep that recovers a drop stranded by a crash, and the
two deferred queues. No model is ever called here.
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


def _load(name):
    spec = importlib.util.spec_from_file_location(
        f"{name}_under_test", SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


vd = _load("vault_daemon")
ds = _load("daemon_states")

WINDOW = 16384          # injected fixture, never read from the machine (R21)
TAG = "a-tag-from-the-resolver"
TODAY = "2026-08-28"
CONFIG = {
    "lock": {"acquire_timeout_s": 1, "stale_after_s": 300, "poll_interval_s": 0.01},
    "probe": {"request_timeout_s": 5},
    "daemon": {"poll_interval_s": 0.01, "classify_confidence_min": 0.7,
               "draft_max_attempts": 2, "drain_idle_s": 900,
               "consolidate_top_n": 15, "judge_edge_max_pairs": 15,
               "queue_max_entries": 500, "phantom_max_per_drain": 10},
}
GOOD_NOTE = "---\ntype: apprentissage\ndate: 2026-08-28\n---\n\n## Contexte\nUn cas.\n"


def reply(body):
    return {"response": body}


class DaemonQueueTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.vault = self.tmp / "Vault"
        for folder in ("Ollama", "Python", "Logiciel"):
            (self.vault / "30_Ressources" / folder).mkdir(parents=True)
        (self.vault / "10_Projets" / "Logiciels" / "ResearchTools").mkdir(parents=True)
        self.outbox = self.tmp / "outbox"
        self.daemon = vd.VaultDaemon(self.vault, self.outbox, CONFIG, today=TODAY)

    def _drop(self, name="a-lock-was-left-behind", subject="a lock was left behind",
              project=None, body="The holder died and the lock stayed."):
        front = f"---\nsource: local-coder\nsubject: {subject}\n"
        if project:
            front += f"project: {project}\n"
        path = self.outbox / "raw" / f"{name}.md"
        path.write_text(front + "---\n" + body + "\n", encoding="utf-8")
        return path

    def _run(self, drop, classification, draft=GOOD_NOTE):
        responses = [reply(json.dumps(classification)), reply(draft)]
        with mock.patch.object(vd.ob, "_post_generate", side_effect=responses):
            return self.daemon.handle(drop, TAG, WINDOW)

    # ---------- two sessions, two daemons ----------

    def test_a_second_daemon_refuses_to_start(self):
        """The outbox is machine-global. Two sessions each starting a daemon
        would classify and draft every drop twice, at two model calls each,
        which the write lock alone does not prevent."""
        first = self.daemon.singleton_lock().acquire()
        self.addCleanup(first.release)
        other = vd.VaultDaemon(self.vault, self.outbox, CONFIG, today=TODAY)
        with mock.patch.object(vd.ob, "resolve_model", side_effect=AssertionError):
            self.assertEqual(other.run_forever(), 1)

    def test_claiming_a_drop_moves_it_out_of_raw(self):
        drop = self._drop()
        claimed = self.daemon.claim(drop)
        self.assertIsNotNone(claimed)
        self.assertFalse(drop.exists())
        self.assertEqual(claimed.parent.name, "working")

    def test_the_loser_of_a_claim_race_gets_nothing(self):
        """Whoever wins the rename owns the drop. The loser must return None
        rather than processing a file that is no longer there."""
        drop = self._drop()
        self.assertIsNotNone(self.daemon.claim(drop))
        other = vd.VaultDaemon(self.vault, self.outbox, CONFIG, today=TODAY)
        self.assertIsNone(other.claim(drop))

    def test_run_once_skips_a_drop_claimed_by_someone_else(self):
        drop = self._drop()
        other = vd.VaultDaemon(self.vault, self.outbox, CONFIG, today=TODAY)
        with mock.patch.object(vd.ob, "resolve_model", return_value=TAG):
            with mock.patch.object(vd, "context_window", return_value=WINDOW):
                with mock.patch.object(self.daemon, "claim", return_value=None):
                    with mock.patch.object(vd.ob, "_post_generate",
                                           side_effect=AssertionError):
                        self.assertEqual(self.daemon.run_once(), [])
        self.assertTrue(drop.exists())

    def test_graphify_is_skipped_when_no_repository_is_configured(self):
        """A daemon is started by hand from wherever the operator stands, so
        inferring the repository from the working directory would refresh the
        wrong graph. No configured root is a stated skip."""
        (self.outbox / "queue" / "graphify").write_text("a.md", encoding="utf-8")
        with mock.patch("daemon_drains.drain_graphify",
                        side_effect=AssertionError) as never:
            report = self.daemon.drain(TAG, WINDOW)
        never.assert_not_called()
        self.assertIn("graphify_repo_root", report["graphify"]["skipped"])
        self.assertEqual(self.daemon.read_queue("graphify"), ["a.md"],
                         "a skipped queue must not be cleared")

    def test_a_configured_repository_reaches_the_graphify_drain(self):
        config = json.loads(json.dumps(CONFIG))
        config["daemon"]["graphify_repo_root"] = str(self.tmp)
        daemon = vd.VaultDaemon(self.vault, self.outbox, config, today=TODAY)
        (self.outbox / "queue" / "graphify").write_text("a.md", encoding="utf-8")
        with mock.patch("daemon_drains.drain_graphify",
                        return_value={"returncode": 0}) as drain:
            daemon.drain(TAG, WINDOW)
        self.assertEqual(drain.call_args[0][1], Path(self.tmp))
        self.assertEqual(daemon.read_queue("graphify"), [])

    def test_a_completed_event_leaves_no_state_file(self):
        report = self._run(self._drop(), {"scope": "reusable",
                                          "technology": "Ollama",
                                          "confidence": 0.9})
        self.assertFalse((self.outbox / "state" / f"{report['event']}.json").exists())
        self.assertEqual(list((self.outbox / "state").glob("*.json")), [])

    def test_a_state_file_that_survives_is_reported_by_the_recovery_sweep(self):
        """A state file outliving its event means the daemon died between the
        write and the archive, so the sweep names it: that is the list of notes
        to check against the journal."""
        self.daemon.write_state("crashed-event", {"state": "WRITE", "rel": "x.md"})
        with mock.patch("sys.stderr", new=io.StringIO()) as err:
            self.daemon.recover_working()
            messages = err.getvalue()
        self.assertIn("crashed-event.json", messages)

    def test_a_drop_stranded_by_a_crash_is_recovered(self):
        """Claiming moves the drop out of raw/, so a daemon that dies mid-event
        would strand it forever. The startup sweep is what preserves the replay
        guarantee the crash ordering was designed for."""
        drop = self._drop()
        claimed = self.daemon.claim(drop)
        self.assertFalse(drop.exists())
        recovered = vd.VaultDaemon(self.vault, self.outbox, CONFIG,
                                   today=TODAY).recover_working()
        self.assertEqual(recovered, [claimed.name])
        self.assertTrue(drop.exists())
        self.assertFalse(claimed.exists())

    def test_recovery_drops_a_stranded_copy_when_the_drop_came_back(self):
        drop = self._drop()
        claimed = self.daemon.claim(drop)
        self._drop()                      # the same name arrives again
        self.assertEqual(self.daemon.recover_working(), [])
        self.assertFalse(claimed.exists())
        self.assertTrue(drop.exists())

    def test_the_drains_are_not_run_on_the_event_path(self):
        with mock.patch.object(vd.VaultDaemon, "drain") as drain:
            self._run(self._drop(), {"scope": "reusable", "technology": "Ollama",
                                     "confidence": 0.9})
        drain.assert_not_called()

    def test_the_drain_consumes_and_clears_both_queues(self):
        self._run(self._drop(), {"scope": "reusable", "technology": "Ollama",
                                 "confidence": 0.9})
        with mock.patch("daemon_drains.drain_consolidation",
                        return_value={"accepted": [], "rejected": []}) as cons:
            with mock.patch("daemon_drains.drain_graphify",
                            return_value={"skipped": "test"}):
                report = self.daemon.drain(TAG, WINDOW)
        cons.assert_called_once()
        self.assertIsNotNone(report["consolidation"])
        self.assertEqual(self.daemon.read_queue("consolidate"), [])
        # The graphify queue is deliberately NOT cleared here: no repository is
        # configured in this fixture, so its work was skipped, and clearing a
        # queue whose work never ran would lose it.
        self.assertIn("graphify_repo_root", report["graphify"]["skipped"])
        self.assertNotEqual(self.daemon.read_queue("graphify"), [])

    def test_graphify_is_skipped_when_no_repository_is_configured(self):
        """A daemon is started by hand from wherever the operator stands, so
        inferring the repository from the working directory would refresh the
        wrong graph. No configured root is a stated skip."""
        (self.outbox / "queue" / "graphify").write_text("a.md", encoding="utf-8")
        with mock.patch("daemon_drains.drain_graphify",
                        side_effect=AssertionError) as never:
            report = self.daemon.drain(TAG, WINDOW)
        never.assert_not_called()
        self.assertIn("graphify_repo_root", report["graphify"]["skipped"])
        self.assertEqual(self.daemon.read_queue("graphify"), ["a.md"],
                         "a skipped queue must not be cleared")

    def test_a_configured_repository_reaches_the_graphify_drain(self):
        config = json.loads(json.dumps(CONFIG))
        config["daemon"]["graphify_repo_root"] = str(self.tmp)
        daemon = vd.VaultDaemon(self.vault, self.outbox, config, today=TODAY)
        (self.outbox / "queue" / "graphify").write_text("a.md", encoding="utf-8")
        with mock.patch("daemon_drains.drain_graphify",
                        return_value={"returncode": 0}) as drain:
            daemon.drain(TAG, WINDOW)
        self.assertEqual(drain.call_args[0][1], Path(self.tmp))
        self.assertEqual(daemon.read_queue("graphify"), [])

    def test_a_completed_event_leaves_no_state_file(self):
        report = self._run(self._drop(), {"scope": "reusable",
                                          "technology": "Ollama",
                                          "confidence": 0.9})
        self.assertFalse((self.outbox / "state" / f"{report['event']}.json").exists())
        self.assertEqual(list((self.outbox / "state").glob("*.json")), [])

    def test_a_state_file_that_survives_is_reported_by_the_recovery_sweep(self):
        """A state file outliving its event means the daemon died between the
        write and the archive, so the sweep names it: that is the list of notes
        to check against the journal."""
        self.daemon.write_state("crashed-event", {"state": "WRITE", "rel": "x.md"})
        with mock.patch("sys.stderr", new=io.StringIO()) as err:
            self.daemon.recover_working()
            messages = err.getvalue()
        self.assertIn("crashed-event.json", messages)

    def test_a_drop_stranded_by_a_crash_is_recovered(self):
        """Claiming moves the drop out of raw/, so a daemon that dies mid-event
        would strand it forever. The startup sweep preserves the replay
        guarantee the crash ordering was designed for."""
        drop = self._drop()
        claimed = self.daemon.claim(drop)
        self.assertFalse(drop.exists())
        recovered = vd.VaultDaemon(self.vault, self.outbox, CONFIG,
                                   today=TODAY).recover_working()
        self.assertEqual(recovered, [claimed.name])
        self.assertTrue(drop.exists())
        self.assertFalse(claimed.exists())

    def test_recovery_drops_a_stranded_copy_when_the_drop_came_back(self):
        drop = self._drop()
        claimed = self.daemon.claim(drop)
        self._drop()
        self.assertEqual(self.daemon.recover_working(), [])
        self.assertFalse(claimed.exists())
        self.assertTrue(drop.exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
