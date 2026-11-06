---
executor: local-coder
tier: standard
bounds:
  max_rounds: 3
  max_tokens: 1500000
  plateau: 2
---

# Plan 8e - Grading one item at a time

> **For agentic workers:** run by the local coder model through the driver (rule R39). Return every
> file you create in full. The test file runs as a script (`unittest.main()` at its end) and puts the
> parent folder of its own folder at the start of `sys.path`, then imports the module under test.

**Goal:** the rubric is normalized by the grader model, and each rubric item of a report is graded in
its own fresh call on the pages that fit, with a wrong or unsupported answer retried once and never
accepted.

**Spec:** `spec.md` D3, D4, D15, "Data shapes" (the grade record), "Driver contracts".

## Global Constraints

Local models only (D2). The `call` is injected (R21). No report text is written anywhere by this
module: a refusal reason is one of our own short codes or messages. A prompt over the window is never
truncated (R8). Every function carries the Purpose, Inputs and Outputs header, and Raises when it raises
on purpose.

## Review Focus

- A score above the item maximum, a missing evidence list for a score under the maximum, or an evidence
  quote that is not in the named page: the answer is refused and the call repeated once with the reason
  added to the calibration note; after the retries the item is `not_run`, never accepted.
- A large report: the item is graded on the pages whose headings match; if none fits, `not_run` with
  reason `no_fit`.
- A daemon that is down propagates; it is not turned into a `not_run` item.

---

### Task 1: the module and its tests

**Files:**
- Create: `.claude/skills/work-ugs-audit/scripts/ugs_grade.py`
- Test: `.claude/skills/work-ugs-audit/scripts/Test/test_ugs_grade.py`

**Reads, do not modify:** `.claude/skills/work-ugs-audit/scripts/ugs_text.py` (`StepContext`, `fill`,
`page_blocks`, `select_pages`), `.claude/skills/work-ugs-audit/scripts/ugs_bridge.py` (`NotRun` with `kind`
and `retryable`), `.claude/skills/work-ugs-audit/scripts/rubric_check.py` (`validate(rubric)` raises
`RubricError`), `.claude/skills/work-ugs-audit/scripts/pdf_annotate.py` (`normalize(text)`).
The prompt slots are in "Driver contracts" of the spec and in the prompt files: `grade_item` has
`LEVELS`, `ITEM`, `SECTIONS`, `CALIBRATION_NOTE`, `LANGUAGE_OF_REPORT`; `rubric_normalize` has
`RUBRIC_TEXT`, `ASSESSMENT_TYPE`. Prompts and schemas come from the context: `ctx.prompts["grade_item"]`,
`ctx.schemas["grade_item"]`, `ctx.prompts["rubric_normalize"]`, `ctx.schemas["rubric"]`.

**Interfaces:**
- `normalize_rubric(rubric_text: str, assessment_type: str, call, ctx) -> dict`: one grader call; the
  answer must pass `rubric_check.validate`. A refused answer is retried `ctx.grade_retries` times, then
  `NotRun("invalid", ...)` is raised. An unretryable `NotRun` propagates.
- `grade_item(item: dict, pages: list[str], call, ctx, language: str, calibration_note: str) -> dict`:
  returns `{item_id, status, score, comment, evidence, audit: "not_run", flag: False}`. The pages sent
  are all of them when `page_blocks` of all pages fits `ctx.window_tokens - ctx.reserve_tokens - overhead`
  (overhead: the token count of the filled prompt with empty sections), else `select_pages`; an empty
  selection gives a `not_run` record with comment `no_fit` and flag true. An answer is accepted when its
  status is `rated` or `not_applicable`; a rated score is between 0 and `max_points`; a not applicable
  score is null; a rated score under the maximum has at least one evidence entry; each evidence quote is
  found, after `normalize`, in the text of its page. Otherwise the call is repeated up to
  `ctx.grade_retries` more times with a line naming the refusal added to `calibration_note`; a retryable
  `NotRun` is handled the same way; `over_budget` gives a `not_run` record with comment `over_budget`;
  other kinds propagate. After the retries the record is `not_run`, score None, comment `invalid_answer`,
  flag true.
- `grade_report(rubric: dict, pages: list[str], report_id: str, loop: int, call, ctx, language: str,
  calibration_note: str, existing: dict | None = None, on_item=None) -> dict`: grades every item in
  rubric order and returns `{report_id, loop, items}`. Items already in `existing` (a partial record) are
  kept and not graded again. After each new item it calls `on_item(item_id, record)` when given.

**Tests to write first, each failing before the code exists** (a fake `call` returning scripted answers
and recording the prompts):
`test_normalize_rubric_returns_a_valid_rubric`; `test_normalize_rubric_retries_an_invalid_answer_then_raises`;
`test_a_rated_item_is_recorded_with_its_evidence`; `test_not_applicable_has_a_null_score`;
`test_score_above_max_is_refused_and_retried_once_with_the_reason`;
`test_low_score_without_evidence_is_refused`; `test_quote_absent_from_its_page_is_refused`;
`test_a_quote_split_across_a_line_break_is_accepted` (the page text has the break, the quote does not);
`test_invalid_after_retries_is_not_run_and_flagged`; `test_large_report_is_graded_on_matching_pages_only`;
`test_item_that_still_does_not_fit_is_not_run_with_no_fit`; `test_over_budget_is_not_run`;
`test_unreachable_propagates`; `test_grade_report_skips_items_in_existing`;
`test_on_item_is_called_once_per_new_item`; `test_calibration_note_reaches_the_prompt`.

- Test: `.claude/skills/work-ugs-audit/scripts/Test/test_ugs_grade.py`

- [ ] Step 1: write the tests, run the file, they fail (module absent).
- [ ] Step 2: write the module, run the file, every test passes.
