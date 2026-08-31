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

Reclamation. A holder is reclaimed when its process is gone, or when the lock is
older than a staleness ceiling. Liveness is probed with OpenProcess on Windows
and with signal 0 on POSIX: os.kill(pid, 0) is NOT portable here, because
Windows Python maps os.kill onto TerminateProcess, so probing with it would kill
the very process being tested. A lock written by another HOST is never judged by
its pid, since pids are per machine; only the age ceiling can reclaim it.

Timeouts are arguments, never literals (R0). The caller reads them from
daemon-config.json.
"""
import ctypes
import json
import os
import socket
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

_WIN_SYNCHRONIZE = 0x00100000
_WIN_ERROR_ACCESS_DENIED = 5
MAX_RECLAIM_ATTEMPTS = 3  # bounded retry (R10): a livelock must end as a refusal


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
        handle = kernel32.OpenProcess(_WIN_SYNCHRONIZE, False, pid)
        if handle:
            kernel32.CloseHandle(handle)
            return True
        # Access denied means the process exists and belongs to someone else.
        return kernel32.GetLastError() == _WIN_ERROR_ACCESS_DENIED
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


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
                 poll_interval_s):
        self.lock_path = Path(lock_path)
        self.acquire_timeout_s = float(acquire_timeout_s)
        self.stale_after_s = float(stale_after_s)
        self.poll_interval_s = float(poll_interval_s)
        self.reclaimed: list[str] = []
        self._token: str | None = None

    def _try_create(self) -> bool:
        token = uuid.uuid4().hex
        payload = json.dumps({
            "pid": os.getpid(),
            "host": socket.gethostname(),
            "token": token,
            "at": _utc_now_iso(),
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
            # Whatever the timestamp says. A live pid on this machine IS the holder.
            if pid_alive(pid):
                return None
            return f"holder pid {pid} is gone"

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


def held_by_live_holder(lock_path, stale_after_s) -> bool:
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

    Outputs:
        live (bool): True only when a holder exists and is neither dead nor
        past the staleness ceiling. Never mutates the lock file.
    --------------------------------------------------------------------------
    """
    probe = VaultLock(lock_path, acquire_timeout_s=0, stale_after_s=stale_after_s,
                      poll_interval_s=0)
    if not probe.lock_path.exists():
        return False
    return probe._stale_reason(probe._read_holder()) is None
