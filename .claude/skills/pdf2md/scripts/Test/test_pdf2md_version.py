"""Offline tests for pdf2md_version. No real pip/network call is made:
check_versions takes injected pip_show_runner/pypi_fetcher (R20/R21)."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pdf2md_version import (
    check_versions,
    parse_pip_show_version,
    parse_pypi_latest_version,
    run_pip_audit,
    upgrade_packages,
)

# Verbatim shape of `pip show mineru-kit`'s relevant line, 2026-10-11.
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


if __name__ == "__main__":
    unittest.main()
