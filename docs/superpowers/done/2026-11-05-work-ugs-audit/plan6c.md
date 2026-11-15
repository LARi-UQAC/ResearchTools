---
executor: local-coder
tier: standard
bounds:
  max_rounds: 3
  max_tokens: 1500000
  plateau: 2
---

# Plan 6c - Script-measured figure criteria

> **For agentic workers:** run by the local coder model through the driver (rule R39). Return every
> file you create in full. The test file runs as a script (`unittest.main()` at its end) and puts the
> parent folder of its own folder, and the folder holding the fixture helper, at the start of
> `sys.path`.

**Goal:** the six measurable figure criteria are decided by script from the extracted figures and the
page text, each verdict carrying the number that justifies it, and a ready-made failure comment can be
looked up for any criterion.

**Spec:** `spec.md` D6, D12 ("`figure-review` is the lower layer": it reads no file of the grading
skill), "Data shapes" (the figures record).

## Global Constraints

Every threshold is read from the criteria data, never written in the code (R0): a criterion's
`threshold` is an object whose `value` is the number. The module reads nothing from the grading skill.
Verdicts are `pass`, `fail`, `not_applicable` or `not_run`; a number that cannot be measured is
`not_run`, never a pass. Every function carries the Purpose, Inputs and Outputs header, and Raises when
it raises on purpose.

## Review Focus

- A raster figure under the minimum resolution fails; a vector figure is `not_applicable` for it.
- A figure called in the text only after the page where it appears fails.
- A numbering gap (Figure 1, Figure 3) fails; a repeated number fails.
- Failure comments come back with their accents.

---

### Task 1: the module and its tests

**Files:**
- Create: `.claude/skills/figure-review/scripts/figure_checks.py`
- Test: `.claude/skills/figure-review/scripts/Test/test_figure_checks.py`

**Reads, do not modify:** `.claude/skills/figure-review/assets/figure_criteria.json` (a list
`criteria` of 22 objects with `id`, `level`, `judged_by`, `applies_to`, `threshold` (an object with
`value`, or null), `comment_fr`, `comment_en`, plus an `extraction` block),
`.claude/skills/figure-review/scripts/Test/_pdf_fixtures.py` (its `make_report(path, pages)` builds a
fictitious PDF).

**Interfaces:**
- `CriteriaError` (a `ValueError`) and `load_criteria(path: Path) -> dict`: reads the data file and
  raises `CriteriaError` naming the entry and the key that is missing (R3).
- `check(figures: list[dict], pages: list[str], body_font_size: float, criteria_doc: dict) ->
  list[dict]`. A figure record has `figure_id`, `page`, `rect`, `source` (`raster` or `vector`),
  `pixel_size` (raster only), `drawing_area_ratio`, `caption`, plus `text_sizes` (the span sizes found
  inside the rectangle, vector only, optional). It returns the records with a `criteria` object
  holding the six script verdicts, each `{verdict, reason}` with the measured number in `reason`:
  `space_used_over_70` (the ratio against its threshold), `effective_resolution` (raster pixels over
  displayed inches against its threshold in dots per inch, else `not_applicable`), `text_size` (vector
  only: the smallest size inside the rectangle over `body_font_size` against its threshold; raster
  `not_run`), `numbered_in_sequence` (figure numbers read from the captions are 1, 2, 3 in order),
  `called_before_appearing` (the first mention `Figure N` or `Fig. N` is on a page not after the
  figure's page), `source_cited` (a bracket reference or the word `Source` in the caption; otherwise
  `not_run`). `pages` holds the text of each page.
- `body_font_size(pdf: Path) -> float`: the most frequent span size of the document.
- `failure_comment(criterion_id: str, criteria: list[dict], language: str) -> str`: the `comment_fr` or
  `comment_en` of that criterion; an unknown id or language raises `CriteriaError`.
- `main(argv)`: `--figures FILE --pdf FILE --criteria FILE --out FILE [--json]`; reads the figures list
  and writes the checked list. It prints counts only. Exit 0, 2 on a refusal, 1 on a failure.

**Tests to write first, each failing before the code exists:**
`test_load_criteria_names_the_missing_key`; `test_space_ratio_pass_and_fail_at_the_threshold`;
`test_low_dpi_raster_fails_and_vector_is_not_applicable`; `test_small_vector_text_fails`;
`test_numbering_gap_fails`; `test_repeated_number_fails`;
`test_figure_called_after_it_appears_fails`; `test_source_marker_in_caption_passes`;
`test_missing_caption_makes_the_source_check_not_run`; `test_reason_carries_the_measured_number`;
`test_failure_comment_in_french_keeps_accents`; `test_unknown_criterion_id_raises`;
`test_body_font_size_is_the_most_frequent_size` (built with the fixture helper).

- Test: `.claude/skills/figure-review/scripts/Test/test_figure_checks.py`

- [ ] Step 1: write the tests, run the file, they fail (module absent).
- [ ] Step 2: write the module, run the file, every test passes.
