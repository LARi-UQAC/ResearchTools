#!/usr/bin/env python3
"""
bench_config.py - read opt-local-stt-vram's stt-bench-config.json.

Every value in that file is a {"value": ..., "provenance": ...} pair (R4), the shape
rt-observe's observe-config.json already uses. A missing key is an explicit error naming
the dotted path and the file (R3); nothing here supplies a default.
"""
import json
from pathlib import Path

CONFIG_PATH = Path(__file__).resolve().parent.parent / "stt-bench-config.json"


def load_config(path: Path = CONFIG_PATH) -> dict:
    """
    --------------------------------------------------------------------------
    Purpose:
        Parse the benchmark configuration file.

    Inputs:
        path (Path): the JSON file; defaults to the skill's own stt-bench-config.json

    Outputs:
        config (dict): the parsed file

    Raises:
        FileNotFoundError: the file does not exist.
        ValueError: the file is not valid JSON.
    --------------------------------------------------------------------------
    """
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path} is not valid JSON: {exc}") from exc


def value(config: dict, *keys: str):
    """
    --------------------------------------------------------------------------
    Purpose:
        Return the "value" of a configuration entry addressed by its key path.

    Inputs:
        config (dict): parsed stt-bench-config.json
        keys (str): the path, e.g. ("gate", "max_llm_demoted_pct")

    Outputs:
        value (Any): the entry's "value" field

    Raises:
        KeyError: any key on the path, or the entry's "value" field, is absent.
    --------------------------------------------------------------------------
    """
    node = config
    for key in keys:
        if not isinstance(node, dict) or key not in node:
            raise KeyError(f"stt-bench-config.json declares no {'.'.join(keys)} "
                           f"(missing at '{key}')")
        node = node[key]
    if not isinstance(node, dict) or "value" not in node:
        raise KeyError(f"stt-bench-config.json entry {'.'.join(keys)} has no 'value' field")
    return node["value"]
