"""
pdf2md_config - Stage 1c of the pdf2md pipeline: diagnose and fix
~/.mineru/config.yaml.

Fixes two defects confirmed against the installed mineru-kit 4.0.11 by
reading mineru/config.py directly (2026-10-10): a top-level "vlm:" key is
silently accepted and ignored by pydantic (it belongs under "model:"), and
llm_aided.max_concurrency defaults to 16, which drives 16-way CPU contention
on a local LLM used for title_leveling/cross_page_table_cell_merge, pushing
every request past the OpenAI SDK's hardcoded 600s x 3-retry ceiling
(mineru/backend/postprocess/llm_client.py's _MAX_LLM_RETRIES = 3, no timeout
override exposed anywhere in mineru's config surface).
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any

import yaml

DEFAULT_MAX_CONCURRENCY_CAP = 2

_HEADER_COMMENT = (
    "# Rewritten by the pdf2md skill ({date}).\n"
    "# model.vlm must sit under model: -- a top-level vlm: key is a stray\n"
    "# field pydantic ignores in silence (confirmed in mineru/config.py's\n"
    "# Config/ModelConfig classes). llm_aided.max_concurrency is capped low\n"
    "# because 16 concurrent calls to one local model contend for the same\n"
    "# CPU/GPU and each one times out instead of succeeding slowly.\n"
)


@dataclass
class ConfigIssue:
    """
    --------------------------------------------------------------------------
    Purpose:
        One diagnosed problem in a loaded mineru config.yaml dict.

    Inputs:
        code (str): a short machine-readable identifier, e.g.
            "vlm_wrong_nesting", "max_concurrency_too_high", "server_url_unset".
        message (str): a human-readable explanation.

    Outputs:
        None.
    --------------------------------------------------------------------------
    """

    code: str
    message: str


@dataclass
class ConfigDiagnosis:
    """
    --------------------------------------------------------------------------
    Purpose:
        The full result of inspecting a loaded config dict: every issue
        found, and whether an llm_aided block exists at all (fixing its
        concurrency is only relevant if the operator has opted into it).

    Inputs:
        None.

    Outputs:
        issues (list[ConfigIssue])
        has_llm_aided (bool)
    --------------------------------------------------------------------------
    """

    issues: list[ConfigIssue] = field(default_factory=list)
    has_llm_aided: bool = False

    @property
    def clean(self) -> bool:
        return not self.issues


def diagnose(
    config: dict[str, Any],
    *,
    expected_server_url: str | None = None,
    max_concurrency_cap: int = DEFAULT_MAX_CONCURRENCY_CAP,
) -> ConfigDiagnosis:
    """
    --------------------------------------------------------------------------
    Purpose:
        Inspect a parsed config.yaml dict and report every known defect,
        without modifying it. Never raises on a missing key -- a key that
        is simply absent is a normal, fixable state, not a malformed file.

    Inputs:
        config (dict): the parsed YAML, or {} for a missing/empty file.
        expected_server_url (str | None): the VLM server URL pdf2md wants
            configured; None means "don't check server_url at all" (used
            when diagnosing before a server has even been started).
        max_concurrency_cap (int): the ceiling above which llm_aided's
            concurrency is flagged.

    Outputs:
        ConfigDiagnosis
    --------------------------------------------------------------------------
    """
    diagnosis = ConfigDiagnosis()

    if "vlm" in config and isinstance(config.get("vlm"), dict):
        diagnosis.issues.append(
            ConfigIssue(
                "vlm_wrong_nesting",
                "Top-level 'vlm:' key found -- pydantic silently ignores it. "
                "Must be nested under 'model: vlm:'.",
            )
        )

    model_vlm = (config.get("model") or {}).get("vlm") or {}
    current_server_url = model_vlm.get("server_url") if isinstance(model_vlm, dict) else None
    if expected_server_url is not None and current_server_url != expected_server_url:
        diagnosis.issues.append(
            ConfigIssue(
                "server_url_unset",
                f"model.vlm.server_url is {current_server_url!r}, expected {expected_server_url!r}.",
            )
        )

    llm_aided = config.get("llm_aided")
    if isinstance(llm_aided, dict):
        diagnosis.has_llm_aided = True
        current_concurrency = llm_aided.get("max_concurrency")
        if not isinstance(current_concurrency, int) or current_concurrency > max_concurrency_cap:
            diagnosis.issues.append(
                ConfigIssue(
                    "max_concurrency_too_high",
                    f"llm_aided.max_concurrency is {current_concurrency!r}, "
                    f"recommended <= {max_concurrency_cap} to avoid CPU-contention timeouts.",
                )
            )

    return diagnosis


def apply_fixes(
    config: dict[str, Any],
    *,
    server_url: str | None,
    max_concurrency_cap: int = DEFAULT_MAX_CONCURRENCY_CAP,
) -> dict[str, Any]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Return a NEW config dict with every known issue fixed: the stray
        top-level "vlm:" key removed (its content discarded -- it never
        did anything, so nothing of value is lost), model.vlm.server_url
        set, and llm_aided.max_concurrency capped if an llm_aided block
        exists. Pure function; the caller decides whether/how to write it.

    Inputs:
        config (dict): the parsed YAML, or {}.
        server_url (str | None): the VLM server URL to set under
            model.vlm.server_url; None leaves it untouched.
        max_concurrency_cap (int): the value to cap llm_aided.max_concurrency
            at, if llm_aided is present and currently above it.

    Outputs:
        dict: the fixed config, ready for yaml.safe_dump.
    --------------------------------------------------------------------------
    """
    fixed = copy.deepcopy(config)
    fixed.pop("vlm", None)

    if server_url is not None:
        model_block = fixed.setdefault("model", {})
        vlm_block = model_block.setdefault("vlm", {})
        vlm_block["server_url"] = server_url

    llm_aided = fixed.get("llm_aided")
    if isinstance(llm_aided, dict):
        current = llm_aided.get("max_concurrency")
        if not isinstance(current, int) or current > max_concurrency_cap:
            llm_aided["max_concurrency"] = max_concurrency_cap

    return fixed


def render_config_yaml(config: dict[str, Any], *, date: str) -> str:
    """
    --------------------------------------------------------------------------
    Purpose:
        Serialize a fixed config dict back to YAML text, with an explanatory
        header comment. Regenerates the file rather than patching the
        original text in place, trading the operator's own comments for a
        guaranteed-correct structure -- acceptable for a small, mostly
        machine-managed file (R13: the header states what changed and why).

    Inputs:
        config (dict): the config to serialize.
        date (str): ISO date stamp for the header comment's provenance.

    Outputs:
        str: complete YAML file content, including the header.
    --------------------------------------------------------------------------
    """
    body = yaml.safe_dump(config, default_flow_style=False, sort_keys=False, allow_unicode=True)
    return _HEADER_COMMENT.format(date=date) + "\n" + body


__all__ = [
    "ConfigIssue",
    "ConfigDiagnosis",
    "diagnose",
    "apply_fixes",
    "render_config_yaml",
    "DEFAULT_MAX_CONCURRENCY_CAP",
]
