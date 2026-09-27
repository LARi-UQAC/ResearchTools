#!/usr/bin/env python3
"""
stt_bench.py - benchmark speech-to-text models beside the resident local LLM, all on VRAM.

The opt-local-stt-vram driver. For each candidate, in its OWN child process (a candidate
measured after another in one process inherits its reserved CUDA memory, measured
2026-09-26): warm the LLM back to full residency, download the model (untimed), load it,
transcribe every reference recording RUNS times, read where both processes' memory now
lives, and time the LLM's next answer. Then score against the operator's reference text
(stt_score.py) and write one selection table.

It measures and reports; it never adopts. Switching the voice panel's model stays a human
edit of rt-observe's observe-config.json, printed at the end, exactly as tune-new-model.ps1
stops before --qualify.

Exit codes (R12): 0 report written (or dry run printed), 2 refusal by design (no reference,
missing audio, engine not installed, no LLM, Ollama down), 1 failure.
"""
import argparse
import json
import os
import statistics
import subprocess
import sys
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

SCRIPTS = Path(__file__).resolve().parent
LOOP_SCRIPTS = SCRIPTS.parents[1] / "loop-engineer" / "scripts"
for _p in (SCRIPTS, LOOP_SCRIPTS):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import bench_config  # noqa: E402
import engines  # noqa: E402
import gpu_memory  # noqa: E402
import stt_score  # noqa: E402
from bench_config import value  # noqa: E402

RAW, REPORT, TABLE = "stt_bench_raw.json", "stt_bench_report.json", "stt_bench_table.md"


class Refusal(RuntimeError):
    """A refusal by design (exit 2): the message says what to supply or fix."""


@dataclass
class Deps:
    """Every effect the benchmark has on the machine, injectable for the offline suite."""
    resolve_llm: Callable
    ollama_up: Callable
    find_llm_pid: Callable
    memory: Callable
    llm_call: Callable
    get_engine: Callable
    child_runner: Callable
    duration_s: Callable
    pid: Callable
    other_gpu: Callable


def default_deps(config: dict) -> Deps:
    """
    --------------------------------------------------------------------------
    Purpose:
        The real implementations: model_resolver for the LLM tag, Ollama's
        HTTP API, the per-process GPU counters, the engine registry, a child
        process per candidate.

    Inputs:
        config (dict): parsed stt-bench-config.json

    Outputs:
        deps (Deps): the live dependencies
    --------------------------------------------------------------------------
    """
    import model_resolver
    from ollama_bridge import OLLAMA_HOST
    t_llm, t_gpu = value(config, "timeouts_s", "llm_call"), value(config, "timeouts_s", "gpu_counter")

    def ollama_up():
        try:
            urllib.request.urlopen(OLLAMA_HOST + "/api/ps", timeout=t_gpu).read()
            return True
        except OSError:
            return False

    def llm_call(tag):
        body = json.dumps({"model": tag, "prompt": value(config, "llm", "probe_prompt"),
                           "stream": False,
                           "options": {"num_predict": value(config, "llm", "probe_tokens")}})
        req = urllib.request.Request(OLLAMA_HOST + "/api/generate", data=body.encode(),
                                     headers={"Content-Type": "application/json"})
        d = json.loads(urllib.request.urlopen(req, timeout=t_llm).read())
        return {"total_s": round(d["total_duration"] / 1e9, 2),
                "prompt_s": round(d["prompt_eval_duration"] / 1e9, 2),
                "tps": round(d["eval_count"] / (d["eval_duration"] / 1e9), 1)}

    def duration_s(path):
        from faster_whisper import decode_audio
        return len(decode_audio(str(path))) / 16000

    return Deps(
        resolve_llm=model_resolver.resolve,
        ollama_up=ollama_up,
        find_llm_pid=lambda names: gpu_memory.find_llm_pid(names, timeout_s=t_gpu),
        memory=lambda pid: gpu_memory.process_memory_mib(pid, timeout_s=t_gpu),
        llm_call=llm_call,
        get_engine=lambda name: engines.get_engine(name, config),
        child_runner=spawn_child,
        duration_s=duration_s,
        pid=os.getpid,
        other_gpu=lambda exclude: gpu_memory.other_gpu_processes(exclude, timeout_s=t_gpu),
    )


def _others(deps: Deps, llm_pid: int, config: dict) -> dict:
    """
    --------------------------------------------------------------------------
    Purpose:
        The other processes holding enough VRAM to change the measurement.

    Inputs:
        deps (Deps): the effects
        llm_pid (int): the LLM's process, which belongs to the measurement
        config (dict): parsed stt-bench-config.json (other_process_warn_mib)

    Outputs:
        others (dict[str, int] | None): pid (as text, JSON's key type) -> MiB,
        or None when the card cannot be read (said on stderr, never guessed)
    --------------------------------------------------------------------------
    """
    floor = value(config, "other_process_warn_mib")
    try:
        found = deps.other_gpu([llm_pid])
    except gpu_memory.GpuMemoryUnavailable as exc:
        print(f"[STT-BENCH] cannot list other GPU processes: {exc}", file=sys.stderr)
        return None
    others = {str(pid): mib for pid, mib in sorted(found.items()) if mib >= floor}
    for pid, mib in others.items():
        print(f"[STT-BENCH] WARNING: process {pid} holds {mib} MiB of VRAM; every candidate "
              "is measured beside it. Close it (a dashboard with Whisper loaded, for "
              "instance) for a clean measurement.", file=sys.stderr, flush=True)
    return others


def parse_candidates(specs: list, engine: str, config: dict) -> list:
    """
    --------------------------------------------------------------------------
    Purpose:
        Turn --model NAME:COMPUTE arguments into candidate records.

    Inputs:
        specs (list[str]): the --model values; empty means the configured defaults
        engine (str): the engine every candidate runs on
        config (dict): parsed stt-bench-config.json

    Outputs:
        candidates (list[dict]): engine, model, compute_type

    Raises:
        Refusal: a spec carries no compute type (never guessed, R3).
    --------------------------------------------------------------------------
    """
    out = []
    for spec in specs or value(config, "default_candidates"):
        model, _, compute = spec.partition(":")
        if not model or not compute:
            raise Refusal(f"'{spec}' names no compute type; write it as NAME:COMPUTE, "
                          f"e.g. {model or 'small'}:float16")
        out.append({"engine": engine, "model": model, "compute_type": compute})
    return out


def parse_reference(path) -> tuple:
    """
    --------------------------------------------------------------------------
    Purpose:
        Read the operator's reference: one 'audio-file | exact words' per line.

    Details:
        Audio paths resolve relative to the reference file and must stay
        inside its folder (R24: resolved first, then compared, never clamped).

    Inputs:
        path (str | Path): the reference file

    Outputs:
        (reference, files) (tuple[dict, dict]): name -> words, name -> Path

    Raises:
        Refusal: file missing, no entry, audio missing, or a path outside.
    --------------------------------------------------------------------------
    """
    ref_path = Path(path)
    if not ref_path.is_file():
        raise Refusal(f"reference file not found: {ref_path}")
    root = ref_path.resolve().parent
    reference, files = {}, {}
    for line in ref_path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.lstrip().startswith("#") or "|" not in line:
            continue
        name, words = (s.strip() for s in line.split("|", 1))
        audio = (root / name).resolve()
        if root not in audio.parents:
            raise Refusal(f"'{name}' resolves outside the reference folder {root}")
        if not audio.is_file():
            raise Refusal(f"audio file '{name}' named in {ref_path.name} does not exist")
        reference[name], files[name] = words, audio
    if not reference:
        raise Refusal(f"{ref_path} holds no 'audio-file | exact words' line")
    return reference, files


def make_job(candidate: dict, files: dict, language: str, llm_tag: str, llm_pid: int) -> dict:
    """Purpose: the JSON a child receives - one candidate and everything it must measure."""
    return {"candidate": candidate, "files": {n: str(p) for n, p in files.items()},
            "language": language, "llm_tag": llm_tag, "llm_pid": llm_pid}


def measure_candidate(job: dict, config: dict, deps: Deps) -> dict:
    """
    --------------------------------------------------------------------------
    Purpose:
        Measure one candidate beside the resident LLM (runs inside the child).

    Details:
        Order is the measurement: warm the LLM and read its residency, download
        (untimed), load (timed), first call (timed apart: it pays CUDA init),
        RUNS transcriptions per recording, then read both processes' memory and
        time the LLM's next answer.

    Inputs:
        job (dict): from make_job
        config (dict): parsed stt-bench-config.json
        deps (Deps): the effects

    Outputs:
        row (dict): the measurement, or the candidate with an "error" field
    --------------------------------------------------------------------------
    """
    cand = job["candidate"]
    row = dict(cand)
    options = {k: value(config, "transcribe", k)
               for k in ("vad_filter", "vad_min_silence_ms", "condition_on_previous_text")}
    try:
        adapter = deps.get_engine(cand["engine"])
        deps.llm_call(job["llm_tag"])
        llm_before = deps.memory(job["llm_pid"])["dedicated_mib"]
        t = time.perf_counter()
        adapter.download(cand["model"])
        row["download_s"] = round(time.perf_counter() - t, 1)
        t = time.perf_counter()
        handle = adapter.load(cand["model"], cand["compute_type"], value(config, "device"))
        row["load_s"] = round(time.perf_counter() - t, 1)
        first = next(iter(job["files"].values()))
        t = time.perf_counter()
        adapter.transcribe(handle, first, job["language"], options)
        row["first_call_s"] = round(time.perf_counter() - t, 2)
        row["files"] = {}
        for name, path in job["files"].items():
            times, text = [], ""
            for _ in range(value(config, "runs_per_file")):
                t = time.perf_counter()
                text = adapter.transcribe(handle, path, job["language"], options)
                times.append(time.perf_counter() - t)
            med = statistics.median(times)
            row["files"][name] = {"median_s": round(med, 2),
                                  "rtf": round(med / deps.duration_s(path), 3), "text": text}
        own = deps.memory(deps.pid())
        row["memory"] = {"dedicated_mib": own["dedicated_mib"], "shared_mib": own["shared_mib"],
                         "llm_dedicated_before_mib": llm_before,
                         "llm_dedicated_after_mib": deps.memory(job["llm_pid"])["dedicated_mib"]}
        row["llm_answer_after"] = deps.llm_call(job["llm_tag"])
    except Exception as exc:  # noqa: BLE001 - any failure makes this candidate not runnable
        return dict(cand, error=f"{type(exc).__name__}: {exc}")
    return row


def spawn_child(job: dict, timeout_s: float, runner=subprocess.run) -> dict:
    """
    --------------------------------------------------------------------------
    Purpose:
        Measure one candidate in a fresh process and return its row.

    Inputs:
        job (dict): from make_job
        timeout_s (float): bound on the whole child, download included (R10)
        runner (callable): subprocess.run, injected by the suite

    Outputs:
        row (dict): the child's row, or the candidate with an "error" naming
        the timeout or the END of the child's stderr (where a traceback names
        its exception)
    --------------------------------------------------------------------------
    """
    argv = [sys.executable, str(Path(__file__).resolve()), "--one", json.dumps(job)]
    try:
        out = runner(argv, capture_output=True, text=True, encoding="utf-8", errors="replace",
                     timeout=timeout_s)
    except subprocess.TimeoutExpired:
        return dict(job["candidate"], error=f"timed out after {timeout_s} s")
    rows = [ln[4:] for ln in (out.stdout or "").splitlines() if ln.startswith("ROW ")]
    if rows:
        return json.loads(rows[-1])
    return dict(job["candidate"],
                error=f"child exit {out.returncode}: {(out.stderr or '').strip()[-400:]}")


def _finish(raw: dict, reference: dict, config: dict, out_dir: Path, as_json: bool) -> int:
    scored = stt_score.score_report(raw, reference, config)
    winner = next((r for r in scored if r["status"] == "ranked"), None)
    table = stt_score.render_table(scored)
    report = {"llm": raw.get("llm"), "language": raw.get("language"), "winner": winner,
              "other_gpu_processes": raw.get("other_gpu_processes"), "rows": scored,
              "rule": {"live_budget_ms": value(config, "live_budget_ms"),
                       "max_llm_demoted_pct": value(config, "gate", "max_llm_demoted_pct"),
                       "weights": {"accuracy": value(config, "weights", "accuracy"),
                                   "speed": value(config, "weights", "speed")}}}
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / REPORT).write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    (out_dir / TABLE).write_text(table + "\n", encoding="utf-8")
    if as_json:
        print(json.dumps(report, ensure_ascii=False, indent=1))
        return 0
    print(table)
    for pid, mib in (raw.get("other_gpu_processes") or {}).items():
        print(f"\nNote: measured beside process {pid}, which held {mib} MiB of VRAM - "
              "rerun with it closed for a clean result.")
    if winner:
        print(f"\nBest: {winner['model']} {winner['compute_type']} (score {winner['score']:.1f}). "
              "To adopt it - a human edit, this skill never adopts - set in "
              ".claude/skills/rt-observe/observe-config.json voice.stt.model_size = "
              f"\"{winner['model']}\" and voice.stt.compute_type = \"{winner['compute_type']}\", "
              "then restart the dashboard.")
    else:
        print("\nNo candidate passed the VRAM gate: nothing to adopt on this card.")
    return 0


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Benchmark STT models beside the resident LLM.")
    p.add_argument("--model", action="append", default=[], metavar="NAME:COMPUTE")
    p.add_argument("--engine")
    p.add_argument("--reference", help="file of 'audio-file | exact words' lines")
    p.add_argument("--language", choices=("auto", "en", "fr"))
    p.add_argument("--out", help="report directory")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--rescore", metavar="RAW_JSON")
    p.add_argument("--json", action="store_true")
    p.add_argument("--config", default=str(bench_config.CONFIG_PATH))
    p.add_argument("--one", help=argparse.SUPPRESS)
    return p


def main(argv=None, deps: Deps = None) -> int:
    """
    --------------------------------------------------------------------------
    Purpose:
        CLI entry: dry run, full benchmark, rescore, or (internal) one child.

    Inputs:
        argv (list[str] | None): arguments; None reads sys.argv
        deps (Deps | None): injected effects; None builds the live ones

    Outputs:
        code (int): 0 done, 2 refusal by design, 1 failure (R12). Side effects:
        the three report files under --out, nothing else.
    --------------------------------------------------------------------------
    """
    args = _parser().parse_args(argv)
    try:
        config = bench_config.load_config(Path(args.config))
        if args.one:
            row = measure_candidate(json.loads(args.one), config, deps or default_deps(config))
            print("ROW " + json.dumps(row, ensure_ascii=False), flush=True)
            return 0
        if not args.reference:
            raise Refusal("--reference FILE is required: one 'audio-file | exact words' line "
                          "per recording, in YOUR words (a model's own output rigs the score)")
        reference, files = parse_reference(args.reference)
        if not args.out and not args.dry_run:
            raise Refusal("--out DIR is required: where the three report files go")
        if args.rescore:
            raw = json.loads(Path(args.rescore).read_text(encoding="utf-8"))
            return _finish(raw, reference, config, Path(args.out), args.json)
        deps = deps or default_deps(config)
        engine = args.engine or value(config, "default_engine")
        candidates = parse_candidates(args.model, engine, config)
        try:
            deps.get_engine(engine)
        except engines.EngineUnavailable as exc:
            raise Refusal(str(exc)) from None
        role = value(config, "llm", "role")
        try:
            tag = deps.resolve_llm(role)
        except Exception as exc:  # noqa: BLE001 - the resolver refuses by raising
            raise Refusal(f"no qualified {role}-role model to measure beside: {exc}") from None
        if not deps.ollama_up():
            raise Refusal("Ollama does not answer; start it before benchmarking beside the LLM")
        language = args.language or value(config, "language")
        names = value(config, "llm", "process_names")
        if args.dry_run:
            try:
                where = f"pid {deps.find_llm_pid(names)}"
            except gpu_memory.GpuMemoryUnavailable:
                where = "not resident yet (the run loads it first)"
            print(f"dry run - nothing downloaded, measured or written\n"
                  f"  engine     {engine}\n  LLM        {tag} ({where})\n  language   {language}")
            for c in candidates:
                print(f"  candidate  {c['model']} {c['compute_type']} (downloaded if not cached)")
            for name in files:
                print(f"  recording  {name}")
            print(f"  would write {Path(args.out or '<--out>') / RAW}, {REPORT}, {TABLE}")
            return 0
        deps.llm_call(tag)
        try:
            llm_pid = deps.find_llm_pid(names)
        except gpu_memory.GpuMemoryUnavailable as exc:
            raise Refusal(str(exc)) from None
        raw = {"engine": engine, "llm": tag, "language": language,
               "runs": value(config, "runs_per_file"),
               "other_gpu_processes": _others(deps, llm_pid, config),
               "audio_s": {n: round(deps.duration_s(p), 2) for n, p in files.items()},
               "llm_alone": {"dedicated_mib": deps.memory(llm_pid)["dedicated_mib"],
                             "answer": deps.llm_call(tag)},
               "candidates": []}
        timeout = value(config, "timeouts_s", "child")
        for c in candidates:
            print(f"[STT-BENCH] measuring {c['model']} {c['compute_type']} ...",
                  file=sys.stderr, flush=True)
            raw["candidates"].append(deps.child_runner(make_job(c, files, language, tag, llm_pid),
                                                       timeout))
        out_dir = Path(args.out)
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / RAW).write_text(json.dumps(raw, ensure_ascii=False, indent=1), encoding="utf-8")
        return _finish(raw, reference, config, out_dir, args.json)
    except Refusal as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
    except (KeyError, ValueError, OSError) as exc:
        print(f"FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    sys.exit(main())
