---
name: finish-branch
description: "Finish a ResearchTools branch end to end: before the pull request (regenerate the mirrors, run every check) and after the owner merges it (clean the project: worktree, branch, main checkout leftovers, machine refresh). Use whenever the user says 'clean the project', 'finish the branch', 'the PR is merged', 'after a merge', 'before the pull request' or 'is the branch ready for a PR', even when no script is named, because the steps live in several files and skipping one leaves stale mirrors, an unproven main or an unsynced ~/.claude."
allowed-tools: [Read, Bash, PowerShell]
permissions: [read, write]
---

# finish-branch

The end of a branch has steps that already exist but live in separate files (R35, R30,
`workflows.md`, the `-Personal` and gh-deploy notes). Measured 2026-11-04 on PR #101: the mirrors
were never regenerated, the full checks were not re-run on the merged `main`, and the machine was
never refreshed. Nothing failed at the time, so nobody noticed. This skill puts the steps in one
order. The logic lives in tested scripts. The skill decides which one to run, when, and what to
show the owner.

It runs from a ResearchTools clone only. `finish-branch.ps1` finds the repository from its own
location, so a copy, or a path through a `~/.claude` junction, is refused with exit 2. Using it on
another project needs a `-Repo` argument that does not exist yet.

## Part 1 - before the pull request (in the branch worktree)

Do these after the last code change and before R35's review loop is called safe:

1. **Regenerate the mirrors in the branch:** `.\install.ps1 -Profile <active>`. Read the active
   profile from the `active_profile:` line of `.claude/CLAUDE.md`, and never guess one. Commit
   every file it changed together with the canonical change. Mirrors belong in the same pull
   request. Fixing them after the merge means a second PR and a stale `main` in between.
2. **Run every check once, after the last commit:** `.\scripts\test\run-all-checks.ps1`. It runs
   the Python suite and every `verify-*.ps1`, including `verify-mirrors-fresh.ps1`, which fails
   when step 1 was skipped. Report the suite and the verifiers separately. "Green" means this
   script exited 0. Otherwise, name the check that failed.
3. **If an agent, a command or a rule changed,** also tell the owner that `.\install.ps1 -Personal` must
   run on their machine. The ordinary run never reaches `~/.copilot/agents` or the VS Code user
   profile.

Then the PR opens as R30 says, with an Issue, a board card and `Fixes #N`.

## Part 2 - after the owner merges ("clean the project")

Run each step from the MAIN clone, never from inside the worktree being removed.

1. **Confirm the merge** with `gh pr view <n> --json state,mergeCommit,headRefOid`. If the PR is
   not `MERGED`, say so and stop. Cleaning an unmerged branch deletes work.
2. **Check the main checkout before touching it.** Run `git status --short` there. Leftover
   uncommitted copies of the branch's files (another session's work, as on 2026-11-04) block the
   pull. Before discarding any of them, diff each against the branch's first commit, ignoring
   line endings, and confirm they hold nothing the merge lacks. Peers share this tree (R32), so
   run `ListAgents` and send a heads-up to a busy peer before changing files there.
3. **Show the dry run** and wait:
   `.\.claude\skills\finish-branch\scripts\finish-branch.ps1 -Branch <b> -Refresh`. It lists the
   git steps and the `setup.ps1 -Update ...` command it would run, and changes nothing. A refusal
   (exit 2) names every reason at once. Fix those, never work around them. For git-ignored files
   in the worktree, list them and confirm they are derived (caches, stamps, logs) before adding
   `-DiscardIgnored`.
4. **Add `-Yes` only when the owner asked for the clean-up.** It deletes a branch on origin.
   Pass `-KeepHooks 'AUTO-SYNC CHECK'` (or the names the owner keeps) when this machine has a
   deliberate local hook variant.
   - `-Yes` alone does the git clean-up: it pulls `main`, removes the worktree and the branch,
     and prunes.
   - `-Refresh` adds the machine refresh after it: `setup.ps1 -Update -Profile <active>
     -RunSuite -NonInteractive -Force`, which runs the suite on the merged `main`, the links
     step and the mirrors, then `install-junctions.ps1 -Sync`. It adds `-Personal` when the PR
     changed an agent, a command or a rule, or when its file list could not be read whole.
   - When nothing is left to clean, `-Refresh` still refreshes. It first refuses a main clone
     that is not on `main` or holds modified tracked files (R32), then pulls `main`.
   - A failed refresh exits 1. Report that as not done, not as a warning.
5. **Relay the reminders** printed with `[TODO]`. When `docs/` changed, the site is published by
   the owner with `mkdocs gh-deploy` from `main`. No script does it.
6. **Verify the end state** and report it in a few lines: on `main`, at `origin/main`, no
   modified file, no worktree or branch left, and the refresh's result.

## Scripts

| Script | Role | Proven by |
|---|---|---|
| `scripts/finish-branch.ps1` | the clean-up and `-Refresh` | `scripts/test/verify-branch-tools.ps1` |
| `scripts/rt-finish.ps1` | its pure decisions (refusals, steps, refresh arguments, reminders); the profile is read by `scripts/lib/rt-update.ps1` (`Get-RtActiveProfile`) | same |
| `scripts/test/run-all-checks.ps1` (repo-wide) | the pre-PR gate | same |
| `scripts/lib/rt-mirrors-fresh.ps1` (repo-wide) | stale-mirror detection | `scripts/test/verify-mirrors-fresh.ps1` |

The two verifiers stay in `scripts/test/` on purpose: `run-all-checks.ps1` discovers only the
`verify-*.ps1` files of its own folder.
