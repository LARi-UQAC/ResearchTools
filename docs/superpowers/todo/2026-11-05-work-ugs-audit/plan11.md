---
executor: cloud
tier: standard
bounds:
  max_rounds: 3
  max_tokens: 1500000
  plateau: 2
---

# Plan 11 - Mirrors, full checks, bounded review, pull request

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans, then `code-review` and
> `security-review` (R35), then the `finish-branch` skill for the steps before the PR. `progress.md` is
> the ledger.

**Goal:** The branch is proven green once, reviewed inside the owner's bounds, and opened as a PR that
fixes #104.

**Architecture:** No new code unless a review finding requires it; a fix is a small plan of its own (R38).

**Tech Stack:** `install.ps1`, `run-all-checks.ps1`, `loop_bounds.py`, `gh`.

**Spec:** `spec.md` "Acceptance"; R31, R33, R35.

## Global Constraints

Bounds `max_rounds 3`, `max_tokens 1500000`, `plateau 2` (owner 2026-11-05). The full suite runs once,
here (owner preference). No merge, no tag. The PR body names no student, no report file name.

## Review Focus

- A review that reads a real student report to "test" the agent: forbidden; reviews read the code and
  the fictitious fixtures only.
- A mirror left stale (`verify-mirrors-fresh.ps1`).
- The landing page `docs/index.md` not naming the new capability (R33).

---

### Task 1: mirrors and full checks

**Files:**
- Modify: `docs/index.md`
- Modify: `CHANGELOG.md`
- Modify: `IMPROVEMENTS.md`
- Modify: `.claude/rules/testing.md`

- [ ] **Step 1:** Add the capability line to `docs/index.md`, an Unreleased entry to `CHANGELOG.md`, and
  one line to `IMPROVEMENTS.md` (language and figure checks unified, undergraduate grading added), and the `figure_tex.py` line to `.claude/rules/testing.md` (plan 9).
- [ ] **Step 2:** `.\install.ps1 -Profile engineering` from the worktree; commit the regenerated mirrors
  with the canonical changes.
- [ ] **Step 3:** `scripts/test/run-all-checks.ps1`. Expected: exit 0; report the Python suite and the
  verifiers separately in `progress.md`. A failure goes back to the plan that owns the file.
- [ ] **Step 4: Commit:** `chore: mirrors and docs for work-ugs-audit (#104)`.

### Task 2: R35 review loop

- [ ] **Step 1:** `python .claude/skills/loop-engineer/scripts/loop_bounds.py init --max-rounds 3 --max-tokens 1500000 --plateau 2`.
- [ ] **Step 2:** `security-review` and `code-review` at high effort on the branch diff against `main`,
  asking for each check and hook who can weaken it; then `loop_bounds.py tick --findings N`.
- [ ] **Step 3:** Each finding fixed with a test that fails first (R20), or declined with a measurement in
  `audit.md` of this folder. Repeat until a bound, a round with no finding, or a safe branch (suite
  green, no Critical or High after re-grading); name which stopped it. A bound reached first: report and
  ask the owner.

### Task 3: pull request and owner actions

- [ ] **Step 1:** Move this folder from `docs/superpowers/todo/` to `docs/superpowers/done/`.
- [ ] **Step 2:** Push, open the PR with `Fixes #104`, the review rounds and what each fixed, deferred
  minors listed.
- [ ] **Step 3:** Tell the owner the actions only he can do: `install.ps1 -Personal` (new agent and
  command); adopt `ugs-grader`, `ugs-auditor`, `ugs-vision` with `model_resolver.py --adopt-role ... --reason`;
  run `vision_probe.py` for the vision role; measure window and speed of both roles before a first batch;
  confirm the outlier threshold; first live batch on his own machine.
