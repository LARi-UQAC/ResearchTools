"""Offline tests for pdf2md_models.parse_models_show, pinned to the exact
`mineru-kit models show` output captured this session."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pdf2md_models import DOWNLOADABLE_TIERS, bootstrap_tier_for, parse_models_show

# Verbatim output of `mineru-kit models show`, captured 2026-10-10
# (the Config: path line is replaced with a placeholder account to avoid
# naming a real account path in a tracked fixture -- R34/security.md).
REAL_MODELS_SHOW_OUTPUT = """\
Config: C:\\Users\\example\\.mineru\\config.yaml
Config exists: true
Effective small backend: onnx
Effective VLM engine: llama-cpp
Repos:
  MinerU-4_models_torch: missing
  MinerU-4_models_onnx: ready
  MinerU2.5-Pro-2605-1.2B: missing
  MinerU2.5-Pro-2605-1.2B-GGUF: ready
Model tiers:
  basic: MinerU-4_models_onnx
  standard: MinerU-4_models_onnx, MinerU2.5-Pro-2605-1.2B-GGUF"""


class TestParseModelsShow(unittest.TestCase):
    def test_ready_and_missing_repos_parsed(self):
        readiness = parse_models_show(REAL_MODELS_SHOW_OUTPUT)
        self.assertTrue(readiness.repo_status["MinerU2.5-Pro-2605-1.2B-GGUF"])
        self.assertFalse(readiness.repo_status["MinerU-4_models_torch"])

    def test_standard_tier_needs_both_its_repos(self):
        readiness = parse_models_show(REAL_MODELS_SHOW_OUTPUT)
        self.assertEqual(
            readiness.tier_repos["standard"],
            ["MinerU-4_models_onnx", "MinerU2.5-Pro-2605-1.2B-GGUF"],
        )

    def test_standard_tier_ready_when_all_its_repos_are_ready(self):
        readiness = parse_models_show(REAL_MODELS_SHOW_OUTPUT)
        self.assertTrue(readiness.tier_ready("standard"))

    def test_basic_tier_also_ready_since_it_shares_the_ready_repo(self):
        readiness = parse_models_show(REAL_MODELS_SHOW_OUTPUT)
        self.assertTrue(readiness.tier_ready("basic"))

    def test_unknown_tier_is_not_ready(self):
        # Negative control: a tier this output never mentions (e.g. the
        # operator typo'd it, or "advanced" which has no model of its
        # own) must report not-ready rather than raising or defaulting true.
        readiness = parse_models_show(REAL_MODELS_SHOW_OUTPUT)
        self.assertFalse(readiness.tier_ready("advanced"))

    def test_tier_not_ready_when_one_of_two_repos_missing(self):
        output = """\
Repos:
  MinerU-4_models_onnx: ready
  MinerU2.5-Pro-2605-1.2B-GGUF: missing
Model tiers:
  standard: MinerU-4_models_onnx, MinerU2.5-Pro-2605-1.2B-GGUF"""
        readiness = parse_models_show(output)
        self.assertFalse(readiness.tier_ready("standard"))

    def test_empty_output_yields_no_ready_tiers(self):
        readiness = parse_models_show("")
        self.assertFalse(readiness.tier_ready("standard"))

    def test_real_output_with_path_on_a_following_line_still_parses(self):
        # The real CLI output wraps the resolved path onto its own line
        # right after "ready"/"missing" -- confirms the path line doesn't
        # get mistaken for a repo status line.
        output = (
            "Repos:\n"
            "  MinerU2.5-Pro-2605-1.2B-GGUF: ready \n"
            "(C:\\Users\\example\\.mineru\\models\\MinerU2.5-Pro-2605-1.2B-GGUF)\n"
            "Model tiers:\n"
            "  standard: MinerU2.5-Pro-2605-1.2B-GGUF"
        )
        readiness = parse_models_show(output)
        self.assertTrue(readiness.repo_status["MinerU2.5-Pro-2605-1.2B-GGUF"])
        self.assertTrue(readiness.tier_ready("standard"))

    def test_downloadable_tiers_are_basic_and_standard_only(self):
        # Pinned to the real `mineru-kit models download --help` output:
        # --tier only accepts basic or standard, never advanced.
        self.assertEqual(DOWNLOADABLE_TIERS, ("basic", "standard"))


class TestBootstrapTierFor(unittest.TestCase):
    def test_standard_maps_to_itself(self):
        self.assertEqual(bootstrap_tier_for("standard"), "standard")

    def test_basic_maps_to_itself(self):
        self.assertEqual(bootstrap_tier_for("basic"), "basic")

    def test_advanced_maps_to_standard(self):
        # Regression: pdf2md.py's "run" subcommand defaults --tier to
        # "advanced" but never forwarded it to run_bootstrap at all,
        # which silently defaulted to checking "standard" regardless of
        # the actual parse tier -- here that happens to be the RIGHT
        # answer for advanced specifically, but only by accident, and it
        # would have raised ValueError outright for "flash".
        self.assertEqual(bootstrap_tier_for("advanced"), "standard")

    def test_flash_maps_to_basic(self):
        # Negative control: naively forwarding "flash" straight into
        # run_bootstrap's tier= would raise ValueError, since "flash" is
        # not in DOWNLOADABLE_TIERS -- this mapping is what prevents that.
        self.assertEqual(bootstrap_tier_for("flash"), "basic")

    def test_unknown_tier_raises(self):
        with self.assertRaises(ValueError):
            bootstrap_tier_for("ultra")

    def test_every_mapped_value_is_downloadable(self):
        for parse_tier in ("flash", "basic", "standard", "advanced"):
            self.assertIn(bootstrap_tier_for(parse_tier), DOWNLOADABLE_TIERS)


if __name__ == "__main__":
    unittest.main()
