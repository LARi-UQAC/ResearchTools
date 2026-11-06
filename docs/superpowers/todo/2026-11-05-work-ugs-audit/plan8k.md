---
executor: local-coder
tier: standard
bounds:
  max_rounds: 3
  max_tokens: 1500000
  plateau: 2
---

# Plan 8k - The command line of the grading driver

> **For agentic workers:** run by the local coder model through the driver (rule R39). Return every
> file you create in full. The test file runs as a script (`unittest.main()` at its end) and puts the
> parent folder of its own folder, and the folder holding the fixture helper, at the start of
> `sys.path`.

**Goal:** one command prepares a folder of reports, runs the steps for every report, analyses the batch
and reports the status, printing only JSON lines that carry report ids, steps, statuses and numbers.

**Spec:** `spec.md` D2, D3, D5, "Working folder", "Driver contracts" (work folder, exit codes).

## Global Constraints

Local models only (D2). Every threshold, role name and count comes from the configuration (R0), and a
missing key is named (R3). Every path is resolved inside the work folder (R24). `--dry-run` writes
nothing (R16). The wrapper reads only what this command prints and the ledger. In tests the `call`, the
window, the counter and the network are injected; the real ones are built only when none is given. Every
function carries the Purpose, Inputs and Outputs header, and Raises when it raises on purpose.

## Review Focus

- The marker sentence of a report never reaches stdout, the ledger or the batch files.
- An out-of-band batch exits 3, opens the next loop, and the next loop's grader prompt carries the
  calibration note; a third loop is refused without `--allow-third`.
- `prepare` twice adds no section; `run --resume` after an unreachable daemon continues where it stopped.

---

### Task 1: the module and its tests

**Files:**
- Create: `.claude/skills/work-ugs-audit/scripts/ugs_driver.py`
- Test: `.claude/skills/work-ugs-audit/scripts/Test/test_ugs_driver.py`

**Reads, do not modify:** `.claude/skills/work-ugs-audit/scripts/ugs_config.py` (`load`, `default_path`,
`annotation_author`), `.claude/skills/work-ugs-audit/scripts/report_prepare.py` (`prepare(reports_dir,
work_dir)`), `.claude/skills/work-ugs-audit/scripts/rubric_check.py` (`validate`),
`.claude/skills/work-ugs-audit/scripts/batch_stats.py` (`main(argv)` with `--work --loop --type
[--allow-third] [--next-loop] [--json]`, one JSON line on stdout, exit 3 out of band, `LoopLimit`),
`.claude/skills/work-ugs-audit/scripts/ugs_run.py` (`run_report`),
`.claude/skills/work-ugs-audit/scripts/ugs_ledger.py`, `.claude/skills/work-ugs-audit/scripts/ugs_text.py`,
`.claude/skills/work-ugs-audit/scripts/ugs_grade.py` (`normalize_rubric`),
`.claude/skills/work-ugs-audit/scripts/ugs_language.py` (`load_table`),
`.claude/skills/work-ugs-audit/scripts/ugs_bridge.py` (`call`, `OllamaDeps`, `NotRun`),
`.claude/skills/work-ugs-audit/assets/ugs_config.json`, `.claude/skills/work-ugs-audit/assets/rubric.schema.json`,
`.claude/skills/loop-engineer/scripts/driver_deps.py` (`BridgeDeps(root).count(text)`),
`.claude/skills/figure-review/scripts/Test/_pdf_fixtures.py`.

**Interfaces:**
- `main(argv=None, *, call=None, fetch=None, window=None, count=None) -> int`. With `call` given,
  `window` and `count` must be given too (tests); otherwise the real ones are built from the
  configuration, the resolver and `BridgeDeps`; the real `call(kind, prompt, schema, images)` maps the
  kind to its role name, passes the reserve, the timeout, `driver.max_image_bytes` and the image cost
  (the `image_tokens` of the probe verdict file in the work folder, else `driver.image_tokens_fallback`)
  to `ugs_bridge.call`. Required configuration keys: `roles.grader`,
  `roles.auditor`, `roles.vision`, `driver.reply_reserve_tokens`, `driver.request_timeout_s`,
  `driver.audit_retries`, `driver.max_image_bytes`, `driver.image_tokens_fallback`,
  `grade.invalid_answer_retries`, `select.min_word_len`, `references.quote_chars`,
  `references.url_timeout_s`, `references.max_retries`, `batch.outlier_z`, `annotation.colors`; one
  missing is exit 2 naming it. Subcommands, all with `--dry-run` and `--json`:
  - `prepare --reports DIR --rubric FILE --type T [--work DIR]`: work folder defaults to `_correction`
    inside the reports folder. Runs `report_prepare.prepare`; reads the rubric file (JSON is validated and
    used as it is; text, Markdown or PDF text goes through `normalize_rubric`; any other extension is a
    refusal that says to convert it); writes the JSON file `rubric`, `spec.md` (the spec template filled through `ugs_text.fill` with the
    slots `ASSESSMENT_TYPE`, `TOTAL_POINTS` and `ITEMS`, the last being one `## I01 - title (points)`
    section per item with its criteria and checklist lines) and the ledger with `add_report` for every report, and the JSON file `loop_state` is not
    touched. Prints one line per report with `report_id`, `pages`, `step` `prepare`, `status` `done`.
  - `run --work DIR [--loop N] [--resume] [--only R01]`: the reports folder is the parent of the work
    folder. For each report in id order, runs `run_report`; the source file name comes from the JSON file `ids`.
    The prompts are those of the skill's `prompts` folder and of the figure-review `prompts` folder
    (`load_prompts` on each, merged), the levels text being the prompt named `levels`; the schemas are
    the skill's schemas file. The calibration note is empty on loop 1 and, after, is the
    `calibration_note` prompt filled with `LOOP`, `MEAN`, `MEAN_BAND`, `SD`, `SD_BAND`, `VERDICT` and
    `REASONS` taken from the previous loop's the JSON file `batch` (a band written as `83 to 93`, the reasons
    joined by a semicolon). Prints one line per report: `report_id`, `status`, and the counts
    of done and blocked steps. A refused loop number (not the current loop) is exit 2. An unretryable
    `NotRun` stops the run: a line with `step`, `status` `not_run` and the kind, exit 1.
  - `batch --work DIR --loop N [--allow-third]`: runs `batch_stats.main` for the loop, stores its JSON
    line as the JSON file `loop-N/batch`, prints it; when out of band and a further loop is allowed, advances
    the JSON file `loop_state` through `batch_stats`, reopens every ledger line except `prepare` with
    `reopen_all`, adds a ledger note `loop <n> opened`, and exits 3; a refused third loop is exit 2.
  - `status --work DIR`: prints the ledger counts and the first open line as one line.
  Every printed line is a JSON object whose values are ids, step labels, statuses, kinds and numbers.

**Tests to write first, each failing before the code exists** (fixture PDFs, a fake `call` answering
valid shapes by kind, a fake `fetch`, `window` and `count` injected, an invented author in a temporary
profile or an injected `author`):
`test_prepare_writes_ids_rubric_spec_and_ledger`; `test_prepare_twice_adds_no_duplicate_section`;
`test_prepare_json_rubric_is_validated_and_not_sent_to_the_model`; `test_unsupported_rubric_extension_is_a_refusal`;
`test_missing_configuration_key_is_named_and_exit_2`; `test_run_grades_every_report_and_prints_json_lines_only`;
`test_run_twice_makes_no_second_model_call`; `test_unreachable_daemon_stops_with_exit_1_and_resume_continues`;
`test_marker_sentence_never_reaches_stdout_ledger_or_batch_files`;
`test_batch_in_band_exits_0_and_writes_batch_json`;
`test_batch_out_of_band_exits_3_reopens_the_ledger_and_loop_two_prompt_has_the_note`;
`test_third_loop_is_refused_without_the_flag_and_allowed_with_it`; `test_status_line`;
`test_dry_run_writes_nothing_for_every_subcommand`; `test_work_path_outside_the_reports_folder_is_refused`;
`test_a_loop_number_other_than_the_current_one_is_refused`.

- Test: `.claude/skills/work-ugs-audit/scripts/Test/test_ugs_driver.py`

- [ ] Step 1: write the tests, run the file, they fail (module absent).
- [ ] Step 2: write the module, run the file, every test passes.
