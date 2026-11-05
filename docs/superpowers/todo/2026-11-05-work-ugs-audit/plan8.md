---
executor: local-coder
tier: standard
bounds:
  max_rounds: 3
  max_tokens: 1500000
  plateau: 2
---

# Plan 8 - The local grading driver

> **For agentic workers:** dispatched to `local-coder` with a `PLAN:` line naming this file. Tests are
> the oracle; tick `progress.md`. No audit inside the wrapper (R38).

**Goal:** One resumable driver runs prepare, grade, language, figures, audit, assemble and batch on local
models only, keeps `progress.md`, and prints status lines that never carry report text.

**Architecture:** `ollama_bridge.build_payload` gains an optional `images` list (omitted when None, so
every existing request stays byte-identical, like `fmt`). `ugs_bridge.py` is the only module that talks
to Ollama, following `obsidian-cli/scripts/daemon_states.py`: resolve the role's tag and window, refuse a
prompt over budget, post with a JSON schema. `ugs_steps.py` holds one function per step; `ugs_driver.py`
is the CLI and the ledger. `vision_probe.py` decides whether a role may judge figures.

**Tech Stack:** Python 3.11 standard library plus the scripts of plans 3 to 6, `unittest`.

**Spec:** `spec.md` D2 to D8, "Data shapes", "Model roles"; plan 7 placeholders and `schemas.json`.

## Global Constraints

`spec.md` "Constraints". No cloud call, no fallback tag (R8). A prompt over the role window is never
truncated: the item is graded on the pages whose Markdown headings match the item, and if that still
does not fit the item is `not_run` with the reason and `[!]` in `progress.md`. Tests inject a fake bridge
(R21); no test reads `local-model-state.json`.

## Review Focus

- Prepare run twice: no duplicate ledger sections, ids stable.
- The grader returns JSON that does not match the schema, or a score above the maximum: the item is
  retried once, then `not_run` with the reason, never accepted.
- The auditor disagrees twice: the item keeps the grader's record, `flag` true, `[!]` in the ledger.
- Ollama down mid-batch: the current step is `not_run`, the run stops with exit 1, and `--resume`
  continues from the first open mark.
- A report text containing a marker sentence: the marker never appears on stdout or in `progress.md`.

---

### Task 1: bridge `images` parameter and `ugs_bridge.py`

**Files:**
- Modify: `.claude/skills/loop-engineer/scripts/ollama_bridge.py`
- Modify: `.claude/skills/loop-engineer/scripts/Test/test_ollama_bridge.py`
- Create: `.claude/skills/work-ugs-audit/scripts/ugs_bridge.py`
- Test: `.claude/skills/work-ugs-audit/scripts/Test/test_ugs_bridge.py`

**Interfaces:**
- Produces:
  - `build_payload(..., fmt=None, images: list[str] | None = None)`: base64 strings placed in the body's
    `images` field only when given.
  - `ugs_bridge.call(role: str, prompt: str, schema: dict, images: list[Path] | None = None, *, post=None,
    resolve=None, window=None, timeout: float) -> dict`: returns the parsed JSON answer; raises
    `NotRun(RuntimeError)` with a reason for: role not adopted, prompt over budget, daemon unreachable,
    unparsable answer. `post`, `resolve`, `window` default to the bridge's own functions and are injected
    in tests.
- [ ] **Step 1: Failing tests:** `test_payload_without_images_is_byte_identical` and
  `test_payload_with_images_carries_base64` (bridge suite); `test_call_returns_parsed_json`;
  `test_over_budget_prompt_is_not_run_and_never_sent`; `test_unparsable_answer_is_not_run_with_reason`;
  `test_unadopted_role_is_not_run`.
- [ ] **Step 2: Run** both suites. Expected: FAIL. **Step 3:** implement. **Step 4: Run.** Expected: OK.
- [ ] **Step 5: Commit:** `feat(work-ugs-audit): local bridge adapter with image input (#104)`.

### Task 2: `ugs_steps.py` and `ugs_driver.py`

**Files:**
- Create: `.claude/skills/work-ugs-audit/scripts/ugs_steps.py`
- Create: `.claude/skills/work-ugs-audit/scripts/ugs_driver.py`
- Test: `.claude/skills/work-ugs-audit/scripts/Test/test_ugs_driver.py`

**Interfaces:**
- Consumes: plans 3 to 7 (`ugs_config`, `rubric_check`, `grade_total`, `batch_stats`, `ref_check`,
  `report_prepare`, `figure_extract`, `pdf_annotate`, `pdf_annex`, the prompts and `schemas.json`);
  `ugs_bridge.call`.
- Produces:
  - `ugs_steps`: `fill(template: str, values: dict) -> str` (raises on an unfilled or unknown
    placeholder); `select_pages(item: dict, pages: list[str], window_tokens: int) -> list[int]`;
    `normalize_rubric(work, rubric_text, assessment_type, call)`; `grade_report(work, rid, loop, call,
    calibration_note)`; `language_report(work, rid, loop, call)`; `figures_report(work, rid, loop, call,
    vision_ok: bool)` (runs `figure_extract`, then `figure_checks`, then one fresh call per figure with the
    model-judged criteria of `figure_criteria.json` that apply to its kind; a failed criterion becomes a
    `figure` annotation whose text is that criterion's `comment_fr` or `comment_en` plus the model's
    reason); `audit_report(work, rid, loop, call, retries)`; `assemble_report(work, rid, loop,
    reports_dir)` (writes `annotations.json`, runs `ref_check` on the reference section found by heading
    `Références`, `References` or `Bibliographie`, then `pdf_annotate` into `loop-<n>/R01/annotated.pdf`
    and `pdf_annex`); `extract_references(pages: list[str]) -> list[str]`.
  - `ugs_driver.main(argv)`: subcommands `prepare --reports DIR --rubric FILE --type T`,
    `run --work DIR [--loop N] [--resume]` (grade, language, figures, audit, assemble per report),
    `batch --work DIR --loop N [--allow-third]`, `status --work DIR`; `--dry-run` everywhere (R16),
    `--json`. Every stdout line is JSON with only `report_id`, `step`, `status`, counts and numbers (R17).
    Ledger lines follow `progress.template.md`. Exit 0 done, 3 batch out of band, 2 refusal, 1 failure.
- [ ] **Step 1: Failing tests** (fake `call` returning schema-valid answers; fixture PDFs from plan 5):
  `test_prepare_writes_ids_rubric_spec_and_ledger`; `test_prepare_twice_adds_no_duplicate_section`;
  `test_every_prompt_placeholder_is_filled_and_none_is_unknown`;
  `test_large_report_grades_an_item_on_matching_pages_only`;
  `test_item_that_still_does_not_fit_is_not_run_and_flagged`;
  `test_invalid_grader_answer_is_retried_once_then_not_run`;
  `test_audit_disagreement_regrades_once_then_flags`;
  `test_figures_are_not_run_when_vision_is_not_ok`;
  `test_only_applicable_criteria_are_sent_and_an_unknown_id_in_the_answer_is_rejected`;
  `test_a_failed_figure_criterion_becomes_an_annotation_with_its_template_comment`;
  `test_assemble_writes_annotated_copy_and_annex_and_leaves_original_unchanged`;
  `test_resume_continues_from_the_first_open_mark` (fake call raising `NotRun` midway);
  `test_marker_sentence_never_reaches_stdout_or_progress` (fake call echoes prompt text into comments);
  `test_batch_out_of_band_exits_3_and_second_loop_gets_the_calibration_note`;
  `test_dry_run_writes_nothing`.
- [ ] **Step 2: Run.** Expected: FAIL. **Step 3:** implement. **Step 4: Run.** Expected: all OK.
- [ ] **Step 5: Commit:** `feat(work-ugs-audit): resumable local grading driver (#104)`.

### Task 3: `vision_probe.py`

**Files:**
- Create: `.claude/skills/work-ugs-audit/scripts/vision_probe.py`
- Test: `.claude/skills/work-ugs-audit/scripts/Test/test_vision_probe.py`
- Modify: `.claude/rules/testing.md`

**Interfaces:**
- Produces: `probe(role: str, call, image: Path, expected: dict) -> dict` with `role`, `ok`, `answers`;
  the fixture chart (made by `_pdf_fixtures`) has a known axis title, unit and curve count, and `ok` is
  true only when all three come back. `main(argv)`: `--role R --work DIR`, writes `vision_probe.json`
  in the work folder, which `figures_report` reads.
- [ ] **Step 1: Failing tests:** `test_probe_passes_when_the_three_facts_come_back`;
  `test_probe_fails_on_a_wrong_axis_title`; `test_probe_is_not_ok_when_the_call_is_not_run`.
- [ ] **Step 2: Run.** Expected: FAIL. **Step 3:** implement. **Step 4: Run.** Expected: OK.
- [ ] **Step 5: Add** the four script lines to `.claude/rules/testing.md`, tick `progress.md`.
- [ ] **Step 6: Commit:** `feat(work-ugs-audit): vision capability probe (#104)`.
