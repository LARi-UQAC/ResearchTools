"""
pdf2md - single entry point dispatching to every pdf2md pipeline stage.

Usage:
    python pdf2md.py bootstrap [--yes] [--server-url URL] [--tier basic|standard]
    python pdf2md.py version [--yes]
    python pdf2md.py serve [--port 30000] [--image-min-tokens 1024]
    python pdf2md.py convert start <pdf> -o <dir> [--tier advanced]
    python pdf2md.py convert status --log <path>
    python pdf2md.py postprocess <markdown_file> -o <dir> [--layout thesis|single]   (single: an article or a talk, ONE main.md)
    python pdf2md.py refs <bibliography_file> -o <ref.md>
    python pdf2md.py run <pdf> -o <dir> [--tier advanced] [--yes]   (dry run without --yes)
    python pdf2md.py validate <pdf> -o <dir> [--fidelity] [--vlm-check --vlm-check-model TAG] [--strict]
    python pdf2md.py repair <pdf> -o <dir> [--yes]
    python pdf2md.py fix <pdf> -o <dir> --model TAG [--pages all] [--rewrite-formulas] [--yes] [--strict]

Every subcommand accepts --json for a machine-readable report (R17) and
follows the exit-code convention (R12): 0 done, 2 refusal by design,
1 failure. See each pdf2md_<stage>.py module's own docstring for what it
does and why; this file only dispatches.
"""

from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        print(__doc__)
        return 2

    command, rest = argv[0], argv[1:]

    if command == "bootstrap":
        from pdf2md_bootstrap import _main as bootstrap_main

        return bootstrap_main(rest)
    if command == "version":
        from pdf2md_version import _main as version_main

        return version_main(rest)
    if command == "serve":
        from pdf2md_server import _main as server_main

        return server_main(rest)
    if command == "convert":
        from pdf2md_convert import _main as convert_main

        return convert_main(rest)
    if command == "postprocess":
        from pdf2md_postprocess import _main as postprocess_main

        return postprocess_main(rest)
    if command == "refs":
        from pdf2md_refs import _main as refs_main

        return refs_main(rest)
    if command == "run":
        return _run_full_pipeline(rest)
    if command == "validate":
        from pdf2md_validate import _main as validate_main

        return validate_main(rest)
    if command == "repair":
        from pdf2md_repair import _main as repair_main

        return repair_main(rest)
    if command == "fix":
        from pdf2md_vlmfix import _main as fix_main

        return fix_main(rest)

    print(f"Unknown command: {command!r}\n\n{__doc__}")
    return 2


def _run_full_pipeline(argv: list[str]) -> int:
    """
    --------------------------------------------------------------------------
    Purpose:
        Orchestrate stages 1 to 4: bootstrap, start the VLM server, start the
        conversion. A DRY RUN unless --yes is passed (R16): without it the
        bootstrap is only reported and nothing is launched, since the real run
        starts a detached llama-server and a conversion that can last hours.
        The command does not block waiting for the conversion; the report
        names the next manual stages.

    Details:
        A bootstrap whose state is not ok AFTER its apply step (a failed pip
        install or model download) stops the run before the server starts
        (R9, R12), whether or not --yes was given.

    Inputs:
        argv (list[str]): "run" subcommand's own args: <pdf> -o <dir>
            [--tier T] [--port P] [--yes] [--json].

    Outputs:
        int: process exit code (R12): 0 done (or a dry run that found nothing
            to fix), 2 a dry run that found something to fix, 1 a failure.
    --------------------------------------------------------------------------
    """
    import argparse
    import json

    from pdf2md_bootstrap import default_config_path, exit_code_for, run_bootstrap
    from pdf2md_convert import build_parse_args, launch_convert
    from pdf2md_models import bootstrap_tier_for
    from pdf2md_server import build_llama_server_args, launch_server, wait_for_server
    from pdf2md_settings import load_pipeline_config
    from pathlib import Path

    settings = load_pipeline_config()
    parser = argparse.ArgumentParser(prog="pdf2md run")
    parser.add_argument("pdf_path")
    parser.add_argument("-o", "--output-dir", required=True)
    parser.add_argument("--tier", default="advanced", choices=("flash", "basic", "standard", "advanced"))
    parser.add_argument("--port", type=int, default=settings["port"])
    parser.add_argument("--yes", action="store_true", help="actually start the server and the conversion (default: dry run)")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    def emit(report: dict) -> None:
        print(json.dumps(report) if args.json else report)

    server_url = f"http://127.0.0.1:{args.port}/v1"

    bootstrap_report = run_bootstrap(
        config_path=default_config_path(),
        expected_server_url=server_url,
        tier=bootstrap_tier_for(args.tier),
        yes=args.yes,
    )
    if not bootstrap_report["ok"]:
        emit({"ok": False, "stage": "bootstrap", **bootstrap_report})
        return exit_code_for(bootstrap_report, yes=args.yes)

    if not args.yes:
        emit(
            {
                "ok": True,
                "dry_run": True,
                "stage": "dry_run",
                "would": [
                    f"start llama-server on port {args.port}, log {Path(args.output_dir) / 'pdf2md-vlm-server.log'}",
                    f"start `mineru-kit parse --tier {args.tier}` on {args.pdf_path}, log {Path(args.output_dir) / 'pdf2md-convert.log'}",
                ],
                "next_step": "re-run the same command with --yes to launch both",
            }
        )
        return 0

    from pdf2md_models import resolve_vlm_paths

    vlm_paths = resolve_vlm_paths()
    server_args = build_llama_server_args(vlm_paths, port=args.port)
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    server_log = out_dir / "pdf2md-vlm-server.log"
    server_process = launch_server(server_args, server_log)
    verification = wait_for_server(server_log, timeout_s=settings["server_wait_s"])
    if not verification.healthy:
        # Do not leave a detached server holding the port and the VRAM for the next run to collide with.
        try:
            server_process.terminate()
        except (OSError, AttributeError):
            pass
        emit(
            {
                "ok": False,
                "stage": "serve",
                "listening": verification.listening,
                "image_min_tokens_warning_present": verification.image_min_tokens_warning_present,
            }
        )
        return 1

    parse_args = build_parse_args(args.pdf_path, str(out_dir), tier=args.tier)
    convert_log = out_dir / "pdf2md-convert.log"
    try:
        process = launch_convert(parse_args, convert_log)
    except Exception:
        server_process.terminate()
        raise

    emit(
        {
            "ok": True,
            "server_url": server_url,
            "convert_pid": process.pid,
            "convert_log": str(convert_log),
            "server_pid": server_process.pid,
            "server_note": "the VLM server is left running (port and VRAM held); stop this pid when no more conversions are planned, a second `run` would collide with it",
            "next_step": "poll `pdf2md.py convert status --log <convert_log>`; once finished is true, run "
            "`pdf2md.py postprocess <markdown output> -o <dir>` then `pdf2md.py refs <bibliography block> -o ref.md`, "
            "then `pdf2md.py validate <pdf> -o <dir> --fidelity` to list conversion errors and `pdf2md.py repair <pdf> -o <dir>` "
            "(a dry run; add --yes to write) to fix what can be fixed mechanically.",
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
