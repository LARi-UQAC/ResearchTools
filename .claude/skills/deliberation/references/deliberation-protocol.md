# Deliberation protocol (canonical)

This is the single source of truth for the multi-model deliberation panel used by the academic
agents (scopus-auditor, paper-auditor, thesis-auditor, thesis-proposal-auditor, scopus-researcher,
reviewer-response). Each agent embeds a short "Deliberation" step that points here; the arbitration
table, provenance markers, validation gate, and log format are defined once, in this file.

## 1. Purpose and the two hard boundaries

The panel improves a near-final draft by having two external models (Gemini and a second reviewer:
GitHub Copilot, or a local Ollama model as the fallback when Copilot does not answer) debate it over
two rounds, enriched with literature evidence (Consensus, and for scopus-researcher also Scopus.AI).
Claude is the final judge: it arbitrates the merged suggestions, validates any new reference against
Scopus, and applies the accepted changes.

What is deliberated is not limited to a kind of object. An agent may submit a plan, a whole review,
reviewer responses, but also a research question, a hypothesis, a methodological choice, a table, a
result, a figure's claim or an equation and its assumptions. The arbitrating agent chooses which
questions to ask, with autonomy, and should phrase them so that the answer can DISAGREE (what is
wrong or missing, what a skeptical reader would object to), in order to obtain an opinion different
from its own. Section 10 states the context every submission must carry.

Two boundaries shape how the work is split:

1. No nested agents. This repo has no agent-to-agent dispatch. The capability is a skill module
   (`deliberate.py` + this doc), invoked by a step the agent embeds, not a separate agent.
2. A subprocess cannot reach MCP or Scopus.AI. `deliberate.py` runs only the Gemini and Copilot API
   calls. Consensus (MCP tool `mcp__claude_ai_Consensus__search`) and Scopus.AI (manual) are reached
   by the agent, which gathers their findings and passes them to the script as an evidence blob.

## 2. Sources

| Source | Who calls it | How | Availability / skip rule |
|---|---|---|---|
| Gemini (newest PRO, resolved at run time) | `deliberate.py` | API, both rounds | `GEMINI_API_KEY` unset or `google-genai` missing -> skip, mark `[REVIEWER UNAVAILABLE: Gemini]` |
| GitHub Copilot (newest catalog entry, resolved at run time) | `deliberate.py` | API, both rounds | no `COPILOT_TOKEN` or `GH_OAUTH_TOKEN`, or `openai` missing, or the call fails (a personal `GITHUB_TOKEN` passes the availability check and is refused at the call) -> skip, mark `[REVIEWER UNAVAILABLE: Copilot]` |
| Local Ollama model (named by `model_resolver.py` for the `session` role, never in code) | `deliberate.py` | API, both rounds, ONLY as the fallback when Copilot is unavailable or fails its call (`--second-reviewer auto`, the default) | resolver names no tag or the daemon is down -> mark `[REVIEWER UNAVAILABLE: Ollama]`. Slow (minutes per call): the panel is meant to be run unattended |
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
  then single-model `medium`, then `low`. Every merged item carries a stable `id` (`M1`, `M2`, ...).
  The pairing is LITERAL: two reviewers who make the same point under different labels (`general`
  against `H1`) come out as two single-model items. Before judging agreement, Claude pairs such
  items by MEANING and records the pairing; a consensus the script missed is still a consensus.
- Context record. The envelope carries `context`: the characters of the draft and of the evidence
  sent against what was supplied, whether the draft was digested or the evidence squeezed to fit the
  token budget, the prompt tokens against the budget, and `warnings[]` in words (digested draft, no
  `--topic`, no evidence, and a format cleaning that removed more than the configured share of the
  draft). Claude reads it before arbitrating: a reviewer that did not see the full text cannot be
  held to a full-text opinion, and any `warnings[]` entry goes into the Log. The cleaning removes
  only LaTeX preambles and comments, code fences, markup tags and HTML comments, never an
  inequality; measured 2026-10-11, a pattern that matched from any `<` to the next `>` had erased
  two thirds of a mathematical draft with no warning.

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
| `structure` (a change to the order, split or merge of sections, or to the plan's own shape) | Accept only if it serves the stated objective of the work and does not contradict a host-agent rule (a mandated section order, a page limit, a template); otherwise flag with the rule it would break | `[✓ GEMINI]` / `[✓ COPILOT]`, or `[? ... — LOW]` when flagged |
| Gemini and Copilot contradict each other | Claude decides; note both positions | `[✓ GEMINI — COPILOT DISAGREED]` |
| Off topic, or answers a different question from the one asked, or rests on a premise the work does not hold (an assumption the draft states the opposite of) | Rejected, with the premise it breaks written out. A confident tone is not evidence | `[✗ — reason]` |
| Rejected | Log the reason in the Deliberation Log | `[✗ — reason]` |

For every item Claude first judges RELEVANCE (does it answer the question asked, about the work as it
stands) and only then applies the row above. No item is adopted because it is confident, and none is
ignored because it is inconvenient: every item gets a disposition and a reason. When the second
reviewer is the local fallback, the marker is `[✓ OLLAMA]` / `[? OLLAMA — LOW]` and the pairing
markers read `[✓ GEMINI + OLLAMA]`; the rules are identical.

The eight canonical markers are: `[✓ GEMINI + COPILOT]`, `[✓ GEMINI]`, `[✓ COPILOT]`,
`[? GEMINI — LOW]`, `[? COPILOT — LOW]`, `[✓ GEMINI — COPILOT DISAGREED]`, `[✗ — reason]`, and the two
unavailability markers `[REVIEWER UNAVAILABLE: Gemini]` / `[REVIEWER UNAVAILABLE: Copilot]`.

Mapping from the script's `agreement` field to the starting marker:

| `agreement` | Starting marker (before the gate) |
|---|---|
| `consensus` | `[✓ GEMINI + COPILOT]` |
| `gemini_only` | `[✓ GEMINI]` |
| `copilot_only` | `[✓ COPILOT]` |
| `ollama_only` | `[✓ OLLAMA]` |
| `conflict` | `[✓ GEMINI — COPILOT DISAGREED]` (Claude resolves, recording both positions; `OLLAMA` replaces `COPILOT` when the local fallback answered, see `second_reviewer` in the envelope) |

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
Panel: Gemini (<envelope models.gemini>) + <second reviewer> (<envelope models.<name>>) + Consensus[ + Scopus.AI]
Rounds: 2   Reviewers unavailable: [none | Gemini | Copilot | Ollama]   Fallback: [none | Copilot -> Ollama, <reason>]
Evidence: Consensus searches: N   [Scopus.AI prompts: M — researcher only]
Context: draft chars sent / supplied, digested: [yes|no], evidence squeezed: [yes|no]; warnings: [none | <each envelope context.warnings entry>]
Accounting: merged items N = Accepted a + Flagged b + Conflicts c + Rejected d  (every id M1..MN appears below)

### Accepted
- M1 [✓ GEMINI + COPILOT] <section> — <suggestion> (Scopus: verified <DOI> | existence confirmed | n/a)

### Flagged (not applied)
- M5 [? GEMINI — LOW] <section> — <suggestion>

### Conflicts resolved by Claude
- M3 [✓ GEMINI — COPILOT DISAGREED] <section> — <decision, with both positions noted>

### Rejected
- M7 [✗ — reason] <section> — <suggestion>
```

Omit any subsection that has no items. The Log is COMPLETE only when every `merged[].id` of the
envelope appears exactly once in the four lists, so that the `Accounting` line adds up. An item left
out is a defect of the step, not a judgement: before writing the Log, count the `merged[]` items and
the Log items and reconcile any difference. Items Claude paired by meaning (section 3) appear once,
under both ids.

## 8. Graceful-skip rules

The deliberation step is MANDATORY: the host agent runs it on every invocation and does not skip it
on grounds of usefulness, draft length, or its own confidence. The only sanctioned skips are the
environmental ones listed below (missing API keys, unreachable MCP), and each still requires the
agent to record its marker in the Deliberation Log. None of these abort the host pipeline.

- One model unavailable (missing key or missing dependency, or a failed call): the script skips it,
  still deliberates with the survivor, and returns the matching `[REVIEWER UNAVAILABLE: ...]` marker.
  Items keep `agreement: gemini_only`, `copilot_only` or `ollama_only`. Paste the marker into the
  Deliberation Log. Having a `GITHUB_TOKEN` is NOT a guarantee that Copilot answers (a personal token
  is refused at the call): the real test is the call, and its failure triggers the local fallback.
- Copilot unavailable or failing, and a local model declared for the resolver's `session` role: the
  panel calls the local model at that moment (`second_reviewer: ollama`, `fallback` recorded in the
  envelope). The call is slow, and the step still never pauses. When no local model is declared, the
  fallback is itself unavailable and the panel proceeds with Gemini alone.
- Both models unavailable: the script returns an empty `merged` list and a skip sentence in
  `overall_assessment`, and exits 0. The deliberation step is then a no-op; continue the pipeline and
  record both unavailability markers.
- Consensus MCP unreachable: log `Consensus : MCP indisponible` and pass an empty evidence file; the
  debate still runs on the draft alone.
- Scopus.AI skipped by the user (researcher only): omit the Scopus.AI section from the evidence blob.

### Free-tier token budget

`deliberate.py` keeps every call inside a token budget automatically, so a free-tier Gemini key
(`GEMINI_API_KEY` from AI Studio) does not exhaust the quota on the prompt. Defaults, all overridable
by flag: `--max-input-tokens 12000`, `--max-output-tokens 4096`, `--max-suggestions 10`,
`--max-evidence-items 6`; round 2 is slim (critiques only, no draft re-send) unless
`--round2-include-draft`, which the host agents pass whenever the rebuttal depends on the
context (section 10); output is compressed by a caveman terse directive (`--no-terse` to disable)
and a coded JSON schema (`--no-coded-schema` to disable), expanded back to the canonical schema
before arbitration. Add `--report-tokens` to print the raw-vs-compressed reduction. On a tight free
tier prefer `--rounds 1` (round 2 still works, now slim). These are compression/budget controls only;
the arbitration table, markers, and the Scopus gate are unchanged. When the prompt exceeds the
budget the script digests the draft to its signal lines: that is a LOSS of context and is reported
in the envelope's `context` record, never silently. Prefer a smaller object with its full context,
or a higher `--max-input-tokens`, to a digest. The local fallback receives the same prompt and
REFUSES, with the numbers, a prompt over its window; it is never given a digest.

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

## 10. The context every submission must carry

The reviewers see only the prompt: no repository, no earlier turn, no other chapter. A question that
omits its context gets an answer about a different problem. Measured 2026-10-11: a three-line
hypothesis sent with no definitions made the local reviewer answer "this is a question, not a
paper", an answer about the prompt and not about the work. So every submission, whatever the object,
is self-sufficient. The host agent decides which questions to ask and puts into each:

- what the object is and where it sits in the work (section, role, what it must achieve);
- the full text of the object, and the definitions, notation, assumptions, equations and earlier
  results it depends on, stated and not merely referenced;
- for a table or a result: the table or the numbers, the protocol that produced them, the baseline
  and the claim drawn from them;
- for a methodology question: the objective, the constraints, the data, the alternatives already
  considered;
- for a plan, a review or a set of responses: the underlying passages the flags are about, not only
  the flags (a flag without its text cannot be judged);
- the evidence file and a precise `--topic`.

A digest of the work is a LAST resort and is declared as such in the Log. When the object plus its
context is too large for a reviewer, split along the work's own seams and REPEAT the shared context
in every part; ask each part in a way that lets the answer disagree. Pass `--round2-include-draft`
when the rebuttal depends on that context, which is the normal case for a research question, a
methodology or a result.
