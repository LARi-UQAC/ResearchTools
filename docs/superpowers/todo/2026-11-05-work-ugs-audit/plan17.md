---
executor: cloud
tier: simple
bounds:
  max_rounds: 3
  max_tokens: 1500000
  plateau: 2
---

# Plan 17 - End of night un5: remove the duplicates, check nothing breaks, run the last local plan

> Cloud plan, deliberately tiny so that no step is forgotten. It runs when `~/.claude/aider-live/un5_night.log`
> holds `NIGHT-FINISHED`. Run the steps in order and tick each one in `progress.md` with its evidence.

**Goal:** one copy of every configuration file, in `.claude/skills/aider-setup/config`. The kit runs in place, so
the rendered copies and the old test projects have no use left.

**Files:**
- Modify: `docs/superpowers/todo/2026-11-05-work-ugs-audit/progress.md`

## Steps

1. **Harvest night un5** (plans 5c, 5d, 6a, 6b, 8b, 8c): read `quality.md`, `progress.md` and `audit.md` of
   `~\.claude\aider-live\work\un5\docs\superpowers\plans\`, copy back only the files each plan names,
   run their tests in the worktree, tick the plans in this ledger, commit. Report the quality percentage of each.
2. **Stop what the night left running:** the watchdog (`Get-Process aider-watchdog`) and the loaded models (`ollama ps`).
3. **Delete the duplicates.** Folders: `~\.claude\aider-live\kit`, `...\aider-live\home`, and every
   project of `...\aider-live\work\` except `un5` (cube, harness1, harness1b, moves, multi, multi2, multi3, u4b,
   u4c, u4cb, u4cc, u4d, u5a, u5b, un2, un3, un3-stopped, un4, uwd), with the `*_run.log` and `*.idmap` files of
   those projects. `un5` goes when step 1 is harvested. The operator deletes `~\.config\aider` himself
   once step 4 is green. `examples/` and `EXAMPLE-PROMPT-robot.md` stay: they are teaching material.
4. **Check the impact on the other plans and on the current configuration**, all from the ResearchTools path:
   - `aider-plan.ps1 -DryRun` on a mounted project, then `aider-night.ps1 -DryRun`: both must find
     `.claude\skills\aider-setup\config` without any flag.
   - `scripts\test\verify-aider-plan.ps1`, `scripts\test\verify-aider-path.ps1`,
     `.claude\skills\aider-setup\scripts\build\verify-kit-install.ps1` (the student zip still installs and starts).
   - `plan_contract.py validate` on one plan (its size ceilings now come from the repository copy only), and the
     tests `test_plan_contract.py`, `test_local_coder_dispatch_guard.py`, `test_aider_ollama_config.py`.
   - Search the repository for `aider-live`, `.config\aider` and `.local\bin`: what remains must be the student zip
     (installer, build scripts, manual) or a documented fallback, never a default of the ResearchTools run.
   - The remaining plans (8d to 8l, 9 to 15, lc-fix 1) must not name a deleted path: `run-plan.sh` uses `aider-live\work`
     only for its project folders.
5. **Run lc-fix plan 1 with `local-coder`** (one plan, so the wrapper): dispatch with the line
   `PLAN: docs/superpowers/plans/lc-fix/plan1.md`. The kit is the one in place. Report the quality percentage from
   `quality.md`.
6. **Close:** note the evidence of steps 1 to 5 in `progress.md`, commit, and tell the operator the two actions only
   he can do: delete `~\.config\aider`, and run `.\setup.ps1 -InstallAiderPath` from the main clone
   after the merge (the Path entry is specific to each machine).
