"""The benchmark CLI and its orchestration, offline: no model, no GPU, no Ollama, no child.

Every external effect goes through an injected Deps, so the refusals (R12 exit 2), the
dry run that writes nothing (R16), the child that fails or hangs ("not runnable", never a
score), and the measurement ORDER inside a child are all asserted without a process.
The order matters: the LLM is warmed before Whisper loads, so the gate reads what Whisper
pushes out rather than what an earlier run left demoted (measured 2026-09-26, the LLM read
3981 MiB of 5380 before any warm-up).
"""
import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import bench_config  # noqa: E402
import engines  # noqa: E402
import stt_bench  # noqa: E402

FIXTURE = json.loads((Path(__file__).resolve().parent / "fixtures" / "session_2026_09_26.json")
                     .read_text(encoding="utf-8"))
CONFIG = bench_config.load_config()


def reference_dir(tmp: Path, lines=None, files=("a.wav", "b.wav")) -> Path:
    for name in files:
        (tmp / name).write_bytes(b"RIFF")
    ref = tmp / "reference.txt"
    ref.write_text("\n".join(lines or ["# the operator's words", "a.wav | un deux trois",
                                       "b.wav | quatre"]), encoding="utf-8")
    return ref


class FakeEngine:
    def __init__(self, log, fail_on=None):
        self.log, self.fail_on = log, fail_on

    def available(self):
        return True, ""

    def download(self, model):
        self.log.append("download")

    def load(self, model, compute_type, device):
        self.log.append("load")
        if self.fail_on == "load":
            raise RuntimeError("CUDA out of memory")
        return object()

    def transcribe(self, handle, audio_path, language, options):
        self.log.append("transcribe")
        return "un deux trois"


def fake_deps(log=None, engine=None, rows=None, llm_pid=4242):
    log = log if log is not None else []
    rows = rows if rows is not None else [dict(r) for r in FIXTURE["candidates"]]

    def child_runner(job, timeout_s):
        for r in rows:
            if r["model"] == job["candidate"]["model"]:
                return dict(r, audio_s=FIXTURE["audio_s"])
        return {"model": job["candidate"]["model"], "error": "no fixture row"}

    return stt_bench.Deps(
        resolve_llm=lambda role: "writer-tag",
        ollama_up=lambda: True,
        find_llm_pid=lambda names: llm_pid,
        memory=lambda pid: (log.append("mem_%s" % ("llm" if pid == llm_pid else "self"))
                            or {"dedicated_mib": 5000, "shared_mib": 0}),
        llm_call=lambda tag: (log.append("llm_call") or {"total_s": 2.5, "prompt_s": 0.3, "tps": 28.0}),
        get_engine=lambda name: engine or FakeEngine(log),
        child_runner=child_runner,
        duration_s=lambda path: 1.0,
        pid=lambda: 7,
        other_gpu=lambda exclude: {},
    )


def run_main(argv, deps):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = stt_bench.main(argv, deps=deps)
    return code, out.getvalue(), err.getvalue()


class ParseCase(unittest.TestCase):
    def test_candidates_need_a_compute_type(self):
        self.assertEqual(stt_bench.parse_candidates(["small:float16"], "faster-whisper", CONFIG),
                         [{"engine": "faster-whisper", "model": "small", "compute_type": "float16"}])
        with self.assertRaises(stt_bench.Refusal) as ctx:
            stt_bench.parse_candidates(["small"], "faster-whisper", CONFIG)
        self.assertIn("small:float16", str(ctx.exception))

    def test_no_model_means_the_configured_defaults(self):
        got = stt_bench.parse_candidates([], "faster-whisper", CONFIG)
        self.assertEqual([c["model"] for c in got],
                         ["small", "medium", "large-v3-turbo", "large-v3"])

    def test_the_reference_is_read_and_its_audio_resolved(self):
        with tempfile.TemporaryDirectory() as t:
            refs, files = stt_bench.parse_reference(reference_dir(Path(t)))
        self.assertEqual(refs, {"a.wav": "un deux trois", "b.wav": "quatre"})
        self.assertEqual([p.name for p in files.values()], ["a.wav", "b.wav"])

    def test_missing_audio_is_refused_by_name(self):
        with tempfile.TemporaryDirectory() as t:
            ref = reference_dir(Path(t), files=("a.wav",))
            with self.assertRaises(stt_bench.Refusal) as ctx:
                stt_bench.parse_reference(ref)
        self.assertIn("b.wav", str(ctx.exception))

    def test_an_audio_path_leaving_the_reference_folder_is_refused(self):
        with tempfile.TemporaryDirectory() as t:
            ref = reference_dir(Path(t), lines=["../x.wav | un"])
            with self.assertRaises(stt_bench.Refusal) as ctx:
                stt_bench.parse_reference(ref)
        self.assertIn("outside", str(ctx.exception))

    def test_an_empty_reference_is_refused(self):
        with tempfile.TemporaryDirectory() as t:
            with self.assertRaises(stt_bench.Refusal):
                stt_bench.parse_reference(reference_dir(Path(t), lines=["# nothing"]))


class ChildCase(unittest.TestCase):
    def test_the_llm_is_warmed_before_whisper_loads_and_read_after(self):
        log = []
        with tempfile.TemporaryDirectory() as t:
            _, files = stt_bench.parse_reference(reference_dir(Path(t)))
            job = stt_bench.make_job({"engine": "faster-whisper", "model": "small",
                                      "compute_type": "float16"}, files, "fr", "writer-tag", 4242)
            row = stt_bench.measure_candidate(job, CONFIG, fake_deps(log))
        self.assertEqual(log[:4], ["llm_call", "mem_llm", "download", "load"])
        self.assertEqual(log[-3:], ["mem_self", "mem_llm", "llm_call"])
        self.assertEqual(row["files"]["a.wav"]["text"], "un deux trois")
        self.assertEqual(set(row["memory"]), {"dedicated_mib", "shared_mib",
                                              "llm_dedicated_before_mib", "llm_dedicated_after_mib"})

    def test_a_failing_load_becomes_an_error_row(self):
        log = []
        with tempfile.TemporaryDirectory() as t:
            _, files = stt_bench.parse_reference(reference_dir(Path(t)))
            job = stt_bench.make_job({"engine": "faster-whisper", "model": "big",
                                      "compute_type": "int8"}, files, "fr", "writer-tag", 4242)
            row = stt_bench.measure_candidate(job, CONFIG, fake_deps(log, FakeEngine(log, "load")))
        self.assertIn("CUDA out of memory", row["error"])
        self.assertNotIn("files", row)

    def test_a_hung_or_silent_child_is_an_error_not_a_score(self):
        def hung(argv, **kw):
            raise subprocess.TimeoutExpired(argv, 5)

        def silent(argv, **kw):
            return subprocess.CompletedProcess(argv, 1, stdout="", stderr="Traceback ...\nBoom")
        job = {"candidate": {"engine": "faster-whisper", "model": "x", "compute_type": "int8"}}
        self.assertIn("timed out after 5",
                      stt_bench.spawn_child(job, 5, runner=hung)["error"])
        self.assertIn("Boom", stt_bench.spawn_child(job, 5, runner=silent)["error"])


class MainCase(unittest.TestCase):
    def test_dry_run_writes_nothing(self):
        with tempfile.TemporaryDirectory() as t:
            ref = reference_dir(Path(t))
            out = Path(t) / "report"
            code, stdout, _ = run_main(["--reference", str(ref), "--out", str(out),
                                        "--model", "small:float16", "--dry-run"], fake_deps())
            self.assertEqual(code, 0)
            self.assertFalse(out.exists())
        self.assertIn("small float16", stdout)

    def test_an_unavailable_engine_is_a_refusal(self):
        deps = fake_deps()

        def missing(name):
            raise engines.EngineUnavailable("faster-whisper: not installed")
        deps.get_engine = missing
        with tempfile.TemporaryDirectory() as t:
            code, _, err = run_main(["--reference", str(reference_dir(Path(t))),
                                     "--out", str(Path(t) / "r")], deps)
        self.assertEqual(code, 2)
        self.assertIn("not installed", err)

    def test_no_reference_is_a_refusal(self):
        code, _, err = run_main(["--out", "x"], fake_deps())
        self.assertEqual(code, 2)
        self.assertIn("--reference", err)

    def test_a_full_run_writes_the_three_files_and_names_what_to_edit(self):
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            lines = [f"{n} | {txt}" for n, txt in FIXTURE["reference"].items()]
            ref = reference_dir(tmp, lines=lines, files=tuple(FIXTURE["reference"]))
            out = tmp / "report"
            code, stdout, _ = run_main(["--reference", str(ref), "--out", str(out)], fake_deps())
            self.assertEqual(code, 0)
            self.assertEqual(sorted(p.name for p in out.iterdir()),
                             ["stt_bench_raw.json", "stt_bench_report.json", "stt_bench_table.md"])
            report = json.loads((out / "stt_bench_report.json").read_text(encoding="utf-8"))
        self.assertEqual(report["winner"]["model"], "large-v3-turbo")
        self.assertIn("voice.stt.model_size", stdout)

    def test_another_process_on_the_gpu_is_named_not_silently_measured_beside(self):
        deps = fake_deps()
        deps.other_gpu = lambda exclude: {13944: 929, 31568: 27}
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            lines = [f"{n} | {txt}" for n, txt in FIXTURE["reference"].items()]
            ref = reference_dir(tmp, lines=lines, files=tuple(FIXTURE["reference"]))
            code, stdout, err = run_main(["--reference", str(ref), "--out", str(tmp / "r")], deps)
            report = json.loads((tmp / "r" / "stt_bench_report.json").read_text(encoding="utf-8"))
        self.assertEqual(code, 0)
        self.assertEqual(report["other_gpu_processes"], {"13944": 929})
        self.assertIn("13944", err)
        self.assertIn("13944", stdout)
        self.assertNotIn("31568", err)

    def test_rescore_recomputes_without_running_a_model(self):
        deps = fake_deps()
        deps.child_runner = lambda job, timeout_s: self.fail("rescore must not run a model")
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            lines = [f"{n} | {txt}" for n, txt in FIXTURE["reference"].items()]
            ref = reference_dir(tmp, lines=lines, files=tuple(FIXTURE["reference"]))
            raw = tmp / "stt_bench_raw.json"
            raw.write_text(json.dumps({k: v for k, v in FIXTURE.items() if k != "reference"}),
                           encoding="utf-8")
            code, stdout, _ = run_main(["--rescore", str(raw), "--reference", str(ref),
                                        "--out", str(tmp / "again")], deps)
            self.assertEqual(code, 0)
            self.assertTrue((tmp / "again" / "stt_bench_table.md").exists())
        self.assertIn("large-v3-turbo", stdout)


if __name__ == "__main__":
    unittest.main()
