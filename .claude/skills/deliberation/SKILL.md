---
name: deliberation
description: "Two-round multi-model deliberation panel: Gemini and GitHub Copilot debate a near-final draft (via deliberate.py), enriched with Consensus and optional Scopus.AI evidence, after which Claude arbitrates per the canonical protocol, validates new references against Scopus, and writes a Deliberation Log. Used as the standardized Deliberation step inside the academic auditor and researcher agents (scopus-auditor, paper-auditor, thesis-auditor, thesis-proposal-auditor, scopus-researcher, reviewer-response) before the final plan, review, or response is written. Trigger when an agent reaches its deliberation/cross-review step."
allowed-tools: [Read, Write, Edit, Bash]
permissions: [env, read, write, shell]
---

# Deliberation panel

A reusable cross-model deliberation applied to a near-final draft. Two external models debate it
over two rounds; Claude is the final judge. The full arbitration logic lives in
[references/deliberation-protocol.md](references/deliberation-protocol.md) — read it before using
this skill. This file is the entry point and contract.

## When to use

- An agent has assembled its near-final output (an improvement plan, a literature review, or a set
  of point-by-point reviewer responses) and needs a rigorous, evidence-backed critique before
  writing it out.
- You want Gemini and Copilot to debate each other (not just review in isolation) and to react to
  fresh literature evidence from Consensus (and Scopus.AI for the researcher).

## Active mandate: find missing references

Beyond critiquing the draft, the panel actively probes for references that should be added to the
specific paper, thesis, or review under audit. The Consensus queries ask what key papers on the
draft's topics and claims are missing; the Gemini and Copilot reviewers return `coverage_gap`
suggestions. Every accepted `coverage_gap` is validated against Scopus, turned into a BibTeX entry
plus a one-sentence introduction and an insertion point, and routed into the host agent's gap
section. Gap-filling on the audited draft is in scope here.

## When NOT to use

- For broad, open-ended topic discovery unanchored to a draft. The initial literature sweep that
  predates any hypothesis stays at scopus-researcher Step 1d. This skill fills gaps on a specific,
  near-final draft; it does not replace that sweep.
- As a standalone command typed by the user. The skill is invoked by the agents at their
  deliberation step, not directly.

## How it splits the work (two hard boundaries)

1. No nested agents in this repo, so the capability is a skill module invoked by an embedded step,
   not a separate agent.
2. A subprocess cannot reach MCP or Scopus.AI, so `deliberate.py` runs only the Gemini and Copilot
   API calls. The agent gathers Consensus (MCP) and Scopus.AI (manual) evidence and passes it in
   via `--evidence-file`.

## Prerequisites

- `GEMINI_API_KEY` and/or `GITHUB_TOKEN`. Either, both, or neither: the panel degrades gracefully
  (a missing key marks that model unavailable; both missing makes the step a no-op that never
  aborts the pipeline).
- `google-genai` and `openai` importable (see `.claude/skills/scopus/scripts/requirements.txt`,
  audited with pip-audit). Missing imports are treated like a missing key.
- For Consensus evidence: the agent needs the `mcp__claude_ai_Consensus__search` tool.
- For the reference gate: `.claude/skills/scopus/scripts/scopus_api.py` reachable.

## Inputs and outputs

- Input: the near-final draft on stdin; topic via `--topic`; the agent-gathered evidence via
  `--evidence-file` (preferred) or `--evidence-context`.
- Output: a JSON envelope on stdout — `reviewers_available`, `reviewers_unavailable`,
  `unavailable_markers`, `overall_assessment`, `round1`, `round2`, and a ranked `merged[]` list
  where each item carries an `agreement` field (`consensus | conflict | gemini_only | copilot_only`).
  Claude maps `agreement` to the canonical markers and arbitrates.

## Invocation

```powershell
# 1. Agent gathers evidence (MCP): mcp__claude_ai_Consensus__search x <=4, write to evidence.txt.
# 2. Run the debate:
$draft | python ".claude/skills/deliberation/scripts/deliberate.py" --stdin `
    --topic "<topic>" --rounds 2 `
    --plan-schema <auditor|researcher|reviewer-response|generic> `
    --evidence-file "<evidence.txt>"
# 3. Parse merged[]; arbitrate, validate new refs, apply, append the Deliberation Log
#    (all rules in references/deliberation-protocol.md).
```

## Resources

- `scripts/deliberate.py` — the two-round debate engine and merger.
- `references/deliberation-protocol.md` — canonical sources table, debate rounds, arbitration table
  and markers, Scopus validation gate, scholar-evaluation handoff, Deliberation Log format, and
  graceful-skip rules.
- `Test/test_deliberate.py` — offline-patched unit tests (merge, ranking, degradation, CLI exit
  codes).
