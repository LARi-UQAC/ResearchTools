"""
test_vault_lock - offline checks for the single-writer lock over the outbox.

No vault, no daemon, no second process: every case runs against a lock file in
tempfile.mkdtemp(). The failure path matters most here (R20). A lock that is
never reclaimed blocks every session's local-writer until a human notices, and a
lock that is reclaimed too eagerly is the silent interleaving inside Decisions.md
the lock exists to prevent, so both directions are asserted.
"""
import importlib.util
import json
import os
import socket
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "vault_lock.py"
spec = importlib.util.spec_from_file_location("vault_lock_under_test", SCRIPT)
vl = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vl)

# Injected fixtures, never read from machine-local measured configuration (R21).
ACQUIRE_TIMEOUT_S = 0.3
STALE_AFTER_S = 60.0
POLL_INTERVAL_S = 0.01


class VaultLockTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.lock_path = self.tmp / "obsidian-outbox.lock"

    def _lock(self, stale_after_s=STALE_AFTER_S, acquire_timeout_s=ACQUIRE_TIMEOUT_S):
        return vl.VaultLock(self.lock_path, acquire_timeout_s=acquire_timeout_s,
                            stale_after_s=stale_after_s,
                            poll_interval_s=POLL_INTERVAL_S)

    def _write_holder(self, pid, age_s=0.0, host=None):
        stamp = datetime.now(timezone.utc) - timedelta(seconds=age_s)
        self.lock_path.write_text(json.dumps({
            "pid": pid, "host": host or socket.gethostname(),
            "token": "someone-elses-token",
            "at": stamp.replace(microsecond=0).isoformat(),
        }), encoding="utf-8")

    def test_acquire_creates_the_lock_and_release_removes_it(self):
        with self._lock():
            self.assertTrue(self.lock_path.exists())
            holder = json.loads(self.lock_path.read_text(encoding="utf-8"))
            self.assertEqual(holder["pid"], os.getpid())
        self.assertFalse(self.lock_path.exists())

    def test_a_live_holder_is_not_reclaimed_and_acquire_refuses(self):
        """The failure path. A lock held by a living process on this host must
        make acquire REFUSE, not take it over: taking it over is the concurrent
        write into Decisions.md that this whole mechanism exists to prevent."""
        self._write_holder(os.getpid())
        started = time.monotonic()
        with self.assertRaises(vl.LockError) as caught:
            self._lock().acquire()
        self.assertIn("still held by", str(caught.exception))
        self.assertGreaterEqual(time.monotonic() - started, ACQUIRE_TIMEOUT_S)
        self.assertTrue(self.lock_path.exists(), "the holder's lock must survive")

    def test_a_dead_holder_is_reclaimed(self):
        self._write_holder(424242)
        with patch.object(vl, "pid_alive", return_value=False):
            lock = self._lock()
            with lock:
                self.assertTrue(self.lock_path.exists())
            self.assertEqual(len(lock.reclaimed), 1)
            self.assertIn("424242", lock.reclaimed[0])

    def test_an_old_lock_is_reclaimed_even_with_a_live_holder(self):
        self._write_holder(os.getpid(), age_s=STALE_AFTER_S + 30)
        lock = self._lock()
        with lock:
            pass
        self.assertEqual(len(lock.reclaimed), 1)
        self.assertIn("ceiling", lock.reclaimed[0])

    def test_another_host_is_judged_by_age_only(self):
        """A pid from another machine means nothing here, so a fresh foreign
        lock is left alone even though that pid is not running locally."""
        self._write_holder(424242, host="some-other-machine")
        with patch.object(vl, "pid_alive", return_value=False):
            with self.assertRaises(vl.LockError):
                self._lock().acquire()

    def test_a_malformed_lock_file_is_reclaimed(self):
        self.lock_path.write_text("not json at all", encoding="utf-8")
        lock = self._lock()
        with lock:
            pass
        self.assertIn("unreadable", lock.reclaimed[0])

    def test_release_happens_on_an_exception(self):
        with self.assertRaises(ValueError):
            with self._lock():
                raise ValueError("work failed under the lock")
        self.assertFalse(self.lock_path.exists(),
                         "an abandoned lock blocks every later writer")

    def test_release_does_not_delete_a_lock_someone_else_now_holds(self):
        lock = self._lock()
        lock.acquire()
        # Simulate: our lock was reclaimed as stale and retaken by another writer.
        self._write_holder(999999)
        lock.release()
        self.assertTrue(self.lock_path.exists())

    def test_pid_alive_says_yes_for_this_process_and_no_for_a_free_pid(self):
        self.assertTrue(vl.pid_alive(os.getpid()))
        self.assertFalse(vl.pid_alive(0))

    def test_held_by_live_holder_reads_a_running_holder_and_never_mutates(self):
        """The read-only question the outbox flush hook asks about the daemon's
        singleton lock. It must answer without touching the file: a reader that
        reclaimed what it inspects would evict the very daemon it found."""
        self._write_holder(os.getpid())
        self.assertTrue(vl.held_by_live_holder(self.lock_path, STALE_AFTER_S))
        self.assertTrue(self.lock_path.exists())

    def test_held_by_live_holder_says_no_when_there_is_no_lock(self):
        self.assertFalse(vl.held_by_live_holder(self.lock_path, STALE_AFTER_S))

    def test_held_by_live_holder_says_no_for_a_dead_or_over_age_holder(self):
        """Both reclamation rules, in the direction the hook depends on: a
        crashed daemon leaves its lock behind, and reading the file's mere
        presence as a running daemon reports exactly backwards."""
        self._write_holder(424242)
        with patch.object(vl, "pid_alive", return_value=False):
            self.assertFalse(vl.held_by_live_holder(self.lock_path, STALE_AFTER_S))
        self._write_holder(os.getpid(), age_s=STALE_AFTER_S + 30)
        self.assertFalse(vl.held_by_live_holder(self.lock_path, STALE_AFTER_S))


if __name__ == "__main__":
    unittest.main(verbosity=2)
