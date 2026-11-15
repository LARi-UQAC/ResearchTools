"""
Offline tests for the `rex` section: the numbers behind the watchdog dog (2026-11-09).

Rex is awake when the watchdog program is in the process list and curled up asleep
when it is not; his three rings are the model server's CPU share and the GPU in
VRAM and in CUDA. A reading that cannot be made is None with its reason, never a
zero (R8). Every call goes through a fake `run` and the clock is injected: no
process, no GPU, no real time (R19, R21).
"""
import datetime
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import collect_rex  # noqa: E402

NOW = datetime.datetime(2026, 11, 9, 22, 0, 0)


def config(**override):
    base = {
        "timeouts_seconds": {"rex_probe": {"value": 5}},
        "rex": {"watchdog_process": {"value": "aider-watchdog.exe"},
                "model_server_names": {"value": ["ollama", "llama-server"]}},
    }
    base["rex"].update(override)
    return base


class Fake(object):
    """A `run` that answers by program name and records every command."""

    def __init__(self, tasklist="", cpu="", gpu="", fail=(), machine="80"):
        self.answers = {"tasklist": tasklist, "powershell": cpu, "nvidia-smi": gpu}
        self.machine = machine
        self.fail = set(fail)
        self.calls = []

    def __call__(self, argv, timeout):
        self.calls.append((argv, timeout))
        if argv[0] in self.fail:
            raise OSError("absent")
        if argv[0] == "powershell" and "LoadPercentage" in argv[-1]:
            return self.machine
        return self.answers[argv[0]]


RUNNING = '"aider-watchdog.exe","4242","Console","1","9,000 K"\n'
GONE = "INFO: No tasks are running which match the specified criteria.\n"


def collect(fake, at=NOW, cpus=20):
    return collect_rex.collect(config(), Path("."), at, run=fake, logical_cpus=cpus)


class Awake(unittest.TestCase):

    def setUp(self):
        collect_rex._LAST.clear()

    def test_a_listed_watchdog_wakes_rex(self):
        self.assertTrue(collect(Fake(tasklist=RUNNING, cpu="10", gpu="5, 100, 200"))["active"])

    def test_no_watchdog_in_the_list_leaves_rex_asleep(self):
        self.assertFalse(collect(Fake(tasklist=GONE, cpu="10", gpu="5, 100, 200"))["active"])

    def test_tasklist_that_cannot_run_is_unread_not_asleep_by_default(self):
        out = collect(Fake(cpu="10", gpu="5, 100, 200", fail=("tasklist",)))
        self.assertIn("active", out["unread"])
        self.assertFalse(out["active"])


class Loads(unittest.TestCase):

    def setUp(self):
        collect_rex._LAST.clear()

    def test_the_first_collection_has_no_cpu_figure_and_says_why(self):
        out = collect(Fake(tasklist=GONE, cpu="100", gpu="5, 100, 200"))
        self.assertIsNone(out["cpu_percent"])
        self.assertIn("cpu", out["unread"])

    def test_cpu_is_the_share_of_all_logical_processors(self):
        collect(Fake(tasklist=GONE, cpu="100", gpu="5, 100, 200"))
        later = NOW + datetime.timedelta(seconds=10)
        out = collect(Fake(tasklist=GONE, cpu="170", gpu="5, 100, 200"), at=later, cpus=20)
        self.assertEqual(35.0, out["cpu_percent"])
        self.assertNotIn("cpu", out["unread"])

    def test_cpu_is_clamped_to_the_whole_machine(self):
        collect(Fake(tasklist=GONE, cpu="0", gpu="5, 100, 200"))
        later = NOW + datetime.timedelta(seconds=1)
        out = collect(Fake(tasklist=GONE, cpu="900", gpu="5, 100, 200"), at=later, cpus=20)
        self.assertEqual(100.0, out["cpu_percent"])

    def test_a_server_that_restarted_resets_the_sample_instead_of_going_negative(self):
        collect(Fake(tasklist=GONE, cpu="500", gpu="5, 100, 200"))
        later = NOW + datetime.timedelta(seconds=5)
        out = collect(Fake(tasklist=GONE, cpu="3", gpu="5, 100, 200"), at=later)
        self.assertIsNone(out["cpu_percent"])

    def test_no_model_server_is_zero_cpu_seconds_not_unreadable(self):
        collect(Fake(tasklist=GONE, cpu="", gpu="5, 100, 200"))
        later = NOW + datetime.timedelta(seconds=5)
        out = collect(Fake(tasklist=GONE, cpu="", gpu="5, 100, 200"), at=later)
        self.assertEqual(0.0, out["cpu_percent"])

    def test_vram_and_cuda_come_from_nvidia_smi(self):
        out = collect(Fake(tasklist=GONE, cpu="1", gpu="37, 2777, 6144"))
        self.assertEqual(37.0, out["cuda_percent"])
        self.assertEqual(round(100.0 * 2777 / 6144, 1), out["vram_percent"])
        self.assertEqual((2777.0, 6144.0), (out["vram_used_mb"], out["vram_total_mb"]))

    def test_the_busiest_gpu_is_the_one_drawn(self):
        out = collect(Fake(tasklist=GONE, cpu="1", gpu="5, 100, 200\n60, 300, 400\n"))
        self.assertEqual(60.0, out["cuda_percent"])

    def test_no_nvidia_smi_is_unread_with_a_reason_and_no_zero(self):
        out = collect(Fake(tasklist=GONE, cpu="1", gpu="", fail=("nvidia-smi",)))
        self.assertIsNone(out["cuda_percent"])
        self.assertIsNone(out["vram_percent"])
        self.assertIn("gpu", out["unread"])

    def test_an_unparsable_gpu_line_is_unread(self):
        out = collect(Fake(tasklist=GONE, cpu="1", gpu="[N/A], [N/A], [N/A]"))
        self.assertIsNone(out["cuda_percent"])

    def test_a_timed_out_call_is_unread_not_a_crash(self):
        class Slow(Fake):
            def __call__(self, argv, timeout):
                if argv[0] == "nvidia-smi":
                    raise subprocess.TimeoutExpired(argv, timeout)
                return super().__call__(argv, timeout)

        out = collect(Slow(tasklist=GONE, cpu="1", gpu=""))
        self.assertIn("gpu", out["unread"])


class MachineLoad(unittest.TestCase):
    """The ring shows the whole machine, as the task manager does; the model
    server's own share stays in cpu_percent."""

    def setUp(self):
        collect_rex._LAST.clear()

    def test_the_whole_machine_load_is_reported_beside_the_server_share(self):
        out = collect(Fake(tasklist=GONE, cpu="100", gpu="5, 100, 200", machine="80"))
        self.assertEqual(80.0, out["machine_cpu_percent"])
        self.assertIsNone(out["cpu_percent"])

    def test_a_decimal_comma_is_read(self):
        out = collect(Fake(tasklist=GONE, cpu="1", gpu="5, 1, 2", machine="63,5"))
        self.assertEqual(63.5, out["machine_cpu_percent"])

    def test_an_unreadable_machine_load_is_none_with_its_reason(self):
        out = collect(Fake(tasklist=GONE, cpu="1", gpu="5, 1, 2", machine="not a number"))
        self.assertIsNone(out["machine_cpu_percent"])
        self.assertIn("machine_cpu", out["unread"])

    def test_the_load_is_clamped_to_a_percentage(self):
        out = collect(Fake(tasklist=GONE, cpu="1", gpu="5, 1, 2", machine="140"))
        self.assertEqual(100.0, out["machine_cpu_percent"])


class Safety(unittest.TestCase):

    def setUp(self):
        collect_rex._LAST.clear()

    def test_every_call_carries_the_configured_timeout(self):
        fake = Fake(tasklist=GONE, cpu="1", gpu="5, 100, 200")
        collect(fake)
        self.assertEqual({5}, {timeout for _argv, timeout in fake.calls})

    def test_a_process_name_that_is_not_a_plain_name_is_refused(self):
        bad = config(model_server_names={"value": ["ollama'; Remove-Item x #"]})
        with self.assertRaises(collect_rex.ConfigKeyError):
            collect_rex.collect(bad, Path("."), NOW, run=Fake(), logical_cpus=4)

    def test_a_missing_key_is_named(self):
        broken = config()
        del broken["rex"]["watchdog_process"]
        with self.assertRaises(collect_rex.ConfigKeyError) as caught:
            collect_rex.collect(broken, Path("."), NOW, run=Fake(), logical_cpus=4)
        self.assertIn("rex.watchdog_process", str(caught.exception))

    def test_the_shipped_configuration_carries_every_key_with_provenance(self):
        import json
        path = Path(__file__).resolve().parent.parent.parent / "observe-config.json"
        shipped = json.loads(path.read_text(encoding="utf-8"))
        for keys in (("ttl_seconds", "rex"), ("timeouts_seconds", "rex_probe"),
                     ("rex", "watchdog_process"), ("rex", "model_server_names")):
            node = shipped
            for key in keys:
                node = node[key]
            self.assertTrue(node.get("provenance"), ".".join(keys))
            self.assertIn("value", node)


LOG_NOW = datetime.datetime(2026, 11, 15, 12, 0, 0, tzinfo=datetime.timezone.utc)


def entry(value):
    """Wrap a value the way observe-config.json does."""
    return {"value": value, "provenance": "test fixture"}


def config_with_log(generating_max=1800):
    """The rex fixture config plus the keys collect_local.py reads."""
    out = config()
    out["paths"] = {"bridge_log": entry("~/.claude/loop-bridge-log.jsonl")}
    out["caps"] = {"local_calls_tail_bytes": entry(100000), "local_calls_recent": entry(3)}
    out["staleness_seconds"] = {"local_active": entry(60),
                                "local_generating_max": entry(generating_max)}
    return out


class LocalRoles(unittest.TestCase):
    """Rex wakes for a local role that is generating, whatever started it (Issue 118)."""

    def setUp(self):
        collect_rex._LAST.clear()
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.home = Path(self._tmp.name)

    def write_log(self, *records):
        path = self.home / ".claude" / "loop-bridge-log.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")

    def start(self, role, at):
        return {"event": "start", "at": at, "role": role, "tag": "tag-a", "num_ctx": 4096,
                "plan": None, "attempt": 1}

    def attempt(self, role, at):
        return {"at": at, "role": role, "tag": "tag-a", "num_ctx": 4096, "prompt_tokens": 5,
                "completion_tokens": 2, "plan": None, "attempt": 1, "accepted": True}

    def run_collect(self, tasklist=GONE, cfg=None, now=LOG_NOW):
        return collect_rex.collect(cfg or config_with_log(), self.home, now,
                                   run=Fake(tasklist=tasklist, cpu="10", gpu="5, 100, 200"),
                                   logical_cpus=20)

    def test_a_generating_local_role_wakes_rex_without_the_watchdog(self):
        self.write_log(self.start("ugs-grader", "2026-11-15T11:59:00+00:00"))
        out = self.run_collect()
        self.assertTrue(out["active"])
        self.assertEqual(out["local_generating"], ["ugs-grader"])

    def test_a_start_older_than_the_generation_limit_does_not_wake_rex(self):
        self.write_log(self.start("ugs-grader", "2026-11-15T10:00:00+00:00"))
        out = self.run_collect()
        self.assertFalse(out["active"])
        self.assertEqual(out["local_generating"], [])

    def test_a_role_whose_call_ended_does_not_wake_rex(self):
        self.write_log(self.start("ugs-grader", "2026-11-15T11:58:00+00:00"),
                       self.attempt("ugs-grader", "2026-11-15T11:59:00+00:00"))
        self.assertFalse(self.run_collect()["active"])

    def test_the_watchdog_alone_still_wakes_rex_with_an_empty_list(self):
        out = self.run_collect(tasklist=RUNNING)
        self.assertTrue(out["active"])
        self.assertEqual(out["local_generating"], [])

    def test_a_missing_bridge_log_is_nothing_to_read_not_an_unread_reading(self):
        out = self.run_collect()
        self.assertFalse(out["active"])
        self.assertNotIn("local_calls", out["unread"])

    def test_a_bridge_config_that_cannot_be_read_is_unread_with_its_reason(self):
        cfg = config_with_log()
        del cfg["caps"]["local_calls_tail_bytes"]
        out = self.run_collect(cfg=cfg)
        self.assertFalse(out["active"])
        self.assertIn("local_calls_tail_bytes", out["unread"]["local_calls"])

    def test_two_generating_roles_are_both_listed_sorted(self):
        self.write_log(self.start("ugs-vision", "2026-11-15T11:59:10+00:00"),
                       self.start("ugs-grader", "2026-11-15T11:59:20+00:00"))
        self.assertEqual(self.run_collect()["local_generating"], ["ugs-grader", "ugs-vision"])

    def test_a_naive_clock_is_read_as_utc_and_does_not_crash(self):
        self.write_log(self.start("ugs-grader", "2026-11-15T11:59:00+00:00"))
        naive = datetime.datetime(2026, 11, 15, 12, 0, 0)
        self.assertTrue(self.run_collect(now=naive)["active"])


if __name__ == "__main__":
    unittest.main()
