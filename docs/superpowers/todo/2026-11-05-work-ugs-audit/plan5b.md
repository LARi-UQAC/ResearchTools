---
executor: local-coder
tier: standard
bounds:
  max_rounds: 3
  max_tokens: 1500000
  plateau: 2
---

# Plan 5b - Pseudonymous ids and Markdown per page

> **For agentic workers:** run by the local coder model through the driver (rule R39). Return every
> file you create in full. The test file runs as a script (`unittest.main()` at its end) and puts the
> parent folder of its own folder at the start of `sys.path`; it also puts the folder holding the
> fixture helper at the start of `sys.path`.

**Goal:** every report of a folder gets a stable id, and each of its pages becomes a Markdown file that
keeps the page number, so a later quote can be anchored on its page.

**Spec:** `spec.md` D2, D7, "Constraints", "Working folder".

## Global Constraints

Library: `pymupdf4llm` page by page through its page-chunks option (already installed). File names of
reports appear only in the id map; nothing printed carries one (R34). Every output path is resolved
inside the work folder (R24). Accented text survives. Every function carries the Purpose, Inputs and
Outputs header, and Raises when it raises on purpose.

## Review Focus

- A folder holding a `.zip` or a non-PDF file: skipped and counted, never an id.
- Re-running after one report was added: existing ids unchanged, the new one gets the next id.
- A page with no text: its Markdown file is written empty and listed, not an error.

---

### Task 1: the module and its tests

**Files:**
- Create: `.claude/skills/work-ugs-audit/scripts/report_prepare.py`
- Test: `.claude/skills/work-ugs-audit/scripts/Test/test_report_prepare.py`

**Reads, do not modify:** `.claude/skills/figure-review/scripts/Test/_pdf_fixtures.py` (its
`make_report(path, pages)` builds a fictitious PDF; a page dict may hold `text`, `image`,
`vector_chart`, `logo`, `caption`).

**Interfaces:**
- `PrepareError` (a `ValueError`).
- `prepare(reports_dir: Path, work_dir: Path) -> list[dict]`: one dict per report with `report_id`
  (`R01`, `R02`, in the sorted order of the PDF file names), `pages` (count) and `empty_pages` (list of
  1-based numbers). It writes the id map in the work folder as a file named `ids` (extension `.json`,
  an object from id to file name, existing ids kept, new ids appended in sorted order), and for each
  report one Markdown file per page at `R01/pages/p001.md`, `R01/pages/p002.md` and so on. Files that
  are not PDFs are skipped and counted in the returned value of a second function
  `skipped_count(reports_dir)`. Raises `PrepareError` when the work folder resolves outside the reports
  folder.
- `main(argv)`: `--reports DIR --work DIR [--dry-run] [--json]`. It prints one JSON line with ids and
  counts only. Exit 0, 2 on a refusal, 1 on a failure. With `--dry-run` nothing is written.

**Tests to write first, each failing before the code exists:**
`test_ids_follow_sorted_names_and_are_stable_on_rerun`; `test_non_pdf_files_are_skipped_and_counted`;
`test_one_markdown_file_per_page_with_accents_kept`; `test_an_empty_page_is_flagged_and_its_file_is_empty`;
`test_work_dir_outside_reports_is_refused`;
`test_stdout_never_carries_a_file_name` (a fixture file named with an invented student name);
`test_dry_run_writes_nothing`; `test_a_report_added_later_gets_the_next_id_and_keeps_the_old_ones`.

- Test: `.claude/skills/work-ugs-audit/scripts/Test/test_report_prepare.py`

- [ ] Step 1: write the tests, run the file, they fail (module absent).
- [ ] Step 2: write the module, run the file, every test passes.
