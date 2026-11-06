# Spec - local-coder runs on the aider kit (Issue 104, follow-up of 2026-11-06)

`local-coder` no longer has a text driver. It is the aider kit run on ONE plan: the plan sits alone
in its plans folder, the kit script `aider-plan.ps1` (installed in `~/.local/bin`) runs it with the
kit's writer model and its required reviewer audit, and nothing needs a wrapper to start it. Several
plans or a night go to `aider-night.ps1`. The files `local_coder_driver.py`, `driver_deps.py`,
`local-coder-driver.json` and `test_local_coder_driver.py` were deleted. The documents were already
rewritten; the tests and the dispatch guard below must now agree with them.

## Facts the tests must assert (all already true in the files)

1. Agent `.claude/agents/local-coder.md`: one plan per dispatch, a `PLAN:` line, the plan alone in its
   plans folder (spec, one plan, progress); it launches the installed `aider-plan.ps1` with `-Path`,
   `-Round`, `-TestCommand`, first with `-DryRun`; it never passes `-NoAudit`, `-AllowCloud` or
   `-Model`; the kit's reviewer audit is required; the kit starts without the agent; step 4 is the R35
   review (`code-review`, `security-review`) whose findings are `- [ ] audit:` lines of `progress.md`
   and `audit.md`; the agent writes and edits no code; no sandbox, no `--audit-begin`, no driver.
2. `.claude/rules/workflows.md`, rule R38: the executor table has rows for cloud, one plan through
   `local-coder` (`aider-plan.ps1`), several plans or a night (`aider-night.ps1`), and a whole session
   switched by hand; the paragraph begins "One plan is one `local-coder` run". Rule R39 part 1 names
   `aider-plan.ps1` and `aider-night.ps1` and says findings are `- [ ] audit:` lines.
3. `.claude/CLAUDE.md`: the R38 paragraph says one plan is one `local-coder` run and several plans go
   to `aider-night.ps1`; the routing row starts "Execute ONE plan with a local model"; the R39
   paragraph names the aider-setup kit.
4. Manual: chapter 05 row `local-coder` ("Runs ONE plan on a local model with the aider-setup kit");
   chapter 11 has no model tag, a role table with columns Tier, Models, Window, Source and date whose
   rows carry the date 2026-11-06, and a paragraph "One plan through `local-coder`"; chapter 14 has the
   heading "`local-coder` and the `aider-setup` pipeline - one harness at two scales".
5. `.claude/skills/loop-engineer/SKILL.md`, step 5 "Code", names `aider-plan.ps1` and `aider-night.ps1`.
6. No document names `local_coder_driver.py`, except chapter 14 which says it is retired.

## Guard

`.claude/hooks/local-coder-dispatch-guard.py` stops asking the resolver for a role. It checks that the
aider kit is installed: the folder `~/.config/aider` holds `model-settings.yml` and
`context-budget.json`, and the folder `~/.local/bin` holds `aider-plan.ps1`. These two folders and the
list of three file names are configuration of the guard (R0, R4 with provenance), with `~` expanded. A
missing file is a refusal that names it and says to run the kit installer. Every other behaviour is
unchanged: the plan header and size checks, the executor must be `local-coder`, and R11 (any failure
of the hook itself exits 0 in silence).
