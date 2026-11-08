# Roadmap - aider-setup self-contained, validated by two live tests, then the work-ugs-audit code

One file, one order. Update the marks here and nowhere else. Marks: `[ ]` not done, `[x]` done, `[!]` blocked.
Who: **C** cloud session (design, prose, data, review), **L** local model through the kit (all code, R39),
**O** owner (reserved commands, decisions).

## Why this order

The feature (Issue #104) needs the kit to write about 25 code plans. The kit crashed once and its test
layout differs from ResearchTools. So: fix the kit minimally, prove the loop on a tiny plan, protect it with
two re-runnable tests, only then refactor the kit to be self-contained, and only then spend hours on the
feature plans. A refactor without the two tests would be done blind.

## Phase 0 - Freeze the current pile (C)

- [ ] 0.1 Commit by path, in three commits, nothing else: (a) `aider-plan.ps1` round-counter fix; (b) kit test layout
      (`conventions.md`, `context-budget.json`, protocol message); (c) local-coder rewrite and aligned docs.
- [ ] 0.2 Commit the rescued files: `scripts/build/` (9 scripts) with the `.gitignore` exception, the reviewer Modelfile.
- [ ] 0.3 Regenerate mirrors (`install.ps1 -Profile engineering`) and commit them with (c).

## Phase 1 - Minimum install so the kit uses the new layout (O)

- [ ] 1.1 Owner runs the kit setup from the repo copy to refresh `~/.config/aider` (`conventions.md`,
      `context-budget.json`). Exact command given by C when 0.x is done. Nothing else in that folder is touched by C.

## Phase 2 - Live tests of the kit (the loop code, test, audit)

- [ ] 2.1 (C) `-DryRun` on both fixtures (`scripts/Test/live/single`, `.../multi`): every file named in a plan is
      recognised, no stray file is created. No model runs.
- [ ] 2.2 (O) Single-plan run, pocket cube, by hand, command given by C. Expect: tests in `scripts/Test/test_rubik.py`,
      none inside `rubik.py`, audit runs, and if the audit reopens the plan the round counter now works.
- [ ] 2.3 (C) Read the result against the checks: separate test file, tests green, ledger ticked, plan archived, audit
      ran. Fix the prose or data if the kit's behaviour shows a gap.
- [ ] 2.4 (C writes plans, L writes code) The re-runnable harness in `scripts/Test/`: a pure checker plus its offline
      test, one runner per case (`live_aider_single.py`, `live_aider_multi.py`), not picked up by the offline suite.
- [ ] 2.5 (O) Multi-plan run (Theta* then trapezoid) with its runner. Expect both plans done, one audit each.

## Phase 3 - aider-setup self-contained (repo is the only source)

`~/.config/aider` becomes an install target, like `~/.claude`: regenerated from the repo, never edited.

- [ ] 3.1 (C plans, L code) `aider-plan.ps1`, `aider-night.ps1`, `new-project.ps1` resolve config and budget from the
      skill when `~/.config/aider` is absent. Guarded by the 2.x tests, re-run after each change.
- [ ] 3.2 (C) Correct `testing.md` and `MANUAL.md`: they describe `scripts/build/` as present, which was false until 0.2.
- [ ] 3.3 (O) Rebuild the student zip from the repo (`build_kit.py`, then `verify-kit-install.ps1`), command given by C.
- [ ] 3.4 (O) Sync installed scripts from the repo; plan `lc-fix` plan 5 automates it.

## Phase 4 - The work-ugs-audit feature (Issue #104)

- [ ] 4.1 Rerun plan 4a (batch statistics) in `~/.claude/local-coder-work/plan4a`; harvest `batch_stats.py` and its test;
      tick the ledger. The open audit line (`render_report` never called) is the first thing the rerun fixes.
- [ ] 4.2 `lc-fix` plans 1-5, one kit project each.
- [ ] 4.3 The 20 feature code plans (4b, 5a-5d, 6a-6c, 8a-8l), one kit project each, in dependency order.
- [ ] 4.4 Cloud plans 9-11, then plan 12: mirrors, all checks once, review loop (3 rounds, 1,500,000 tokens, plateau 2),
      pull request with `Fixes #104`. The owner merges.

## Owner decisions of 2026-11-07 (given in advance, the owner is away)

- Scope to deliver: phases 0 to 3. Stop before phase 4 and write a report.
- Order changed by the owner: finish the two test plans and RUN the tests first; commits (phase 0) come after.
- Cloud may repair aider-setup code in the repo (never `~/.config/aider`) for any defect a test reveals: 3 attempts per defect,
  then stop and report. This permission ends when both tests pass. Once aider-setup is tested, all code is local.
- Tests run from the repo with a rendered temporary config (no install into `~/.config/aider` needed).
- Test folder is named `Test` (capital T), as in ResearchTools. Done in the repo source on 2026-11-07, not committed yet.

## Rules that stay

Kit edits only with the owner's go, in the repo source first. Never edit `~/.config/aider`. No commit in the repo while
a kit run uses it. One real model call before any lot. Short answers, verify before affirming.
