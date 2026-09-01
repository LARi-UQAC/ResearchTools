"""
github_reviewer.py — GitHub cross-reviewer (the "Copilot" leg) for the scopus-auditor pipeline.

Sends a draft improvement plan to the newest chat model GitHub exposes and returns structured
peer-review suggestions that Claude arbitrates before writing the final plan.

The provider chain and the run-time model resolution live in copilot_providers.py; read its
docstring for why GitHub Copilot and the retired GitHub Models are two different products with
two different tokens. Neither the endpoint nor the model is hardcoded here: one dead host or
one retired model id must not take the leg down, which is exactly what happened twice.

Usage:
  python github_reviewer.py "<draft text>" [--topic "<topic>"] [--model auto]
  python github_reviewer.py --stdin [--topic "<topic>"] [--model auto]
  python github_reviewer.py --list-models

Output: JSON to stdout. Errors to stderr.
Requires: COPILOT_TOKEN (GitHub Copilot) or GITHUB_TOKEN (legacy GitHub Models).
"""

import argparse
import json
import sys

from copilot_providers import (PROVIDERS, endpoint_model, entry_id, fetch_catalog,
                               provider_token, resolve_latest_model)
from reviewer_schema import error_object, expand_schema

try:
    from openai import OpenAI
    _OPENAI_OK = True
except ImportError:
    OpenAI = None
    _OPENAI_OK = False


class ReviewerError(Exception):
    """Raised when the GitHub reviewer cannot return a result (missing dependency, missing
    token, API failure, or non-JSON response). Never prints and never calls sys.exit, so
    callers such as deliberate.py can mark the reviewer unavailable and keep going instead of
    aborting the host pipeline. `raw` carries the model's unparsable text when the failure was
    a parse failure, so the caller can surface it under `_raw`."""

    def __init__(self, message: str, raw: str = ""):
        super().__init__(message)
        self.raw = raw


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
    """True when openai is importable and at least one provider in the chain has a token.
    Never raises or exits."""
    return _OPENAI_OK and any(provider_token(p) for p in PROVIDERS)


def _require_token() -> str:
    """Kept for callers that only need to know a token exists; the per-provider token is read
    inside the call loop, since the chain spans two products with two different credentials."""
    for provider in PROVIDERS:
        token = provider_token(provider)
        if token:
            return token
    raise ReviewerError(
        "No GitHub reviewer token set. Set COPILOT_TOKEN for GitHub Copilot "
        "(api.githubcopilot.com refuses a personal access token), or GITHUB_TOKEN for the "
        "legacy GitHub Models hosts. "
        "Fix: [System.Environment]::SetEnvironmentVariable('COPILOT_TOKEN', '...', 'User')"
    )


def run_copilot(
    user_prompt: str,
    model: str = "auto",
    temperature: float = 0.3,
    max_tokens: int = 2048,
    system_prompt: str = _SYSTEM_PROMPT,
) -> dict:
    """
    --------------------------------------------------------------------------
    Purpose:
        Send a user prompt to the first GitHub provider that answers and return
        the parsed JSON object. Pure core shared by the standalone CLI and
        deliberate.py. Never prints and never calls sys.exit; raises ReviewerError
        on any failure so callers can mark the reviewer unavailable and continue.

    Inputs:
        user_prompt (str): complete user message (the caller does all formatting).
        model (str): model id, or 'auto' to resolve the newest catalog entry.
        temperature (float): sampling temperature.
        max_tokens (int): hard cap on the response (kept symmetric with the
            Gemini reviewer so both panelists stay bounded). max_tokens precedes
            system_prompt so deliberate.py's positional call threads the cap here.
        system_prompt (str): system framing; defaults to the peer-review prompt.

    Outputs:
        result (dict): parsed JSON response following the canonical reviewer schema.
    --------------------------------------------------------------------------
    """
    if not _OPENAI_OK:
        raise ReviewerError("openai not installed. Run: pip install openai")
    _require_token()
    if model in ("", "auto", None):
        model = resolve_latest_model()[0]

    last_error = "no provider had a token"
    for provider in PROVIDERS:
        token = provider_token(provider)
        if not token:
            continue
        client = OpenAI(base_url=provider["base"], api_key=token,
                        default_headers=provider.get("headers") or None)
        try:
            response = client.chat.completions.create(
                model=endpoint_model(model, provider["qualified"]),
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                response_format={"type": "json_object"},
                temperature=temperature,
                max_tokens=max_tokens,
            )
        except Exception as exc:
            # Fail over on an HTTP status (a retired or moved host answers 404/410) as well as
            # on a network exception. Only the last error is kept, for the report.
            last_error = f"{provider['name']}: {exc}"
            continue

        raw = (response.choices[0].message.content or "").strip()
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ReviewerError(
                f"GitHub Models returned non-JSON response: {raw[:200]}", raw=raw) from exc
        # Expand unconditionally: idempotent on canonical input, and it rescues a response
        # that came back in the panel's coded keys.
        return expand_schema(parsed)

    raise ReviewerError(f"GitHub reviewer failed on every provider. Last error: {last_error}")


def review(draft: str, topic: str, model: str) -> None:
    """Standalone CLI behavior: format the default review prompt, call the model, print JSON."""
    user_message = _USER_PROMPT.format(topic=topic or "not specified", draft=draft)
    result = run_copilot(user_message, model)
    print(json.dumps(result, ensure_ascii=False, indent=2))


def _print_catalogs(publisher: str) -> None:
    """--list-models: show every provider's catalog and the id that wins, so a stale model can
    be seen rather than guessed."""
    for provider in PROVIDERS:
        token = provider_token(provider)
        if not token:
            print(f"{provider['name']}: no token ({' or '.join(provider['token_env'])} unset)")
            continue
        entries = fetch_catalog(provider, token)
        ids = sorted(entry_id(e) for e in entries if isinstance(e, dict) and entry_id(e))
        print(f"{provider['name']} ({provider['catalog']}): {len(ids)} entries")
        for model_id in ids:
            print(f"  {model_id}")
    model, source = resolve_latest_model(publisher)
    print(f"resolved: {model}" + (f"  (from {source})" if source
                                  else "  (FALLBACK - no catalog answered)"))


def main() -> None:
    parser = argparse.ArgumentParser(description="GitHub peer-reviewer for scopus-auditor")
    parser.add_argument("draft", nargs="?", default=None, help="Draft plan text")
    parser.add_argument("--stdin", action="store_true", help="Read draft from stdin")
    parser.add_argument("--topic", default="", help="Research topic for context")
    parser.add_argument("--model", default="auto",
                        help="Model ID, or 'auto' (default) to resolve the newest catalog "
                             "entry at run time")
    parser.add_argument("--publisher", default="openai",
                        help="Preferred publisher when resolving 'auto' (default: openai)")
    parser.add_argument("--list-models", action="store_true",
                        help="Print every provider catalog and the resolved winner, then exit")
    args = parser.parse_args()

    if args.list_models:
        _print_catalogs(args.publisher)
        return

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
