"""
gemini_reviewer.py — Gemini AI cross-reviewer for the scopus-auditor pipeline.

Sends a draft improvement plan to Gemini 2.0 Flash and returns structured
peer-review suggestions that Claude arbitrates before writing the final plan.

Usage:
  python gemini_reviewer.py "<draft text>" [--topic "<topic>"] [--model gemini-2.0-flash]
  python gemini_reviewer.py --stdin [--topic "<topic>"] [--model gemini-2.0-flash]

Output: JSON to stdout. Errors to stderr.
Requires: GEMINI_API_KEY env var.
"""

import argparse
import json
import os
import sys

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
    of aborting the host pipeline."""

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


def _require_api_key() -> str:
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        raise ReviewerError(
            "GEMINI_API_KEY is not set. "
            "Fix: [System.Environment]::SetEnvironmentVariable('GEMINI_API_KEY', 'key', 'User')"
        )
    return key


def count_gemini_tokens(prompt: str, model: str = "gemini-2.0-flash") -> int:
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

    raise ReviewerError(f"Gemini returned non-JSON response: {raw[:200]}")


def run_gemini(prompt: str, model: str = "gemini-2.0-flash", temperature: float = 0.3,
               max_output_tokens: int = 2048) -> dict:
    """
    --------------------------------------------------------------------------
    Purpose:
        Send a fully-formed prompt to Gemini and return the parsed JSON object.
        Pure core shared by the standalone CLI and deliberate.py. Never prints and
        never calls sys.exit; raises ReviewerError on any failure so callers can
        mark the reviewer unavailable and continue.

    Inputs:
        prompt (str): complete prompt text (the caller does all formatting).
        model (str): Gemini model id.
        temperature (float): sampling temperature.
        max_output_tokens (int): hard cap on the response so a free-tier call
            finishes instead of overrunning the budget; pair with a terse,
            bounded prompt so the JSON completes within it.

    Outputs:
        result (dict): parsed JSON response following the reviewer schema.
    --------------------------------------------------------------------------
    """
    if not _GENAI_OK:
        raise ReviewerError("google-genai not installed. Run: pip install google-genai")
    api_key = _require_api_key()
    client = genai.Client(api_key=api_key)

    try:
        response = client.models.generate_content(
            model=model,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=temperature,
                max_output_tokens=max_output_tokens,
            ),
        )
    except Exception as exc:
        raise ReviewerError(f"Gemini API call failed: {exc}") from exc

    raw = (response.text or "").strip()
    return _salvage_json(raw)


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
    parser.add_argument("--model", default="gemini-2.0-flash", help="Gemini model ID")
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
        sys.exit(1)


if __name__ == "__main__":
    main()
