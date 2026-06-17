# Deliberation protocol (canonical)

This is the single source of truth for the multi-model deliberation panel used by the academic
agents (scopus-auditor, paper-auditor, thesis-auditor, thesis-proposal-auditor, scopus-researcher,
reviewer-response). Each agent embeds a short "Deliberation" step that points here; the arbitration
table, provenance markers, validation gate, and log format are defined once, in this file.

## 1. Purpose and the two hard boundaries

The panel improves a near-final draft by having two external models (Gemini and GitHub Copilot)
debate it over two rounds, enriched with literature evidence (Consensus, and for scopus-researcher
also Scopus.AI). Claude is the final judge: it arbitrates the merged suggestions, validates any new
reference against Scopus, and applies the accepted changes.

Two boundaries shape how the work is split:

1. No nested agents. This repo has no agent-to-agent dispatch. The capability is a skill module
   (`deliberate.py` + this doc), invoked by a step the agent embeds, not a separate agent.
2. A subprocess cannot reach MCP or Scopus.AI. `deliberate.py` runs only the Gemini and Copilot API
   calls. Consensus (MCP tool `mcp__claude_ai_Consensus__search`) and Scopus.AI (manual) are reached
   by the agent, which gathers their findings and passes them to the script as an evidence blob.

## 2. Sources

| Source | Who calls it | How | Availability / skip rule |
|---|---|---|---|
| Gemini 2.0 Flash | `deliberate.py` | API, both rounds | `GEMINI_API_KEY` unset or `google-genai` missing -> skip, mark `[REVIEWER UNAVAILABLE: Gemini]` |
| GitHub Copilot (GPT-4o) | `deliberate.py` | API, both rounds | `GITHUB_TOKEN` unset or `openai` missing -> skip, mark `[REVIEWER UNAVAILABLE: Copilot]` |
| Consensus | the agent | `mcp__claude_ai_Consensus__search`, before deliberation; folded into the evidence blob | MCP unreachable -> log `Consensus : MCP indisponible`, pass an empty evidence file |
| Scopus.AI | the agent (scopus-researcher only) | manual copy-paste at the researcher's Step 1a | researcher only; the other five agents never invoke it |

The agent gathers evidence first (a small, targeted set of Consensus queries on the draft's main
claims or gaps, batches of at most 3, one query per second), writes it to a file, then runs the
script with `--evidence-file`. Use a file, not `--evidence-context`, so large dumps survive
PowerShell quoting.

At least one Consensus query in every run MUST be a gap probe of the form "what key recent papers on
`<draft topic / weakest claim>` are missing from this draft" — the panel's job is not only to
critique the existing text but to surface references that should be added. The papers these probes
return feed the `coverage_gap` arbitration (section 4) and the Scopus gate (section 5).

## 3. The two debate rounds

`deliberate.py` runs the debate; the agent does not prompt the models directly.

- Round 1 (independent critique). Each available model receives the draft plus the evidence blob and
  returns the reviewer schema `{overall_assessment, suggestions[]}`, where each suggestion has
  `target_section, type, suggestion, confidence, requires_scopus_validation`. Models are told not to
  invent a specific paper; they flag the need instead.
- Round 2 (rebuttal, default `--rounds 2`). Each model is shown the other model's Round-1 JSON and
  the same evidence, and revises: keep, withdraw, or strengthen each point, adding
  `responses_to_other[] {target_section, stance(agree|disagree|partial), reason}`. `--rounds 1`
  skips this and the Round-1 position is final.
- Merge. The script pairs suggestions by `(target_section, type)` and assigns each merged item an
  `agreement` value, then ranks them: `consensus` first, then single-model `high`, then `conflict`,
  then single-model `medium`, then `low`.

The script never accepts, validates, or scores anything. It emits evidence for Claude to judge.

## 4. Canonical arbitration table and provenance markers

Claude arbitrates every item in the script's `merged[]` list with this table (carried over verbatim
from the original scopus-auditor cross-review so the logic is now defined once):

| Condition | Rule | Plan marker |
|---|---|---|
| Both Gemini AND Copilot flag same issue | Accept — consensus | `[✓ GEMINI + COPILOT]` |
| `reference_issue`, `requires_scopus_validation: true` | Run the Scopus gate (section 5) first; accept only if Scopus confirms | `[✓ GEMINI]` or `[✓ COPILOT]` |
| `text_improvement`, `confidence: high`, single reviewer | Accept unless it contradicts Scopus-validated facts | `[✓ GEMINI]` or `[✓ COPILOT]` |
| `text_improvement`, `confidence: low` | Flag but do not apply | `[? GEMINI — LOW]` or `[? COPILOT — LOW]` |
| `coverage_gap` | Run `scopus_api.py search` to verify papers exist; accept if >= 1 result. On accept, produce a Scopus-validated BibTeX entry, a one-sentence introduction, and an insertion point, then route into the host agent's gap section | `[✓ GEMINI]` or `[✓ COPILOT]` |
| `style` | Accept if consistent with the CLAUDE.md anti-AI-style rules | `[✓ GEMINI]` or `[✓ COPILOT]` |
| Gemini and Copilot contradict each other | Claude decides; note both positions | `[✓ GEMINI — COPILOT DISAGREED]` |
| Rejected | Log the reason in the Deliberation Log | `[✗ — reason]` |

The eight canonical markers are: `[✓ GEMINI + COPILOT]`, `[✓ GEMINI]`, `[✓ COPILOT]`,
`[? GEMINI — LOW]`, `[? COPILOT — LOW]`, `[✓ GEMINI — COPILOT DISAGREED]`, `[✗ — reason]`, and the two
unavailability markers `[REVIEWER UNAVAILABLE: Gemini]` / `[REVIEWER UNAVAILABLE: Copilot]`.

Mapping from the script's `agreement` field to the starting marker:

| `agreement` | Starting marker (before the gate) |
|---|---|
| `consensus` | `[✓ GEMINI + COPILOT]` |
| `gemini_only` | `[✓ GEMINI]` |
| `copilot_only` | `[✓ COPILOT]` |
| `conflict` | `[✓ GEMINI — COPILOT DISAGREED]` (Claude resolves, recording both positions) |

This table supersedes the lighter inline variants previously embedded in paper-auditor,
thesis-auditor, and thesis-proposal-auditor.

## 5. Scopus validation gate for any new reference

Before accepting any suggestion that proposes or relies on a specific paper (`type: reference_issue`
or `coverage_gap`, or any item with `requires_scopus_validation: true`), Claude runs Scopus and
accepts only on confirmation. The two modes differ, so use the right one:

- Full bibliographic fields available (DOI, title, authors, year): use `verify`, accept only on
  `valid: true`.
  ```
  python ".claude/skills/scopus/scripts/scopus_api.py" verify "<DOI or title>" --expected-title "..." --expected-authors "..." --expected-year "YYYY"
  ```
- Existence check only (a coverage-gap topic, no full entry): use `validate` or `search`, accept if
  at least one result is returned.
  ```
  python ".claude/skills/scopus/scripts/scopus_api.py" validate "<title>"
  python ".claude/skills/scopus/scripts/scopus_api.py" search  "<topic>" --count 5
  ```

Warning: `validate` returns `{"mode": "validate", "query": ..., "total_found": N, "results": [...]}`.
It has NO `valid` field. Test `total_found >= 1` (or a non-empty `results`), never `result["valid"]`.
Only `verify` returns `valid: true|false`.

Host-stricter rule. When the host agent already defines a stricter reference workflow, defer to it
instead of this generic gate. In particular, reviewer-response runs its own decision tree (found +
DOI auto-approve; found + no DOI flag `[NO DOI]`; not found remove and search a validated
alternative); a panel-proposed reference there goes through that tree, not this section.

## 6. scholar-evaluation scoring handoff (optional)

For agents that already produce a ScholarEval score (the five auditor and researcher agents), run the
deliberation step before the scoring step so the score reflects the deliberated draft. Map the
dimension scores to the fixed eight keys and call the skill:

```
python ".claude/skills/scholar-evaluation/scripts/calculate_scores.py" --scores <scores.json> --output <report.txt>
```

Keys: `problem_formulation, literature_review, methodology, data_collection, analysis, results,
writing, citations`.

reviewer-response has no quality score and skips this handoff. There the panel's value is the
critique of each rebuttal plus the supporting evidence, not a numeric grade.

## 7. Deliberation Log

After arbitration, append this block to the agent's output (the plan file for the auditors, the
final review for the researcher, the Step 8 summary for reviewer-response). It generalizes the older
`## Cross-Review Log`.

```markdown
## Deliberation Log
Panel: Gemini (gemini-2.0-flash) + Copilot (gpt-4o) + Consensus[ + Scopus.AI]
Rounds: 2   Reviewers unavailable: [none | Gemini | Copilot]
Evidence: Consensus searches: N   [Scopus.AI prompts: M — researcher only]

### Accepted
- [✓ GEMINI + COPILOT] <section> — <suggestion> (Scopus: verified <DOI> | existence confirmed | n/a)

### Flagged (not applied)
- [? GEMINI — LOW] <section> — <suggestion>

### Conflicts resolved by Claude
- [✓ GEMINI — COPILOT DISAGREED] <section> — <decision, with both positions noted>

### Rejected
- [✗ — reason] <section> — <suggestion>
```

Omit any subsection that has no items.

## 8. Graceful-skip rules

The deliberation step is MANDATORY: the host agent runs it on every invocation and does not skip it
on grounds of usefulness, draft length, or its own confidence. The only sanctioned skips are the
environmental ones listed below (missing API keys, unreachable MCP), and each still requires the
agent to record its marker in the Deliberation Log. None of these abort the host pipeline.

- One model unavailable (missing key or missing dependency): the script skips it, still deliberates
  with the survivor, and returns the matching `[REVIEWER UNAVAILABLE: ...]` marker. Items keep
  `agreement: gemini_only` or `copilot_only`. Paste the marker into the Deliberation Log.
- Both models unavailable: the script returns an empty `merged` list and a skip sentence in
  `overall_assessment`, and exits 0. The deliberation step is then a no-op; continue the pipeline and
  record both unavailability markers.
- Consensus MCP unreachable: log `Consensus : MCP indisponible` and pass an empty evidence file; the
  debate still runs on the draft alone.
- Scopus.AI skipped by the user (researcher only): omit the Scopus.AI section from the evidence blob.

### Free-tier token budget

`deliberate.py` keeps every call inside a token budget automatically, so a free-tier Gemini key
(`GEMINI_API_KEY` from AI Studio) does not exhaust the quota on the prompt. Defaults, all overridable
by flag: `--max-input-tokens 12000`, `--max-output-tokens 2048`, `--max-suggestions 10`,
`--max-evidence-items 6`; round 2 is slim (critiques only, no draft re-send) unless
`--round2-include-draft`; output is compressed by a caveman terse directive (`--no-terse` to disable)
and a coded JSON schema (`--no-coded-schema` to disable), expanded back to the canonical schema
before arbitration. Add `--report-tokens` to print the raw-vs-compressed reduction. On a tight free
tier prefer `--rounds 1` (round 2 still works, now slim). These are compression/budget controls only;
the arbitration table, markers, and the Scopus gate are unchanged.

## 9. How an agent invokes the panel

```powershell
# 1. Gather evidence (agent side, MCP): mcp__claude_ai_Consensus__search x <=4, write to a file.
# 2. Run the debate (subprocess):
$draft | python ".claude/skills/deliberation/scripts/deliberate.py" --stdin `
    --topic "<detected topic>" --rounds 2 `
    --plan-schema <auditor|researcher|reviewer-response|generic> `
    --evidence-file "<evidence.txt>"
# 3. Parse merged[]; arbitrate per sections 4-5; apply accepted items; append the Deliberation Log.
```

The step is fully autonomous: no user pause. (scopus-researcher keeps its single sanctioned pause at
Step 1a for Scopus.AI; the deliberation step itself never pauses.)
