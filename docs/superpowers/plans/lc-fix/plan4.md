---
executor: local-coder
tier: standard
bounds:
  max_rounds: 3
  max_tokens: 1500000
  plateau: 2
---

# Plan 4 - The plan contract rule test follows the one-plan local-coder

> **For agentic workers:** run by the local coder model through the aider kit (rule R39). Return every
> file you change in full. The test file runs as a script (`unittest.main()` at its end).

**Goal:** the documentation test of rule R38 asserts the facts of the spec: the executor table, the
one-plan paragraph, the agent procedure through the kit, and the routing row. It keeps its negative
controls (R20).

**Spec:** the section "Facts the tests must assert" of the spec, points 1, 2 and 3.

## Global Constraints

Documentation only: the test reads the repository files and changes none of them. Do not edit any
document. Keep the structure of the test. An assertion about the removed driver or a whole ledger per
dispatch is replaced by the matching fact of the spec, not just deleted. Every function carries the
Purpose, Inputs and Outputs header.

## Review Focus

- The routing row is found by its new start, and the old start is asserted absent.
- The agent definition is asserted to name no model tag and no driver.

---

### Task 1: the test

**Files:**
- Modify: `.claude/hooks/Test/test_plan_contract_rule.py`

The failing tests of the current run name what must change; run the file first and read the output.

- Test: `.claude/hooks/Test/test_plan_contract_rule.py`

- [ ] Step 1: run the file and read each failing assertion.
- [ ] Step 2: rewrite the failing assertions against the facts of the spec, run the file, every test passes.
