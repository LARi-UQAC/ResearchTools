"""
pdf2md_bootstrap - Stage 1 of the pdf2md pipeline: idempotent, safe-to-rerun
check that mineru-kit is installed, its VLM model is downloaded, and
~/.mineru/config.yaml is free of the two defects measured this session
(wrong vlm: nesting, high llm_aided.max_concurrency).

Dry-run by default (R16): reports every issue found and what WOULD be done,
writes nothing until --yes. The config path is read from MINERU_CONFIG /
MINERU_HOME (mineru's own env vars) or the user's home directory -- never a
literal account path (R1).
"""

from __future__ import annotations

import datetime
import json
import os
import subprocess
from pathlib import Path
from typing import Callable


def _today_iso() -> str:
    return datetime.date.today().isoformat()

import yaml

from pdf2md_config import apply_fixes, diagnose, render_config_yaml
from pdf2md_models import DOWNLOADABLE_TIERS, ModelReadiness, parse_models_show, run_models_show


def default_config_path() -> Path:
    """
    --------------------------------------------------------------------------
    Purpose:
        Resolve ~/.mineru/config.yaml the same way mineru itself does
        (MINERU_CONFIG override, else MINERU_HOME/config.yaml, else
        ~/.mineru/config.yaml) -- never a hardcoded account path (R1).

    Inputs:
        None.

    Outputs:
        Path
    --------------------------------------------------------------------------
    """
    if "MINERU_CONFIG" in os.environ:
        return Path(os.environ["MINERU_CONFIG"])
    home = os.environ.get("MINERU_HOME", str(Path.home() / ".mineru"))
    return Path(home) / "config.yaml"


def check_packages_installed(
    packages: tuple[str, ...] = ("mineru-kit", "mineru-llama-cpp"),
    *,
    runner: Callable[..., subprocess.CompletedProcess] | None = None,
) -> dict[str, bool]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Check whether each required package is importable/installed via
        `pip show`, without installing anything.

    Inputs:
        packages (tuple[str, ...]): package names to check.
        runner (callable | None): injected for tests; defaults to
            subprocess.run.

    Outputs:
        dict[str, bool]: package name -> installed.
    --------------------------------------------------------------------------
    """
    runner = runner or subprocess.run
    return {
        package: runner(["pip", "show", package], capture_output=True, text=True, timeout=30).returncode == 0
        for package in packages
    }


def run_bootstrap(
    *,
    config_path: Path,
    expected_server_url: str | None,
    tier: str = "standard",
    yes: bool,
    pip_runner: Callable[..., subprocess.CompletedProcess] | None = None,
    models_show_runner: Callable[..., str] | None = None,
    download_runner: Callable[..., subprocess.CompletedProcess] | None = None,
    date_provider: Callable[[], str] | None = None,
) -> dict:
    """
    --------------------------------------------------------------------------
    Purpose:
        Run the full bootstrap check (packages, model readiness, config),
        and apply fixes only when yes=True. Every effect (pip, mineru-kit
        CLI, filesystem) stays behind the given seams so this is testable
        without a real environment (R20/R21).

    Inputs:
        config_path (Path): where config.yaml lives (or would be created).
        expected_server_url (str | None): the VLM server URL to set, once
            known; None if the server has not started yet (bootstrap runs
            before stage 3).
        tier (str): download tier if the model is missing; must be one of
            DOWNLOADABLE_TIERS.
        yes (bool): apply fixes/downloads; False means report-only.
        pip_runner, models_show_runner, download_runner: injected IO seams.
        date_provider (callable | None): returns the ISO date stamped into
            the rewritten config's header comment (R13/R19 -- never read
            the wall clock directly inside logic; defaults to
            datetime.date.today().isoformat, injected here so a test can
            pin it rather than asserting against "whenever this test runs").

    Outputs:
        dict: a JSON-serializable report (R17) with keys "ok", "issues",
            "model_ready", "applied" (bool).

    Raises:
        ValueError: if tier is not in DOWNLOADABLE_TIERS (R12 -- a refusal
            by design, not a crash on a bad argument).
    --------------------------------------------------------------------------
    """
    if tier not in DOWNLOADABLE_TIERS:
        raise ValueError(f"tier must be one of {DOWNLOADABLE_TIERS}, got {tier!r}")

    packages = check_packages_installed(runner=pip_runner)
    missing_packages = [name for name, installed in packages.items() if not installed]

    try:
        show_output = (models_show_runner or run_models_show)()
        readiness: ModelReadiness | None = parse_models_show(show_output)
    except Exception as exc:  # noqa: BLE001 -- surfaced, not swallowed (R11 is for hooks, not this CLI)
        readiness = None
        model_error = str(exc)
    else:
        model_error = None

    model_ready = readiness.tier_ready(tier) if readiness is not None else False

    config_text = config_path.read_text(encoding="utf-8") if config_path.exists() else ""
    config_dict = yaml.safe_load(config_text) or {} if config_text else {}
    diagnosis = diagnose(config_dict, expected_server_url=expected_server_url)

    report: dict = {
        "ok": True,
        "missing_packages": missing_packages,
        "model_ready": model_ready,
        "model_error": model_error,
        "config_issues": [{"code": i.code, "message": i.message} for i in diagnosis.issues],
        "applied": False,
    }

    if not yes:
        report["ok"] = not missing_packages and model_ready and diagnosis.clean
        return report

    if missing_packages:
        runner = pip_runner or subprocess.run
        pip_result = runner(["pip", "install", *missing_packages], capture_output=True, text=True, timeout=600)
        report["packages_installed"] = pip_result.returncode == 0

    if not model_ready and readiness is not None:
        runner = download_runner or subprocess.run
        download_result = runner(
            ["mineru-kit", "models", "download", "--tier", tier], capture_output=True, text=True, timeout=1800
        )
        report["model_downloaded"] = download_result.returncode == 0

    if not diagnosis.clean:
        fixed = apply_fixes(config_dict, server_url=expected_server_url)
        config_path.parent.mkdir(parents=True, exist_ok=True)
        stamp = (date_provider or _today_iso)()
        config_path.write_text(render_config_yaml(fixed, date=stamp), encoding="utf-8")
        report["config_fixed"] = True

    report["applied"] = True
    return report


def _main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=None, help="config.yaml path (default: mineru's own resolution)")
    parser.add_argument("--server-url", default=None, help="VLM server URL to set in config, once known")
    parser.add_argument("--tier", default="standard", choices=DOWNLOADABLE_TIERS)
    parser.add_argument("--yes", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    config_path = Path(args.config) if args.config else default_config_path()
    report = run_bootstrap(config_path=config_path, expected_server_url=args.server_url, tier=args.tier, yes=args.yes)
    print(json.dumps(report) if args.json else report)
    return 0 if report["ok"] else (0 if args.yes else 2)


if __name__ == "__main__":
    raise SystemExit(_main())
