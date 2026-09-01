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

- `GEMINI_API_KEY` for the Gemini leg, and for the GitHub leg one of `COPILOT_TOKEN`,
  `GH_OAUTH_TOKEN` (exchanged automatically for a Copilot token), or the legacy `GITHUB_TOKEN`.
  Either leg, both, or neither: the panel degrades gracefully (a missing key marks that model
  unavailable; both missing makes the step a no-op that never aborts the pipeline).
- `google-genai` and `openai` importable (see `.claude/skills/scopus/scripts/requirements.txt`,
  audited with pip-audit). Missing imports are treated like a missing key.
- For Consensus evidence: the agent needs the `mcp__claude_ai_Consensus__search` tool.
- For the reference gate: `.claude/skills/scopus/scripts/scopus_api.py` reachable.

## Model resolution and provider failover

Neither leg hardcodes a model. `--gemini-model auto` and `--copilot-model auto` (both the
default) resolve the newest model at run time from the provider's own catalog, and the envelope
records the concrete ids under `models` so a log never leaves `auto` to be guessed at. A frozen
default is what killed each leg once: Gemini on the retired `gemini-2.0-flash`, GitHub on a
`gpt-4o` that stayed put while newer models shipped.

Ranking, per `copilot_providers.recency_key`: numeric family version first, then the catalog's
own release date, then stable over preview, then the id. Generation outranks date deliberately,
because a re-published older family carries a fresher date than a newer one; the date only
separates two releases of the same family. A newer-generation preview therefore beats an older
stable, which is why the Gemini leg runs `gemini-3.1-pro-preview` rather than `gemini-2.5-pro`.

The GitHub leg walks a provider chain and uses the first one holding a token, failing over on an
HTTP status as well as on a network error:

| Provider | Host | Token | Model id form |
|---|---|---|---|
| `copilot` | `api.githubcopilot.com` | `COPILOT_TOKEN`, or minted from `GH_OAUTH_TOKEN` | bare |
| `github-models` | `models.github.ai/inference` | `GITHUB_TOKEN` | `publisher/model` |
| `azure-inference` | `models.inference.ai.azure.com` | `GITHUB_TOKEN` | bare |

GitHub Copilot and GitHub Models are different products with different credentials, and the two
are easy to confuse because the Copilot model picker shows GPT, Gemini, Kimi and MAI. Copilot
refuses a personal access token (`400 Personal Access Tokens are not supported for this
endpoint`); it wants a short-lived token minted from an OAuth login, which the panel will do by
itself given `GH_OAUTH_TOKEN` (obtain it with `gh auth login`, then `gh auth token`). GitHub
Models, the free inference API a PAT could call, was retired on 2026-07-30 and answers
`410 github_models_retirement_brownout`; both of its hosts stay in the chain because a chain is
what survives the next retirement. Measured 2026-08-14: with only `GITHUB_TOKEN` set, every
provider fails and the leg is correctly marked unavailable.

Run `python .claude/skills/scopus/scripts/github_reviewer.py --list-models` to see each catalog
and the winner. A `resolved:` line reading `(FALLBACK - no catalog answered)` means no catalog
could be read and the run would be on a known-stale id, not on the latest.

## Schema tolerance and lost critiques

Both legs expand a coded-key response back to the canonical schema before it reaches the merge,
so a model that answers `{"a": ..., "x": [...]}` is understood rather than dropped. The expansion
is idempotent on canonical input and runs by default in `run_gemini` / `run_copilot`. It is
opt-out (`expand=False`) for a caller whose own schema uses free dict keys — `gemini_table.py`
does that, since its `cells` are keyed by the table's concept names and a column named `c` or
`t` would otherwise be renamed.

When a response cannot be parsed at all, the leg's entry in `round1` / `round2` carries `_error`
and the truncated `_raw` text instead of vanishing. An empty critique that is silently dropped
reads as agreement in the merge, which is the worse failure.

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
- `../scopus/scripts/copilot_providers.py` — the GitHub provider chain, the token exchange, and
  the latest-model ranking.
- `../scopus/scripts/reviewer_schema.py` — the coded-to-canonical expansion both legs share, and
  the `_error` / `_raw` object a failed leg logs.
- `references/deliberation-protocol.md` — canonical sources table, debate rounds, arbitration table
  and markers, Scopus validation gate, scholar-evaluation handoff, Deliberation Log format, and
  graceful-skip rules.
- `Test/test_deliberate.py` — offline-patched unit tests (merge, ranking, degradation, CLI exit
  codes, coded-schema tolerance, `_raw` preservation, provider failover, model resolution).
