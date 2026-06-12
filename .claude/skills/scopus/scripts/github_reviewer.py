"""
github_reviewer.py — GitHub Copilot (GPT-4o via GitHub Models) cross-reviewer
for the scopus-auditor pipeline.

Sends a draft improvement plan to GPT-4o via the GitHub Models API and returns
structured peer-review suggestions that Claude arbitrates before writing the final plan.

Usage:
  python github_reviewer.py "<draft text>" [--topic "<topic>"] [--model gpt-4o]
  python github_reviewer.py --stdin [--topic "<topic>"] [--model gpt-4o]

Output: JSON to stdout. Errors to stderr.
Requires: GITHUB_TOKEN env var (GitHub personal access token with Education Pro).
"""

import argparse
import json
import os
import sys

try:
    from openai import OpenAI
    _OPENAI_OK = True
except ImportError:
    OpenAI = None
    _OPENAI_OK = False


class ReviewerError(Exception):
    """Raised when the Copilot reviewer cannot return a result (missing dependency, missing
    GITHUB_TOKEN, API failure, or non-JSON response). Never prints and never calls sys.exit,
    so callers such as deliberate.py can mark the reviewer unavailable and keep going instead
    of aborting the host pipeline."""

_GITHUB_MODELS_ENDPOINT = "https://models.inference.ai.azure.com"

_SYSTEM_PROMPT = (
    "You are a senior academic peer reviewer with expertise in IEEE and Elsevier journals. "
    "Critique the provided improvement plan rigorously. Identify weak suggestions, missed issues, "
    "structural problems, and coverage gaps. Do NOT invent specific paper references. "
    "If a reference would strengthen a point, flag the need without naming a paper. "
    "Respond ONLY with valid JSON — no prose, no markdown wrapping."
)

_USER_PROMPT = """\
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


def copilot_available() -> bool:
    """True when openai is importable and GITHUB_TOKEN is set. Never raises or exits."""
    return _OPENAI_OK and bool(os.environ.get("GITHUB_TOKEN", "").strip())


def _require_token() -> str:
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if not token:
        raise ReviewerError(
            "GITHUB_TOKEN is not set. "
            "Fix: [System.Environment]::SetEnvironmentVariable('GITHUB_TOKEN', 'ghp_...', 'User')"
        )
    return token


def run_copilot(
    user_prompt: str,
    model: str = "gpt-4o",
    temperature: float = 0.3,
    max_tokens: int = 2048,
    system_prompt: str = _SYSTEM_PROMPT,
) -> dict:
    """
    --------------------------------------------------------------------------
    Purpose:
        Send a user prompt to GPT-4o via GitHub Models and return the parsed JSON
        object. Pure core shared by the standalone CLI and deliberate.py. Never
        prints and never calls sys.exit; raises ReviewerError on any failure so
        callers can mark the reviewer unavailable and continue.

    Inputs:
        user_prompt (str): complete user message (the caller does all formatting).
        model (str): GitHub Models model id.
        temperature (float): sampling temperature.
        max_tokens (int): hard cap on the response (kept symmetric with the
            Gemini reviewer so both panelists stay bounded). max_tokens precedes
            system_prompt so deliberate.py's positional call threads the cap here.
        system_prompt (str): system framing; defaults to the peer-review prompt.

    Outputs:
        result (dict): parsed JSON response following the reviewer schema.
    --------------------------------------------------------------------------
    """
    if not _OPENAI_OK:
        raise ReviewerError("openai not installed. Run: pip install openai")
    token = _require_token()
    client = OpenAI(base_url=_GITHUB_MODELS_ENDPOINT, api_key=token)

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            response_format={"type": "json_object"},
            temperature=temperature,
            max_tokens=max_tokens,
        )
    except Exception as exc:
        raise ReviewerError(f"GitHub Models API call failed: {exc}") from exc

    raw = (response.choices[0].message.content or "").strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ReviewerError(f"GitHub Models returned non-JSON response: {raw[:200]}") from exc


def review(draft: str, topic: str, model: str) -> None:
    """Standalone CLI behavior: format the default review prompt, call GPT-4o, print JSON."""
    user_message = _USER_PROMPT.format(topic=topic or "not specified", draft=draft)
    result = run_copilot(user_message, model)
    print(json.dumps(result, ensure_ascii=False, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description="GitHub Copilot peer-reviewer for scopus-auditor")
    parser.add_argument("draft", nargs="?", default=None, help="Draft plan text")
    parser.add_argument("--stdin", action="store_true", help="Read draft from stdin")
    parser.add_argument("--topic", default="", help="Research topic for context")
    parser.add_argument("--model", default="gpt-4o", help="GitHub Models model ID")
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
