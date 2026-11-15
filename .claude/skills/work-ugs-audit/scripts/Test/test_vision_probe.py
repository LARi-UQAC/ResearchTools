import sys
import os
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

# Put the parent folder of the test folder (scripts) at the start of sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import vision_probe
from vision_probe import probe, main, NotRun

class TestVisionProbe(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = Path(tempfile.mkdtemp())
        self.image_path = self.tmp_dir / "test.png"
        self.image_path.touch()
        self.expected = {
            "x_title": "Time",
            "y_title": "Voltage",
            "unit": "V",
            "curve_count": 2
        }
        self.prompt = "Describe the chart."
        self.schema = {"type": "object"}

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def make_call_usage(self, responses):
        """
        Purpose: Create a mock call_usage function.
        Inputs:
            responses: list of (answer, usage) tuples or exceptions.
        Outputs:
            function that returns the responses in order.
        """
        calls = iter(responses)
        def _call(prompt, schema, images=None):
            try:
                return next(calls)
            except StopIteration:
                raise AssertionError("Too many calls")
        return _call

    def test_probe_passes_when_the_four_facts_come_back(self):
        answer = {
            "x_title": "Time",
            "y_title": "Voltage",
            "unit": "V",
            "curve_count": 2
        }
        usage_with = {"prompt_tokens": 100}
        usage_without = {"prompt_tokens": 50}
        
        call_usage = self.make_call_usage([
            (answer, usage_with),
            (answer, usage_without)
        ])
        
        result = probe(call_usage, self.image_path, self.expected, self.prompt, self.schema)
        self.assertTrue(result["ok"])
        self.assertEqual(result["image_tokens"], 50)
        self.assertEqual(result["answers"], answer)

    def test_probe_fails_on_a_wrong_axis_title(self):
        answer = {
            "x_title": "Wrong",
            "y_title": "Voltage",
            "unit": "V",
            "curve_count": 2
        }
        usage = {"prompt_tokens": 100}
        
        call_usage = self.make_call_usage([
            (answer, usage),
            (answer, usage)
        ])
        
        result = probe(call_usage, self.image_path, self.expected, self.prompt, self.schema)
        self.assertFalse(result["ok"])

    def test_probe_fails_on_a_wrong_curve_count(self):
        answer = {
            "x_title": "Time",
            "y_title": "Voltage",
            "unit": "V",
            "curve_count": 3
        }
        usage = {"prompt_tokens": 100}
        
        call_usage = self.make_call_usage([
            (answer, usage),
            (answer, usage)
        ])
        
        result = probe(call_usage, self.image_path, self.expected, self.prompt, self.schema)
        self.assertFalse(result["ok"])

    def test_comparison_ignores_case_accents_and_spaces(self):
        answer = {
            "x_title": "  t i m e  ",
            "y_title": "VoltaGe",
            "unit": "v",
            "curve_count": 2
        }
        usage = {"prompt_tokens": 100}
        
        call_usage = self.make_call_usage([
            (answer, usage),
            (answer, usage)
        ])
        
        result = probe(call_usage, self.image_path, self.expected, self.prompt, self.schema)
        self.assertTrue(result["ok"])

    def test_not_run_on_the_first_call_is_not_ok_with_its_kind(self):
        err = NotRun("unreachable", "network error")
        call_usage = self.make_call_usage([
            err,
            ({}, {})
        ])
        
        result = probe(call_usage, self.image_path, self.expected, self.prompt, self.schema)
        self.assertFalse(result["ok"])
        self.assertEqual(result["kind"], "unreachable")
        self.assertIsNone(result["answers"])
        self.assertIsNone(result["image_tokens"])

    def test_image_tokens_is_the_difference_of_the_two_prompt_counts(self):
        answer = self.expected
        usage_with = {"prompt_tokens": 200}
        usage_without = {"prompt_tokens": 150}
        
        call_usage = self.make_call_usage([
            (answer, usage_with),
            (answer, usage_without)
        ])
        
        result = probe(call_usage, self.image_path, self.expected, self.prompt, self.schema)
        self.assertEqual(result["image_tokens"], 50)

    def test_missing_count_gives_none(self):
        answer = self.expected
        usage_with = {}
        usage_without = {"prompt_tokens": 150}
        
        call_usage = self.make_call_usage([
            (answer, usage_with),
            (answer, usage_without)
        ])
        
        result = probe(call_usage, self.image_path, self.expected, self.prompt, self.schema)
        self.assertIsNone(result["image_tokens"])

    def test_main_writes_the_verdict_file_inside_the_work_folder(self):
        # Setup work dir
        work_dir = self.tmp_dir / "work"
        work_dir.mkdir()
        
        # Image must be inside work_dir
        image_path = work_dir / "test.png"
        image_path.touch()
        
        # Mock probe to avoid real calls
        original_probe = vision_probe.probe
        vision_probe.probe = MagicMock(return_value={"ok": True, "image_tokens": 10, "kind": None, "answers": {}})
        
        try:
            # We need to mock config loading too or provide a valid expected file
            expected_file = work_dir / "expected.json"
            expected_file.write_text(json.dumps(self.expected))
            
            argv = ["--work", str(work_dir), "--image", str(image_path), "--expected", str(expected_file)]
            
            # Mock config
            original_load = vision_probe.load_config
            vision_probe.load_config = MagicMock(return_value={
                "roles.vision": "role-name",
                "driver.request_timeout_s": 10,
                "driver.count_timeout_s": 20,
                "driver.reply_reserve_tokens": 100,
                "driver.image_tokens_fallback": 50,
                "driver.max_image_bytes": 1000,
            })
            
            exit_code = main(argv)
            self.assertEqual(exit_code, 0)
            
            vision_probe_file = work_dir / "vision_probe.json"
            self.assertTrue(vision_probe_file.exists())
            data = json.loads(vision_probe_file.read_text())
            self.assertTrue(data["ok"])
        finally:
            vision_probe.probe = original_probe
            if hasattr(vision_probe, 'load_config'):
                vision_probe.load_config = original_load

    def test_main_refuses_a_path_outside_the_work_folder(self):
        work_dir = self.tmp_dir / "work"
        work_dir.mkdir()
        
        outside_image = self.tmp_dir / "outside.png"
        outside_image.touch()
        
        expected_file = work_dir / "expected.json"
        expected_file.write_text(json.dumps(self.expected))
        
        argv = ["--work", str(work_dir), "--image", str(outside_image), "--expected", str(expected_file)]
        
        exit_code = main(argv)
        self.assertEqual(exit_code, 2)

    def test_dry_run_writes_nothing(self):
        work_dir = self.tmp_dir / "work"
        work_dir.mkdir()
        
        # Image must be inside work_dir
        image_path = work_dir / "test.png"
        image_path.touch()
        
        expected_file = work_dir / "expected.json"
        expected_file.write_text(json.dumps(self.expected))
        
        argv = ["--work", str(work_dir), "--image", str(image_path), "--expected", str(expected_file), "--dry-run"]

        # A dry run calls no model: a probe or a call that is reached fails the test
        boom = MagicMock(side_effect=AssertionError("no model call in a dry run"))
        original_probe = vision_probe.probe
        vision_probe.probe = boom
        try:
            exit_code = main(argv, call_usage=boom)
        finally:
            vision_probe.probe = original_probe
        self.assertEqual(exit_code, 0)

        vision_probe_file = work_dir / "vision_probe.json"
        self.assertFalse(vision_probe_file.exists())
        self.assertEqual(sorted(p.name for p in work_dir.iterdir()), ["expected.json", "test.png"])

    def test_missing_configuration_key_is_a_refusal_naming_it(self):
        work_dir = self.tmp_dir / "work"
        work_dir.mkdir()
        image_path = work_dir / "test.png"
        image_path.touch()
        expected_file = work_dir / "expected.json"
        expected_file.write_text(json.dumps(self.expected))
        original_load = vision_probe.load_config

        def refusing(path):
            raise vision_probe.ConfigError("missing required key 'roles.vision'")

        vision_probe.load_config = refusing
        try:
            exit_code = main(["--work", str(work_dir), "--image", str(image_path), "--expected", str(expected_file)])
        finally:
            vision_probe.load_config = original_load
        self.assertEqual(exit_code, 2)

if __name__ == "__main__":
    unittest.main()
