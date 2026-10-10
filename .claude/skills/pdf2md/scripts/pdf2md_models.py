"""
pdf2md_models - model/package readiness for the pdf2md pipeline (stage 1).

Resolves the VLM model's real paths through mineru's OWN registry module
rather than reimplementing its file-naming convention (R2: one module owns
an external identifier's resolution; duplicating it elsewhere is how two
truths drift apart). Also parses `mineru-kit models show`'s human-readable
output, since that CLI has no --json flag (confirmed: its --help lists none).
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from typing import Callable

_READY_LINE_RE = re.compile(r"^\s*([\w.\-]+):\s*(ready|missing)\s*$", re.MULTILINE)
_TIER_LINE_RE = re.compile(r"^\s*(flash|basic|standard|advanced):\s*(.+)$", re.MULTILINE)

#: mineru-kit models download --tier only accepts these two (confirmed via
#: --help, 2026-10-10); "advanced" reuses standard's model at higher effort
#: (mineru/parser/tier.py maps flash/basic/standard/advanced to
#: flash/medium/high/xhigh "effort", no separate advanced model exists).
DOWNLOADABLE_TIERS = ("basic", "standard")


@dataclass
class ModelReadiness:
    """
    --------------------------------------------------------------------------
    Purpose:
        Parsed readiness of every model repo `mineru-kit models show`
        reports, plus which repos each tier actually needs.

    Inputs:
        None.

    Outputs:
        repo_status (dict[str, bool]): repo name -> True if "ready".
        tier_repos (dict[str, list[str]]): tier name -> repo names it needs.
    --------------------------------------------------------------------------
    """

    repo_status: dict[str, bool]
    tier_repos: dict[str, list[str]]

    def tier_ready(self, tier: str) -> bool:
        needed = self.tier_repos.get(tier, [])
        return bool(needed) and all(self.repo_status.get(repo, False) for repo in needed)


def parse_models_show(output: str) -> ModelReadiness:
    """
    --------------------------------------------------------------------------
    Purpose:
        Parse the text `mineru-kit models show` prints into a structured
        readiness report. The command has no machine-readable output mode,
        so this is a best-effort text parser over its documented shape:

            Repos:
              <name>: ready
              (<path>)
            Model tiers:
              standard: <name>, <name>

    Inputs:
        output (str): the command's full stdout.

    Outputs:
        ModelReadiness
    --------------------------------------------------------------------------
    """
    repo_status = {name: (status == "ready") for name, status in _READY_LINE_RE.findall(output)}
    tier_repos = {
        tier: [name.strip() for name in repos.split(",")]
        for tier, repos in _TIER_LINE_RE.findall(output)
    }
    return ModelReadiness(repo_status=repo_status, tier_repos=tier_repos)


def run_models_show(runner: Callable[..., subprocess.CompletedProcess] | None = None) -> str:
    """
    --------------------------------------------------------------------------
    Purpose:
        Run `mineru-kit models show` and return its stdout. Thin IO wrapper
        kept separate from parse_models_show so tests exercise the parser
        on fixture text without spawning a process (R20/R21).

    Inputs:
        runner (callable | None): injected for tests; defaults to
            subprocess.run.

    Outputs:
        str: the command's stdout.

    Raises:
        subprocess.CalledProcessError: if the command exits non-zero.
    --------------------------------------------------------------------------
    """
    runner = runner or subprocess.run
    result = runner(["mineru-kit", "models", "show"], capture_output=True, text=True, timeout=30, check=True)
    return result.stdout


_RESOLVE_SNIPPET = (
    "from mineru.model.registry import vlm_model_repo\n"
    "from mineru.kit.vlm_server.llama_cpp_server import _read_gguf_context_length\n"
    "from pathlib import Path\n"
    "repo = vlm_model_repo('llama-cpp')\n"
    "model_dir = repo.ensure()\n"
    "model_gguf = model_dir / repo.paths['main']\n"
    "print(model_dir)\n"
    "print(model_gguf)\n"
    "print(model_dir / repo.paths['mmproj'])\n"
    "print(repo.name)\n"
    "print(_read_gguf_context_length(Path(model_gguf)))\n"
)


def resolve_vlm_paths(runner: Callable[..., subprocess.CompletedProcess] | None = None):
    """
    --------------------------------------------------------------------------
    Purpose:
        Resolve the VLM model's binary/model/mmproj paths and trained
        context length by asking mineru's OWN registry module, via a small
        subprocess snippet, rather than reimplementing its file-naming
        convention (R2). Returns a pdf2md_server.VlmPaths.

    Inputs:
        runner (callable | None): injected for tests; defaults to
            subprocess.run.

    Outputs:
        VlmPaths (from pdf2md_server)

    Raises:
        RuntimeError: if the registry snippet fails (mineru not installed,
            model not downloaded, or an unexpected output shape) -- named
            rather than left as a bare CalledProcessError (R3).
    --------------------------------------------------------------------------
    """
    import shutil
    import sys
    from pathlib import Path

    from pdf2md_server import VlmPaths

    runner = runner or subprocess.run
    result = runner(["python", "-c", _RESOLVE_SNIPPET], capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        raise RuntimeError(
            "Could not resolve the VLM model via mineru's own registry "
            f"(exit {result.returncode}): {result.stderr.strip()}"
        )
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    if len(lines) < 5:
        raise RuntimeError(f"Unexpected output from the model-registry snippet: {result.stdout!r}")
    _model_dir, model_gguf, mmproj_gguf, alias, n_ctx_train_text = lines[:5]

    binary = shutil.which("llama-server") or shutil.which("llama-server.exe")
    if binary is None:
        import mineru_llama_cpp  # noqa: PLC0415 -- optional dependency, only needed here

        binary_name = "llama-server.exe" if sys.platform == "win32" else "llama-server"
        binary = str(Path(mineru_llama_cpp.__file__).resolve().parent / "bin" / binary_name)

    try:
        n_ctx_train = int(n_ctx_train_text)
    except ValueError as exc:
        raise RuntimeError(f"Model-registry snippet returned a non-integer context length: {n_ctx_train_text!r}") from exc
    if n_ctx_train <= 0:
        raise RuntimeError("Model-registry snippet could not read the model's trained context length from its GGUF header.")

    return VlmPaths(binary=binary, model_gguf=model_gguf, mmproj_gguf=mmproj_gguf, alias=alias, n_ctx_train=n_ctx_train)


__all__ = [
    "ModelReadiness",
    "parse_models_show",
    "run_models_show",
    "resolve_vlm_paths",
    "DOWNLOADABLE_TIERS",
]
