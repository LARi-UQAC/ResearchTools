---
executor: cloud
tier: standard
bounds:
  max_rounds: 3
  max_tokens: 1500000
  plateau: 2
---

# Plan 9 - Skill `figure-review` and the migration of the four auditors

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans (session, judgment work). The
> SKILL.md is authored with superpowers:writing-skills and skill-creator:skill-creator. `progress.md` is
> the ledger.

**Goal:** One figure skill that both the undergraduate grader (PDF, local model) and the research
auditors (LaTeX, cloud model) call; the auditors stop carrying their own figure checklists, with no
behaviour change.

**Architecture:** `figure-review` already holds, from plans 5 to 7, `figure_extract.py`,
`figure_checks.py`, `figure_criteria.json`, `figure_analysis.template.json` and `prompts/figure.md`. This
plan adds the research-scope criteria, a LaTeX reader so the script checks also run on a `.tex`, the
SKILL.md, and points the auditors and `/tikz` to it. The caller's own model judges the `model` criteria.

**Tech Stack:** Python standard library, `unittest`, Markdown definitions.

**Spec:** `spec.md` item 4, D6, D12; design section 7.4 and 7.5.

## Global Constraints

`spec.md` "Constraints". No behaviour change on the research side: every figure check, flag text and
LaTeX action an auditor applies today stays reachable (the same proof as plan 2). `find-skills` was run
on 2026-11-05: no equivalent exists; `how-to-review-figure` (quantumbfs/sci-brain) and
`figure-results-review` (a-green-hand-jack/ml-research-skills) were read for ideas only (R36 part 4), the
`severity` field comes from the first.

## Review Focus

- A research-only criterion (a TikZ rule) sent to the undergraduate grader: excluded by `scope`.
- A `.tex` whose figure is `\input` from another file, or uses `\autoref` or `\cref`: still found.
- A figure referenced only after it appears, in LaTeX: flagged like in a PDF.
- An auditor keeping a figure flag in its report template that the skill no longer defines.

---

### Task 1: research criteria, LaTeX reader, SKILL.md, migration

**Files:**
- Create: `.claude/skills/figure-review/SKILL.md`
- Modify: `.claude/skills/figure-review/assets/figure_criteria.json`
- Create: `.claude/skills/figure-review/scripts/figure_tex.py`
- Test: `.claude/skills/figure-review/scripts/Test/test_figure_tex.py`
- Modify: `.claude/agents/paper-auditor.md`
- Modify: `.claude/agents/thesis-auditor.md`
- Modify: `.claude/agents/thesis-proposal-auditor.md`
- Modify: `.claude/agents/scopus-auditor.md`
- Modify: `.claude/commands/tikz.md`
- Test: `.claude/hooks/Test/test_figure_review_contract.py`

**Interfaces:**
- Consumes: `figure_checks.check`, `load_criteria` (plan 6).
- Produces:
  - `figure_criteria.json` gains `scope: research` entries: the nine TikZ rules of `.claude/CLAUDE.md`
    "Figures" (positioning, arrows over shapes, overlapping arrows, perpendicular arrows, shape spacing,
    label spacing, cited with two sentences, TiKZiT-simple code, `fig:three-words` label) plus every
    research figure check the four auditors apply today that is not already among the 21 (found in step
    1). Each with the same keys as the 21, `flag` holding the auditor's exact bracket text.
  - `figure_tex.figures(tex_text: str) -> list[dict]`: each `figure` environment with `label`,
    `caption`, `includes` (graphic paths or `tikz`), `position` (character offset); `\input` and
    `\include` are followed when a `base_dir` is given.
  - `figure_tex.references(tex_text: str) -> dict`: label to offsets of `\ref`, `\autoref`, `\cref`.
  - `figure_tex.text_checks(tex_text: str, criteria_doc: dict) -> list[dict]`: verdicts for
    `numbered_in_sequence`, `called_before_appearing` and the label-form rule, same record shape as
    `figure_checks.check`.
  - `main(argv)`: `--tex FILE [--base-dir DIR] [--json]`; exit 0, 1 findings, 2 refusal.

- [ ] **Step 1: Inventory.** List, in the scratchpad, every figure check and flag of the four auditors and
  of `/tikz`, and mark which ones already map to one of the 21 criteria. That list is the "before" set.
- [ ] **Step 2: Write the failing tests.** `test_figure_tex.py`: `test_figures_and_captions_found`;
  `test_input_files_are_followed`; `test_ref_autoref_cref_all_count`; `test_figure_cited_after_it_appears_fails`;
  `test_label_not_three_words_fails`; `test_criteria_file_now_has_research_entries_with_flags`.
  `test_figure_review_contract.py`: `test_each_auditor_and_tikz_point_to_figure_review`;
  `test_every_figure_flag_an_auditor_prints_is_in_the_criteria`; `test_no_auditor_restates_the_tikz_rule_list`;
  `test_undergraduate_scope_excludes_research_only_entries`; a negative control on fictitious text.
- [ ] **Step 3: Run** both with `.venv-skills\Scripts\python.exe`. Expected: FAIL.
- [ ] **Step 4: Implement** `figure_tex.py`, extend `figure_criteria.json`, write `SKILL.md` (first
  sentence: figure review, graphiques, axes, unités, légende, résolution, TikZ, PDF and LaTeX), edit the
  four auditors and `/tikz` to point to the skill, keeping each pipeline step.
- [ ] **Step 5: Run** both. Expected: OK, and the auditors' flag sets before and after are equal (record
  both counts in `progress.md`). The `figure_tex.py` inventory line goes into `.claude/rules/testing.md`
  in plan 11, task 1.
- [ ] **Step 6: Commit:** `feat(figure-review): one figure skill for PDF and LaTeX, auditors migrated (#104)`.
