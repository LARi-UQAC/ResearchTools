---
executor: local-coder
tier: standard
bounds:
  max_rounds: 3
  max_tokens: 1500000
  plateau: 2
---

# Plan 4a - Batch statistics and the loop counter

> **For agentic workers:** run by the local coder model through the driver (rule R39). Return every
> file you create in full. The test file runs as a script (`unittest.main()` at its end) and puts the
> parent folder of its own folder at the start of `sys.path`, then imports the module under test.

**Goal:** a script decides, from totals only, whether the batch sits in the calibration band and how
many loops remain, writes the grade table and the numeric part of the batch report, and never prints a
comment.

**Spec:** `spec.md` D4, D5, "Data shapes", "Working folder".

## Global Constraints

Sample standard deviation (n minus 1). Every threshold comes from the calibration targets file or the
configuration (R0), never from a literal. Outputs carry report ids only (R34): no comment text, no
file name. Fictitious data in tests. Python standard library only. Every function carries the
Purpose, Inputs and Outputs header.

## Review Focus

- A batch of one report: the sd is undefined, the verdict is `insufficient`.
- An incomplete report (`complete` false): excluded from the statistics and listed, never a zero.
- A third loop requested with the state at 2 and no flag: refused.

---

### Task 1: the module and its tests

**Files:**
- Create: `.claude/skills/work-ugs-audit/scripts/batch_stats.py`
- Test: `.claude/skills/work-ugs-audit/scripts/Test/test_batch_stats.py`

**Reads, do not modify:** `.claude/skills/work-ugs-audit/scripts/ugs_config.py` (its `load(path)`
returns a flat dict of dotted keys, here `batch.outlier_z`, and `default_path()` names the file),
`.claude/skills/work-ugs-audit/assets/calibration_targets.json` (per assessment type `lab_report` and
`project_report`, each key a `{value, provenance}` pair: `target_mean`, `target_sd`, `mean_tolerance`,
`sd_tolerance`, `max_loops`), `.claude/skills/work-ugs-audit/assets/grade_sheet.template.csv` (its first
line shows the shape of the grade table header).

**Interfaces:**
- `analyze(totals: list[dict], targets: dict, outlier_z: float) -> dict`. Each total is the dict of
  the totals module: `report_id`, `percent` (float or None), `complete` (bool). Returns `n`, `mean`,
  `sd`, `mean_band` and `sd_band` (two numbers each: target minus and plus tolerance), `verdict`
  (`in_band`, `out_of_band` or `insufficient`), `reasons` (which band was left and by how much),
  `outliers` (ids whose absolute z-score exceeds `outlier_z`), `excluded` (ids of incomplete reports).
  `targets` is the block of one assessment type with the `value` fields already read.
- `next_loop(state_path: Path, max_loops: int, allow_third: bool) -> int`: creates the state file at
  loop 1, then adds 1 on each call; past `max_loops` it raises `LoopLimit` (a `RuntimeError`) unless
  `allow_third` is true.
- `write_grades_csv(totals: list[dict], rubric: dict, path: Path) -> None`: header is `report_id`, then
  each rubric item id in order, then `total`, `percent`, `complete`; one row per report, item scores
  taken from `by_item`.
- `render_report(values: dict, template_text: str) -> str`: fills a `string.Template` with the keys
  `loop`, `assessment_type`, `n`, `mean`, `mean_band`, `sd`, `sd_band`, `verdict`, `reasons`,
  `outlier_z`, `outliers`, `excluded`; a missing key raises, never a blank.
- `main(argv)`: `--work DIR --loop N --type T [--allow-third] [--next-loop] [--json]`. It reads
  the file named `totals` (extension `.json`, one totals dict) of each report folder `R*` inside the
  loop folder `loop-N`, and the file named `rubric` (extension `.json`) in the work folder, then the
  targets file of the skill. It writes the file named `grades` (extension `.csv`) and the file named
  `batch_report` (extension `.md`) in the loop folder, and prints ONE JSON line with the verdict, counts
  and bands, never a comment. With `--next-loop` it only calls `next_loop` on the file named
  `loop_state` (extension `.json`) of the work folder and prints the new number. Exit 0 in band, 3 out of band, 2 refusal
  (bad type, missing file, loop limit), 1 failure. Every path is resolved inside the work folder.

**Tests to write first, each failing before the code exists:**
`test_mean_and_sample_sd_on_a_known_batch`; `test_in_band_batch` (mean 88, sd 4);
`test_mean_below_83_is_out_of_band_with_reason`; `test_sd_above_6_is_out_of_band_with_reason`;
`test_sd_below_2_is_out_of_band` (everyone at 90); `test_one_report_is_insufficient`;
`test_incomplete_report_is_excluded_and_listed`; `test_outlier_uses_the_given_z`;
`test_loop_counter_refuses_a_third_loop_without_the_flag`;
`test_loop_counter_allows_it_with_the_flag`; `test_grades_csv_header_and_rows`;
`test_render_report_raises_on_a_missing_key`; `test_stdout_line_holds_no_comment_text` (a marker
sentence in the inputs never appears); `test_cli_exit_codes` (0, 3, 2);
`test_cli_refuses_a_work_path_that_escapes_the_work_folder`.

- Test: `.claude/skills/work-ugs-audit/scripts/Test/test_batch_stats.py`

- [ ] Step 1: write the tests, run the file, they fail (module absent).
- [ ] Step 2: write the module, run the file, every test passes.
