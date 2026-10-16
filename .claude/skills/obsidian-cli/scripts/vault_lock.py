#!/usr/bin/env python3
"""
vault_lock.py - single-writer lock over the machine-global Obsidian outbox.

Stage 0 of the vault event daemon. The outbox (~/.claude/obsidian-outbox/) is
shared by every Claude Code session on this machine, so two sessions can already
flush concurrently into the same Decisions.md. vault-access-guard.py does not
close that hole: it guards Claude Code tool calls, and a daemon is a separate OS
process that never passes through it. This lock is the only mechanism spanning
both.

The lock file lives BESIDE the outbox and never inside the vault, so a machine
with no vault keeps a clean no-op.

Reclamation. A holder is reclaimed when its process is gone, when its pid now
belongs to a different process, or when the lock is older than a staleness
ceiling. Liveness is probed with OpenProcess on Windows and with signal 0 on
POSIX: os.kill(pid, 0) is NOT portable here, because Windows Python maps
os.kill onto TerminateProcess, so probing with it would kill the very process
being tested. A lock written by another HOST is never judged by its pid, since
pids are per machine; only the age ceiling can reclaim it.

Pid reuse. A pid alone does not identify a process across a reboot. Diagnosed
2026-10-01 from vault-daemon.log against the Windows boot log: on 2026-09-29 the
daemon, killed at shutdown with its lock in place, found its own stale pid
alive after the reboot (an unrelated process, most likely its own launch chain)
and refused to start, so no daemon ran for the whole day. The lock therefore
also records "started", the creation marker of the holder's process
(process_start_marker); a live pid whose current marker differs is a reused pid
and the lock is reclaimed. A SECOND, independent check (_boot_time_utc, added
2026-10-07 from the PR #42 review) reclaims any same-host lock whose own "at"
predates this boot, regardless of whether "started" was ever recorded - so a
lock written before process_start_marker existed is covered too, on a full
restart. Remaining gaps: Windows Fast Startup's hybrid shutdown does not reset
the tick counter the boot check reads (stated limit, see _boot_time_utc; a
one-time daemon restart after this fix lands closes it, since every lock from
then on carries "started"), and a reused pid that this user cannot query
(another account) is still read as the holder.

Timeouts are arguments, never literals (R0). The caller reads them from
daemon-config.json.
"""
import ctypes
import json
import os
import socket
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

_WIN_SYNCHRONIZE = 0x00100000
_WIN_QUERY_LIMITED_INFORMATION = 0x1000
_WIN_ERROR_ACCESS_DENIED = 5
_WIN_STILL_ACTIVE = 259
MAX_RECLAIM_ATTEMPTS = 3  # bounded retry (R10): a livelock must end as a refusal


class _FileTime(ctypes.Structure):
    _fields_ = [("low", ctypes.c_uint32), ("high", ctypes.c_uint32)]


class LockError(RuntimeError):
    """The lock could not be acquired within the caller's timeout."""


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def pid_alive(pid: int) -> bool:
    """
    --------------------------------------------------------------------------
    Purpose:
        Report whether a process id is still running, without signalling it.

    Inputs:
        pid (int): the process id read from a lock file

    Outputs:
        alive (bool): True when the process exists, or exists but is not
        accessible to this user. False only when it is provably gone.
    --------------------------------------------------------------------------
    """
    if pid <= 0:
        return False
    if os.name == "nt":
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(
            _WIN_SYNCHRONIZE | _WIN_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            # Access denied means the process exists and belongs to someone else.
            return kernel32.GetLastError() == _WIN_ERROR_ACCESS_DENIED
        try:
            # A successfully opened handle is NOT proof of a running process:
            # measured 2026-09-26, OpenProcess(SYNCHRONIZE) still succeeded
            # for a pid Get-Process, tasklist and WMI all agreed had already
            # exited - Windows keeps the kernel object openable for a window
            # after exit. GetExitCodeProcess is the only thing that actually
            # distinguishes "running" from "exited, handle not yet reaped".
            exit_code = ctypes.c_ulong(0)
            if not kernel32.GetExitCodeProcess(
                    handle, ctypes.pointer(exit_code)):
                return True  # Could not query; assume alive rather than guess.
            return exit_code.value == _WIN_STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _boot_time_utc() -> "datetime | None":
    """
    --------------------------------------------------------------------------
    Purpose:
        This machine's boot time, UTC: the general form of the pid-reuse
        check, independent of whether "started" was ever recorded in a given
        lock file. PR #42's review named the gap this closes - a lock
        written before process_start_marker existed keeps the old
        pid-decides rule through the first FULL RESTART after this fix
        lands, since there is no marker in it to compare. A lock's own "at"
        timestamp predating the boot, with its pid alive now, is reused
        whatever the lock carries. Stated limit (round 2 of the review,
        M1): Windows Fast Startup hibernates the kernel session on
        "shut down then power on" rather than resetting it, so
        GetTickCount64 does NOT reset there the way it does on a real
        restart - a legacy lock survives that specific shutdown path even
        after this fix. New locks are unaffected, since they always carry
        "started". Confirmed on this machine (Fast Startup is enabled, per
        the PR thread): restart the vault daemon once after this fix lands,
        so every lock it holds from then on carries "started" and is
        reboot-safe whichever way the machine is powered off.

    Inputs:
        none.

    Outputs:
        boot (datetime | None): UTC boot time, or None when it cannot be
        read (unsupported platform, permission, parse failure). Never
        raises; the caller degrades to the existing started-marker/pid rule
        rather than refuse to judge the lock (R11).
    --------------------------------------------------------------------------
    """
    try:
        if os.name == "nt":
            kernel32 = ctypes.windll.kernel32
            kernel32.GetTickCount64.restype = ctypes.c_ulonglong
            uptime_ms = kernel32.GetTickCount64()
            return datetime.now(timezone.utc) - timedelta(milliseconds=uptime_ms)
        uptime_path = Path("/proc/uptime")
        if uptime_path.exists():
            uptime_s = float(uptime_path.read_text(encoding="utf-8").split()[0])
            return datetime.now(timezone.utc) - timedelta(seconds=uptime_s)
    except (OSError, ValueError, IndexError, AttributeError):
        # Same width as process_start_marker's own narrowing, round-2 review
        # (mutation-testing gap #2): a ctypes/WinError failure (OSError), a
        # garbage /proc/uptime (ValueError from float(), IndexError from an
        # empty split()), or a missing ctypes binding (AttributeError).
        return None
    return None


def process_start_marker(pid: int) -> "int | None":
    """
    --------------------------------------------------------------------------
    Purpose:
        Identify ONE incarnation of a pid, so a lock can tell the process that
        wrote it from an unrelated process that was later given the same pid.

    Details:
        Windows: creation time from GetProcessTimes (100 ns ticks, as an int).
        Linux: field 22 (starttime, clock ticks since boot) of /proc/<pid>/stat,
        parsed after the LAST ")" because comm may contain spaces and parentheses.
        The value is opaque: compare for equality only, never across platforms.

    Inputs:
        pid (int): the process id to inspect

    Outputs:
        marker (int | None): the opaque marker, or None on any other platform
        or whenever it cannot be read (process gone, access denied, parse
        failure). Never raises.
    --------------------------------------------------------------------------
    """
    try:
        if pid <= 0:
            return None
        if os.name == "nt":
            from ctypes import wintypes
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.OpenProcess.argtypes = [
                wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
            kernel32.OpenProcess.restype = wintypes.HANDLE
            kernel32.GetProcessTimes.argtypes = [
                wintypes.HANDLE, ctypes.POINTER(_FileTime),
                ctypes.POINTER(_FileTime), ctypes.POINTER(_FileTime),
                ctypes.POINTER(_FileTime)]
            kernel32.GetProcessTimes.restype = wintypes.BOOL
            kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
            kernel32.CloseHandle.restype = wintypes.BOOL
            handle = kernel32.OpenProcess(
                _WIN_QUERY_LIMITED_INFORMATION, False, pid)
            if not handle:
                return None
            try:
                created, exited, kernel, user = (
                    _FileTime(), _FileTime(), _FileTime(), _FileTime())
                if not kernel32.GetProcessTimes(
                        handle, ctypes.byref(created), ctypes.byref(exited),
                        ctypes.byref(kernel), ctypes.byref(user)):
                    return None
                return (created.high << 32) | created.low
            finally:
                kernel32.CloseHandle(handle)
        stat = Path(f"/proc/{pid}/stat")
        if stat.exists():
            tail = stat.read_text(encoding="utf-8").rsplit(")", 1)[1].split()
            # tail[0] is field 3 (state), so field 22 sits at index 19.
            return int(tail[19])
    except (OSError, ValueError, IndexError, AttributeError):
        # Every realistic failure here: a dead/inaccessible pid (OSError), a
        # malformed /proc/<pid>/stat parse (IndexError/ValueError), or a
        # ctypes binding gap on an exotic platform (AttributeError). Narrowed
        # from a bare `except Exception` per the PR #42 review (Low): that
        # caught a real bug here exactly like it degrades an expected one,
        # which is the silent-failure class R11 exists to keep visible.
        return None
    return None


class VaultLock:
    """
    --------------------------------------------------------------------------
    Purpose:
        Serialize every writer of the outbox and of the vault behind one lock
        file, and reclaim a lock its holder can no longer release.

    Inputs:
        lock_path (Path | str): the lock file, beside the outbox
        acquire_timeout_s (float): how long acquire() waits before refusing
        stale_after_s (float): age past which a lock is reclaimed
        poll_interval_s (float): wait between two acquisition attempts

    Outputs:
        Used as a context manager. `reclaimed` lists one reason string per
        reclamation performed, so the caller can log what it took over.
    --------------------------------------------------------------------------
    """

    def __init__(self, lock_path, acquire_timeout_s, stale_after_s,
                 poll_interval_s, boot_skew_tolerance_s=0.0):
        self.lock_path = Path(lock_path)
        self.acquire_timeout_s = float(acquire_timeout_s)
        self.stale_after_s = float(stale_after_s)
        self.poll_interval_s = float(poll_interval_s)
        # PR #42 review (Medium M2, owner-decided 2026-10-07): a lock's "at"
        # and the computed boot time are both wall-clock-derived, so a clock
        # step forward after the daemon wrote its lock (an NTP correction
        # shortly after boot, no RTC, a manual set) could make a genuinely
        # live daemon's lock look like it predates boot and get reclaimed -
        # a second daemon on the outbox, the exact collision the singleton
        # exists to prevent. Reused only when "at" predates boot by MORE
        # than this margin. Kept a float default rather than a required
        # parameter so a caller that has not been updated (an external
        # drill script, say) still runs - at the old, zero-margin behavior -
        # instead of raising; every caller inside this repository passes the
        # configured value (R0).
        self.boot_skew_tolerance_s = float(boot_skew_tolerance_s)
        self.reclaimed: list[str] = []
        self._token: str | None = None

    def _try_create(self) -> bool:
        token = uuid.uuid4().hex
        payload = json.dumps({
            "pid": os.getpid(),
            "host": socket.gethostname(),
            "token": token,
            "at": _utc_now_iso(),
            # Distinguishes this process from a later one given the same pid
            # (null where the platform cannot say).
            "started": process_start_marker(os.getpid()),
        })
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(self.lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            return False
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
        self._token = token
        return True

    def _read_holder(self) -> "dict | None":
        try:
            return json.loads(self.lock_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def _stale_reason(self, holder) -> "str | None":
        """
        ----------------------------------------------------------------------
        Purpose:
            Say why a holder may be reclaimed, or None when it may not.

            ON THIS HOST, LIVENESS DECIDES AND AGE DOES NOT. The order was the
            other way until 2026-08-30, and it was wrong for the singleton lock:
            age was tested first, so a holder past the ceiling was declared
            stale before the pid check could find it alive. The write lock is
            held around a filesystem write for milliseconds, which is what the
            300s ceiling was measured for; the daemon's singleton lock is held
            for the daemon's whole life. Measured that day: a daemon running
            since 13:19 held a 6h36m-old lock, `-Status` reported "not running",
            and acquire() would have DELETED that lock and started a second
            daemon on the same outbox - exactly what the singleton prevents.

            Age still decides for a foreign host, where a pid means nothing
            locally, and for a holder carrying no usable pid.

            A live pid is the holder only if it is the SAME process. When the lock
            carries an int "started" and the pid's current marker is readable and
            differs, the pid was reused and the lock is reclaimed (2026-09-29:
            after a reboot the dead daemon's pid was alive again, most likely
            inside the new daemon's own launch chain, and the daemon refused to
            start behind its own ghost - inferred from the log, not observed). A
            legacy lock with no "started", or an unreadable current marker, keeps
            the pid-decides rule; a pid reused by a process this user cannot
            query is therefore still read as the holder.

            The cost, stated: a wedged holder whose process is alive but doing
            no work is never reclaimed here. That is a different failure, and
            the log tail plus `-Status` are what surface it; silently evicting a
            live process to cover for it is the worse trade.
        ----------------------------------------------------------------------
        """
        if not isinstance(holder, dict):
            return "lock file is unreadable or malformed"

        pid = holder.get("pid")
        same_host = holder.get("host") == socket.gethostname()

        if same_host and isinstance(pid, int):
            # A lock recorded before THIS boot cannot belong to a process
            # still running now: whatever owns `pid` today necessarily
            # started after the lock was written, so it is a reused pid
            # regardless of whether "started" was ever recorded. Checked
            # before pid_alive/started so a legacy lock (written before that
            # field existed) is safe across a full restart - the High
            # finding from the PR #42 review: without this, the first full
            # restart after this fix ships still reproduced #41 for any
            # lock already on disk. Does NOT cover Windows Fast Startup's
            # hybrid shutdown (M1, stated limit, see _boot_time_utc); a
            # one-time daemon restart after this fix lands closes that gap
            # too, since every lock from then on carries "started".
            # Only when boot time is actually readable (R11): an unavailable
            # boot time degrades to the rule below rather than refusing to
            # judge the lock.
            stamp = holder.get("at")
            boot = _boot_time_utc()
            if boot is not None and stamp:
                try:
                    # Both operands must be aware for the comparison below, or
                    # a hand-edited or foreign-shaped "at" with no offset
                    # raises TypeError here exactly as it does on the
                    # foreign-host branch's subtraction further down -
                    # reproduced live during the PR #42 review (L1) and
                    # otherwise escaping acquire() and held_by_live_holder,
                    # which the flush hook calls (R11). A naive stamp is
                    # treated as UTC, matching how _utc_now_iso always writes
                    # one with an explicit offset, so only a value this
                    # module never produced itself takes this branch.
                    at = datetime.fromisoformat(str(stamp))
                    if at.tzinfo is None:
                        at = at.replace(tzinfo=timezone.utc)
                    margin = timedelta(seconds=self.boot_skew_tolerance_s)
                    is_before_boot = at < (boot - margin)
                except (TypeError, ValueError):
                    is_before_boot = False
                if is_before_boot:
                    return (f"holder pid {pid}'s lock was recorded at {stamp}, "
                            f"before this boot ({boot.replace(microsecond=0).isoformat()}); "
                            f"a live pid now is necessarily a reused pid")
            # Whatever the timestamp says otherwise: a live pid on this
            # machine is the holder, unless its start marker proves it is a
            # later process.
            if not pid_alive(pid):
                return f"holder pid {pid} is gone"
            recorded = holder.get("started")
            if isinstance(recorded, int) and not isinstance(recorded, bool):
                current = process_start_marker(pid)
                if current is not None and current != recorded:
                    return (f"holder pid {pid} was reused by a different "
                            f"process (start marker changed)")
            return None

        # Foreign host, or no usable pid: age is the only thing that can reclaim.
        stamp = holder.get("at")
        try:
            age = (datetime.now(timezone.utc)
                   - datetime.fromisoformat(str(stamp))).total_seconds()
        except (TypeError, ValueError):
            return "lock file carries no usable timestamp"
        if age > self.stale_after_s:
            return f"lock is {int(age)}s old, past the {int(self.stale_after_s)}s ceiling"
        return None

    def _reclaim(self, holder, reason: str) -> None:
        self.reclaimed.append(reason)
        try:
            self.lock_path.unlink()
        except FileNotFoundError:
            pass

    def acquire(self) -> "VaultLock":
        deadline = time.monotonic() + self.acquire_timeout_s
        reclaims = 0
        while True:
            if self._try_create():
                return self
            holder = self._read_holder()
            reason = self._stale_reason(holder)
            if reason and reclaims < MAX_RECLAIM_ATTEMPTS:
                reclaims += 1
                self._reclaim(holder, reason)
                continue
            if time.monotonic() >= deadline:
                held_by = holder if holder else "an unreadable holder"
                raise LockError(
                    f"[VAULT-LOCK] {self.lock_path} still held by {held_by} after "
                    f"{self.acquire_timeout_s}s; refusing to write concurrently."
                )
            time.sleep(self.poll_interval_s)

    def release(self) -> None:
        """Release only a lock this instance still owns, so a lock already
        reclaimed by someone else is never deleted from under them."""
        if self._token is None:
            return
        holder = self._read_holder()
        if isinstance(holder, dict) and holder.get("token") == self._token:
            try:
                self.lock_path.unlink()
            except FileNotFoundError:
                pass
        self._token = None

    def __enter__(self) -> "VaultLock":
        return self.acquire()

    def __exit__(self, exc_type, exc, tb) -> bool:
        self.release()
        return False


def held_by_live_holder(lock_path, stale_after_s, boot_skew_tolerance_s=0.0) -> bool:
    """
    --------------------------------------------------------------------------
    Purpose:
        Answer whether a lock file represents a holder that is still running,
        applying the same rules acquire() uses to decide it may reclaim one.
        A reader that merely tests for the file would call a crashed daemon
        alive, which is the exact case the outbox flush hook has to report on:
        drops waiting in raw/ with nothing left to consume them.

    Inputs:
        lock_path (Path | str): the lock file to inspect
        stale_after_s (float): age past which a holder is judged gone
        boot_skew_tolerance_s (float): see VaultLock's own docstring (R0:
            read from daemon-config.json's lock.boot_skew_tolerance_s by
            every caller inside this repository; defaulted here only so an
            external caller not yet updated still runs)

    Outputs:
        live (bool): True only when a holder exists and is neither dead nor
        past the staleness ceiling. Never mutates the lock file.
    --------------------------------------------------------------------------
    """
    probe = VaultLock(lock_path, acquire_timeout_s=0, stale_after_s=stale_after_s,
                      poll_interval_s=0, boot_skew_tolerance_s=boot_skew_tolerance_s)
    if not probe.lock_path.exists():
        return False
    return probe._stale_reason(probe._read_holder()) is None
