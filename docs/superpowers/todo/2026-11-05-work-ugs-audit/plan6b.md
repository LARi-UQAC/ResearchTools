---
executor: local-coder
tier: standard
bounds:
  max_rounds: 3
  max_tokens: 1500000
  plateau: 2
---

# Plan 6b - The completed rubric appended to the PDF

> **For agentic workers:** run by the local coder model through the driver (rule R39). Return every
> file you create in full. The test file runs as a script (`unittest.main()` at its end) and puts the
> parent folder of its own folder, and the folder holding the fixture helper, at the start of
> `sys.path`.

**Goal:** the annotated copy of a student PDF ends with pages that show the completed rubric: one row per
item with its score over its maximum, its status and its comment, and the total.

**Spec:** `spec.md` D1, D15, "Data shapes" (the grade record).

## Global Constraints

Library: PyMuPDF only (its HTML story layout). The annex is appended to the annotated copy, never to the
original. Text values are HTML-escaped by the script. A `not_run` item shows `not_run` and the total is
withheld (shown as a dash), never a zero. Every function carries the Purpose, Inputs and Outputs
header, and Raises when it raises on purpose.

## Review Focus

- A rubric of twelve items with long comments spans several pages and nothing is clipped.
- HTML special characters in a comment are escaped, accents render.
- A refusal when the PDF to extend is not the annotated copy (the path is given by the caller).

---

### Task 1: the module and its tests

**Files:**
- Create: `.claude/skills/work-ugs-audit/scripts/pdf_annex.py`
- Test: `.claude/skills/work-ugs-audit/scripts/Test/test_pdf_annex.py`

**Reads, do not modify:** `.claude/skills/figure-review/scripts/Test/_pdf_fixtures.py` (its
`make_report(path, pages)` builds a fictitious PDF). The HTML template is the file named
`annex.template` with the extension `.html` in the skill's `assets` folder; it holds the placeholders
`{{REPORT_ID}}`, `{{LOOP}}`, `{{ROWS}}` and `{{TOTAL}}`, and the script reads it as text and replaces
the four placeholders. A test may use its own small template string instead.

**Interfaces:**
- `AnnexError` (a `ValueError`).
- `render_rows(rubric: dict, grade: dict, totals: dict) -> str`: one `tr` element per rubric item, in
  rubric order, with four `td` cells: the title, the score over the maximum (for example `0.5 / 1`),
  the status and the comment (escaped). `grade` has `items` with `item_id`, `status`, `score`,
  `comment`; `totals` has `total` (string or null) and `by_item`.
- `build_html(template: str, rows: str, report_id: str, loop: int, total: str | None) -> str`: replaces
  the four placeholders; a null total becomes a dash. A placeholder left unreplaced raises `AnnexError`.
- `append_annex(pdf: Path, html: str) -> int`: appends the pages the HTML needs, using a story laid out
  page after page, to `pdf` and returns the number of pages added.
- `main(argv)`: `--pdf FILE --rubric FILE --grade FILE --totals FILE --report-id ID --loop N
  [--template FILE] [--json]`; it prints the number of pages added only. Exit 0, 2 on a refusal,
  1 on a failure.

**Tests to write first, each failing before the code exists:**
`test_annex_pages_are_appended_and_text_is_readable` (a rubric title, a score `0.5 / 1`, the total
`28.5` found in the extracted text); `test_long_comments_span_pages_without_clipping` (every comment
string found); `test_html_special_characters_are_escaped`;
`test_not_run_item_shows_not_run_and_the_total_is_a_dash`; `test_accents_render`;
`test_an_unreplaced_placeholder_raises`; `test_original_pages_are_unchanged` (the first pages' text is
identical after the append).

- Test: `.claude/skills/work-ugs-audit/scripts/Test/test_pdf_annex.py`

- [ ] Step 1: write the tests, run the file, they fail (module absent).
- [ ] Step 2: write the module, run the file, every test passes.
