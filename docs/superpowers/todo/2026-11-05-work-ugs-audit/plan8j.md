---
executor: local-coder
tier: standard
bounds:
  max_rounds: 3
  max_tokens: 1500000
  plateau: 2
---

# Plan 8j - Running the steps of one report

> **For agentic workers:** run by the local coder model through the driver (rule R39). Return every
> file you create in full. The test file runs as a script (`unittest.main()` at its end) and puts the
> parent folder of its own folder, and the folder holding the fixture helper, at the start of
> `sys.path`.

**Goal:** one function runs grade, language, figures, audit and assemble for one report in a loop folder,
keeps the ledger as it goes, saves partial results, and resumes from the first open line.

**Spec:** `spec.md` D3, D6, "Driver contracts" (work folder, ledger lines, exit codes).

## Global Constraints

Local models only (D2). The `call` and the network are injected (R21). The ledger receives only labels,
marks and short codes (D2). A step failing on an ordinary error is marked blocked and stops that report
only. A model that cannot run (`NotRun` of an unretryable kind) propagates: the step stays open so a
resume continues there. Every function carries the Purpose, Inputs and Outputs header, and Raises when
it raises on purpose.

## Review Focus

- A run stopped in the middle of the grade step continues at the first item not yet saved.
- A run repeated after success calls the model zero times.
- The marker sentence of a report never reaches the ledger.

---

### Task 1: the module and its tests

**Files:**
- Create: `.claude/skills/work-ugs-audit/scripts/ugs_run.py`
- Test: `.claude/skills/work-ugs-audit/scripts/Test/test_ugs_run.py`

**Reads, do not modify:** `.claude/skills/work-ugs-audit/scripts/ugs_ledger.py` (`read`, `write`,
`set_mark`, `parse`, `add_figures`), `.claude/skills/work-ugs-audit/scripts/ugs_text.py` (`StepContext`,
`read_pages`, `detect_language`), `.claude/skills/work-ugs-audit/scripts/ugs_grade.py` (`grade_report`),
`.claude/skills/work-ugs-audit/scripts/ugs_audit.py` (`audit_report`),
`.claude/skills/work-ugs-audit/scripts/ugs_language.py` (`language_report`),
`.claude/skills/work-ugs-audit/scripts/ugs_figures.py` (`figures_report`),
`.claude/skills/work-ugs-audit/scripts/ugs_assemble.py` (`assemble_report`),
`.claude/skills/work-ugs-audit/scripts/ugs_bridge.py` (`NotRun`),
`.claude/skills/figure-review/scripts/Test/_pdf_fixtures.py`.

**Interfaces:**
- `run_report(work_dir: Path, report_id: str, loop: int, src_pdf: Path, call, ctx, services: dict,
  calibration_note: str, fetch) -> dict`. `services` holds `rubric`, `entries` (language table),
  `criteria_doc`, `hints`, `vision_ok` and `settings` (for `assemble_report`). The ledger is
  `work_dir/progress.md`; the loop folder is `work_dir/loop-N/R01`. Steps in order, each skipped when
  every ledger line of it is already marked done or blocked:
  1. `grade`: `grade_report` with the partial `grade`.json as `existing`; after each item the partial
     file is saved and the line `grade I01` marked `[x]`, or `[!]` with the item's comment code when
     `not_run`.
  2. `language`: `language_report`; writes `language`.json (the annotations list); mark `[x]`, or `[!]`
     with note `pages=<n>` when some page did not run.
  3. `figures`: `figures_report` with the partial `figures`.json as `existing`; once the figures are
     known their ids are added to the ledger with `add_figures`; after each figure its line is marked
     `[x]`, or `[!]` when any model criterion of it is `not_run`; the `figures` line is marked `[x]`
     (or `[!]` when vision was not validated) at the end.
  4. `audit`: `audit_report` on the saved grade, which is rewritten; mark `[x]`, or `[!]` with note
     `flags=<n>` when any item is flagged.
  5. `assemble`: `assemble_report`; mark `[x]` with note `pages=<n>`.
  An ordinary exception inside a step marks that line `[!]` with a note `error=<ExceptionName>`, stops
  the report and returns status `failed`. Returns `{report_id, status, steps}` where status is `done`
  or `failed` and `steps` maps each step to `done`, `blocked` or `skipped`; no text of the report.

**Tests to write first, each failing before the code exists** (fixture PDF and a fake `call` that
answers every kind with a valid answer):
`test_all_five_steps_run_and_the_ledger_is_marked`; `test_second_run_makes_no_model_call`;
`test_resume_continues_at_the_first_item_not_saved` (the fake raises `NotRun` unreachable on item 2);
`test_unreachable_leaves_the_step_open_and_propagates`; `test_not_run_item_is_marked_blocked`;
`test_figure_lines_are_added_and_marked`; `test_flagged_item_blocks_the_audit_line_with_a_count`;
`test_ordinary_error_blocks_the_step_and_stops_the_report`;
`test_loop_two_writes_into_its_own_folder_and_keeps_loop_one`;
`test_marker_sentence_never_reaches_the_ledger` (the fake echoes the prompt into its comments);
`test_returned_summary_holds_no_report_text`.

- Test: `.claude/skills/work-ugs-audit/scripts/Test/test_ugs_run.py`

- [ ] Step 1: write the tests, run the file, they fail (module absent).
- [ ] Step 2: write the module, run the file, every test passes.
