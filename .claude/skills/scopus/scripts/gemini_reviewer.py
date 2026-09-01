"""
gemini_reviewer.py — Gemini AI cross-reviewer for the scopus-auditor pipeline.

Sends a draft improvement plan to Gemini (latest PRO by default, resolved via
ListModels) and returns structured
peer-review suggestions that Claude arbitrates before writing the final plan.

Usage:
  python gemini_reviewer.py "<draft text>" [--topic "<topic>"] [--model auto]
  python gemini_reviewer.py --stdin [--topic "<topic>"] [--model auto]

Output: JSON to stdout. Errors to stderr.
Requires: GEMINI_API_KEY env var.
"""

import argparse
import json
import os
import re
import sys

from reviewer_schema import error_object, expand_schema

try:
    from google import genai
    from google.genai import types
    _GENAI_OK = True
except ImportError:
    genai = None
    types = None
    _GENAI_OK = False


class ReviewerError(Exception):
    """Raised when the Gemini reviewer cannot return a result (missing dependency, missing
    GEMINI_API_KEY, API failure, or non-JSON response). Never prints and never calls sys.exit,
    so callers such as deliberate.py can mark the reviewer unavailable and keep going instead
    of aborting the host pipeline. `raw` carries the model's unparsable text when the failure
    was a parse failure, so the caller can surface it under `_raw` rather than lose the
    critique silently."""

    def __init__(self, message: str, raw: str = ""):
        super().__init__(message)
        self.raw = raw

_REVIEW_PROMPT = """\
You are a senior academic peer reviewer with expertise in IEEE and Elsevier journals.
You have been given a draft improvement plan for a literature review.
Your task: critique this plan rigorously. Identify weak suggestions, missed issues,
structural problems, and gaps in coverage. Do NOT invent specific paper references.
If a reference would strengthen a point, flag the need without naming a paper.

Respond ONLY with valid JSON matching this exact schema:
{{
  "overall_assessment": "<2-3 sentence global critique of the plan quality>",
  "suggestions": [
    {{
      "target_section": "<section id like A1, B2, C, E, or general>",
      "type": "<text_improvement | reference_issue | coverage_gap | style | structure>",
      "suggestion": "<specific actionable text>",
      "confidence": "<high | medium | low>",
      "requires_scopus_validation": <true | false>
    }}
  ]
}}

Topic context: {topic}

Draft improvement plan:
---
{draft}
---
"""


def gemini_available() -> bool:
    """True when google-genai is importable and GEMINI_API_KEY is set. Never raises or exits."""
    return _GENAI_OK and bool(os.environ.get("GEMINI_API_KEY", "").strip())


# Variant suffixes that are not text-reviewer models even when the name says "pro".
_NON_TEXT_MARKERS = ("image", "tts", "live", "audio", "embedding", "computer-use",
                     "customtools", "translate", "omni")

_RESOLVED_MODEL: str | None = None  # per-process cache; ListModels is one API call


def resolve_gemini_model(preference: str = "pro") -> str:
    """
    --------------------------------------------------------------------------
    Purpose:
        Pick the most recent usable Gemini model of the requested family by
        querying ListModels, so a retired hardcoded default (the fate of
        gemini-2.0-flash) can never break the pipeline again. Among text
        generation models named gemini-<version>-<family>*, the highest version
        wins; at equal version a stable name beats a -preview one. Falls back
        to 'gemini-flash-latest' when listing fails, and caches the result for
        the process lifetime.

    Inputs:
        preference (str): model family, 'pro' (default) or 'flash'.

    Outputs:
        model (str): a concrete model id usable with generate_content.
    --------------------------------------------------------------------------
    """
    global _RESOLVED_MODEL
    if _RESOLVED_MODEL:
        return _RESOLVED_MODEL
    fallback = "gemini-flash-latest"
    if not _GENAI_OK:
        return fallback
    try:
        client = genai.Client(api_key=_require_api_key())
        best: tuple[float, int, str] | None = None
        for model in client.models.list():
            name = (getattr(model, "name", "") or "").split("/")[-1]
            match = re.match(
                rf"^gemini-(\d+(?:\.\d+)?)-{preference}(?:$|-)", name)
            if not match:
                continue
            if any(marker in name for marker in _NON_TEXT_MARKERS):
                continue
            version = float(match.group(1))
            stable = 0 if name.endswith("-preview") or "-preview-" in name else 1
            candidate = (version, stable, name)
            if best is None or candidate > best:
                best = candidate
        _RESOLVED_MODEL = best[2] if best else fallback
    except Exception:  # listing failure: degrade to the alias, never crash
        _RESOLVED_MODEL = fallback
    return _RESOLVED_MODEL


def _require_api_key() -> str:
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        raise ReviewerError(
            "GEMINI_API_KEY is not set. "
            "Fix: [System.Environment]::SetEnvironmentVariable('GEMINI_API_KEY', 'key', 'User')"
        )
    return key


def count_gemini_tokens(prompt: str, model: str = "auto") -> int:
    """
    --------------------------------------------------------------------------
    Purpose:
        Best-effort prompt token count via Gemini's count_tokens endpoint, which
        does NOT consume generation quota. The deliberation panel uses it to keep
        each call inside a free-tier token budget. Never raises and never exits;
        callers fall back to a character heuristic when this returns -1.

    Inputs:
        prompt (str): the text whose tokens to count.
        model (str): Gemini model id (the tokenizer is model-specific).

    Outputs:
        total (int): token count, or -1 if unavailable (missing dependency or
        key, or any API failure).
    --------------------------------------------------------------------------
    """
    if not _GENAI_OK:
        return -1
    try:
        if model in ("", "auto", None):
            model = resolve_gemini_model()
        client = genai.Client(api_key=_require_api_key())
        result = client.models.count_tokens(model=model, contents=prompt)
        return int(getattr(result, "total_tokens", -1) or -1)
    except Exception:  # missing key, network, or API change — degrade, never crash
        return -1


def _salvage_json(raw: str) -> dict:
    """
    Parse possibly-truncated JSON. A free-tier max_output_tokens cap can cut the
    response mid-array; rather than lose a near-complete answer, trim to the last
    complete object and re-balance the brackets once. Raises ReviewerError only
    when even the repair fails.
    """
    raw = raw.strip()
    # Some models wrap the JSON in a markdown fence despite the JSON mime type.
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[-1]
        if raw.rstrip().endswith("```"):
            raw = raw.rstrip()[:-3]
        raw = raw.strip()
    # Trim any preamble before the first JSON opener.
    first = min((i for i in (raw.find("{"), raw.find("[")) if i >= 0), default=0)
    raw = raw[first:]

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    last = raw.rfind("}")
    if last != -1:
        repaired = raw[: last + 1]
        repaired += "]" * max(0, repaired.count("[") - repaired.count("]"))
        repaired += "}" * max(0, repaired.count("{") - repaired.count("}"))
        try:
            return json.loads(repaired)
        except json.JSONDecodeError:
            pass

    raise ReviewerError(f"Gemini returned non-JSON response: {raw[:200]}", raw=raw)


def run_gemini(prompt: str, model: str = "auto", temperature: float = 0.3,
               max_output_tokens: int = 8192, *, expand: bool = True) -> dict:
    """
    --------------------------------------------------------------------------
    Purpose:
        Send a fully-formed prompt to Gemini and return the parsed JSON object.
        Pure core shared by the standalone CLI and deliberate.py. Never prints and
        never calls sys.exit; raises ReviewerError on any failure so callers can
        mark the reviewer unavailable and continue. With model='auto' the most
        recent PRO model is resolved via ListModels, and a NOT_FOUND on an
        explicit model id triggers one retry on the resolved model, so a retired
        id degrades instead of failing the panel.

    Inputs:
        prompt (str): complete prompt text (the caller does all formatting).
        model (str): Gemini model id, or 'auto' for the latest PRO.
        temperature (float): sampling temperature.
        max_output_tokens (int): response cap; sized so a structured review
            finishes without truncation (truncated JSON was the historical
            'Gemini returned non-JSON response' failure).
        expand (bool): map the reviewer schema's coded keys back to canonical
            form. On for the peer-review callers, which is every caller that
            asked for that schema. Off for a caller whose own schema uses free
            dict keys, such as gemini_table.py: its `cells` keys are the table's
            concept names, so a column named 'c' or 'type' would be silently
            renamed by the reviewer key map.

    Outputs:
        result (dict): parsed JSON response, canonical when expand is on.
    --------------------------------------------------------------------------
    """
    if not _GENAI_OK:
        raise ReviewerError("google-genai not installed. Run: pip install google-genai")
    api_key = _require_api_key()
    client = genai.Client(api_key=api_key)
    if model in ("", "auto", None):
        model = resolve_gemini_model()

    def _call(model_id: str):
        return client.models.generate_content(
            model=model_id,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=temperature,
                max_output_tokens=max_output_tokens,
            ),
        )

    try:
        response = _call(model)
    except Exception as exc:
        # Retired/typoed explicit id: retry once on the freshest PRO before giving up.
        resolved = resolve_gemini_model()
        if "NOT_FOUND" in str(exc) and resolved != model:
            try:
                response = _call(resolved)
            except Exception as exc2:
                raise ReviewerError(f"Gemini API call failed: {exc2}") from exc2
        else:
            raise ReviewerError(f"Gemini API call failed: {exc}") from exc

    raw = (response.text or "").strip()
    parsed = _salvage_json(raw)
    # Every reviewer response is expanded, not only the ones the panel asked in coded keys: a
    # model answers in whichever form it likes, and expand_schema is idempotent on canonical
    # input, so running it by default costs nothing and closes the gap a caller could forget.
    return expand_schema(parsed) if expand else parsed


def review(draft: str, topic: str, model: str) -> None:
    """Standalone CLI behavior: format the default review prompt, call Gemini, print JSON."""
    prompt = _REVIEW_PROMPT.format(topic=topic or "not specified", draft=draft)
    result = run_gemini(prompt, model)
    print(json.dumps(result, ensure_ascii=False, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description="Gemini peer-reviewer for scopus-auditor")
    parser.add_argument("draft", nargs="?", default=None, help="Draft plan text")
    parser.add_argument("--stdin", action="store_true", help="Read draft from stdin")
    parser.add_argument("--topic", default="", help="Research topic for context")
    parser.add_argument("--model", default="auto", help="Gemini model ID, or 'auto' for the latest PRO")
    args = parser.parse_args()

    if args.stdin:
        draft = sys.stdin.read().strip()
    elif args.draft:
        draft = args.draft.strip()
    else:
        parser.error("Provide draft text as argument or use --stdin")

    if not draft:
        print("ERROR: Draft text is empty.", file=sys.stderr)
        sys.exit(1)

    try:
        review(draft, args.topic, args.model)
    except ReviewerError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        # A parse failure still carries the model's text; emit it as a schema-shaped error
        # object so a caller capturing stdout keeps the critique instead of losing it.
        if getattr(exc, "raw", ""):
            print(json.dumps(error_object(str(exc), exc.raw), ensure_ascii=False, indent=2))
        sys.exit(1)


if __name__ == "__main__":
    main()
