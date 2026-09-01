"""
gemini_table.py — bounded Gemini task: enrich a comparison table's cells.

Stage helper for the academic agents' "build comparison table" step. Claude extracts the table axes
(concepts = columns, parameters = rows, per CLAUDE.md); this script asks Gemini ONLY to fill the
cell detail. Tiny input + bounded output, so it fits a Gemini free-tier budget where a whole-draft
critique would not. Gemini returns content as JSON; Claude assembles the LaTeX table (bold first
row/column, 10% grey header, two-sentence citation) — keeping Gemini's output small and dodging
LaTeX-escaping issues.

See ../references/table-enrichment.md for the input/output contract and the graceful-skip rule.

Usage:
  python gemini_table.py --axes-file axes.json
  echo '<axes json>' | python gemini_table.py --stdin

Input JSON:
  { "concepts": ["col1", ...], "parameters": ["row1", ...],
    "context": "<1-2 lines>", "refs": [{"key": "smith2023", "title": "..."}] }

Output: JSON to stdout. Errors to stderr. Requires GEMINI_API_KEY (skips gracefully without it).
"""

import argparse
import json
import sys

# Single-source the Gemini API core from the sibling reviewer module.
from gemini_reviewer import run_gemini, count_gemini_tokens, gemini_available

# Caveman terse directive (mirrors deliberate.py) — applies to cell text only, never to JSON keys.
_TERSE_DIRECTIVE = (
    "Write every cell caveman-terse: drop articles, filler, hedging. Fragments OK. "
    "Keep technical terms exact. <=12 words per cell."
)

_SCHEMA = """{
  "rows": [
    { "parameter": "<row label>", "cells": { "<concept>": "<short detail>" } }
  ],
  "notes": "<= 2 sentences on any gap or caveat>"
}"""


def _refs_block(refs: list) -> str:
    """Compact one-line-per-ref listing; empty when no refs are provided."""
    lines = []
    for ref in refs or []:
        if isinstance(ref, dict):
            key = (ref.get("key") or "").strip()
            title = (ref.get("title") or "").strip()
            lines.append(f"- {key}: {title}".rstrip())
    return "\n".join(lines)


def _build_prompt(axes: dict, terse: bool, refs_detail: bool, include_context: bool) -> str:
    """
    --------------------------------------------------------------------------
    Purpose:
        Build the compact table-enrichment prompt. refs_detail / include_context
        are dropped first when trimming under the token budget.

    Inputs:
        axes (dict): concepts, parameters, context, refs.
        terse (bool): inject the caveman directive.
        refs_detail (bool): include the per-ref title listing.
        include_context (bool): include the free-text context line.

    Outputs:
        prompt (str): the prompt text.
    --------------------------------------------------------------------------
    """
    concepts = axes.get("concepts") or []
    parameters = axes.get("parameters") or []
    terse_line = (_TERSE_DIRECTIVE + "\n") if terse else ""
    context = axes.get("context", "") if include_context else ""
    context_line = f"Context: {context}\n" if context else ""
    refs = _refs_block(axes.get("refs")) if refs_detail else ""
    refs_line = f"References (use ONLY these; do not invent papers):\n{refs}\n" if refs else ""

    return f"""Fill each (parameter x concept) cell of this comparison table. Concepts are the columns,
parameters are the rows. {('Use ONLY the listed references; ' if refs else '')}do NOT invent papers.
Respond ONLY with valid JSON.
{terse_line}{context_line}{refs_line}
Concepts (columns): {json.dumps(concepts, ensure_ascii=False)}
Parameters (rows): {json.dumps(parameters, ensure_ascii=False)}

JSON schema:
{_SCHEMA}
"""


def enrich(axes: dict, model: str, temperature: float, max_input_tokens: int) -> dict:
    """
    --------------------------------------------------------------------------
    Purpose:
        Ask Gemini to fill the comparison-table cells within a bounded output.
        max_output_tokens scales with table size; the input is trimmed (refs,
        then context) if it exceeds max_input_tokens.

    Inputs:
        axes (dict): concepts, parameters, context, refs.
        model (str): Gemini model id.
        temperature (float): sampling temperature.
        max_input_tokens (int): input budget ceiling.

    Outputs:
        result (dict): {"rows": [...], "cells": {...}, "notes": "..."}.
    --------------------------------------------------------------------------
    """
    rows = len(axes.get("parameters") or [])
    cols = len(axes.get("concepts") or [])
    max_output_tokens = max(1024, rows * cols * 24)

    prompt = _build_prompt(axes, terse=True, refs_detail=True, include_context=True)

    def over_budget(text: str) -> bool:
        n = count_gemini_tokens(text, model)
        n = n if n >= 0 else max(1, len(text) // 4)
        return n > max_input_tokens

    if over_budget(prompt):  # drop ref titles first
        prompt = _build_prompt(axes, terse=True, refs_detail=False, include_context=True)
    if over_budget(prompt):  # then drop free-text context
        prompt = _build_prompt(axes, terse=True, refs_detail=False, include_context=False)

    # expand=False: the reviewer key map must not touch this schema. The `cells` keys are the
    # table's own concept names, so a column named 'c', 'm' or 'type' would be renamed.
    return run_gemini(prompt, model, temperature, max_output_tokens, expand=False)


def _load_axes(args) -> dict:
    if args.stdin:
        raw = sys.stdin.read()
    elif args.axes_file:
        try:
            with open(args.axes_file, "r", encoding="utf-8") as fh:
                raw = fh.read()
        except OSError as exc:
            print(f"ERROR: cannot read --axes-file: {exc}", file=sys.stderr)
            sys.exit(1)
    else:
        print("ERROR: provide --axes-file or --stdin", file=sys.stderr)
        sys.exit(1)

    try:
        axes = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"ERROR: axes input is not valid JSON: {exc}", file=sys.stderr)
        sys.exit(1)
    if not isinstance(axes, dict) or not axes.get("concepts") or not axes.get("parameters"):
        print("ERROR: axes must be a JSON object with non-empty 'concepts' and 'parameters'.",
              file=sys.stderr)
        sys.exit(1)
    return axes


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="Gemini comparison-table cell enrichment")
    parser.add_argument("--axes-file", default=None, help="Path to the axes JSON")
    parser.add_argument("--stdin", action="store_true", help="Read axes JSON from stdin")
    parser.add_argument("--model", default="gemini-2.0-flash")
    parser.add_argument("--temperature", type=float, default=0.3)
    parser.add_argument("--max-input-tokens", type=int, default=4000)
    args = parser.parse_args()

    # Graceful skip: no Gemini -> the agent's Claude-authored table proceeds unchanged. Exit 0.
    if not gemini_available():
        print(json.dumps({"skipped": True, "reason": "Gemini unavailable"}, ensure_ascii=False))
        return

    axes = _load_axes(args)
    try:
        result = enrich(axes, args.model, args.temperature, args.max_input_tokens)
    except Exception as exc:  # ReviewerError or any failure -> skip, never block the table step
        print(json.dumps({"skipped": True, "reason": str(exc)}, ensure_ascii=False))
        return

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
