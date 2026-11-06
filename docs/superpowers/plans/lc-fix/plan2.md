---
executor: local-coder
tier: standard
bounds:
  max_rounds: 3
  max_tokens: 1500000
  plateau: 2
---

# Plan 2 - The rule test follows the one-plan local-coder

> **For agentic workers:** run by the local coder model through the aider kit (rule R39). Return every
> file you change in full. The test file runs as a script (`unittest.main()` at its end).

**Goal:** the documentation test of rule R39 asserts the facts of the spec instead of the removed text
driver. It still proves the rule is written, and it keeps its negative controls (R20).

**Spec:** the section "Facts the tests must assert" of the spec, points 1, 2, 3, 5 and 6.

## Global Constraints

Documentation only: the test reads the repository files and changes none of them. Do not edit any
document. Keep the structure of the test (one class per concern, the finder helpers with their negative
control). An assertion about the removed driver, its sandbox or the `PROGRESS:` line is replaced by the
matching fact of the spec, never just deleted without a replacement for the same concern. Every function
carries the Purpose, Inputs and Outputs header.

## Review Focus

- A test that cannot fail: each rewritten assertion is checked against a planted wrong text.
- The rule is still asserted in all places that carry it (agent, workflows, exported region, loop skill).

---

### Task 1: the test

**Files:**
- Modify: `.claude/hooks/Test/test_cloud_never_codes_rule.py`

The failing tests of the current run name what must change; run the file first and read the output.

- Test: `.claude/hooks/Test/test_cloud_never_codes_rule.py`

- [ ] Step 1: run the file and read each failing assertion.
- [ ] Step 2: rewrite the failing assertions against the facts of the spec, run the file, every test passes.
