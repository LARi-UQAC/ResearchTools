---
executor: local-coder
tier: standard
bounds:
  max_rounds: 3
  max_tokens: 1500000
  plateau: 2
---

# Plan 6a - Native PDF annotations

> **For agentic workers:** run by the local coder model through the driver (rule R39). Return every
> file you create in full. The test file runs as a script (`unittest.main()` at its end) and puts the
> parent folder of its own folder, and the folder holding the fixture helper, at the start of
> `sys.path`.

**Goal:** a copy of a student PDF carries every remark as a native annotation anchored on the quoted
passage or on a figure's rectangle; the original is never touched.

**Spec:** `spec.md` D1, D2, D15, "Data shapes" (the annotations list).

## Global Constraints

Library: PyMuPDF only. The note author is a parameter; no name is written in the code or in the
fixtures (an invented name is used in tests). A passage not found is reported and never placed
elsewhere. The output path is resolved and must differ from the source (R24). Every function carries
the Purpose, Inputs and Outputs header, and Raises when it raises on purpose.

## Review Focus

- A quote split across two lines or hyphenated at a line end: matched after normalization.
- A quote found twice on the page: the first is used and the duplicate is reported.
- French accents and a typographic apostrophe: found.
- Destination equal to source: refused before any write.

---

### Task 1: the module and its tests

**Files:**
- Create: `.claude/skills/work-ugs-audit/scripts/pdf_annotate.py`
- Test: `.claude/skills/work-ugs-audit/scripts/Test/test_pdf_annotate.py`

**Reads, do not modify:** `.claude/skills/figure-review/scripts/Test/_pdf_fixtures.py` (its
`make_report(path, pages)` builds a fictitious PDF), `.claude/skills/work-ugs-audit/scripts/ugs_config.py`
(`load(path)` returns a flat dict of dotted keys, here `annotation.colors`, an object from the kinds
`technical`, `figure`, `language`, `reference` to a hex colour; `default_path()` names the file).

**Interfaces:**
- `AnnotateError` (a `ValueError`).
- `normalize(text: str) -> str`: NFC form, typographic apostrophes and quotes to straight ones,
  whitespace collapsed to one space, line-end hyphen joins removed.
- `annotate(src: Path, items: list[dict], dst: Path, colors: dict, author: str) -> dict`. An item has
  `page` (1-based), `kind` (`technical`, `figure`, `language`, `reference`), `code`, `quote` (string or
  null), `rect` (four numbers or null) and `comment`. A `quote` item gets a highlight annotation on the
  quoted words plus a note carrying `comment`, in the colour of its kind; a `rect` item gets a rectangle
  annotation plus a note; an item with neither is not found. The note's author is `author`. Returns
  `placed` (count), `not_found` (indexes) and `duplicates` (indexes found more than once). Raises
  `AnnotateError` when `dst` resolves to `src`.
- `main(argv)`: `--src FILE --items FILE --dst FILE --author NAME [--json]`; the items file is a JSON
  list; the colours come from the configuration. It prints counts only. Exit 0, 2 on a refusal, 1 on a
  failure.

**Tests to write first, each failing before the code exists:**
`test_quote_is_highlighted_with_its_note_on_the_right_page` (read back with PyMuPDF: annotation type,
page, note text, colour); `test_hyphenated_and_split_quote_is_found`; `test_accented_quote_is_found`;
`test_missing_quote_is_reported_not_placed`; `test_duplicate_quote_uses_first_and_is_reported`;
`test_rect_item_gets_a_rectangle_annotation`; `test_source_file_is_unchanged` (hash before and after);
`test_dst_equal_to_src_is_refused`; `test_author_is_the_value_passed_in` (an invented name);
`test_stdout_carries_counts_only`.

- Test: `.claude/skills/work-ugs-audit/scripts/Test/test_pdf_annotate.py`

- [ ] Step 1: write the tests, run the file, they fail (module absent).
- [ ] Step 2: write the module, run the file, every test passes.
