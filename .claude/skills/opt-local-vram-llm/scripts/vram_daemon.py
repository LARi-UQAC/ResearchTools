#!/usr/bin/env python3
"""
vram_daemon.py - the second search axis: moving the Ollama daemon between KV cache types.

OLLAMA_KV_CACHE_TYPE decides how many tokens fit in the VRAM left over after the weights,
which makes it the axis that matters most for the retained window. It is also the axis that
cannot be set per request: the daemon reads it once at start, so every value costs a
restart, and a restart evicts the resident model.

Split out of vram_optimizer.py to keep both files under the repository's 4096-token source
ceiling, and because "how do I move the daemon and prove it moved" is a different concern
from "which measured configuration wins".
"""

from __future__ import annotations

import contextlib
import logging
import subprocess
from pathlib import Path
from typing import Callable, Iterator

import vram_probe

logger = logging.getLogger(__name__)

KV_CACHE_VARIABLE = "OLLAMA_KV_CACHE_TYPE"

# The axis values, cheapest cache first. f16 is exact and largest, q4_0 is smallest and
# adds dequantisation work on every cache access; which one wins is measured, not assumed.
KV_CACHE_TYPES: tuple[str, ...] = ("f16", "q8_0", "q4_0")

_RESTART_TIMEOUT_S = 300.0

# scripts/dev/restart-ollama.ps1, five levels up from
# .claude/skills/opt-local-vram-llm/scripts/vram_daemon.py.
RESTART_SCRIPT = Path(__file__).resolve().parents[4] / "scripts" / "dev" / "restart-ollama.ps1"


class DaemonError(Exception):
    """Raised when the daemon cannot be moved, or did not move. Never degrades quietly."""


def _write_user_env(name: str, value: str) -> None:
    """
    --------------------------------------------------------------------------
    Purpose:
        Set a persistent USER environment variable. The daemon is launched by
        the tray application at logon, so it never sees a variable exported in
        this process; it must be written to the user scope and the daemon
        restarted afterwards.

    Inputs:
        name (str): variable name.
        value (str): value to set.

    Outputs:
        None.

    Raises:
        DaemonError: PowerShell failed or could not run.
    --------------------------------------------------------------------------
    """
    script = f"[Environment]::SetEnvironmentVariable('{name}', '{value}', 'User')"
    try:
        done = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, text=True, timeout=_RESTART_TIMEOUT_S)
    except (OSError, subprocess.SubprocessError) as exc:
        raise DaemonError(f"[VRAM-DAEMON] could not set {name}: {exc}") from exc
    if done.returncode != 0:
        raise DaemonError(f"[VRAM-DAEMON] could not set {name}: {done.stderr.strip()}")


def _run_restart_script(restart_script: Path) -> None:
    """
    --------------------------------------------------------------------------
    Purpose:
        Restart the Ollama daemon through the repository's own script, which
        kills BOTH `ollama` and the `llama-server.exe` child that a naive
        process-name pattern misses, and verifies against nvidia-smi that the
        VRAM actually came back. Orphaned children holding VRAM produced a
        false throughput measurement on this machine on 2026-08-14.

    Inputs:
        restart_script (Path): path to scripts/dev/restart-ollama.ps1.

    Outputs:
        None.

    Raises:
        DaemonError: the script is missing, could not run, or exited non-zero.
    --------------------------------------------------------------------------
    """
    if not restart_script.is_file():
        raise DaemonError(f"[VRAM-DAEMON] restart script not found at {restart_script}.")
    try:
        done = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-File", str(restart_script)],
            capture_output=True, text=True, timeout=_RESTART_TIMEOUT_S)
    except (OSError, subprocess.SubprocessError) as exc:
        raise DaemonError(f"[VRAM-DAEMON] restart could not run: {exc}") from exc
    if done.returncode != 0:
        raise DaemonError(f"[VRAM-DAEMON] restart failed: {done.stderr.strip()}")


def active_kv_cache_type() -> str:
    """
    --------------------------------------------------------------------------
    Purpose:
        Report the KV cache type the RUNNING daemon has, from its own log.

    Inputs:
        None.

    Outputs:
        result (str): the active value, or "" when the log does not name it.
    --------------------------------------------------------------------------
    """
    return vram_probe.daemon_settings().get(KV_CACHE_VARIABLE, "")


def set_kv_cache_type(value: str, restart_script: Path = RESTART_SCRIPT) -> None:
    """
    --------------------------------------------------------------------------
    Purpose:
        Move the daemon onto one value of the KV cache axis and PROVE it took
        it.

        The order is fixed and load-bearing: write the variable, then restart,
        then verify. Restarting first would have the daemon re-read the old
        value, and the sweep would then attribute its numbers to a setting that
        was never active - the same class of false measurement as the orphaned
        llama-server processes of 2026-08-14.

    Inputs:
        value (str): one of KV_CACHE_TYPES.
        restart_script (Path): path to restart-ollama.ps1.

    Outputs:
        None.

    Raises:
        DaemonError: the write or the restart failed, or the daemon came back
        on a different value.
    --------------------------------------------------------------------------
    """
    _write_user_env(KV_CACHE_VARIABLE, value)
    _run_restart_script(restart_script)
    active = active_kv_cache_type()
    if active != value:
        raise DaemonError(
            f"[VRAM-DAEMON] asked the daemon for {KV_CACHE_VARIABLE}={value} but it came "
            f"back with {active!r}; refusing to measure against a setting that is not active."
        )
    logger.info("[VRAM-DAEMON] daemon now on %s=%s", KV_CACHE_VARIABLE, value)


@contextlib.contextmanager
def axis_restored(
    original_value: str,
    restart_script: Path = RESTART_SCRIPT,
) -> Iterator[Callable[[str], None]]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Yield a function that moves the daemon onto an axis value, and put the
        daemon back on `original_value` when the block exits for ANY reason.
        The machine must never be left on a value chosen by an aborted search:
        the next unrelated run would then measure against it without knowing.

    Inputs:
        original_value (str): the value read before the search started.
        restart_script (Path): path to restart-ollama.ps1.

    Outputs:
        Yields a callable taking one axis value.
    --------------------------------------------------------------------------
    """
    applied: list[str] = []

    def apply_axis(value: str) -> None:
        applied.append(value)
        set_kv_cache_type(value, restart_script)

    try:
        yield apply_axis
    finally:
        if applied and applied[-1] != original_value:
            logger.info("[VRAM-DAEMON] restoring %s=%s", KV_CACHE_VARIABLE, original_value)
            try:
                set_kv_cache_type(original_value, restart_script)
            except DaemonError as exc:
                logger.error("[VRAM-DAEMON] could not restore the axis value: %s", exc)
