#!/usr/bin/env python3
"""Shared helpers for the professor-expertise-finder skill.

One implementation of the name/location normalization and the data-root
resolution, imported by table.py, exclusions.py, file_search.py, and
selections.py. Nothing here is specific to one of those scripts; a change
here changes all four call sites at once rather than drifting between
four near-copies.
"""
from __future__ import annotations

import json
import os
import re
import unicodedata
from pathlib import Path

DEFAULT_DATA_ROOT = Path.home() / "workspace" / "professor-expertise"
DATA_ROOT_ENV = "PROFESSOR_EXPERTISE_DATA"

CONFIG_PATH = Path(__file__).resolve().parent / "pef_config.json"


def data_root() -> Path:
    """
    --------------------------------------------------------------------------
    Purpose:
        Resolve the root directory the skill's data instances (location
        tables, batch registries) live under.

    Inputs:
        None (reads the PROFESSOR_EXPERTISE_DATA environment variable).

    Outputs:
        root (Path): the value of PROFESSOR_EXPERTISE_DATA when set, else
            the documented default ~/workspace/professor-expertise (R1 - no
            hardcoded path; a professor who wants a different root sets the
            environment variable rather than editing this file).
    --------------------------------------------------------------------------
    """
    value = os.environ.get(DATA_ROOT_ENV)
    return Path(value) if value else DEFAULT_DATA_ROOT


def load_config() -> dict:
    """
    --------------------------------------------------------------------------
    Purpose:
        Read the skill's policy constants (rubric subscore values, the
        retain threshold, the per-university cap) from pef_config.json.

    Inputs:
        None.

    Outputs:
        config (dict): the parsed JSON object.

    Raises:
        FileNotFoundError: pef_config.json is missing.
        ValueError: the file exists but is not valid JSON, or a required
            key is absent (R3 - a missing configuration value is an
            explicit error, never a silent default).
    --------------------------------------------------------------------------
    """
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(f"missing policy config: {CONFIG_PATH}")
    try:
        config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"malformed policy config {CONFIG_PATH}: {exc}") from exc
    for key in ("subscore_values", "retain_threshold", "max_per_university"):
        if key not in config:
            raise ValueError(f"policy config {CONFIG_PATH} is missing key {key!r}")
    return config


def slugify(text: str) -> str:
    """
    --------------------------------------------------------------------------
    Purpose:
        Turn a free-text location or batch name into a filesystem-safe,
        accent-free slug used as a directory name.

    Inputs:
        text (str): e.g. "Canada, Ontario", "France, Île-de-France",
            "Worldwide", "Concours 2027".

    Outputs:
        slug (str): lowercase ASCII, words joined by single hyphens, never
            empty (falls back to "unspecified").
    --------------------------------------------------------------------------
    """
    folded = unicodedata.normalize("NFKD", text)
    folded = "".join(c for c in folded if not unicodedata.combining(c))
    folded = re.sub(r"[^a-zA-Z0-9]+", "-", folded.lower()).strip("-")
    return re.sub(r"-+", "-", folded) or "unspecified"


def norm(text: str) -> str:
    """
    --------------------------------------------------------------------------
    Purpose:
        Fold a name or university string for case/accent/whitespace
        -insensitive comparison.

    Inputs:
        text (str | None): any free-text field; None is treated as "".

    Outputs:
        folded (str): lowercase, accent-stripped, non-alphanumeric runs
            collapsed to a single space, trimmed.
    --------------------------------------------------------------------------
    """
    folded = unicodedata.normalize("NFKD", text or "")
    folded = "".join(c for c in folded if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", folded.lower()).strip()


def name_key(text: str) -> tuple[str, ...]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Build a word-order-insensitive comparison key for a person's name,
        so "Jane Doe" and "Doe, Jane" match.

    Inputs:
        text (str): a full name, in any word order.

    Outputs:
        key (tuple[str, ...]): the normalized words of the name, sorted.
    --------------------------------------------------------------------------
    """
    return tuple(sorted(norm(text).split()))
