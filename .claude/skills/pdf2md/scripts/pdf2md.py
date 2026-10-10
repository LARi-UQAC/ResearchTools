"""
pdf2md - single entry point dispatching to every pdf2md pipeline stage.

Usage:
    python pdf2md.py bootstrap [--yes] [--server-url URL] [--tier basic|standard]
    python pdf2md.py version [--yes]
    python pdf2md.py serve [--port 30000] [--image-min-tokens 1024]
    python pdf2md.py convert start <pdf> -o <dir> [--tier advanced]
    python pdf2md.py convert status --log <path>
    python pdf2md.py postprocess <markdown_file> -o <dir>
    python pdf2md.py refs <bibliography_file> -o <ref.md>
    python pdf2md.py run <pdf> -o <dir> [--tier advanced] [--yes]

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

    print(f"Unknown command: {command!r}\n\n{__doc__}")
    return 2


def _run_full_pipeline(argv: list[str]) -> int:
    """
    --------------------------------------------------------------------------
    Purpose:
        Orchestrate every stage in order: bootstrap, version check (report
        only unless --yes), start the VLM server, start the conversion,
        then report that postprocess/refs are the operator's next manual
        step once the (potentially hours-long) conversion finishes --
        this command does not block waiting for it.

    Inputs:
        argv (list[str]): "run" subcommand's own args: <pdf> -o <dir>
            [--tier T] [--yes].

    Outputs:
        int: process exit code (R12).
    --------------------------------------------------------------------------
    """
    import argparse
    import json

    from pdf2md_bootstrap import default_config_path, run_bootstrap
    from pdf2md_convert import build_parse_args, launch_convert
    from pdf2md_models import bootstrap_tier_for
    from pdf2md_server import build_llama_server_args, launch_server, wait_for_server
    from pathlib import Path

    parser = argparse.ArgumentParser(prog="pdf2md run")
    parser.add_argument("pdf_path")
    parser.add_argument("-o", "--output-dir", required=True)
    parser.add_argument("--tier", default="advanced", choices=("flash", "basic", "standard", "advanced"))
    parser.add_argument("--port", type=int, default=30000)
    parser.add_argument("--yes", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    server_url = f"http://127.0.0.1:{args.port}/v1"

    bootstrap_report = run_bootstrap(
        config_path=default_config_path(),
        expected_server_url=server_url,
        tier=bootstrap_tier_for(args.tier),
        yes=args.yes,
    )
    if not bootstrap_report["ok"] and not args.yes:
        report = {"ok": False, "stage": "bootstrap", **bootstrap_report}
        print(json.dumps(report) if args.json else report)
        return 2

    from pdf2md_models import resolve_vlm_paths

    vlm_paths = resolve_vlm_paths()
    server_args = build_llama_server_args(vlm_paths, port=args.port)
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    server_log = out_dir / "pdf2md-vlm-server.log"
    launch_server(server_args, server_log)
    verification = wait_for_server(server_log, timeout_s=120.0)
    if not verification.healthy:
        report = {"ok": False, "stage": "serve", "listening": verification.listening, "image_min_tokens_warning_present": verification.image_min_tokens_warning_present}
        print(json.dumps(report) if args.json else report)
        return 1

    parse_args = build_parse_args(args.pdf_path, str(out_dir), tier=args.tier)
    convert_log = out_dir / "pdf2md-convert.log"
    process = launch_convert(parse_args, convert_log)

    report = {
        "ok": True,
        "server_url": server_url,
        "convert_pid": process.pid,
        "convert_log": str(convert_log),
        "next_step": "poll `pdf2md.py convert status --log <convert_log>`; once finished is true, run "
        "`pdf2md.py postprocess <markdown output> -o <dir>` then `pdf2md.py refs <bibliography block> -o ref.md`.",
    }
    print(json.dumps(report) if args.json else report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
