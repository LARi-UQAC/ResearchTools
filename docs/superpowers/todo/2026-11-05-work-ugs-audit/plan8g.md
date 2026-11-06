---
executor: local-coder
tier: standard
bounds:
  max_rounds: 3
  max_tokens: 1500000
  plateau: 2
---

# Plan 8g - Language findings page by page

> **For agentic workers:** run by the local coder model through the driver (rule R39). Return every
> file you create in full. The test file runs as a script (`unittest.main()` at its end) and puts the
> parent folder of its own folder at the start of `sys.path`, then imports the module under test.

**Goal:** the grader model lists language errors of a report, page by page, using only the undergraduate
categories of the language table, and every finding that cannot be anchored in the PDF is dropped.

**Spec:** `spec.md` D9, "Data shapes" (the annotations list), "Driver contracts".

## Global Constraints

Local models only (D2). The `call` is injected (R21). A finding with a code outside the table, or with a
quote that is not in its page, is rejected and counted, never placed elsewhere. Every function carries
the Purpose, Inputs and Outputs header, and Raises when it raises on purpose.

## Review Focus

- Accented quotes and a typographic apostrophe are found after normalization.
- One page failing to run does not stop the others.
- The same finding returned twice for a page is kept once.

---

### Task 1: the module and its tests

**Files:**
- Create: `.claude/skills/work-ugs-audit/scripts/ugs_language.py`
- Test: `.claude/skills/work-ugs-audit/scripts/Test/test_ugs_language.py`

**Reads, do not modify:** `.claude/skills/language-review/assets/language_categories.json` (an object
whose `entries` list holds, per category, `code`, `label_fr`, `label_en`, `severity` and `scope`, the scope
being `both` or `research`), `.claude/skills/work-ugs-audit/scripts/ugs_text.py` (`StepContext`, `fill`),
`.claude/skills/work-ugs-audit/scripts/ugs_bridge.py` (`NotRun`),
`.claude/skills/work-ugs-audit/scripts/pdf_annotate.py` (`normalize(text)`). The `language` prompt has the
slots `LANGUAGE_TABLE`, `SECTION` and `LANGUAGE_OF_REPORT`; prompt and schema are
`ctx.prompts["language"]` and `ctx.schemas["language"]`.

**Interfaces:**
- `load_table(path: Path) -> list[dict]`: the entries whose scope is `both`; a missing file or key
  raises `ValueError` naming it.
- `table_text(entries: list[dict], language: str) -> str`: one line per entry, `CODE - label - severity`,
  the label in the report language (`fr` or `en`).
- `language_report(pages: list[str], call, ctx, entries: list[dict], language: str) -> dict`: one grader
  call per page whose text is not blank, in page order. Returns `annotations` (dicts with `page`, `kind`
  `language`, `code`, `quote`, `rect` None and `comment`, the comment being the proposal and the reason
  joined by a dash, or the reason alone), `rejected` (count of findings dropped for an unknown code or a
  quote not found in the page after `normalize`) and `not_run` (page numbers whose call failed after
  `ctx.grade_retries` repeats of a retryable `NotRun`). A finding repeated on a page with the same code
  and quote is kept once. Unretryable `NotRun` kinds propagate.

**Tests to write first, each failing before the code exists** (a fake `call` answering per page):
`test_load_table_keeps_both_scope_entries_only`; `test_load_table_names_a_missing_key`;
`test_table_text_uses_the_report_language`; `test_a_valid_finding_becomes_a_language_annotation`;
`test_unknown_code_is_rejected_and_counted`; `test_quote_not_on_the_page_is_rejected_and_counted`;
`test_accented_quote_with_a_typographic_apostrophe_is_accepted`; `test_blank_page_makes_no_call`;
`test_a_failed_page_is_listed_and_the_others_still_run`; `test_duplicate_finding_is_kept_once`;
`test_unreachable_propagates`; `test_comment_without_a_proposal_is_the_reason_alone`.

- Test: `.claude/skills/work-ugs-audit/scripts/Test/test_ugs_language.py`

- [ ] Step 1: write the tests, run the file, they fail (module absent).
- [ ] Step 2: write the module, run the file, every test passes.
