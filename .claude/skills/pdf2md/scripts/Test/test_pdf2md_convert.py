"""Offline tests for pdf2md_convert. Log fixtures are verbatim snippets
from the real `mineru-kit parse --tier advanced` run this session (one
routing correctly via http-client, one that fell back to the in-process
engine, the regression this skill exists to prevent)."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pdf2md_convert import _main, build_parse_args, launch_convert, parse_convert_log

REAL_CORRECTLY_ROUTED_LOG = """\
2026-10-10 11:33:56.773 | INFO     | mineru.model.vlm.runtime:_create_model:348 - get http-client predictor cost: 0.36s
2026-10-10 11:33:56.773 | INFO     | mineru.backend.analysis.pdf.window:_log_processing_window_plan:105 - Hybrid processing-window run. page_count=162, window_size=64, total_windows=3
2026-10-10 11:34:00.571 | INFO     | mineru.backend.analysis.pdf.window:_log_processing_window:113 - Hybrid processing window 1/3: pages 1-64/162 (64 pages)"""

REAL_IN_PROCESS_FALLBACK_LOG = """\
2026-10-10 11:02:16.779 | INFO     | mineru.model.vlm.selector:get_vlm_engine:61 - Using llama-cpp-engine as the inference engine for VLM.
0.01.598.489 W load_hparams: if you encounter problems with accuracy, try adding --image-min-tokens 1024"""

# Verbatim tail of a real run that crashed mid-conversion, 2026-10-10: a
# Vulkan GPU driver fault killed the VLM server while the conversion was
# correctly routed through it (window 1/3, "Layout Predict" complete,
# "Two Step Extraction" just starting). "Error: Failed to parse {path}:
# {error}" is mineru-kit's own GENERIC terminal-failure template, confirmed
# in mineru/utils/translations.py (the exact counterpart of the success
# template "Parsed {count} input(s)." that _PARSED_RE already matches) --
# not an artifact specific to this one GPU crash.
REAL_CRASHED_LOG = REAL_CORRECTLY_ROUTED_LOG + """
Layout Predict: 100%|##########| 64/64 [01:08<00:00,  1.07s/it]
Two Step Extraction:   0%|          | 0/64 [00:50<?, ?it/s]
Error: Failed to parse C:\\Martin
Otis\\Recherche\\TheseMaitrise\\2026\\ShokoufehNaderi\\these.pdf: Unexpected status
code: [500], response body: {"error":{"code":500,"message":"got exception:
vk::Queue::submit: ErrorDeviceLost","type":"server_error"}}"""


class TestBuildParseArgs(unittest.TestCase):
    def test_never_includes_disable_image_analysis(self):
        args = build_parse_args("thesis.pdf", "./out")
        self.assertNotIn("--disable-image-analysis", args)

    def test_ocr_mode_not_forced(self):
        # Negative control: never pass --ocr-mode ocr, which is LESS
        # accurate than the native text layer where one exists.
        args = build_parse_args("thesis.pdf", "./out")
        self.assertNotIn("--ocr-mode", args)

    def test_tier_and_format_passed_through(self):
        args = build_parse_args("thesis.pdf", "./out", tier="advanced", output_format="markdown")
        self.assertIn("advanced", args)
        self.assertIn("markdown", args)

    def test_pdf_and_output_dir_present(self):
        args = build_parse_args("thesis.pdf", "./out")
        self.assertIn("thesis.pdf", args)
        self.assertIn("./out", args)


class TestParseConvertLog(unittest.TestCase):
    def test_correctly_routed_log_reports_true(self):
        progress = parse_convert_log(REAL_CORRECTLY_ROUTED_LOG)
        self.assertTrue(progress.routed_via_vlm_server)

    def test_in_process_fallback_log_reports_false(self):
        # The regression this skill exists to prevent: if this ever comes
        # back True (or None) on this exact fixture, the config/server
        # wiring silently regressed.
        progress = parse_convert_log(REAL_IN_PROCESS_FALLBACK_LOG)
        self.assertFalse(progress.routed_via_vlm_server)

    def test_unknown_yet_is_none_not_false(self):
        # Before either line has appeared (process just started), routing
        # status must read as "not yet known", not be misread as "failed".
        progress = parse_convert_log("")
        self.assertIsNone(progress.routed_via_vlm_server)

    def test_current_window_parsed(self):
        progress = parse_convert_log(REAL_CORRECTLY_ROUTED_LOG)
        self.assertEqual(progress.current_window, (1, 3))

    def test_finished_detected_from_success_line(self):
        progress = parse_convert_log("Parsed 1 input(s).")
        self.assertTrue(progress.finished)

    def test_not_finished_when_no_success_line(self):
        progress = parse_convert_log(REAL_CORRECTLY_ROUTED_LOG)
        self.assertFalse(progress.finished)

    def test_no_error_detected_on_a_healthy_in_progress_log(self):
        # Negative control: an ordinary in-progress log (no crash) must
        # never be misread as failed.
        progress = parse_convert_log(REAL_CORRECTLY_ROUTED_LOG)
        self.assertIsNone(progress.error)

    def test_crashed_run_is_detected_as_an_error_not_as_still_running(self):
        # Regression: a process that crashed mid-conversion used to report
        # finished=False forever, indistinguishable from "still running" --
        # measured live 2026-10-10 when a Vulkan driver fault killed the
        # VLM server and `convert status` kept reporting finished=false
        # with no indication anything had gone wrong.
        progress = parse_convert_log(REAL_CRASHED_LOG)
        self.assertIsNotNone(progress.error)
        self.assertIn("ErrorDeviceLost", progress.error)
        self.assertFalse(progress.finished)

    def test_crashed_run_still_reports_the_routing_and_window_it_reached(self):
        # A failure must not blank out the progress already parsed before
        # it -- knowing it crashed during window 1/3, correctly routed, is
        # useful diagnostic context.
        progress = parse_convert_log(REAL_CRASHED_LOG)
        self.assertTrue(progress.routed_via_vlm_server)
        self.assertEqual(progress.current_window, (1, 3))


class TestLaunchConvert(unittest.TestCase):
    def test_popen_receives_the_built_args(self):
        captured = {}

        class FakePopen:
            def __init__(self, args, **kwargs):
                captured["args"] = args
                self.pid = 1234

        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "convert.log"
            process = launch_convert(["mineru-kit", "parse", "x.pdf"], log_path, popen=FakePopen)

        self.assertEqual(captured["args"], ["mineru-kit", "parse", "x.pdf"])
        self.assertEqual(process.pid, 1234)


class TestStatusCliReportsFailure(unittest.TestCase):
    """CLI-level proof that `convert status` surfaces a crash, not only
    the pure parse_convert_log() function underneath it."""

    def test_ok_is_false_and_error_present_for_a_crashed_log(self):
        import io
        import json
        import tempfile
        from contextlib import redirect_stdout
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "convert.log"
            log_path.write_text(REAL_CRASHED_LOG, encoding="utf-8")
            buf = io.StringIO()
            with redirect_stdout(buf):
                exit_code = _main(["status", "--log", str(log_path), "--json"])
        report = json.loads(buf.getvalue())
        self.assertEqual(exit_code, 0)  # reporting a failure is itself a successful status check
        self.assertFalse(report["ok"])
        self.assertIn("ErrorDeviceLost", report["error"])

    def test_ok_is_true_and_error_is_none_for_a_healthy_log(self):
        import io
        import json
        import tempfile
        from contextlib import redirect_stdout
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "convert.log"
            log_path.write_text(REAL_CORRECTLY_ROUTED_LOG, encoding="utf-8")
            buf = io.StringIO()
            with redirect_stdout(buf):
                _main(["status", "--log", str(log_path), "--json"])
        report = json.loads(buf.getvalue())
        self.assertTrue(report["ok"])
        self.assertIsNone(report["error"])


if __name__ == "__main__":
    unittest.main()
