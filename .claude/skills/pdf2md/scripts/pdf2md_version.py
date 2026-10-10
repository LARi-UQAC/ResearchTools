"""
pdf2md_version - Stage 2 of the pdf2md pipeline: check mineru-kit's version
against PyPI, report-only by default.

Never auto-upgrades silently (R16): the rest of this skill is grounded in
version-4.0.11-specific behaviour (the os.execv quoting bug, the
model.vlm.server_url nesting requirement, the hardcoded 3-retry llm_aided
timeout) measured hands-on. An upgrade could change or fix any of that
without warning, so --yes is required to actually apply one, and a
pip-audit follows per security.md.
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from typing import Callable

_PACKAGES = ("mineru-kit", "mineru-llama-cpp")
_PIP_SHOW_VERSION_RE = re.compile(r"^Version:\s*(.+)$", re.MULTILINE)


@dataclass
class VersionCheck:
    """
    --------------------------------------------------------------------------
    Purpose:
        One package's installed-vs-latest comparison.

    Inputs:
        None.

    Outputs:
        package (str), installed (str | None), latest (str | None),
        upgrade_available (bool)
    --------------------------------------------------------------------------
    """

    package: str
    installed: str | None
    latest: str | None

    @property
    def upgrade_available(self) -> bool:
        return self.installed is not None and self.latest is not None and self.installed != self.latest


def parse_pip_show_version(output: str) -> str | None:
    """Pure parse of `pip show <pkg>`'s "Version: X.Y.Z" line; None if absent (package not installed)."""
    match = _PIP_SHOW_VERSION_RE.search(output)
    return match.group(1).strip() if match else None


def parse_pypi_latest_version(payload: dict) -> str | None:
    """Pure parse of PyPI's JSON API response (`https://pypi.org/pypi/<pkg>/json`)'s info.version field."""
    return (payload.get("info") or {}).get("version")


def check_versions(
    *,
    pip_show_runner: Callable[[str], str],
    pypi_fetcher: Callable[[str], dict],
    packages: tuple[str, ...] = _PACKAGES,
) -> list[VersionCheck]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Compare installed vs latest PyPI version for each tracked package.
        Every effect is injected (R20/R21) -- no real pip call or network
        request happens inside this function.

    Inputs:
        pip_show_runner (callable): str (package name) -> str (pip show
            stdout, or "" if not installed).
        pypi_fetcher (callable): str (package name) -> dict (parsed PyPI
            JSON response).
        packages (tuple[str, ...]): which packages to check.

    Outputs:
        list[VersionCheck]
    --------------------------------------------------------------------------
    """
    results = []
    for package in packages:
        installed = parse_pip_show_version(pip_show_runner(package))
        latest = parse_pypi_latest_version(pypi_fetcher(package))
        results.append(VersionCheck(package, installed, latest))
    return results


def real_pip_show_runner(package: str, runner: Callable[..., subprocess.CompletedProcess] | None = None) -> str:
    """IO wrapper: `pip show <package>`, empty string (not an exception) if the package is not installed."""
    runner = runner or subprocess.run
    result = runner(["pip", "show", package], capture_output=True, text=True, timeout=30)
    return result.stdout if result.returncode == 0 else ""


def real_pypi_fetcher(package: str, timeout_s: float = 10.0) -> dict:
    """IO wrapper: fetch https://pypi.org/pypi/<package>/json (R10: bounded timeout)."""
    import urllib.request

    with urllib.request.urlopen(f"https://pypi.org/pypi/{package}/json", timeout=timeout_s) as response:
        return json.loads(response.read().decode("utf-8"))


def upgrade_packages(
    packages: tuple[str, ...] = _PACKAGES,
    *,
    runner: Callable[..., subprocess.CompletedProcess] | None = None,
) -> subprocess.CompletedProcess:
    """
    --------------------------------------------------------------------------
    Purpose:
        Run `pip install --upgrade <packages>`. Only called when the
        caller has explicit --yes consent (R16); never invoked by the
        default dry-run path.

    Inputs:
        packages (tuple[str, ...]): packages to upgrade.
        runner (callable | None): injected for tests; defaults to
            subprocess.run.

    Outputs:
        subprocess.CompletedProcess
    --------------------------------------------------------------------------
    """
    runner = runner or subprocess.run
    return runner(["pip", "install", "--upgrade", *packages], capture_output=True, text=True, timeout=600)


def run_pip_audit(runner: Callable[..., subprocess.CompletedProcess] | None = None) -> subprocess.CompletedProcess:
    """IO wrapper: `pip-audit`, run after an upgrade per security.md."""
    runner = runner or subprocess.run
    return runner(["pip-audit"], capture_output=True, text=True, timeout=300)


def _main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--yes", action="store_true", help="actually upgrade, then run pip-audit (default: report only)")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    checks = check_versions(pip_show_runner=real_pip_show_runner, pypi_fetcher=real_pypi_fetcher)
    report: dict = {
        "ok": True,
        "checks": [
            {"package": c.package, "installed": c.installed, "latest": c.latest, "upgrade_available": c.upgrade_available}
            for c in checks
        ],
        "upgraded": False,
    }

    any_upgrade = any(c.upgrade_available for c in checks)
    if any_upgrade and not args.yes:
        report["refused"] = "upgrade(s) available but --yes not passed; dry-run only (R16)"
        print(json.dumps(report) if args.json else report)
        return 2
    if any_upgrade and args.yes:
        upgrade_result = upgrade_packages()
        audit_result = run_pip_audit()
        report["upgraded"] = upgrade_result.returncode == 0
        report["pip_audit_returncode"] = audit_result.returncode
        report["pip_audit_output"] = audit_result.stdout

    print(json.dumps(report) if args.json else report)
    return 0 if report.get("upgraded", True) is not False else 1


if __name__ == "__main__":
    raise SystemExit(_main())
