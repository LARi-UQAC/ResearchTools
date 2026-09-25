"""
aider-thread-probe.py - how many CPU threads are worth giving a local model
that does not fit on the card, and what the real limit is.

Stage: measurement. Nothing here changes a model, a Modelfile or a daemon
setting. It loads, measures, and reports.

The GPU probe next to this file answers "which model x context puts layers on
the GPU". It does not answer the question that follows once the answer is
"almost none": the model is then running out of system RAM, so what bounds it -
the thread count, the PCIe bus, or system memory bandwidth. Those three have
different remedies and only one of them is "use more threads".

Two modes, because one measurement cannot separate them:

  bandwidth  aggregate DRAM read bandwidth against worker count. No model and
             no daemon. If the curve flattens at N workers, nothing running on
             this CPU goes faster past N threads, so the sweep's plateau has a
             cause rather than only a shape.

  sweep      one reload of the real model per thread rung, with a timed decode
             instrumented for CPU load, free RAM, hard page-ins and the PCIe
             traffic that actually crossed the bus during it.

Every parser of the daemon's log is IMPORTED from aider-gpu-probe.py rather
than copied, so there is one implementation of each reading. That file's name
carries hyphens and cannot be imported by name, so it is loaded by path - the
same approach already used elsewhere for session-hooks-inventory.py.

Exit codes (R12): 0 success, 2 a refusal by design, anything else a failure.
"""

from __future__ import annotations

import argparse
import ctypes
import importlib.util
import json
import multiprocessing as mp
import pathlib
import platform
import queue
import re
import shutil
import subprocess
import sys
import threading
import time

EXIT_OK = 0
EXIT_FAIL = 1
EXIT_REFUSED = 2

PROBE_FILENAME = "aider-gpu-probe.py"
CONFIG_FILENAME = "aider-thread-probe.json"

SRC_LOG = "server.log"
SRC_API = "/api/generate"
SRC_SMI = "nvidia-smi"


class Refusal(Exception):
    """Raised when this script must stop rather than guess. Names what is missing."""


# ---------------------------------------------------------------------------
# Borrowing the probe's parsers
# ---------------------------------------------------------------------------

def load_probe(path: pathlib.Path):
    """
    --------------------------------------------------------------------------
    Purpose:
        Load aider-gpu-probe.py as a module so its log parsers, its daemon
        client and its proven eviction routine are reused rather than copied.
        A second implementation of "read the offloaded layer count" is a second
        thing to keep correct.

    Inputs:
        path (pathlib.Path): the probe's location, normally beside this file.

    Outputs:
        module: the loaded probe. Refuses, naming the path, when it is absent
        or does not import, because every reading below depends on it.
    --------------------------------------------------------------------------
    """
    if not path.is_file():
        raise Refusal(f"the GPU probe was not found at {path}, and this script "
                      f"reuses its log parsers rather than carrying its own")
    spec = importlib.util.spec_from_file_location("aider_gpu_probe", path)
    if spec is None or spec.loader is None:
        raise Refusal(f"{path} could not be loaded as a Python module")
    module = importlib.util.module_from_spec(spec)
    sys.modules["aider_gpu_probe"] = module
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        raise Refusal(f"{path} failed to import: {type(exc).__name__}: {exc}") from exc
    return module


def load_config(path: pathlib.Path) -> dict:
    """Parse the configuration, refusing rather than defaulting."""
    if not path.is_file():
        raise Refusal(f"configuration file not found: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise Refusal(f"configuration file does not parse: {path}: {exc}") from exc


# ---------------------------------------------------------------------------
# Samplers. Each one degrades to "unavailable, with its reason" and never
# takes the run down with it: a missing counter is worth less than the
# measurement it accompanies (R11).
# ---------------------------------------------------------------------------

class _Win32Memory(ctypes.Structure):
    _fields_ = [("dwLength", ctypes.c_uint32),
                ("dwMemoryLoad", ctypes.c_uint32),
                ("ullTotalPhys", ctypes.c_uint64),
                ("ullAvailPhys", ctypes.c_uint64),
                ("ullTotalPageFile", ctypes.c_uint64),
                ("ullAvailPageFile", ctypes.c_uint64),
                ("ullTotalVirtual", ctypes.c_uint64),
                ("ullAvailVirtual", ctypes.c_uint64),
                ("ullAvailExtendedVirtual", ctypes.c_uint64)]


class _Filetime(ctypes.Structure):
    _fields_ = [("low", ctypes.c_uint32), ("high", ctypes.c_uint32)]


def _filetime_value(ft: _Filetime) -> int:
    return (ft.high << 32) | ft.low


class CpuRamSampler:
    """
    Total CPU load and memory headroom across a timed window, read through
    ctypes rather than a subprocess so a sample costs microseconds and the
    sampler does not itself perturb what it measures.

    CPU load comes from GetSystemTimes, whose kernel figure INCLUDES idle, so
    busy is (kernel + user - idle) and not (kernel + user). Getting that wrong
    reports a machine at 100 percent while it sleeps.
    """

    def __init__(self, interval_s: float):
        self.interval_s = float(interval_s)
        self.cpu_pct = []
        self.avail_phys_mib = []
        self.avail_pagefile_mib = []
        self.reason = None
        self._stop = threading.Event()
        self._thread = None
        self._kernel32 = None

    def _snapshot_times(self):
        idle, kernel, user = _Filetime(), _Filetime(), _Filetime()
        if not self._kernel32.GetSystemTimes(ctypes.byref(idle),
                                             ctypes.byref(kernel),
                                             ctypes.byref(user)):
            return None
        return _filetime_value(idle), _filetime_value(kernel), _filetime_value(user)

    def _snapshot_memory(self):
        status = _Win32Memory()
        status.dwLength = ctypes.sizeof(_Win32Memory)
        if not self._kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return None
        return (status.ullAvailPhys / (1024 * 1024),
                status.ullAvailPageFile / (1024 * 1024))

    def _run(self):
        previous = self._snapshot_times()
        while not self._stop.is_set():
            self._stop.wait(self.interval_s)
            current = self._snapshot_times()
            if previous and current:
                d_idle = current[0] - previous[0]
                d_total = (current[1] - previous[1]) + (current[2] - previous[2])
                if d_total > 0:
                    self.cpu_pct.append(100.0 * (1.0 - d_idle / d_total))
            previous = current
            memory = self._snapshot_memory()
            if memory:
                self.avail_phys_mib.append(memory[0])
                self.avail_pagefile_mib.append(memory[1])

    def start(self):
        if platform.system() != "Windows":
            self.reason = (f"CPU and memory sampling here is a Windows kernel32 "
                           f"call; on {platform.system()} it is unavailable")
            return self
        self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return self

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=self.interval_s * 4)
        return self


class StreamSampler:
    """
    A child process that prints one number per line per interval, read on a
    thread until stopped. Two counters arrive this way because neither has a
    cheap in-process equivalent on Windows.
    """

    def __init__(self, argv, parse_line, label: str):
        self.argv = list(argv)
        self.parse_line = parse_line
        self.label = label
        self.samples = []
        self.reason = None
        self._proc = None
        self._thread = None

    def _run(self):
        for line in self._proc.stdout:
            parsed = self.parse_line(line)
            if parsed is not None:
                self.samples.append(parsed)

    def start(self):
        try:
            self._proc = subprocess.Popen(
                self.argv, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                text=True, encoding="utf-8", errors="replace", bufsize=1)
        except Exception as exc:
            self.reason = f"{self.label} could not start: {type(exc).__name__}: {exc}"
            return self
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return self

    def stop(self):
        if self._proc is None:
            return self
        try:
            self._proc.terminate()
            self._proc.wait(timeout=10)
        except Exception:
            try:
                self._proc.kill()
            except Exception:
                pass
        if self._thread:
            self._thread.join(timeout=5)
        if not self.samples and self.reason is None:
            self.reason = f"{self.label} produced no sample in the timed window"
        return self


class DmonParser:
    """
    `nvidia-smi dmon` rows, mapped by the HEADER it prints rather than by fixed
    positions.

    The column set depends on which -s selectors were asked for: `-s t` prints
    three columns and `-s ut` prints nine. A positional parser written for the
    first silently reads `sm` as `rxpci` the moment the selector string changes,
    and reports a busy GPU as PCIe traffic. So the first header line is used to
    learn the names, and a row whose field count disagrees with them is dropped
    rather than mapped.

    A '-' field means the counter is unsupported on this part. It is dropped and
    never read as a zero, because zero is a measurement and unsupported is not.
    """

    def __init__(self):
        self.columns = None

    def __call__(self, line: str):
        text = line.strip()
        if text.startswith("#"):
            names = text.lstrip("#").split()
            # Two header lines: names first ("gpu sm mem ... rxpci txpci"), then
            # units ("Idx % % ... MB/s MB/s"). Only the first teaches anything.
            if names and names[0].lower() == "gpu":
                self.columns = names[1:]
            return None
        if not self.columns:
            return None
        fields = text.split()
        if len(fields) != len(self.columns) + 1:
            return None
        row = {}
        for name, raw in zip(self.columns, fields[1:]):
            try:
                row[name] = float(raw)
            except ValueError:
                continue
        return row or None


def _parse_pagein_line(line: str):
    """One integer page-in-per-second reading, ignoring anything else the
    child prints."""
    text = line.strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def gpu_sampler(cfg: dict, origin: str, probe, which=shutil.which):
    """GPU-side instrumentation in ONE child process: SM and memory-controller
    utilization alongside PCIe receive and transmit. One `dmon` rather than two
    because a second sampler would be a second thing to keep alive, and both
    numbers are needed to tell a card that is idle from a bus that is idle."""
    binary = require(probe, cfg, "gpu.nvidia_smi", origin)
    interval = require(probe, cfg, "gpu.pcie_sample_interval_s", origin)
    select = require(probe, cfg, "gpu.dmon_select", origin)
    resolved = which(binary)
    sampler = StreamSampler([], DmonParser(), "nvidia-smi dmon")
    if not resolved:
        sampler.reason = (f"'{binary}' is not on PATH, so GPU utilization and the "
                          f"PCIe traffic that actually crossed the bus cannot be "
                          f"measured")
        return sampler
    # Invoked by the resolved path: a bare name fails on Windows, where the
    # launcher carries an extension.
    sampler.argv = [resolved, "dmon", "-s", str(select), "-d", str(int(interval))]
    return sampler


# The old name, kept so nothing that already calls it breaks.
pcie_sampler = gpu_sampler


def pagein_sampler(cfg: dict, origin: str, probe, which=shutil.which):
    enabled = require(probe, cfg, "paging.enabled", origin)
    interval = require(probe, cfg, "paging.sample_interval_s", origin)
    sampler = StreamSampler([], _parse_pagein_line, "page-in counter")
    if not enabled:
        sampler.reason = "page-in sampling is switched off in the configuration"
        return sampler
    if platform.system() != "Windows":
        sampler.reason = (f"the page-in counter read here is a Windows WMI class; "
                          f"on {platform.system()} it is unavailable")
        return sampler
    resolved = which("powershell")
    if not resolved:
        sampler.reason = "powershell is not on PATH, so hard page-ins are unmeasured"
        return sampler
    # The WMI PROPERTY name is locale-independent, where a typeperf counter path
    # is not: '\Memory\Pages Input/sec' does not resolve on a French Windows.
    script = ("while($true){(Get-CimInstance Win32_PerfFormattedData_PerfOS_Memory)"
              ".PagesInputPerSec; Start-Sleep -Seconds %d}" % int(interval))
    sampler.argv = [resolved, "-NoProfile", "-NonInteractive", "-Command", script]
    return sampler


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def require(probe, cfg: dict, dotted: str, origin: str):
    """The probe's own no-silent-default reader, so a missing key is named once
    in one voice (R3)."""
    return probe.require(cfg, dotted, origin)


def mean(values):
    return sum(values) / len(values) if values else None


def peak(values):
    return max(values) if values else None


def rounded(value, places: int):
    return None if value is None else round(float(value), places)


def mean_by(rows, key_field: str, value_field: str = "decode_tps") -> list:
    """
    --------------------------------------------------------------------------
    Purpose:
        Group rows by the setting they measured and average each group.

    Details:
        Repeats exist because one run of a rung does not separate it from its
        neighbour. Measured 2026-09-05 at num_ctx 65536, the SAME offload
        setting produced 3.48, 3.00 and 3.02 tok/s - a 16 percent spread, wider
        than the gap between settings.

        Comparing the best single run of each setting is therefore worse than
        useless: it hands the win to whichever setting happened to be measured
        on the quietest moment of the machine, which is the noisiest one rather
        than the fastest. That is what this replaced.

    Outputs:
        groups (list[dict]): one per setting, sorted by it, each carrying the
        mean, how many runs it averages, the raw values, and the spread across
        them so a reader can see whether the mean means anything.
    --------------------------------------------------------------------------
    """
    groups = {}
    for row in rows:
        key, value = row.get(key_field), row.get(value_field)
        if key is None or value is None:
            continue
        groups.setdefault(int(key), []).append(float(value))
    out = []
    for key in sorted(groups):
        values = groups[key]
        low, high = min(values), max(values)
        # None, not 0.0, for a setting run once: zero spread would claim the
        # measurement was repeated and found stable, which is the opposite of
        # what one run establishes.
        spread = None
        if len(values) > 1 and low > 0:
            spread = 100.0 * (high - low) / low
        out.append({"key": key, "mean": sum(values) / len(values),
                    "n": len(values), "values": values, "spread_pct": spread})
    return out


# ---------------------------------------------------------------------------
# Mode: bandwidth
# ---------------------------------------------------------------------------

def _bandwidth_worker(buffer_mib: int, seconds: float, barrier, results):
    """
    One worker: allocate a PRIVATE buffer far larger than last-level cache,
    touch it so the pages are resident, wait on the barrier so every worker is
    running at once, then read it end to end until the deadline.

    numpy's sum is single-threaded and memory bound, which is what makes one
    worker one thread's worth of demand. The buffer is private per worker
    because a shared one would be answered from another worker's cache and the
    curve would flatten for the wrong reason.
    """
    try:
        import numpy
    except Exception as exc:                     # reported, never raised into the parent
        results.put(("error", f"numpy is required for the bandwidth mode: {exc}"))
        return
    elements = int(buffer_mib) * 1024 * 1024 // 8
    array = numpy.ones(elements, dtype=numpy.float64)
    array.sum()                                  # fault the pages in before timing
    try:
        barrier.wait(timeout=120)
    except Exception as exc:
        results.put(("error", f"workers failed to start together: {exc}"))
        return
    start = time.perf_counter()
    passes = 0
    while time.perf_counter() - start < seconds:
        array.sum()
        passes += 1
    elapsed = time.perf_counter() - start
    results.put(("ok", passes * elements * 8, elapsed))


def spawn_readers(workers: int, buffer_mib: int, seconds: float):
    """
    Run `workers` reader processes concurrently and collect what each measured.

    Separated from the aggregation below so the arithmetic can be tested
    without starting a process. It has to be separated rather than merely
    convenient: multiprocessing's spawn start method re-imports the worker's
    module BY NAME in the child, and this file's name carries hyphens, so a
    suite that loaded it by path cannot drive this function at all. The real
    path is exercised by running the tool; the aggregation is exercised here.
    """
    barrier = mp.Barrier(workers)
    results = mp.Queue()
    processes = [mp.Process(target=_bandwidth_worker,
                            args=(buffer_mib, seconds, barrier, results))
                 for _ in range(workers)]
    for process in processes:
        process.start()
    collected, errors = [], []
    for _ in processes:
        try:
            item = results.get(timeout=seconds + 180)
        except queue.Empty:
            errors.append("a worker returned no result before its deadline")
            continue
        if item[0] == "ok":
            collected.append((item[1], item[2]))
        else:
            errors.append(item[1])
    for process in processes:
        process.join(timeout=30)
    return collected, errors


def bandwidth_point(workers: int, buffer_mib: int, seconds: float,
                    spawn=spawn_readers) -> dict:
    """Aggregate read bandwidth for one worker count."""
    collected, errors = spawn(workers, buffer_mib, seconds)
    row = {"workers": workers, "buffer_mib_per_worker": buffer_mib,
           "gb_per_s": None, "per_worker_gb_per_s": None,
           "status": "ok", "source": "numpy read of a private per-worker buffer"}
    if errors or not collected:
        row["status"] = "; ".join(errors) or "no worker reported"
        return row
    total_bytes = sum(item[0] for item in collected)
    window = mean([item[1] for item in collected])
    row["gb_per_s"] = total_bytes / window / 1e9
    row["per_worker_gb_per_s"] = row["gb_per_s"] / workers
    return row


def run_bandwidth(cfg: dict, origin: str, probe, worker_counts=None) -> list:
    buffer_mib = require(probe, cfg, "bandwidth.buffer_mib_per_worker", origin)
    seconds = require(probe, cfg, "bandwidth.seconds_per_point", origin)
    counts = worker_counts or require(probe, cfg, "bandwidth.workers", origin)
    rows = []
    for workers in counts:
        row = bandwidth_point(int(workers), int(buffer_mib), float(seconds))
        rows.append(row)
        print(render_bandwidth_row(row, cfg, origin, probe), flush=True)
    return rows


# ---------------------------------------------------------------------------
# Mode: sweep
# ---------------------------------------------------------------------------

def new_sweep_row(model: str, num_ctx: int, num_thread: int,
                  num_gpu: int = None) -> dict:
    """One rung, every measured field absent until something measures it."""
    return {
        "model": model, "num_ctx": num_ctx, "num_thread_requested": num_thread,
        "num_thread_granted": None, "thread_effect": None,
        "num_gpu_requested": num_gpu, "gpu_effect": None,
        "status": "ok",
        "decode_tps": None, "prefill_tps": None,
        "layers_offloaded": None, "layers_total": None,
        "n_ctx_granted": None, "kv_cache_mib": None,
        "compute_buffer_device_mib": None, "compute_buffer_host_mib": None,
        "cpu_pct_mean": None, "cpu_pct_peak": None,
        "gpu_sm_pct_mean": None, "gpu_sm_pct_peak": None,
        "gpu_mem_pct_mean": None, "gpu_mem_pct_peak": None,
        "free_ram_mib_min": None, "pagefile_avail_mib_min": None,
        "page_in_per_s_mean": None, "page_in_per_s_peak": None, "paged": None,
        "pcie_rx_mb_s_mean": None, "pcie_rx_mb_s_peak": None,
        "pcie_tx_mb_s_mean": None, "pcie_tx_mb_s_peak": None,
        "vram_used_mib": None, "vram_total_mib": None,
        "load_seconds": None, "unavailable": {}, "sources": {},
    }


def default_samplers(cfg: dict, origin: str, probe, deps):
    """The three real samplers, built together so the one place that decides
    what instrumentation a rung carries is also the seam a test replaces."""
    interval = require(probe, cfg, "paging.sample_interval_s", origin)
    return (CpuRamSampler(interval),
            pcie_sampler(cfg, origin, probe, which=deps.which),
            pagein_sampler(cfg, origin, probe, which=deps.which))


def sweep_one(cfg: dict, origin: str, probe, deps, num_thread: int,
              model: str, num_ctx: int, samplers=default_samplers,
              num_gpu: int = None, reject_clamped: bool = True) -> dict:
    """
    --------------------------------------------------------------------------
    Purpose:
        One thread rung end to end: evict and prove it, refuse below the
        free-RAM floor, load with num_thread requested, READ BACK from the
        server log what the daemon actually granted, then run one instrumented
        timed decode.

    Inputs:
        cfg (dict), origin (str): configuration and its path.
        probe (module), deps: the borrowed parsers and the injected effects.
        num_thread (int), model (str), num_ctx (int): the rung.

    Outputs:
        row (dict): the measured rung. "status" says what went wrong wherever a
        field came back None, and "thread_effect" says whether the request took
        effect at all - a rung whose granted thread count did not move measures
        nothing, and reporting its throughput as a thread datum would be a
        wrong answer that reads exactly like a right one (R9).
    --------------------------------------------------------------------------
    """
    places = require(probe, cfg, "report.float_places", origin)
    keep_alive = require(probe, cfg, "ollama.keep_alive", origin)
    think = require(probe, cfg, "ollama.think", origin)
    load_timeout = float(require(probe, cfg, "ollama.load_timeout_s", origin))
    decode_timeout = float(require(probe, cfg, "ollama.decode_timeout_s", origin))
    read_delay = float(require(probe, cfg, "server_log.read_delay_s", origin))
    min_free = float(require(probe, cfg, "safety.min_free_ram_mib", origin))
    reread = float(require(probe, cfg, "safety.free_ram_reread_delay_s", origin))
    patterns = require(probe, cfg, "log_patterns", origin)
    selection = require(probe, cfg, "log_selection", origin)

    row = new_sweep_row(model, num_ctx, num_thread, num_gpu)

    probe.evict_all(deps, cfg, origin)

    proceed, free, free_source = probe.free_ram_above_floor(deps, min_free, reread)
    if free is not None:
        row["free_ram_mib_min"] = rounded(free, 0)
        row["sources"]["free_ram_mib_min"] = free_source
    if not proceed:
        row["status"] = (f"skipped: free RAM {free:.0f} MiB is below the "
                         f"{min_free:.0f} MiB floor after a re-read")
        return row

    options = {"num_ctx": int(num_ctx), "num_thread": int(num_thread)}
    if num_gpu is not None:
        options["num_gpu"] = int(num_gpu)
    offset = deps.log.offset()
    load_started = deps.clock()
    warmup = {
        "model": model, "stream": False, "think": think, "keep_alive": keep_alive,
        "prompt": require(probe, cfg, "measurement.warmup_prompt", origin),
        "options": dict(options, num_predict=int(
            require(probe, cfg, "measurement.warmup_num_predict", origin))),
    }
    try:
        deps.daemon.generate(warmup, load_timeout)
    except Exception as exc:
        row["status"] = f"load failed: {type(exc).__name__}: {str(exc)[-200:]}"
        return row
    row["load_seconds"] = rounded(deps.clock() - load_started, places)

    if read_delay > 0:
        deps.sleeper(read_delay)
    tail = deps.log.tail(offset)

    split = probe.parse_offload(tail, patterns["offload"])
    if split is not None:
        row["layers_offloaded"], row["layers_total"] = split
        row["sources"]["layers_offloaded"] = SRC_LOG
    row["n_ctx_granted"] = probe.parse_int(tail, patterns["n_ctx"])
    row["kv_cache_mib"] = probe.parse_mib(tail, patterns["kv_cache_mib"],
                                          selection["kv_cache_mib"])
    pools = probe.parse_compute_buffers(tail, patterns["compute_buffer_pool"])
    row["compute_buffer_device_mib"], row["compute_buffer_host_mib"] = \
        probe.split_compute_buffers(pools, selection["host_pool_patterns"])
    row["num_thread_granted"] = probe.parse_int(tail, patterns["n_threads"])
    for field in ("n_ctx_granted", "kv_cache_mib", "compute_buffer_device_mib",
                  "compute_buffer_host_mib", "num_thread_granted"):
        if row[field] is not None:
            row["sources"][field] = SRC_LOG

    # Trap carried over from the GPU probe: a num_ctx the daemon cannot place is
    # CLAMPED and reported as success, and two rungs on different windows are
    # not comparable.
    if row["n_ctx_granted"] is not None and row["n_ctx_granted"] != num_ctx:
        if reject_clamped:
            row["status"] = (f"rejected: requested num_ctx {num_ctx} but the daemon "
                             f"granted {row['n_ctx_granted']}; the rung would "
                             f"describe a window that was never in force")
            return row
        # In a CONTEXT sweep the clamp is the answer rather than a spoiled rung:
        # the question being asked is which windows this card can actually
        # grant, so the run continues and the row says what was granted.
        row["status"] = (f"clamped: asked {num_ctx}, granted "
                         f"{row['n_ctx_granted']}")

    # The verification this script exists for. Nothing in the API says whether
    # num_thread was honoured, and an ignored request produces a full table of
    # identical throughputs that reads as "threads do not matter".
    granted = row["num_thread_granted"]
    if granted is None:
        row["thread_effect"] = "unknown: the log carried no n_threads line"
    elif granted == num_thread:
        row["thread_effect"] = "honoured"
    else:
        row["thread_effect"] = f"IGNORED: asked {num_thread}, ran {granted}"

    # The same verification for the layer override. Ollama accepts num_gpu and
    # then places what it can, so a request for 12 layers that yielded 5 is the
    # allocator declining rather than a measurement of 12 layers. Reported from
    # the log's own offload line, which is the only honest source (R9).
    if num_gpu is not None:
        placed = row["layers_offloaded"]
        if placed is None:
            row["gpu_effect"] = "unknown: the log carried no offload line"
        elif placed == num_gpu:
            row["gpu_effect"] = "honoured"
        else:
            row["gpu_effect"] = f"DECLINED: asked {num_gpu}, placed {placed}"

    cpu, pcie, pagein = samplers(cfg, origin, probe, deps)
    cpu.start()
    pcie.start()
    pagein.start()

    decode = {
        "model": model, "stream": False, "think": think, "keep_alive": keep_alive,
        "prompt": require(probe, cfg, "measurement.decode_prompt", origin),
        "options": dict(options, num_predict=int(
            require(probe, cfg, "measurement.decode_num_predict", origin))),
    }
    try:
        response = deps.daemon.generate(decode, decode_timeout)
    except Exception as exc:
        row["status"] = f"decode failed: {type(exc).__name__}: {str(exc)[-200:]}"
        response = None
    finally:
        cpu.stop()
        pcie.stop()
        pagein.stop()

    if response is not None:
        row["decode_tps"] = rounded(probe.decode_tps(response), places)
        row["sources"]["decode_tps"] = SRC_API
        prompt_count = response.get("prompt_eval_count")
        prompt_ns = response.get("prompt_eval_duration")
        if prompt_count and prompt_ns:
            row["prefill_tps"] = rounded(prompt_count / (prompt_ns / 1e9), places)
            row["sources"]["prefill_tps"] = SRC_API

    row["cpu_pct_mean"] = rounded(mean(cpu.cpu_pct), places)
    row["cpu_pct_peak"] = rounded(peak(cpu.cpu_pct), places)
    if cpu.avail_phys_mib:
        row["free_ram_mib_min"] = rounded(min(cpu.avail_phys_mib), 0)
        row["sources"]["free_ram_mib_min"] = "kernel32 GlobalMemoryStatusEx"
    if cpu.avail_pagefile_mib:
        row["pagefile_avail_mib_min"] = rounded(min(cpu.avail_pagefile_mib), 0)
    if cpu.reason:
        row["unavailable"]["cpu_pct"] = cpu.reason

    if pcie.samples:
        def series(column):
            return [s[column] for s in pcie.samples
                    if isinstance(s, dict) and column in s]

        for field, column in (("pcie_rx_mb_s", "rxpci"), ("pcie_tx_mb_s", "txpci"),
                              ("gpu_sm_pct", "sm"), ("gpu_mem_pct", "mem")):
            values = series(column)
            if not values:
                continue
            row[f"{field}_mean"] = rounded(mean(values), places)
            row[f"{field}_peak"] = rounded(peak(values), places)
            row["sources"][f"{field}_mean"] = SRC_SMI
    if pcie.reason:
        row["unavailable"]["gpu"] = pcie.reason

    if pagein.samples:
        row["page_in_per_s_mean"] = rounded(mean(pagein.samples), places)
        row["page_in_per_s_peak"] = rounded(peak(pagein.samples), places)
        row["paged"] = bool(peak(pagein.samples))
        row["sources"]["page_in_per_s_mean"] = "Win32_PerfFormattedData_PerfOS_Memory"
    if pagein.reason:
        row["unavailable"]["page_in"] = pagein.reason

    try:
        used, total = probe.nvidia_smi_memory(cfg, origin, runner=deps.runner,
                                              which=deps.which)
        row["vram_used_mib"], row["vram_total_mib"] = used, total
        row["sources"]["vram_used_mib"] = SRC_SMI
    except Exception as exc:
        row["unavailable"]["vram"] = f"{type(exc).__name__}: {exc}"

    return row


def run_sweep(cfg: dict, origin: str, probe, deps, threads=None,
              model=None, num_ctx=None, samplers=default_samplers) -> list:
    model = model or require(probe, cfg, "sweep.model", origin)
    num_ctx = num_ctx or require(probe, cfg, "sweep.num_ctx", origin)
    rungs = threads or require(probe, cfg, "sweep.threads", origin)
    repeats = int(require(probe, cfg, "sweep.repeats", origin))

    installed = probe.installed_names(
        deps.daemon.tags(float(require(probe, cfg, "ollama.connect_timeout_s", origin))))
    if model not in installed:
        raise Refusal(f"the tag '{model}' is not installed on this daemon. "
                      f"Installed: {', '.join(sorted(installed)) or 'nothing'}. "
                      f"Set sweep.model in {origin} to a tag you actually have.")

    rows = []
    print(render_sweep_header(), flush=True)
    for num_thread in rungs:
        for _ in range(repeats):
            row = sweep_one(cfg, origin, probe, deps, int(num_thread),
                            model, int(num_ctx), samplers=samplers)
            rows.append(row)
            print(render_sweep_row(row), flush=True)
    return rows


def interleave(rungs, repeats: int) -> list:
    """
    The rung list repeated end to end, never rung-by-rung.

    Measured 2026-09-05 over nine offload rungs: every setting declined
    monotonically across the run - 3.48, 3.00, 3.02 for one of them - as the
    machine warmed or accumulated memory pressure. Blocked repeats (2,2,2,3,3,3)
    would have charged that whole drift to the settings measured last.
    Interleaved (2,3,4,2,3,4,...) it falls on all of them equally, so the
    ranking survives even when the absolute numbers do not.
    """
    return [rung for _ in range(max(1, int(repeats))) for rung in rungs]


def run_gpu_sweep(cfg: dict, origin: str, probe, deps, gpu_layers=None,
                  num_thread=None, model=None, num_ctx=None,
                  samplers=default_samplers, repeats: int = 1) -> list:
    """
    --------------------------------------------------------------------------
    Purpose:
        Sweep the number of layers forced onto the card, holding threads and
        context constant. The allocator picks conservatively - measured
        2026-09-05 it placed 5 of 66 layers and refused a sixth at 2607 MiB
        while reporting 2057 MiB still free, leaving about 2.5 GB of the card
        idle and 14 GB of weights in system RAM. This asks whether that spare
        VRAM can be used, and it is an experiment rather than a fix because
        the allocator may be right.

    Inputs:
        cfg (dict), origin (str), probe (module), deps: as elsewhere.
        gpu_layers (list[int] | None): the rungs, lowest first so the
            allocator's own choice acts as the control.
        num_thread (int | None): held constant across every rung.

    Outputs:
        rows (list[dict]): one per rung. A request the allocator declines is
        labelled DECLINED rather than recorded as a measurement of the layer
        count asked for, and consecutive load failures stop the sweep instead
        of hammering a card that has just refused twice.
    --------------------------------------------------------------------------
    """
    model = model or require(probe, cfg, "sweep.model", origin)
    num_ctx = num_ctx or require(probe, cfg, "sweep.num_ctx", origin)
    layers = gpu_layers or require(probe, cfg, "sweep.gpu_layers", origin)
    threads = num_thread or require(probe, cfg, "sweep.gpu_sweep_num_thread", origin)
    stop_after = int(require(probe, cfg, "sweep.gpu_stop_after_failures", origin))

    installed = probe.installed_names(
        deps.daemon.tags(float(require(probe, cfg, "ollama.connect_timeout_s", origin))))
    if model not in installed:
        raise Refusal(f"the tag '{model}' is not installed on this daemon. "
                      f"Installed: {', '.join(sorted(installed)) or 'nothing'}.")

    rows = []
    consecutive = 0
    layers = interleave(layers, repeats)
    print(render_sweep_header(), flush=True)
    for count in layers:
        row = sweep_one(cfg, origin, probe, deps, int(threads), model,
                        int(num_ctx), samplers=samplers, num_gpu=int(count))
        rows.append(row)
        print(render_sweep_row(row), flush=True)
        if row["status"].startswith("load failed"):
            consecutive += 1
            if consecutive >= stop_after:
                print(f"  stopping the layer sweep: {consecutive} consecutive load "
                      f"failures, which is the card refusing rather than a rung "
                      f"worth retrying", flush=True)
                break
        else:
            consecutive = 0
    return rows


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def render_bandwidth_row(row: dict, cfg: dict, origin: str, probe) -> str:
    places = require(probe, cfg, "report.float_places", origin)
    if row["gb_per_s"] is None:
        return f"  workers {row['workers']:>3}   {row['status']}"
    return (f"  workers {row['workers']:>3}   aggregate "
            f"{row['gb_per_s']:>7.{places}f} GB/s   per worker "
            f"{row['per_worker_gb_per_s']:>6.{places}f} GB/s")


def render_bandwidth_verdict(rows: list) -> str:
    """Where the curve stops rising, which is the ceiling any thread count runs
    into. Reported as the knee rather than the maximum, because the maximum is
    often one noisy point above a plateau that started earlier."""
    usable = [r for r in rows if r["gb_per_s"] is not None]
    if len(usable) < 2:
        return "  not enough points to locate a saturation knee"
    best = max(usable, key=lambda r: r["gb_per_s"])
    threshold = 0.95 * best["gb_per_s"]
    knee = min((r for r in usable if r["gb_per_s"] >= threshold),
               key=lambda r: r["workers"])
    return (f"  peak {best['gb_per_s']:.2f} GB/s at {best['workers']} workers; "
            f"within 5 percent of peak already at {knee['workers']} workers.\n"
            f"  Past {knee['workers']} concurrent readers this machine returns no "
            f"more bandwidth, so a model bound by memory traffic gains nothing "
            f"from more threads than that.")


SWEEP_COLUMNS = ("thr_ask", "thr_got", "gpu_ask", "dec_tps", "pre_tps", "cpu%",
                 "pk%", "sm%", "vramMiB", "gpu_lyr", "freeRAM", "pgin/s",
                 "rx_MB/s", "tx_MB/s", "load_s")


def render_sweep_header() -> str:
    head = ("  " + "".join(f"{name:>9}" for name in SWEEP_COLUMNS) + "   status")
    return head + "\n  " + "-" * (9 * len(SWEEP_COLUMNS) + 10)


def _cell(value, spec: str = "") -> str:
    if value is None:
        return f"{'-':>9}"
    return f"{format(value, spec):>9}" if spec else f"{value:>9}"


def render_sweep_row(row: dict) -> str:
    layers = "-"
    if row["layers_offloaded"] is not None and row["layers_total"]:
        layers = f"{row['layers_offloaded']}/{row['layers_total']}"
    # Both effects are shown when both are abnormal. Showing only one hid a
    # declined layer override behind an ignored thread request, which the test
    # suite caught: the row then reads as though the override had been granted.
    notes = []
    if row["status"] != "ok":
        notes.append(row["status"])
    for key in ("thread_effect", "gpu_effect"):
        effect = row.get(key)
        if effect and effect != "honoured":
            notes.append(effect)
    note = "; ".join(notes) if notes else "ok"
    cells = [
        _cell(row["num_thread_requested"]),
        _cell(row["num_thread_granted"]),
        _cell(row.get("num_gpu_requested")),
        _cell(row["decode_tps"], ".2f"),
        _cell(row["prefill_tps"], ".1f"),
        _cell(row["cpu_pct_mean"], ".1f"),
        _cell(row["cpu_pct_peak"], ".1f"),
        _cell(row.get("gpu_sm_pct_mean"), ".1f"),
        # VRAM actually occupied. It belongs beside sm%, because the pair is the
        # diagnosis: a card at 56 percent occupancy and 9 percent SM is one whose
        # allocator declined to use it, which no other column says outright.
        _cell(row.get("vram_used_mib"), ".0f"),
        f"{layers:>9}",
        _cell(row["free_ram_mib_min"], ".0f"),
        _cell(row["page_in_per_s_mean"], ".0f"),
        _cell(row["pcie_rx_mb_s_mean"], ".1f"),
        _cell(row["pcie_tx_mb_s_mean"], ".1f"),
        _cell(row["load_seconds"], ".0f"),
    ]
    return "  " + "".join(cells) + "   " + note


def render_sweep_verdict(rows: list) -> str:
    usable = [r for r in rows if r["decode_tps"] is not None]
    if not usable:
        return "  no rung produced a decode figure, so nothing can be concluded"
    honoured = [r for r in usable if r["thread_effect"] == "honoured"]
    lines = []
    if not honoured:
        lines.append("  NOT ONE rung's thread request was honoured by the daemon, so "
                     "every throughput above describes the same run and none of it "
                     "is a thread measurement.")
        return "\n".join(lines)
    # Averaged per thread count, for the reason given on mean_by: with repeats,
    # comparing best single runs picks the luckiest measurement rather than the
    # fastest setting.
    groups = mean_by(honoured, "num_thread_granted")
    best = max(groups, key=lambda g: g["mean"])
    threshold = 0.97 * best["mean"]
    knee = min((g for g in groups if g["mean"] >= threshold),
               key=lambda g: g["key"])
    runs = "" if best["n"] == 1 else f" (mean of {best['n']} runs)"
    lines.append(f"  fastest {best['mean']:.2f} tok/s at {best['key']} "
                 f"threads{runs}; within 3 percent of that already at "
                 f"{knee['key']} threads.")
    paged = [r for r in honoured if r.get("paged")]
    if paged:
        lines.append(f"  {len(paged)} of {len(honoured)} rungs recorded hard page-ins "
                     f"during the timed decode, so those figures measure the disk as "
                     f"much as the CPU and are not clean thread data.")
    rx = [r["pcie_rx_mb_s_mean"] for r in honoured if r["pcie_rx_mb_s_mean"] is not None]
    if rx:
        lines.append(f"  PCIe receive averaged at most {max(rx):.1f} MB/s during decode, "
                     f"against a gen4 x8 link. Weight traffic does not cross the bus "
                     f"per token; only the layer-boundary activations do.")
    sm = [r["gpu_sm_pct_mean"] for r in honoured
          if r.get("gpu_sm_pct_mean") is not None]
    if sm:
        lines.append(f"  GPU SM utilization averaged at most {max(sm):.1f} percent. "
                     f"With most layers on the CPU that is the expected reading and "
                     f"not a broken card: the GPU finishes its few layers and then "
                     f"waits for the CPU to finish the rest of the token.")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def run_context_sweep(cfg: dict, origin: str, probe, deps, contexts=None,
                      num_thread=None, num_gpu=None, model=None,
                      samplers=default_samplers, repeats: int = 1) -> list:
    """
    --------------------------------------------------------------------------
    Purpose:
        Sweep the context window, which is the axis that decides everything
        else. Measured 2026-09-05: the window buys a compute buffer charged to
        VRAM, 3525 MiB at 262144 against 191.56 MiB at 8192 on the same card,
        and that buffer DISPLACES weights - which is why a 262144 window placed
        zero layers on the GPU. The KV cache, about 34 KiB per token, is the
        second cost and not the first.

    Inputs:
        contexts (list[int] | None): the window rungs, smallest first.
        num_gpu (int | None): None leaves placement to the allocator, which is
            the point of this sweep - it shows how many layers each window
            leaves room for.

    Outputs:
        rows (list[dict]): one per rung. A window the daemon CLAMPS is recorded
        with what it granted rather than rejected, because in this sweep the
        clamp is the finding.
    --------------------------------------------------------------------------
    """
    model = model or require(probe, cfg, "sweep.model", origin)
    rungs = contexts or require(probe, cfg, "sweep.contexts", origin)
    threads = num_thread or require(probe, cfg, "sweep.gpu_sweep_num_thread", origin)

    rows = []
    rungs = interleave(rungs, repeats)
    print(render_sweep_header(), flush=True)
    for window in rungs:
        row = sweep_one(cfg, origin, probe, deps, int(threads), model,
                        int(window), samplers=samplers, num_gpu=num_gpu,
                        reject_clamped=False)
        rows.append(row)
        print(render_sweep_row(row), flush=True)
    return rows


def render_context_verdict(rows: list) -> str:
    """
    What each window costs in VRAM and in layers. The recommendation this feeds
    is not "the biggest window" but "the smallest window that holds the work",
    because every token of window is paid for in displaced weights.
    """
    usable = [r for r in rows if r["decode_tps"] is not None]
    if not usable:
        return "  no window produced a decode figure, so nothing can be concluded"
    lines = []
    clamped = [r for r in rows if r["status"].startswith("clamped")]
    if clamped:
        lines.append(f"  {len(clamped)} window(s) were CLAMPED by the daemon: it "
                     f"granted less than was asked and reported success, so the "
                     f"largest windows below describe what was actually in force.")
    for row in usable:
        kv = row["kv_cache_mib"]
        compute = row["compute_buffer_device_mib"]
        layers = row["layers_offloaded"]
        total = row["layers_total"]
        lines.append(
            f"  n_ctx {row['n_ctx_granted'] or row['num_ctx']:>7}: "
            f"{row['decode_tps']:>5.2f} tok/s, "
            f"{layers if layers is not None else '?'}/{total or '?'} layers, "
            f"KV {kv if kv is not None else '?'} MiB, "
            f"device compute buffer {compute if compute is not None else '?'} MiB")
    best = max(usable, key=lambda r: r["decode_tps"])
    lines.append(f"  fastest at n_ctx "
                 f"{best['n_ctx_granted'] or best['num_ctx']}, "
                 f"{best['decode_tps']:.2f} tok/s with "
                 f"{best['layers_offloaded']} layers placed.")
    lines.append("  Choose the SMALLEST window that holds the assembled prompt, "
                 "not the fastest one here: a window too small to hold the work "
                 "does not run at all, and one larger than the work needs pays "
                 "for itself in layers it pushed off the card.")
    return "\n".join(lines)


def render_gpu_verdict(rows: list) -> str:
    """
    Whether forcing layers onto the card helped, judged on placement actually
    achieved and on the page-in rate, which is the mechanism. A row whose
    override was declined is excluded from the comparison rather than counted
    as its requested layer count.
    """
    usable = [r for r in rows if r["decode_tps"] is not None]
    if not usable:
        return "  no rung produced a decode figure, so nothing can be concluded"
    lines = []
    declined = [r for r in usable
                if (r.get("gpu_effect") or "").startswith("DECLINED")]
    if declined:
        lines.append(f"  {len(declined)} of {len(usable)} overrides were DECLINED: "
                     f"the allocator placed fewer layers than asked, so those rows "
                     f"measure the placement it chose and not the one requested.")
    failed = [r for r in rows if r["status"].startswith("load failed")]
    if failed:
        lines.append(f"  {len(failed)} rung(s) failed to load outright, which is the "
                     f"card refusing the override rather than a slow result.")

    # Averaged per setting, never compared as best-single-run against
    # best-single-run: with repeats that hands the win to whichever setting was
    # measured on the quietest moment of the machine.
    groups = mean_by(usable, "layers_offloaded")
    baseline = groups[0]
    base_layers = baseline["key"]
    # Compared against the settings that actually placed MORE layers, not
    # against the best group overall - that includes the baseline, so the
    # comparison could only ever report a gain.
    forced = [g for g in groups if g["key"] > base_layers]
    if not forced:
        lines.append(f"  no override placed more than the "
                     f"{base_layers} layers the allocator chose for itself, so "
                     f"there is nothing to compare: on this card, at this "
                     f"context, the spare VRAM is not reachable this way.")
    else:
        best = max(forced, key=lambda g: g["mean"])
        runs = "" if best["n"] == 1 else f", mean of {best['n']} runs"
        base_runs = "" if baseline["n"] == 1 else f", mean of {baseline['n']}"
        lines.append(f"  {best['mean']:.2f} tok/s with {best['key']} layers "
                     f"placed{runs}, against {baseline['mean']:.2f} tok/s at "
                     f"{base_layers} layers{base_runs}, the allocator's own choice.")
        if baseline["mean"]:
            change = 100.0 * (best["mean"] - baseline["mean"]) / baseline["mean"]
            verb = "gains" if change >= 0 else "LOSES"
            lines.append(f"  forcing layers {verb} {abs(change):.1f} percent.")
        worst_spread = max((g["spread_pct"] for g in groups
                            if g["n"] > 1 and g["spread_pct"] is not None),
                           default=None)
        if worst_spread is None:
            lines.append("  Each setting was run ONCE, so none of the gaps above "
                         "is separated from run-to-run noise. Repeat the rungs "
                         "before acting on a small difference.")
        else:
            lines.append(f"  Run-to-run spread within one setting reached "
                         f"{worst_spread:.0f} percent, so treat any gap smaller "
                         f"than that as unresolved.")

    pairs = [(r["layers_offloaded"], r["page_in_per_s_mean"]) for r in usable
             if r["page_in_per_s_mean"] is not None]
    if len(pairs) >= 2:
        lines.append("  page-ins per second by layers placed: "
                     + ", ".join(f"{layers}->{rate:.0f}" for layers, rate in pairs)
                     + ". That rate is the mechanism: moving weights onto the card "
                       "is only worth it if it falls.")
    sm = [(r["layers_offloaded"], r["gpu_sm_pct_mean"]) for r in usable
          if r.get("gpu_sm_pct_mean") is not None]
    if sm:
        lines.append("  GPU SM utilization by layers placed: "
                     + ", ".join(f"{layers}->{pct:.1f}%" for layers, pct in sm)
                     + ". A low figure is correct rather than broken while most "
                       "layers run on the CPU: the card waits its turn each token.")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Measure what actually bounds a local model that does not fit "
                    "on the card: threads, PCIe, or memory bandwidth.")
    parser.add_argument("--mode",
                        choices=("bandwidth", "sweep", "gpulayers", "context",
                                 "both"),
                        default="both",
                        help="bandwidth needs no daemon and takes minutes; sweep "
                             "reloads the model once per thread rung; gpulayers "
                             "sweeps forced offload instead, threads held fixed")
    parser.add_argument("--config", default=None,
                        help=f"path to {CONFIG_FILENAME} (default: beside this script)")
    parser.add_argument("--threads", nargs="+", type=int, default=None,
                        help="override the thread rungs, e.g. --threads 10 16")
    parser.add_argument("--workers", nargs="+", type=int, default=None,
                        help="override the bandwidth worker counts")
    parser.add_argument("--num-gpu", nargs="+", type=int, default=None,
                        dest="num_gpu",
                        help="layer rungs for --mode gpulayers, lowest first so "
                             "the allocator's own choice is the control")
    parser.add_argument("--gpu-threads", type=int, default=None,
                        help="thread count held constant during --mode gpulayers")
    parser.add_argument("--contexts", nargs="+", type=int, default=None,
                        help="window rungs for --mode context, smallest first")
    parser.add_argument("--repeats", type=int, default=1,
                        help="run every rung this many times, INTERLEAVED rather "
                             "than blocked, so a machine that slows over the run "
                             "affects all settings equally instead of the last "
                             "one. One run cannot separate rungs inside the "
                             "noise: use 3 before trusting a small difference")
    parser.add_argument("--context-num-gpu", type=int, default=None,
                        help="force offload during --mode context; omit to let "
                             "the allocator decide, which is what shows how many "
                             "layers each window leaves room for")
    parser.add_argument("--model", default=None, help="override sweep.model")
    parser.add_argument("--num-ctx", type=int, default=None, help="override sweep.num_ctx")
    parser.add_argument("--dry-run", action="store_true",
                        help="print the plan and touch nothing (R16)")
    parser.add_argument("--json", dest="json_out", default=None,
                        help="write the machine-readable report here (R17)")
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    here = pathlib.Path(__file__).resolve().parent

    try:
        probe = load_probe(here / PROBE_FILENAME)
    except Refusal as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return EXIT_REFUSED

    refusals = (Refusal, probe.Refusal)
    try:
        config_path = pathlib.Path(args.config) if args.config else here / CONFIG_FILENAME
        cfg = load_config(config_path)
        origin = str(config_path)

        model = args.model or require(probe, cfg, "sweep.model", origin)
        num_ctx = args.num_ctx or require(probe, cfg, "sweep.num_ctx", origin)
        rungs = args.threads or require(probe, cfg, "sweep.threads", origin)
        workers = args.workers or require(probe, cfg, "bandwidth.workers", origin)

        if args.dry_run:
            print(f"config      {origin}")
            print(f"mode        {args.mode}")
            if args.mode in ("bandwidth", "both"):
                print(f"bandwidth   workers {workers}, "
                      f"{require(probe, cfg, 'bandwidth.buffer_mib_per_worker', origin)} "
                      f"MiB each, "
                      f"{require(probe, cfg, 'bandwidth.seconds_per_point', origin)} s "
                      f"per point")
            if args.mode in ("sweep", "both"):
                print(f"sweep       {model} at num_ctx {num_ctx}, thread rungs {rungs}, "
                      f"{require(probe, cfg, 'sweep.repeats', origin)} repeat(s)")
                print(f"            each rung evicts, reloads, and reads back the "
                      f"granted thread count from the server log")
            if args.mode == "gpulayers":
                layers = args.num_gpu or require(probe, cfg, "sweep.gpu_layers", origin)
                threads = args.gpu_threads or require(
                    probe, cfg, "sweep.gpu_sweep_num_thread", origin)
                print(f"gpulayers   {model} at num_ctx {num_ctx}, forced offload "
                      f"rungs {layers}, threads held at {threads}")
                print(f"            placement is read back from the log, so an "
                      f"override the allocator declines is labelled rather than "
                      f"recorded as granted")
            if args.mode == "context":
                windows = args.contexts or require(probe, cfg, "sweep.contexts", origin)
                threads = args.gpu_threads or require(
                    probe, cfg, "sweep.gpu_sweep_num_thread", origin)
                placement = ("the allocator's choice" if args.context_num_gpu is None
                             else f"forced at {args.context_num_gpu} layers")
                print(f"context     {model}, window rungs {windows}, threads held "
                      f"at {threads}, offload {placement}")
                print(f"            a window the daemon clamps is RECORDED with "
                      f"what it granted, not rejected: here the clamp is the "
                      f"finding")
            print("wrote       nothing")
            return EXIT_OK

        report = {"config": origin, "mode": args.mode,
                  "started": time.strftime("%Y-%m-%dT%H:%M:%S"),
                  "bandwidth": [], "sweep": [], "gpu_layers": [], "context": []}

        if args.mode in ("bandwidth", "both"):
            print("== DRAM read bandwidth against concurrent readers")
            report["bandwidth"] = run_bandwidth(cfg, origin, probe, workers)
            print(render_bandwidth_verdict(report["bandwidth"]))
            print()

        if args.mode in ("sweep", "gpulayers", "context", "both"):
            log_path = probe.resolve_server_log(
                require(probe, cfg, "server_log.candidate_paths", origin), origin)
            deps = probe.Deps(
                daemon=probe.Daemon(require(probe, cfg, "ollama.host", origin)),
                log=probe.FileLogReader(
                    log_path, require(probe, cfg, "server_log.max_tail_bytes", origin)),
                ram=probe.free_ram_mib)

        if args.mode in ("sweep", "both"):
            print(f"== decode throughput against thread count  ({model}, "
                  f"num_ctx {num_ctx})")
            report["sweep"] = run_sweep(cfg, origin, probe, deps, rungs,
                                        model, num_ctx)
            print(render_sweep_verdict(report["sweep"]))

        if args.mode == "gpulayers":
            print(f"== decode throughput against forced offload  ({model}, "
                  f"num_ctx {num_ctx})")
            report["gpu_layers"] = run_gpu_sweep(
                cfg, origin, probe, deps, args.num_gpu, args.gpu_threads,
                model, num_ctx, repeats=args.repeats)
            print(render_gpu_verdict(report["gpu_layers"]))

        if args.mode == "context":
            print(f"== decode throughput against context window  ({model})")
            report["context"] = run_context_sweep(
                cfg, origin, probe, deps, args.contexts, args.gpu_threads,
                args.context_num_gpu, model, repeats=args.repeats)
            print(render_context_verdict(report["context"]))

        if args.json_out:
            pathlib.Path(args.json_out).write_text(
                json.dumps(report, indent=2), encoding="utf-8")
            print(f"\nreport -> {args.json_out}")
        return EXIT_OK

    except refusals as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return EXIT_REFUSED
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return EXIT_FAIL


if __name__ == "__main__":
    mp.freeze_support()
    sys.exit(main())
