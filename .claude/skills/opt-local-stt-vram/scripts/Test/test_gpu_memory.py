"""Per-process GPU memory reads, with every process call replaced by a fake.

The Windows path reads the GPU Process Memory performance counters because nvidia-smi
under WDDM cannot say whose memory is whose (measured 2026-09-26). Each unanswerable case
must raise GpuMemoryUnavailable with a reason, never return a zero that reads like a
measurement (R8).
"""
import subprocess
import sys
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import gpu_memory  # noqa: E402


def runner_returning(stdout, returncode=0):
    calls = []

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, returncode, stdout=stdout, stderr="")
    run.calls = calls
    return run


def runner_raising(exc):
    def run(argv, **kwargs):
        raise exc
    return run


class WindowsCountersCase(unittest.TestCase):
    def test_dedicated_and_shared_are_parsed(self):
        run = runner_returning("929 76\n")
        mem = gpu_memory.process_memory_mib(1234, timeout_s=30, runner=run, platform="win32")
        self.assertEqual(mem, {"dedicated_mib": 929, "shared_mib": 76})
        argv, kwargs = run.calls[0]
        self.assertIn("pid_1234", " ".join(argv))
        self.assertEqual(kwargs["timeout"], 30)

    def test_no_counter_output_is_unavailable_not_zero(self):
        with self.assertRaises(gpu_memory.GpuMemoryUnavailable):
            gpu_memory.process_memory_mib(1234, timeout_s=30, runner=runner_returning(""),
                                          platform="win32")

    def test_a_timeout_is_unavailable_with_its_reason(self):
        run = runner_raising(subprocess.TimeoutExpired(["powershell"], 30))
        with self.assertRaises(gpu_memory.GpuMemoryUnavailable) as ctx:
            gpu_memory.process_memory_mib(1234, timeout_s=30, runner=run, platform="win32")
        self.assertIn("timed out", str(ctx.exception))


class NvidiaSmiCase(unittest.TestCase):
    def test_the_pid_row_is_read_and_shared_is_unknown(self):
        run = runner_returning("99, 5000\n1234, 600\n")
        mem = gpu_memory.process_memory_mib(1234, timeout_s=30, runner=run, platform="linux")
        self.assertEqual(mem, {"dedicated_mib": 600, "shared_mib": None})

    def test_a_pid_not_on_the_gpu_is_unavailable(self):
        with self.assertRaises(gpu_memory.GpuMemoryUnavailable):
            gpu_memory.process_memory_mib(1234, timeout_s=30,
                                          runner=runner_returning("99, 5000\n"),
                                          platform="linux")

    def test_a_missing_nvidia_smi_is_unavailable(self):
        with self.assertRaises(gpu_memory.GpuMemoryUnavailable) as ctx:
            gpu_memory.process_memory_mib(1234, timeout_s=30,
                                          runner=runner_raising(FileNotFoundError("nvidia-smi")),
                                          platform="linux")
        self.assertIn("nvidia-smi", str(ctx.exception))


class OtherProcessesCase(unittest.TestCase):
    def test_every_other_process_holding_vram_is_listed(self):
        run = runner_returning("28004 4819\n13944 929\n555 0\n")
        others = gpu_memory.other_gpu_processes([28004], timeout_s=30, runner=run,
                                                platform="win32")
        self.assertEqual(others, {13944: 929})

    def test_a_clean_card_lists_nothing(self):
        others = gpu_memory.other_gpu_processes([28004], timeout_s=30,
                                                runner=runner_returning("28004 4819\n"),
                                                platform="win32")
        self.assertEqual(others, {})

    def test_elsewhere_nvidia_smi_lists_the_processes(self):
        others = gpu_memory.other_gpu_processes([1], timeout_s=30,
                                                runner=runner_returning("1, 5000\n77, 800\n"),
                                                platform="linux")
        self.assertEqual(others, {77: 800})


class LlmPidCase(unittest.TestCase):
    def test_the_first_matching_process_is_returned(self):
        pid = gpu_memory.find_llm_pid(["llama-server"], timeout_s=30,
                                      runner=runner_returning("28004\n31000\n"),
                                      platform="win32")
        self.assertEqual(pid, 28004)

    def test_no_llm_process_is_unavailable_naming_what_was_searched(self):
        with self.assertRaises(gpu_memory.GpuMemoryUnavailable) as ctx:
            gpu_memory.find_llm_pid(["llama-server"], timeout_s=30,
                                    runner=runner_returning(""), platform="win32")
        self.assertIn("llama-server", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
