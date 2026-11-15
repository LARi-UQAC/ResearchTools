---
executor: local-coder
tier: standard
bounds:
  max_rounds: 3
  max_tokens: 1500000
  plateau: 2
---

# Plan 8d - The ledger

> **For agentic workers:** run by the local coder model through the driver (rule R39). Return every
> file you create in full. The test file runs as a script (`unittest.main()` at its end) and puts the
> parent folder of its own folder at the start of `sys.path`, then imports the module under test.

**Goal:** the progress ledger is read and written by script only: sections per report, step lines with
three marks, an optional short note, and a resume rule that finds the first open line.

**Spec:** `spec.md` D3, "Driver contracts" (ledger lines).

## Global Constraints

Python standard library only. Pure functions on text, plus one atomic writer. A note is a short code:
only ASCII letters, digits, space and the characters `_ . , : = / + -`, at most 60 characters; anything
else raises, so report text can never enter the ledger (D2). Every function carries the Purpose, Inputs
and Outputs header, and Raises when it raises on purpose.

## Review Focus

- Adding a report that already has a section changes nothing.
- A mark change touches exactly one line.
- A note with accented text, a newline or 61 characters is refused.

---

### Task 1: the module and its tests

**Files:**
- Create: `.claude/skills/work-ugs-audit/scripts/ugs_ledger.py`
- Test: `.claude/skills/work-ugs-audit/scripts/Test/test_ugs_ledger.py`

**Interfaces:**
- `LedgerError` (a `ValueError`).
- `MARKS`: the three strings `" "`, `"x"` and `"!"`.
- `new_ledger(title: str) -> str`: a first line `# title` and an empty `## notes` section.
- `add_report(text: str, report_id: str, item_ids: list[str]) -> str`: appends a section `## R01` with
  the lines `- [ ] prepare`, one `- [ ] grade I01` per item id, then `language`, `figures`, `audit` and
  `assemble`, in that order. Idempotent: a report already present leaves the text unchanged.
- `add_figures(text: str, report_id: str, figure_ids: list[str]) -> str`: inserts one `- [ ] figure F01`
  line per id right after the `figures` line of that report; ids already present are skipped.
- `parse(text: str) -> list[dict]`: one dict per step line, in file order, with `report_id`, `label`
  (for example `grade I01`), `mark` and `note` (or None).
- `set_mark(text: str, report_id: str, label: str, mark: str, note: str | None = None) -> str`: changes
  exactly that line; an unknown report, label or mark, or a bad note, raises `LedgerError`.
- `first_open(text: str) -> tuple[str, str] | None`: the report id and label of the first line marked open.
- `counts(text: str) -> dict`: `done`, `open` and `blocked` line counts.
- `reopen_all(text: str, keep: list[str]) -> str`: sets every line open again except those whose label is
  in `keep`, for a new grading loop; notes are removed from reopened lines.
- `add_note(text: str, line: str) -> str`: appends one line under `## notes`, checked like a note.
- `read(path: Path) -> str` and `write(path: Path, text: str) -> None`: UTF-8; the writer goes through a
  sibling temporary file and a replace.

**Tests to write first, each failing before the code exists:**
`test_add_report_writes_the_step_lines_in_order`; `test_add_report_twice_changes_nothing`;
`test_add_figures_after_the_figures_line_and_not_twice`; `test_parse_reads_marks_and_notes`;
`test_set_mark_changes_exactly_one_line`; `test_unknown_label_report_or_mark_raises`;
`test_note_with_accents_newline_or_61_characters_is_refused`; `test_first_open_follows_file_order`;
`test_first_open_is_none_when_nothing_is_open`; `test_counts`; `test_reopen_all_keeps_the_named_labels`;
`test_add_note_is_checked_like_a_note`; `test_write_is_atomic_and_read_round_trips`.

- Test: `.claude/skills/work-ugs-audit/scripts/Test/test_ugs_ledger.py`

- [ ] Step 1: write the tests, run the file, they fail (module absent).
- [ ] Step 2: write the module, run the file, every test passes.
