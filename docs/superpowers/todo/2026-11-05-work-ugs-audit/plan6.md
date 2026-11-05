---
executor: local-coder
tier: standard
bounds:
  max_rounds: 3
  max_tokens: 1500000
  plateau: 2
---

# Plan 6 - Writing the PDF: annotations and the completed-rubric annex

> **For agentic workers:** dispatched to `local-coder` with a `PLAN:` line naming this file. Tests are
> the oracle; tick `progress.md`. No audit inside the wrapper (R38).

**Goal:** A copy of the student PDF carries every remark as a native annotation and ends with the
completed rubric; the original is never touched. The figure correction template holds the 21 criteria,
and the six measurable ones are decided by script.

**Architecture:** `pdf_annotate.py` places highlight annotations with a pop-up note on a quoted passage,
or a rectangle annotation on a figure. `pdf_annex.py` renders the rubric from an HTML template with
PyMuPDF and appends the pages. Both refuse to write over their input.

**Tech Stack:** PyMuPDF 1.27.2.3, `unittest`, fixtures of plan 5.

**Spec:** `spec.md` D1, D2, "Data shapes" (`annotations.json`, `grade.json`); plan 3 `grade_total`.

## Global Constraints

`spec.md` "Constraints". The note author field is a fixed label from config, never a person's name.
A passage not found is reported and never placed elsewhere (design anti-goal "annotations that move").
Output path resolved inside the working folder (R24).

## Review Focus

- A quote split across two lines or hyphenated at a line end: matched after whitespace and hyphen
  normalization.
- A quote found twice on the same page: the first occurrence is used and the count is reported.
- A quote with French accents or a typographic apostrophe: found.
- An annex for a rubric of twelve items with long comments: spans several pages, nothing clipped.
- Destination equal to source: refused before any write.

---

### Task 1: `pdf_annotate.py`

**Files:**
- Create: `.claude/skills/work-ugs-audit/scripts/pdf_annotate.py`
- Test: `.claude/skills/work-ugs-audit/scripts/Test/test_pdf_annotate.py`

**Interfaces:**
- Consumes: `ugs_config.load` (`annotation.colors`); `_pdf_fixtures.make_report`.
- Produces:
  - `normalize(text: str) -> str`: NFC, typographic apostrophe to straight, collapsed whitespace,
    line-end hyphen joins removed.
  - `annotate(src: Path, items: list[dict], dst: Path, colors: dict, author: str) -> dict` with
    `placed`, `not_found` (list of item indexes), `duplicates` (indexes found more than once).
    A `quote` item gets a highlight plus note; a `rect` item gets a rectangle annotation plus note;
    an item with neither is `not_found`. Raises `AnnotateError` when `dst` resolves to `src`.
  - `main(argv)`: `--src --items --dst [--json]`; prints counts only.

- [ ] **Step 1: Write the failing tests:** `test_quote_is_highlighted_with_its_note_on_the_right_page`
  (read back with PyMuPDF: annotation type, page, note text, colour); `test_hyphenated_and_split_quote_is_found`;
  `test_accented_quote_is_found`; `test_missing_quote_is_reported_not_placed`;
  `test_duplicate_quote_uses_first_and_is_reported`; `test_rect_item_gets_a_rectangle_annotation`;
  `test_source_file_is_unchanged` (hash before and after); `test_dst_equal_to_src_is_refused`;
  `test_author_is_the_configured_label`.
- [ ] **Step 2: Run.** Expected: FAIL. **Step 3:** implement. **Step 4: Run.** Expected: all OK.
- [ ] **Step 5: Commit:** `feat(work-ugs-audit): native PDF annotations from JSON (#104)`.

### Task 2: `pdf_annex.py`

**Files:**
- Create: `.claude/skills/work-ugs-audit/assets/annex.template.html`
- Create: `.claude/skills/work-ugs-audit/scripts/pdf_annex.py`
- Test: `.claude/skills/work-ugs-audit/scripts/Test/test_pdf_annex.py`

**Interfaces:**
- Consumes: `grade_total.compute` output, `rubric.json`, `grade.json`.
- Produces:
  - `annex.template.html`: a table, one row per rubric item (title, score over maximum, status,
    comment), a total row, the report id and loop number in the heading; placeholders
    `{{REPORT_ID}}`, `{{LOOP}}`, `{{ROWS}}`, `{{TOTAL}}`. Text values are HTML-escaped by the script.
  - `render_rows(rubric: dict, grade: dict, totals: dict) -> str`.
  - `append_annex(pdf: Path, html: str) -> int`: appends pages to `pdf` (the annotated copy, never the
    original) and returns the number added, using PyMuPDF `Story` laid out page after page.
  - `main(argv)`: `--pdf --rubric --grade [--json]`.

- [ ] **Step 1: Write the failing tests:** `test_annex_pages_are_appended_and_text_is_readable`
  (rubric title, a score `0.5 / 1`, the total `28.5`); `test_long_comments_span_pages_without_clipping`
  (every comment string found in the extracted text); `test_html_special_characters_are_escaped`;
  `test_not_run_item_shows_not_run_and_total_is_withheld`; `test_accents_render`.
- [ ] **Step 2: Run.** Expected: FAIL. **Step 3:** implement. **Step 4: Run.** Expected: all OK.
- [ ] **Step 5: Commit:** `feat(work-ugs-audit): completed rubric appended to the PDF (#104)`.

### Task 3: figure correction template and script-measured criteria

**Files:**
- Create: `.claude/skills/figure-review/assets/figure_criteria.json`
- Create: `.claude/skills/figure-review/assets/figure_analysis.template.json`
- Create: `.claude/skills/figure-review/scripts/figure_checks.py`
- Test: `.claude/skills/figure-review/scripts/Test/test_figure_checks.py`
- Modify: `.claude/rules/testing.md`

**Interfaces:**
- Consumes: `figure_extract.extract` records (plan 5), page Markdown (any list of page strings). Nothing
  from `work-ugs-audit`: `figure-review` is the lower layer.
- Produces:
  - `figure_criteria.json` (the correction template): an `extraction` block (`min_area_pt2` 2500,
    `background_threshold` 245, each `{value, provenance}`, provenance "proposal 2026-11-05, tuned at the
    owner's review") and `criteria[]`, 21 entries in the order of design 7.4, each `id` (snake case),
    `group` (`owner`, `readability`, `text_link`, `technical`, `diagram`), `scope` (`undergraduate`,
    `research`, `both`; all 21 are `both`), `severity` (`minor`, `major`), `label_fr`, `label_en`,
    `judged_by` (`script`, `model`, `script_then_model`), `applies_to` (list of figure kinds), `threshold`
    (`{value, provenance}` or null: `space_used_over_70` 0.70 owner 2026-11-05, `effective_resolution`
    150 DPI and `text_size` 0.7 proposals), `standard` (`ISO 80000`, `ISO 5807` or null, marked "named
    by the session, to be confirmed"), `comment_fr`, `comment_en` (the ready-to-use failure comment,
    polite, one sentence, addressed to an undergraduate). Owner provenance on the six original criteria.
  - `load_criteria(path: Path) -> dict` raising `CriteriaError(ValueError)` naming the entry and key (R3).
  - `figure_analysis.template.json`: the `figures.json` shape of `spec.md`, with `criteria` holding every
    id of `figure_criteria.json` at `{verdict: "not_run", reason: ""}` and an empty `extra` object.
  - `figure_checks.check(figures: list[dict], pages: list[str], body_font_size: float,
    criteria_doc: dict) -> list[dict]`: returns the records with the script verdicts filled, each
    threshold read from its criterion: `space_used_over_70` (ratio against its threshold),
    `effective_resolution` (pixels over displayed inches, raster only, else `not_applicable`),
    `text_size` (vector only: smallest span inside the rect over `body_font_size`, raster left `not_run`
    for the model),
    `numbered_in_sequence`, `called_before_appearing` (first "Figure N" or "Fig. N" mention page not after
    the figure page), `source_cited` (`[n]` or "Source" in the caption, else `not_run` for the model when a
    borrowed figure is suspected). Each verdict carries its measured number in `reason`.
  - `body_font_size(pdf: Path) -> float`: the most frequent span size of the document.
  - `failure_comment(criterion_id: str, criteria: list[dict], language: str) -> str`.

- [ ] **Step 1: Write the two assets.** `comment_fr` in plain French with accents; the 21 ids match the
  template keys exactly.
- [ ] **Step 2: Write the failing tests:** `test_criteria_file_has_21_unique_ids_and_both_comments`;
  `test_template_keys_equal_the_criteria_ids`; `test_space_ratio_pass_and_fail_at_the_configured_bound`;
  `test_low_dpi_raster_fails_and_vector_is_not_applicable`; `test_small_vector_text_fails`;
  `test_numbering_gap_fails`; `test_figure_called_after_it_appears_fails`;
  `test_source_marker_in_caption_passes`; `test_reason_carries_the_measured_number`;
  `test_failure_comment_in_french_keeps_accents`.
- [ ] **Step 3: Run.** Expected: FAIL. **Step 4:** implement. **Step 5: Run.** Expected: all OK.
- [ ] **Step 6: Add** the three script lines (`pdf_annotate`, `pdf_annex`, `figure_checks`) to
  `.claude/rules/testing.md`, tick `progress.md`.
- [ ] **Step 7: Commit:** `feat(work-ugs-audit): figure correction template and measured criteria (#104)`.
