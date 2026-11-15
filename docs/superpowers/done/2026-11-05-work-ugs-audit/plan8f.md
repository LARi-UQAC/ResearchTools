---
executor: local-coder
tier: standard
bounds:
  max_rounds: 3
  max_tokens: 1500000
  plateau: 2
---

# Plan 8f - The auditor

> **For agentic workers:** run by the local coder model through the driver (rule R39). Return every
> file you create in full. The test file runs as a script (`unittest.main()` at its end) and puts the
> parent folder of its own folder at the start of `sys.path`, then imports the module under test.

**Goal:** a second model checks each graded item and never edits it; a disagreement sends the item back
to the grader once with the auditor's reason, and a second disagreement flags the item for the professor.

**Spec:** `spec.md` D3, "Data shapes" (the grade record), "Driver contracts".

## Global Constraints

Local models only (D2). The `call` is injected (R21). The auditor answers only `agree` or `disagree`
with a reason. Every function carries the Purpose, Inputs and Outputs header, and Raises when it raises
on purpose.

## Review Focus

- The auditor disagrees, the regrade agrees: the regraded record replaces the first.
- The auditor disagrees twice: the first record is kept unchanged, with flag true.
- An item that is `not_applicable` or `not_run` is not sent to the auditor.
- The auditor call fails after its retries: the audit field is `not_run` and the flag stays false.

---

### Task 1: the module and its tests

**Files:**
- Create: `.claude/skills/work-ugs-audit/scripts/ugs_audit.py`
- Test: `.claude/skills/work-ugs-audit/scripts/Test/test_ugs_audit.py`

**Reads, do not modify:** `.claude/skills/work-ugs-audit/scripts/ugs_text.py` (`StepContext`, `fill`,
`page_blocks`, `select_pages`), `.claude/skills/work-ugs-audit/scripts/ugs_bridge.py` (`NotRun`),
`.claude/skills/work-ugs-audit/scripts/ugs_grade.py` (`grade_item(item, pages, call, ctx, language,
calibration_note)` returns an item record). The `audit_item` prompt has the slots `ITEM`,
`GRADE_RECORD` and `EVIDENCE_PAGES`; prompt and schema are `ctx.prompts["audit_item"]` and
`ctx.schemas["audit_item"]`.

**Interfaces:**
- `audit_item(item: dict, record: dict, pages: list[str], call, ctx) -> dict`: one auditor call; returns
  `{verdict, reason}` with verdict `agree`, `disagree` or `not_run`. `GRADE_RECORD` is the record as JSON
  without its `audit` and `flag` keys. `EVIDENCE_PAGES` holds the pages named by the evidence, or the
  pages `select_pages` picks when there is no evidence. A retryable `NotRun` is repeated up to
  `ctx.audit_retries` more times, then the verdict is `not_run`; other kinds propagate.
- `audit_report(rubric: dict, pages: list[str], grade: dict, call, ctx, language: str,
  calibration_note: str, on_item=None) -> dict`: returns a new grade record. For each rated item it audits;
  on `agree` the item gets `audit` `agree`; on `disagree` the grader regrades the item once with the
  auditor's reason appended to the calibration note, and the auditor checks the new record: if it agrees
  the new record replaces the first, with `audit` `agree`; if it disagrees again the first record is kept
  with `audit` `disagree` and `flag` true. Other items keep `audit` `not_run`. After each item it calls
  `on_item(item_id, record)` when given. The input record is never changed.

**Tests to write first, each failing before the code exists** (a fake `call` scripted per kind):
`test_agree_marks_the_item`; `test_disagree_then_agree_on_regrade_replaces_the_record`;
`test_disagree_twice_keeps_the_first_record_and_flags`; `test_regrade_prompt_carries_the_auditor_reason`;
`test_not_applicable_and_not_run_items_are_not_audited`; `test_auditor_failure_is_not_run_without_flag`;
`test_unreachable_propagates`; `test_the_input_record_is_not_changed`; `test_on_item_is_called_per_audited_item`;
`test_evidence_pages_are_the_pages_named_by_the_evidence`.

- Test: `.claude/skills/work-ugs-audit/scripts/Test/test_ugs_audit.py`

- [ ] Step 1: write the tests, run the file, they fail (module absent).
- [ ] Step 2: write the module, run the file, every test passes.
