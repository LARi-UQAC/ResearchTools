# Maintenance, checks and CI

Chapter 15 of the ResearchTools manual. Back to [table of contents](../../README.md).

This chapter is for the person who keeps the toolkit healthy: proving a change, deploying it to
`~/.claude`, closing a branch, and publishing this site. Installing and updating a machine is in
[chapter 01](01-installation.md).

## The green stamp

`scripts/test/run-offline-tests.ps1` finds every `.claude/**/Test/test_*.py` suite and runs it with
no network, no API key and no model. Each suite is graded PASSED, FAILED or NOT RUN (a suite that
cannot import a third-party package). A full pass writes `.rt-green.json`, a hash per code file, and
any failure deletes it. The stamp is what lets `install-junctions.ps1 -Sync` copy a hook or a skill
script into `~/.claude`: only a file a green run has proven is copied, and the rest is held and named.
The interpreter is `.venv-skills` of this clone, then of the main clone from a worktree, and the
script refuses with the rebuild command (`.\setup.ps1 -InstallPython`) rather than falling back to
whatever `python` is on the `PATH`.

## Checks

| Script | Proves | Runs |
|---|---|---|
| `scripts/test/run-offline-tests.ps1` | Every Python suite, and writes the green stamp | about 15 minutes |
| `scripts/test/run-all-checks.ps1` | The suite, then every `verify-*.ps1` of `scripts/test`, each in its own process. Exit 0 only if all pass | about 15 minutes |
| `scripts/audit/check-deployment.ps1` | Read-only: does `~/.claude` match the repository (agents by hash, skill links, hooks, contract block, settings entry, green stamp, interpreter) | seconds |
| `scripts/audit/check-claude-template.ps1` | Read-only drift check of `CLAUDE.template.md` against the live global file, plus the write-path invariants | seconds |
| `scripts/audit/check-graph-health.ps1` | What the code graph holds and whether it is stale. Reserved to the `local-writer` agent, since it reads the graph | seconds |

`run-all-checks.ps1` takes `-DryRun` (list, run nothing), `-SkipSuite`, `-Only a,b`, `-Exclude names`
and `-ReportPath file.json`. It leaves out `verify-graph-health.ps1` for the same reason as above.

The eleven verifiers in `scripts/test/` each prove one installer or tool by running it for real against a
throwaway home or repository, never your own:

| Verifier | Proves |
|---|---|
| `verify-branch-tools.ps1` | `run-all-checks.ps1` and `finish-branch.ps1` |
| `verify-daemon-install.ps1` | `setup.ps1 -InstallDaemon` and the `OBSIDIAN_VAULT` offer |
| `verify-graph-health.ps1` | The graph health script (`local-writer` only) |
| `verify-no-personal-data.ps1` | No published file carries the account name of whoever runs it |
| `verify-python-env.ps1` | `setup.ps1 -InstallPython`: the three environments, their order, one pin per library, every requirements file registered |
| `verify-python-libs.ps1` | Every third-party import is declared and the library tables of chapter 02 are current (`scripts/docs/python_libs.py --check`) |
| `verify-rt-contract.ps1` | The generated `RT-CONTRACT` block of the global `CLAUDE.md` |
| `verify-setup-writes.ps1` | The three writes `setup.ps1` makes to the global configuration |
| `verify-sync-writes.ps1` | The two irreversible writes of `-Sync` and what it selects |
| `verify-template-audit.ps1` | The title gate in `check-claude-template.ps1` |
| `verify-venv-resolution.ps1` | How every launcher finds its interpreter |

Five more live beside their skill and are not run by `run-all-checks.ps1`:
`scripts/local/Test/verify-claude-switch.ps1`, the three `verify-*.ps1` in
`.claude/skills/aider-setup/scripts/Test/`, and `verify-kit-install.ps1` for the student kit.

## Improving ResearchTools from another folder

Code written to work around a weakness in ResearchTools goes **inside ResearchTools**, at the level of
the skill, agent or command that carries the weakness, never in the paper, thesis or grant folder.
The protocol, written in `.claude/CLAUDE.md`, has eight steps: find the owner and extend its code
with a flag, read `.rt-green.json`, copy each file to `.rt-undo/` before changing it, prove the fix
with a test and a full suite, loop at most three times, roll back after the third failure, make the
fix active with `install-junctions.ps1 -Sync`, and log one line in `IMPROVEMENTS.md`. Nothing is
committed by that protocol.

## From a change to a merged branch

1. A change that opens a pull request has a GitHub Issue and a card on the project board (R30).
2. Update the documentation of what the change touched in the same pull request (R31, R33), see
   [chapter 08](08-rules.md).
3. Before the pull request opens, run the bounded security and code review of R35 and fix what it
   finds. The review bounds are declared first, see [chapter 11](11-local-coding.md).
4. Run `scripts/test/run-all-checks.ps1` once, after the last commit.
5. Open the pull request. The owner merges it, never a session.
6. After the merge, from the main clone, `scripts/test/finish-branch.ps1 -Branch <branch>`.

`finish-branch.ps1` removes the merged branch's worktree, deletes the branch locally and on origin,
prunes, and moves a plans folder from `docs/superpowers/todo` to `done`. It is a dry run until `-Yes`,
and it never uses `--force`. It refuses, listing every reason at once and changing nothing, when no
merged pull request has that head, when the local or the origin branch is not on the merged commit,
when the main clone is not on the main branch or holds modified tracked files, when the worktree is
dirty, holds git-ignored files (unless `-DiscardIgnored`) or holds a junction or symbolic link, and
when it is started from inside the worktree it removes. A second run finds nothing to clean and exits 0.

## Continuous integration

Two GitHub workflows run on pull requests. `privacy-scan.yml` is free and static: it scans the added
commits for secrets and personal-data shapes. `review.yml` is billed and optional: a headless review
posts one consolidated comment. Both are described in [chapter 15](15-security-audit.md). There is no
workflow that runs the test suites, they are run by hand as above.

## This documentation site

The site is built by MkDocs Material (the libraries of `.venv-docs` are listed in [chapter 02](02-profiles.md#python-environments-every-library)) from `mkdocs.yml` at the repository root and the pages under
`docs/`. Chapter order is the `nav` list in that file, and the chapter table in `README.md` and in
`docs/index.md` follows it. A chapter that is added, removed or renamed updates all three.

| Task | Command |
|---|---|
| Install the tools, once | `.\setup.ps1 -InstallPython`, which builds `.venv-docs` from `requirements-docs.txt` with the other environments ([chapter 01](01-installation.md), Step 5) |
| Preview | `.venv-docs\Scripts\python.exe -m mkdocs serve`, then open the printed local address |
| Check links and anchors | `.venv-docs\Scripts\python.exe -m mkdocs build --strict`, which must print no warning |
| Publish | `.venv-docs\Scripts\python.exe -m mkdocs gh-deploy`, run by hand from `main` after the merge |

MkDocs serves only `docs/`. The build hook `scripts/docs/mkdocs_hooks.py` rewrites a link that reaches
outside `docs/` (to `README.md` or `.claude/CLAUDE.md`, for example) into its page on GitHub, on the
branch named by `extra.docs_source_ref` in `mkdocs.yml`. Those links therefore work only once the
change is on that branch, which is why publishing happens after the merge. A push to `main` never
updates the published site by itself, and the deploy is the only way the live pages change.

## Deployed services

`deploy/` holds the container set for the `form-service` HTTP API: `docker-compose.yml`, a
`Caddyfile` reverse proxy, `initdb/` which enables pgvector on the PostgreSQL 17 container, and
`form-service/` for the service itself. Its boundary with ThesisTracker is in [chapter 17](17-thesistracker-integration.md).

---
[← 15 Security audit and guards](15-security-audit.md) | [Table of contents](../../README.md) | [17 ThesisTracker integration →](17-thesistracker-integration.md)
