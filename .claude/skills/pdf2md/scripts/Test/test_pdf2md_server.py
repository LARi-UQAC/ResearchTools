"""Offline tests for pdf2md_server. No real process is spawned (R20/R21):
launch_server and wait_for_server take injected popen/read_text/sleep/clock
callables. Log fixtures are verbatim from the real llama-server runs this
session (one that started clean with --image-min-tokens, one that didn't)."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pdf2md_server import (
    GRAMMAR_DEFAULT,
    ServerVerification,
    VlmPaths,
    build_llama_server_args,
    launch_server,
    verify_server_log,
    wait_for_server,
)

# Verbatim tail of a real llama-server run started WITH --image-min-tokens
# 1024 actually reaching the binary (this session, 2026-10-10): listening,
# no grounding warning.
REAL_HEALTHY_LOG = """\
0.00.372.021 I srv    load_model: loading model 'MinerU2.5-Pro-2605-1.2B-Q8_0.gguf'
0.03.546.101 I srv    load_model: loaded multimodal model, 'mmproj-MinerU2.5-Pro-2605-1.2B-Q8_0.gguf'
0.03.769.426 I srv    load_model: initializing, n_slots = 4, n_ctx_slot = 8192, kv_unified = 'false'
0.03.772.244 I srv  llama_server: model loaded
0.03.772.251 I srv  llama_server: listening on http://127.0.0.1:30000"""

# Verbatim tail of a real run WITHOUT --image-min-tokens (the original
# failing case the skill exists to fix) -- still listens, but the warning
# is present, meaning accuracy is degraded even though the server is "up".
REAL_WARNING_STILL_PRESENT_LOG = """\
0.07.065.333 W load_hparams: Qwen-VL models require at minimum 1024 image tokens to function correctly on grounding tasks
0.07.065.347 W load_hparams: if you encounter problems with accuracy, try adding --image-min-tokens 1024
0.07.356.764 I srv  llama_server: listening on http://127.0.0.1:30000"""


class TestBuildLlamaServerArgs(unittest.TestCase):
    def setUp(self):
        self.paths = VlmPaths(
            binary="/fake/llama-server.exe",
            model_gguf="/fake/model.gguf",
            mmproj_gguf="/fake/mmproj.gguf",
            alias="FakeModel",
            n_ctx_train=8192,
        )

    def test_grammar_passed_as_one_argv_element_not_split(self):
        # This is the whole point: build the args as a Python list so
        # subprocess.Popen quotes it correctly, unlike mineru's own
        # os.execv wrapper (which does not) or PowerShell 5.1's
        # Start-Process -ArgumentList array (same bug, one layer over).
        args = build_llama_server_args(self.paths)
        self.assertIn(GRAMMAR_DEFAULT, args)
        # Negative control: the grammar string must appear as ONE element,
        # never split into "root", "::=", ".*" as separate argv entries.
        self.assertNotIn("::=", args)

    def test_ctx_size_is_trained_context_times_parallel(self):
        args = build_llama_server_args(self.paths, n_parallel=4)
        ctx_index = args.index("--ctx-size") + 1
        self.assertEqual(args[ctx_index], str(8192 * 4))

    def test_image_min_tokens_included(self):
        args = build_llama_server_args(self.paths, image_min_tokens=1024)
        self.assertIn("--image-min-tokens", args)
        self.assertIn("1024", args)

    def test_model_and_mmproj_paths_present(self):
        args = build_llama_server_args(self.paths)
        self.assertIn(self.paths.model_gguf, args)
        self.assertIn(self.paths.mmproj_gguf, args)

    def test_binary_is_first_argv_element(self):
        args = build_llama_server_args(self.paths)
        self.assertEqual(args[0], self.paths.binary)


class TestVerifyServerLog(unittest.TestCase):
    def test_healthy_log_reports_listening_and_no_warning(self):
        verification = verify_server_log(REAL_HEALTHY_LOG)
        self.assertTrue(verification.listening)
        self.assertFalse(verification.image_min_tokens_warning_present)
        self.assertTrue(verification.healthy)

    def test_warning_still_present_is_not_healthy_even_though_listening(self):
        # The regression this test guards: "it's listening" is not enough
        # to call the fix successful -- the warning reappearing means
        # --image-min-tokens did not actually reach the binary.
        verification = verify_server_log(REAL_WARNING_STILL_PRESENT_LOG)
        self.assertTrue(verification.listening)
        self.assertTrue(verification.image_min_tokens_warning_present)
        self.assertFalse(verification.healthy)

    def test_empty_log_is_not_listening(self):
        verification = verify_server_log("")
        self.assertFalse(verification.listening)
        self.assertFalse(verification.healthy)


class TestWaitForServer(unittest.TestCase):
    def test_returns_as_soon_as_healthy_without_exhausting_timeout(self):
        reads = iter(["", "", REAL_HEALTHY_LOG])
        sleeps = []
        clock_calls = [0.0]

        def fake_clock():
            return clock_calls[0]

        def fake_sleep(seconds):
            sleeps.append(seconds)
            clock_calls[0] += seconds

        verification = wait_for_server(
            None, timeout_s=60.0, poll_interval_s=1.0,
            read_text=lambda _path: next(reads),
            sleep=fake_sleep,
            clock=fake_clock,
        )
        self.assertTrue(verification.healthy)
        self.assertEqual(len(sleeps), 2)  # two failed reads before the healthy one

    def test_gives_up_at_timeout_and_reports_last_verification(self):
        # Negative control: a log that never becomes healthy must not hang.
        clock_calls = [0.0]

        def fake_clock():
            return clock_calls[0]

        def fake_sleep(seconds):
            clock_calls[0] += seconds

        verification = wait_for_server(
            None, timeout_s=5.0, poll_interval_s=1.0,
            read_text=lambda _path: "",
            sleep=fake_sleep,
            clock=fake_clock,
        )
        self.assertFalse(verification.healthy)
        self.assertGreaterEqual(clock_calls[0], 5.0)


class TestLaunchServer(unittest.TestCase):
    def test_popen_called_with_the_given_args_list(self):
        captured = {}

        class FakePopen:
            def __init__(self, args, **kwargs):
                captured["args"] = args
                captured["kwargs"] = kwargs
                self.pid = 4242

        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "server.log"
            process = launch_server(["binary", "--flag"], log_path, popen=FakePopen)

        self.assertEqual(captured["args"], ["binary", "--flag"])
        self.assertEqual(process.pid, 4242)


if __name__ == "__main__":
    unittest.main()
