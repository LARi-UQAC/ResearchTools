"""Offline tests for pdf2md_convert. Log fixtures are verbatim snippets
from the real `mineru-kit parse --tier advanced` run this session (one
routing correctly via http-client, one that fell back to the in-process
engine, the regression this skill exists to prevent)."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pdf2md_convert import build_parse_args, launch_convert, parse_convert_log

REAL_CORRECTLY_ROUTED_LOG = """\
2026-10-10 11:33:56.773 | INFO     | mineru.model.vlm.runtime:_create_model:348 - get http-client predictor cost: 0.36s
2026-10-10 11:33:56.773 | INFO     | mineru.backend.analysis.pdf.window:_log_processing_window_plan:105 - Hybrid processing-window run. page_count=162, window_size=64, total_windows=3
2026-10-10 11:34:00.571 | INFO     | mineru.backend.analysis.pdf.window:_log_processing_window:113 - Hybrid processing window 1/3: pages 1-64/162 (64 pages)"""

REAL_IN_PROCESS_FALLBACK_LOG = """\
2026-10-10 11:02:16.779 | INFO     | mineru.model.vlm.selector:get_vlm_engine:61 - Using llama-cpp-engine as the inference engine for VLM.
0.01.598.489 W load_hparams: if you encounter problems with accuracy, try adding --image-min-tokens 1024"""


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


if __name__ == "__main__":
    unittest.main()
