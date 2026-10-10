"""Offline tests for pdf2md_version. No real pip/network call is made:
check_versions takes injected pip_show_runner/pypi_fetcher (R20/R21)."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pdf2md_version import (
    VersionCheck,
    build_version_report,
    check_versions,
    parse_pip_show_version,
    parse_pypi_latest_version,
    run_pip_audit,
    upgrade_packages,
)

# Verbatim shape of `pip show mineru-kit`'s relevant line, 2026-10-10.
REAL_PIP_SHOW_OUTPUT = """\
Name: mineru-kit
Version: 4.0.11
Summary: MinerU Kit
Location: c:\\users\\example\\appdata\\local\\programs\\python\\python313\\lib\\site-packages"""


class TestParsePipShowVersion(unittest.TestCase):
    def test_extracts_version_from_real_output(self):
        self.assertEqual(parse_pip_show_version(REAL_PIP_SHOW_OUTPUT), "4.0.11")

    def test_not_installed_package_returns_none(self):
        # pip show on an absent package exits non-zero and prints
        # nothing useful; the IO wrapper turns that into "", which must
        # parse to None, not raise and not silently return "0.0.0".
        self.assertIsNone(parse_pip_show_version(""))


class TestParsePypiLatestVersion(unittest.TestCase):
    def test_extracts_version_from_pypi_json_shape(self):
        payload = {"info": {"version": "4.1.0", "name": "mineru-kit"}}
        self.assertEqual(parse_pypi_latest_version(payload), "4.1.0")

    def test_missing_info_key_returns_none(self):
        self.assertIsNone(parse_pypi_latest_version({}))


class TestCheckVersions(unittest.TestCase):
    def test_upgrade_available_when_versions_differ(self):
        checks = check_versions(
            pip_show_runner=lambda _pkg: "Version: 4.0.11",
            pypi_fetcher=lambda _pkg: {"info": {"version": "4.1.0"}},
            packages=("mineru-kit",),
        )
        self.assertTrue(checks[0].upgrade_available)

    def test_no_upgrade_when_versions_match(self):
        checks = check_versions(
            pip_show_runner=lambda _pkg: "Version: 4.0.11",
            pypi_fetcher=lambda _pkg: {"info": {"version": "4.0.11"}},
            packages=("mineru-kit",),
        )
        self.assertFalse(checks[0].upgrade_available)

    def test_not_installed_is_never_flagged_as_upgrade_available(self):
        # Negative control: a package that isn't installed at all must not
        # read as "an upgrade is available" -- that's a different problem
        # (bootstrap's job), not stage 2's.
        checks = check_versions(
            pip_show_runner=lambda _pkg: "",
            pypi_fetcher=lambda _pkg: {"info": {"version": "4.1.0"}},
            packages=("mineru-kit",),
        )
        self.assertIsNone(checks[0].installed)
        self.assertFalse(checks[0].upgrade_available)

    def test_checks_every_requested_package(self):
        seen = []

        def fake_pip_show(pkg):
            seen.append(pkg)
            return "Version: 1.0.0"

        check_versions(
            pip_show_runner=fake_pip_show,
            pypi_fetcher=lambda _pkg: {"info": {"version": "1.0.0"}},
            packages=("mineru-kit", "mineru-llama-cpp"),
        )
        self.assertEqual(seen, ["mineru-kit", "mineru-llama-cpp"])


class TestUpgradeAndAudit(unittest.TestCase):
    def test_upgrade_packages_builds_correct_argv(self):
        captured = {}

        def fake_runner(args, **kwargs):
            captured["args"] = args

            class Result:
                returncode = 0

            return Result()

        upgrade_packages(("mineru-kit",), runner=fake_runner)
        self.assertEqual(captured["args"], ["pip", "install", "--upgrade", "mineru-kit"])

    def test_pip_audit_invoked_with_no_extra_args(self):
        captured = {}

        def fake_runner(args, **kwargs):
            captured["args"] = args

            class Result:
                returncode = 0
                stdout = "No known vulnerabilities found"

            return Result()

        result = run_pip_audit(runner=fake_runner)
        self.assertEqual(captured["args"], ["pip-audit"])
        self.assertEqual(result.returncode, 0)


class _FakeCompletedProcess:
    def __init__(self, returncode=0, stdout=""):
        self.returncode = returncode
        self.stdout = stdout


class TestBuildVersionReport(unittest.TestCase):
    def test_nothing_to_upgrade_exits_zero(self):
        # Regression: _main used to return exit code 1 for this exact,
        # healthy case (report["upgraded"] stays its initial False with
        # no upgrade ever attempted, and the old code read that False as
        # failure instead of "nothing needed").
        checks = [VersionCheck("mineru-kit", "4.0.11", "4.0.11")]
        report, exit_code = build_version_report(checks, yes=False)
        self.assertEqual(exit_code, 0)
        self.assertFalse(report["upgrade_available"])

    def test_upgrade_available_without_yes_refuses(self):
        checks = [VersionCheck("mineru-kit", "4.0.11", "4.1.0")]
        report, exit_code = build_version_report(checks, yes=False)
        self.assertEqual(exit_code, 2)
        self.assertIn("refused", report)

    def test_upgrade_available_with_yes_and_success_exits_zero(self):
        checks = [VersionCheck("mineru-kit", "4.0.11", "4.1.0")]
        report, exit_code = build_version_report(
            checks, yes=True,
            upgrade_fn=lambda: _FakeCompletedProcess(returncode=0),
            audit_fn=lambda: _FakeCompletedProcess(returncode=0, stdout="No known vulnerabilities found"),
        )
        self.assertEqual(exit_code, 0)
        self.assertTrue(report["upgraded"])

    def test_upgrade_available_with_yes_and_failure_exits_one(self):
        checks = [VersionCheck("mineru-kit", "4.0.11", "4.1.0")]
        report, exit_code = build_version_report(
            checks, yes=True,
            upgrade_fn=lambda: _FakeCompletedProcess(returncode=1),
            audit_fn=lambda: _FakeCompletedProcess(returncode=0),
        )
        self.assertEqual(exit_code, 1)
        self.assertFalse(report["upgraded"])

    def test_upgrade_fn_and_audit_fn_not_called_when_no_upgrade(self):
        # Negative control: must not run pip install/pip-audit when there
        # is nothing to upgrade.
        calls = []
        checks = [VersionCheck("mineru-kit", "4.0.11", "4.0.11")]
        build_version_report(
            checks, yes=True,
            upgrade_fn=lambda: calls.append("upgrade") or _FakeCompletedProcess(),
            audit_fn=lambda: calls.append("audit") or _FakeCompletedProcess(),
        )
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
