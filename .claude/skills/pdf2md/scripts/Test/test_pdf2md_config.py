"""Offline tests for pdf2md_config: diagnose/apply_fixes against the exact
config.yaml shape measured this session (a top-level vlm: key that pydantic
silently ignores, and llm_aided.max_concurrency defaulting to 16)."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import yaml

from pdf2md_config import DEFAULT_MAX_CONCURRENCY_CAP, apply_fixes, diagnose, render_config_yaml

REAL_BROKEN_CONFIG_TEXT = """
llm_aided:
  api_key: "ollama"
  base_url: "http://localhost:11434/v1"
  model: "Qwen3.8-maxctx"
  enable_thinking: false
  max_concurrency: 16
  features:
    title_leveling: true
    cross_page_table_cell_merge: true

vlm:
  image_min_tokens: 1024
"""


class TestDiagnose(unittest.TestCase):
    def test_top_level_vlm_key_is_flagged(self):
        config = yaml.safe_load(REAL_BROKEN_CONFIG_TEXT)
        diagnosis = diagnose(config, expected_server_url="http://127.0.0.1:30000/v1")
        codes = {issue.code for issue in diagnosis.issues}
        self.assertIn("vlm_wrong_nesting", codes)

    def test_server_url_missing_is_flagged_when_one_is_expected(self):
        config = yaml.safe_load(REAL_BROKEN_CONFIG_TEXT)
        diagnosis = diagnose(config, expected_server_url="http://127.0.0.1:30000/v1")
        codes = {issue.code for issue in diagnosis.issues}
        self.assertIn("server_url_unset", codes)

    def test_server_url_not_checked_when_none_expected(self):
        # Negative control: before a server exists, we must not flag its absence.
        config = yaml.safe_load(REAL_BROKEN_CONFIG_TEXT)
        diagnosis = diagnose(config, expected_server_url=None)
        codes = {issue.code for issue in diagnosis.issues}
        self.assertNotIn("server_url_unset", codes)

    def test_high_max_concurrency_is_flagged(self):
        config = yaml.safe_load(REAL_BROKEN_CONFIG_TEXT)
        diagnosis = diagnose(config, expected_server_url=None)
        codes = {issue.code for issue in diagnosis.issues}
        self.assertIn("max_concurrency_too_high", codes)
        self.assertTrue(diagnosis.has_llm_aided)

    def test_concurrency_not_flagged_when_no_llm_aided_block(self):
        # Negative control: an operator who never set up llm_aided should
        # not be told to fix a block they never opted into.
        diagnosis = diagnose({}, expected_server_url=None)
        self.assertFalse(diagnosis.has_llm_aided)
        codes = {issue.code for issue in diagnosis.issues}
        self.assertNotIn("max_concurrency_too_high", codes)

    def test_clean_config_has_no_issues(self):
        clean = {
            "llm_aided": {"max_concurrency": 1},
            "model": {"vlm": {"server_url": "http://127.0.0.1:30000/v1"}},
        }
        diagnosis = diagnose(clean, expected_server_url="http://127.0.0.1:30000/v1")
        self.assertTrue(diagnosis.clean)

    def test_missing_file_as_empty_dict_does_not_raise(self):
        diagnosis = diagnose({}, expected_server_url=None)
        self.assertIsInstance(diagnosis.issues, list)


class TestApplyFixes(unittest.TestCase):
    def test_top_level_vlm_key_removed(self):
        config = yaml.safe_load(REAL_BROKEN_CONFIG_TEXT)
        fixed = apply_fixes(config, server_url="http://127.0.0.1:30000/v1")
        self.assertNotIn("vlm", fixed)

    def test_server_url_set_under_model(self):
        config = yaml.safe_load(REAL_BROKEN_CONFIG_TEXT)
        fixed = apply_fixes(config, server_url="http://127.0.0.1:30000/v1")
        self.assertEqual(fixed["model"]["vlm"]["server_url"], "http://127.0.0.1:30000/v1")

    def test_max_concurrency_capped(self):
        config = yaml.safe_load(REAL_BROKEN_CONFIG_TEXT)
        fixed = apply_fixes(config, server_url=None, max_concurrency_cap=2)
        self.assertEqual(fixed["llm_aided"]["max_concurrency"], 2)

    def test_concurrency_already_low_is_left_alone(self):
        config = {"llm_aided": {"max_concurrency": 1}}
        fixed = apply_fixes(config, server_url=None, max_concurrency_cap=2)
        self.assertEqual(fixed["llm_aided"]["max_concurrency"], 1)

    def test_no_llm_aided_block_is_not_created(self):
        # apply_fixes must not invent an llm_aided block for an operator
        # who never configured one.
        fixed = apply_fixes({}, server_url="http://127.0.0.1:30000/v1")
        self.assertNotIn("llm_aided", fixed)

    def test_server_url_none_leaves_model_vlm_untouched(self):
        config = {"model": {"vlm": {"server_url": "http://old:9999/v1"}}}
        fixed = apply_fixes(config, server_url=None)
        self.assertEqual(fixed["model"]["vlm"]["server_url"], "http://old:9999/v1")

    def test_diagnose_after_apply_fixes_is_clean(self):
        # End-to-end: the exact broken config this session measured, fixed,
        # must re-diagnose as clean.
        config = yaml.safe_load(REAL_BROKEN_CONFIG_TEXT)
        fixed = apply_fixes(config, server_url="http://127.0.0.1:30000/v1")
        diagnosis = diagnose(fixed, expected_server_url="http://127.0.0.1:30000/v1")
        self.assertTrue(diagnosis.clean)

    def test_default_cap_constant_is_low(self):
        self.assertLessEqual(DEFAULT_MAX_CONCURRENCY_CAP, 2)


class TestRenderConfigYaml(unittest.TestCase):
    def test_round_trips_through_yaml(self):
        fixed = {"model": {"vlm": {"server_url": "http://127.0.0.1:30000/v1"}}, "llm_aided": {"max_concurrency": 1}}
        text = render_config_yaml(fixed, date="2026-10-10")
        reparsed = yaml.safe_load(text)
        self.assertEqual(reparsed, fixed)

    def test_header_comment_present(self):
        text = render_config_yaml({}, date="2026-10-10")
        self.assertIn("2026-10-10", text)
        self.assertIn("model.vlm", text)


if __name__ == "__main__":
    unittest.main()
