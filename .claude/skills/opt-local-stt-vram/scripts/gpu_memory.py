#!/usr/bin/env python3
"""
gpu_memory.py - how much GPU memory ONE process holds, and where.

On Windows (WDDM) nvidia-smi's memory.used is a card total that cannot say whose memory is
whose, and a process's allocation can be demoted to system RAM without that total saying
so. The per-process performance counters '\\GPU Process Memory(pid_N*)\\Dedicated Usage'
and '...\\Shared Usage' can (measured 2026-09-26 on an RTX A1000: they showed the resident
LLM losing 1.3 GB of VRAM to a Whisper model that nvidia-smi reported as fitting).
Elsewhere, nvidia-smi --query-compute-apps gives the per-process figure and no shared
share. That second path is proven by the offline suite only, not on a Linux machine.

Every unanswerable read raises GpuMemoryUnavailable with its reason (R8): a zero would read
like a measurement.
"""
import subprocess

_WIN_COUNTERS = (
    "$s=(Get-Counter '\\GPU Process Memory(pid_{pid}*)\\Dedicated Usage',"
    "'\\GPU Process Memory(pid_{pid}*)\\Shared Usage' -ErrorAction SilentlyContinue).CounterSamples;"
    "if ($s) {{"
    "$d=($s|?{{$_.Path -match 'dedicated'}}|Measure-Object CookedValue -Sum).Sum;"
    "$h=($s|?{{$_.Path -match 'shared'}}|Measure-Object CookedValue -Sum).Sum;"
    "'{{0}} {{1}}' -f [math]::Round($d/1MB),[math]::Round($h/1MB) }}")


class GpuMemoryUnavailable(RuntimeError):
    """The GPU memory of a process could not be read; the message says why."""


def _run(runner, argv: list, timeout_s: float) -> str:
    try:
        out = runner(argv, capture_output=True, text=True, timeout=timeout_s)
    except subprocess.TimeoutExpired:
        raise GpuMemoryUnavailable(f"{argv[0]} timed out after {timeout_s} s") from None
    except (FileNotFoundError, OSError) as exc:
        raise GpuMemoryUnavailable(f"{argv[0]} could not be run: {exc}") from None
    if out.returncode != 0:
        raise GpuMemoryUnavailable(f"{argv[0]} exited {out.returncode}")
    return out.stdout or ""


def process_memory_mib(pid: int, timeout_s: float, runner=subprocess.run,
                       platform: str = None) -> dict:
    """
    --------------------------------------------------------------------------
    Purpose:
        Read the dedicated and shared GPU memory one process holds.

    Inputs:
        pid (int): the process
        timeout_s (float): bound on the one subprocess call (R10)
        runner (callable): subprocess.run, injected by the suite
        platform (str): sys.platform, injected by the suite

    Outputs:
        memory (dict): dedicated_mib (int) and shared_mib (int, or None where
        the platform cannot tell)

    Raises:
        GpuMemoryUnavailable: the tool is absent, timed out, failed, or does not
            list the process.
    --------------------------------------------------------------------------
    """
    import sys
    platform = platform or sys.platform
    if platform == "win32":
        text = _run(runner, ["powershell", "-NoProfile", "-Command",
                             _WIN_COUNTERS.format(pid=pid)], timeout_s).split()
        if len(text) != 2:
            raise GpuMemoryUnavailable(f"no GPU Process Memory counter for pid {pid}")
        return {"dedicated_mib": int(text[0]), "shared_mib": int(text[1])}
    text = _run(runner, ["nvidia-smi", "--query-compute-apps=pid,used_memory",
                         "--format=csv,noheader,nounits"], timeout_s)
    for line in text.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) == 2 and parts[0] == str(pid):
            return {"dedicated_mib": int(parts[1]), "shared_mib": None}
    raise GpuMemoryUnavailable(f"nvidia-smi lists no GPU process {pid}")


_WIN_ALL = (
    "(Get-Counter '\\GPU Process Memory(*)\\Dedicated Usage' -ErrorAction SilentlyContinue)"
    ".CounterSamples | Group-Object { ($_.InstanceName -split '_')[1] } | ForEach-Object "
    "{ '{0} {1}' -f $_.Name, [math]::Round(($_.Group | Measure-Object CookedValue -Sum).Sum/1MB) }")


def other_gpu_processes(exclude_pids: list, timeout_s: float, runner=subprocess.run,
                        platform: str = None) -> dict:
    """
    --------------------------------------------------------------------------
    Purpose:
        List every OTHER process holding dedicated GPU memory, so a benchmark
        can say what else shares the card instead of silently measuring beside
        it (measured 2026-09-26: a dashboard left open held its own Whisper,
        929 MiB, which would have been charged to every candidate).

    Inputs:
        exclude_pids (list[int]): processes that belong to the measurement
        timeout_s (float): bound on the one subprocess call (R10)
        runner (callable): subprocess.run, injected by the suite
        platform (str): sys.platform, injected by the suite

    Outputs:
        others (dict[int, int]): pid -> dedicated MiB, zero-MiB processes left out

    Raises:
        GpuMemoryUnavailable: the tool is absent, timed out or failed.
    --------------------------------------------------------------------------
    """
    import sys
    platform = platform or sys.platform
    if platform == "win32":
        text = _run(runner, ["powershell", "-NoProfile", "-Command", _WIN_ALL], timeout_s)
        pairs = [line.split() for line in text.splitlines()]
    else:
        text = _run(runner, ["nvidia-smi", "--query-compute-apps=pid,used_memory",
                             "--format=csv,noheader,nounits"], timeout_s)
        pairs = [[p.strip() for p in line.split(",")] for line in text.splitlines()]
    others = {}
    for pair in pairs:
        if len(pair) == 2 and pair[0].isdigit() and pair[1].isdigit():
            pid, mib = int(pair[0]), int(pair[1])
            if mib > 0 and pid not in exclude_pids:
                others[pid] = others.get(pid, 0) + mib
    return others


def find_llm_pid(names: list, timeout_s: float, runner=subprocess.run,
                 platform: str = None) -> int:
    """
    --------------------------------------------------------------------------
    Purpose:
        Find the process that holds the resident LLM's weights (Ollama runs
        the model in a child, llama-server.exe on Windows as of 0.33.0).

    Inputs:
        names (list[str]): process names to look for, from the config
        timeout_s (float): bound on the one subprocess call (R10)
        runner (callable): subprocess.run, injected by the suite
        platform (str): sys.platform, injected by the suite

    Outputs:
        pid (int): the first matching process

    Raises:
        GpuMemoryUnavailable: no process of those names is running.
    --------------------------------------------------------------------------
    """
    import sys
    platform = platform or sys.platform
    if platform == "win32":
        argv = ["powershell", "-NoProfile", "-Command",
                "Get-Process -Name %s -ErrorAction SilentlyContinue | "
                "ForEach-Object { $_.Id }" % ",".join(names)]
    else:
        argv = ["pgrep", "-x", "|".join(names)]
    try:
        text = _run(runner, argv, timeout_s)
    except GpuMemoryUnavailable:
        text = ""
    pids = [int(t) for t in text.split() if t.isdigit()]
    if not pids:
        raise GpuMemoryUnavailable(f"no running LLM process named {', '.join(names)}")
    return pids[0]
