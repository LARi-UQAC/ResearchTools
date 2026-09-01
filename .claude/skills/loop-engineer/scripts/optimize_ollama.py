"""
optimize_ollama.py - measure-first GPU budget tuner for the local Ollama bridge (P4 Task 4).

Two independent CLI verbs:

  --detect          prints the GPU card name, total video memory (MiB), and driver
                     version, read from `nvidia-smi` (the only source this module trusts
                     for VRAM; a model card is not evidence and neither is a claim in an
                     issue). Never infers a number that was not measured this call.

  --sweep <tag>      climbs CONTEXT_LADDER (8192, 16384, 32768, 65536) starting from the
                     P4 Task 1 measured baseline rung, and STOPS at the first rung that
                     fails acceptance, keeping the LAST accepted rung - it never tries a
                     larger window once one has failed. Acceptance for a rung requires
                     all three, every one of 3 timed runs at that rung: `ollama ps` reads
                     100 percent GPU (never a mix with CPU - on Windows "shared GPU
                     memory" is system RAM over PCIe and counts as a spill, not headroom),
                     at least 300 MiB stays free (`nvidia-smi`), and the median generation
                     time has not regressed past the first accepted rung's median by more
                     than REGRESSION_TOLERANCE_FACTOR (a documented judgment call, not a
                     measured constant - see that constant's own comment). Writes
                     `.claude/local-model-config.json`, machine-local and gitignored,
                     which Task 5 reads for its retained num_ctx.

Why the HTTP API, not the `ollama run` CLI, drives every timed measurement here: `ollama
run --help` (checked directly, this session) has no context-window flag of any kind, so
there is no CLI mechanism to test a num_ctx other than the one already frozen into a
tag's Modelfile. `POST /api/generate` accepts `options.num_ctx` per request instead -
the same mechanism ollama_bridge.py already uses for D2 (see that module's docstring) -
so every rung in this sweep is a genuine, isolated measurement of that exact window,
never a guess extrapolated from the Modelfile's current setting. A consequence, stated
plainly: this sweep's absolute seconds are not directly comparable to P4 Task 1's
43.7 s CLI-measured median (`ollama run`, no explicit num_predict, free-running to EOS) -
this module's own regression check is therefore rung-to-rung, against the FIRST accepted
rung's median measured by this same module, never against that CLI figure. The CLI
figure remains a separate, valid sanity reference, reported alongside but not used as
the gate.

Weight-cost vs KV-cost isolation (brief, Step 2): `isolate_weight_and_kv_cost` loads the
SAME tag once at a deliberately tiny window (SMALL_CTX_FOR_ISOLATION) and once at the
retained candidate window, measures steady-state `nvidia-smi` VRAM at each (never mid-
generation - the model must be fully loaded and idle for this reading), and solves the
two-point linear system `used(N) = weights_mib + kv_per_token_mib * N` for the model's
fixed weight cost and its per-token KV cost, since a Transformer's KV cache buffer size
scales linearly with the context window (measured directly in the P4 Task 1 server.log:
"KV buffer size = 256.00 MiB (8192 cells, ...)" - a fixed constant per context length,
not a function of anything else). This is the source of "the measured cost per 1k
tokens" the brief asks for, and of the weights/KV-cache MiB split Task 4's own Modelfile
comment template needs.

`used_mib` is always computed as `memory.total - memory.free` from `nvidia-smi`, never
read from `memory.used` directly: P4 Task 1's own baseline measurement found the two
disagree by a small, real amount at rest (139 MiB) that `memory.used` does not
attribute to any process. This module keeps the same convention so its own numbers stay
comparable to that baseline row in p4-measurements.md.

Standard library only: argparse, json, logging, re, subprocess, sys, threading, time,
urllib.request, urllib.error, dataclasses avoided in favor of plain dict records so the
JSON round-trip in write_config needs no custom encoder. No `requests`, no `ollama`
Python package - the same constraint ollama_bridge.py and model_resolver.py already
carry, kept here for consistency across the three scripts sharing this directory.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# .../loop-engineer/scripts/optimize_ollama.py
SCRIPTS_DIR = Path(__file__).resolve().parent
LOOP_ENGINEER_DIR = SCRIPTS_DIR.parent
CLAUDE_DIR = LOOP_ENGINEER_DIR.parent.parent

# Machine-local, gitignored (see .gitignore, added by P4 Task 3) - never a source
# deliverable. Task 5 reads this file for the retained num_ctx per model.
CONFIG_PATH = CLAUDE_DIR / "local-model-config.json"

OLLAMA_HOST = "http://127.0.0.1:11434"
GENERATE_URL = f"{OLLAMA_HOST}/api/generate"

OLLAMA_PS_TIMEOUT_S = 30.0
NVIDIA_SMI_TIMEOUT_S = 15.0
REQUEST_TIMEOUT_S = 300.0

# Fixed sampling parameters, matching ollama_bridge.py's own measured, working
# mechanism (P4 Task 1: options.seed over the HTTP API is the only reproducible path;
# the CLI's piped `/set parameter seed` measurably does not work - see that module's
# docstring, D6). Reused here as literal constants, not by importing ollama_bridge, so
# this script carries no runtime dependency on the closed bridge module.
FIXED_SEED = 42
FIXED_TEMPERATURE = 0.2
FIXED_TOP_P = 0.9
FIXED_TOP_K = 40
RESPONSE_RESERVE_TOKENS = 1024  # num_predict cap for every timed generation in the sweep

# Issue #12 T3's own protocol. A fixed, SHORT reply is what makes decode throughput
# comparable across model families: with a 1024-token reserve a reasoning model spends the
# whole of it while a coder answers in about 150, so elapsed time then measures verbosity
# rather than speed. Measured 2026-08-27: 36.991 s versus 4.918 s at decode throughputs of
# 27.3 and 30.1 tokens per second.
DEFAULT_NUM_PREDICT = 160

# Acceptance thresholds for a sweep rung (brief, Step 2): all three required on every one
# of the 3 timed runs at that rung, not just the median.
MIN_FREE_MIB = 300
GPU_RESIDENCY_FULL_PERCENT = 100

# Judgment call, not a measured constant (documented as such, same convention
# model_resolver.py uses for its own thresholds): 20 percent slack against the FIRST
# accepted rung's median, so ordinary run-to-run generation-length variance (measured in
# P4 Task 1: three runs of the same prompt spanned 40.6-53.1 s with no working seed to
# pin content) does not itself fail a rung that is otherwise fully resident. A real
# CPU-spill regression is far larger than this (the brief's own measured spill penalty
# is 4.7x), so 20 percent cannot mask that failure mode; it only absorbs sampling noise.
REGRESSION_TOLERANCE_FACTOR = 1.20

# Mid-generation sample delay: P4 Task 1 sampled `ollama ps` about 8 s into a ~40 s run,
# deliberately after model load and into steady-state generation. This sweep uses the
# same order of magnitude.
MID_RUN_SAMPLE_DELAY_S = 6.0

# Settle time after a priming call before reading steady-state VRAM for the weight/KV
# isolation measurement (isolate_weight_and_kv_cost) - long enough for the daemon's own
# post-load bookkeeping to finish, short enough not to risk OLLAMA_KEEP_ALIVE unloading
# the model between the priming call and the read.
ISOLATION_SETTLE_S = 3.0

# The context ladder this sweep climbs, starting at the P4 Task 1 measured baseline rung
# (8192, already confirmed 100% GPU that session). Each rung doubles the window, which
# mirrors how the KV cache itself scales (linearly with num_ctx - see the module
# docstring's server.log citation), so doubling roughly doubles the KV cost each step.
CONTEXT_LADDER: tuple[int, ...] = (8192, 16384, 32768, 65536)

# Deliberately tiny window used only to isolate the model's fixed weight cost from its
# num_ctx-dependent KV cost (brief, Step 2). Not a candidate rung itself.
SMALL_CTX_FOR_ISOLATION = 512

# Fallback prompt used only when --prompt-file is omitted. A real sweep run should pass
# --prompt-file pointing at the same prompt used to establish the baseline median in
# p4-measurements.md, so the per-rung timings stay comparable to each other; this default
# exists so the script has a defined, working behavior even when no such file is given.
DEFAULT_SWEEP_PROMPT = (
    "Write a two-paragraph explanation, in English, of why a bounded KV cache matters "
    "when running a 9B parameter language model on a 6 GB GPU. Mention num_ctx and "
    "residency explicitly."
)

_PROBE_PROMPT = "Hello."

_PROCESSOR_FULL_RE = re.compile(r"^(\d+)%\s*GPU$")
_PROCESSOR_MIXED_RE = re.compile(r"^(\d+)%/(\d+)%\s*CPU/GPU$")


class OptimizeError(RuntimeError):
    """
    Raised on every measurement refusal in this module: an unreachable `nvidia-smi` or
    Ollama daemon, unparsable command output, a subprocess that failed to start, or a
    sweep that could not accept even its first rung. There is no silent fallback path -
    every failure mode raises this instead of returning a guessed or partial number.
    """


def _run(cmd: list[str], timeout: float) -> subprocess.CompletedProcess[str]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Shared subprocess boundary for every external command this module
        runs (`nvidia-smi`, `ollama ps`, `model_resolver.py --resolve`), so
        the "cannot run" and "timed out" failure modes are handled once.

    Inputs:
        cmd (list[str]): the pre-tokenized command (never built by shell
            concatenation of untrusted input).
        timeout (float): seconds before the call is killed.

    Outputs:
        result (subprocess.CompletedProcess[str]): the completed process
        (stdout/stderr as text); caller checks returncode itself, since some
        callers treat a non-zero exit as recoverable information rather than
        an immediate error.

    Raises:
        OptimizeError: the command could not be started or timed out.
    --------------------------------------------------------------------------
    """
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as exc:
        raise OptimizeError(f"[OPTIMIZE] cannot run {cmd!r}: {exc}") from exc


def nvidia_smi_query(fields: list[str], timeout: float = NVIDIA_SMI_TIMEOUT_S) -> list[str]:
    """
    --------------------------------------------------------------------------
    Purpose:
        The sole path this module measures GPU state through. Runs
        `nvidia-smi --query-gpu=<fields> --format=csv,noheader,nounits` and
        returns the first GPU's row, one string per requested field, in the
        order requested - never a claim, never a model card, always this
        exact command's own output for this exact invocation.

    Inputs:
        fields (list[str]): nvidia-smi query-gpu field names (e.g. "name",
            "memory.total", "memory.free", "driver_version").
        timeout (float): seconds before the call is killed.

    Outputs:
        result (list[str]): one stripped string per requested field.

    Raises:
        OptimizeError: nvidia-smi is not on PATH, timed out, exited non-zero,
        or returned no GPU row.
    --------------------------------------------------------------------------
    """
    query = ",".join(fields)
    proc = _run(["nvidia-smi", f"--query-gpu={query}", "--format=csv,noheader,nounits"], timeout)
    if proc.returncode != 0:
        raise OptimizeError(f"[OPTIMIZE] nvidia-smi exited {proc.returncode}: {proc.stderr.strip()}")
    lines = [line for line in proc.stdout.splitlines() if line.strip()]
    if not lines:
        raise OptimizeError("[OPTIMIZE] nvidia-smi returned no GPU row.")
    return [part.strip() for part in lines[0].split(",")]


def detect_card() -> dict[str, Any]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Implement the measurement behind --detect: card model, total video
        memory, and driver version, each read fresh from nvidia-smi.

    Inputs:
        none.

    Outputs:
        result (dict): {"name": str, "memory_total_mib": int,
        "driver_version": str}.

    Raises:
        OptimizeError: see nvidia_smi_query.
    --------------------------------------------------------------------------
    """
    name, total_str, driver = nvidia_smi_query(["name", "memory.total", "driver_version"])
    return {"name": name, "memory_total_mib": int(total_str), "driver_version": driver}


def gpu_memory_mib() -> tuple[int, int]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Read current (used_mib, free_mib). used_mib is computed as
        memory.total - memory.free, never read from nvidia-smi's own
        memory.used field directly: P4 Task 1 measured the two disagree by a
        small, real amount at rest (139 MiB) that memory.used does not
        attribute to any process. This keeps every number in this module
        comparable to that baseline row in p4-measurements.md.

    Inputs:
        none.

    Outputs:
        result (tuple[int, int]): (used_mib, free_mib).

    Raises:
        OptimizeError: see nvidia_smi_query.
    --------------------------------------------------------------------------
    """
    total_str, free_str = nvidia_smi_query(["memory.total", "memory.free"])
    total = int(total_str)
    free = int(free_str)
    return total - free, free


def cmd_detect() -> int:
    """
    --------------------------------------------------------------------------
    Purpose:
        Implement --detect's CLI output: three measured lines, nothing
        inferred.

    Inputs:
        none.

    Outputs:
        result (int): 0 on success.

    Raises:
        OptimizeError: see detect_card.
    --------------------------------------------------------------------------
    """
    card = detect_card()
    print(f"card: {card['name']}")
    print(f"total_video_memory_mib: {card['memory_total_mib']}")
    print(f"driver_version: {card['driver_version']}")
    return 0


def gpu_residency_percent(processor_field: str) -> int:
    """
    --------------------------------------------------------------------------
    Purpose:
        Parse `ollama ps`'s PROCESSOR column into a single GPU-resident
        percentage. Ollama prints this field in exactly two shapes, measured
        directly this session and in P4 Task 1: "100% GPU" for full
        residency, or "NN%/MM% CPU/GPU" when the daemon splits the model
        across CPU and GPU (Windows counts "shared GPU memory" spill as CPU
        here, per the brief's own warning, never as headroom).

    Inputs:
        processor_field (str): the two-token PROCESSOR field as printed by
            `ollama ps` (e.g. "100% GPU" or "23%/77% CPU/GPU").

    Outputs:
        result (int): the GPU-resident percentage (0-100).

    Raises:
        OptimizeError: the field matches neither known shape - refusing to
        guess a residency percentage rather than defaulting to 100 or 0.
    --------------------------------------------------------------------------
    """
    field = processor_field.strip()
    match_full = _PROCESSOR_FULL_RE.match(field)
    if match_full:
        return int(match_full.group(1))
    match_mixed = _PROCESSOR_MIXED_RE.match(field)
    if match_mixed:
        return int(match_mixed.group(2))
    raise OptimizeError(f"[OPTIMIZE] unrecognized 'ollama ps' PROCESSOR field: {processor_field!r}")


def ollama_ps_raw(timeout: float = OLLAMA_PS_TIMEOUT_S) -> str:
    """
    --------------------------------------------------------------------------
    Purpose:
        Run `ollama ps` and return its raw stdout.

    Inputs:
        timeout (float): seconds before the call is killed.

    Outputs:
        result (str): the raw stdout (header row plus one row per resident
        model; empty table when nothing is loaded).

    Raises:
        OptimizeError: the daemon is unreachable, the call timed out, or it
        exited non-zero.
    --------------------------------------------------------------------------
    """
    proc = _run(["ollama", "ps"], timeout)
    if proc.returncode != 0:
        raise OptimizeError(f"[OPTIMIZE] 'ollama ps' exited {proc.returncode}: {proc.stderr.strip()}")
    return proc.stdout


def parse_ollama_ps_row(raw: str, tag: str) -> dict[str, Any] | None:
    """
    --------------------------------------------------------------------------
    Purpose:
        Extract `tag`'s row from `ollama ps` output. Columns are whitespace-
        separated: NAME ID SIZE_NUM SIZE_UNIT PROCESSOR_PCT PROCESSOR_LABEL
        CONTEXT UNTIL... (measured directly this session and in P4 Task 1:
        the PROCESSOR field is always exactly two whitespace-separated
        tokens, either "100%" + "GPU" or "23%/77%" + "CPU/GPU", so CONTEXT is
        always the seventh token, never located by a positional guess past
        that).

    Inputs:
        raw (str): `ollama ps`'s raw stdout.
        tag (str): the model tag to find (matched against the NAME column
            exactly).

    Outputs:
        result (dict | None): {"size_str": str, "processor_field": str,
        "gpu_percent": int, "context": int} for the matching row, or None
        when `tag` is not currently resident (not an error - a cold sweep
        rung is expected to load it).

    Raises:
        OptimizeError: a row starting with `tag` has fewer fields than this
        format requires, or its PROCESSOR field does not parse (see
        gpu_residency_percent).
    --------------------------------------------------------------------------
    """
    lines = raw.splitlines()
    for line in lines[1:]:
        parts = line.split()
        if not parts or parts[0] != tag:
            continue
        if len(parts) < 7:
            raise OptimizeError(f"[OPTIMIZE] 'ollama ps' row for {tag!r} has too few fields: {line!r}")
        size_str = f"{parts[2]} {parts[3]}"
        processor_field = f"{parts[4]} {parts[5]}"
        context = int(parts[6])
        return {
            "size_str": size_str,
            "processor_field": processor_field,
            "gpu_percent": gpu_residency_percent(processor_field),
            "context": context,
        }
    return None


GPU_RESIDENCY_MIN_RATIO = 0.999


def _api_ps_body(timeout: float = OLLAMA_PS_TIMEOUT_S) -> dict[str, Any]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Fetch the daemon's own /api/ps document. Split from api_ps_row so a
        test can replace the transport without touching the parsing.

    Inputs:
        timeout (float): socket timeout in seconds.

    Outputs:
        result (dict): the decoded response body.

    Raises:
        OptimizeError: the daemon is unreachable or answered non-JSON. No
        silent fallback - an unmeasurable card is a stop, not a default.
    --------------------------------------------------------------------------
    """
    try:
        with urllib.request.urlopen(f"{OLLAMA_HOST}/api/ps", timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise OptimizeError(f"[OPTIMIZE] /api/ps unreachable or unreadable: {exc}") from exc


def api_ps_row(tag: str, timeout: float = OLLAMA_PS_TIMEOUT_S) -> dict[str, Any] | None:
    """
    --------------------------------------------------------------------------
    Purpose:
        Report one resident model's memory split and granted window from
        /api/ps. Replaces parsing the PROCESSOR text column of `ollama ps`:
        the API returns size, size_vram and context_length as numbers, so
        residency is a ratio rather than an integer recovered from a string
        such as "21%/79% CPU/GPU", and the granted window is read rather
        than inferred.

    Inputs:
        tag (str): the model tag to look for.
        timeout (float): socket timeout in seconds.

    Outputs:
        result (dict | None): {"size", "size_vram", "context_length",
        "residency_ratio"} for the tag, or None when it is not resident at
        this instant (a normal condition mid-load, not an error).
    --------------------------------------------------------------------------
    """
    for model in _api_ps_body(timeout).get("models", []):
        if tag not in (model.get("name"), model.get("model")):
            continue
        size = model.get("size") or 0
        size_vram = model.get("size_vram") or 0
        return {
            "size": size,
            "size_vram": size_vram,
            "context_length": model.get("context_length"),
            "residency_ratio": round(size_vram / size, 6) if size else 0.0,
        }
    return None


def build_payload(prompt: str, model: str, num_ctx: int, num_predict: int, seed: int = FIXED_SEED) -> dict[str, Any]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Build the /api/generate request body for one measurement call. This
        is the same mechanism ollama_bridge.py's build_payload uses (fixed
        seed/temperature/top_p/top_k, num_ctx and num_predict always set
        explicitly), reproduced here as a pure function rather than imported,
        so this module has no runtime dependency on the closed bridge file.

    Inputs:
        prompt (str): the full prompt text.
        model (str): the Ollama tag to request.
        num_ctx (int): the context window for this request.
        num_predict (int): the reply-length cap for this request.
        seed (int): the sampling seed (default FIXED_SEED).

    Outputs:
        result (dict): the request body, ready for json.dumps.
    --------------------------------------------------------------------------
    """
    return {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {
            "seed": seed,
            "num_ctx": num_ctx,
            "num_predict": num_predict,
            "temperature": FIXED_TEMPERATURE,
            "top_p": FIXED_TOP_P,
            "top_k": FIXED_TOP_K,
        },
    }


def post_generate(payload: dict[str, Any], timeout: float = REQUEST_TIMEOUT_S) -> dict[str, Any]:
    """
    --------------------------------------------------------------------------
    Purpose:
        The sole network boundary in this module. POSTs to /api/generate and
        returns the parsed JSON response.

    Inputs:
        payload (dict): the request body from build_payload.
        timeout (float): socket timeout in seconds.

    Outputs:
        result (dict): the parsed JSON response.

    Raises:
        OptimizeError: connection failure, read timeout, a non-2xx HTTP
        status, or a response body that is not valid JSON.
    --------------------------------------------------------------------------
    """
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        GENERATE_URL, data=body, method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
    except TimeoutError as exc:
        raise OptimizeError(f"[OPTIMIZE] Ollama request timed out after {timeout}s: {exc}") from exc
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise OptimizeError(f"[OPTIMIZE] Ollama returned HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise OptimizeError(f"[OPTIMIZE] cannot reach the Ollama daemon at {GENERATE_URL}: {exc.reason}") from exc
    try:
        return json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise OptimizeError(f"[OPTIMIZE] Ollama response was not valid JSON: {exc}") from exc


def timed_generate_with_sample(
    tag: str,
    prompt: str,
    num_ctx: int,
    num_predict: int,
    sample_delay_s: float = MID_RUN_SAMPLE_DELAY_S,
) -> dict[str, Any]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Run one real, timed generation against the live daemon and, while it
        is still in flight, sample `ollama ps` and nvidia-smi from a second
        thread - the same mid-generation-sample technique P4 Task 1 used by
        hand (measured about 8 s into a run already in progress), so
        PROCESSOR/CONTEXT and VRAM are read during steady-state generation,
        never inferred from the request alone or read only after the model
        has already finished and possibly unloaded.

    Inputs:
        tag (str): the model tag to generate with.
        prompt (str): the full prompt text.
        num_ctx (int): the context window for this call.
        num_predict (int): the reply-length cap for this call.
        sample_delay_s (float): seconds to wait before sampling.

    Outputs:
        result (dict): {"elapsed_s": float, "response": dict, "sample":
        dict | None} - "sample" is None only if the mid-run measurement
        itself failed (logged as a warning, never silently dropped) or the
        model was not yet resident at the sample instant.

    Raises:
        OptimizeError: the generation call itself failed (network, HTTP
        status, invalid JSON) - propagated from the worker thread.
    --------------------------------------------------------------------------
    """
    holder: dict[str, Any] = {}
    error_holder: list[BaseException] = []

    def _worker() -> None:
        t0 = time.perf_counter()
        try:
            payload = build_payload(prompt, tag, num_ctx, num_predict)
            response = post_generate(payload)
        except OptimizeError as exc:
            error_holder.append(exc)
            return
        holder["elapsed_s"] = time.perf_counter() - t0
        holder["response"] = response

    thread = threading.Thread(target=_worker)
    thread.start()
    time.sleep(sample_delay_s)

    sample: dict[str, Any] | None = None
    try:
        ps_row = parse_ollama_ps_row(ollama_ps_raw(), tag)
        api_row = api_ps_row(tag)
        used_mib, free_mib = gpu_memory_mib()
        if ps_row is not None:
            # The text row still supplies gpu_percent and the human-readable size for the
            # report; the API row supplies the two numbers the objective function ranks on.
            sample = {
                **ps_row,
                "used_mib": used_mib,
                "free_mib": free_mib,
                "residency_ratio": (api_row or {}).get("residency_ratio", 0.0),
            }
        else:
            logger.warning("[OPTIMIZE] mid-run sample: %r not resident yet at the sample instant.", tag)
    except OptimizeError as exc:
        logger.warning("[OPTIMIZE] mid-run sample failed: %s", exc)

    thread.join()
    if error_holder:
        raise error_holder[0]
    if "response" not in holder:
        raise OptimizeError("[OPTIMIZE] generation thread produced no response.")
    return {"elapsed_s": holder["elapsed_s"], "response": holder["response"], "sample": sample}


def _throughput_tokens_per_s(response: dict[str, Any]) -> float | None:
    """
    --------------------------------------------------------------------------
    Purpose:
        Compute measured tokens/second from the daemon's own reported
        eval_count and eval_duration (nanoseconds), never estimated from
        wall-clock time and a character count.

    Inputs:
        response (dict): the /api/generate response body.

    Outputs:
        result (float | None): tokens per second, or None if the response
        carried no usable eval_count/eval_duration pair.
    --------------------------------------------------------------------------
    """
    eval_count = response.get("eval_count")
    eval_duration_ns = response.get("eval_duration")
    if not isinstance(eval_count, int) or not isinstance(eval_duration_ns, int) or eval_duration_ns <= 0:
        return None
    return eval_count / (eval_duration_ns / 1e9)


def evaluate_rung(
    tag: str,
    num_ctx: int,
    prompt: str,
    num_predict: int,
    baseline_median_s: float | None,
    runs_per_rung: int = 3,
) -> dict[str, Any]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Run one rung of the sweep: `runs_per_rung` timed generations (P4 Task
        1's own protocol - 3 runs, median taken), sampling residency mid-
        generation on each. A rung is accepted only if EVERY run's sample
        meets the 100 percent GPU / 300 MiB free thresholds - the worst
        (minimum) observed value across the runs decides this, not the best
        one - and the median elapsed time has not regressed past
        `baseline_median_s` by more than REGRESSION_TOLERANCE_FACTOR.

    Inputs:
        tag (str): the model tag being swept.
        num_ctx (int): the context window for this rung.
        prompt (str): the full prompt text (same prompt across every rung, so
            the comparison is apples to apples).
        num_predict (int): the reply-length cap for every run.
        baseline_median_s (float | None): the first accepted rung's median,
            or None for the first rung itself (no regression check yet).
        runs_per_rung (int): number of timed runs at this rung (default 3).

    Outputs:
        result (dict): {"num_ctx", "median_s", "runs_s", "throughputs_tok_s",
        "min_gpu_percent", "min_free_mib", "residency_ratio" (the WORST
        run's size_vram/size ratio, from /api/ps), "decode_tps" (the MEDIAN
        run's eval_count/eval_duration throughput), "samples", "accepted"}.

    Raises:
        OptimizeError: no mid-run sample was captured on ANY of the runs at
        this rung (refuses rather than accepting on unmeasured residency).
    --------------------------------------------------------------------------
    """
    runs: list[dict[str, Any]] = []
    for _ in range(runs_per_rung):
        runs.append(timed_generate_with_sample(tag, prompt, num_ctx, num_predict))

    elapsed_sorted = sorted(r["elapsed_s"] for r in runs)
    median_s = elapsed_sorted[len(elapsed_sorted) // 2]
    throughputs = [t for t in (_throughput_tokens_per_s(r["response"]) for r in runs) if t is not None]

    samples = [r["sample"] for r in runs if r["sample"] is not None]
    if not samples:
        raise OptimizeError(
            f"[OPTIMIZE] num_ctx={num_ctx}: no mid-run sample was captured on any of the "
            f"{runs_per_rung} runs; refusing to accept a rung whose residency was never "
            "actually measured."
        )

    min_gpu_percent = min(s["gpu_percent"] for s in samples)
    min_free_mib = min(s["free_mib"] for s in samples)
    residency_ratios = [s["residency_ratio"] for s in samples if "residency_ratio" in s]
    min_residency_ratio = min(residency_ratios) if residency_ratios else 0.0
    decode_sorted = sorted(throughputs)
    median_decode_tps = decode_sorted[len(decode_sorted) // 2] if decode_sorted else 0.0
    regressed = (
        baseline_median_s is not None
        and median_s > baseline_median_s * REGRESSION_TOLERANCE_FACTOR
    )
    # Fix (2026-08-27): a rung above the model's OWN native context maximum was being
    # accepted. Ollama does not error on options.num_ctx past that maximum - it silently
    # clamps, so the request costs exactly the memory of the clamped window and the whole
    # acceptance predicate above passes on numbers that describe a DIFFERENT, smaller
    # window. Measured on qwen2.5-coder:7b-gpu (native max 32768): rung 65536 reported
    # min_free_mib 617 and 100 percent GPU, byte-identical to rung 32768, and 'ollama ps'
    # reported CONTEXT 32768 on all three runs - so the sweep retained 65536, a window the
    # daemon will never grant. That number then feeds the bridge's budget gate, which would
    # pass a ~64k-token prompt straight into the num_ctx // 2 + 2 truncation this repository
    # keeps a measured signature for. The residency samples already carry the daemon's own
    # CONTEXT field, so the clamp is detectable with no extra call: a rung is honest only
    # when every sample reports the window that was actually asked for.
    observed_contexts = sorted({s["context"] for s in samples if s.get("context") is not None})
    clamped = bool(observed_contexts) and observed_contexts != [num_ctx]
    accepted = (
        min_gpu_percent >= GPU_RESIDENCY_FULL_PERCENT
        and min_free_mib >= MIN_FREE_MIB
        and not regressed
        and not clamped
    )
    return {
        "num_ctx": num_ctx,
        "median_s": round(median_s, 3),
        "runs_s": [round(s, 3) for s in elapsed_sorted],
        "throughputs_tok_s": [round(t, 2) for t in throughputs],
        "min_gpu_percent": min_gpu_percent,
        "min_free_mib": min_free_mib,
        "residency_ratio": min_residency_ratio,
        "decode_tps": round(median_decode_tps, 2),
        "samples": samples,
        "regressed_past_baseline": regressed,
        "observed_contexts": observed_contexts,
        "clamped_by_model_maximum": clamped,
        "accepted": accepted,
    }


def _load_and_measure_steady_state(tag: str, num_ctx: int, settle_s: float = ISOLATION_SETTLE_S) -> int:
    """
    --------------------------------------------------------------------------
    Purpose:
        Force the daemon to load `tag` at exactly `num_ctx` with a short
        priming call (num_predict=1 is enough to trigger a reload if the
        resident context differs - the same num_predict=1 trick
        ollama_bridge.py's probe_prompt_tokens already relies on, reproduced
        here rather than imported), wait `settle_s` for the daemon's own
        post-load bookkeeping to finish, then read steady-state VRAM.

    Inputs:
        tag (str): the model tag to load.
        num_ctx (int): the context window to load it at.
        settle_s (float): seconds to wait after the priming call before
            reading nvidia-smi.

    Outputs:
        result (int): used_mib (total - free) once the model is resident and
        idle at this num_ctx.

    Raises:
        OptimizeError: the priming call or the nvidia-smi read failed.
    --------------------------------------------------------------------------
    """
    payload = build_payload(_PROBE_PROMPT, tag, num_ctx, num_predict=1)
    post_generate(payload)
    time.sleep(settle_s)
    used_mib, _free_mib = gpu_memory_mib()
    return used_mib


def isolate_weight_and_kv_cost(tag: str, candidate_num_ctx: int) -> dict[str, Any]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Isolate the model's fixed weight cost from its num_ctx-dependent KV
        cache cost (brief, Step 2: "load once at a deliberately small window,
        once at the candidate window, and subtract"). Loads `tag` at
        SMALL_CTX_FOR_ISOLATION and at `candidate_num_ctx`, measures
        steady-state VRAM at each, and solves the two-point linear system
        `used(N) = weights_mib + kv_per_token_mib * N` - valid because the KV
        cache buffer size scales linearly with the context window (measured
        directly in the P4 Task 1 server.log: a fixed MiB-per-context-length
        constant, not a function of anything else).

    Inputs:
        tag (str): the model tag being measured.
        candidate_num_ctx (int): the retained rung from the sweep.

    Outputs:
        result (dict): {"small_ctx", "used_small_mib", "used_candidate_mib",
        "weights_mib", "kv_cache_mib_at_candidate",
        "kv_cost_mib_per_1k_tokens", "total_mib"}.

    Raises:
        OptimizeError: candidate_num_ctx does not exceed the isolation
        window, or either steady-state measurement failed.
    --------------------------------------------------------------------------
    """
    if candidate_num_ctx <= SMALL_CTX_FOR_ISOLATION:
        raise OptimizeError(
            f"[OPTIMIZE] candidate num_ctx ({candidate_num_ctx}) must exceed the isolation "
            f"window ({SMALL_CTX_FOR_ISOLATION})."
        )
    used_small = _load_and_measure_steady_state(tag, SMALL_CTX_FOR_ISOLATION)
    used_candidate = _load_and_measure_steady_state(tag, candidate_num_ctx)

    delta_mib = used_candidate - used_small
    delta_ctx = candidate_num_ctx - SMALL_CTX_FOR_ISOLATION
    kv_per_token_mib = delta_mib / delta_ctx
    weights_mib = used_small - kv_per_token_mib * SMALL_CTX_FOR_ISOLATION
    kv_at_candidate_mib = kv_per_token_mib * candidate_num_ctx

    return {
        "small_ctx": SMALL_CTX_FOR_ISOLATION,
        "used_small_mib": used_small,
        "used_candidate_mib": used_candidate,
        "weights_mib": round(weights_mib, 1),
        "kv_cache_mib_at_candidate": round(kv_at_candidate_mib, 1),
        "kv_cost_mib_per_1k_tokens": round(kv_per_token_mib * 1000, 2),
        "total_mib": round(used_candidate, 1),
    }


def resolve_kv_cache_type_label(explicit_label: str | None) -> str:
    """
    --------------------------------------------------------------------------
    Purpose:
        Determine the OLLAMA_KV_CACHE_TYPE label to record alongside a
        measurement. `os.environ` here is THIS SCRIPT's own process, not the
        Ollama daemon's - the two are separate processes, and (measured
        directly in this plan's own Step 1) a value set by `setx`, or set in
        one shell, does not propagate into a different, already-running or
        separately-spawned process. So a bare `os.environ.get(...)` in this
        function would silently read "unset" even while the daemon serving
        every request in this sweep is actually running under a real KV
        cache type - a wrong-but-plausible-looking value is worse than an
        honest "unknown", per this whole plan's governing rule (measure,
        never infer). `explicit_label` (the --kv-cache-type-label CLI flag)
        lets the caller state the value it independently verified from the
        daemon's own server.log "server config" line; when omitted, this
        function tries the same-process environment variable as a best
        effort (correct only when the caller's own shell set it before
        invoking this script) and otherwise says so explicitly rather than
        guessing "f16".

    Inputs:
        explicit_label (str | None): the --kv-cache-type-label CLI value, or
            None if not passed.

    Outputs:
        result (str): `explicit_label` if given; else this process's own
        OLLAMA_KV_CACHE_TYPE if set; else an explicit "unknown" message
        naming why it could not be determined here.
    --------------------------------------------------------------------------
    """
    if explicit_label:
        return explicit_label
    same_process_value = os.environ.get("OLLAMA_KV_CACHE_TYPE")
    if same_process_value:
        return same_process_value
    return (
        "unknown (OLLAMA_KV_CACHE_TYPE was not set in this script's own process, and "
        "--kv-cache-type-label was not passed; a value set via setx or a different shell "
        "does not propagate here - verify from the daemon's own server.log 'server config' "
        "line and pass --kv-cache-type-label explicitly)"
    )


def write_config(
    tag: str,
    retained_rung: dict[str, Any],
    sweep_records: list[dict[str, Any]],
    vram_split: dict[str, Any],
    card: dict[str, Any],
    kv_cache_type_label: str,
) -> None:
    """
    --------------------------------------------------------------------------
    Purpose:
        The only place local-model-config.json is written. Merges this
        model's fresh measurement into any existing document (so sweeping a
        second tag does not erase the first), keyed by tag under "models".

    Inputs:
        tag (str): the model tag just swept.
        retained_rung (dict): the last accepted rung's record from
            evaluate_rung.
        sweep_records (list[dict]): every rung's record, accepted or not, in
            climb order.
        vram_split (dict): isolate_weight_and_kv_cost's result.
        card (dict): detect_card's result, recorded alongside so a later
            reader knows what hardware these numbers were measured on.
        kv_cache_type_label (str): resolve_kv_cache_type_label's result - the
            weight/KV split and every rung's free-MiB reading depend on this
            setting, so a later reader must know which one produced the
            numbers on record.

    Outputs:
        None. CONFIG_PATH is created (parents included) or updated.
    --------------------------------------------------------------------------
    """
    existing: dict[str, Any] = {}
    if CONFIG_PATH.exists():
        raw = CONFIG_PATH.read_text(encoding="utf-8").strip()
        if raw:
            existing = json.loads(raw)

    models = existing.setdefault("models", {})
    models[tag] = {
        "measured_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "gpu_card": card,
        "kv_cache_type": kv_cache_type_label,
        "retained_num_ctx": retained_rung["num_ctx"],
        "acceptance_thresholds": {
            "min_gpu_residency_percent": GPU_RESIDENCY_FULL_PERCENT,
            "min_free_mib": MIN_FREE_MIB,
            "regression_tolerance_factor": REGRESSION_TOLERANCE_FACTOR,
        },
        "retained_rung_measurement": retained_rung,
        "sweep_ladder": sweep_records,
        "vram_split_at_retained_num_ctx": vram_split,
    }
    existing["_header"] = {
        "purpose": (
            "Per-model measured GPU budget for the local Ollama bridge (P4 Task 4, "
            "optimize_ollama.py --sweep). Every number under 'models' is measured on this "
            "machine at 'measured_at', never inferred from a model card or an issue claim."
        ),
        "written_by": "optimize_ollama.py --sweep",
    }

    payload = json.dumps(existing, indent=2, ensure_ascii=False) + "\n"
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = CONFIG_PATH.with_name(CONFIG_PATH.name + ".tmp")
    tmp_path.write_text(payload, encoding="utf-8")
    os.replace(tmp_path, CONFIG_PATH)


def cmd_sweep(
    tag: str,
    prompt: str,
    num_predict: int = RESPONSE_RESERVE_TOKENS,
    kv_cache_type_label: str | None = None,
) -> int:
    """
    --------------------------------------------------------------------------
    Purpose:
        Implement --sweep <tag>: climb CONTEXT_LADDER, stop at the first
        rejected rung, keep the last accepted one, isolate its weight/KV
        split, and write local-model-config.json.

    Inputs:
        tag (str): the model tag to sweep.
        prompt (str): the prompt used for every timed run (same prompt at
            every rung, so the comparison is apples to apples).
        num_predict (int): the reply-length cap for every timed run.
        kv_cache_type_label (str | None): the --kv-cache-type-label CLI
            value, or None; resolved via resolve_kv_cache_type_label before
            being written to the config (see that function's docstring for
            why this cannot be read reliably from this process's own
            environment alone).

    Outputs:
        result (int): 0 on success.

    Raises:
        OptimizeError: not even the first rung on the ladder was accepted, or
        any measurement step failed.
    --------------------------------------------------------------------------
    """
    card = detect_card()
    logger.info(
        "[OPTIMIZE] detected card: %s, %d MiB total, driver %s",
        card["name"], card["memory_total_mib"], card["driver_version"],
    )

    records: list[dict[str, Any]] = []
    baseline_median_s: float | None = None
    last_accepted: dict[str, Any] | None = None

    for num_ctx in CONTEXT_LADDER:
        logger.info("[OPTIMIZE] sweeping num_ctx=%d for %s ...", num_ctx, tag)
        record = evaluate_rung(tag, num_ctx, prompt, num_predict, baseline_median_s)
        records.append(record)

        if not record["accepted"]:
            if record["clamped_by_model_maximum"]:
                logger.info(
                    "[OPTIMIZE] num_ctx=%d REJECTED (clamped by the model's own maximum: "
                    "the daemon reported CONTEXT %s, not %d); keeping num_ctx=%s",
                    num_ctx, record["observed_contexts"], num_ctx,
                    last_accepted["num_ctx"] if last_accepted else "none",
                )
                break
            logger.info(
                "[OPTIMIZE] num_ctx=%d REJECTED (min_gpu_percent=%d min_free_mib=%d "
                "median_s=%.3f regressed=%s); stopping the ladder, keeping num_ctx=%s.",
                num_ctx, record["min_gpu_percent"], record["min_free_mib"], record["median_s"],
                record["regressed_past_baseline"],
                last_accepted["num_ctx"] if last_accepted else "none",
            )
            break

        logger.info(
            "[OPTIMIZE] num_ctx=%d ACCEPTED (min_gpu_percent=%d min_free_mib=%d median_s=%.3f)",
            num_ctx, record["min_gpu_percent"], record["min_free_mib"], record["median_s"],
        )
        last_accepted = record
        if baseline_median_s is None:
            baseline_median_s = record["median_s"]

    if last_accepted is None:
        raise OptimizeError(
            f"[OPTIMIZE] no rung was accepted for {tag!r}, not even num_ctx={CONTEXT_LADDER[0]}; "
            "refusing to write a config with no retained window."
        )

    vram_split = isolate_weight_and_kv_cost(tag, last_accepted["num_ctx"])
    resolved_kv_label = resolve_kv_cache_type_label(kv_cache_type_label)
    write_config(tag, last_accepted, records, vram_split, card, resolved_kv_label)

    print(f"retained_num_ctx: {last_accepted['num_ctx']}")
    print(f"retained_median_s: {last_accepted['median_s']}")
    print(f"kv_cache_type: {resolved_kv_label}")
    print(f"weights_mib: {vram_split['weights_mib']}")
    print(f"kv_cache_mib_at_retained_num_ctx: {vram_split['kv_cache_mib_at_candidate']}")
    print(f"kv_cost_mib_per_1k_tokens: {vram_split['kv_cost_mib_per_1k_tokens']}")
    print(f"total_mib: {vram_split['total_mib']} of {card['memory_total_mib']} MiB")
    print(f"config_written_to: {CONFIG_PATH}")
    return 0


def build_arg_parser() -> argparse.ArgumentParser:
    """
    --------------------------------------------------------------------------
    Purpose:
        Build the CLI: exactly one of --detect, --sweep TAG.

    Inputs:
        none.

    Outputs:
        result (argparse.ArgumentParser): the configured parser.
    --------------------------------------------------------------------------
    """
    parser = argparse.ArgumentParser(
        description="Measure-first GPU budget tuner for the local Ollama bridge (P4 Task 4). "
                     "Every number comes from nvidia-smi, 'ollama ps', or a timed HTTP call - "
                     "never inferred or copied from a model card."
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--detect", action="store_true", help="print card model, total VRAM, driver version")
    group.add_argument("--sweep", type=str, metavar="TAG", help="sweep the context ladder for TAG")
    parser.add_argument(
        "--prompt-file", type=Path, default=None, dest="prompt_file",
        help="prompt file used for every timed run in --sweep (default: a short built-in "
             "English prompt; pass the same file used for the baseline median in "
             "p4-measurements.md to keep the two comparable)",
    )
    parser.add_argument(
        "--num-predict", type=int, default=DEFAULT_NUM_PREDICT, dest="num_predict",
        help=f"reply-length cap for every timed run in --sweep (default {DEFAULT_NUM_PREDICT})",
    )
    parser.add_argument(
        "--kv-cache-type-label", type=str, default=None, dest="kv_cache_type_label",
        help="the OLLAMA_KV_CACHE_TYPE value actually active on the DAEMON for this --sweep "
             "run, verified by the caller from the daemon's own server.log 'server config' "
             "line - this script's own process environment does not reliably reflect the "
             "daemon's (see resolve_kv_cache_type_label). Recorded verbatim in "
             "local-model-config.json; omit only when this process's own OLLAMA_KV_CACHE_TYPE "
             "is known to match the daemon's.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """
    --------------------------------------------------------------------------
    Purpose:
        CLI entry point.

    Inputs:
        argv (list[str] | None): argument vector (defaults to sys.argv[1:]).

    Outputs:
        result (int): process exit code.
    --------------------------------------------------------------------------
    """
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    try:
        if args.detect:
            return cmd_detect()
        if args.sweep:
            prompt = (
                args.prompt_file.read_text(encoding="utf-8")
                if args.prompt_file is not None
                else DEFAULT_SWEEP_PROMPT
            )
            return cmd_sweep(args.sweep, prompt, args.num_predict, args.kv_cache_type_label)
    except OptimizeError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 1


if __name__ == "__main__":
    sys.exit(main())
