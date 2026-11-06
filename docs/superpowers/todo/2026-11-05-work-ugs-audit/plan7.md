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

**Files (all written 2026-11-06 by the session):**
- `.claude/skills/scholar-evaluation/references/undergraduate_framework.md` and a paragraph in its `SKILL.md`
- `.claude/skills/work-ugs-audit/prompts/`: `levels.md`, `rubric_normalize.md`, `grade_item.md`,
  `audit_item.md`, `language.md`, `calibration_note.md`, `vision_probe.md`, `schemas.json`
- `.claude/skills/figure-review/prompts/figure.md` (sections `## single` and `## set`)
- `.claude/skills/work-ugs-audit/assets/`: `spec.template.md`, `progress.template.md`

**Interfaces (plan 8 fills exactly these slots; a slot not listed here does not exist):**
- `levels.md`: no slot, loaded as the levels text. `rubric_normalize.md`: `{{RUBRIC_TEXT}}`,
  `{{ASSESSMENT_TYPE}}`. `grade_item.md`: `{{LEVELS}}`, `{{ITEM}}`, `{{SECTIONS}}`, `{{CALIBRATION_NOTE}}`,
  `{{LANGUAGE_OF_REPORT}}`. `audit_item.md`: `{{ITEM}}`, `{{GRADE_RECORD}}`, `{{EVIDENCE_PAGES}}`.
  `language.md`: `{{LANGUAGE_TABLE}}`, `{{SECTION}}`, `{{LANGUAGE_OF_REPORT}}`. `calibration_note.md`: `{{LOOP}}`,
  `{{MEAN}}`, `{{MEAN_BAND}}`, `{{SD}}`, `{{SD_BAND}}`, `{{VERDICT}}`, `{{REASONS}}`. `vision_probe.md`: none.
- `figure.md` `## single`: `{{CAPTION}}`, `{{CITING_TEXT}}`, `{{SCRIPT_VERDICTS}}`, `{{CRITERIA}}`; `## set`:
  `{{FIGURE_COUNT}}`, `{{CRITERION}}`. The figure kind is NOT a slot: it is not known before the model
  looks (decision of 2026-11-06): the model names it, and the driver forces `not_applicable` on any
  criterion that does not apply to that kind (plan 8h).
- `schemas.json` keys: `rubric`, `grade_item`, `audit_item`, `language`, `figure`, `figure_set`,
  `vision_probe`. `spec.template.md` slots: `{{ASSESSMENT_TYPE}}`, `{{TOTAL_POINTS}}`, `{{ITEMS}}`.

- [x] **Step 1: Write `undergraduate_framework.md`** and add one paragraph to `scholar-evaluation/SKILL.md`
  pointing to it for undergraduate work (research framework unchanged).
- [x] **Step 2: Write the five prompts and `schemas.json`.** Validate `schemas.json` parses and that each
  schema's required keys match `spec.md` (check by a one-off read in the scratchpad, not a new script).
- [!] **Step 3 (not run: roles ugs-grader, ugs-auditor, ugs-vision are not adopted yet; the owner adopts them before the real lot): Dry check on fictitious input:** fill `grade_item.md` by hand with a fictitious item and a
  fictitious page; send it once through `ollama_bridge.py --role ugs-grader --no-vault-context` if the
  role is adopted, else record `[!] role not adopted` in `progress.md` and continue (plan 8 tests fake
  the bridge). Never use a real report here.
- [x] **Step 4: Write the two templates.**
- [x] **Step 5: Commit:** `feat(work-ugs-audit): undergraduate framework and local prompts (#104)`.
