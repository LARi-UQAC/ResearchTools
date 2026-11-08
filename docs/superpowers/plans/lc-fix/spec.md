# Spec - local-coder runs on the aider kit (Issue 104, follow-up of 2026-11-06)

`local-coder` no longer has a text driver. It is the aider kit run on ONE plan: the plan is mounted
as the only plan of a small kit project outside the repository (the kit's `new-project.ps1`), the kit script `aider-plan.ps1` (installed in `~/.local/bin`) runs it with the
kit's writer model and its required reviewer audit, and nothing needs a wrapper to start it. Several
plans or a night go to `aider-night.ps1`. The files `local_coder_driver.py`, `driver_deps.py`,
`local-coder-driver.json` and `test_local_coder_driver.py` were deleted. The documents were already
rewritten; the tests and the dispatch guard below must now agree with them.

## Facts the tests must assert (all already true in the files)

1. Agent `.claude/agents/local-coder.md`: one plan per dispatch, a `PLAN:` line; it mounts a kit project outside the repository with
   `new-project.ps1` (spec, the plan as `plan1.md`, a progress file whose step lines name their files, only the
   files the plan reads or changes), launches the installed `aider-plan.ps1` with `-Path`, `-Config`,
   `-BudgetFile`, `-TestCommand`, first with `-DryRun`, and brings back only the files the plan names; it never passes `-NoAudit`, `-AllowCloud` or
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

## Sync of the kit scripts (owner decision 2026-11-06, point 8)

No script copies only the kit scripts: the kit installer works file by file and its force option would also
overwrite the owner's tuned configuration. The existing repository sync, run at every session start by the
sync option of the junction installer, is extended instead. A new function in `scripts/lib/rt-sync.ps1`
copies every file at the top level of `.claude/skills/aider-setup/scripts` (not the `Test` folder) into the
`.local/bin` folder of the home that owns the `.claude` folder being synced. Rules:

- The installed text is the repository text with every `{{HOME}}` replaced by that home path written with
  forward slashes, saved as UTF-8 without a byte order mark (the same rule as the kit installer). A file
  whose installed text is already identical is left alone.
- A file is written only when it is proven: a script must parse without errors, a Python file must be
  proven by the green stamp (`Test-RtProven`), a data file must parse as JSON, a batch file has no check.
  A file that fails is reported as held and never written.
- Before a write, the previous installed file is copied into the undo folder, as `Sync-RtFile` does.
- The `.local/bin` folder must already exist: when it does not, the step is skipped without a message (the
  kit is not installed, rule R11). The `.config/aider` folder is never read or written.
- The step honours the dry-run flag already used by the sync (`RtWhatIf`): it reports and writes nothing.
