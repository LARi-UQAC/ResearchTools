"""
Offline tests for aider-thread-probe.py. No daemon, no GPU, no model load and
no network: every effect is injected, so this suite runs on a machine that has
never installed Ollama.

The cases that matter here are the negative ones. A thread sweep is unusually
easy to get wrong in a way that still prints a plausible table:

  - Ollama may IGNORE options.num_thread. Every rung then runs identically and
    the table reads "threads do not matter" when it in fact measured one
    configuration eight times.
  - A num_ctx the daemon cannot place is CLAMPED and reported as success, so
    two rungs silently describe different windows.
  - A counter that is unavailable must say so with its reason. A zero page-in
    rate and an unmeasured page-in rate lead to opposite conclusions.

Configuration is a fixture rather than the shipped JSON (R21): the shipped file
names this machine's CPU thread counts and its installed model tag, so a test
reading it would pass only here. One test does read the shipped file, and only
to assert it declares the keys the script requires.
"""

import importlib.util
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

HERE = pathlib.Path(__file__).resolve().parent
BIN = HERE.parent
SCRIPT = BIN / "aider-thread-probe.py"
PROBE = BIN / "aider-gpu-probe.py"
SHIPPED_CONFIG = BIN / "aider-thread-probe.json"


def load_by_path(path: pathlib.Path, name: str):
    """Both files carry hyphens and cannot be imported by name."""
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


tp = load_by_path(SCRIPT, "aider_thread_probe_under_test")
probe = load_by_path(PROBE, "aider_gpu_probe_for_test")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def fixture_config() -> dict:
    return {
        "ollama": {"host": "http://127.0.0.1:11434", "connect_timeout_s": 1,
                   "load_timeout_s": 5, "decode_timeout_s": 5, "show_timeout_s": 1,
                   "keep_alive": "5m", "think": False,
                   "evict_poll_interval_s": 0, "evict_timeout_s": 1,
                   "post_evict_settle_s": 0},
        "server_log": {"candidate_paths": [], "read_delay_s": 0,
                       "max_tail_bytes": 4000},
        "log_patterns": {
            "offload": [r"load_tensors:\s+offloaded\s+(\d+)/(\d+)\s+layers to GPU"],
            "kv_cache_mib": [r"llama_kv_cache:\s*size\s*=\s*([0-9.]+)\s*MiB"],
            "compute_buffer_pool": [
                r"sched_reserve:\s*(\S+) compute buffer size\s*=\s*([0-9.]+)\s*MiB"],
            "n_threads": [r"n_threads\s*=\s*(\d+)"],
            "n_ctx": [r"llama_context:\s*n_ctx\s*=\s*(\d+)"],
            "kv_cache_type": [r"OLLAMA_KV_CACHE_TYPE:([^\s\]]+)"],
            "fit_attempt": [
                r"common_params_fit_impl:\s*id=\d+,\s*n_layer=\s*(\d+),"
                r"[^\n]*?mem=\s*(\d+)\s*MiB"],
        },
        "log_selection": {"kv_cache_mib": "sum", "compute_buffer_mib": "split",
                          "host_pool_patterns": ["(?i)host", "(?i)^cpu"]},
        "gpu": {"nvidia_smi": "nvidia-smi", "query_timeout_s": 1,
                "pcie_sample_interval_s": 1, "dmon_select": "ut"},
        "paging": {"enabled": True, "sample_interval_s": 1},
        "safety": {"min_free_ram_mib": 4096, "free_ram_reread_delay_s": 0},
        "sweep": {"model": "fixture-model:test", "num_ctx": 8192,
                  "threads": [4, 10], "repeats": 1,
                  "gpu_layers": [5, 8, 10], "gpu_sweep_num_thread": 14,
                  "gpu_stop_after_failures": 2},
        "measurement": {"warmup_prompt": "hi", "warmup_num_predict": 1,
                        "decode_prompt": "write", "decode_num_predict": 128},
        "bandwidth": {"workers": [1], "buffer_mib_per_worker": 2,
                      "seconds_per_point": 0.05},
        "report": {"float_places": 2},
    }


def fixture_log(n_threads: int = 10, n_ctx: int = 8192,
                offloaded: int = 5, total: int = 66) -> str:
    return "\n".join([
        "load_tensors: loading model tensors, this can take a while...",
        f"load_tensors: offloaded {offloaded}/{total} layers to GPU",
        "load_tensors:        CUDA0 model buffer size =  1949.85 MiB",
        "load_tensors:    CUDA_Host model buffer size = 14071.61 MiB",
        f"llama_context: n_ctx = {n_ctx}",
        "llama_kv_cache: size = 304.00 MiB (8192 cells, 66 layers, 1/1 seqs)",
        "sched_reserve: CUDA0 compute buffer size = 451.60 MiB",
        "sched_reserve: CUDA_Host compute buffer size = 174.90 MiB",
        f"cmn init: llama threadpool init, n_threads = {n_threads}",
    ])


class FakeDaemon:
    def __init__(self, log_text: str, decode_tps: float = 2.73,
                 fail_on: str = None):
        self.log_text = log_text
        self.decode_tps = decode_tps
        self.fail_on = fail_on
        self.calls = []

    def tags(self, timeout):
        return {"models": [{"name": "fixture-model:test"}]}

    def ps(self, timeout):
        return {"models": []}

    def generate(self, payload, timeout):
        self.calls.append(payload)
        predict = (payload.get("options") or {}).get("num_predict")
        if self.fail_on == "load" and predict == 1:
            raise TimeoutError("load timed out")
        if self.fail_on == "decode" and predict and predict > 1:
            raise TimeoutError("decode timed out")
        if predict == 1:
            return {"response": "hi"}
        return {"response": "text", "eval_count": 128,
                "eval_duration": int(128 / self.decode_tps * 1e9),
                "prompt_eval_count": 30, "prompt_eval_duration": int(30 / 6.7 * 1e9)}


class FakeLog:
    def __init__(self, text: str):
        self.text = text

    def offset(self):
        return 0

    def tail(self, offset):
        return self.text


class FakeSampler:
    def __init__(self, samples=None, reason=None):
        self.samples = samples or []
        self.reason = reason
        self.started = False
        self.stopped = False

    def start(self):
        self.started = True
        return self

    def stop(self):
        self.stopped = True
        return self


class FakeCpuSampler(FakeSampler):
    def __init__(self, cpu_pct=None, avail_phys=None, reason=None):
        super().__init__(reason=reason)
        self.cpu_pct = cpu_pct if cpu_pct is not None else [60.0, 70.0]
        self.avail_phys_mib = avail_phys if avail_phys is not None else [2000.0, 1534.0]
        self.avail_pagefile_mib = [10700.0]


def fake_deps(daemon, log, ram_mib=8192.0):
    return probe.Deps(daemon=daemon, log=log,
                      runner=lambda *a, **k: subprocess.CompletedProcess(
                          a[0] if a else [], 0, "3597, 6144", ""),
                      which=lambda name: None,
                      clock=lambda: 0.0,
                      sleeper=lambda seconds: None,
                      ram=lambda: (ram_mib, "fixture"))


def sampler_factory(cpu=None, pcie=None, pagein=None):
    zero_gpu = {"sm": 0.0, "mem": 0.0, "rxpci": 0.0, "txpci": 0.0}
    holder = {"cpu": cpu or FakeCpuSampler(),
              "pcie": pcie or FakeSampler([dict(zero_gpu), dict(zero_gpu)]),
              "pagein": pagein or FakeSampler([10615.0, 19023.0])}

    def build(cfg, origin, probe_module, deps):
        return holder["cpu"], holder["pcie"], holder["pagein"]

    build.holder = holder
    return build


# ---------------------------------------------------------------------------
# Refusals
# ---------------------------------------------------------------------------

class TestRefusals(unittest.TestCase):

    def test_absent_probe_is_refused_and_names_the_path(self):
        with tempfile.TemporaryDirectory() as scratch:
            missing = pathlib.Path(scratch) / "aider-gpu-probe.py"
            with self.assertRaises(tp.Refusal) as caught:
                tp.load_probe(missing)
            self.assertIn(str(missing), str(caught.exception))

    def test_absent_config_is_refused_and_names_the_path(self):
        with tempfile.TemporaryDirectory() as scratch:
            missing = pathlib.Path(scratch) / "nope.json"
            with self.assertRaises(tp.Refusal) as caught:
                tp.load_config(missing)
            self.assertIn(str(missing), str(caught.exception))

    def test_unparsable_config_is_refused_rather_than_half_read(self):
        with tempfile.TemporaryDirectory() as scratch:
            bad = pathlib.Path(scratch) / "bad.json"
            bad.write_text("{ not json", encoding="utf-8")
            with self.assertRaises(tp.Refusal):
                tp.load_config(bad)

    def test_a_tag_that_is_not_installed_is_refused_by_name(self):
        daemon = FakeDaemon(fixture_log())
        deps = fake_deps(daemon, FakeLog(fixture_log()))
        with self.assertRaises(tp.Refusal) as caught:
            tp.run_sweep(fixture_config(), "fixture", probe, deps,
                         threads=[10], model="absent-model:test")
        message = str(caught.exception)
        self.assertIn("absent-model:test", message)
        self.assertIn("fixture-model:test", message)


# ---------------------------------------------------------------------------
# The verification the script exists for
# ---------------------------------------------------------------------------

class TestThreadEffect(unittest.TestCase):

    def _row(self, requested, granted_in_log):
        log = fixture_log(n_threads=granted_in_log)
        daemon = FakeDaemon(log)
        return tp.sweep_one(fixture_config(), "fixture", probe,
                            fake_deps(daemon, FakeLog(log)),
                            requested, "fixture-model:test", 8192,
                            samplers=sampler_factory())

    def test_a_honoured_request_is_recorded_as_honoured(self):
        row = self._row(10, 10)
        self.assertEqual(row["thread_effect"], "honoured")
        self.assertEqual(row["num_thread_granted"], 10)
        self.assertEqual(row["status"], "ok")

    def test_an_ignored_request_is_named_and_carries_both_numbers(self):
        # The defect this whole column exists for: asked 16, ran 10. Without
        # this the row reports 10 threads' throughput as 16 threads' throughput.
        row = self._row(16, 10)
        self.assertIn("IGNORED", row["thread_effect"])
        self.assertIn("16", row["thread_effect"])
        self.assertIn("10", row["thread_effect"])

    def test_a_log_with_no_thread_line_is_unknown_and_not_assumed_honoured(self):
        log = fixture_log().replace("n_threads = 10", "n_threads_batch = 10")
        daemon = FakeDaemon(log)
        row = tp.sweep_one(fixture_config(), "fixture", probe,
                           fake_deps(daemon, FakeLog(log)), 16,
                           "fixture-model:test", 8192, samplers=sampler_factory())
        self.assertIsNone(row["num_thread_granted"])
        self.assertIn("unknown", row["thread_effect"])

    def test_the_ignored_effect_reaches_the_rendered_row(self):
        row = self._row(16, 10)
        self.assertIn("IGNORED", tp.render_sweep_row(row))

    def test_a_sweep_where_nothing_was_honoured_refuses_to_name_a_winner(self):
        rows = [self._row(16, 10), self._row(20, 10)]
        verdict = tp.render_sweep_verdict(rows)
        self.assertIn("NOT ONE", verdict)
        self.assertNotIn("fastest", verdict)


# ---------------------------------------------------------------------------
# Traps carried over from the GPU probe
# ---------------------------------------------------------------------------

class TestRungGuards(unittest.TestCase):

    def test_a_clamped_window_is_rejected_rather_than_recorded(self):
        log = fixture_log(n_ctx=17772)
        daemon = FakeDaemon(log)
        row = tp.sweep_one(fixture_config(), "fixture", probe,
                           fake_deps(daemon, FakeLog(log)), 10,
                           "fixture-model:test", 8192, samplers=sampler_factory())
        self.assertIn("rejected", row["status"])
        self.assertIn("17772", row["status"])
        self.assertIsNone(row["decode_tps"])

    def test_a_granted_window_that_matches_is_not_rejected(self):
        # Negative control: without it the assertion above passes on a guard
        # that rejects every rung.
        log = fixture_log(n_ctx=8192)
        daemon = FakeDaemon(log)
        row = tp.sweep_one(fixture_config(), "fixture", probe,
                           fake_deps(daemon, FakeLog(log)), 10,
                           "fixture-model:test", 8192, samplers=sampler_factory())
        self.assertEqual(row["status"], "ok")
        self.assertIsNotNone(row["decode_tps"])

    def test_below_the_free_ram_floor_the_rung_is_skipped_and_nothing_loads(self):
        log = fixture_log()
        daemon = FakeDaemon(log)
        row = tp.sweep_one(fixture_config(), "fixture", probe,
                           fake_deps(daemon, FakeLog(log), ram_mib=1024.0), 10,
                           "fixture-model:test", 8192, samplers=sampler_factory())
        self.assertIn("skipped", row["status"])
        # The eviction may generate, but no LOAD may have been attempted.
        loads = [c for c in daemon.calls if (c.get("options") or {})]
        self.assertEqual(loads, [])

    def test_a_failed_load_is_a_row_and_not_a_dead_sweep(self):
        log = fixture_log()
        daemon = FakeDaemon(log, fail_on="load")
        row = tp.sweep_one(fixture_config(), "fixture", probe,
                           fake_deps(daemon, FakeLog(log)), 10,
                           "fixture-model:test", 8192, samplers=sampler_factory())
        self.assertIn("load failed", row["status"])
        self.assertIn("TimeoutError", row["status"])

    def test_a_failed_decode_still_stops_every_sampler(self):
        log = fixture_log()
        daemon = FakeDaemon(log, fail_on="decode")
        factory = sampler_factory()
        row = tp.sweep_one(fixture_config(), "fixture", probe,
                           fake_deps(daemon, FakeLog(log)), 10,
                           "fixture-model:test", 8192, samplers=factory)
        self.assertIn("decode failed", row["status"])
        for name in ("cpu", "pcie", "pagein"):
            self.assertTrue(factory.holder[name].stopped,
                            f"{name} sampler was left running after a failed decode")


# ---------------------------------------------------------------------------
# Instrumentation
# ---------------------------------------------------------------------------

class TestSamplerParsing(unittest.TestCase):

    def _feed(self, select_header, *rows):
        parser = tp.DmonParser()
        self.assertIsNone(parser(select_header))
        return parser, [parser(row) for row in rows]

    def test_a_pcie_only_row_is_parsed_by_name(self):
        _, got = self._feed("# gpu  rxpci  txpci ",
                            "# Idx   MB/s   MB/s ",
                            "    0    123     45 ")
        self.assertEqual(got[-1], {"rxpci": 123.0, "txpci": 45.0})

    def test_the_utilization_header_remaps_every_column(self):
        # The defect a positional parser would have: with -s ut the first data
        # field is sm, not rxpci, so fixed positions report a busy GPU as bus
        # traffic. Verified against the real header, read 2026-09-05.
        _, got = self._feed(
            "# gpu     sm    mem    enc    dec    jpg    ofa  rxpci  txpci ",
            "# Idx      %      %      %      %      %      %   MB/s   MB/s ",
            "    0     37      9      0      0      0      0     12      3 ")
        row = got[-1]
        self.assertEqual(row["sm"], 37.0)
        self.assertEqual(row["mem"], 9.0)
        self.assertEqual(row["rxpci"], 12.0)
        self.assertEqual(row["txpci"], 3.0)

    def test_a_row_arriving_before_any_header_is_dropped(self):
        parser = tp.DmonParser()
        self.assertIsNone(parser("    0    123     45 "))

    def test_a_row_whose_width_disagrees_with_the_header_is_dropped(self):
        _, got = self._feed("# gpu  rxpci  txpci ", "    0    123 ")
        self.assertIsNone(got[-1])

    def test_an_unsupported_dmon_counter_is_dropped_not_read_as_zero(self):
        # '-' means the part does not report it. Zero would be a measurement.
        _, got = self._feed("# gpu  rxpci  txpci ", "    0      -      - ")
        self.assertIsNone(got[-1])

    def test_a_partially_unsupported_row_keeps_what_it_reported(self):
        _, got = self._feed("# gpu     sm  rxpci ", "    0     37      - ")
        self.assertEqual(got[-1], {"sm": 37.0})

    def test_a_zero_dmon_row_is_kept_because_zero_is_a_measurement(self):
        _, got = self._feed("# gpu  rxpci  txpci ", "    0      0      0 ")
        self.assertEqual(got[-1], {"rxpci": 0.0, "txpci": 0.0})

    def test_gpu_utilization_reaches_the_row_and_the_table(self):
        log = fixture_log()
        daemon = FakeDaemon(log)
        factory = sampler_factory(pcie=FakeSampler([
            {"sm": 30.0, "mem": 8.0, "rxpci": 0.0, "txpci": 0.0},
            {"sm": 50.0, "mem": 12.0, "rxpci": 1.0, "txpci": 0.0}]))
        row = tp.sweep_one(fixture_config(), "fixture", probe,
                           fake_deps(daemon, FakeLog(log)), 10,
                           "fixture-model:test", 8192, samplers=factory)
        self.assertEqual(row["gpu_sm_pct_mean"], 40.0)
        self.assertEqual(row["gpu_sm_pct_peak"], 50.0)
        self.assertEqual(row["gpu_mem_pct_mean"], 10.0)
        self.assertEqual(row["pcie_rx_mb_s_mean"], 0.5)
        self.assertIn("40.0", tp.render_sweep_row(row))
        self.assertIn("sm%", tp.render_sweep_header())

    def test_page_in_lines(self):
        self.assertEqual(tp._parse_pagein_line(" 10615 \n"), 10615.0)
        self.assertIsNone(tp._parse_pagein_line("\n"))
        self.assertIsNone(tp._parse_pagein_line("PagesInputPerSec\n"))

    def test_an_absent_nvidia_smi_disables_pcie_with_a_reason_and_no_argv(self):
        sampler = tp.pcie_sampler(fixture_config(), "fixture", probe,
                                  which=lambda name: None)
        self.assertIsNotNone(sampler.reason)
        self.assertIn("PATH", sampler.reason)
        self.assertEqual(sampler.argv, [])

    def test_pcie_sampler_invokes_the_resolved_path_not_the_bare_name(self):
        sampler = tp.pcie_sampler(fixture_config(), "fixture", probe,
                                  which=lambda name: r"C:\resolved\nvidia-smi.exe")
        self.assertEqual(sampler.argv[0], r"C:\resolved\nvidia-smi.exe")
        self.assertIn("dmon", sampler.argv)

    def test_paging_switched_off_in_config_is_a_stated_reason(self):
        cfg = fixture_config()
        cfg["paging"]["enabled"] = False
        sampler = tp.pagein_sampler(cfg, "fixture", probe, which=lambda n: "pwsh")
        self.assertIsNotNone(sampler.reason)
        self.assertEqual(sampler.argv, [])

    def test_an_unavailable_counter_is_reported_with_its_reason_not_as_zero(self):
        log = fixture_log()
        daemon = FakeDaemon(log)
        factory = sampler_factory(
            pcie=FakeSampler([], reason="nvidia-smi is not on PATH"),
            pagein=FakeSampler([], reason="powershell is not on PATH"))
        row = tp.sweep_one(fixture_config(), "fixture", probe,
                           fake_deps(daemon, FakeLog(log)), 10,
                           "fixture-model:test", 8192, samplers=factory)
        self.assertIsNone(row["pcie_rx_mb_s_mean"])
        self.assertIsNone(row["gpu_sm_pct_mean"])
        self.assertIsNone(row["page_in_per_s_mean"])
        self.assertIsNone(row["paged"])
        self.assertIn("gpu", row["unavailable"])
        self.assertIn("page_in", row["unavailable"])

    def test_measured_counters_populate_the_row_and_flag_paging(self):
        log = fixture_log()
        daemon = FakeDaemon(log)
        row = tp.sweep_one(fixture_config(), "fixture", probe,
                           fake_deps(daemon, FakeLog(log)), 10,
                           "fixture-model:test", 8192, samplers=sampler_factory())
        self.assertEqual(row["decode_tps"], 2.73)
        self.assertEqual(row["layers_offloaded"], 5)
        self.assertEqual(row["layers_total"], 66)
        self.assertEqual(row["kv_cache_mib"], 304.0)
        self.assertEqual(row["compute_buffer_device_mib"], 451.6)
        self.assertEqual(row["compute_buffer_host_mib"], 174.9)
        self.assertEqual(row["free_ram_mib_min"], 1534.0)
        self.assertTrue(row["paged"])
        self.assertEqual(row["cpu_pct_mean"], 65.0)

    def test_a_zero_page_in_rate_is_measured_and_means_not_paging(self):
        log = fixture_log()
        daemon = FakeDaemon(log)
        factory = sampler_factory(pagein=FakeSampler([0.0, 0.0]))
        row = tp.sweep_one(fixture_config(), "fixture", probe,
                           fake_deps(daemon, FakeLog(log)), 10,
                           "fixture-model:test", 8192, samplers=factory)
        self.assertEqual(row["page_in_per_s_mean"], 0.0)
        self.assertFalse(row["paged"])


# ---------------------------------------------------------------------------
# Verdicts
# ---------------------------------------------------------------------------

class TestVerdicts(unittest.TestCase):

    def _bw(self, pairs):
        return [{"workers": w, "gb_per_s": g, "per_worker_gb_per_s": g / w,
                 "buffer_mib_per_worker": 192, "status": "ok", "source": "fixture"}
                for w, g in pairs]

    def test_the_knee_is_the_earliest_point_within_five_percent_of_peak(self):
        # The real curve: peak is at 16 but the plateau began at 10, and
        # reporting 16 would recommend six threads that buy nothing.
        rows = self._bw([(1, 13.5), (4, 43.7), (6, 50.9), (8, 53.4), (10, 57.1),
                         (12, 58.3), (16, 60.1), (20, 59.9)])
        verdict = tp.render_bandwidth_verdict(rows)
        self.assertIn("at 10 workers", verdict)
        self.assertIn("60.10", verdict.replace("60.1 ", "60.10 "))

    def test_a_still_rising_curve_puts_the_knee_at_its_last_point(self):
        rows = self._bw([(1, 10.0), (2, 20.0), (4, 40.0)])
        self.assertIn("at 4 workers", tp.render_bandwidth_verdict(rows))

    def test_too_few_bandwidth_points_says_so_rather_than_inventing_a_knee(self):
        self.assertIn("not enough points", tp.render_bandwidth_verdict(self._bw([(1, 10.0)])))

    def test_a_failed_bandwidth_point_carries_its_status_not_a_number(self):
        row = {"workers": 4, "gb_per_s": None, "per_worker_gb_per_s": None,
               "status": "a worker returned no result", "buffer_mib_per_worker": 192}
        rendered = tp.render_bandwidth_row(row, fixture_config(), "fixture", probe)
        self.assertIn("a worker returned no result", rendered)
        self.assertNotIn("GB/s", rendered)

    def test_the_sweep_verdict_flags_rungs_contaminated_by_paging(self):
        rows = []
        for requested, tps, paged in ((10, 2.73, True), (16, 2.80, True)):
            log = fixture_log(n_threads=requested)
            daemon = FakeDaemon(log, decode_tps=tps)
            rows.append(tp.sweep_one(
                fixture_config(), "fixture", probe,
                fake_deps(daemon, FakeLog(log)), requested,
                "fixture-model:test", 8192,
                samplers=sampler_factory(
                    pagein=FakeSampler([10615.0] if paged else [0.0]))))
        verdict = tp.render_sweep_verdict(rows)
        self.assertIn("hard page-ins", verdict)
        self.assertIn("2 of 2", verdict)

    def test_clean_rungs_are_not_flagged_for_paging(self):
        rows = []
        for requested, tps in ((10, 2.73), (16, 2.80)):
            log = fixture_log(n_threads=requested)
            daemon = FakeDaemon(log, decode_tps=tps)
            rows.append(tp.sweep_one(
                fixture_config(), "fixture", probe,
                fake_deps(daemon, FakeLog(log)), requested,
                "fixture-model:test", 8192,
                samplers=sampler_factory(pagein=FakeSampler([0.0, 0.0]))))
        verdict = tp.render_sweep_verdict(rows)
        self.assertNotIn("hard page-ins", verdict)
        self.assertIn("fastest", verdict)

    def test_no_decode_figure_concludes_nothing(self):
        row = tp.new_sweep_row("m", 8192, 10)
        self.assertIn("nothing can be concluded", tp.render_sweep_verdict([row]))


# ---------------------------------------------------------------------------
# Bandwidth mode, run for real but tiny
# ---------------------------------------------------------------------------

class TestForcedOffload(unittest.TestCase):
    """
    The layer override. The allocator ACCEPTS num_gpu and then places what it
    can, so the request succeeding says nothing about what happened - only the
    log's offload line does. A row that reported the requested count would
    claim a measurement of 12 layers taken on 5.
    """

    def _row(self, requested_gpu, placed_in_log, **kwargs):
        # n_threads matches the request so the ONLY abnormal axis is the layer
        # override, and a DECLINED note cannot be confused with a thread one.
        log = fixture_log(n_threads=14, offloaded=placed_in_log)
        daemon = FakeDaemon(log, **kwargs)
        row = tp.sweep_one(fixture_config(), "fixture", probe,
                           fake_deps(daemon, FakeLog(log)), 14,
                           "fixture-model:test", 8192,
                           samplers=sampler_factory(), num_gpu=requested_gpu)
        return row, daemon

    def test_a_placement_matching_the_request_is_honoured(self):
        row, _ = self._row(8, 8)
        self.assertEqual(row["gpu_effect"], "honoured")
        self.assertEqual(row["num_gpu_requested"], 8)

    def test_a_declined_override_names_both_counts(self):
        row, _ = self._row(12, 5)
        self.assertIn("DECLINED", row["gpu_effect"])
        self.assertIn("12", row["gpu_effect"])
        self.assertIn("5", row["gpu_effect"])

    def test_a_declined_override_reaches_the_rendered_row(self):
        row, _ = self._row(12, 5)
        self.assertIn("DECLINED", tp.render_sweep_row(row))

    def test_both_effects_are_shown_when_both_are_abnormal(self):
        # The defect this suite found: showing only one note hid a declined
        # layer override behind an ignored thread request, and the row then
        # read as though the override had been granted.
        log = fixture_log(n_threads=10, offloaded=5)
        daemon = FakeDaemon(log)
        row = tp.sweep_one(fixture_config(), "fixture", probe,
                           fake_deps(daemon, FakeLog(log)), 14,
                           "fixture-model:test", 8192,
                           samplers=sampler_factory(), num_gpu=12)
        rendered = tp.render_sweep_row(row)
        self.assertIn("IGNORED", rendered)
        self.assertIn("DECLINED", rendered)

    def test_the_verdict_says_so_when_no_override_placed_more_layers(self):
        rows = []
        for requested in (5, 8, 12):
            log = fixture_log(n_threads=14, offloaded=5)
            daemon = FakeDaemon(log)
            rows.append(tp.sweep_one(
                fixture_config(), "fixture", probe,
                fake_deps(daemon, FakeLog(log)), 14, "fixture-model:test", 8192,
                samplers=sampler_factory(), num_gpu=requested))
        verdict = tp.render_gpu_verdict(rows)
        self.assertIn("nothing to compare", verdict)
        self.assertNotIn("gains", verdict)

    def test_no_offload_line_is_unknown_and_not_assumed_honoured(self):
        log = fixture_log().replace("offloaded 5/66 layers to GPU", "no split here")
        daemon = FakeDaemon(log)
        row = tp.sweep_one(fixture_config(), "fixture", probe,
                           fake_deps(daemon, FakeLog(log)), 14,
                           "fixture-model:test", 8192,
                           samplers=sampler_factory(), num_gpu=10)
        self.assertIn("unknown", row["gpu_effect"])

    def test_the_request_carries_num_gpu_only_when_one_was_given(self):
        _, with_gpu = self._row(8, 8)
        loads = [c for c in with_gpu.calls if (c.get("options") or {}).get("num_ctx")]
        self.assertTrue(all(c["options"].get("num_gpu") == 8 for c in loads))

        log = fixture_log()
        daemon = FakeDaemon(log)
        tp.sweep_one(fixture_config(), "fixture", probe,
                     fake_deps(daemon, FakeLog(log)), 14,
                     "fixture-model:test", 8192, samplers=sampler_factory())
        loads = [c for c in daemon.calls if (c.get("options") or {}).get("num_ctx")]
        self.assertTrue(loads)
        for call in loads:
            self.assertNotIn("num_gpu", call["options"])

    def test_a_thread_only_row_has_no_gpu_effect(self):
        log = fixture_log()
        daemon = FakeDaemon(log)
        row = tp.sweep_one(fixture_config(), "fixture", probe,
                           fake_deps(daemon, FakeLog(log)), 14,
                           "fixture-model:test", 8192, samplers=sampler_factory())
        self.assertIsNone(row["gpu_effect"])
        self.assertIsNone(row["num_gpu_requested"])

    def test_consecutive_load_failures_stop_the_layer_sweep(self):
        # A card that has refused an override twice will refuse the higher
        # rungs too, and continuing just hammers it.
        log = fixture_log()
        daemon = FakeDaemon(log, fail_on="load")
        rows = tp.run_gpu_sweep(fixture_config(), "fixture", probe,
                                fake_deps(daemon, FakeLog(log)),
                                gpu_layers=[5, 8, 10, 12, 14],
                                samplers=sampler_factory())
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(r["status"].startswith("load failed") for r in rows))

    def test_a_healthy_layer_sweep_runs_every_rung(self):
        # Negative control for the stop rule: without it the assertion above
        # passes on a sweep that always stops after two.
        log = fixture_log()
        daemon = FakeDaemon(log)
        rows = tp.run_gpu_sweep(fixture_config(), "fixture", probe,
                                fake_deps(daemon, FakeLog(log)),
                                gpu_layers=[5, 8, 10, 12, 14],
                                samplers=sampler_factory())
        self.assertEqual(len(rows), 5)

    def test_the_gpu_verdict_reports_a_loss_as_a_loss(self):
        rows = []
        for requested, placed, tps in ((5, 5, 3.40), (8, 8, 3.00)):
            log = fixture_log(offloaded=placed)
            daemon = FakeDaemon(log, decode_tps=tps)
            rows.append(tp.sweep_one(
                fixture_config(), "fixture", probe,
                fake_deps(daemon, FakeLog(log)), 14, "fixture-model:test", 8192,
                samplers=sampler_factory(), num_gpu=requested))
        verdict = tp.render_gpu_verdict(rows)
        self.assertIn("LOSES", verdict)
        self.assertIn("page-ins per second by layers placed", verdict)

    def test_the_gpu_verdict_counts_declined_overrides(self):
        rows = []
        for requested, placed in ((5, 5), (12, 5)):
            log = fixture_log(offloaded=placed)
            daemon = FakeDaemon(log)
            rows.append(tp.sweep_one(
                fixture_config(), "fixture", probe,
                fake_deps(daemon, FakeLog(log)), 14, "fixture-model:test", 8192,
                samplers=sampler_factory(), num_gpu=requested))
        self.assertIn("1 of 2 overrides were DECLINED",
                      tp.render_gpu_verdict(rows))

    def test_repeated_settings_are_averaged_not_maximised(self):
        # Setting 4 holds the single best run but the worse mean. Comparing
        # best-single-run against best-single-run would name it the winner,
        # which is what repeats were run to prevent.
        rows = []
        for requested, tps in ((3, 3.90), (3, 3.80), (3, 3.70),
                               (4, 5.00), (4, 2.50), (4, 2.50), (2, 3.00)):
            log = fixture_log(n_threads=14, offloaded=requested)
            daemon = FakeDaemon(log, decode_tps=tps)
            rows.append(tp.sweep_one(
                fixture_config(), "fixture", probe,
                fake_deps(daemon, FakeLog(log)), 14, "fixture-model:test", 8192,
                samplers=sampler_factory(), num_gpu=requested))
        verdict = tp.render_gpu_verdict(rows)
        self.assertIn("with 3 layers placed", verdict)
        self.assertNotIn("with 4 layers placed", verdict)
        self.assertIn("mean of 3 runs", verdict)

    def test_the_gpu_verdict_states_the_spread_when_settings_were_repeated(self):
        rows = []
        for requested, tps in ((2, 3.48), (2, 3.00), (3, 4.11), (3, 3.64)):
            log = fixture_log(n_threads=14, offloaded=requested)
            daemon = FakeDaemon(log, decode_tps=tps)
            rows.append(tp.sweep_one(
                fixture_config(), "fixture", probe,
                fake_deps(daemon, FakeLog(log)), 14, "fixture-model:test", 8192,
                samplers=sampler_factory(), num_gpu=requested))
        self.assertIn("Run-to-run spread", tp.render_gpu_verdict(rows))

    def test_the_gpu_verdict_warns_when_nothing_was_repeated(self):
        # Negative control: one run per setting cannot separate anything, and
        # the verdict must say so rather than presenting a ranking as settled.
        rows = []
        for requested, tps in ((2, 3.00), (3, 3.10)):
            log = fixture_log(n_threads=14, offloaded=requested)
            daemon = FakeDaemon(log, decode_tps=tps)
            rows.append(tp.sweep_one(
                fixture_config(), "fixture", probe,
                fake_deps(daemon, FakeLog(log)), 14, "fixture-model:test", 8192,
                samplers=sampler_factory(), num_gpu=requested))
        self.assertIn("run ONCE", tp.render_gpu_verdict(rows))

    def test_mean_by_groups_and_reports_spread(self):
        groups = tp.mean_by([{"k": 2, "decode_tps": 4.0},
                             {"k": 2, "decode_tps": 2.0},
                             {"k": 3, "decode_tps": 3.0}], "k")
        self.assertEqual([g["key"] for g in groups], [2, 3])
        self.assertEqual(groups[0]["mean"], 3.0)
        self.assertEqual(groups[0]["n"], 2)
        self.assertEqual(groups[0]["spread_pct"], 100.0)
        self.assertIsNone(groups[1]["spread_pct"])

    def test_the_gpu_verdict_concludes_nothing_without_a_decode_figure(self):
        row = tp.new_sweep_row("m", 8192, 14, 8)
        self.assertIn("nothing can be concluded", tp.render_gpu_verdict([row]))


class TestBandwidthAggregation(unittest.TestCase):
    """
    The arithmetic only. The real spawn cannot be driven from here: spawn
    re-imports the worker's module by name in the child and this file's name
    carries hyphens, so a by-path import gives the child a module it cannot
    find. Running the tool exercises that path.
    """

    def test_aggregate_is_total_bytes_over_the_shared_window(self):
        # Two workers, 4 GB each in 2 s => 8 GB / 2 s = 4 GB/s aggregate.
        row = tp.bandwidth_point(
            2, 192, 2.0,
            spawn=lambda w, m, s: ([(4e9, 2.0), (4e9, 2.0)], []))
        self.assertEqual(row["status"], "ok")
        self.assertAlmostEqual(row["gb_per_s"], 4.0, places=6)
        self.assertAlmostEqual(row["per_worker_gb_per_s"], 2.0, places=6)

    def test_workers_that_ran_for_unequal_windows_use_the_mean_window(self):
        row = tp.bandwidth_point(
            2, 192, 2.0,
            spawn=lambda w, m, s: ([(4e9, 1.0), (4e9, 3.0)], []))
        self.assertAlmostEqual(row["gb_per_s"], 4.0, places=6)

    def test_a_worker_error_is_the_status_and_no_number_is_invented(self):
        row = tp.bandwidth_point(
            4, 192, 2.0,
            spawn=lambda w, m, s: ([], ["numpy is required for the bandwidth mode"]))
        self.assertIsNone(row["gb_per_s"])
        self.assertIn("numpy is required", row["status"])

    def test_no_worker_reporting_at_all_is_a_status_and_not_a_zero(self):
        row = tp.bandwidth_point(4, 192, 2.0, spawn=lambda w, m, s: ([], []))
        self.assertIsNone(row["gb_per_s"])
        self.assertIn("no worker reported", row["status"])


# ---------------------------------------------------------------------------
# The CLI, and the shipped configuration
# ---------------------------------------------------------------------------

class TestCli(unittest.TestCase):

    def test_dry_run_writes_nothing_and_exits_zero(self):
        with tempfile.TemporaryDirectory() as scratch:
            config = pathlib.Path(scratch) / "cfg.json"
            config.write_text(json.dumps(fixture_config()), encoding="utf-8")
            before = sorted(p.name for p in pathlib.Path(scratch).iterdir())
            completed = subprocess.run(
                [sys.executable, str(SCRIPT), "--dry-run", "--config", str(config)],
                capture_output=True, text=True, timeout=120)
            self.assertEqual(completed.returncode, tp.EXIT_OK, completed.stderr)
            self.assertIn("wrote       nothing", completed.stdout)
            self.assertEqual(sorted(p.name for p in pathlib.Path(scratch).iterdir()),
                             before)

    def test_an_unparsable_config_exits_two_as_a_refusal_by_design(self):
        with tempfile.TemporaryDirectory() as scratch:
            config = pathlib.Path(scratch) / "cfg.json"
            config.write_text("{ not json", encoding="utf-8")
            completed = subprocess.run(
                [sys.executable, str(SCRIPT), "--dry-run", "--config", str(config)],
                capture_output=True, text=True, timeout=120)
            self.assertEqual(completed.returncode, tp.EXIT_REFUSED)
            self.assertIn("REFUSED", completed.stderr)

    def test_the_shipped_config_declares_every_key_the_script_reads(self):
        cfg = json.loads(SHIPPED_CONFIG.read_text(encoding="utf-8"))
        for dotted in ("ollama.host", "ollama.keep_alive", "ollama.think",
                       "ollama.load_timeout_s", "ollama.decode_timeout_s",
                       "ollama.evict_poll_interval_s", "ollama.evict_timeout_s",
                       "ollama.post_evict_settle_s", "ollama.connect_timeout_s",
                       "server_log.candidate_paths", "server_log.read_delay_s",
                       "server_log.max_tail_bytes", "log_selection.kv_cache_mib",
                       "log_selection.compute_buffer_mib",
                       "log_selection.host_pool_patterns",
                       "gpu.nvidia_smi", "gpu.query_timeout_s",
                       "gpu.pcie_sample_interval_s", "gpu.dmon_select",
                       "sweep.gpu_layers", "sweep.gpu_sweep_num_thread",
                       "sweep.gpu_stop_after_failures",
                       "paging.enabled", "paging.sample_interval_s",
                       "safety.min_free_ram_mib", "safety.free_ram_reread_delay_s",
                       "sweep.model", "sweep.num_ctx", "sweep.threads",
                       "sweep.repeats", "measurement.warmup_prompt",
                       "measurement.warmup_num_predict",
                       "measurement.decode_prompt",
                       "measurement.decode_num_predict",
                       "bandwidth.workers", "bandwidth.buffer_mib_per_worker",
                       "bandwidth.seconds_per_point", "report.float_places"):
            probe.require(cfg, dotted, str(SHIPPED_CONFIG))
        for name in ("offload", "kv_cache_mib", "compute_buffer_pool",
                     "n_threads", "n_ctx"):
            self.assertIn(name, cfg["log_patterns"])

    def test_the_shipped_thread_rungs_span_the_question_being_asked(self):
        # 10 is what the daemon picks by itself and 16 is the 80-percent-of-20
        # target. A sweep missing either cannot answer "should I raise it".
        cfg = json.loads(SHIPPED_CONFIG.read_text(encoding="utf-8"))
        self.assertIn(10, cfg["sweep"]["threads"])
        self.assertIn(16, cfg["sweep"]["threads"])

    def test_the_shipped_config_names_no_model_tag_in_the_script(self):
        # R2: exactly one place names a tag, and it is the configuration.
        source = SCRIPT.read_text(encoding="utf-8")
        for tag in ("qwen3.8", "gemma4", "qwen2.5-coder", "ornith"):
            self.assertNotIn(tag, source,
                             f"the model tag {tag} is written into the script")


if __name__ == "__main__":
    unittest.main(verbosity=2)
