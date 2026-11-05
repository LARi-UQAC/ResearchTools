---
executor: local-coder
tier: standard
bounds:
  max_rounds: 3
  max_tokens: 1500000
  plateau: 2
---

# Plan 4 - Batch statistics with the loop counter, and the reference check

> **For agentic workers:** dispatched to `local-coder` with a `PLAN:` line naming this file. Tests are
> the oracle; tick `progress.md`. No audit inside the wrapper (R38).

**Goal:** A script decides, from totals only, whether the batch sits in the calibration band and how many
loops remain; another reports each reference's status without ever moving a score.

**Architecture:** `batch_stats.py` reads `grade_total` outputs and `calibration_targets.json`, writes
`grades.csv` and the numeric part of `batch_report.md`, and owns `loop_state.json`. `ref_check.py`
classifies references with patterns held as data and fetches URLs through an injected function.

**Tech Stack:** Python standard library (`statistics`, `csv`, `re`, `urllib.request`), `unittest`.

**Spec:** `spec.md` D4, D5, D8, "Data shapes"; plan 3 interfaces.

## Global Constraints

`spec.md` "Constraints". Sample standard deviation (`statistics.stdev`, n minus 1). Thresholds from JSON
(R0). No network call in tests: the fetch function is injected (R21). Outputs carry report ids only.

## Review Focus

- A batch of one report: the sd is undefined; the verdict is `insufficient`, not in or out of band.
- A batch with an incomplete report (`complete` false): excluded from statistics and listed, never
  counted as zero.
- A third loop requested with `loop_state.json` already at 2 and no `--allow-third`: refused.
- A URL that times out or answers 403: `unreachable` or `blocked`, never an exception.
- A standard written `ISO9001:2015`, `ISO 9001`, `CSA C22.1-21`, `CAN/CSA-Z462`: classified as standards.

---

### Task 1: `batch_stats.py`

**Files:**
- Create: `.claude/skills/work-ugs-audit/assets/calibration_targets.json`
- Create: `.claude/skills/work-ugs-audit/assets/grade_sheet.template.csv`
- Create: `.claude/skills/work-ugs-audit/assets/batch_report.template.md`
- Create: `.claude/skills/work-ugs-audit/scripts/batch_stats.py`
- Test: `.claude/skills/work-ugs-audit/scripts/Test/test_batch_stats.py`

**Interfaces:**
- Consumes: `ugs_config.load` (plan 3, for `batch.outlier_z`), the dict returned by `grade_total.compute`.
- Produces:
  - `calibration_targets.json`: per type `lab_report` and `project_report`, `{value, provenance}` for
    `target_mean` 88, `target_sd` 4, `mean_tolerance` 5, `sd_tolerance` 2, `max_loops` 2; provenance
    "owner 2026-11-05".
  - `analyze(totals: list[dict], targets: dict, outlier_z: float) -> dict` with `n`, `mean`, `sd`,
    `mean_band` `[83, 93]`, `sd_band` `[2, 6]`, `verdict` (`in_band`, `out_of_band`, `insufficient`),
    `reasons` (which band was left and by how much), `outliers` (ids with absolute z over `outlier_z`),
    `excluded` (incomplete ids).
  - `next_loop(state_path: Path, max_loops: int, allow_third: bool) -> int`: creates the state at 1,
    increments, raises `LoopLimit(RuntimeError)` past `max_loops` unless `allow_third`.
  - `write_grades_csv(totals, rubric, path)` with header `report_id,` plus each item id, `total,percent,complete`.
  - `main(argv)`: `--work DIR --loop N --type T [--allow-third] [--json]`; prints one JSON line with the
    verdict, counts and band, never a comment text. Exit 0 in band, 3 out of band, 2 refusal, 1 failure.

- [ ] **Step 1: Write the failing tests:** `test_mean_and_sample_sd_on_a_known_batch`;
  `test_in_band_batch` (mean 88, sd 4); `test_mean_below_83_is_out_of_band_with_reason`;
  `test_sd_above_6_is_out_of_band_with_reason`; `test_sd_below_2_is_out_of_band` (everyone 90);
  `test_one_report_is_insufficient`; `test_incomplete_report_is_excluded_and_listed`;
  `test_outlier_uses_the_configured_z`; `test_loop_counter_refuses_a_third_loop_without_the_flag`;
  `test_loop_counter_allows_it_with_the_flag`; `test_grades_csv_header_and_rows`;
  `test_stdout_line_holds_no_comment_text` (a comment marker in the input never appears);
  `test_cli_exit_codes` (0, 3, 2).
- [ ] **Step 2: Run** with `.venv-skills\Scripts\python.exe`. Expected: FAIL.
- [ ] **Step 3: Write** the three assets and implement `batch_stats.py`.
- [ ] **Step 4: Run.** Expected: all OK.
- [ ] **Step 5: Commit:** `feat(work-ugs-audit): batch statistics and loop counter (#104)`.

### Task 2: `ref_check.py`

**Files:**
- Create: `.claude/skills/work-ugs-audit/assets/undergrad_references.json`
- Create: `.claude/skills/work-ugs-audit/scripts/ref_check.py`
- Test: `.claude/skills/work-ugs-audit/scripts/Test/test_ref_check.py`
- Modify: `.claude/rules/testing.md`

**Interfaces:**
- Consumes: `ugs_config.load` (`references.url_timeout_s`, `references.max_retries`).
- Produces:
  - `undergrad_references.json`: `standard_patterns` (regex strings for ISO, IEC, CSA, CAN/CSA, ANSI,
    IEEE Std, each with provenance), `accepted_kinds` list.
  - `classify(ref: str, patterns: dict) -> str` in `standard`, `url`, `other`.
  - `check(ref: str, body_text: str, patterns: dict, fetch, timeout: float) -> dict` with `kind`,
    `status` (`form-ok`, `malformed`, `reachable`, `unreachable`, `blocked`, `not_checked`), `cited`
    (bool: a `[n]` marker or the standard id appears in `body_text`). `fetch(url, timeout) -> int`
    returns an HTTP status or raises `OSError`.
  - `main(argv)`: `--refs FILE --body FILE [--json]`; exit 0 always on a completed check, 2 refusal.

- [ ] **Step 1: Write the failing tests:** `test_standard_forms_are_classified` (the five forms of the
  Review Focus); `test_a_malformed_standard_is_reported`; `test_reachable_unreachable_blocked_from_injected_fetch`
  (200, timeout `OSError`, 403); `test_retries_follow_the_config`; `test_cited_by_number_and_by_standard_id`;
  `test_an_uncited_reference_is_reported`; `test_accented_body_text_is_searched_correctly`;
  `test_no_real_network_in_the_suite` (the default fetch is never called).
- [ ] **Step 2: Run.** Expected: FAIL. **Step 3:** implement. **Step 4: Run.** Expected: all OK.
- [ ] **Step 5: Add** both script lines to `.claude/rules/testing.md`, tick `progress.md`.
- [ ] **Step 6: Commit:** `feat(work-ugs-audit): undergraduate reference check (#104)`.
