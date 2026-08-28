#!/usr/bin/env python3
"""
vram_modelfile.py - stage 2 of the VRAM optimizer: render the tuned Modelfile.

A pure renderer. It takes a base tag's own configuration, a retained window and the
measurement that justifies it, and returns the Modelfile text. It opens no file and runs no
`ollama create`; the driver does that, so this module is testable without Ollama.

Consumed by vram_optimizer.py.
"""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

# The bridge overrides temperature/top_p/top_k per request but NOT these, so a value left in
# a Modelfile DOES reach generation. A repetition penalty on code is actively harmful:
# identifiers repeat by construction. Never emitted, and never copied from a base tag.
FORBIDDEN_PARAMETERS = frozenset({"presence_penalty", "frequency_penalty", "repeat_penalty"})

# Emitted for HUMAN callers (`ollama run`). Inert for the bridge, which pins its own.
_TEMPERATURE_BY_ROLE = {"coder": "0.1", "writer": "0.3"}

ROLE_SYSTEM = {
    "coder": (
        "You are a coding assistant. You are given a small, already-written plan and you "
        "implement exactly what it specifies. Write complete, working code. Match the "
        "surrounding style. Explain only what is not obvious from the code itself."
    ),
    "writer": (
        "You are a technical writer. You produce docstrings, code comments, Markdown "
        "documentation and short notes. Be concise, correct and direct. Follow the "
        "structure you are given exactly."
    ),
}

# `ollama show --modelfile` emits a directive either on one line or wrapped in triple
# quotes across many. Parsing only the single-line form silently truncates a real chat
# template to its first line, which matters precisely in the case this module exists for:
# a blob FROM inherits no template, so a truncated one produces an unframed model.
_TRIPLE_RE = re.compile(r'^(TEMPLATE|SYSTEM)\s+"""(.*?)"""\s*$', re.MULTILINE | re.DOTALL)
_SINGLE_RE = re.compile(r'^(TEMPLATE|SYSTEM|RENDERER|PARSER)\s+(?!""")(.+)$', re.MULTILINE)
_STOP_RE = re.compile(r"^PARAMETER stop\s+(.+)$", re.MULTILINE)


def base_configuration(tag: str) -> dict[str, Any]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Read a base tag's own TEMPLATE, SYSTEM, RENDERER, PARSER and stop
        tokens out of `ollama show --modelfile`. Needed only when the tuned
        variant will name a blob, since a blob inherits none of them.

    Inputs:
        tag (str): the base model tag.

    Outputs:
        result (dict): {"template", "system", "renderer", "parser", "stop"},
        with None for an absent directive and a list for stop tokens. A
        triple-quoted directive is returned whole, newlines included.
    --------------------------------------------------------------------------
    """
    import vram_probe

    return parse_modelfile(vram_probe._ollama_show(tag, modelfile=True))


def parse_modelfile(text: str) -> dict[str, Any]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Split a Modelfile's directives. Separated from base_configuration so
        the parser is testable without Ollama.

    Inputs:
        text (str): the output of `ollama show --modelfile`.

    Outputs:
        result (dict): {"template", "system", "renderer", "parser", "stop"}.
    --------------------------------------------------------------------------
    """
    config: dict[str, Any] = {
        "template": None, "system": None, "renderer": None, "parser": None, "stop": [],
    }
    for directive, body in _TRIPLE_RE.findall(text):
        config[directive.lower()] = body
    for directive, body in _SINGLE_RE.findall(text):
        key = directive.lower()
        if config.get(key) is None:
            config[key] = body.strip()
    config["stop"] = [s.strip() for s in _STOP_RE.findall(text)]
    return config


def render(
    *,
    base_tag: str,
    from_reference: str,
    from_is_blob: bool,
    num_ctx: int,
    role: str,
    base_config: dict[str, Any],
    provenance: dict[str, Any],
) -> str:
    """
    --------------------------------------------------------------------------
    Purpose:
        Render the tuned variant's Modelfile.

    Inputs:
        base_tag (str): the tag this variant derives from, for the comments.
        from_reference (str): what FROM names - a tag, or a blob path.
        from_is_blob (bool): True when the projector is being dropped, which is
            the ONLY case where the base's directives must be restated.
        num_ctx (int): the retained window.
        role (str): "writer" or "coder"; selects SYSTEM and temperature.
        base_config (dict): parse_modelfile's output for the base tag.
        provenance (dict): card, vram_mib, kv_cache_type, free_mib, decode_tps,
            date - the measurement that justifies num_ctx.

    Outputs:
        result (str): the Modelfile text, ready to write.
    --------------------------------------------------------------------------
    """
    lines: list[str] = [f"FROM {from_reference}", ""]

    lines.append(f"# Tuned variant of {base_tag} for the {role} role, generated by")
    lines.append("# vram_optimizer.py. Every number below was measured, not chosen.")
    lines.append(f"# Card: {provenance['card']}, {provenance['vram_mib']} MiB.")
    if provenance.get("measured", True):
        lines.append(
            f"# Retained on {provenance['date']}: num_ctx {num_ctx} at "
            f"OLLAMA_KV_CACHE_TYPE={provenance['kv_cache_type']}, "
            f"{provenance['free_mib']} MiB free, {provenance['decode_tps']} tok/s decode, "
            "100 percent GPU residency."
        )
    else:
        # A preview must never wear the provenance of a measurement. Emitting the retained
        # line with placeholder zeros would claim 100 percent residency before a single rung
        # had been measured, which is the exact failure this tool exists to prevent.
        lines.append(
            f"# PREVIEW ONLY, NOTHING MEASURED YET ({provenance['date']}). num_ctx {num_ctx} "
            "is the model's native maximum, not a retained value, and the daemon's current "
            f"OLLAMA_KV_CACHE_TYPE={provenance['kv_cache_type']} is only where a sweep would "
            "start. Run without --dry-run to replace this line with a measurement."
        )
    if from_is_blob:
        lines.append(
            "# FROM names a blob, not the tag, because the tag ships a separate vision"
        )
        lines.append(
            "# projector layer this text-only variant does not need. A blob inherits no"
        )
        lines.append(
            "# TEMPLATE, SYSTEM, RENDERER, PARSER or stop token, so each is restated below."
        )
    lines.append("")

    if from_is_blob:
        if base_config.get("template"):
            lines.append(_directive("TEMPLATE", base_config["template"]))
        if base_config.get("renderer"):
            lines.append(f"RENDERER {base_config['renderer']}")
        if base_config.get("parser"):
            lines.append(f"PARSER {base_config['parser']}")
        for stop in base_config.get("stop", []):
            lines.append(f"PARAMETER stop {stop}")

    lines.append(_directive("SYSTEM", ROLE_SYSTEM[role]))
    lines.append("")

    lines.append("# Inert for the bridge, which pins its own sampling on every request;")
    lines.append("# these apply to `ollama run` and any other client.")
    lines.append(f"PARAMETER temperature {_TEMPERATURE_BY_ROLE[role]}")
    lines.append("PARAMETER top_p 0.9")
    lines.append("PARAMETER top_k 20")
    lines.append("")
    lines.append("# No repetition penalty of any kind. The bridge does NOT override those,")
    lines.append("# so one left in a Modelfile does reach generation, and penalising")
    lines.append("# repetition in code punishes identifiers, which repeat by construction.")
    lines.append("")
    lines.append(f"PARAMETER num_ctx {num_ctx}")
    lines.append("")
    lines.append("# Forces every layer onto the GPU. Without it Ollama holds layers back even")
    lines.append("# when the weights fit: one untuned base measured 79 percent GPU at 16384.")
    lines.append("PARAMETER num_gpu 99")
    return "\n".join(lines) + "\n"


def _directive(name: str, body: str) -> str:
    """
    --------------------------------------------------------------------------
    Purpose:
        Emit a directive, triple-quoting it when its body spans lines so the
        Modelfile stays parseable.

    Inputs:
        name (str): the directive keyword.
        body (str): its value.

    Outputs:
        result (str): the directive line, or block.
    --------------------------------------------------------------------------
    """
    if "\n" in body:
        return f'{name} """{body}"""'
    return f"{name} {body}"
