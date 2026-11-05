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
completed rubric; the original is never touched.

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
- Modify: `.claude/rules/testing.md`

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
- [ ] **Step 5: Add** both script lines to `.claude/rules/testing.md`, tick `progress.md`.
- [ ] **Step 6: Commit:** `feat(work-ugs-audit): completed rubric appended to the PDF (#104)`.
