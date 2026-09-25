"""
Offline test for aider-gpu-probe.py.

Needs no Ollama daemon, no GPU, no server log of its own and no network: the
HTTP client, the log reader, the subprocess runner, the clock, the sleeper and
the free-RAM reader are all injected, and the few filesystem cases build their
files under tempfile.

Every behaviour is asserted in both directions. A parser is proven to read the
real log line AND to report nothing rather than a zero when the line is absent;
the clamp guard is proven to reject a granted window that differs from the
requested one AND to accept the one that matches; the skip predicate is proven
to skip AND not to skip. A check that cannot fail proves nothing, and each of
these guards exists because the failure it catches is silent: a wrong number
that looks exactly like a right one.

Run:  python Test/test_aider_gpu_probe.py
"""

from __future__ import annotations

import importlib.util
import json
import pathlib
import sys
import tempfile
import unittest


def _load_module():
    """The script's filename carries hyphens, so it cannot be imported by name."""
    here = pathlib.Path(__file__).resolve().parent
    target = here.parent / "aider-gpu-probe.py"
    if not target.is_file():
        raise SystemExit(f"script not found beside the test: {target}")
    spec = importlib.util.spec_from_file_location("aider_gpu_probe", target)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


probe = _load_module()


# --------------------------------------------------------------------------
# Fixtures: verbatim samples of the lines the daemon writes.
# --------------------------------------------------------------------------

LOAD_CPU_ONLY = """
time=2026-09-03T09:00:00 level=INFO msg="server config" env="map[OLLAMA_CONTEXT_LENGTH:262144 OLLAMA_KV_CACHE_TYPE:q8_0 OLLAMA_MAX_LOADED_MODELS:1]"
common_params_fit_impl: id=0, n_layer= 2, n_part= 0, overflow_type=4, mem=  4553 MiB
common_params_fit_impl: id=0, n_layer= 1, n_part= 0, overflow_type=4, mem=  4302 MiB
load_tensors: offloaded 0/66 layers to GPU
llama_kv_cache: size = 8704.00 MiB (262144 cells,  16 layers,  1/1 seqs), K (q8_0): 4352.00 MiB, V (q8_0): 4352.00 MiB
llama_kv_cache: size =  544.00 MiB (262144 cells,   1 layers,  1/1 seqs), K (f16):  272.00 MiB, V (f16):  272.00 MiB
sched_reserve:      CUDA0 compute buffer size =  1959.73 MiB
sched_reserve:  CUDA_Host compute buffer size =   276.02 MiB
cmn          init: llama threadpool init, n_threads = 10
llama_context: n_ctx                 = 262144
"""

LOAD_FULLY_RESIDENT = """
load_tensors: offloaded 29/29 layers to GPU
llama_kv_cache: size =  512.00 MiB (32768 cells,  28 layers,  1/1 seqs), K (q8_0): 256.00 MiB, V (q8_0): 256.00 MiB
sched_reserve:      CUDA0 compute buffer size =   304.00 MiB
cmn          init: llama threadpool init, n_threads = 14
llama_context: n_ctx                 = 32768
"""

LOAD_CLAMPED = """
load_tensors: offloaded 29/29 layers to GPU
llama_kv_cache: size =  512.00 MiB (32768 cells,  28 layers,  1/1 seqs)
sched_reserve:      CUDA0 compute buffer size =   304.00 MiB
llama_context: n_ctx                 = 32768
"""

LOAD_SILENT = "time=2026-09-03T09:00:00 level=INFO msg=\"something unrelated\"\n"


def base_config():
    """A complete configuration, built here rather than read from the shipped
    file, so a test's expectations do not move when the shipped defaults do."""
    return {
        "ollama": {
            "host": "http://127.0.0.1:11434",
            "connect_timeout_s": 5, "load_timeout_s": 30, "decode_timeout_s": 30,
            "show_timeout_s": 5, "keep_alive": "5m", "think": False,
            "evict_poll_interval_s": 0.01, "evict_timeout_s": 1,
            "post_evict_settle_s": 0.01,
        },
        "server_log": {
            "candidate_paths": ["{{HOME}}/nowhere/server.log"],
            "read_delay_s": 0, "max_tail_bytes": 100000,
        },
        "log_patterns": {
            "offload": [r"load_tensors:\s+offloaded\s+(\d+)/(\d+)\s+layers to GPU"],
            "kv_cache_mib": [r"llama_kv_cache:\s*size\s*=\s*([0-9.]+)\s*MiB"],
            "compute_buffer_pool": [
                r"sched_reserve:\s*(\S+) compute buffer size\s*=\s*([0-9.]+)\s*MiB",
                r"(\S+) compute buffer size\s*=\s*([0-9.]+)\s*MiB"],
            "n_threads": [r"n_threads\s*=\s*(\d+)"],
            "n_ctx": [r"llama_context:\s*n_ctx\s*=\s*(\d+)"],
            "kv_cache_type": [r"OLLAMA_KV_CACHE_TYPE:([^\s\]]+)"],
            "fit_attempt": [r"common_params_fit_impl:\s*id=\d+,\s*n_layer=\s*(\d+),"
                            r"[^\n]*?mem=\s*(\d+)\s*MiB"],
        },
        "log_selection": {"kv_cache_mib": "sum", "compute_buffer_mib": "split",
                          "host_pool_patterns": [r"(?i)host", r"(?i)^cpu"]},
        "gpu": {"nvidia_smi": "nvidia-smi", "query_timeout_s": 5},
        "measurement": {
            "warmup_prompt": "hi", "warmup_num_predict": 1,
            "decode_prompt": "write a paragraph", "decode_num_predict": 128,
        },
        "skip": {"kv_bytes_per_token": 34816, "vram_headroom_mib": 1024},
        "safety": {"min_free_ram_mib": 8192, "free_ram_reread_delay_s": 0},
        "ranking": {"order": [["layers_fraction", "desc"], ["decode_tps", "desc"],
                              ["num_ctx", "desc"]]},
        "models": ["small:tag"],
        "contexts": [8192],
    }


class FakeLog:
    """The injected log reader: it is handed text, never a file."""

    def __init__(self, text=""):
        self.text = text
        self.offsets_asked = []

    def offset(self):
        return len(self.text)

    def tail(self, offset):
        self.offsets_asked.append(offset)
        return self.text


class FakeDaemon:
    """Records what was asked of the daemon, answers from canned bodies."""

    def __init__(self, ps_bodies=None, generate_results=None, tags_body=None,
                 show_body=None):
        self.host = "http://fake"
        self._ps = list(ps_bodies or [{"models": []}])
        self._generate = list(generate_results or [])
        self._tags = tags_body if tags_body is not None else {"models": []}
        self._show = show_body if show_body is not None else {}
        self.generate_calls = []
        self.ps_calls = 0
        self.show_calls = []

    def ps(self, timeout):
        self.ps_calls += 1
        return self._ps.pop(0) if len(self._ps) > 1 else self._ps[0]

    def tags(self, timeout):
        if isinstance(self._tags, Exception):
            raise self._tags
        return self._tags

    def show(self, model, timeout):
        self.show_calls.append(model)
        if isinstance(self._show, Exception):
            raise self._show
        return self._show

    def generate(self, payload, timeout):
        self.generate_calls.append(payload)
        if not self._generate:
            return {}
        result = self._generate.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def make_deps(daemon=None, log=None, free=(20000.0, "os"), smi=(1000.0, 6144.0)):
    """A Deps bundle whose every effect is a fake."""
    sleeps = []
    deps = probe.Deps(
        daemon or FakeDaemon(),
        log if log is not None else FakeLog(),
        clock=lambda: 0.0,
        sleeper=sleeps.append,
        ram=lambda: free,
        smi=(lambda: smi) if smi else None,
    )
    deps.sleeps = sleeps
    return deps


def resident(name, size=1000, size_vram=1000):
    return {"models": [{"name": name, "size": size, "size_vram": size_vram}]}


# --------------------------------------------------------------------------
# Log parsing
# --------------------------------------------------------------------------

class TestLogParsing(unittest.TestCase):

    def setUp(self):
        self.patterns = base_config()["log_patterns"]

    def test_offload_line_is_read(self):
        self.assertEqual(probe.parse_offload(LOAD_CPU_ONLY, self.patterns["offload"]),
                         (0, 66))

    def test_a_load_with_no_offload_line_reports_nothing_not_zero(self):
        # The failure case that matters: a silent log must never be read as
        # "zero layers", which is a real and different measurement.
        self.assertIsNone(probe.parse_offload(LOAD_SILENT, self.patterns["offload"]))

    def test_two_kv_caches_are_summed(self):
        # A hybrid attention layout prints one line per cache. Taking the first
        # under-reports the cache by the size of every other one.
        total = probe.parse_mib(LOAD_CPU_ONLY, self.patterns["kv_cache_mib"], "sum")
        self.assertAlmostEqual(total, 8704.00 + 544.00, places=2)

    def test_first_selection_would_have_missed_the_second_cache(self):
        first = probe.parse_mib(LOAD_CPU_ONLY, self.patterns["kv_cache_mib"], "first")
        self.assertAlmostEqual(first, 8704.00, places=2)

    def test_absent_figure_is_none(self):
        self.assertIsNone(probe.parse_mib(LOAD_SILENT, self.patterns["kv_cache_mib"],
                                          "sum"))

    def test_thread_count_is_read(self):
        self.assertEqual(probe.parse_int(LOAD_CPU_ONLY, self.patterns["n_threads"]), 10)

    def test_n_threads_batch_alone_does_not_match(self):
        self.assertIsNone(probe.parse_int("n_threads_batch = 14\n",
                                          self.patterns["n_threads"]))

    def test_granted_window_is_read(self):
        self.assertEqual(probe.parse_int(LOAD_CPU_ONLY, self.patterns["n_ctx"]), 262144)

    def test_kv_cache_type_comes_from_the_server_config_line(self):
        self.assertEqual(probe.parse_str(LOAD_CPU_ONLY, self.patterns["kv_cache_type"]),
                         "q8_0")

    def test_kv_cache_type_absent_is_none_not_a_guess(self):
        self.assertIsNone(probe.parse_str(LOAD_FULLY_RESIDENT,
                                          self.patterns["kv_cache_type"]))

    def test_allocator_attempts_are_captured_in_order(self):
        attempts = probe.parse_fit_attempts(LOAD_CPU_ONLY, self.patterns["fit_attempt"])
        self.assertEqual(attempts, [{"n_layer": 2, "mem_mib": 4553},
                                    {"n_layer": 1, "mem_mib": 4302}])

    def test_no_allocator_attempts_is_an_empty_list(self):
        self.assertEqual(probe.parse_fit_attempts(LOAD_FULLY_RESIDENT,
                                                  self.patterns["fit_attempt"]), [])


class TestComputeBufferSplit(unittest.TestCase):
    """The device pool competes for VRAM and the host pool competes with the
    weights that were spilled to system RAM. Adding them describes no real
    constraint, so they are two figures and the classification is data."""

    def setUp(self):
        cfg = base_config()
        self.patterns = cfg["log_patterns"]["compute_buffer_pool"]
        self.hosts = cfg["log_selection"]["host_pool_patterns"]

    def test_each_pool_is_read_with_its_name(self):
        pools = probe.parse_compute_buffers(LOAD_CPU_ONLY, self.patterns)
        self.assertEqual(pools, [("CUDA0", 1959.73), ("CUDA_Host", 276.02)])

    def test_device_and_host_are_reported_apart_and_never_added(self):
        pools = probe.parse_compute_buffers(LOAD_CPU_ONLY, self.patterns)
        device, host = probe.split_compute_buffers(pools, self.hosts)
        self.assertAlmostEqual(device, 1959.73, places=2)
        self.assertAlmostEqual(host, 276.02, places=2)
        self.assertNotAlmostEqual(device, 1959.73 + 276.02, places=2)

    def test_several_device_pools_are_summed_within_their_own_side(self):
        pools = [("CUDA0", 100.0), ("CUDA1", 50.0), ("CUDA_Host", 20.0)]
        device, host = probe.split_compute_buffers(pools, self.hosts)
        self.assertAlmostEqual(device, 150.0, places=2)
        self.assertAlmostEqual(host, 20.0, places=2)

    def test_a_side_with_no_pool_is_none_rather_than_zero(self):
        # No host buffer reserved and no host buffer reported are different
        # answers, and 0.0 would read as the first.
        device, host = probe.split_compute_buffers([("CUDA0", 304.0)], self.hosts)
        self.assertAlmostEqual(device, 304.0, places=2)
        self.assertIsNone(host)

    def test_a_pool_nobody_classified_counts_as_a_device_pool(self):
        # The conservative reading when the question is what has to fit on the
        # card. Asserted so a backend naming its pools differently degrades in
        # a known direction rather than silently dropping the figure.
        device, host = probe.split_compute_buffers([("Vulkan0", 800.0)], self.hosts)
        self.assertAlmostEqual(device, 800.0, places=2)
        self.assertIsNone(host)

    def test_the_host_classifier_is_data_and_can_be_changed(self):
        device, host = probe.split_compute_buffers([("Vulkan0", 800.0)],
                                                   [r"(?i)vulkan"])
        self.assertIsNone(device)
        self.assertAlmostEqual(host, 800.0, places=2)

    def test_a_combining_rule_still_yields_one_number_for_anyone_who_wants_it(self):
        pools = probe.parse_compute_buffers(LOAD_CPU_ONLY, self.patterns)
        values = [mib for _, mib in pools]
        self.assertAlmostEqual(probe._select(values, "sum"), 1959.73 + 276.02, places=2)
        self.assertAlmostEqual(probe._select(values, "max"), 1959.73, places=2)


class TestNativeContext(unittest.TestCase):

    def test_context_length_is_found_by_suffix_not_by_architecture(self):
        found, key = probe.native_context(
            {"model_info": {"general.architecture": "qwen35",
                            "qwen35.context_length": 262144}})
        self.assertEqual(found, 262144)
        self.assertEqual(key, "qwen35.context_length")

    def test_a_body_with_no_context_length_states_why(self):
        found, why = probe.native_context({"model_info": {"general.architecture": "x"}})
        self.assertIsNone(found)
        self.assertIn("context_length", why)


# --------------------------------------------------------------------------
# Predicates and arithmetic
# --------------------------------------------------------------------------

class TestSkipPredicate(unittest.TestCase):

    def test_a_window_whose_kv_cache_exceeds_the_card_is_skipped(self):
        skip, reason = probe.should_skip(262144, 34816, 6144, 1024)
        self.assertTrue(skip)
        self.assertIn("predicted KV", reason)

    def test_a_window_that_fits_is_attempted(self):
        skip, reason = probe.should_skip(8192, 34816, 6144, 1024)
        self.assertFalse(skip)
        self.assertEqual(reason, "")

    def test_a_window_above_the_models_maximum_is_skipped_before_it_is_clamped(self):
        skip, reason = probe.should_skip(65536, 34816, 65536, 1024, native_max=32768)
        self.assertTrue(skip)
        self.assertIn("clamp", reason)

    def test_a_window_exactly_at_the_maximum_is_not_skipped(self):
        skip, _ = probe.should_skip(32768, 1, 65536, 1024, native_max=32768)
        self.assertFalse(skip)

    def test_predicted_cache_matches_the_measured_one(self):
        # 34816 bytes per token at 262144 tokens is the 8704 MiB measured on a
        # real load, which is what makes this screening estimate usable.
        self.assertAlmostEqual(probe.predicted_kv_mib(262144, 34816), 8704.0, places=1)


class TestDecodeThroughput(unittest.TestCase):

    def test_tokens_per_second_come_from_the_decode_fields(self):
        tps = probe.decode_tps({"eval_count": 128, "eval_duration": 8_000_000_000,
                                "prompt_eval_count": 4000,
                                "prompt_eval_duration": 100_000_000})
        self.assertAlmostEqual(tps, 16.0, places=3)

    def test_a_zero_duration_is_not_an_infinite_rate(self):
        self.assertIsNone(probe.decode_tps({"eval_count": 128, "eval_duration": 0}))

    def test_a_response_missing_the_decode_fields_reports_nothing(self):
        self.assertIsNone(probe.decode_tps({"prompt_eval_count": 10,
                                            "prompt_eval_duration": 5}))

    def test_a_boolean_is_not_a_count(self):
        self.assertIsNone(probe.decode_tps({"eval_count": True,
                                            "eval_duration": 1_000_000_000}))


class TestResidencyRatio(unittest.TestCase):

    def test_ratio_is_the_memory_ratio_from_api_ps(self):
        self.assertAlmostEqual(
            probe.residency_ratio(resident("t", size=1000, size_vram=80), "t"),
            0.08, places=4)

    def test_a_tag_that_is_not_resident_has_no_ratio(self):
        self.assertIsNone(probe.residency_ratio(resident("other"), "t"))

    def test_a_zero_size_is_not_divided_by(self):
        self.assertIsNone(probe.residency_ratio(resident("t", size=0, size_vram=0), "t"))


class TestRanking(unittest.TestCase):

    def rows(self):
        return [
            {"model": "a", "layers_fraction": 0.0, "decode_tps": 2.0, "num_ctx": 262144},
            {"model": "b", "layers_fraction": 1.0, "decode_tps": 30.0, "num_ctx": 8192},
            {"model": "c", "layers_fraction": 1.0, "decode_tps": 30.0, "num_ctx": 32768},
        ]

    def test_gpu_residency_outranks_context(self):
        order = base_config()["ranking"]["order"]
        ranked = probe.rank_rows(self.rows(), order)
        self.assertEqual([r["model"] for r in ranked], ["c", "b", "a"])

    def test_a_different_order_is_configuration_not_code(self):
        ranked = probe.rank_rows(self.rows(), [["num_ctx", "desc"]])
        self.assertEqual([r["model"] for r in ranked], ["a", "c", "b"])

    def test_an_unmeasured_value_never_wins_by_being_absent(self):
        rows = self.rows()
        rows.append({"model": "d", "layers_fraction": None, "decode_tps": None,
                     "num_ctx": 262144})
        ranked = probe.rank_rows(rows, base_config()["ranking"]["order"])
        self.assertEqual(ranked[-1]["model"], "d")

    def test_a_ranking_field_no_row_carries_is_refused(self):
        with self.assertRaises(probe.Refusal) as caught:
            probe.rank_rows(self.rows(), [["throughput", "desc"]])
        self.assertIn("throughput", str(caught.exception))


# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------

class TestConfigValidation(unittest.TestCase):

    def test_a_complete_configuration_validates(self):
        probe.validate_config(base_config(), "fixture.json")

    def test_a_missing_key_names_the_key_and_the_file(self):
        cfg = base_config()
        del cfg["ollama"]["keep_alive"]
        with self.assertRaises(probe.Refusal) as caught:
            probe.validate_config(cfg, "somewhere/aider-gpu-probe.json")
        message = str(caught.exception)
        self.assertIn("ollama.keep_alive", message)
        self.assertIn("somewhere/aider-gpu-probe.json", message)

    def test_an_empty_model_list_is_refused(self):
        cfg = base_config()
        cfg["models"] = []
        with self.assertRaises(probe.Refusal):
            probe.validate_config(cfg, "fixture.json")

    def test_a_context_that_is_not_a_positive_integer_is_refused(self):
        cfg = base_config()
        cfg["contexts"] = [8192, "32768"]
        with self.assertRaises(probe.Refusal):
            probe.validate_config(cfg, "fixture.json")

    def test_a_malformed_ranking_entry_is_refused(self):
        cfg = base_config()
        cfg["ranking"]["order"] = [["layers_fraction", "descending"]]
        with self.assertRaises(probe.Refusal):
            probe.validate_config(cfg, "fixture.json")

    def test_a_pattern_that_does_not_compile_is_refused_before_the_sweep(self):
        cfg = base_config()
        cfg["log_patterns"]["offload"] = ["load_tensors: offloaded ((\\d+)"]
        with self.assertRaises(probe.Refusal) as caught:
            probe.validate_config(cfg, "fixture.json")
        self.assertIn("log_patterns.offload", str(caught.exception))

    def test_a_pattern_with_too_few_capture_groups_is_refused(self):
        # The compute-buffer pattern needs the pool AND the number. Edited down
        # to one group it would fail deep in a sweep with an IndexError.
        cfg = base_config()
        cfg["log_patterns"]["compute_buffer_pool"] = [
            r"compute buffer size\s*=\s*([0-9.]+)\s*MiB"]
        with self.assertRaises(probe.Refusal) as caught:
            probe.validate_config(cfg, "fixture.json")
        self.assertIn("capture group", str(caught.exception))

    def test_an_unknown_selection_rule_is_refused(self):
        cfg = base_config()
        cfg["log_selection"]["kv_cache_mib"] = "average"
        with self.assertRaises(probe.Refusal):
            probe.validate_config(cfg, "fixture.json")

    def test_split_is_a_compute_buffer_rule_only(self):
        # It answers a question the KV cache does not have: the KV cache is not
        # reported per memory pool, so "split" there would silently do nothing.
        cfg = base_config()
        cfg["log_selection"]["compute_buffer_mib"] = "split"
        probe.validate_config(cfg, "fixture.json")
        cfg["log_selection"]["kv_cache_mib"] = "split"
        with self.assertRaises(probe.Refusal):
            probe.validate_config(cfg, "fixture.json")

    def test_an_empty_host_pool_classifier_is_refused(self):
        cfg = base_config()
        cfg["log_selection"]["host_pool_patterns"] = []
        with self.assertRaises(probe.Refusal) as caught:
            probe.validate_config(cfg, "fixture.json")
        self.assertIn("host_pool_patterns", str(caught.exception))

    def test_a_missing_configuration_file_is_refused_by_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = pathlib.Path(tmp) / "absent.json"
            with self.assertRaises(probe.Refusal) as caught:
                probe.load_config(missing)
            self.assertIn("absent.json", str(caught.exception))

    def test_a_configuration_that_does_not_parse_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            broken = pathlib.Path(tmp) / "broken.json"
            broken.write_text("{ not json", encoding="utf-8")
            with self.assertRaises(probe.Refusal) as caught:
                probe.load_config(broken)
            self.assertIn("does not parse", str(caught.exception))

    def test_the_shipped_configuration_validates(self):
        # The file students receive must itself pass the validator, or the
        # first thing they run refuses.
        shipped = pathlib.Path(probe.__file__).resolve().parent / probe.DEFAULT_CONFIG_NAME
        probe.load_config(shipped)

    def test_the_shipped_configuration_carries_no_home_directory(self):
        shipped = pathlib.Path(probe.__file__).resolve().parent / probe.DEFAULT_CONFIG_NAME
        text = shipped.read_text(encoding="utf-8")
        home = pathlib.Path.home()
        self.assertNotIn(str(home), text)
        self.assertNotIn(home.name, text)


class TestPlaceholders(unittest.TestCase):

    def test_home_is_substituted(self):
        resolved = probe.expand_placeholders("{{HOME}}/x")
        self.assertTrue(resolved.endswith("/x"))
        self.assertNotIn("{{HOME}}", resolved)

    def test_an_unknown_placeholder_is_left_alone_rather_than_emptied(self):
        self.assertEqual(probe.expand_placeholders("{{NOPE}}/x"), "{{NOPE}}/x")


# --------------------------------------------------------------------------
# The log reader and the server-log refusal
# --------------------------------------------------------------------------

class TestFileLogReader(unittest.TestCase):

    def test_only_what_was_appended_after_the_offset_is_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "server.log"
            path.write_text("an older load nobody asked about\n", encoding="utf-8")
            reader = probe.FileLogReader(path, 100000)
            offset = reader.offset()
            with open(path, "a", encoding="utf-8") as handle:
                handle.write(LOAD_FULLY_RESIDENT)
            tail = reader.tail(offset)
            self.assertNotIn("older load", tail)
            self.assertIn("offloaded 29/29", tail)

    def test_a_rotated_log_is_read_from_its_start_rather_than_read_as_silent(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "server.log"
            path.write_text(LOAD_FULLY_RESIDENT, encoding="utf-8")
            reader = probe.FileLogReader(path, 100000)
            tail = reader.tail(10_000_000)      # an offset from before a rotation
            self.assertIn("offloaded 29/29", tail)


class TestServerLogResolution(unittest.TestCase):

    def test_the_first_existing_candidate_wins(self):
        with tempfile.TemporaryDirectory() as tmp:
            real = pathlib.Path(tmp) / "server.log"
            real.write_text("x", encoding="utf-8")
            found = probe.resolve_server_log(
                [str(pathlib.Path(tmp) / "absent.log"), str(real)], "fixture.json")
            self.assertEqual(found, real)

    def test_no_log_at_all_refuses_and_names_every_path_tried(self):
        with tempfile.TemporaryDirectory() as tmp:
            a = str(pathlib.Path(tmp) / "one.log")
            b = str(pathlib.Path(tmp) / "two.log")
            with self.assertRaises(probe.Refusal) as caught:
                probe.resolve_server_log([a, b], "fixture.json")
            message = str(caught.exception)
            self.assertIn("one.log", message)
            self.assertIn("two.log", message)
            self.assertIn("fixture.json", message)


# --------------------------------------------------------------------------
# Eviction, VRAM and free RAM
# --------------------------------------------------------------------------

class TestEviction(unittest.TestCase):

    def test_every_resident_tag_is_asked_to_unload_and_the_effect_is_checked(self):
        daemon = FakeDaemon(ps_bodies=[resident("a"), {"models": []}])
        deps = make_deps(daemon)
        probe.evict_all(deps, base_config(), "fixture.json")
        self.assertEqual([c["model"] for c in daemon.generate_calls], ["a"])
        self.assertEqual(daemon.generate_calls[0]["keep_alive"], 0)

    def test_a_tag_that_stays_resident_is_a_refusal_not_a_load_on_top_of_it(self):
        daemon = FakeDaemon(ps_bodies=[resident("a")])
        clock = iter([0.0, 0.0, 999.0, 999.0])
        deps = make_deps(daemon)
        deps.clock = lambda: next(clock)
        with self.assertRaises(probe.Refusal) as caught:
            probe.evict_all(deps, base_config(), "fixture.json")
        self.assertIn("still resident", str(caught.exception))

    def test_the_settle_delay_is_waited_out(self):
        daemon = FakeDaemon(ps_bodies=[{"models": []}])
        deps = make_deps(daemon)
        probe.evict_all(deps, base_config(), "fixture.json")
        self.assertIn(0.01, deps.sleeps)


class TestNvidiaSmi(unittest.TestCase):

    class Completed:
        def __init__(self, returncode=0, stdout="", stderr=""):
            self.returncode, self.stdout, self.stderr = returncode, stdout, stderr

    def test_used_and_total_are_read(self):
        used, total = probe.nvidia_smi_memory(
            base_config(), "fixture.json",
            runner=lambda *a, **k: self.Completed(stdout="1234, 6144\n"),
            which=lambda name: "/usr/bin/" + name)
        self.assertEqual((used, total), (1234.0, 6144.0))

    def test_the_binary_is_invoked_by_its_resolved_path(self):
        seen = {}

        def runner(argv, **kwargs):
            seen["argv"] = argv
            return self.Completed(stdout="1, 2\n")

        probe.nvidia_smi_memory(base_config(), "fixture.json", runner=runner,
                                which=lambda name: "C:/full/path/nvidia-smi.exe")
        self.assertEqual(seen["argv"][0], "C:/full/path/nvidia-smi.exe")

    def test_an_absent_nvidia_smi_is_a_refusal_not_a_blank_column(self):
        with self.assertRaises(probe.Refusal) as caught:
            probe.nvidia_smi_memory(base_config(), "fixture.json",
                                    runner=lambda *a, **k: self.Completed(),
                                    which=lambda name: None)
        self.assertIn("nvidia-smi", str(caught.exception))

    def test_a_non_zero_exit_is_a_refusal(self):
        with self.assertRaises(probe.Refusal):
            probe.nvidia_smi_memory(
                base_config(), "fixture.json",
                runner=lambda *a, **k: self.Completed(returncode=9, stderr="driver"),
                which=lambda name: name)

    def test_output_that_is_not_two_numbers_is_a_refusal(self):
        with self.assertRaises(probe.Refusal):
            probe.nvidia_smi_memory(
                base_config(), "fixture.json",
                runner=lambda *a, **k: self.Completed(stdout="no devices\n"),
                which=lambda name: name)


class TestFreeRamFloor(unittest.TestCase):

    def test_a_low_first_reading_is_re_read_before_it_is_believed(self):
        # Measured behaviour: right after an eviction the machine reported a
        # few GB free and, seconds later, four times that.
        readings = iter([(4400.0, "os"), (17600.0, "os")])
        deps = make_deps()
        deps.ram = lambda: next(readings)
        proceed, free, _ = probe.free_ram_above_floor(deps, 8192.0, 5.0)
        self.assertTrue(proceed)
        self.assertEqual(free, 17600.0)
        self.assertIn(5.0, deps.sleeps)

    def test_a_reading_that_stays_low_stops_the_load(self):
        deps = make_deps()
        deps.ram = lambda: (1000.0, "os")
        proceed, free, _ = probe.free_ram_above_floor(deps, 8192.0, 0.0)
        self.assertFalse(proceed)
        self.assertEqual(free, 1000.0)

    def test_unreadable_free_ram_proceeds_and_says_why(self):
        # An unknown is not a low reading, and refusing on one would make the
        # script unusable on any platform whose free RAM is not readable here.
        deps = make_deps()
        deps.ram = lambda: (None, "not readable on this platform")
        proceed, free, why = probe.free_ram_above_floor(deps, 8192.0, 0.0)
        self.assertTrue(proceed)
        self.assertIsNone(free)
        self.assertIn("not readable", why)


# --------------------------------------------------------------------------
# One combination, end to end, with every effect faked
# --------------------------------------------------------------------------

class TestMeasureOne(unittest.TestCase):

    def happy_daemon(self):
        return FakeDaemon(
            ps_bodies=[{"models": []}, {"models": []},
                       resident("small:tag", size=5_000_000, size_vram=5_000_000)],
            generate_results=[{}, {"eval_count": 128,
                                   "eval_duration": 4_000_000_000}])

    def test_a_fully_resident_load_is_measured_and_every_field_cites_its_source(self):
        daemon = self.happy_daemon()
        deps = make_deps(daemon, FakeLog(LOAD_FULLY_RESIDENT))
        row = probe.measure_one(deps, base_config(), "fixture.json", "small:tag", 32768)
        self.assertEqual(row["status"], "ok")
        self.assertEqual((row["layers_offloaded"], row["layers_total"]), (29, 29))
        self.assertEqual(row["layers_fraction"], 1.0)
        self.assertEqual(row["n_threads"], 14)
        self.assertEqual(row["n_ctx_granted"], 32768)
        self.assertAlmostEqual(row["decode_tps"], 32.0, places=2)
        self.assertEqual(row["sources"]["layers_offloaded"], probe.SRC_LOG)
        self.assertEqual(row["sources"]["decode_tps"], probe.SRC_MEASURED)
        self.assertEqual(row["sources"]["residency_ratio"], probe.SRC_API)
        self.assertEqual(row["vram_total_mib"], 6144.0)
        self.assertAlmostEqual(row["compute_buffer_device_mib"], 304.0, places=2)
        self.assertIsNone(row["compute_buffer_host_mib"])
        self.assertIsNone(row["compute_buffer_mib"])

    def test_the_compute_buffer_sides_reach_the_row_apart(self):
        daemon = FakeDaemon(
            ps_bodies=[{"models": []}, {"models": []}, resident("big:tag")],
            generate_results=[{}, {"eval_count": 32, "eval_duration": 16_000_000_000}])
        deps = make_deps(daemon, FakeLog(LOAD_CPU_ONLY))
        row = probe.measure_one(deps, base_config(), "fixture.json", "big:tag", 262144)
        self.assertAlmostEqual(row["compute_buffer_device_mib"], 1959.73, places=2)
        self.assertAlmostEqual(row["compute_buffer_host_mib"], 276.02, places=2)
        # Every pool survives into the row whatever the rule, so the JSON
        # report loses nothing the log said.
        self.assertEqual(set(row["compute_buffer_pools"]), {"CUDA0", "CUDA_Host"})
        self.assertEqual(row["sources"]["compute_buffer_device_mib"], probe.SRC_LOG)

    def test_a_combining_rule_fills_the_single_field_instead(self):
        cfg = base_config()
        cfg["log_selection"]["compute_buffer_mib"] = "sum"
        daemon = FakeDaemon(
            ps_bodies=[{"models": []}, {"models": []}, resident("big:tag")],
            generate_results=[{}, {"eval_count": 32, "eval_duration": 16_000_000_000}])
        deps = make_deps(daemon, FakeLog(LOAD_CPU_ONLY))
        row = probe.measure_one(deps, cfg, "fixture.json", "big:tag", 262144)
        self.assertAlmostEqual(row["compute_buffer_mib"], 1959.73 + 276.02, places=2)
        self.assertIsNone(row["compute_buffer_device_mib"])
        self.assertIsNone(row["compute_buffer_host_mib"])

    def test_the_requested_window_is_sent_in_options_not_left_to_the_daemon_default(self):
        daemon = self.happy_daemon()
        deps = make_deps(daemon, FakeLog(LOAD_FULLY_RESIDENT))
        probe.measure_one(deps, base_config(), "fixture.json", "small:tag", 32768)
        self.assertEqual(daemon.generate_calls[-2]["options"]["num_ctx"], 32768)
        self.assertIs(daemon.generate_calls[-1]["think"], False)
        self.assertEqual(daemon.generate_calls[-1]["keep_alive"], "5m")

    def test_a_clamped_window_is_rejected_rather_than_recorded(self):
        # The request succeeded and the numbers look plausible. They describe a
        # window the daemon never granted, so the row is refused.
        daemon = self.happy_daemon()
        deps = make_deps(daemon, FakeLog(LOAD_CLAMPED))
        row = probe.measure_one(deps, base_config(), "fixture.json", "small:tag", 262144)
        self.assertIn("rejected", row["status"])
        self.assertIn("262144", row["status"])
        self.assertIn("32768", row["status"])
        self.assertIsNone(row["decode_tps"])

    def test_a_matching_window_is_not_rejected(self):
        daemon = self.happy_daemon()
        deps = make_deps(daemon, FakeLog(LOAD_CLAMPED))
        row = probe.measure_one(deps, base_config(), "fixture.json", "small:tag", 32768)
        self.assertEqual(row["status"], "ok")

    def test_a_cpu_only_load_is_reported_as_zero_layers_with_the_allocators_reasons(self):
        daemon = FakeDaemon(
            ps_bodies=[{"models": []}, {"models": []},
                       resident("big:tag", size=17_000_000, size_vram=1_400_000)],
            generate_results=[{}, {"eval_count": 32, "eval_duration": 16_000_000_000}])
        deps = make_deps(daemon, FakeLog(LOAD_CPU_ONLY))
        row = probe.measure_one(deps, base_config(), "fixture.json", "big:tag", 262144)
        self.assertEqual(row["layers_offloaded"], 0)
        self.assertEqual(row["layers_fraction"], 0.0)
        self.assertEqual(row["kv_cache_type"], "q8_0")
        self.assertEqual(len(row["fit_attempts"]), 2)
        # The memory ratio says 8% while no layer reached the GPU. Both are
        # reported, and they are different columns for exactly this reason.
        self.assertAlmostEqual(row["residency_ratio"], 0.0824, places=3)
        self.assertEqual(row["layers_fraction"], 0.0)

    def test_a_silent_log_is_a_stated_unknown_not_a_zero(self):
        daemon = self.happy_daemon()
        deps = make_deps(daemon, FakeLog(LOAD_SILENT))
        row = probe.measure_one(deps, base_config(), "fixture.json", "small:tag", 32768)
        self.assertIsNone(row["layers_offloaded"])
        self.assertIn("no 'offloaded N/M layers' line", row["status"])

    def test_a_tag_that_is_not_resident_after_the_load_measures_nothing(self):
        daemon = FakeDaemon(ps_bodies=[{"models": []}, {"models": []},
                                       resident("someone-else")],
                            generate_results=[{}])
        deps = make_deps(daemon, FakeLog(LOAD_FULLY_RESIDENT))
        row = probe.measure_one(deps, base_config(), "fixture.json", "small:tag", 32768)
        self.assertIn("not resident", row["status"])
        self.assertIsNone(row["decode_tps"])

    def test_a_failed_load_is_one_row_and_not_a_dead_sweep(self):
        daemon = FakeDaemon(ps_bodies=[{"models": []}],
                            generate_results=[RuntimeError("out of memory")])
        deps = make_deps(daemon, FakeLog(LOAD_SILENT))
        row = probe.measure_one(deps, base_config(), "fixture.json", "small:tag", 32768)
        self.assertIn("load failed", row["status"])
        self.assertIn("out of memory", row["status"])

    def test_a_response_with_no_decode_fields_says_so_rather_than_reporting_zero(self):
        daemon = FakeDaemon(
            ps_bodies=[{"models": []}, {"models": []}, resident("small:tag")],
            generate_results=[{}, {"prompt_eval_count": 10}])
        deps = make_deps(daemon, FakeLog(LOAD_FULLY_RESIDENT))
        row = probe.measure_one(deps, base_config(), "fixture.json", "small:tag", 32768)
        self.assertIsNone(row["decode_tps"])
        self.assertIn("eval_count", row["status"])

    def test_a_load_below_the_free_ram_floor_is_not_attempted(self):
        daemon = FakeDaemon(ps_bodies=[{"models": []}])
        deps = make_deps(daemon, FakeLog(LOAD_FULLY_RESIDENT), free=(1000.0, "os"))
        row = probe.measure_one(deps, base_config(), "fixture.json", "small:tag", 32768)
        self.assertIn("below the", row["status"])
        self.assertEqual(daemon.generate_calls, [])

    def test_the_log_offset_is_taken_before_the_load(self):
        daemon = self.happy_daemon()
        log = FakeLog(LOAD_FULLY_RESIDENT)
        deps = make_deps(daemon, log)
        probe.measure_one(deps, base_config(), "fixture.json", "small:tag", 32768)
        self.assertEqual(log.offsets_asked, [len(LOAD_FULLY_RESIDENT)])


# --------------------------------------------------------------------------
# Planning, preflight and reporting
# --------------------------------------------------------------------------

class TestPlan(unittest.TestCase):

    def test_a_combination_that_cannot_fit_is_marked_skip_with_its_reason(self):
        plan = probe.plan_combinations(["m"], [8192, 262144], 34816, 6144, 1024)
        self.assertFalse(plan[0]["skip"])
        self.assertTrue(plan[1]["skip"])
        self.assertIn("predicted KV", plan[1]["skip_reason"])

    def test_the_native_maximum_marks_a_rung_before_it_is_attempted(self):
        plan = probe.plan_combinations(["m"], [65536], 1, 65536, 1024,
                                       {"m": 32768})
        self.assertTrue(plan[0]["skip"])
        self.assertEqual(plan[0]["native_max"], 32768)


class TestPreflight(unittest.TestCase):

    def test_a_tag_that_is_not_installed_is_refused_by_name(self):
        daemon = FakeDaemon(tags_body={"models": [{"name": "other:tag"}]})
        with self.assertRaises(probe.Refusal) as caught:
            probe.preflight(base_config(), "fixture.json", ["small:tag"], [8192],
                            daemon, 6144.0)
        message = str(caught.exception)
        self.assertIn("small:tag", message)
        self.assertIn("other:tag", message)
        # The shipped 'models' list names tags tuned elsewhere, so this is the
        # first thing a new machine hits: the message has to carry the fix.
        self.assertIn("ollama list", message)
        self.assertIn("fixture.json", message)

    def test_an_unreachable_daemon_is_refused_and_names_the_host(self):
        daemon = FakeDaemon(tags_body=OSError("connection refused"))
        with self.assertRaises(probe.Refusal) as caught:
            probe.preflight(base_config(), "fixture.json", ["small:tag"], [8192],
                            daemon, 6144.0)
        self.assertIn("http://fake", str(caught.exception))

    def test_a_show_call_that_fails_leaves_the_maximum_unknown_rather_than_guessed(self):
        daemon = FakeDaemon(tags_body={"models": [{"name": "small:tag"}]},
                            show_body=RuntimeError("no such model"))
        _, plan, why = probe.preflight(base_config(), "fixture.json", ["small:tag"],
                                       [8192], daemon, 6144.0)
        self.assertIsNone(plan[0]["native_max"])
        self.assertIn("no such model", why["small:tag"])

    def test_the_native_maximum_reaches_the_plan(self):
        daemon = FakeDaemon(
            tags_body={"models": [{"name": "small:tag"}]},
            show_body={"model_info": {"qwen35.context_length": 32768}})
        _, plan, _ = probe.preflight(base_config(), "fixture.json", ["small:tag"],
                                     [65536], daemon, 6144.0)
        self.assertTrue(plan[0]["skip"])
        self.assertIn("32768", plan[0]["skip_reason"])


class TestTable(unittest.TestCase):

    def row(self, **over):
        row = probe.new_row("m", 8192)
        row.update(over)
        return row

    def test_every_column_states_where_its_figure_came_from(self):
        text = probe.render_table([self.row(layers_offloaded=29, layers_total=29,
                                            layers_fraction=1.0, decode_tps=30.0)])
        self.assertIn(probe.SRC_LOG, text)
        self.assertIn(probe.SRC_MEASURED, text)
        self.assertIn(probe.SRC_SMI, text)

    def test_the_two_percentages_are_told_apart_in_the_legend(self):
        text = probe.render_table([self.row()])
        self.assertIn("MEMORY ratio", text)
        self.assertIn("offloaded layers", text)

    def test_an_unmeasured_field_prints_a_dash_rather_than_a_zero(self):
        text = probe.render_table([self.row()])
        self.assertIn("-", text)
        self.assertNotIn("0.00", text)

    def test_a_row_whose_status_is_not_ok_carries_a_note(self):
        text = probe.render_table([self.row(status="rejected: clamped")])
        self.assertIn("notes:", text)
        self.assertIn("rejected: clamped", text)

    def test_the_two_compute_buffer_sides_are_two_columns(self):
        text = probe.render_table([self.row(compute_buffer_device_mib=1959.73,
                                            compute_buffer_host_mib=276.02)],
                                  split=True)
        self.assertIn("cbuf dev", text)
        self.assertIn("cbuf host", text)
        self.assertIn("1960", text)
        self.assertIn("276", text)
        # The sum must appear nowhere: it is the number this split exists to
        # stop being printed.
        self.assertNotIn("2236", text)

    def test_a_combining_rule_prints_one_column_instead(self):
        text = probe.render_table([self.row(compute_buffer_mib=2235.75)], split=False)
        self.assertIn("cbuf MiB", text)
        self.assertNotIn("cbuf dev", text)
        self.assertNotIn("cbuf host", text)

    def test_the_header_and_the_cells_stay_the_same_width_in_both_modes(self):
        for split in (True, False):
            columns = probe.columns_for(split)
            cells = probe.format_row(self.row(), split)
            self.assertEqual(len(columns), len(cells))

    def test_the_allocators_attempts_explain_a_zero_layer_row(self):
        text = probe.render_table([self.row(
            layers_offloaded=0, layers_total=66, layers_fraction=0.0,
            fit_attempts=[{"n_layer": 1, "mem_mib": 4302}])])
        self.assertIn("4302 MiB", text)


# --------------------------------------------------------------------------
# The CLI
# --------------------------------------------------------------------------

class TestDryRun(unittest.TestCase):
    """--dry-run must load nothing. Driven through main() with the daemon, the
    GPU query and the log all replaced."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = pathlib.Path(self.tmp.name)
        self.log = root / "server.log"
        self.log.write_text(LOAD_SILENT, encoding="utf-8")
        cfg = base_config()
        cfg["server_log"]["candidate_paths"] = [str(self.log)]
        cfg["contexts"] = [8192, 262144]
        self.config_path = root / "cfg.json"
        self.config_path.write_text(json.dumps(cfg), encoding="utf-8")

        self.daemon = FakeDaemon(
            tags_body={"models": [{"name": "small:tag"}]},
            show_body={"model_info": {"qwen35.context_length": 262144}})
        self.saved = (probe.Daemon, probe.nvidia_smi_memory)
        probe.Daemon = lambda host, transport=None: self.daemon
        probe.nvidia_smi_memory = lambda *a, **k: (1000.0, 6144.0)

    def tearDown(self):
        probe.Daemon, probe.nvidia_smi_memory = self.saved
        self.tmp.cleanup()

    def test_a_dry_run_starts_nothing(self):
        code = probe.main(["--config", str(self.config_path), "--dry-run"])
        self.assertEqual(code, probe.EXIT_OK)
        self.assertEqual(self.daemon.generate_calls, [])

    def test_a_dry_run_still_refuses_a_tag_that_is_not_installed(self):
        code = probe.main(["--config", str(self.config_path), "--dry-run",
                           "--models", "absent:tag"])
        self.assertEqual(code, probe.EXIT_REFUSED)
        self.assertEqual(self.daemon.generate_calls, [])

    def test_a_missing_configuration_refuses_with_the_refusal_code(self):
        code = probe.main(["--config", str(pathlib.Path(self.tmp.name) / "absent.json"),
                           "--dry-run"])
        self.assertEqual(code, probe.EXIT_REFUSED)


if __name__ == "__main__":
    unittest.main(verbosity=2)
