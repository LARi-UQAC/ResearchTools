"""Offline tests for pdf2md_bootstrap. No real pip, mineru-kit CLI, or
network call happens -- every IO seam is injected (R20/R21), and
config_path points at a tempfile so nothing touches a real
~/.mineru/config.yaml."""

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import yaml

from pdf2md_bootstrap import check_packages_installed, default_config_path, run_bootstrap

REAL_MODELS_SHOW_READY = """\
Repos:
  MinerU-4_models_onnx: ready
  MinerU2.5-Pro-2605-1.2B-GGUF: ready
Model tiers:
  standard: MinerU-4_models_onnx, MinerU2.5-Pro-2605-1.2B-GGUF"""

REAL_MODELS_SHOW_MISSING = """\
Repos:
  MinerU-4_models_onnx: ready
  MinerU2.5-Pro-2605-1.2B-GGUF: missing
Model tiers:
  standard: MinerU-4_models_onnx, MinerU2.5-Pro-2605-1.2B-GGUF"""

REAL_BROKEN_CONFIG_TEXT = """\
llm_aided:
  max_concurrency: 16
vlm:
  image_min_tokens: 1024
"""


class _FakeResult:
    def __init__(self, returncode=0, stdout=""):
        self.returncode = returncode
        self.stdout = stdout


class TestDefaultConfigPath(unittest.TestCase):
    def test_mineru_config_env_wins(self):
        old = os.environ.get("MINERU_CONFIG")
        os.environ["MINERU_CONFIG"] = "/explicit/config.yaml"
        try:
            self.assertEqual(default_config_path(), Path("/explicit/config.yaml"))
        finally:
            if old is None:
                del os.environ["MINERU_CONFIG"]
            else:
                os.environ["MINERU_CONFIG"] = old

    def test_never_hardcodes_an_account_path(self):
        # R1: the resolved path must come from Path.home() / an env var,
        # never a literal account name baked into this module.
        for name in ("MINERU_CONFIG", "MINERU_HOME"):
            os.environ.pop(name, None)
        resolved = default_config_path()
        self.assertEqual(resolved, Path.home() / ".mineru" / "config.yaml")


class TestCheckPackagesInstalled(unittest.TestCase):
    def test_reports_installed_and_missing(self):
        def fake_runner(args, **kwargs):
            package = args[-1]
            return _FakeResult(returncode=0 if package == "mineru" else 1)

        result = check_packages_installed(("mineru", "mineru-llama-cpp"), runner=fake_runner)
        self.assertTrue(result["mineru"])
        self.assertFalse(result["mineru-llama-cpp"])

    def test_default_packages_use_the_real_pip_distribution_name(self):
        # Regression: the default tuple named "mineru-kit" as a pip
        # package, but `pip show mineru-kit` reports "Package(s) not
        # found" on a real install -- the CLI entry point is named
        # mineru-kit, the pip DISTRIBUTION installing it is "mineru"
        # (confirmed via `pip show mineru`, 2026-10-10, version 4.0.11).
        calls = []

        def fake_runner(args, **kwargs):
            calls.append(args[-1])
            return _FakeResult(returncode=0)

        check_packages_installed(runner=fake_runner)
        self.assertIn("mineru", calls)
        self.assertNotIn("mineru-kit", calls)


class TestRunBootstrap(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.config_path = Path(self.tmp_dir.name) / "config.yaml"

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_invalid_tier_is_refused_before_touching_anything(self):
        with self.assertRaises(ValueError):
            run_bootstrap(
                config_path=self.config_path, expected_server_url=None, tier="advanced", yes=False,
            )

    def test_dry_run_reports_issues_without_writing(self):
        self.config_path.write_text(REAL_BROKEN_CONFIG_TEXT, encoding="utf-8")
        report = run_bootstrap(
            config_path=self.config_path,
            expected_server_url="http://127.0.0.1:30000/v1",
            yes=False,
            pip_runner=lambda args, **kw: _FakeResult(returncode=0),
            models_show_runner=lambda: REAL_MODELS_SHOW_READY,
        )
        self.assertFalse(report["ok"])
        self.assertFalse(report["applied"])
        codes = {issue["code"] for issue in report["config_issues"]}
        self.assertIn("vlm_wrong_nesting", codes)
        # Dry run must not have touched the file.
        self.assertEqual(self.config_path.read_text(encoding="utf-8"), REAL_BROKEN_CONFIG_TEXT)

    def test_yes_fixes_the_config_on_disk(self):
        self.config_path.write_text(REAL_BROKEN_CONFIG_TEXT, encoding="utf-8")
        report = run_bootstrap(
            config_path=self.config_path,
            expected_server_url="http://127.0.0.1:30000/v1",
            yes=True,
            pip_runner=lambda args, **kw: _FakeResult(returncode=0),
            models_show_runner=lambda: REAL_MODELS_SHOW_READY,
        )
        self.assertTrue(report["applied"])
        fixed = yaml.safe_load(self.config_path.read_text(encoding="utf-8"))
        self.assertNotIn("vlm", fixed)
        self.assertEqual(fixed["model"]["vlm"]["server_url"], "http://127.0.0.1:30000/v1")

    def test_config_header_uses_the_injected_date_not_a_hardcoded_one(self):
        # Regression: the header comment's date was a literal "2026-10-10"
        # regardless of when the fix actually ran (R13). Pinning an
        # obviously-different injected date proves it is no longer
        # hardcoded, rather than merely re-asserting the same value that
        # happened to match the hardcoded one.
        self.config_path.write_text(REAL_BROKEN_CONFIG_TEXT, encoding="utf-8")
        run_bootstrap(
            config_path=self.config_path,
            expected_server_url="http://127.0.0.1:30000/v1",
            yes=True,
            pip_runner=lambda args, **kw: _FakeResult(returncode=0),
            models_show_runner=lambda: REAL_MODELS_SHOW_READY,
            date_provider=lambda: "2030-01-15",
        )
        written = self.config_path.read_text(encoding="utf-8")
        self.assertIn("2030-01-15", written)
        self.assertNotIn("2026-10-10", written)

    def test_missing_model_triggers_download_only_with_yes(self):
        self.config_path.write_text("", encoding="utf-8")
        download_calls = []

        def fake_download(args, **kwargs):
            download_calls.append(args)
            return _FakeResult(returncode=0)

        run_bootstrap(
            config_path=self.config_path,
            expected_server_url=None,
            tier="standard",
            yes=True,
            pip_runner=lambda args, **kw: _FakeResult(returncode=0),
            models_show_runner=lambda: REAL_MODELS_SHOW_MISSING,
            download_runner=fake_download,
        )
        self.assertEqual(len(download_calls), 1)
        self.assertIn("--tier", download_calls[0])
        self.assertIn("standard", download_calls[0])

    def test_no_download_attempted_when_model_already_ready(self):
        # Negative control: must not re-download an already-ready model.
        self.config_path.write_text("", encoding="utf-8")
        download_calls = []

        run_bootstrap(
            config_path=self.config_path,
            expected_server_url=None,
            yes=True,
            pip_runner=lambda args, **kw: _FakeResult(returncode=0),
            models_show_runner=lambda: REAL_MODELS_SHOW_READY,
            download_runner=lambda args, **kw: download_calls.append(args) or _FakeResult(returncode=0),
        )
        self.assertEqual(download_calls, [])

    def test_missing_packages_reported(self):
        self.config_path.write_text("", encoding="utf-8")
        report = run_bootstrap(
            config_path=self.config_path,
            expected_server_url=None,
            yes=False,
            pip_runner=lambda args, **kw: _FakeResult(returncode=1),
            models_show_runner=lambda: REAL_MODELS_SHOW_READY,
        )
        self.assertIn("mineru", report["missing_packages"])

    def test_models_show_failure_is_reported_not_raised(self):
        self.config_path.write_text("", encoding="utf-8")

        def failing_models_show():
            raise RuntimeError("mineru-kit not on PATH")

        report = run_bootstrap(
            config_path=self.config_path,
            expected_server_url=None,
            yes=False,
            pip_runner=lambda args, **kw: _FakeResult(returncode=0),
            models_show_runner=failing_models_show,
        )
        self.assertFalse(report["model_ready"])
        self.assertIn("mineru-kit not on PATH", report["model_error"])

    def test_missing_config_file_treated_as_empty_not_an_error(self):
        # config_path does not exist at all (fresh machine case).
        report = run_bootstrap(
            config_path=self.config_path,
            expected_server_url="http://127.0.0.1:30000/v1",
            yes=False,
            pip_runner=lambda args, **kw: _FakeResult(returncode=0),
            models_show_runner=lambda: REAL_MODELS_SHOW_READY,
        )
        self.assertIn("server_url_unset", {i["code"] for i in report["config_issues"]})


if __name__ == "__main__":
    unittest.main()
