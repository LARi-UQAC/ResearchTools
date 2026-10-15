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

from pdf2md_bootstrap import check_packages_installed, default_config_path, exit_code_for, run_bootstrap

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


class _StatefulPip:
    """A pip fake whose `show` answer changes after an `install`, like a real environment."""

    def __init__(self, installed: set[str], install_succeeds: bool = True):
        self.installed = set(installed)
        self.install_succeeds = install_succeeds
        self.calls: list[list[str]] = []

    def __call__(self, args, **kwargs):
        self.calls.append(list(args))
        if "install" in args:
            if self.install_succeeds:
                self.installed |= {spec.split("==")[0] for spec in args if "==" in spec}
            return _FakeResult(returncode=0 if self.install_succeeds else 1)
        return _FakeResult(returncode=0 if args[-1] in self.installed else 1)


class TestApplyIsVerified(unittest.TestCase):
    """H4 of the 2026-10-15 review (R9, R12): `ok` must describe the state AFTER
    the apply step, and a failed apply under --yes must not read as success."""

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.config_path = Path(self.tmp_dir.name) / "config.yaml"
        self.config_path.write_text("", encoding="utf-8")

    def tearDown(self):
        self.tmp_dir.cleanup()

    def _run(self, pip, models_show=REAL_MODELS_SHOW_READY, download=None, yes=True):
        return run_bootstrap(
            config_path=self.config_path,
            expected_server_url=None,
            yes=yes,
            pip_runner=pip,
            models_show_runner=(lambda: models_show) if isinstance(models_show, str) else models_show,
            download_runner=download or (lambda args, **kw: _FakeResult(returncode=0)),
        )

    def test_a_failed_pip_install_under_yes_is_not_ok(self):
        report = self._run(_StatefulPip(installed=set(), install_succeeds=False))
        self.assertFalse(report["packages_installed"])
        self.assertFalse(report["ok"])
        self.assertIn("mineru", report["missing_packages_after"])

    def test_a_successful_install_makes_the_report_ok(self):
        # Positive control: without it, "always not ok" would pass the test above.
        report = self._run(_StatefulPip(installed=set(), install_succeeds=True))
        self.assertTrue(report["packages_installed"])
        self.assertEqual(report["missing_packages_after"], [])
        self.assertTrue(report["ok"])

    def test_a_failed_model_download_under_yes_is_not_ok(self):
        report = self._run(
            _StatefulPip(installed={"mineru", "mineru-llama-cpp"}),
            models_show=REAL_MODELS_SHOW_MISSING,
            download=lambda args, **kw: _FakeResult(returncode=1),
        )
        self.assertFalse(report["model_downloaded"])
        self.assertFalse(report["ok"])

    def test_a_download_that_exits_zero_but_leaves_the_model_missing_is_not_ok(self):
        # R9: the exit code of the downloader is not the effect.
        report = self._run(
            _StatefulPip(installed={"mineru", "mineru-llama-cpp"}),
            models_show=REAL_MODELS_SHOW_MISSING,
            download=lambda args, **kw: _FakeResult(returncode=0),
        )
        self.assertTrue(report["model_downloaded"])
        self.assertFalse(report["model_ready_after"])
        self.assertFalse(report["ok"])

    def test_pip_runs_under_the_interpreter_of_this_skill_with_pinned_versions(self):
        pip = _StatefulPip(installed=set())
        self._run(pip)
        install_calls = [call for call in pip.calls if "install" in call]
        self.assertEqual(len(install_calls), 1)
        self.assertEqual(install_calls[0][:3], [sys.executable, "-m", "pip"])
        specs = install_calls[0][4:]
        self.assertTrue(all("==" in spec for spec in specs), specs)
        self.assertIn("mineru==4.0.11", specs)
        for call in pip.calls:
            self.assertEqual(call[:3], [sys.executable, "-m", "pip"], "a bare `pip` was invoked")

    def test_a_dry_run_installs_nothing(self):
        pip = _StatefulPip(installed=set())
        report = self._run(pip, yes=False)
        self.assertFalse(report["ok"])
        self.assertFalse(any("install" in call for call in pip.calls))


class TestConfigBackup(unittest.TestCase):
    def test_the_original_config_is_kept_before_it_is_rewritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.yaml"
            path.write_text("# my notes\n" + REAL_BROKEN_CONFIG_TEXT, encoding="utf-8")
            report = run_bootstrap(
                config_path=path, expected_server_url="http://127.0.0.1:30000/v1", yes=True,
                pip_runner=_StatefulPip(installed={"mineru", "mineru-llama-cpp"}),
                models_show_runner=lambda: REAL_MODELS_SHOW_READY,
            )
            backup = Path(report["config_backup"])
            self.assertEqual(backup.read_text(encoding="utf-8"), "# my notes\n" + REAL_BROKEN_CONFIG_TEXT)
            self.assertNotIn("# my notes", path.read_text(encoding="utf-8"))

    def test_a_second_run_does_not_overwrite_the_first_backup(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.yaml"
            backup = Path(tmp) / "config.yaml.pdf2md-backup"
            backup.write_text("first original", encoding="utf-8")
            path.write_text(REAL_BROKEN_CONFIG_TEXT, encoding="utf-8")
            run_bootstrap(
                config_path=path, expected_server_url="http://127.0.0.1:30000/v1", yes=True,
                pip_runner=_StatefulPip(installed={"mineru", "mineru-llama-cpp"}),
                models_show_runner=lambda: REAL_MODELS_SHOW_READY,
            )
            self.assertEqual(backup.read_text(encoding="utf-8"), "first original")


class TestBackupIsNotClaimedTwice(unittest.TestCase):
    def test_a_rewrite_with_an_older_backup_says_it_has_no_backup_of_its_own(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.yaml"
            (Path(tmp) / "config.yaml.pdf2md-backup").write_text("older", encoding="utf-8")
            path.write_text(REAL_BROKEN_CONFIG_TEXT, encoding="utf-8")
            report = run_bootstrap(
                config_path=path, expected_server_url="http://127.0.0.1:30000/v1", yes=True,
                pip_runner=_StatefulPip(installed={"mineru", "mineru-llama-cpp"}),
                models_show_runner=lambda: REAL_MODELS_SHOW_READY,
            )
        self.assertNotIn("config_backup", report)
        self.assertIn("config_backup_from_earlier_run", report)


class TestExitCode(unittest.TestCase):
    def test_a_failed_apply_under_yes_exits_1_not_0(self):
        self.assertEqual(exit_code_for({"ok": False}, yes=True), 1)

    def test_a_refused_dry_run_exits_2(self):
        self.assertEqual(exit_code_for({"ok": False}, yes=False), 2)

    def test_an_ok_report_exits_0(self):
        self.assertEqual(exit_code_for({"ok": True}, yes=True), 0)
        self.assertEqual(exit_code_for({"ok": True}, yes=False), 0)


if __name__ == "__main__":
    unittest.main()
