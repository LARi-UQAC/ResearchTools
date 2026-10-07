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
_LEGACY = object()  # sentinel: write a lock payload with no "started" key
# A marker no real process incarnation of this test run can have (R0: fixture).
FOREIGN_MARKER = 1


class VaultLockTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.lock_path = self.tmp / "obsidian-outbox.lock"

    def _lock(self, stale_after_s=STALE_AFTER_S, acquire_timeout_s=ACQUIRE_TIMEOUT_S):
        return vl.VaultLock(self.lock_path, acquire_timeout_s=acquire_timeout_s,
                            stale_after_s=stale_after_s,
                            poll_interval_s=POLL_INTERVAL_S)

    def _write_holder(self, pid, age_s=0.0, host=None, started=_LEGACY):
        stamp = datetime.now(timezone.utc) - timedelta(seconds=age_s)
        payload = {
            "pid": pid, "host": host or socket.gethostname(),
            "token": "someone-elses-token",
            "at": stamp.replace(microsecond=0).isoformat(),
        }
        if started is not _LEGACY:  # omitted = a lock written before "started"
            payload["started"] = started
        self.lock_path.write_text(json.dumps(payload), encoding="utf-8")

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

    def test_an_old_lock_with_a_LIVE_holder_is_NOT_reclaimed(self):
        """Inverted on 2026-08-30. This asserted the opposite, and the opposite
        was the defect: the daemon's singleton lock is held for the daemon's
        whole life, so age alone called a healthy daemon dead. Measured that
        day - a daemon running since 13:19 held a 6h36m-old lock, -Status said
        "not running", and acquire() would have deleted it and started a second
        daemon on the same outbox. On this host the pid decides."""
        self._write_holder(os.getpid(), age_s=STALE_AFTER_S + 30)
        long_ago = datetime.now(timezone.utc) - timedelta(days=365)
        with patch.object(vl, "_boot_time_utc", return_value=long_ago):
            with self.assertRaises(vl.LockError):
                self._lock().acquire()
        self.assertTrue(self.lock_path.exists(), "a live holder's lock must survive")

    def test_a_very_old_lock_with_a_live_holder_still_survives(self):
        """The real scale of the case, not just one tick over the ceiling: the
        measured lock was 6h36m old against a 300s ceiling. Boot time is
        pinned far in the past so this does not depend on the TEST machine's
        own real uptime (R19/R21) - without that pin, a test host rebooted
        less than 6h36m before the suite runs would make the new boot-reuse
        check below misfire on this very test."""
        self._write_holder(os.getpid(), age_s=6 * 3600 + 36 * 60)
        long_ago = datetime.now(timezone.utc) - timedelta(days=365)
        with patch.object(vl, "_boot_time_utc", return_value=long_ago):
            self.assertTrue(vl.held_by_live_holder(self.lock_path, STALE_AFTER_S),
                            "a running daemon must not be reported dead by age alone")

    def test_an_old_lock_whose_holder_is_DEAD_is_still_reclaimed(self):
        """The reorder must not cost the reclamation that matters: a crashed
        daemon leaves its lock behind and something has to take it."""
        self._write_holder(424242, age_s=STALE_AFTER_S + 30)
        with patch.object(vl, "pid_alive", return_value=False):
            lock = self._lock()
            with lock:
                pass
            self.assertEqual(len(lock.reclaimed), 1)
            self.assertIn("424242", lock.reclaimed[0])

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

    @unittest.skipUnless(os.name == "nt", "Windows-only liveness path")
    def test_pid_alive_checks_the_exit_code_not_only_the_handle(self):
        """Measured 2026-09-26: OpenProcess(SYNCHRONIZE) succeeded (handle
        516) for a pid Get-Process, tasklist and Get-CimInstance Win32_Process
        all agreed had already exited - Windows keeps that kernel object
        openable for a window after exit. A handle opening is not proof of
        life; GetExitCodeProcess is."""
        def fake_get_exit_code(handle, ref):
            ref.contents.value = 0  # exited, not STILL_ACTIVE
            return 1
        with patch.object(vl.ctypes.windll.kernel32, "OpenProcess",
                          return_value=516), \
             patch.object(vl.ctypes.windll.kernel32, "CloseHandle",
                          return_value=1), \
             patch.object(vl.ctypes.windll.kernel32, "GetExitCodeProcess",
                          side_effect=fake_get_exit_code):
            self.assertFalse(vl.pid_alive(24652))

    @unittest.skipUnless(os.name == "nt", "Windows-only liveness path")
    def test_pid_alive_says_yes_when_the_exit_code_is_still_active(self):
        """The positive control for the case above: an open handle whose
        GetExitCodeProcess reports STILL_ACTIVE (259) is genuinely alive."""
        def fake_get_exit_code(handle, ref):
            ref.contents.value = 259  # STILL_ACTIVE
            return 1
        with patch.object(vl.ctypes.windll.kernel32, "OpenProcess",
                          return_value=516), \
             patch.object(vl.ctypes.windll.kernel32, "CloseHandle",
                          return_value=1), \
             patch.object(vl.ctypes.windll.kernel32, "GetExitCodeProcess",
                          side_effect=fake_get_exit_code):
            self.assertTrue(vl.pid_alive(24652))

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
        # Age still decides for a FOREIGN host, where a local pid means nothing.
        self._write_holder(424242, age_s=STALE_AFTER_S + 30, host="some-other-machine")
        self.assertFalse(vl.held_by_live_holder(self.lock_path, STALE_AFTER_S))
        # ...and a dead holder is reported dead however fresh its timestamp is.
        self._write_holder(424242, age_s=0)
        with patch.object(vl, "pid_alive", return_value=False):
            self.assertFalse(vl.held_by_live_holder(self.lock_path, STALE_AFTER_S))

    # --- pid reuse after a reboot (diagnosed 2026-10-01) -------------------

    def test_a_reused_pid_with_a_different_start_marker_is_reclaimed(self):
        """Regression, the 2026-09-29 mechanism: the daemon was killed at
        shutdown with its lock in place, and after the reboot an unrelated
        process (most likely the daemon's own launch chain) had its pid. The pid
        is alive, but it is a different incarnation, so the lock is stale."""
        real = vl.process_start_marker(os.getpid())
        if real is None:
            self.skipTest("start marker unsupported on this platform")
        self._write_holder(os.getpid(), started=real + 12345)
        self.assertFalse(vl.held_by_live_holder(self.lock_path, STALE_AFTER_S))
        before = self.lock_path.read_text(encoding="utf-8")
        vl.held_by_live_holder(self.lock_path, STALE_AFTER_S)
        self.assertEqual(self.lock_path.read_text(encoding="utf-8"), before,
                         "the read-only probe must not touch the file")
        lock = self._lock()
        with lock:
            pass
        self.assertEqual(len(lock.reclaimed), 1)
        self.assertIn(str(os.getpid()), lock.reclaimed[0])
        self.assertIn("reused", lock.reclaimed[0])

    def test_a_live_holder_with_its_real_start_marker_is_still_held(self):
        """Negative control for the case above: without it, an implementation
        reclaiming every live holder would pass the regression."""
        real = vl.process_start_marker(os.getpid())
        if real is None:
            self.skipTest("start marker unsupported on this platform")
        self._write_holder(os.getpid(), started=real)
        self.assertTrue(vl.held_by_live_holder(self.lock_path, STALE_AFTER_S))
        with self.assertRaises(vl.LockError):
            vl.VaultLock(self.lock_path, acquire_timeout_s=0,
                         stale_after_s=STALE_AFTER_S,
                         poll_interval_s=POLL_INTERVAL_S).acquire()

    def test_a_legacy_lock_without_started_keeps_a_live_pid_as_holder(self):
        self._write_holder(os.getpid())  # no "started" key
        self.assertTrue(vl.held_by_live_holder(self.lock_path, STALE_AFTER_S))

    # --- the PR #42 review's High finding: a lock with no "started" field,
    # on the FIRST reboot after this fix lands, must still be reboot-safe ---

    def test_a_legacy_lock_from_before_this_boot_is_reclaimed_even_with_a_live_pid(self):
        """The gap the review named: vault_lock.py's old pid-decides rule for
        a holder with no "started" key meant the first reboot after this fix
        ships still reproduced #41, since nothing told a legacy lock apart
        from a genuine live holder. A lock recorded before the CURRENT boot
        cannot belong to a process still running now - whatever owns `pid`
        today necessarily started after the lock was written - so this is
        checked independently of whether "started" was ever recorded."""
        self._write_holder(os.getpid(), age_s=3600)  # written 1h ago, no "started"
        booted_recently = datetime.now(timezone.utc) - timedelta(seconds=10)
        with patch.object(vl, "_boot_time_utc", return_value=booted_recently):
            self.assertFalse(vl.held_by_live_holder(self.lock_path, STALE_AFTER_S))
            lock = self._lock()
            with lock:
                pass
        self.assertEqual(len(lock.reclaimed), 1)
        self.assertIn(str(os.getpid()), lock.reclaimed[0])
        self.assertIn("boot", lock.reclaimed[0])

    def test_a_lock_written_after_boot_is_not_reclaimed_by_the_boot_check(self):
        """Negative control: an ordinary lock, written well after the machine
        booted, by a genuinely live holder, must survive the new check -
        without this, an implementation reclaiming every lock older than
        boot time would pass the regression above for the wrong reason."""
        self._write_holder(os.getpid(), age_s=3600)
        booted_long_ago = datetime.now(timezone.utc) - timedelta(days=1)
        with patch.object(vl, "_boot_time_utc", return_value=booted_long_ago):
            self.assertTrue(vl.held_by_live_holder(self.lock_path, STALE_AFTER_S))

    def test_boot_check_degrades_when_boot_time_is_unreadable(self):
        """R11: a platform or permission failure that cannot report boot time
        falls back to the existing started-marker/pid rule rather than
        refusing to judge the lock at all."""
        self._write_holder(os.getpid(), age_s=3600)  # legacy, no "started"
        with patch.object(vl, "_boot_time_utc", return_value=None):
            self.assertTrue(vl.held_by_live_holder(self.lock_path, STALE_AFTER_S))

    def test_boot_time_utc_reads_a_plausible_value_or_degrades_to_none(self):
        boot = vl._boot_time_utc()
        if boot is not None:
            self.assertLess(boot, datetime.now(timezone.utc))

    def test_an_unreadable_current_marker_keeps_a_live_pid_as_holder(self):
        """Conservative on purpose: when the live process cannot be queried the
        pid decides, as before, rather than evicting a possibly real daemon."""
        self._write_holder(os.getpid(), started=FOREIGN_MARKER)
        with patch.object(vl, "process_start_marker", return_value=None):
            self.assertTrue(vl.held_by_live_holder(self.lock_path, STALE_AFTER_S))

    def test_a_dead_pid_is_reclaimed_whatever_the_marker_says(self):
        self._write_holder(424242, started=FOREIGN_MARKER)
        with patch.object(vl, "pid_alive", return_value=False):
            lock = self._lock()
            with lock:
                pass
        self.assertIn("424242", lock.reclaimed[0])
        self.assertIn("gone", lock.reclaimed[0])

    def test_try_create_records_this_process_start_marker(self):
        lock = self._lock()
        with lock:
            holder = json.loads(self.lock_path.read_text(encoding="utf-8"))
        self.assertIn("started", holder)
        self.assertEqual(holder["started"], vl.process_start_marker(os.getpid()))

    @unittest.skipIf(os.name == "nt", "exercises the Linux /proc parse path")
    def test_process_start_marker_degrades_on_a_malformed_proc_stat(self):
        """PR #42 review (Low): the bare `except Exception` around this
        function's body used to swallow everything, including a real bug.
        Narrowed to the failure shapes this parse can actually produce -
        proven here with a malformed /proc/<pid>/stat (IndexError from the
        rsplit) and with an unrelated exception type, which must still
        propagate rather than silently returning None."""
        with patch.object(vl.Path, "exists", return_value=True), \
             patch.object(vl.Path, "read_text", return_value="not a stat line"):
            self.assertIsNone(vl.process_start_marker(os.getpid()))

    @unittest.skipIf(os.name == "nt", "exercises the Linux /proc parse path")
    def test_process_start_marker_does_not_swallow_an_unrelated_bug(self):
        """Negative control for the narrowing above: a bare `except
        Exception` would also pass this, which is exactly what made it the
        wrong width."""
        with patch.object(vl.Path, "exists", side_effect=KeyError("boom")):
            with self.assertRaises(KeyError):
                vl.process_start_marker(os.getpid())

    @unittest.skipUnless(os.name == "nt" or Path("/proc/self/stat").exists(),
                         "start marker is implemented for Windows and Linux")
    def test_process_start_marker_is_stable_and_none_for_a_missing_pid(self):
        first = vl.process_start_marker(os.getpid())
        self.assertIsInstance(first, int)
        self.assertEqual(first, vl.process_start_marker(os.getpid()))
        self.assertIsNone(vl.process_start_marker(2 ** 31 - 2))
        self.assertIsNone(vl.process_start_marker(0))


if __name__ == "__main__":
    unittest.main(verbosity=2)
