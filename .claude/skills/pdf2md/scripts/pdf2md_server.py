"""
pdf2md_server - Stage 3 of the pdf2md pipeline: start the standalone VLM
server llama-server.exe directly, bypassing mineru-kit's own vlm-server
wrapper.

Confirmed broken on Windows (2026-10-10, mineru-kit 4.0.11): that wrapper
(mineru/kit/vlm_server/llama_cpp_server.py) builds its argv as a Python list
and launches via os.execv, which does not quote its own injected default
`--grammar "root ::= .*"` (contains a space) when crossing the POSIX-argv to
Windows-command-line boundary. llama-server receives it split into separate
tokens and dies with "error: invalid argument: ::=" -- reproduced even with
zero flags supplied by the caller, so it is not a usage mistake. The exact
same failure mode was separately reproduced via PowerShell 5.1's
`Start-Process -ArgumentList <array>`, which has the identical quoting gap
for array elements containing spaces (isolated by testing the same grammar
string through `& $binary --grammar "root ::= .*"`, which works fine, proving
the binary and the grammar string are not the problem).

subprocess.Popen on Windows quotes a list of arguments correctly on its own
(via the stdlib's list2cmdline), so launching llama-server.exe directly this
way sidesteps the whole bug class rather than working around it with a
manually pre-quoted string.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

DEFAULT_PORT = 30000
DEFAULT_IMAGE_MIN_TOKENS = 1024
DEFAULT_N_PARALLEL = 4
DEFAULT_N_GPU_LAYERS = 99
GRAMMAR_DEFAULT = "root ::= .*"
_LISTENING_RE = re.compile(r"listening on http://[\w.:]+")
_IMAGE_MIN_TOKENS_WARNING = "Qwen-VL models require at minimum"


@dataclass
class VlmPaths:
    """
    --------------------------------------------------------------------------
    Purpose:
        The resolved, machine-specific paths pdf2md_server needs to build a
        llama-server invocation. Never hardcoded (R1) -- read from
        mineru-kit's own model registry at run time by pdf2md_models.

    Inputs:
        None.

    Outputs:
        binary (str): absolute path to llama-server.exe (or the
            extension-less binary on non-Windows).
        model_gguf (str): absolute path to the main model file.
        mmproj_gguf (str): absolute path to the multimodal projector file.
        alias (str): the model's registry name, used as --alias so
            /v1/models reports a stable name.
        n_ctx_train (int): the model's trained context length, read from the
            GGUF header -- used to size --ctx-size.
    --------------------------------------------------------------------------
    """

    binary: str
    model_gguf: str
    mmproj_gguf: str
    alias: str
    n_ctx_train: int


def build_llama_server_args(
    paths: VlmPaths,
    *,
    port: int = DEFAULT_PORT,
    image_min_tokens: int = DEFAULT_IMAGE_MIN_TOKENS,
    n_parallel: int = DEFAULT_N_PARALLEL,
    n_gpu_layers: int = DEFAULT_N_GPU_LAYERS,
) -> list[str]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Build the exact llama-server.exe argv mineru's own wrapper would
        build for this model (read from llama_cpp_server.py's main(), see
        module docstring), plus --image-min-tokens, which fixes a real
        grounding-accuracy warning for Qwen-VL-family models (confirmed
        present in the bundled binary's own --help), not a cosmetic one.

    Inputs:
        paths (VlmPaths): resolved binary/model/mmproj paths and alias.
        port (int): TCP port to bind.
        image_min_tokens (int): minimum image tokens for vision grounding.
        n_parallel (int): slot count (mineru's own hard-partitioned KV
            default is 4).
        n_gpu_layers (int): GPU offload layers (mineru's own default is 99,
            i.e. "as many as fit").

    Outputs:
        list[str]: the full argv, [binary, *flags] -- ready for
            subprocess.Popen with no shell involved.
    --------------------------------------------------------------------------
    """
    ctx_size = paths.n_ctx_train * n_parallel
    return [
        paths.binary,
        "--port", str(port),
        "--grammar", GRAMMAR_DEFAULT,
        "--special",
        "-m", paths.model_gguf,
        "--mmproj", paths.mmproj_gguf,
        "--alias", paths.alias,
        "--parallel", str(n_parallel),
        "--n-gpu-layers", str(n_gpu_layers),
        "--no-kv-unified",
        "--cache-ram", "0",
        "--ctx-size", str(ctx_size),
        "--image-min-tokens", str(image_min_tokens),
    ]


@dataclass
class ServerVerification:
    """
    --------------------------------------------------------------------------
    Purpose:
        What reading the server's own log tells us about whether it is
        actually usable -- never trust the launcher's exit code alone (R9).

    Inputs:
        None.

    Outputs:
        listening (bool): a "listening on http://..." line was found.
        image_min_tokens_warning_present (bool): the grounding warning is
            still present, meaning --image-min-tokens did not actually take
            effect.
    --------------------------------------------------------------------------
    """

    listening: bool
    image_min_tokens_warning_present: bool

    @property
    def healthy(self) -> bool:
        return self.listening and not self.image_min_tokens_warning_present


def verify_server_log(log_text: str) -> ServerVerification:
    """
    --------------------------------------------------------------------------
    Purpose:
        Pure check of a llama-server log's content against the two things
        that matter: did it actually start, and did the image-min-tokens
        fix actually reach the binary (the warning reappearing means a
        config/flag regression, not a cosmetic issue).

    Inputs:
        log_text (str): the server's stderr/stdout log content so far.

    Outputs:
        ServerVerification
    --------------------------------------------------------------------------
    """
    return ServerVerification(
        listening=bool(_LISTENING_RE.search(log_text)),
        image_min_tokens_warning_present=_IMAGE_MIN_TOKENS_WARNING in log_text,
    )


def wait_for_server(
    log_path: Path,
    *,
    timeout_s: float = 60.0,
    poll_interval_s: float = 1.0,
    read_text: Callable[[Path], str] | None = None,
    sleep: Callable[[float], None] | None = None,
    clock: Callable[[], float] | None = None,
) -> ServerVerification:
    """
    --------------------------------------------------------------------------
    Purpose:
        Poll a log file until the server reports it is listening, or a
        bounded timeout elapses (R10 -- no unbounded wait). Every effect is
        injected so this is testable without a real process or real clock
        (R19/R21).

    Inputs:
        log_path (Path): path to the server's log file.
        timeout_s (float): give up after this many seconds.
        poll_interval_s (float): sleep this long between reads.
        read_text (callable | None): Path -> str; defaults to reading the
            file, tolerating it not existing yet.
        sleep (callable | None): defaults to time.sleep.
        clock (callable | None): defaults to time.monotonic.

    Outputs:
        ServerVerification: the last read verification, whether or not it
            ever became healthy -- the caller decides what a timeout means.
    --------------------------------------------------------------------------
    """
    read_text = read_text or (lambda p: p.read_text(encoding="utf-8", errors="replace") if p.exists() else "")
    sleep = sleep or time.sleep
    clock = clock or time.monotonic

    deadline = clock() + timeout_s
    verification = ServerVerification(listening=False, image_min_tokens_warning_present=False)
    while clock() < deadline:
        verification = verify_server_log(read_text(log_path))
        if verification.healthy:
            return verification
        sleep(poll_interval_s)
    return verification


def launch_server(
    args: list[str],
    log_path: Path,
    *,
    popen: Callable[..., subprocess.Popen] | None = None,
) -> subprocess.Popen:
    """
    --------------------------------------------------------------------------
    Purpose:
        Launch llama-server.exe detached, with stdout+stderr merged into one
        log file (llama-server logs everything to stderr; merging means one
        file to poll). Detached so the server outlives this process.

    Inputs:
        args (list[str]): the full argv, as built by build_llama_server_args.
        log_path (Path): where to write the server's combined log.
        popen (callable | None): injected for tests (R20/R21); defaults to
            subprocess.Popen.

    Outputs:
        subprocess.Popen: the handle (mainly for its .pid).
    --------------------------------------------------------------------------
    """
    popen = popen or subprocess.Popen
    creationflags = 0
    if sys.platform == "win32":
        creationflags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    with open(log_path, "w", encoding="utf-8") as log_file:
        process = popen(
            args,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            creationflags=creationflags,
            close_fds=True,
        )
    # The child inherits its own duplicate of the handle at process-creation
    # time, so closing it here (parent side) does not affect the child's
    # ability to keep writing -- leaving it open would leak one fd per
    # server launched for as long as this (short-lived CLI) process runs.
    return process


def _main(argv: list[str] | None = None) -> int:
    import argparse

    from pdf2md_models import resolve_vlm_paths

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--image-min-tokens", type=int, default=DEFAULT_IMAGE_MIN_TOKENS)
    parser.add_argument("--log", default=None, help="log file path (default: <port>.llama-server.log beside the state dir)")
    parser.add_argument("--timeout", type=float, default=60.0, help="seconds to wait for the server to report listening")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    try:
        vlm_paths = resolve_vlm_paths()
    except Exception as exc:  # noqa: BLE001 -- surfaced as a named, reported failure (R12)
        report = {"ok": False, "stage": "resolve_vlm_paths", "error": str(exc)}
        print(json.dumps(report) if args.json else f"ERROR resolving model paths: {exc}")
        return 1

    server_args = build_llama_server_args(vlm_paths, port=args.port, image_min_tokens=args.image_min_tokens)
    log_path = Path(args.log) if args.log else Path.cwd() / f"pdf2md-vlm-{args.port}.log"
    process = launch_server(server_args, log_path)
    verification = wait_for_server(log_path, timeout_s=args.timeout)

    report = {
        "ok": verification.healthy,
        "pid": process.pid,
        "port": args.port,
        "log_path": str(log_path),
        "listening": verification.listening,
        "image_min_tokens_warning_present": verification.image_min_tokens_warning_present,
        "server_url": f"http://127.0.0.1:{args.port}/v1",
    }
    print(json.dumps(report) if args.json else report)
    return 0 if verification.healthy else 1


if __name__ == "__main__":
    raise SystemExit(_main())
