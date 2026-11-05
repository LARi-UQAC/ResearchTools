---
executor: cloud
tier: standard
bounds:
  max_rounds: 3
  max_tokens: 1500000
  plateau: 2
---

# Plan 10 - Migrate the four auditors and `/tikz` to `figure-review`

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans (session, judgment work).
> `progress.md` is the ledger.

**Goal:** `paper-auditor`, `thesis-auditor`, `thesis-proposal-auditor`, `scopus-auditor` and `/tikz` stop
carrying their own figure checklists and call `figure-review`, for TikZ, draw.io and other vector figures
as well as bitmaps, with rendering as an option; no behaviour change otherwise.

**Architecture:** Each auditor keeps its figure step and its LaTeX markup rows, but the list of figure
checks is replaced by a reference to `figure_criteria.json` (scope `research` and `both`), the script
checks come from `figure_tex.text_checks`, and visual review uses `figure_render.py --render` when the
caller asks for it. The auditor's cloud model judges the `model` criteria.

**Tech Stack:** Markdown agent definitions, Python `unittest`.

**Spec:** `spec.md` item 4, D12, D13; design section 7.5.

## Global Constraints

`spec.md` "Constraints". Every figure flag an auditor prints today stays reachable with the same text
and LaTeX action (proof as in plan 2). Agent pipeline integrity: no step removed. The rendering option
defaults to off in every auditor; the dispatch prompt or the user turns it on.

## Review Focus

- An auditor that used to look at a PNG directly losing that ability because rendering is off: bitmaps
  are native and are always shown, the option only concerns non-native formats.
- `/tikz` validating code only: it keeps its nine rules as `source` criteria and gains the render option.
- An auditor's report template naming a figure flag the criteria file lacks.

---

### Task 1: four auditors, `/tikz`, contract test

**Files:**
- Modify: `.claude/agents/paper-auditor.md`
- Modify: `.claude/agents/thesis-auditor.md`
- Modify: `.claude/agents/thesis-proposal-auditor.md`
- Modify: `.claude/agents/scopus-auditor.md`
- Modify: `.claude/commands/tikz.md`
- Test: `.claude/hooks/Test/test_figure_review_contract.py`

**Interfaces:**
- Consumes: `figure_criteria.json` (`flag`, `scope`, `needs`), `figure_tex.text_checks`,
  `figure_render.py --render` (plan 9).
- Produces: in each definition, one paragraph naming `figure-review`, the option (render non-native
  figures to PNG, off by default), and the rule that a mixed document is handled figure by figure.

- [ ] **Step 1: Snapshot.** List every figure flag and check in the five files (scratchpad): the "before"
  set. Plan 9 has used this list to fill the research entries; check it is complete.
- [ ] **Step 2: Write the failing test:** `test_each_auditor_and_tikz_point_to_figure_review`;
  `test_each_states_the_render_option_off_by_default`; `test_every_figure_flag_an_auditor_prints_is_in_the_criteria`;
  `test_no_auditor_restates_the_tikz_rule_list`; `test_undergraduate_scope_excludes_research_only_entries`;
  a negative control on fictitious text.
- [ ] **Step 3: Run** `.venv-skills\Scripts\python.exe .claude/hooks/Test/test_figure_review_contract.py`.
  Expected: FAIL.
- [ ] **Step 4: Edit** the four auditors and `/tikz`.
- [ ] **Step 5: Run** the test; the "after" flag set equals the "before" set. Record both counts in
  `progress.md`.
- [ ] **Step 6: Commit:** `refactor(agents): figure checks come from figure-review (#104)`.
