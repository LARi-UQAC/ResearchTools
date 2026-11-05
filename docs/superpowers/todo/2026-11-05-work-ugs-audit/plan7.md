---
executor: cloud
tier: standard
bounds:
  max_rounds: 3
  max_tokens: 1500000
  plateau: 2
---

# Plan 7 - Undergraduate framework, local-model prompts and the ledger templates

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans (session, judgment work: what
> the local models are told decides how severe they are). `progress.md` is the ledger.

**Goal:** The text the local grader, auditor and vision models receive, and the anchored levels that keep
grades near the calibration target, exist as data files the driver of plan 8 fills.

**Architecture:** One Markdown prompt per model call kind, with `{{PLACEHOLDER}}` slots and no student
text. One JSON file of output schemas passed to Ollama's `format` field. The framework lives in
`scholar-evaluation` so other agents can reuse it. Templates for `spec.md` and `progress.md` reproduce
the aider-setup ledger shape.

**Tech Stack:** Markdown, JSON Schema subset accepted by Ollama structured output.

**Spec:** `spec.md` D3, D5, D6, D8, D9, "Data shapes"; design sections 4 (anti-goals) and 7.3.

## Global Constraints

`spec.md` "Constraints". Prompts are written for a mid-size local model: short sentences, the level
anchors stated with numbers, one task per prompt. Severity: "complete and correct" is 88 percent of an
item (D5); points are lost for a missing element or a technical error, never for style alone. Comments
are written in the report's language. Every prompt says that the answer must quote the report verbatim
in `evidence`. No model tag (R2).

## Review Focus

- A grade prompt that lets the model give full marks with no evidence: the schema requires at least one
  evidence entry for a `rated` item with a score below the maximum.
- The audit prompt drifting into re-grading: it returns `agree` or `disagree` with a reason, nothing else.
- The figure prompt judging criteria the script already measured (`space_used_over_70`,
  `effective_resolution` and the four others): it receives the measured verdicts and only explains them.
- A block diagram judged on axes and units: only the criteria whose `applies_to` holds the figure kind
  are sent; the others are `not_applicable`.
- A rubric whose text holds checkboxes `[]` and fractional points (`/0.5`): the normalize prompt keeps
  each section as one item with its checklist lines.

---

### Task 1: framework, prompts, schemas, templates

**Files:**
- Create: `.claude/skills/scholar-evaluation/references/undergraduate_framework.md`
- Modify: `.claude/skills/scholar-evaluation/SKILL.md`
- Create: `.claude/skills/work-ugs-audit/prompts/rubric_normalize.md`
- Create: `.claude/skills/work-ugs-audit/prompts/grade_item.md`
- Create: `.claude/skills/work-ugs-audit/prompts/audit_item.md`
- Create: `.claude/skills/work-ugs-audit/prompts/language.md`
- Create: `.claude/skills/figure-review/prompts/figure.md`
- Create: `.claude/skills/work-ugs-audit/prompts/schemas.json`
- Create: `.claude/skills/work-ugs-audit/assets/spec.template.md`
- Create: `.claude/skills/work-ugs-audit/assets/progress.template.md`

**Interfaces:**
- Produces (plan 8 fills exactly these placeholders; a placeholder not listed here does not exist):
  - `rubric_normalize.md`: `{{RUBRIC_TEXT}}`, `{{ASSESSMENT_TYPE}}`. Answer: `rubric.json` shape.
  - `grade_item.md`: `{{LEVELS}}` (the framework's anchor table), `{{ITEM}}` (one rubric item as JSON),
    `{{SECTIONS}}` (page-tagged Markdown of the relevant pages), `{{CALIBRATION_NOTE}}` (empty on loop 1,
    the batch verdict and reasons from `batch_stats` on later loops), `{{LANGUAGE_OF_REPORT}}`.
  - `audit_item.md`: `{{ITEM}}`, `{{GRADE_RECORD}}`, `{{EVIDENCE_PAGES}}`.
  - `language.md`: `{{LANGUAGE_TABLE}}` (undergraduate-scope entries of `language_categories.json`),
    `{{SECTION}}`, `{{LANGUAGE_OF_REPORT}}`.
  - `figure.md`: `{{CAPTION}}`, `{{CITING_TEXT}}`, `{{FIGURE_KIND}}`, `{{SCRIPT_VERDICTS}}` (the six
    script-measured verdicts with their numbers, to explain, never to overturn), `{{CRITERIA}}` (the
    model-judged entries of `figure_criteria.json` that apply to this kind, with their labels); the image
    travels in the request's `images` field (plan 8), not in the text. The model first names the figure
    kind, then judges each listed criterion. The file has two sections: `## single` (above) and `## set`
    with `{{FIGURE_COUNT}}` and `{{CRITERION}}`, for the per-report style criterion judged on one contact
    sheet image.
  - `schemas.json`: keys `rubric`, `grade_item`, `audit_item`, `language`, `figure`, `figure_set`, each an Ollama
    `format` schema matching `spec.md` "Data shapes" (`language` answers a list of
    `{page, code, quote, proposed, reason}`; `figure` answers `kind` and a list of
    `{id, verdict, reason}` restricted to the ids it was given; the driver rejects any other id;
    `figure_set` answers `{verdict, reason, figures_involved[]}`).
  - `undergraduate_framework.md`: five anchored levels per item as a share of `max_points` (absent 0,
    attempted 0.5, partial 0.75, complete and correct 0.88, exemplary 1.0), when each applies for a
    technical report, and the statuses `rated`, `not_applicable`, `not_run`.
  - `spec.template.md`: header (course code slot, assessment type, total), one `## I01 - title (points)`
    section per item with its criteria and checklist. `progress.template.md`: `## notes` plus one
    `## R01` section with the step lines of `spec.md` D3 and D6 (prepare, items, language, figures F01...,
    audit, assemble), marks `[ ]`, `[x]`, `[!]`.

- [ ] **Step 1: Write `undergraduate_framework.md`** and add one paragraph to `scholar-evaluation/SKILL.md`
  pointing to it for undergraduate work (research framework unchanged).
- [ ] **Step 2: Write the five prompts and `schemas.json`.** Validate `schemas.json` parses and that each
  schema's required keys match `spec.md` (check by a one-off read in the scratchpad, not a new script).
- [ ] **Step 3: Dry check on fictitious input:** fill `grade_item.md` by hand with a fictitious item and a
  fictitious page; send it once through `ollama_bridge.py --role ugs-grader --no-vault-context` if the
  role is adopted, else record `[!] role not adopted` in `progress.md` and continue (plan 8 tests fake
  the bridge). Never use a real report here.
- [ ] **Step 4: Write the two templates.**
- [ ] **Step 5: Commit:** `feat(work-ugs-audit): undergraduate framework and local prompts (#104)`.
