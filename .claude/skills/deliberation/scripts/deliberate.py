"""
deliberate.py — Deliberation panel (debate stage of the audit / research pipeline).

Runs a two-round debate between Gemini and GitHub Copilot over a near-final draft, then
merges their critiques into a single ranked, consensus-tagged suggestion list for Claude to
arbitrate. The script performs ONLY the Gemini and Copilot API calls; Consensus (MCP) and
Scopus.AI evidence are gathered by the calling agent and passed in via --evidence-file. The
script never calls Scopus, never scores, and never aborts the host pipeline.

See ../references/deliberation-protocol.md for the arbitration table, provenance markers, the
Scopus validation gate, and the deliberation-log format.

Output: a JSON envelope to stdout (or --out path). Diagnostics to stderr.
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path

# The two reviewer cores live in the sibling scopus skill; import them from there so the API
# clients stay single-sourced. parents[2] == .claude/skills, then scopus/scripts.
_SCOPUS_SCRIPTS = Path(__file__).resolve().parents[2] / "scopus" / "scripts"
if str(_SCOPUS_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCOPUS_SCRIPTS))

try:
    from gemini_reviewer import run_gemini, gemini_available, count_gemini_tokens
except Exception:  # pragma: no cover - defensive: missing file/dep must not crash the panel
    run_gemini = None

    def gemini_available() -> bool:
        return False

    def count_gemini_tokens(prompt: str, model: str = "gemini-2.0-flash") -> int:
        return -1

try:
    from github_reviewer import run_copilot, copilot_available
except Exception:  # pragma: no cover
    run_copilot = None

    def copilot_available() -> bool:
        return False


_CONF_RANK = {"high": 3, "medium": 2, "low": 1}

_SCHEMA_HINTS = {
    "auditor": "A1, B2, C, E, N, general",
    "researcher": "a theme name, G1 (gap), H1 (hypothesis), references, general",
    "reviewer-response": "R1-2, R2-3, general (reviewer comment IDs)",
    "generic": "a section id or general",
}

_SCHEMA = """{
  "overall_assessment": "<2-3 sentence global critique>",
  "suggestions": [
    {
      "target_section": "<SECTION>",
      "type": "<text_improvement | reference_issue | coverage_gap | style | structure>",
      "suggestion": "<specific actionable text>",
      "confidence": "<high | medium | low>",
      "requires_scopus_validation": true or false
    }
  ]
}"""

_R2_EXTRA = """Also add a top-level array describing your stance on the other reviewer:
  "responses_to_other": [
    { "target_section": "<id>", "stance": "agree | disagree | partial", "reason": "<short>" }
  ]"""

# --- Compression (RTK / Caveman analogues) ---------------------------------------------------
# Caveman is prompt-injection only (no text transformer), so we port its terse directive into the
# reviewer prompt. Applies to free-text VALUES only — never to JSON keys or structure.
_TERSE_DIRECTIVE = (
    "Write every free-text value caveman-terse: drop articles, filler, hedging, pleasantries. "
    "Fragments OK. Keep technical terms exact. <=2 sentences per suggestion."
)

# Coded schema: short keys + 1-2 char enum codes cut output tokens (keys repeat per suggestion).
# Claude expands back to canonical form via _expand_schema before _merge, so the protocol markers
# and the rest of the pipeline are untouched.
_SCHEMA_CODED = """{
  "a": "<2-3 sentence global critique>",
  "x": [
    { "s": "<SECTION>", "t": "<ti|ri|cg|sy|sc>", "m": "<actionable text>",
      "c": "<h|m|l>", "v": true or false }
  ]
}
Legend: a=overall_assessment x=suggestions s=target_section t=type m=suggestion c=confidence
v=requires_scopus_validation. type: ti=text_improvement ri=reference_issue cg=coverage_gap
sy=style sc=structure. confidence: h=high m=medium l=low."""

_R2_EXTRA_CODED = """Also add a top-level array "r" (responses_to_other):
  "r": [ { "s": "<id>", "st": "<a|d|p>", "rs": "<short>" } ]
Legend: r=responses_to_other st=stance(a=agree d=disagree p=partial) rs=reason."""

# coded-key -> canonical-key (applied to dict keys at any level; canonical keys pass through)
_KEY_FROM_CODE = {
    "a": "overall_assessment", "x": "suggestions", "s": "target_section", "t": "type",
    "m": "suggestion", "c": "confidence", "v": "requires_scopus_validation",
    "r": "responses_to_other", "st": "stance", "rs": "reason",
}
# coded-value -> canonical-value, applied only to the named fields after key expansion
_TYPE_FROM_CODE = {"ti": "text_improvement", "ri": "reference_issue", "cg": "coverage_gap",
                   "sy": "style", "sc": "structure"}
_CONF_FROM_CODE = {"h": "high", "m": "medium", "l": "low"}
_STANCE_FROM_CODE = {"a": "agree", "d": "disagree", "p": "partial"}


def _expand_schema(obj):
    """
    --------------------------------------------------------------------------
    Purpose:
        Map a coded-key model response back to the canonical reviewer schema so
        the merge/arbitration logic is unchanged. Idempotent and safe on already-
        canonical input (the standalone CLIs and the offline test fixtures emit
        full keys), so it can run unconditionally after every model call.

    Inputs:
        obj (dict | list | scalar): a parsed model response (coded or canonical).

    Outputs:
        expanded (same shape): canonical keys and enum values.
    --------------------------------------------------------------------------
    """
    if isinstance(obj, list):
        return [_expand_schema(i) for i in obj]
    if not isinstance(obj, dict):
        return obj
    out = {}
    for k, v in obj.items():
        out[_KEY_FROM_CODE.get(k, k)] = _expand_schema(v) if isinstance(v, (dict, list)) else v
    if isinstance(out.get("type"), str):
        out["type"] = _TYPE_FROM_CODE.get(out["type"], out["type"])
    if isinstance(out.get("confidence"), str):
        out["confidence"] = _CONF_FROM_CODE.get(out["confidence"], out["confidence"])
    if isinstance(out.get("stance"), str):
        out["stance"] = _STANCE_FROM_CODE.get(out["stance"], out["stance"])
    return out


# --- Input compression: format-aware strip, structural digest, evidence trim -----------------


def _strip_source(draft: str) -> str:
    """RTK-analogue: drop format noise (LaTeX preamble/comments, markdown code fences, raw HTML)
    while keeping prose and claim lines. Returns the original draft if stripping empties it."""
    if not draft:
        return draft or ""
    text = draft
    if "\\begin{document}" in text:
        text = text.split("\\begin{document}", 1)[1]
    if "\\end{document}" in text:
        text = text.split("\\end{document}", 1)[0]
    text = "\n".join(re.sub(r"(?<!\\)%.*$", "", line) for line in text.splitlines())  # LaTeX comments
    text = re.sub(r"```.*?```", "", text, flags=re.DOTALL)                            # md code fences
    text = re.sub(r"<[^>]+>", "", text)                                               # raw HTML
    text = re.sub(r"\n\s*\n\s*\n+", "\n\n", text)                                     # collapse blanks
    return text.strip() or draft


_SIGNAL_RE = re.compile(r"^([A-Z]\d|#|\[|-|\*|\\section|\\subsection|\\item|issue)", re.IGNORECASE)


def _digest_draft(draft: str) -> str:
    """Last-resort over-budget reduction: keep only signal lines (headings, ids, list items,
    issue/suggestion lines, label lines). Returns the original draft if nothing matches."""
    if not draft:
        return draft or ""
    keep = [
        s for s in (ln.strip() for ln in draft.splitlines())
        if s and (_SIGNAL_RE.match(s) or "suggestion" in s.lower() or s.endswith(":"))
    ]
    digest = "\n".join(keep)
    return digest if digest.strip() else draft


def _trim_evidence(evidence: str, max_items: int) -> str:
    """Cap the evidence blob to the top-K items and reduce each to title + first claim line,
    dropping abstracts/DOIs/URLs (the models are told not to cite specific papers anyway)."""
    if not evidence or not evidence.strip():
        return evidence or ""
    blocks = [b.strip() for b in re.split(r"\n\s*\n", evidence.strip()) if b.strip()]
    if len(blocks) <= 1:
        blocks = [ln.strip() for ln in evidence.strip().splitlines() if ln.strip()]
    kept = []
    for block in blocks[: max(1, max_items)]:
        lines = [ln for ln in block.splitlines() if ln.strip()]
        kept.append(" ".join(lines[:2]).strip())
    return "\n".join(kept)


def _token_count(text: str, model: str) -> int:
    """Token count via Gemini count_tokens, falling back to a chars/4 heuristic when unavailable."""
    n = count_gemini_tokens(text, model)
    return n if n >= 0 else max(1, len(text) // 4)


# --------------------------------------------------------------------------- prompts


def _round1_prompt(draft: str, topic: str, evidence: str, schema_hint: str,
                   terse: bool = True, coded: bool = True, max_suggestions: int = 10) -> str:
    schema = _SCHEMA_CODED if coded else _SCHEMA
    terse_line = (_TERSE_DIRECTIVE + "\n") if terse else ""
    return f"""Senior IEEE/Elsevier peer reviewer. Critique this near-final draft: weak suggestions,
missed issues, structural problems, coverage gaps. Do NOT invent paper references; flag the need
without naming a paper. Return at most {max_suggestions} suggestions, highest-severity first.
Respond ONLY with valid JSON.
{terse_line}
Topic: {topic or 'not specified'}

Evidence (unverified candidates from external literature engines; do not assert a specific paper
exists unless listed):
---
{evidence or 'none'}
---

Draft:
---
{draft}
---

JSON schema (target_section examples: {schema_hint}):
{schema}
"""


def _round2_prompt(
    topic: str, schema_hint: str, own_r1: dict, other_r1: dict, other_name: str,
    terse: bool = True, coded: bool = True, max_suggestions: int = 10,
    draft: str = "", evidence: str = "",
) -> str:
    schema = _SCHEMA_CODED if coded else _SCHEMA
    extra = _R2_EXTRA_CODED if coded else _R2_EXTRA
    terse_line = (_TERSE_DIRECTIVE + "\n") if terse else ""
    # Default round 2 is slim: the rebuttal needs the two critiques, not the whole draft again.
    body_draft = f"\nDraft:\n---\n{draft}\n---\n" if draft else ""
    body_ev = f"\nEvidence:\n---\n{evidence}\n---\n" if evidence else ""
    return f"""Revise your peer review after seeing a second reviewer's critique.
{terse_line}
Topic: {topic or 'not specified'}
{body_draft}{body_ev}
Your first-round critique (JSON):
{json.dumps(own_r1, ensure_ascii=False)}

Other reviewer ({other_name}) critique (JSON):
{json.dumps(other_r1, ensure_ascii=False)}

For each point: keep, withdraw, or strengthen it given the other reviewer and the evidence. Where
you disagree, say so with a reason. Return at most {max_suggestions} suggestions. Respond ONLY with
valid JSON (target_section examples: {schema_hint}).
{schema}

{extra}
"""


# --------------------------------------------------------------------------- merge


def _norm(value: str) -> str:
    return (value or "").strip().lower()


def _best_conf(a: str, b: str) -> str:
    ra, rb = _CONF_RANK.get(_norm(a), 2), _CONF_RANK.get(_norm(b), 2)
    if ra == rb:
        return (a or "medium")
    return a if ra > rb else b


def _disagreed_sections(final_obj: dict) -> set:
    out = set()
    for r in (final_obj or {}).get("responses_to_other", []) or []:
        if isinstance(r, dict) and _norm(r.get("stance")) == "disagree":
            out.add(_norm(r.get("target_section")))
    return out


def _collect(final_obj: dict) -> list:
    return [s for s in (final_obj or {}).get("suggestions", []) or [] if isinstance(s, dict)]


def _mk_item(gs: dict, cs: dict, sources: list, agreement: str, confidence: str) -> dict:
    primary = gs or cs or {}
    item = {
        "rank": 0,
        "target_section": (primary.get("target_section") or "").strip(),
        "type": (primary.get("type") or "").strip(),
        "suggestion": (primary.get("suggestion") or "").strip(),
        "confidence": (confidence or "medium"),
        "requires_scopus_validation": bool(primary.get("requires_scopus_validation", False)),
        "agreement": agreement,
        "sources": sources,
        "conflict_notes": None,
    }
    if agreement == "conflict":
        notes = []
        if gs:
            notes.append("gemini: " + (gs.get("suggestion") or "").strip())
        if cs:
            notes.append("copilot: " + (cs.get("suggestion") or "").strip())
        item["conflict_notes"] = " | ".join(notes)
    return item


def _tier(item: dict) -> int:
    agreement, conf = item["agreement"], _norm(item["confidence"])
    if agreement == "consensus":
        return 0
    if agreement in ("gemini_only", "copilot_only") and conf == "high":
        return 1
    if agreement == "conflict":
        return 2
    if agreement in ("gemini_only", "copilot_only") and conf == "medium":
        return 3
    return 4


def _merge(gem_final: dict, cop_final: dict) -> list:
    """
    --------------------------------------------------------------------------
    Purpose:
        Pair the two models' final suggestions by (target_section, type), tag each
        merged item with an agreement value (consensus | conflict | gemini_only |
        copilot_only), and rank the list per the protocol tiers.

    Inputs:
        gem_final (dict): Gemini's final-round critique (or None).
        cop_final (dict): Copilot's final-round critique (or None).

    Outputs:
        merged (list): ranked merged suggestion dicts (see _mk_item).
    --------------------------------------------------------------------------
    """
    gem_sugs, cop_sugs = _collect(gem_final), _collect(cop_final)
    disagreed = _disagreed_sections(gem_final) | _disagreed_sections(cop_final)

    def key(s: dict) -> tuple:
        return (_norm(s.get("target_section")), _norm(s.get("type")))

    cop_index: dict = {}
    for i, s in enumerate(cop_sugs):
        cop_index.setdefault(key(s), []).append(i)

    used_cop: set = set()
    merged: list = []

    for gs in gem_sugs:
        match_idx = next((i for i in cop_index.get(key(gs), []) if i not in used_cop), None)
        if match_idx is not None:
            used_cop.add(match_idx)
            cs = cop_sugs[match_idx]
            agreement = "conflict" if key(gs)[0] in disagreed else "consensus"
            conf = _best_conf(gs.get("confidence"), cs.get("confidence"))
            merged.append(_mk_item(gs, cs, ["gemini", "copilot"], agreement, conf))
        else:
            merged.append(_mk_item(gs, None, ["gemini"], "gemini_only", gs.get("confidence")))

    for i, cs in enumerate(cop_sugs):
        if i not in used_cop:
            merged.append(_mk_item(None, cs, ["copilot"], "copilot_only", cs.get("confidence")))

    merged.sort(key=_tier)  # stable sort preserves original order within a tier
    for idx, item in enumerate(merged):
        item["rank"] = idx + 1
    return merged


# --------------------------------------------------------------------------- orchestration


def _safe_call(fn, *args):
    """Call a reviewer core; return (result_dict_or_None, error_str_or_None). Never raises."""
    try:
        return fn(*args), None
    except Exception as exc:  # ReviewerError or any API/runtime failure
        return None, str(exc)


def _synthesis(merged: list) -> str:
    total = len(merged)
    cons = sum(1 for m in merged if m["agreement"] == "consensus")
    conflict = sum(1 for m in merged if m["agreement"] == "conflict")
    single = total - cons - conflict
    return (f"Panel produced {total} merged suggestions: {cons} consensus, "
            f"{single} single-model, {conflict} conflict.")


def _fit_round1_prompt(draft: str, topic: str, evidence: str, schema_hint: str, model: str,
                       max_input_tokens: int, max_evidence_items: int, terse: bool, coded: bool,
                       max_suggestions: int, report_tokens: bool) -> str:
    """
    --------------------------------------------------------------------------
    Purpose:
        Build the shared round-1 prompt and progressively trim it under a token
        budget: strip source noise, cap evidence, then (only if still over)
        squeeze evidence harder and digest the draft. The prompt is identical for
        both models, so budgeting it once covers Gemini and Copilot.

    Inputs:
        draft, topic, evidence, schema_hint (str): prompt parts.
        model (str): Gemini model id used for count_tokens.
        max_input_tokens (int): budget ceiling.
        max_evidence_items (int): evidence cap.
        terse, coded (bool) / max_suggestions (int): compression knobs.
        report_tokens (bool): print a raw-vs-compressed reduction to stderr.

    Outputs:
        prompt (str): the trimmed round-1 prompt.
    --------------------------------------------------------------------------
    """
    if report_tokens:
        raw = _round1_prompt(draft, topic, evidence, schema_hint,
                             terse=False, coded=False, max_suggestions=max_suggestions)
        raw_n = _token_count(raw, model)

    draft_eff = _strip_source(draft)
    evidence_eff = _trim_evidence(evidence, max_evidence_items)

    def build(d, e):
        return _round1_prompt(d, topic, e, schema_hint,
                              terse=terse, coded=coded, max_suggestions=max_suggestions)

    prompt = build(draft_eff, evidence_eff)
    if _token_count(prompt, model) > max_input_tokens:           # 1) squeeze evidence to top-3
        evidence_eff = _trim_evidence(evidence, min(3, max_evidence_items))
        prompt = build(draft_eff, evidence_eff)
    if _token_count(prompt, model) > max_input_tokens:           # 2) digest the draft
        prompt = build(_digest_draft(draft_eff), evidence_eff)

    if report_tokens:
        final_n = _token_count(prompt, model)
        pct = round(100 * (raw_n - final_n) / raw_n) if raw_n > 0 else 0
        print(f"TOKENS: raw~{raw_n} compressed~{final_n} (-{pct}%)", file=sys.stderr)
    return prompt


def deliberate(draft: str, topic: str, evidence: str, rounds: int,
               gemini_model: str, copilot_model: str, temperature: float,
               plan_schema: str, *,
               max_input_tokens: int = 12000, max_output_tokens: int = 2048,
               max_suggestions: int = 10, max_evidence_items: int = 6,
               round2_include_draft: bool = False, terse: bool = True,
               coded_schema: bool = True, report_tokens: bool = False) -> dict:
    """
    --------------------------------------------------------------------------
    Purpose:
        Run the two-round Gemini<->Copilot debate and merge the result. Degrades
        gracefully: a missing key or failing model is marked unavailable and the
        survivor still deliberates; both missing yields an empty no-op envelope.

    Inputs:
        draft (str): the near-final draft to critique.
        topic (str): topic context for the reviewers.
        evidence (str): orchestrator-gathered evidence blob (may be "").
        rounds (int): 1 (independent only) or 2 (with rebuttal).
        gemini_model / copilot_model (str): model ids.
        temperature (float): sampling temperature.
        plan_schema (str): selects the target_section example vocabulary.
        max_input_tokens / max_output_tokens (int): per-call budget caps.
        max_suggestions (int): cap on suggestions requested per model.
        max_evidence_items (int): cap on evidence items sent.
        round2_include_draft (bool): re-send draft+evidence in round 2 (default off
            keeps round 2 slim — the rebuttal only needs the two critiques).
        terse (bool): inject the caveman terse directive into the prompts.
        coded_schema (bool): use short-key/coded-enum schema, expanded after parse.
        report_tokens (bool): print a raw-vs-compressed token reduction to stderr.

    Outputs:
        envelope (dict): the deliberation result (see module docstring / protocol).
    --------------------------------------------------------------------------
    """
    schema_hint = _SCHEMA_HINTS.get(plan_schema, _SCHEMA_HINTS["generic"])

    available = {"gemini": gemini_available() and run_gemini is not None,
                 "copilot": copilot_available() and run_copilot is not None}
    unavailable_markers = []
    if not available["gemini"]:
        unavailable_markers.append("[REVIEWER UNAVAILABLE: Gemini]")
    if not available["copilot"]:
        unavailable_markers.append("[REVIEWER UNAVAILABLE: Copilot]")

    envelope = {
        "mode": "deliberation",
        "topic": topic,
        "rounds_executed": 0,
        "reviewers_available": [],
        "reviewers_unavailable": [],
        "unavailable_markers": unavailable_markers,
        "overall_assessment": "",
        "round1": {"gemini": None, "copilot": None},
        "round2": {"gemini": None, "copilot": None},
        "merged": [],
    }

    if not available["gemini"] and not available["copilot"]:
        envelope["reviewers_unavailable"] = ["gemini", "copilot"]
        envelope["overall_assessment"] = (
            "Deliberation skipped - no reviewer credentials available.")
        return envelope

    r1_prompt = _fit_round1_prompt(
        draft, topic, evidence, schema_hint, gemini_model, max_input_tokens,
        max_evidence_items, terse, coded_schema, max_suggestions, report_tokens)
    gem_r1 = cop_r1 = None

    if available["gemini"]:
        gem_r1, err = _safe_call(run_gemini, r1_prompt, gemini_model, temperature, max_output_tokens)
        if gem_r1 is None:
            available["gemini"] = False
            unavailable_markers.append("[REVIEWER UNAVAILABLE: Gemini]")
            print(f"WARN: Gemini round 1 failed: {err}", file=sys.stderr)
        else:
            gem_r1 = _expand_schema(gem_r1)
    if available["copilot"]:
        cop_r1, err = _safe_call(run_copilot, r1_prompt, copilot_model, temperature, max_output_tokens)
        if cop_r1 is None:
            available["copilot"] = False
            unavailable_markers.append("[REVIEWER UNAVAILABLE: Copilot]")
            print(f"WARN: Copilot round 1 failed: {err}", file=sys.stderr)
        else:
            cop_r1 = _expand_schema(cop_r1)

    envelope["round1"] = {"gemini": gem_r1, "copilot": cop_r1}

    gem_r2 = cop_r2 = None
    if rounds >= 2:
        empty = {"overall_assessment": "(other reviewer unavailable)", "suggestions": []}
        # Slim round 2 by default: send the two critiques only, not the draft again.
        r2_draft = _strip_source(draft) if round2_include_draft else ""
        r2_ev = _trim_evidence(evidence, max_evidence_items) if round2_include_draft else ""
        if gem_r1 is not None:
            p = _round2_prompt(topic, schema_hint, gem_r1, cop_r1 or empty, "Copilot",
                               terse=terse, coded=coded_schema, max_suggestions=max_suggestions,
                               draft=r2_draft, evidence=r2_ev)
            gem_r2, err = _safe_call(run_gemini, p, gemini_model, temperature, max_output_tokens)
            if gem_r2 is None:
                print(f"WARN: Gemini round 2 failed, keeping round 1: {err}", file=sys.stderr)
            else:
                gem_r2 = _expand_schema(gem_r2)
        if cop_r1 is not None:
            p = _round2_prompt(topic, schema_hint, cop_r1, gem_r1 or empty, "Gemini",
                               terse=terse, coded=coded_schema, max_suggestions=max_suggestions,
                               draft=r2_draft, evidence=r2_ev)
            cop_r2, err = _safe_call(run_copilot, p, copilot_model, temperature, max_output_tokens)
            if cop_r2 is None:
                print(f"WARN: Copilot round 2 failed, keeping round 1: {err}", file=sys.stderr)
            else:
                cop_r2 = _expand_schema(cop_r2)

    envelope["round2"] = {"gemini": gem_r2, "copilot": cop_r2}
    envelope["rounds_executed"] = 2 if (rounds >= 2 and (gem_r2 or cop_r2)) else 1

    gem_final = gem_r2 or gem_r1
    cop_final = cop_r2 or cop_r1
    envelope["merged"] = _merge(gem_final, cop_final)

    envelope["reviewers_available"] = [m for m in ("gemini", "copilot") if available[m]]
    envelope["reviewers_unavailable"] = [m for m in ("gemini", "copilot") if not available[m]]
    # Deduplicate markers while preserving order.
    envelope["unavailable_markers"] = list(dict.fromkeys(unavailable_markers))
    envelope["overall_assessment"] = _synthesis(envelope["merged"])
    return envelope


# --------------------------------------------------------------------------- CLI


def _read_evidence(args) -> str:
    if args.evidence_file:
        try:
            return Path(args.evidence_file).read_text(encoding="utf-8")
        except OSError as exc:
            print(f"ERROR: cannot read --evidence-file: {exc}", file=sys.stderr)
            sys.exit(1)
    return args.evidence_context or ""


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # JSON may carry non-ASCII from the models

    parser = argparse.ArgumentParser(
        description="Two-round Gemini<->Copilot deliberation panel for the academic agents")
    parser.add_argument("draft", nargs="?", default=None, help="Draft text (or use --stdin)")
    parser.add_argument("--stdin", action="store_true", help="Read the draft from stdin")
    parser.add_argument("--topic", default="", help="Topic context for the reviewers")
    parser.add_argument("--evidence-file", default=None,
                        help="Path to the orchestrator evidence blob (Consensus / Scopus.AI)")
    parser.add_argument("--evidence-context", default=None,
                        help="Inline evidence blob (prefer --evidence-file for large text)")
    parser.add_argument("--rounds", type=int, default=2, help="1 (independent) or 2 (debate)")
    parser.add_argument("--gemini-model", default="gemini-2.0-flash")
    parser.add_argument("--copilot-model", default="gpt-4o")
    parser.add_argument("--temperature", type=float, default=0.3)
    parser.add_argument("--plan-schema", default="generic",
                        choices=["auditor", "researcher", "reviewer-response", "generic"])
    parser.add_argument("--out", default="-", help="Output path, or '-' for stdout")
    # Token budget (free-tier safe defaults)
    parser.add_argument("--max-input-tokens", type=int, default=12000,
                        help="Trim the prompt below this many tokens")
    parser.add_argument("--max-output-tokens", type=int, default=2048,
                        help="Hard cap on each model's response")
    parser.add_argument("--max-suggestions", type=int, default=10,
                        help="Cap on suggestions requested per model")
    parser.add_argument("--max-evidence-items", type=int, default=6,
                        help="Cap on evidence items sent")
    parser.add_argument("--round2-include-draft", action="store_true",
                        help="Re-send draft+evidence in round 2 (default: slim, critiques only)")
    # Compression (RTK / Caveman analogues), all on by default
    parser.add_argument("--terse", dest="terse", action="store_true", default=True,
                        help="Caveman terse directive on output values (default on)")
    parser.add_argument("--no-terse", dest="terse", action="store_false")
    parser.add_argument("--coded-schema", dest="coded_schema", action="store_true", default=True,
                        help="Short-key/coded-enum schema, expanded after parse (default on)")
    parser.add_argument("--no-coded-schema", dest="coded_schema", action="store_false")
    parser.add_argument("--report-tokens", action="store_true",
                        help="Print raw-vs-compressed token counts to stderr")
    args = parser.parse_args()

    if args.rounds not in (1, 2):
        print("ERROR: --rounds must be 1 or 2.", file=sys.stderr)
        sys.exit(1)

    if args.stdin:
        draft = sys.stdin.read().strip()
    elif args.draft:
        draft = args.draft.strip()
    else:
        parser.error("Provide draft text as an argument or use --stdin")

    if not draft:
        print("ERROR: Draft text is empty.", file=sys.stderr)
        sys.exit(1)

    evidence = _read_evidence(args)

    envelope = deliberate(
        draft=draft, topic=args.topic, evidence=evidence, rounds=args.rounds,
        gemini_model=args.gemini_model, copilot_model=args.copilot_model,
        temperature=args.temperature, plan_schema=args.plan_schema,
        max_input_tokens=args.max_input_tokens, max_output_tokens=args.max_output_tokens,
        max_suggestions=args.max_suggestions, max_evidence_items=args.max_evidence_items,
        round2_include_draft=args.round2_include_draft, terse=args.terse,
        coded_schema=args.coded_schema, report_tokens=args.report_tokens,
    )

    out_text = json.dumps(envelope, ensure_ascii=False, indent=2)
    if args.out and args.out != "-":
        Path(args.out).write_text(out_text, encoding="utf-8")
    else:
        print(out_text)


if __name__ == "__main__":
    main()
