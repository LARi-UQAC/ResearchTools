"""
aider-gpu-probe - measure which (Ollama model x context window) combinations
actually put transformer layers on the GPU, and rank what it finds.

Why it exists. A large quantised model can be asked for a huge context window,
report itself as loaded, and run entirely on the CPU. `ollama ps` does not say
so: it reports a MEMORY split, computed from bytes resident in each space, and
the compute buffers plus a projector are enough to make a run with ZERO layers
on the GPU read as a few percent GPU. The only honest source is the server log
line

    load_tensors: offloaded 0/66 layers to GPU

so that line, and never `ollama ps`, decides what this script reports. The
residency ratio from `/api/ps` is still recorded, in its own column, labelled
as the memory ratio it is.

Three traps this script is built around, each of which silently produces a
wrong measurement rather than an error:

  1. The server log is append-only and holds every load since the daemon
     started. Parsing the whole file finds the LAST load, which may belong to
     someone else, so a load that failed outright reports the previous run's
     numbers as its own. The byte length is therefore recorded BEFORE the load
     request and only the text appended after it is read.

  2. A `num_ctx` above the model's native maximum is not an error: it is
     clamped, and the request succeeds. The rung then costs the memory of the
     smaller window while describing a window the daemon never granted. So the
     native maximum is read from `/api/show` before the rung is attempted, and
     the granted window is read back from the log's `llama_context: n_ctx`
     line afterwards. A measurement whose granted window is not the requested
     one is REJECTED rather than recorded.

  3. Freed memory is reported late. Immediately after an eviction a machine can
     report a few GB free and, seconds later, four times that. A free-RAM floor
     read once therefore refuses to start on a machine that is fine, so the
     reading is taken after a settle delay and re-taken once before it is
     believed.

What it is not. It does not tune anything, and it does not restart the daemon.
The KV cache type is daemon-wide and read only at daemon start, so this script
reports the value in force, read out of the log's own `server config` line,
rather than pretending it can sweep it.

Stage: machine characterisation. Run once per machine, or after installing a
model. Reads a JSON configuration beside this file; writes a table, and a JSON
report when asked. Standard library only, so there is nothing to install.
"""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import pathlib
import platform
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request

# Exit codes: 0 success, 2 refusal by design, 1 failure.
EXIT_OK = 0
EXIT_FAILED = 1
EXIT_REFUSED = 2

# Where each reported number came from. Every row carries one of these per
# field, so no figure in the table is unattributed.
SRC_LOG = "server.log"
SRC_MEASURED = "measured"
SRC_SMI = "nvidia-smi"
SRC_API = "api/ps"
SRC_OS = "os"
SRC_CONFIG = "config"

DEFAULT_CONFIG_NAME = "aider-gpu-probe.json"


class Refusal(Exception):
    """Raised when the script must stop rather than guess. Names what is missing."""


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

def expand_placeholders(text: str) -> str:
    """
    --------------------------------------------------------------------------
    Purpose:
        Resolve the {{NAME}} placeholders the shipped configuration uses in
        place of any machine path, so no account name is written into the kit.

    Inputs:
        text (str): a configured string, possibly holding {{HOME}} and friends.

    Outputs:
        resolved (str): the same string with every known placeholder replaced.
    --------------------------------------------------------------------------
    """
    home = str(pathlib.Path.home())
    table = {
        "{{HOME}}": home,
        "{{USERPROFILE}}": home,
        "{{LOCALAPPDATA}}": os.environ.get(
            "LOCALAPPDATA", str(pathlib.Path(home) / "AppData" / "Local")),
        "{{APPDATA}}": os.environ.get(
            "APPDATA", str(pathlib.Path(home) / "AppData" / "Roaming")),
        "{{XDG_CACHE_HOME}}": os.environ.get(
            "XDG_CACHE_HOME", str(pathlib.Path(home) / ".cache")),
    }
    for key, value in table.items():
        text = text.replace(key, value)
    return text


def require(cfg: dict, dotted: str, origin: str):
    """
    --------------------------------------------------------------------------
    Purpose:
        Read one configuration value, refusing rather than defaulting when it
        is absent. The refusal names both the key and the file it was expected
        in, because a silent default is indistinguishable from a measured value
        once it has reached a report.

    Inputs:
        cfg (dict): the parsed configuration.
        dotted (str): the key path, for example "ollama.host".
        origin (str): the configuration file's path, quoted in the refusal.

    Outputs:
        value (object): whatever the configuration holds at that key.
    --------------------------------------------------------------------------
    """
    node = cfg
    walked = []
    for part in dotted.split("."):
        walked.append(part)
        if not isinstance(node, dict) or part not in node:
            raise Refusal(
                f"configuration key '{'.'.join(walked)}' is missing from {origin}")
        node = node[part]
    return node


# Every pattern group the log parser reads, and how many capture groups each
# one must have. A pattern edited down to fewer groups would otherwise fail
# deep in a sweep with an IndexError rather than at validation.
PATTERN_GROUPS = {
    "offload": 2,               # 1 offloaded, 2 total
    "kv_cache_mib": 1,          # 1 MiB
    "compute_buffer_pool": 2,   # 1 pool name, 2 MiB
    "n_threads": 1,
    "n_ctx": 1,
    "kv_cache_type": 1,
    "fit_attempt": 2,           # 1 layer count, 2 MiB
}

REQUIRED_KEYS = (
    "ollama.host",
    "ollama.connect_timeout_s",
    "ollama.load_timeout_s",
    "ollama.decode_timeout_s",
    "ollama.show_timeout_s",
    "ollama.keep_alive",
    "ollama.think",
    "ollama.evict_poll_interval_s",
    "ollama.evict_timeout_s",
    "ollama.post_evict_settle_s",
    "server_log.candidate_paths",
    "server_log.read_delay_s",
    "server_log.max_tail_bytes",
    "log_selection.kv_cache_mib",
    "log_selection.compute_buffer_mib",
    "log_selection.host_pool_patterns",
    "gpu.nvidia_smi",
    "gpu.query_timeout_s",
    "measurement.warmup_prompt",
    "measurement.warmup_num_predict",
    "measurement.decode_prompt",
    "measurement.decode_num_predict",
    "skip.kv_bytes_per_token",
    "skip.vram_headroom_mib",
    "safety.min_free_ram_mib",
    "safety.free_ram_reread_delay_s",
    "ranking.order",
    "models",
    "contexts",
)

# How several matching lines are combined into one figure.
SELECTIONS = ("sum", "max", "last", "first")
# The compute buffers accept one more rule, and it is their default: report the
# device pool and the host pool as separate figures. Summing them adds VRAM to
# system RAM and describes no real constraint, since only the device pool
# competes for the card while the host pool competes with weights that were
# spilled to RAM. "max" is at least the figure that has to fit, but it discards
# the host figure, which is the second half of the story on a paging machine.
SELECTION_SPLIT = "split"
COMPUTE_SELECTIONS = SELECTIONS + (SELECTION_SPLIT,)


def validate_config(cfg: dict, origin: str) -> None:
    """
    --------------------------------------------------------------------------
    Purpose:
        Check every key this script reads, and the shape of those that are not
        scalars, so a typo is reported in the first second rather than after a
        sweep that costs minutes per combination.

    Inputs:
        cfg (dict): the parsed configuration.
        origin (str): the configuration file's path, quoted in refusals.

    Outputs:
        None. Raises Refusal naming the first key that is missing or malformed.
    --------------------------------------------------------------------------
    """
    for key in REQUIRED_KEYS:
        require(cfg, key, origin)

    models = require(cfg, "models", origin)
    if not isinstance(models, list) or not models:
        raise Refusal(f"'models' must be a non-empty list in {origin}")
    if not all(isinstance(m, str) and m for m in models):
        raise Refusal(f"'models' must hold model tags as strings in {origin}")

    contexts = require(cfg, "contexts", origin)
    if not isinstance(contexts, list) or not contexts:
        raise Refusal(f"'contexts' must be a non-empty list in {origin}")
    if not all(isinstance(c, int) and not isinstance(c, bool) and c > 0
               for c in contexts):
        raise Refusal(f"'contexts' must hold positive integers in {origin}")

    order = require(cfg, "ranking.order", origin)
    if not isinstance(order, list) or not order:
        raise Refusal(f"'ranking.order' must be a non-empty list in {origin}")
    for entry in order:
        if (not isinstance(entry, list) or len(entry) != 2
                or entry[1] not in ("asc", "desc")):
            raise Refusal(
                f"'ranking.order' entries must be [field, \"asc\"|\"desc\"] "
                f"in {origin}: {entry!r}")

    for name, needed in PATTERN_GROUPS.items():
        patterns = require(cfg, f"log_patterns.{name}", origin)
        if not isinstance(patterns, list) or not patterns:
            raise Refusal(f"'log_patterns.{name}' must be a non-empty list in {origin}")
        for pattern in patterns:
            if not isinstance(pattern, str):
                raise Refusal(f"'log_patterns.{name}' must hold regexes as strings "
                              f"in {origin}")
            try:
                compiled = re.compile(pattern)
            except re.error as exc:
                raise Refusal(
                    f"'log_patterns.{name}' holds a pattern that does not compile "
                    f"in {origin}: {pattern!r}: {exc}") from exc
            if compiled.groups < needed:
                raise Refusal(
                    f"'log_patterns.{name}' needs {needed} capture group(s) and this "
                    f"pattern has {compiled.groups} in {origin}: {pattern!r}")

    rule = require(cfg, "log_selection.kv_cache_mib", origin)
    if rule not in SELECTIONS:
        raise Refusal(f"'log_selection.kv_cache_mib' must be one of "
                      f"{', '.join(SELECTIONS)} in {origin}: {rule!r}")
    rule = require(cfg, "log_selection.compute_buffer_mib", origin)
    if rule not in COMPUTE_SELECTIONS:
        raise Refusal(f"'log_selection.compute_buffer_mib' must be one of "
                      f"{', '.join(COMPUTE_SELECTIONS)} in {origin}: {rule!r}")

    host_patterns = require(cfg, "log_selection.host_pool_patterns", origin)
    if not isinstance(host_patterns, list) or not host_patterns:
        raise Refusal(f"'log_selection.host_pool_patterns' must be a non-empty list "
                      f"in {origin}; it is what tells a host pool from a device one")
    for pattern in host_patterns:
        if not isinstance(pattern, str):
            raise Refusal(f"'log_selection.host_pool_patterns' must hold regexes as "
                          f"strings in {origin}")
        try:
            re.compile(pattern)
        except re.error as exc:
            raise Refusal(f"'log_selection.host_pool_patterns' holds a pattern that "
                          f"does not compile in {origin}: {pattern!r}: {exc}") from exc


def load_config(path: pathlib.Path) -> dict:
    """
    --------------------------------------------------------------------------
    Purpose:
        Parse the JSON configuration and prove the keys this script depends on
        are present before a single model is loaded.

    Inputs:
        path (pathlib.Path): the configuration file.

    Outputs:
        cfg (dict): the parsed and validated configuration.
    --------------------------------------------------------------------------
    """
    if not path.is_file():
        raise Refusal(f"configuration file not found: {path}")
    try:
        cfg = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise Refusal(f"configuration file does not parse: {path}: {exc}") from exc
    validate_config(cfg, str(path))
    return cfg


# ---------------------------------------------------------------------------
# Log parsing. Pure: it is given text, never a path.
# ---------------------------------------------------------------------------

def _matches(text: str, patterns) -> list:
    """Match objects of the FIRST configured pattern that matches at all, so a
    later pattern is a fallback for another log format rather than a second
    reading of the same load."""
    for pattern in patterns:
        found = list(re.finditer(pattern, text))
        if found:
            return found
    return []


def _select(values, rule: str):
    """Apply a configured selection rule to the numbers one pattern matched."""
    if not values:
        return None
    if rule == "sum":
        return sum(values)
    if rule == "max":
        return max(values)
    if rule == "first":
        return values[0]
    return values[-1]


def parse_offload(text: str, patterns):
    """
    --------------------------------------------------------------------------
    Purpose:
        Read how many layers actually went to the GPU. This is the measurement
        the whole script exists for, and the reason `/api/ps` is never used in
        its place: a run with 0 of 66 layers offloaded still holds GPU bytes,
        and still reports a non-zero GPU share there.

    Inputs:
        text (str): the log text appended by this load, and no earlier one.
        patterns (list[str]): regexes whose group 1 is the offloaded count and
            group 2 the total.

    Outputs:
        split (tuple[int, int] | None): (offloaded, total), or None when the
        log carried no such line, which is reported rather than read as zero.
    --------------------------------------------------------------------------
    """
    found = _matches(text, patterns)
    if not found:
        return None
    last = found[-1]
    return int(last.group(1)), int(last.group(2))


def parse_mib(text: str, patterns, rule: str):
    """
    --------------------------------------------------------------------------
    Purpose:
        Read a MiB figure out of the log, combining the several lines one load
        can produce. A hybrid attention layout prints one KV cache line per
        cache, and compute buffers are printed per memory pool, so taking the
        first line under-reports both.

    Inputs:
        text (str): the log text appended by this load.
        patterns (list[str]): regexes whose group 1 is the number.
        rule (str): the configured selection, "sum", "max", "first" or "last".

    Outputs:
        mib (float | None): the figure, or None when the log did not carry it.
    --------------------------------------------------------------------------
    """
    found = _matches(text, patterns)
    return _select([float(m.group(1)) for m in found], rule)


def parse_compute_buffers(text: str, patterns) -> list:
    """
    --------------------------------------------------------------------------
    Purpose:
        Read every compute buffer the load reserved, keeping the POOL each one
        belongs to. The pool is what makes the figure mean something: a device
        pool competes for VRAM, a host pool competes with whatever weights were
        spilled to system RAM, and one number covering both describes no real
        constraint.

    Inputs:
        text (str): the log text appended by this load.
        patterns (list[str]): regexes, group 1 the pool name, group 2 the MiB.

    Outputs:
        pools (list[tuple[str, float]]): (pool, MiB) pairs, in log order.
    --------------------------------------------------------------------------
    """
    return [(m.group(1), float(m.group(2))) for m in _matches(text, patterns)]


def is_host_pool(pool: str, host_patterns) -> bool:
    """Whether a pool name denotes system RAM. Data-driven, because a backend
    this was never run against names its pools differently."""
    return any(re.search(pattern, pool) for pattern in host_patterns)


def split_compute_buffers(pools, host_patterns):
    """
    --------------------------------------------------------------------------
    Purpose:
        Total the compute buffers per side. Several device pools (more than one
        card) are summed together, as are several host pools, but the two sides
        are never added to each other.

    Inputs:
        pools (list[tuple[str, float]]): from parse_compute_buffers.
        host_patterns (list[str]): regexes naming a host pool.

    Outputs:
        totals (tuple[float | None, float | None]): (device MiB, host MiB). A
        side with no pool at all is None rather than 0.0: a load that reserved
        no host buffer and one whose host buffer was not reported are different
        answers.
    --------------------------------------------------------------------------
    """
    device = [mib for pool, mib in pools if not is_host_pool(pool, host_patterns)]
    host = [mib for pool, mib in pools if is_host_pool(pool, host_patterns)]
    return (sum(device) if device else None, sum(host) if host else None)


def parse_int(text: str, patterns):
    """Read one integer (group 1) out of the log, the last occurrence winning."""
    found = _matches(text, patterns)
    if not found:
        return None
    return int(found[-1].group(1))


def parse_str(text: str, patterns):
    """Read one string (group 1) out of the log, the last occurrence winning."""
    found = _matches(text, patterns)
    if not found:
        return None
    return found[-1].group(1)


def parse_fit_attempts(text: str, patterns) -> list:
    """
    --------------------------------------------------------------------------
    Purpose:
        Capture the allocator's own failed attempts, which appear just before
        its verdict and explain it: they say how much memory one layer, then
        none, would have needed. Without them a row reading 0 layers offloaded
        looks like a policy decision rather than an arithmetic one.

    Inputs:
        text (str): the log text appended by this load.
        patterns (list[str]): regexes, group 1 the layer count, group 2 the MiB.

    Outputs:
        attempts (list[dict]): {"n_layer": int, "mem_mib": int}, in log order.
    --------------------------------------------------------------------------
    """
    return [{"n_layer": int(m.group(1)), "mem_mib": int(m.group(2))}
            for m in _matches(text, patterns)]


def native_context(show_body) -> tuple:
    """
    --------------------------------------------------------------------------
    Purpose:
        Read the model's own maximum context window from a /api/show body. The
        key is architecture-prefixed, so it is found by its suffix rather than
        by naming an architecture this script would then have to keep current.

    Inputs:
        show_body (dict): the parsed /api/show response.

    Outputs:
        found (tuple[int | None, str]): the window and the key it came from, or
        None and the reason it was not found. Not found is stated rather than
        replaced by a number, since a wrong ceiling silently admits a rung the
        daemon will clamp.
    --------------------------------------------------------------------------
    """
    info = (show_body or {}).get("model_info") or {}
    for key, value in info.items():
        if key.endswith(".context_length") and isinstance(value, int):
            return value, key
    return None, "no '<arch>.context_length' key in the /api/show model_info"


# ---------------------------------------------------------------------------
# Predicates and arithmetic (pure)
# ---------------------------------------------------------------------------

def predicted_kv_mib(num_ctx: int, kv_bytes_per_token: float) -> float:
    """
    --------------------------------------------------------------------------
    Purpose:
        Predict the KV cache a context window needs, from a per-token cost the
        configuration carries with its provenance. Used ONLY to skip a
        combination that cannot fit; every KV figure the table reports is read
        back from the server log instead.

    Inputs:
        num_ctx (int): the context window.
        kv_bytes_per_token (float): bytes of KV cache per token, from config.

    Outputs:
        mib (float): the predicted cache size in MiB.
    --------------------------------------------------------------------------
    """
    return num_ctx * kv_bytes_per_token / (1024.0 * 1024.0)


def should_skip(num_ctx: int, kv_bytes_per_token: float, vram_total_mib: float,
                headroom_mib: float, native_max=None):
    """
    --------------------------------------------------------------------------
    Purpose:
        Decide whether a combination is worth loading at all. Two reasons to
        skip, and both would otherwise cost minutes and yield a misleading row:
        a window whose KV cache alone exceeds the card cannot place a single
        layer, and a window above the model's native maximum is silently
        clamped, so the row would describe a window that was never granted.

    Inputs:
        num_ctx (int): the requested context window.
        kv_bytes_per_token (float): bytes of KV cache per token, from config.
        vram_total_mib (float): total VRAM, measured by nvidia-smi.
        headroom_mib (float): VRAM the configuration reserves for everything
            that is not KV cache: weights, compute buffers and the desktop.
        native_max (int | None): the model's own maximum, when it is known.

    Outputs:
        verdict (tuple[bool, str]): whether to skip, and the reason to print.
    --------------------------------------------------------------------------
    """
    if native_max is not None and num_ctx > native_max:
        return True, (f"above the model's native maximum of {native_max}; "
                      f"Ollama would clamp it silently and the row would "
                      f"describe a window that was never granted")
    predicted = predicted_kv_mib(num_ctx, kv_bytes_per_token)
    budget = vram_total_mib - headroom_mib
    if predicted >= budget:
        return True, (f"predicted KV {predicted:.0f} MiB >= {budget:.0f} MiB "
                      f"({vram_total_mib:.0f} VRAM - {headroom_mib:.0f} headroom)")
    return False, ""


def decode_tps(response: dict):
    """
    --------------------------------------------------------------------------
    Purpose:
        Compute decode throughput from an Ollama generate response. eval_* is
        decode and prompt_eval_* is prefill; prefill is parallel and fast,
        decode is the number a user feels, and mixing them reports one that
        belongs to neither.

    Inputs:
        response (dict): the parsed /api/generate response.

    Outputs:
        tps (float | None): tokens per second, or None when the response did
        not carry both fields or reported a non-positive duration.
    --------------------------------------------------------------------------
    """
    count = response.get("eval_count")
    duration = response.get("eval_duration")
    for value in (count, duration):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
    if duration <= 0:
        return None
    return float(count) / (float(duration) / 1e9)


def residency_ratio(ps_body, model: str):
    """
    --------------------------------------------------------------------------
    Purpose:
        Report size_vram / size for a resident tag. This is a MEMORY ratio and
        never a work ratio, which is why it is a column of its own beside the
        offloaded-layer count and never a substitute for it.

    Inputs:
        ps_body (dict): the parsed /api/ps response.
        model (str): the tag to look for.

    Outputs:
        ratio (float | None): the ratio, or None when the tag is not resident
        or the response carried no usable sizes.
    --------------------------------------------------------------------------
    """
    for entry in (ps_body or {}).get("models") or []:
        if (entry.get("name") or entry.get("model")) != model:
            continue
        size = entry.get("size")
        vram = entry.get("size_vram")
        if isinstance(size, (int, float)) and size > 0 and isinstance(vram, (int, float)):
            return float(vram) / float(size)
        return None
    return None


def rank_rows(rows: list, order) -> list:
    """
    --------------------------------------------------------------------------
    Purpose:
        Order the measured rows so the real trade-off is visible: how much of
        the model reached the GPU, how fast it then decodes, and how much
        context that bought. The ordering is configuration, so an operator who
        values context above speed re-ranks without editing code.

    Inputs:
        rows (list[dict]): the measured rows.
        order (list[list]): [field, "asc"|"desc"] pairs, most significant first.

    Outputs:
        ranked (list[dict]): a new list, sorted. A row missing a field sorts
        last on that field whatever the direction, so an unmeasured value never
        wins a ranking by being absent.
    --------------------------------------------------------------------------
    """
    for row in rows:
        for field, _ in order:
            if field not in row:
                raise Refusal(
                    f"ranking field '{field}' is not a measured field; "
                    f"rows carry: {', '.join(sorted(row))}")

    def key(row):
        parts = []
        for field, direction in order:
            value = row.get(field)
            missing = value is None
            number = 0.0 if missing else float(value)
            parts.append((1 if missing else 0,
                          -number if direction == "desc" else number))
        return parts

    return sorted(rows, key=key)


# ---------------------------------------------------------------------------
# The boundary: everything that touches the machine is injected here, so the
# offline suite drives every branch with no daemon, no log and no GPU.
# ---------------------------------------------------------------------------

def http_json(url: str, payload, timeout: float):
    """POST when a payload is given, GET otherwise. Returns the parsed body.
    Every call carries an explicit timeout, passed by the caller from config."""
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


class FileLogReader:
    """
    The server log, read by offset. `offset()` is taken before a load and
    `tail(offset)` returns only what was appended after it, which is what keeps
    one load's numbers from being credited to the next. The file is read fully
    into memory and the handle closed, because the daemon is appending to it
    while this runs.
    """

    def __init__(self, path: pathlib.Path, max_bytes: int):
        self.path = pathlib.Path(path)
        self.max_bytes = int(max_bytes)

    def offset(self) -> int:
        try:
            return self.path.stat().st_size
        except OSError:
            return 0

    def tail(self, offset: int) -> str:
        size = self.offset()
        # A rotated log is now shorter than the offset. Read it from the start
        # rather than returning nothing, which would read as "the daemon said
        # nothing about this load".
        start = 0 if size < offset else offset
        if size - start > self.max_bytes:
            start = size - self.max_bytes
        with open(self.path, "rb") as handle:
            handle.seek(start)
            data = handle.read()
        return data.decode("utf-8", errors="replace")


class Daemon:
    """Thin client over the Ollama HTTP API. The transport is injected."""

    def __init__(self, host: str, transport=http_json):
        self.host = host.rstrip("/")
        self.transport = transport

    def tags(self, timeout):
        return self.transport(f"{self.host}/api/tags", None, timeout)

    def ps(self, timeout):
        return self.transport(f"{self.host}/api/ps", None, timeout)

    def show(self, model, timeout):
        return self.transport(f"{self.host}/api/show", {"model": model}, timeout)

    def generate(self, payload, timeout):
        return self.transport(f"{self.host}/api/generate", payload, timeout)


class Deps:
    """Every effect the sweep performs, in one injected bundle."""

    def __init__(self, daemon, log, runner=subprocess.run, which=shutil.which,
                 clock=time.monotonic, sleeper=time.sleep, ram=None, smi=None):
        self.daemon = daemon
        self.log = log
        self.runner = runner
        self.which = which
        self.clock = clock
        self.sleeper = sleeper
        self.ram = ram
        self.smi = smi


def resident_names(ps_body) -> list:
    """The tags currently held in memory, from /api/ps. Used for presence and
    for the memory ratio only: the CPU/GPU percentages the same endpoint
    reports are not read here at all."""
    models = (ps_body or {}).get("models") or []
    return [m.get("name") or m.get("model") for m in models
            if (m.get("name") or m.get("model"))]


def installed_names(tags_body) -> list:
    """Every tag the daemon has pulled, from /api/tags."""
    models = (tags_body or {}).get("models") or []
    return [m.get("name") or m.get("model") for m in models
            if (m.get("name") or m.get("model"))]


def evict_all(deps: Deps, cfg: dict, origin: str) -> None:
    """
    --------------------------------------------------------------------------
    Purpose:
        Unload everything resident and PROVE it, then wait for the operating
        system to report the memory back. Two large models briefly co-resident
        is enough to stop a laptop outright, and eviction returns in about a
        second while the accounting takes several more.

    Inputs:
        deps (Deps): the injected effects.
        cfg (dict): the parsed configuration.
        origin (str): the configuration file's path, quoted in refusals.

    Outputs:
        None. Raises Refusal when the daemon still reports a resident model
        after the configured timeout: the effect is checked rather than the
        call's apparent success, since loading on top of a resident model is
        exactly what stops the machine.
    --------------------------------------------------------------------------
    """
    poll = float(require(cfg, "ollama.evict_poll_interval_s", origin))
    limit = float(require(cfg, "ollama.evict_timeout_s", origin))
    settle = float(require(cfg, "ollama.post_evict_settle_s", origin))
    request_timeout = float(require(cfg, "ollama.connect_timeout_s", origin))

    for name in resident_names(deps.daemon.ps(request_timeout)):
        deps.daemon.generate({"model": name, "keep_alive": 0}, request_timeout)

    deadline = deps.clock() + limit
    while True:
        still = resident_names(deps.daemon.ps(request_timeout))
        if not still:
            break
        if deps.clock() >= deadline:
            raise Refusal(f"models still resident after {limit:.0f}s of eviction: "
                          + ", ".join(still))
        deps.sleeper(poll)

    if settle > 0:
        deps.sleeper(settle)


def nvidia_smi_memory(cfg: dict, origin: str, runner=subprocess.run,
                      which=shutil.which):
    """
    --------------------------------------------------------------------------
    Purpose:
        Read used and total VRAM. An absent nvidia-smi is a refusal and not a
        blank column, because the skip predicate and every VRAM figure in the
        table depend on it.

    Inputs:
        cfg (dict), origin (str): configuration and its path.
        runner (callable), which (callable): injected for the offline suite.

    Outputs:
        memory (tuple[float, float]): (used MiB, total MiB).
    --------------------------------------------------------------------------
    """
    binary = require(cfg, "gpu.nvidia_smi", origin)
    timeout = float(require(cfg, "gpu.query_timeout_s", origin))
    resolved = which(binary)
    if not resolved:
        raise Refusal(f"'{binary}' was not found on PATH, so VRAM cannot be measured")
    # Invoked by the resolved path rather than the bare name: a bare name fails
    # on Windows, where the launcher carries an extension.
    completed = runner([resolved, "--query-gpu=memory.used,memory.total",
                        "--format=csv,noheader,nounits"],
                       capture_output=True, text=True, timeout=timeout)
    if completed.returncode != 0:
        tail = (completed.stderr or "").strip()[-300:]
        raise Refusal(f"{binary} exited {completed.returncode}: {tail}")
    lines = (completed.stdout or "").strip().splitlines()
    if not lines:
        raise Refusal(f"{binary} reported no GPU")
    parts = [p.strip() for p in lines[0].split(",")]
    if len(parts) < 2:
        raise Refusal(f"{binary} output not understood: {lines[0]!r}")
    try:
        return float(parts[0]), float(parts[1])
    except ValueError as exc:
        raise Refusal(f"{binary} output not understood: {lines[0]!r}") from exc


def free_ram_mib(system=platform.system):
    """
    --------------------------------------------------------------------------
    Purpose:
        Report free system RAM, which is what a CPU-only load consumes and what
        the safety floor is checked against.

    Inputs:
        system (callable): injected so the suite drives both platforms.

    Outputs:
        free (tuple[float | None, str]): MiB and its source, or None and the
        reason it is unavailable. Unavailable is stated, never reported as 0:
        no free memory and no way to read it are different answers.
    --------------------------------------------------------------------------
    """
    name = system()
    if name == "Windows":
        class Status(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong),
                        ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong),
                        ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong),
                        ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong),
                        ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
        status = Status()
        status.dwLength = ctypes.sizeof(Status)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return None, "GlobalMemoryStatusEx failed"
        return status.ullAvailPhys / (1024.0 * 1024.0), SRC_OS
    meminfo = pathlib.Path("/proc/meminfo")
    if meminfo.is_file():
        for line in meminfo.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("MemAvailable:"):
                return float(line.split()[1]) / 1024.0, SRC_OS
        return None, "/proc/meminfo carried no MemAvailable line"
    return None, f"free RAM is not readable on {name} with the standard library"


def free_ram_above_floor(deps: Deps, floor_mib: float, reread_delay_s: float):
    """
    --------------------------------------------------------------------------
    Purpose:
        Decide whether there is enough free RAM to load, taking the third trap
        into account: freed memory is reported late, so a single reading taken
        just after an eviction refuses to start on a machine that is fine. A
        reading below the floor is therefore slept on and taken again before it
        is believed.

    Inputs:
        deps (Deps): the injected effects, for the RAM reader and the sleeper.
        floor_mib (float): the configured floor.
        reread_delay_s (float): how long to wait before the second reading.

    Outputs:
        verdict (tuple[bool, float | None, str]): whether to proceed, the free
        RAM finally read, and its source or the reason it is unavailable.
        Unreadable free RAM proceeds: an unknown is not a low reading.
    --------------------------------------------------------------------------
    """
    free, source = deps.ram()
    if free is None:
        return True, None, source
    if free >= floor_mib:
        return True, free, source
    if reread_delay_s > 0:
        deps.sleeper(reread_delay_s)
    free, source = deps.ram()
    if free is None:
        return True, None, source
    return free >= floor_mib, free, source


# ---------------------------------------------------------------------------
# The sweep
# ---------------------------------------------------------------------------

def plan_combinations(models, contexts, kv_bytes_per_token, vram_total_mib,
                      headroom_mib, native_max_by_model=None) -> list:
    """
    --------------------------------------------------------------------------
    Purpose:
        Build the list of combinations to run, each carrying whether it will be
        skipped and why, so --dry-run prints exactly what a real run would do.

    Inputs:
        models (list[str]), contexts (list[int]): from configuration.
        kv_bytes_per_token (float), headroom_mib (float): from configuration.
        vram_total_mib (float): measured.
        native_max_by_model (dict | None): each model's own maximum window,
            where /api/show reported one.

    Outputs:
        plan (list[dict]): one entry per combination.
    --------------------------------------------------------------------------
    """
    native_max_by_model = native_max_by_model or {}
    plan = []
    for model in models:
        for num_ctx in contexts:
            skip, reason = should_skip(num_ctx, kv_bytes_per_token, vram_total_mib,
                                       headroom_mib,
                                       native_max_by_model.get(model))
            plan.append({
                "model": model,
                "num_ctx": num_ctx,
                "skip": skip,
                "skip_reason": reason,
                "native_max": native_max_by_model.get(model),
                "predicted_kv_mib": round(
                    predicted_kv_mib(num_ctx, kv_bytes_per_token), 1),
            })
    return plan


def new_row(model: str, num_ctx: int) -> dict:
    """One result row, every measured field absent until something measures it."""
    return {
        "model": model, "num_ctx": num_ctx, "status": "ok",
        "layers_offloaded": None, "layers_total": None, "layers_fraction": None,
        "n_ctx_granted": None, "kv_cache_mib": None,
        "compute_buffer_device_mib": None, "compute_buffer_host_mib": None,
        "compute_buffer_mib": None, "compute_buffer_pools": {},
        "n_threads": None, "kv_cache_type": None, "decode_tps": None,
        "residency_ratio": None, "vram_used_mib": None, "vram_total_mib": None,
        "free_ram_mib": None, "fit_attempts": [], "sources": {},
    }


def measure_one(deps: Deps, cfg: dict, origin: str, model: str,
                num_ctx: int) -> dict:
    """
    --------------------------------------------------------------------------
    Purpose:
        Run one combination end to end: evict and prove it, refuse to load
        below the free-RAM floor, load, read only the log this load appended,
        reject the measurement when the granted window is not the requested
        one, confirm the tag is resident, then measure decode throughput on a
        second request. Every field records where it came from.

    Inputs:
        deps (Deps): the injected effects.
        cfg (dict), origin (str): configuration and its path.
        model (str), num_ctx (int): the combination.

    Outputs:
        row (dict): the measured row, whose "status" says what went wrong
        whenever a field came back None.
    --------------------------------------------------------------------------
    """
    keep_alive = require(cfg, "ollama.keep_alive", origin)
    think = require(cfg, "ollama.think", origin)
    load_timeout = float(require(cfg, "ollama.load_timeout_s", origin))
    decode_timeout = float(require(cfg, "ollama.decode_timeout_s", origin))
    connect_timeout = float(require(cfg, "ollama.connect_timeout_s", origin))
    read_delay = float(require(cfg, "server_log.read_delay_s", origin))
    min_free_ram = float(require(cfg, "safety.min_free_ram_mib", origin))
    reread_delay = float(require(cfg, "safety.free_ram_reread_delay_s", origin))
    patterns = require(cfg, "log_patterns", origin)
    selection = require(cfg, "log_selection", origin)

    row = new_row(model, num_ctx)

    evict_all(deps, cfg, origin)

    proceed, free, free_source = free_ram_above_floor(deps, min_free_ram, reread_delay)
    if free is not None:
        row["free_ram_mib"] = round(free, 0)
        row["sources"]["free_ram_mib"] = free_source
    if not proceed:
        row["status"] = (f"skipped: free RAM {free:.0f} MiB is below the "
                         f"{min_free_ram:.0f} MiB floor after a re-read, and "
                         f"loading here is what stops the machine")
        return row

    offset = deps.log.offset()
    base_options = {"num_ctx": num_ctx}
    payload = {
        "model": model,
        "prompt": require(cfg, "measurement.warmup_prompt", origin),
        "stream": False,
        "think": think,
        "keep_alive": keep_alive,
        "options": dict(base_options,
                        num_predict=int(require(cfg, "measurement.warmup_num_predict",
                                                origin))),
    }
    try:
        deps.daemon.generate(payload, load_timeout)
    except Exception as exc:            # one failed load is a row, not a dead sweep
        row["status"] = f"load failed: {type(exc).__name__}: {str(exc)[-200:]}"
        return row

    if read_delay > 0:
        deps.sleeper(read_delay)
    tail = deps.log.tail(offset)

    split = parse_offload(tail, patterns["offload"])
    if split is None:
        # No figure is substituted from /api/ps here. That endpoint reports
        # resident bytes rather than layers, and reads as a few percent GPU on
        # a run that placed none.
        row["status"] = ("the server log carried no 'offloaded N/M layers' line "
                         "for this load, so the CPU/GPU split is unknown")
    else:
        row["layers_offloaded"], row["layers_total"] = split
        row["layers_fraction"] = round(split[0] / split[1], 4) if split[1] else None
        for field in ("layers_offloaded", "layers_total", "layers_fraction"):
            row["sources"][field] = SRC_LOG

    row["n_ctx_granted"] = parse_int(tail, patterns["n_ctx"])
    row["kv_cache_mib"] = parse_mib(tail, patterns["kv_cache_mib"],
                                    selection["kv_cache_mib"])

    # Every pool is kept whatever the configured rule, so the JSON report loses
    # nothing the log said and a later question can be answered without a
    # second sweep.
    pools = parse_compute_buffers(tail, patterns["compute_buffer_pool"])
    row["compute_buffer_pools"] = {pool: mib for pool, mib in pools}
    if selection["compute_buffer_mib"] == SELECTION_SPLIT:
        row["compute_buffer_device_mib"], row["compute_buffer_host_mib"] = \
            split_compute_buffers(pools, selection["host_pool_patterns"])
    else:
        row["compute_buffer_mib"] = _select([mib for _, mib in pools],
                                            selection["compute_buffer_mib"])

    row["n_threads"] = parse_int(tail, patterns["n_threads"])
    row["kv_cache_type"] = parse_str(tail, patterns["kv_cache_type"])
    row["fit_attempts"] = parse_fit_attempts(tail, patterns["fit_attempt"])
    for field in ("n_ctx_granted", "kv_cache_mib", "compute_buffer_device_mib",
                  "compute_buffer_host_mib", "compute_buffer_mib",
                  "n_threads", "kv_cache_type"):
        if row[field] is not None:
            row["sources"][field] = SRC_LOG

    if row["n_ctx_granted"] is not None and row["n_ctx_granted"] != num_ctx:
        # Trap 2. The request succeeded, the window was clamped, and recording
        # this row would describe a window the daemon never granted.
        row["status"] = (f"rejected: requested num_ctx {num_ctx} but the daemon "
                         f"granted {row['n_ctx_granted']}; the measurement would "
                         f"describe a window that was never in force")
        return row

    ps_body = deps.daemon.ps(connect_timeout)
    if model not in resident_names(ps_body):
        row["status"] = "the tag is not resident after the load, so nothing was measured"
        return row
    row["residency_ratio"] = residency_ratio(ps_body, model)
    if row["residency_ratio"] is not None:
        row["residency_ratio"] = round(row["residency_ratio"], 4)
        row["sources"]["residency_ratio"] = SRC_API

    decode_payload = {
        "model": model,
        "prompt": require(cfg, "measurement.decode_prompt", origin),
        "stream": False,
        "think": think,
        "keep_alive": keep_alive,
        "options": dict(base_options,
                        num_predict=int(require(cfg, "measurement.decode_num_predict",
                                                origin))),
    }
    try:
        response = deps.daemon.generate(decode_payload, decode_timeout)
        tps = decode_tps(response)
        if tps is None:
            row["status"] = ("the generate response carried no usable eval_count and "
                             "eval_duration, so decode was not measured")
        else:
            row["decode_tps"] = round(tps, 2)
            row["sources"]["decode_tps"] = SRC_MEASURED
    except Exception as exc:
        row["status"] = f"decode failed: {type(exc).__name__}: {str(exc)[-200:]}"

    if deps.smi is not None:
        used, total = deps.smi()
        row["vram_used_mib"], row["vram_total_mib"] = used, total
        row["sources"]["vram_used_mib"] = SRC_SMI
        row["sources"]["vram_total_mib"] = SRC_SMI

    free_after, free_source = deps.ram()
    if free_after is not None:
        row["free_ram_mib"] = round(free_after, 0)
        row["sources"]["free_ram_mib"] = free_source

    return row


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

# (header, source) per column, so the table states where each figure came from
# under its own heading rather than in a caption nobody reads. The compute
# buffer is one column or two depending on the configured rule, which is why
# the columns are built rather than declared once.
COLUMNS_HEAD = (
    ("model", SRC_CONFIG),
    ("num_ctx", SRC_CONFIG),
    ("granted", SRC_LOG),
    ("layers", SRC_LOG),
    ("gpu%", SRC_LOG),
    ("tok/s", SRC_MEASURED),
    ("kv MiB", SRC_LOG),
)
COLUMNS_COMPUTE_SPLIT = (("cbuf dev", SRC_LOG), ("cbuf host", SRC_LOG))
COLUMNS_COMPUTE_ONE = (("cbuf MiB", SRC_LOG),)
COLUMNS_TAIL = (
    ("thr", SRC_LOG),
    ("kv type", SRC_LOG),
    ("mem%", SRC_API),
    ("vram MiB", SRC_SMI),
)


def columns_for(split: bool) -> tuple:
    """The table's columns for the configured compute-buffer rule."""
    middle = COLUMNS_COMPUTE_SPLIT if split else COLUMNS_COMPUTE_ONE
    return COLUMNS_HEAD + middle + COLUMNS_TAIL


def format_row(row: dict, split: bool = True) -> list:
    """Render one measured row as the table's cells, an unmeasured field as '-'."""
    def num(value, spec):
        return "-" if value is None else format(value, spec)

    layers = ("-" if row["layers_offloaded"] is None
              else f"{row['layers_offloaded']}/{row['layers_total']}")
    fraction = ("-" if row["layers_fraction"] is None
                else f"{100 * row['layers_fraction']:.0f}%")
    memory = ("-" if row["residency_ratio"] is None
              else f"{100 * row['residency_ratio']:.0f}%")
    vram = ("-" if row["vram_used_mib"] is None
            else f"{row['vram_used_mib']:.0f}/{row['vram_total_mib']:.0f}")
    compute = ([num(row["compute_buffer_device_mib"], ".0f"),
                num(row["compute_buffer_host_mib"], ".0f")] if split
               else [num(row["compute_buffer_mib"], ".0f")])
    return ([row["model"], str(row["num_ctx"]), num(row["n_ctx_granted"], "d"),
             layers, fraction, num(row["decode_tps"], ".2f"),
             num(row["kv_cache_mib"], ".0f")]
            + compute
            + [num(row["n_threads"], "d"), row["kv_cache_type"] or "-",
               memory, vram])


def render_table(rows: list, split: bool = True) -> str:
    """Lay the ranked rows out as a fixed-width table with a source line under
    the header, so no printed number is unattributed, and a note per row whose
    status is not ok."""
    columns = columns_for(split)
    header = [c[0] for c in columns]
    sources = [c[1] for c in columns]
    body = [format_row(r, split) for r in rows]
    widths = []
    for index in range(len(columns)):
        candidates = [len(header[index]), len(sources[index])]
        candidates.extend(len(cells[index]) for cells in body)
        widths.append(max(candidates))

    def line(cells):
        return "  ".join(cell.ljust(widths[i]) for i, cell in enumerate(cells)).rstrip()

    out = [line(header), line(sources), line(["-" * w for w in widths])]
    out.extend(line(cells) for cells in body)

    notes = []
    for row in rows:
        if row["status"] != "ok":
            notes.append(f"  {row['model']} @ {row['num_ctx']}: {row['status']}")
        if row["fit_attempts"] and not row["layers_offloaded"]:
            attempts = ", ".join(f"{a['n_layer']} layer(s) needed {a['mem_mib']} MiB"
                                 for a in row["fit_attempts"])
            notes.append(f"  {row['model']} @ {row['num_ctx']}: allocator tried "
                         f"{attempts}")
    if notes:
        out.append("")
        out.append("notes:")
        out.extend(notes)
    out.append("")
    out.append("gpu%  is offloaded layers, read from the server log: the honest split.")
    out.append("mem%  is size_vram/size from /api/ps: a MEMORY ratio, not a work ratio.")
    if split:
        out.append("cbuf  dev is the device pool, competing for VRAM; host is the "
                   "system-RAM pool.")
        out.append("      They are never added: one number over both describes no "
                   "real constraint.")
    return "\n".join(out)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="Measure which (model x context) combinations put layers on the GPU.")
    ap.add_argument("--config", default=None,
                    help=f"configuration file (default: {DEFAULT_CONFIG_NAME} "
                         f"beside this script)")
    ap.add_argument("--models", nargs="+", default=None,
                    help="override the configured model list")
    ap.add_argument("--contexts", nargs="+", type=int, default=None,
                    help="override the configured context list")
    ap.add_argument("--dry-run", action="store_true",
                    help="print exactly what would be loaded, and load nothing")
    ap.add_argument("--json", dest="json_out", default=None,
                    help="also write the whole result as JSON to this path")
    return ap


def resolve_server_log(candidates, origin: str) -> pathlib.Path:
    """
    --------------------------------------------------------------------------
    Purpose:
        Find the Ollama server log among the configured candidates, refusing
        with every path tried when none exists. Without it there is no honest
        answer to give, so this is a stop and not a degradation.

    Inputs:
        candidates (list[str]): configured paths, placeholders unresolved.
        origin (str): the configuration file's path, quoted in the refusal.

    Outputs:
        path (pathlib.Path): the first candidate that exists.
    --------------------------------------------------------------------------
    """
    tried = []
    for raw in candidates:
        path = pathlib.Path(expand_placeholders(raw))
        tried.append(str(path))
        if path.is_file():
            return path
    raise Refusal(
        "no Ollama server log found, and the CPU/GPU split cannot be read "
        "honestly without it.\n  tried: " + "\n         ".join(tried)
        + f"\n  the list comes from 'server_log.candidate_paths' in {origin}")


def preflight(cfg: dict, origin: str, models, contexts, daemon: Daemon,
              vram_total_mib: float):
    """
    --------------------------------------------------------------------------
    Purpose:
        Everything that must be settled before a model is loaded: the daemon
        answers, every requested tag is installed, and each model's native
        context maximum is known so a rung that would be silently clamped is
        skipped rather than measured.

    Inputs:
        cfg (dict), origin (str): configuration and its path.
        models (list[str]), contexts (list[int]): the effective lists.
        daemon (Daemon): the client.
        vram_total_mib (float): measured VRAM, for the skip predicate.

    Outputs:
        state (tuple[list, list, dict]): installed tags, the plan, and the
        native maximum found per model (or the reason it was not found).
    --------------------------------------------------------------------------
    """
    connect_timeout = float(require(cfg, "ollama.connect_timeout_s", origin))
    show_timeout = float(require(cfg, "ollama.show_timeout_s", origin))

    try:
        tags = daemon.tags(connect_timeout)
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise Refusal(f"no Ollama daemon answered at {daemon.host}: {exc}") from exc

    installed = installed_names(tags)
    absent = [m for m in models if m not in installed]
    if absent:
        # A refusal rather than a warning, and it carries the fix: the shipped
        # 'models' list names tags tuned on the machine it was written on, so
        # this is the first thing a new machine hits and the message has to be
        # enough on its own.
        raise Refusal("these tags are not installed: " + ", ".join(absent)
                      + "\n  installed: " + (", ".join(sorted(installed)) or "(none)")
                      + f"\n  run 'ollama list' and put the tags you have into the "
                        f"'models' list of {origin}")

    native_max = {}
    native_why = {}
    for model in models:
        try:
            found, why = native_context(daemon.show(model, show_timeout))
        except Exception as exc:
            found, why = None, f"/api/show failed: {type(exc).__name__}: {exc}"
        if found is not None:
            native_max[model] = found
        native_why[model] = why

    plan = plan_combinations(
        models, contexts,
        float(require(cfg, "skip.kv_bytes_per_token", origin)),
        vram_total_mib,
        float(require(cfg, "skip.vram_headroom_mib", origin)),
        native_max)
    return installed, plan, native_why


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    config_path = (pathlib.Path(args.config) if args.config
                   else pathlib.Path(__file__).resolve().parent / DEFAULT_CONFIG_NAME)
    origin = str(config_path)

    try:
        cfg = load_config(config_path)
        models = args.models or require(cfg, "models", origin)
        contexts = args.contexts or require(cfg, "contexts", origin)
        host = expand_placeholders(require(cfg, "ollama.host", origin))

        log_path = resolve_server_log(
            require(cfg, "server_log.candidate_paths", origin), origin)
        used, total = nvidia_smi_memory(cfg, origin)
        daemon = Daemon(host)
        installed, plan, native_why = preflight(cfg, origin, models, contexts,
                                                daemon, total)
    except Refusal as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return EXIT_REFUSED

    deps = Deps(daemon,
                FileLogReader(log_path, int(require(cfg, "server_log.max_tail_bytes",
                                                    origin))),
                ram=free_ram_mib,
                smi=lambda: nvidia_smi_memory(cfg, origin))

    print(f"server log : {log_path}")
    print("             the only source used for the CPU/GPU split; /api/ps is not")
    print(f"vram       : {used:.0f} / {total:.0f} MiB used   ({SRC_SMI})")
    print(f"daemon     : {host}, {len(installed)} tags installed")
    for model, why in native_why.items():
        if not why.startswith("no ") and not why.startswith("/api/show failed"):
            continue
        print(f"note       : native context maximum unknown for {model}: {why}")
    print()

    if args.dry_run:
        print("dry run, nothing is loaded and nothing is written:")
        for entry in plan:
            verdict = f"SKIP  {entry['skip_reason']}" if entry["skip"] else "LOAD"
            native = "?" if entry["native_max"] is None else str(entry["native_max"])
            print(f"  {entry['model']:<28} num_ctx={entry['num_ctx']:<7} "
                  f"native_max={native:<8} predicted KV "
                  f"{entry['predicted_kv_mib']:>9.1f} MiB   {verdict}")
        return EXIT_OK

    rows = []
    try:
        for entry in plan:
            if entry["skip"]:
                print(f"skip  {entry['model']} @ {entry['num_ctx']}: "
                      f"{entry['skip_reason']}")
                continue
            print(f"load  {entry['model']} @ {entry['num_ctx']} ...", flush=True)
            rows.append(measure_one(deps, cfg, origin, entry["model"],
                                    entry["num_ctx"]))
        evict_all(deps, cfg, origin)
    except Refusal as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return EXIT_REFUSED
    except KeyboardInterrupt:
        print("\ninterrupted, reporting what was measured so far", file=sys.stderr)

    if not rows:
        print("no combination ran, so there is nothing to rank", file=sys.stderr)
        return EXIT_FAILED

    try:
        order = require(cfg, "ranking.order", origin)
        ranked = rank_rows(rows, order)
    except Refusal as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return EXIT_REFUSED

    split = (require(cfg, "log_selection.compute_buffer_mib", origin)
             == SELECTION_SPLIT)
    print()
    print(render_table(ranked, split))

    if args.json_out:
        report = {"server_log": str(log_path), "host": host,
                  "vram_used_mib": used, "vram_total_mib": total,
                  "ranking": order, "rows": ranked}
        out = pathlib.Path(args.json_out)
        out.write_text(json.dumps(report, indent=2), encoding="utf-8")
        # Verify the effect rather than trusting the call.
        if not out.is_file() or out.stat().st_size == 0:
            print(f"FAILED: {out} was not written", file=sys.stderr)
            return EXIT_FAILED
        print(f"\nwrote {out} ({out.stat().st_size} bytes)")

    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
