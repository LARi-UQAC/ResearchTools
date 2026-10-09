"""
test_wp_config.py - offline tests for wp_errors.py and wp_config.py.

Proves: the four shipped config keys and their values/provenance, the
missing-key and missing-provenance refusals naming their source, the
missing-file and invalid-JSON refusals, and the exit-code mapping
(WpRefusal -> 2, any other exception -> 1).
"""
import json
import tempfile
import unittest
from pathlib import Path

import _fixtures  # noqa: F401  (inserts SCRIPTS on sys.path)

import wp_errors
import wp_config


class TestShippedConfig(unittest.TestCase):
    def test_shipped_values(self):
        cfg = wp_config.load_config()
        self.assertEqual(wp_config.config_value(cfg, "http.timeout_s", "x.json"), 30)
        self.assertEqual(wp_config.config_value(cfg, "http.get_retries", "x.json"), 2)
        self.assertEqual(wp_config.config_value(cfg, "http.retry_backoff_s", "x.json"), 2)
        self.assertEqual(wp_config.config_value(cfg, "rest.per_page", "x.json"), 100)
        self.assertEqual(wp_config.config_value(cfg, "preview.snippet_chars", "x.json"), 400)

    def test_every_key_has_provenance(self):
        cfg = wp_config.load_config()
        for dotted in (
            "http.timeout_s",
            "http.get_retries",
            "http.retry_backoff_s",
            "rest.per_page",
            "preview.snippet_chars",
        ):
            parts = dotted.split(".")
            node = cfg
            for part in parts:
                node = node[part]
            self.assertIsInstance(node.get("provenance"), str)
            self.assertTrue(node["provenance"].strip())


class TestConfigValueRefusals(unittest.TestCase):
    def test_missing_key_is_named(self):
        cfg = wp_config.load_config()
        with self.assertRaises(wp_errors.WpRefusal) as ctx:
            wp_config.config_value(cfg, "http.nope", "x.json")
        message = str(ctx.exception)
        self.assertIn("http.nope", message)
        self.assertIn("x.json", message)

    def test_node_without_provenance_refused(self):
        cfg = {"http": {"timeout_s": {"value": 1}}}
        with self.assertRaises(wp_errors.WpRefusal):
            wp_config.config_value(cfg, "http.timeout_s", "x.json")

    def test_missing_file_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "nope.json"
            with self.assertRaises(wp_errors.WpRefusal):
                wp_config.load_config(missing)

    def test_invalid_json_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "bad.json"
            bad.write_text("{not json", encoding="utf-8")
            with self.assertRaises(wp_errors.WpRefusal):
                wp_config.load_config(bad)


class TestExitCodeMapping(unittest.TestCase):
    def test_exit_code_mapping(self):
        self.assertEqual(wp_errors.exit_code_for(wp_errors.WpRefusal("x")), 2)
        self.assertEqual(wp_errors.exit_code_for(wp_errors.WpSyncError("x")), 1)
        self.assertEqual(wp_errors.exit_code_for(ValueError()), 1)


class TestStatusCode(unittest.TestCase):
    def test_default_is_none(self):
        self.assertIsNone(wp_errors.WpSyncError("x").status_code)

    def test_can_be_set(self):
        self.assertEqual(wp_errors.WpSyncError("x", status_code=400).status_code, 400)


if __name__ == "__main__":
    unittest.main()
