# MEMORY - aider-setup, continuity notes for the next session

Not the ResearchTools auto-memory system (that one is per-conversation-directory and
cross-project). This is a plain handoff file for whoever picks up the `aider-setup` integration
next, matching the convention the original aider-kit work already used. Read `PROGRESS.md` at
the repo root first for what is done; this file is for what to remember while continuing.

## Where things live now (2026-09-24)

The canonical source moved from `~/.config/aider/` + `~/.local/bin/` into
`.claude/skills/aider-setup/` of this repository. The old external locations still exist on
this machine and were **not deleted** - they are simply no longer where an edit belongs. Edit
inside the repo from now on; the external copies are stale the moment this integration is
reviewed and kept.

`config/rules.md` is generated, never edited: `scripts/aider-rules-sync.py` derives it from
`.claude/rules/*.md` of this repository. Its `DEFAULT_SOURCE` is now computed from the
script's own file location (`parents[4] / ".claude" / "rules"`), not a literal - if the repo
ever moves or is cloned elsewhere, this keeps working with no edit.

`scripts/build/` is the packaging pipeline for the **student-facing** `aider-kit.zip`. It now
reads its canonical sources from `SKILL_ROOT` (this skill's own tree) rather than `$HOME`.
Three kinds of `$HOME` reference remain in the tree and are all correct, not missed bugs:
(1) `scripts/build/*.ps1`'s references to where the assembled kit gets INSTALLED on a
student's or the operator's own machine (`setup.ps1`'s target, genuinely per-machine);
(2) the runtime scripts (`aider-plan.ps1`, `aider-plan-core.ps1`, `aider-night.ps1`,
`ollama-tune.ps1`, `run-detached.ps1`) reading their OWN installed config at
`$HOME/.config/aider/...` at actual run time, post-`setup.ps1` - these run on the machine that
does the nightly work, which is a different question from where the repo's canonical copy
lives; (3) `scripts/build/aider.conf.yml.saved`, a gitignored, genuinely machine-local test
fixture carrying this machine's real paths, used only to drive `verify-aider-plan.ps1` and
`verify-kit-install.ps1`'s own dry runs against this machine's real aider install.

## Traps worth not re-discovering

- `aider-plan.ps1` dot-sources `aider-plan-core.ps1` via `$PSScriptRoot`, i.e. **flat, same
  directory** - not a `lib/` subfolder. It was moved there deliberately during this session
  after starting in `scripts/lib/`.
- `python` on PATH on this machine resolves to `C:\Users\m3otis99\...`, a DIFFERENT account's
  install (matches the known limitation already logged in the 2026-09-05 resumption docs, item
  6.2). Use `.venv-skills\Scripts\python.exe` explicitly for anything that must run from this
  repo's own environment; it has no `pytest`, so aider's suites run as plain scripts
  (`python file.py`), not `pytest file.py`.
- Two test counts drifted upward since the source's own last documented figure:
  `test_aider_thread_probe.py` is 62 (was 58), `test_aider_ollama_config.py` is 49 (was 37).
  `testing.md` now states the measured figures with today's date; if they move again, re-measure
  rather than trusting either number.
- `verify-kit-install.ps1`'s `-Report <path>.json` argument threw a `WriteAllText` path-format
  exception when invoked from a Git Bash `powershell -File` wrapper on this machine, while the
  six real checks it printed all still passed and it still exited 0. That looks like an
  invocation-environment artifact (mixed Bash/PowerShell `$env:TEMP` forms), not a defect in
  the script; re-verify from a native PowerShell session before spending time on it.
- The `_REQUIRED_SCRIPTS` list inside `build_kit.py` and the `harnesses.json` /
  `mirror-policy.json` registries are the actual sources of truth for what ships and what
  mirrors what - read those files rather than this one when in doubt, since this file is notes,
  not a manifest.

## Left undone, on purpose

- **A full unattended night against a real (non-fixture) project.** This is the integration
  plan's own step 9 and the one thing that genuinely needs hours of GPU and model time; it was
  not attempted in this session.
- **OpenHands.** Registered as `documented_not_built` in both registries, on the operator's own
  choice (asked directly rather than guessed) - there is no `.openhands/` convention verified
  on this machine, so nothing beyond that honest placeholder was built.
- **Repointing the one-shot editing tools** (`sync_manual.py`, `manual_project_section.py`)
  at the repo's own `MANUAL.md`. They still read `Path.home() / ".config/aider/MANUAL.md"`.
  They are not part of the repeatable build pipeline (`build_kit.py` -> `finish_kit.py` ->
  `newproject_ps1.py` -> `patch_setup.py`), so this was left rather than touched under time
  pressure; low risk, since re-running either against the external copy at worst edits a file
  nobody reads anymore, but worth fixing before either is run again.
- **The dedicated README.md per-skill subsection and file-tree diagram** that other skills
  carry (see `### recommendation-letter` for the pattern) were not added, only the inventory
  table row - `SKILL.md` carries the rest.

## Read first, next time

`PROGRESS.md` (repo root) for phase-by-phase status and evidence.
`docs/superpowers/todo/2026-09-04-aider-kit-integration-plan.md` for the original plan this
session executed against (sections 4.4-4.6, 8.5, 8.6 record defects measured after that plan
was written and are the ones already fixed in the sources this session copied in).
