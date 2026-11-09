---
executor: local-coder
tier: simple
bounds:
  max_rounds: 3
  max_tokens: 1500000
  plateau: 2
---

# Plan 5e - The failure output of report_prepare carries no exception text

**Goal:** an unexpected failure of `report_prepare.py` prints only the exception type and a fixed message,
never the exception text, because that text can hold a report file name or a path.

**Spec:** `spec.md` "Constraints" (nothing printed carries a file name), rule R34, rule R8.

## Global Constraints

Python standard library only. No numeric literal in code (R0). The refusal and failure outputs stay one
JSON line. Fictitious names only in tests (R34). Comments in English.

## Review Focus

- A `FileNotFoundError` or `PermissionError` raised inside `prepare` on a file named with an invented
  student name: stdout holds the exception type and no part of the name or the path.
- The refusal path (`PrepareError`) keeps its fixed messages and its exit code 2.

---

### Task 1: fixed failure message

**Files:**
- Modify: `.claude/skills/work-ugs-audit/scripts/report_prepare.py`
- Test: `.claude/skills/work-ugs-audit/scripts/Test/test_report_prepare.py`

**Interfaces:**
- `main(argv)` keeps its signature and exit codes. In the generic failure branch the printed JSON object
  holds `status` (`failure`), `error_type` (the exception class name) and a fixed `error` message that does
  not interpolate the exception. Nothing else from the exception is printed.

**Tests to write first, each failing before the change:**
`test_unexpected_failure_prints_the_type_and_no_file_name` (patch `prepare` to raise a
`FileNotFoundError` whose text holds a path with an invented student name; assert exit 1, the class name in
stdout, and no part of the name in stdout).
