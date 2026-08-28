#!/usr/bin/env python3
"""
vram_probe.py - stage 1 of the VRAM optimizer: report facts, change nothing.

Answers the four questions the optimizer needs before it may build anything: what the tag
is made of (manifest layers, hence whether a vision projector can be dropped), how large a
window the model itself allows, what the daemon is actually configured with, and what the
card is. Every answer comes from a file, a subprocess, or the daemon's own API, never from
a model card or an assumption.

Consumed by vram_optimizer.py. Writes nothing.
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_OLLAMA_TIMEOUT_S = 30.0
_DEFAULT_MANIFESTS_ROOT = Path.home() / ".ollama" / "models" / "manifests"
_DEFAULT_SERVER_LOG = Path(os.environ.get("LOCALAPPDATA", "")) / "Ollama" / "server.log"

# 'context length      262144' inside the Model block of `ollama show`.
_CONTEXT_LENGTH_RE = re.compile(r"^\s*context length\s+(\d+)\s*$", re.MULTILINE)

# 'OLLAMA_KV_CACHE_TYPE:q8_0' inside the env map of the 'server config' log line.
_ENV_PAIR_RE = re.compile(r"(OLLAMA_[A-Z_]+):([^\s\]]*)")


class ProbeError(Exception):
    """Raised when a fact cannot be established. Never returns a guess instead."""


def _ollama_show(tag: str, modelfile: bool = False) -> str:
    """
    --------------------------------------------------------------------------
    Purpose:
        Run `ollama show` and return its stdout. Isolated so a test can replace
        the subprocess without patching subprocess globally.

    Inputs:
        tag (str): the model tag to describe.
        modelfile (bool): pass --modelfile instead of the human summary.

    Outputs:
        result (str): the command's stdout.

    Raises:
        ProbeError: the command is absent, timed out, or exited non-zero.
    --------------------------------------------------------------------------
    """
    cmd = ["ollama", "show", tag] + (["--modelfile"] if modelfile else [])
    try:
        done = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=_OLLAMA_TIMEOUT_S)
    except (OSError, subprocess.SubprocessError) as exc:
        raise ProbeError(f"[VRAM-PROBE] `{' '.join(cmd)}` could not run: {exc}") from exc
    if done.returncode != 0:
        raise ProbeError(
            f"[VRAM-PROBE] `{' '.join(cmd)}` exited {done.returncode}: {done.stderr.strip()}"
        )
    return done.stdout


def manifest_layers(tag: str, manifests_root: Path | None = None) -> list[dict[str, Any]]:
    """
    --------------------------------------------------------------------------
    Purpose:
        List the layers of a tag's manifest. This is what distinguishes a model
        whose vision support sits in a SEPARATE projector layer, which a
        text-only variant can simply not name, from one whose vision is baked
        into a single model layer, where no margin can be recovered that way.
        Both cases were measured on this machine on 2026-08-27.

    Inputs:
        tag (str): "name:tag"; a bare name is treated as "name:latest".
        manifests_root (Path | None): manifest tree root; defaults to
            ~/.ollama/models/manifests.

    Outputs:
        result (list[dict]): one {"kind", "size", "digest"} per layer, where
        kind is the media type's last dotted segment (model, projector,
        template, system, params, license).

    Raises:
        ProbeError: no manifest file for this tag anywhere under the root.
        Locally created tags sit directly under <root>/<name>/<tag> while
        pulled ones nest under registry.ollama.ai/library, so the walk covers
        both rather than assuming one layout.
    --------------------------------------------------------------------------
    """
    root = manifests_root or _DEFAULT_MANIFESTS_ROOT
    name, _, version = tag.partition(":")
    version = version or "latest"
    for base, _dirs, _files in os.walk(root):
        candidate = Path(base) / name / version
        if candidate.is_file():
            manifest = json.loads(candidate.read_text(encoding="utf-8"))
            return [
                {
                    "kind": layer["mediaType"].rsplit(".", 1)[-1],
                    "size": int(layer.get("size", 0)),
                    "digest": layer.get("digest", ""),
                }
                for layer in manifest.get("layers", [])
            ]
    raise ProbeError(f"[VRAM-PROBE] no manifest for {tag!r} under {root}.")


def projector_layer(layers: list[dict[str, Any]]) -> dict[str, Any] | None:
    """
    --------------------------------------------------------------------------
    Purpose:
        Return the vision projector layer, when the tag carries one as a
        separate layer.

    Inputs:
        layers (list[dict]): the output of manifest_layers.

    Outputs:
        result (dict | None): the projector layer, or None.
    --------------------------------------------------------------------------
    """
    for layer in layers:
        if layer["kind"] == "projector":
            return layer
    return None


def model_layer(layers: list[dict[str, Any]]) -> dict[str, Any]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Return the language model layer, the one a text-only variant names
        directly when the projector is dropped.

    Inputs:
        layers (list[dict]): the output of manifest_layers.

    Outputs:
        result (dict): the model layer.

    Raises:
        ProbeError: the manifest declares no model layer.
    --------------------------------------------------------------------------
    """
    for layer in layers:
        if layer["kind"] == "model":
            return layer
    raise ProbeError("[VRAM-PROBE] manifest declares no model layer.")


def native_max_context(tag: str) -> int:
    """
    --------------------------------------------------------------------------
    Purpose:
        Report the largest window the model itself supports. Ollama does not
        error above it - it clamps silently - so the ladder must stop here
        rather than discover the ceiling by measuring identical rungs.

    Inputs:
        tag (str): the model tag.

    Outputs:
        result (int): the native context maximum in tokens.

    Raises:
        ProbeError: `ollama show` printed no context length.
    --------------------------------------------------------------------------
    """
    match = _CONTEXT_LENGTH_RE.search(_ollama_show(tag))
    if not match:
        raise ProbeError(f"[VRAM-PROBE] `ollama show {tag}` reported no context length.")
    return int(match.group(1))


def daemon_settings(server_log: Path | None = None) -> dict[str, str]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Report the OLLAMA_* settings the RUNNING daemon actually has, read from
        the last 'server config' line it logged at start. This process's own
        environment does not reliably reflect the daemon's: the daemon is
        launched by the tray application at logon and never sees a variable set
        afterwards in another shell.

    Inputs:
        server_log (Path | None): defaults to %LOCALAPPDATA%\\Ollama\\server.log.

    Outputs:
        result (dict[str, str]): variable name to value, taken from the LAST
        such line, since every restart appends one rather than replacing it.

    Raises:
        ProbeError: the log is absent or carries no 'server config' line.
    --------------------------------------------------------------------------
    """
    path = server_log or _DEFAULT_SERVER_LOG
    if not path.is_file():
        raise ProbeError(f"[VRAM-PROBE] no Ollama server log at {path}.")
    lines = [
        line
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines()
        if "server config" in line
    ]
    if not lines:
        raise ProbeError(f"[VRAM-PROBE] {path} carries no 'server config' line.")
    return dict(_ENV_PAIR_RE.findall(lines[-1]))
