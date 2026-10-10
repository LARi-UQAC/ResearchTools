"""
pdf2md_convert - Stage 4 of the pdf2md pipeline: run `mineru-kit parse`
detached (it can run for hours on a long thesis at --tier advanced) and
report progress from its own log, rather than blocking the caller.

--ocr-mode is left at mineru's own default ("auto"): forcing "ocr" is LESS
accurate than the native text layer where the PDF already has one, which is
mineru's own OCR-det/OCR-rec speed (confirmed in a real run: tens of pages
per second, consistent with reusing an embedded text layer rather than
doing full visual OCR). --disable-image-analysis is never passed.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

_HTTP_CLIENT_LINE = "get http-client predictor cost"
_IN_PROCESS_ENGINE_LINE = "Using llama-cpp-engine as the inference engine for VLM"
_WINDOW_RE = re.compile(r"Hybrid processing window (\d+)/(\d+)")
_PARSED_RE = re.compile(r"Parsed (\d+) input")
# mineru-kit's own generic terminal-failure template (confirmed verbatim in
# mineru/utils/translations.py: "Failed to parse {path}: {error}", the exact
# counterpart of the success template "Parsed {count} input(s)." _PARSED_RE
# already matches). Without this, a crashed conversion (measured 2026-10-10:
# a Vulkan driver crash, "vk::Queue::submit: ErrorDeviceLost", mid-run) was
# reported as finished=false forever -- indistinguishable from "still
# running" to a caller polling this status.
_FAILED_RE = re.compile(r"Error:\s*Failed to parse.*", re.DOTALL)


@dataclass
class ConvertProgress:
    """
    --------------------------------------------------------------------------
    Purpose:
        What can be read back from a `mineru-kit parse` log, without
        trusting the launcher's own exit code (R9 -- the process is still
        running when this is checked, so there is no exit code yet).

    Inputs:
        None.

    Outputs:
        routed_via_vlm_server (bool | None): True/False once determined,
            None if the log has not reached that point yet. False is a
            real finding -- it means stage 3's server_url config did not
            take effect and the slow/warning-prone in-process engine is
            being used instead.
        current_window (tuple[int, int] | None): (window, total_windows).
        finished (bool): a "Parsed N input(s)" success line was seen.
        error (str | None): mineru-kit's own "Error: Failed to parse ..."
            terminal-failure line, or None while the run is either still
            going or has already finished successfully. A caller polling
            this status must check error BEFORE treating finished=False
            as "still running" -- a crashed process never becomes
            finished=True on its own.
    --------------------------------------------------------------------------
    """

    routed_via_vlm_server: bool | None
    current_window: tuple[int, int] | None
    finished: bool
    error: str | None


def parse_convert_log(log_text: str) -> ConvertProgress:
    """
    --------------------------------------------------------------------------
    Purpose:
        Pure parse of a parse-run's log text into a progress snapshot.

    Inputs:
        log_text (str): the log's content so far.

    Outputs:
        ConvertProgress
    --------------------------------------------------------------------------
    """
    routed: bool | None = None
    if _HTTP_CLIENT_LINE in log_text:
        routed = True
    elif _IN_PROCESS_ENGINE_LINE in log_text:
        routed = False

    window_matches = _WINDOW_RE.findall(log_text)
    current_window = (int(window_matches[-1][0]), int(window_matches[-1][1])) if window_matches else None

    failed_match = _FAILED_RE.search(log_text)
    error = failed_match.group(0).strip() if failed_match else None

    return ConvertProgress(
        routed_via_vlm_server=routed, current_window=current_window, finished=bool(_PARSED_RE.search(log_text)), error=error
    )


def build_parse_args(
    pdf_path: str,
    output_dir: str,
    *,
    tier: str = "advanced",
    pages: str = "all",
    output_format: str = "markdown",
) -> list[str]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Build the `mineru-kit parse` argv. --ocr-mode and image analysis
        are deliberately left at their accuracy-preserving defaults (see
        module docstring); never pass --disable-image-analysis or
        --ocr-mode ocr here.

    Inputs:
        pdf_path (str): the source PDF.
        output_dir (str): where mineru writes its markdown output.
        tier (str): "flash" | "basic" | "standard" | "advanced".
        pages (str): mineru's own page-range syntax; "all" for the whole doc.
        output_format (str): "markdown" | "middle_json" | "zip".

    Outputs:
        list[str]: argv, [mineru-kit, parse, ...] -- ready for
            subprocess.Popen with no shell involved.
    --------------------------------------------------------------------------
    """
    return [
        "mineru-kit", "parse", pdf_path,
        "-o", output_dir,
        "--pages", pages,
        "--tier", tier,
        "--format", output_format,
        "-v",
    ]


def launch_convert(args: list[str], log_path: Path, *, popen: Callable[..., subprocess.Popen] | None = None) -> subprocess.Popen:
    """
    --------------------------------------------------------------------------
    Purpose:
        Launch `mineru-kit parse` detached (R9's companion: a caller that
        blocks on a multi-hour conversion is not useful; this returns
        immediately with a pid and a log path to poll).

    Inputs:
        args (list[str]): as built by build_parse_args.
        log_path (Path): combined stdout+stderr destination.
        popen (callable | None): injected for tests; defaults to
            subprocess.Popen.

    Outputs:
        subprocess.Popen
    --------------------------------------------------------------------------
    """
    popen = popen or subprocess.Popen
    creationflags = 0
    if sys.platform == "win32":
        creationflags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    with open(log_path, "w", encoding="utf-8") as log_file:
        process = popen(args, stdout=log_file, stderr=subprocess.STDOUT, creationflags=creationflags, close_fds=True)
    # See pdf2md_server.launch_server's identical comment: the child keeps
    # its own duplicated handle, so closing this one in the parent avoids
    # an fd leak rather than risking the child losing its output stream.
    return process


def _main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    start = subparsers.add_parser("start", help="launch the conversion detached")
    start.add_argument("pdf_path")
    start.add_argument("-o", "--output-dir", required=True)
    start.add_argument("--tier", default="advanced", choices=("flash", "basic", "standard", "advanced"))
    start.add_argument("--log", default=None)
    start.add_argument("--json", action="store_true")

    status = subparsers.add_parser("status", help="report progress from an existing log")
    status.add_argument("--log", required=True)
    status.add_argument("--json", action="store_true")

    args = parser.parse_args(argv)

    if args.command == "start":
        parse_args = build_parse_args(args.pdf_path, args.output_dir, tier=args.tier)
        log_path = Path(args.log) if args.log else Path(args.output_dir) / "pdf2md-convert.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        process = launch_convert(parse_args, log_path)
        report = {"ok": True, "pid": process.pid, "log_path": str(log_path), "tier": args.tier}
        print(json.dumps(report) if args.json else report)
        return 0

    log_path = Path(args.log)
    progress = parse_convert_log(log_path.read_text(encoding="utf-8", errors="replace") if log_path.exists() else "")
    report = {
        "ok": progress.error is None,
        "routed_via_vlm_server": progress.routed_via_vlm_server,
        "current_window": list(progress.current_window) if progress.current_window else None,
        "finished": progress.finished,
        "error": progress.error,
    }
    print(json.dumps(report) if args.json else report)
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
