---
executor: local-coder
tier: standard
bounds:
  max_rounds: 3
  max_tokens: 1500000
  plateau: 2
---

# Plan 3 - Configuration, rubric check and grade totals

> **For agentic workers:** dispatched to `local-coder` with a `PLAN:` line naming this file. Tests are
> the oracle; tick `progress.md`. No audit inside the wrapper (R38).

**Goal:** The rubric JSON is validated and every total is computed by a script, with the three item
statuses handled explicitly.

**Architecture:** `ugs_config.py` reads `{value, provenance}` JSON files and names a missing key.
`rubric_check.py` validates a normalized rubric. `grade_total.py` turns a rubric plus a grade record into
totals. Standard library only.

**Tech Stack:** Python 3.11 standard library, `unittest`, `json`, `decimal`.

**Spec:** `spec.md` "Data shapes" (`rubric.json`, `grade.json`), D4, D10.

## Global Constraints

`spec.md` "Constraints". Points may be decimal; sums use `decimal.Decimal` from the string form so that
0.5 + 0.5 + 1 + ... gives exactly 28.5. `not_run` is never a zero. No student data in fixtures (R34).

## Review Focus

- A rubric whose item points do not sum to `total_points` (the professor's arithmetic slip): refused,
  naming both sums.
- A grade with a score above the item maximum, or negative: refused, naming the item.
- Every item `not_applicable`: percent is undefined, reported as such, never a division by zero.
- A grade record whose `item_id` set differs from the rubric's: refused, listing missing and extra ids.

---

### Task 1: config loader, rubric check, totals

**Files:**
- Create: `.claude/skills/work-ugs-audit/assets/ugs_config.json`
- Create: `.claude/skills/work-ugs-audit/assets/rubric.schema.json`
- Create: `.claude/skills/work-ugs-audit/assets/rubric.template.json`
- Create: `.claude/skills/work-ugs-audit/assets/grade.template.json`
- Create: `.claude/skills/work-ugs-audit/scripts/ugs_config.py`
- Create: `.claude/skills/work-ugs-audit/scripts/rubric_check.py`
- Create: `.claude/skills/work-ugs-audit/scripts/grade_total.py`
- Test: `.claude/skills/work-ugs-audit/scripts/Test/test_rubric_check.py`
- Test: `.claude/skills/work-ugs-audit/scripts/Test/test_grade_total.py`
- Modify: `.claude/rules/testing.md`

**Interfaces:**
- Produces:
  - `ugs_config.json`, every value `{value, provenance}`: `figure.min_area_pt2` 2500, `figure.background_threshold`
    245, `figure.space_ratio_min` 0.70 (owner 2026-11-05), `figure.min_effective_dpi` 150,
    `figure.min_text_ratio` 0.7 (figure text height over body text height), `annotation.colors` (one per kind:
    technical, figure, language, reference), `references.url_timeout_s` 10, `references.max_retries` 1,
    `batch.outlier_z` 2.0, `driver.audit_retries` 1, `driver.request_timeout_s` 600. Provenance
    "proposal 2026-11-05, tuned at the owner's review" except the owner value.
  - `ugs_config.load(path: Path) -> dict` returns plain values; `ConfigError(ValueError)` names the
    dotted key and the file (R3). `ugs_config.default_path() -> Path` is `assets/ugs_config.json` beside
    the skill.
  - `rubric_check.validate(rubric: dict) -> dict` returns `{"items": n, "total_points": str}`; raises
    `RubricError(ValueError)` for: missing key, unknown `assessment_type`, empty `items`, duplicate or
    malformed `id` (pattern `I` plus two digits), `max_points` not positive, empty `title`, sum of
    `max_points` different from `total_points` (both sums in the message).
  - `grade_total.compute(rubric: dict, grade: dict) -> dict` returns `report_id`, `total` (str decimal),
    `max_rated` (str), `percent` (float rounded to 2, or null when `max_rated` is 0), `by_item`
    (`{item_id: {"status", "score", "max"}}`), `not_run` (list of ids), `complete` (bool, false when any
    item is `not_run`; then `total` and `percent` are null). Raises `GradeError(ValueError)` for score
    out of range, `rated` with a null score, non-null score on `not_run`, id set mismatch.
  - Both scripts: `main(argv) -> int`, `--json`, exit 0 ok, 2 refusal, 1 failure (R12); stdout utf-8.
- Consumes: nothing.

- [ ] **Step 1: Write the four asset files.** The templates are the shapes of `spec.md` with one
  fictitious item each; the schema is a JSON Schema draft 2020-12 document describing `rubric.json`
  (documentation for humans; the code does not need a schema library).
- [ ] **Step 2: Write the failing tests.** `test_rubric_check.py`: `test_points_table_rubric_totalling_100_passes`
  (eleven fictitious items whose points sum to 100); `test_checklist_rubric_with_fractional_points_totalling_28_5_passes`
  (twelve items: 1, 2, 10, 5, 5, 0.5, 0.5, 1, 1, 1, 1, 0.5); `test_a_sum_mismatch_names_both_sums`;
  one test per other `RubricError` cause; `test_config_loads_and_a_missing_key_is_named`;
  `test_shipped_config_values_carry_provenance`. `test_grade_total.py`: `test_total_and_percent_on_a_full_grade`
  (exact `"28.5"` when all scores are full); `test_not_applicable_is_excluded_from_the_maximum`;
  `test_an_absent_element_rated_zero_counts_as_zero`; `test_not_run_makes_the_total_null_and_lists_the_item`;
  `test_all_not_applicable_gives_null_percent`; one test per `GradeError` cause; `test_cli_exit_codes`.
- [ ] **Step 3: Run** both suites with `.venv-skills\Scripts\python.exe`. Expected: FAIL (modules absent).
- [ ] **Step 4: Implement** `ugs_config.py`, `rubric_check.py`, `grade_total.py` with the signatures above.
- [ ] **Step 5: Run** both suites. Expected: all OK.
- [ ] **Step 6: Add** the three script lines to `.claude/rules/testing.md` (R23) and tick `progress.md`.
- [ ] **Step 7: Commit:** `feat(work-ugs-audit): config loader, rubric check, grade totals (#104)`.
