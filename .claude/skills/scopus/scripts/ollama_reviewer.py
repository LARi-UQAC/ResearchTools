"""
ollama_reviewer.py - local Ollama reviewer core for the deliberation panel.

Third reviewer core, beside gemini_reviewer.py and github_reviewer.py, so deliberate.py can use a
local model as the fallback voice when GitHub Copilot does not answer. The model is never named
here: model_resolver.py (reached through ollama_bridge.resolve_model) names the tag at run time,
exactly as it does for local-writer and local-coder, and refuses rather than substituting a
weaker one (R2, R8).

A deliberation prompt is a focused question or a short draft, never a whole chapter. The prompt
plus the reply must fit the configured context window (num_ctx in ollama-reviewer.json): a prompt that does not fit is refused
with the numbers, never truncated, because Ollama truncates in silence and reports success.

Never prints and never calls sys.exit: every failure raises ReviewerError, so the panel marks
the reviewer unavailable and carries on, the same contract as the other two cores.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from gemini_reviewer import ReviewerError, _salvage_json
from reviewer_schema import expand_schema

_HERE = Path(__file__).resolve().parent
CONFIG_PATH = _HERE / "ollama-reviewer.json"
_BRIDGE_DIR = _HERE.parents[1] / "loop-engineer" / "scripts"

_CONFIG_KEYS = ("role", "num_ctx", "request_timeout_s", "reply_tokens", "seed")


def load_config(path: Path | None = None) -> dict:
    """
    --------------------------------------------------------------------------
    Purpose:
        Read ollama-reviewer.json. Every value carries its provenance (R4).

    Inputs:
        path (Path | None): the file, defaulting to the one beside this module.

    Outputs:
        dict: key -> value (provenance dropped).

    Raises:
        ReviewerError: the file is missing, unreadable, or lacks a key; the
            message names the key and the file (R3).
    --------------------------------------------------------------------------
    """
    target = path or CONFIG_PATH
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReviewerError(f"cannot read {target}: {exc}") from exc
    missing = [key for key in _CONFIG_KEYS if key not in raw or "value" not in raw[key]]
    if missing:
        raise ReviewerError(f"{target} lacks the key(s) {missing}")
    return {key: raw[key]["value"] for key in _CONFIG_KEYS}


def _bridge():
    """Import ollama_bridge lazily from the loop-engineer skill (single source of the Ollama
    transport, the budget probe and the reasoning stripper; a copy would drift, R18)."""
    if str(_BRIDGE_DIR) not in sys.path:
        sys.path.insert(0, str(_BRIDGE_DIR))
    try:
        import ollama_bridge  # type: ignore
    except ImportError as exc:
        raise ReviewerError(f"ollama_bridge is not importable from {_BRIDGE_DIR}: {exc}") from exc
    return ollama_bridge


def resolve_ollama_model(role: str | None = None) -> str:
    """
    --------------------------------------------------------------------------
    Purpose:
        Ask the model resolver which local tag serves the reviewer role at
        this moment. Nothing is cached: the answer follows whatever model is
        adopted when the panel runs.

    Inputs:
        role (str | None): resolver role; None reads it from the config.

    Outputs:
        str: the Ollama tag.

    Raises:
        ReviewerError: the resolver or the daemon refuses, or names no tag.
    --------------------------------------------------------------------------
    """
    bridge = _bridge()
    try:
        return bridge.resolve_model(role or load_config()["role"])
    except bridge.BridgeError as exc:
        raise ReviewerError(str(exc)) from exc


def ollama_available() -> bool:
    """True when the resolver names a tag for the reviewer role. Never raises."""
    try:
        return bool(resolve_ollama_model())
    except Exception:
        return False


def input_budget(model: str = "auto") -> int:
    """
    --------------------------------------------------------------------------
    Purpose:
        How many prompt tokens the reviewer can take: the tag's measured
        window minus the reply budget. deliberate.py caps its shared prompt
        with this when the local model is a leg.

    Inputs:
        model (str): a tag, or "auto" for the resolver's.

    Outputs:
        int: tokens available to the prompt.

    Raises:
        ReviewerError: the configuration is unreadable.
    --------------------------------------------------------------------------
    """
    config = load_config()
    return int(config["num_ctx"]) - int(config["reply_tokens"])


def run_ollama(prompt: str, model: str = "auto", temperature: float = 0.3,
               max_output_tokens: int = 4096, *, expand: bool = True) -> dict:
    """
    --------------------------------------------------------------------------
    Purpose:
        Send a fully formed prompt to the local model and return the parsed
        JSON object, in the same shape run_gemini and run_copilot return.

    Details:
        The prompt tokens are counted exactly by the daemon (the bridge's
        probe). prompt + reply must fit the configured window or the call is
        refused. Reasoning is switched off by the bridge (think=false), the
        reply is constrained to valid JSON, and a reply cut by the reply cap
        is salvaged to its last complete suggestion.

    Inputs:
        prompt (str): complete prompt text.
        model (str): a tag, or "auto" for the resolver's.
        temperature (float): sampling temperature.
        max_output_tokens (int): reply cap; the configured reply_tokens caps it.
        expand (bool): map coded keys back to canonical form.

    Outputs:
        dict: the parsed review.

    Raises:
        ReviewerError: no model, prompt too large, daemon refusal or
            timeout, empty or unparsable reply (carrying `raw` when there is one).
    --------------------------------------------------------------------------
    """
    bridge = _bridge()
    config = load_config()
    tag = resolve_ollama_model() if model in ("", "auto", None) else model
    num_ctx = int(config["num_ctx"])
    reply =min(int(max_output_tokens), int(config["reply_tokens"]))
    try:
        prompt_tokens = bridge.probe_prompt_tokens(prompt, tag, num_ctx)
    except bridge.BridgeError as exc:
        raise ReviewerError(str(exc)) from exc
    if prompt_tokens + reply > num_ctx:
        raise ReviewerError(
            f"the prompt is {prompt_tokens} tokens and the reply budget {reply}, over the {num_ctx}-token window of {tag}; "
            "ask a shorter question (refusing rather than letting Ollama truncate)")
    payload = bridge.build_payload(prompt, tag, int(config["seed"]), num_ctx, fmt="json")
    payload["options"]["num_predict"] = reply
    payload["options"]["temperature"] = temperature
    try:
        response = bridge._post_generate(payload, float(config["request_timeout_s"]))
    except bridge.BridgeError as exc:
        raise ReviewerError(str(exc)) from exc
    try:
        text = bridge.strip_reasoning(response.get("response", "")).strip()
    except bridge.ReasoningAnomalyError as exc:
        raise ReviewerError(f"reasoning markers could not be resolved: {exc}") from exc
    if not text:
        raise ReviewerError(f"empty reply from {tag} (done_reason={response.get('done_reason')!r})")
    try:
        parsed = _salvage_json(text)
    except ReviewerError as exc:
        raise ReviewerError(str(exc).replace("Gemini", "Ollama"), raw=getattr(exc, "raw", "") or text) from exc
    return expand_schema(parsed) if expand else parsed
