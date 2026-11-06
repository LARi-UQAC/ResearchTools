---
executor: local-coder
tier: standard
bounds:
  max_rounds: 3
  max_tokens: 1500000
  plateau: 2
---

# Plan 8i - Assembling the annotated copy

> **For agentic workers:** run by the local coder model through the driver (rule R39). Return every
> file you create in full. The test file runs as a script (`unittest.main()` at its end) and puts the
> parent folder of its own folder, and the folder holding the fixture helper, at the start of
> `sys.path`.

**Goal:** the results of one report (grade, language, figures, references) become one annotations list,
one annotated copy of the PDF and the appended rubric pages, and the totals are computed by script.

**Spec:** `spec.md` D1, D8, D15, "Data shapes" (annotations, totals), "Driver contracts".

## Global Constraints

No model call here. The source PDF is never changed (D1). Every output path is inside the report's loop
folder (R24). Nothing printed or returned carries report text. The network is injected (R21). Every
function carries the Purpose, Inputs and Outputs header, and Raises when it raises on purpose.

## Review Focus

- A rated item with no evidence makes no annotation; its comment is still in the appended rubric.
- A reference with a bad form, an unreachable address, a blocked address or no citation in the text is
  annotated on the start of its own entry, in the report language.
- The total is withheld when an item is `not_run`.

---

### Task 1: the module and its tests

**Files:**
- Create: `.claude/skills/work-ugs-audit/scripts/ugs_assemble.py`
- Test: `.claude/skills/work-ugs-audit/scripts/Test/test_ugs_assemble.py`

**Reads, do not modify:** `.claude/skills/work-ugs-audit/scripts/grade_total.py` (`compute(rubric, grade)`),
`.claude/skills/work-ugs-audit/scripts/pdf_annotate.py` (`annotate(src, items, dst, colors, author)`),
`.claude/skills/work-ugs-audit/scripts/pdf_annex.py` (`render_rows(rubric, grade, totals)`,
`build_html(template, rows, report_id, loop, total)`, `append_annex(pdf, html)`),
`.claude/skills/work-ugs-audit/scripts/ref_check.py` (`check_all(refs, body_text, patterns, fetch,
timeout, retries)` returns dicts with `index`, `kind`, `status`, `cited`),
`.claude/skills/work-ugs-audit/scripts/ugs_text.py` (`split_body_and_references(pages)`),
`.claude/skills/figure-review/scripts/Test/_pdf_fixtures.py`.

**Interfaces:**
- `grade_annotations(rubric: dict, grade: dict) -> list[dict]`: for each `rated` item and each of its
  evidence entries, one annotation with `page`, `kind` `technical`, `code` the item id, `quote`, `rect`
  None and a comment `I01 7.5 / 10: <comment>`; other items give none.
- `figure_annotations(figures: dict) -> list[dict]`: for each figure criterion with verdict `fail` and a
  `comment`, one annotation with the figure's `page`, `kind` `figure`, `code` the criterion id, `quote`
  None, the figure's `rect` and that comment.
- `reference_annotations(results: list[dict], entries: list[dict], comments: dict, language: str,
  quote_chars: int) -> list[dict]`: for each result whose status is `malformed`, `unreachable` or
  `blocked`, or whose `cited` is false, one annotation with the entry's `page`, `kind` `reference`, a
  `code` (`malformed`, `unreachable`, `blocked` or `uncited`, the status winning over the citation), the
  first `quote_chars` characters of the entry as `quote`, `rect` None, and the comment `comments[code]
  [language]`.
- `assemble_report(src_pdf: Path, report_dir: Path, report_id: str, loop: int, rubric: dict, pages:
  list[str], language: str, settings: dict, fetch) -> dict`: reads `grade`.json, and `language`.json and
  `figures`.json when present, from `report_dir`; computes the totals and writes `totals`.json; checks
  the references found by `split_body_and_references`; writes `annotations`.json; writes
  `annotated.pdf` with `annotate`; appends the rubric pages built from `settings["annex_template"]`.
  `settings` holds `colors`, `author`, `quote_chars`, `url_timeout_s`, `max_retries`, `patterns`,
  `ref_comments`, `annex_template`; a missing key raises `ValueError` naming it. Returns
  `{report_id, placed, not_found, duplicates, annex_pages, complete, percent}` and nothing else.

**Tests to write first, each failing before the code exists** (fixture PDF, fake `fetch`, invented author):
`test_grade_annotations_one_per_evidence_entry`; `test_unrated_items_make_no_annotation`;
`test_figure_annotations_only_for_failed_criteria_with_a_comment`;
`test_reference_codes_and_their_priority`; `test_reference_comment_is_in_the_report_language`;
`test_assemble_writes_totals_annotations_and_annotated_copy`;
`test_assemble_appends_the_rubric_pages_and_leaves_the_source_unchanged` (hash before and after);
`test_missing_language_and_figures_files_are_fine`; `test_not_run_item_withholds_the_total`;
`test_missing_setting_is_named`; `test_return_value_holds_no_report_text`;
`test_outputs_stay_inside_the_report_folder`.

- Test: `.claude/skills/work-ugs-audit/scripts/Test/test_ugs_assemble.py`

- [ ] Step 1: write the tests, run the file, they fail (module absent).
- [ ] Step 2: write the module, run the file, every test passes.
