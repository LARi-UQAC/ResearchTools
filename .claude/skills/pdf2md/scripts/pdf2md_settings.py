"""
pdf2md_settings - the stage 1 to 6 settings (port, timeouts, pinned packages)
read from pdf2md-pipeline.json, never written as literals in the stage modules
(R0). Every value carries its provenance in that file (R4).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_CONFIG_PATH = Path(__file__).with_name("pdf2md-pipeline.json")
_CONFIG_KEYS = (
    "port",
    "image_min_tokens",
    "n_parallel",
    "n_gpu_layers",
    "server_wait_s",
    "server_poll_interval_s",
    "pip_show_timeout_s",
    "pip_install_timeout_s",
    "pip_audit_timeout_s",
    "models_show_timeout_s",
    "models_download_timeout_s",
    "resolve_snippet_timeout_s",
    "pypi_timeout_s",
    "pinned_packages",
)


def load_pipeline_config(path: Path = _CONFIG_PATH) -> dict:
    """
    --------------------------------------------------------------------------
    Purpose:
        Read pdf2md-pipeline.json and return key -> value for every key in
        _CONFIG_KEYS. A missing file or key is an explicit error naming the
        key and the file (R3), never a silent default.

    Inputs:
        path (Path): the JSON file; defaults to the one beside this module.

    Outputs:
        dict: key -> value (the provenance string is not returned).

    Raises:
        RuntimeError: the file is absent, or a key of _CONFIG_KEYS is missing
            or has no "value" member.
    --------------------------------------------------------------------------
    """
    if not path.exists():
        raise RuntimeError(f"pdf2md settings file not found: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    missing = [key for key in _CONFIG_KEYS if not isinstance(data.get(key), dict) or "value" not in data[key]]
    if missing:
        raise RuntimeError(f"pdf2md settings: missing key(s) {missing} in {path}")
    return {key: data[key]["value"] for key in _CONFIG_KEYS}


def pip_command(*args: str) -> list[str]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Build a pip argv that runs under the interpreter running this skill
        (sys.executable -m pip), so an install lands in the same environment
        the skill imports from, not in whichever `pip` comes first on PATH.

    Inputs:
        *args (str): pip arguments, e.g. "show", "mineru".

    Outputs:
        list[str]: [sys.executable, "-m", "pip", *args].
    --------------------------------------------------------------------------
    """
    return [sys.executable, "-m", "pip", *args]
