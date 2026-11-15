---
executor: local-coder
tier: standard
bounds:
  max_rounds: 3
  max_tokens: 1500000
  plateau: 2
---

# Plan 3 - The manual test follows the one-plan local-coder

> **For agentic workers:** run by the local coder model through the aider kit (rule R39). Return every
> file you change in full. The test file runs as a script (`unittest.main()` at its end).

**Goal:** the test of the manual chapters on local coding asserts the facts of the spec instead of the
removed text driver and the old role table. It keeps its negative controls (R20).

**Spec:** the section "Facts the tests must assert" of the spec, points 4 and 6. The chapter must name
no model tag (R2), and every row of its role table carries a date.

## Global Constraints

Documentation only: the test reads the repository files and changes none of them. Do not edit any
document. Keep the structure of the test. An assertion about the removed driver, the 262K path through the
wrapper or a whole ledger per dispatch is replaced by the matching fact of the spec, not just deleted.
Every function carries the Purpose, Inputs and Outputs header.

## Review Focus

- A test that cannot fail: each rewritten assertion is checked against a planted wrong text.
- The chapter 11 table of roles is found by its columns Tier, Models, Window, Source and date.

---

### Task 1: the test

**Files:**
- Modify: `.claude/hooks/Test/test_manual_local_coding.py`

The failing tests of the current run name what must change; run the file first and read the output.

- Test: `.claude/hooks/Test/test_manual_local_coding.py`

- [ ] Step 1: run the file and read each failing assertion.
- [ ] Step 2: rewrite the failing assertions against the facts of the spec, run the file, every test passes.
