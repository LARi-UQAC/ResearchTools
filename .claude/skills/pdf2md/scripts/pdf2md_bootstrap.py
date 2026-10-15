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

import yaml

from pdf2md_config import apply_fixes, diagnose, render_config_yaml
from pdf2md_models import DOWNLOADABLE_TIERS, ModelReadiness, parse_models_show, run_models_show
from pdf2md_settings import load_pipeline_config, pip_command


def _today_iso() -> str:
    return datetime.date.today().isoformat()


def _package_name(spec: str) -> str:
    """Distribution name of a pinned requirement such as "mineru==4.0.11"."""
    return spec.split("==", 1)[0]


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
    packages: tuple[str, ...] | None = None,
    *,
    runner: Callable[..., subprocess.CompletedProcess] | None = None,
    timeout_s: float | None = None,
) -> dict[str, bool]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Check whether each required package is importable/installed via
        `pip show`, without installing anything. "mineru" is the real pip
        DISTRIBUTION name (confirmed via `pip show mineru`, 2026-10-10,
        version 4.0.11); "mineru-kit" is only the CLI entry point it
        installs, never a separate pip package -- `pip show mineru-kit`
        reports "Package(s) not found" on this machine.

    Inputs:
        packages (tuple[str, ...] | None): package names to check; None
            means the names of pdf2md-pipeline.json's pinned_packages.
        runner (callable | None): injected for tests; defaults to
            subprocess.run.
        timeout_s (float | None): per-call bound (R10); None reads
            pip_show_timeout_s from pdf2md-pipeline.json.

    Outputs:
        dict[str, bool]: package name -> installed.
    --------------------------------------------------------------------------
    """
    settings = load_pipeline_config()
    runner = runner or subprocess.run
    if packages is None:
        packages = tuple(_package_name(spec) for spec in settings["pinned_packages"])
    bound = settings["pip_show_timeout_s"] if timeout_s is None else timeout_s
    return {
        package: runner(pip_command("show", package), capture_output=True, text=True, timeout=bound).returncode == 0
        for package in packages
    }


def _pinned_specs(missing: list[str], pinned: list[str]) -> list[str]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Map each missing package name to its pinned requirement string so the
        install never runs on an unpinned name (security.md).

    Inputs:
        missing (list[str]): package names to install.
        pinned (list[str]): pdf2md-pipeline.json's pinned_packages.

    Outputs:
        list[str]: the pinned requirement for each missing package.

    Raises:
        RuntimeError: a missing package has no pinned version (R3).
    --------------------------------------------------------------------------
    """
    by_name = {_package_name(spec): spec for spec in pinned}
    unpinned = [name for name in missing if name not in by_name]
    if unpinned:
        raise RuntimeError(f"no pinned version for {unpinned} in pdf2md-pipeline.json (pinned_packages)")
    return [by_name[name] for name in missing]


def exit_code_for(report: dict, *, yes: bool) -> int:
    """
    --------------------------------------------------------------------------
    Purpose:
        The bootstrap exit code (R12): 0 when the post-apply state is ok, 2
        when a dry run found something to do (a refusal by design), 1 when
        --yes was given and the state is still not ok (a failed apply).

    Inputs:
        report (dict): a run_bootstrap report; only "ok" is read.
        yes (bool): whether --yes was passed.

    Outputs:
        int: 0, 1 or 2.
    --------------------------------------------------------------------------
    """
    if report["ok"]:
        return 0
    return 1 if yes else 2


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

    settings = load_pipeline_config()
    if missing_packages:
        runner = pip_runner or subprocess.run
        pip_result = runner(
            pip_command("install", *_pinned_specs(missing_packages, settings["pinned_packages"])),
            capture_output=True,
            text=True,
            timeout=settings["pip_install_timeout_s"],
        )
        report["packages_installed"] = pip_result.returncode == 0

    if not model_ready and readiness is not None:
        runner = download_runner or subprocess.run
        download_result = runner(
            ["mineru-kit", "models", "download", "--tier", tier],
            capture_output=True,
            text=True,
            timeout=settings["models_download_timeout_s"],
        )
        report["model_downloaded"] = download_result.returncode == 0

    if not diagnosis.clean:
        fixed = apply_fixes(config_dict, server_url=expected_server_url)
        config_path.parent.mkdir(parents=True, exist_ok=True)
        if config_path.exists():
            # The file is global to every mineru use on the machine and the rewrite drops comments.
            # Never overwrite an earlier backup: the operator may have edited the file since.
            # Each rewrite gets the next free name (.pdf2md-backup, .pdf2md-backup.1, ...).
            backup = config_path.with_name(config_path.name + ".pdf2md-backup")
            counter = 0
            while backup.exists():
                counter += 1
                backup = config_path.with_name(f"{config_path.name}.pdf2md-backup.{counter}")
            backup.write_bytes(config_path.read_bytes())
            report["config_backup"] = str(backup)
        stamp = (date_provider or _today_iso)()
        config_path.write_text(render_config_yaml(fixed, date=stamp), encoding="utf-8")
        report["config_fixed"] = True

    report["applied"] = True

    # R9: `ok` is read back from the state after the apply, never from the
    # exit codes of pip or the downloader, which say nothing about the effect.
    packages_after = check_packages_installed(runner=pip_runner)
    report["missing_packages_after"] = [name for name, installed in packages_after.items() if not installed]
    try:
        readiness_after = parse_models_show((models_show_runner or run_models_show)())
        report["model_ready_after"] = readiness_after.tier_ready(tier)
    except Exception as exc:  # noqa: BLE001 -- reported in the JSON, and ok stays False
        report["model_ready_after"] = False
        report["model_error_after"] = str(exc)
    config_after = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {} if config_path.exists() else {}
    report["config_issues_after"] = [
        {"code": i.code, "message": i.message}
        for i in diagnose(config_after, expected_server_url=expected_server_url).issues
    ]
    report["ok"] = not report["missing_packages_after"] and report["model_ready_after"] and not report["config_issues_after"]
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
    return exit_code_for(report, yes=args.yes)


if __name__ == "__main__":
    raise SystemExit(_main())
