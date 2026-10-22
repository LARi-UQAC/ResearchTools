# Changelog

All notable user-facing changes to this project. Format loosely follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

This file is for someone following releases. For the dated, engineering-level decision log
(what broke, what was measured, why a fix looks the way it does), see
[IMPROVEMENTS.md](IMPROVEMENTS.md).

## [Unreleased]

### Added
- Manual: four new chapters, `07 Hooks and guards`, `08 Rules and conventions`, `09 Harnesses and
  mirrors` and `15 Maintenance, checks and CI`, and two placeholder chapters, `17 PCB design` and
  `18 3D CAD design`. The chapters are reordered so that commands, agents and skills come first
  (04 Commands, 05 Agents, 06 Skills), and the chapter files are renamed to match. The links in
  `README.md`, `docs/index.md`, `mkdocs.yml` and four documentation tests follow.
- Manual: the SkillSpector scan now covers all 25 skills (289 findings, rated by rule family in
  chapter 13), and the open findings it confirmed are listed there.
- Manual: chapter 02 lists every third-party Python library of the two environments, `.venv-skills`
  and `.venv-docs`, one row per library with its installed version, the requirements file that
  declares it and whether `setup.ps1 -InstallPython` installs it. Built from the `import`
  statements of all the Python files. Libraries that the code imported and no file declared are now
  declared: `requests` (extract-statistic), `PyMuPDF` (pdf2md, paper2talk), `playwright-stealth`
  (scopus), `cryptography` (form-service), `tiktoken` (loop-engineer), and four new requirements
  files for `word2latex`, `drawio2tikz`, `rt-observe` and `opt-local-stt-vram`.
- Manual (corrections): the environment-variable table of chapter 02 no longer documents the retired Gemini 2.0
  Flash and GitHub Models routes, and lists `COPILOT_TOKEN`, `GH_OAUTH_TOKEN` and the other
  variables the toolkit reads. Chapter 05 no longer documents the unwired `--loop --budget`
  option, chapter 06 no longer gives a `/drawio2tikz` command that does not exist, and the counts
  in chapters 00 and 16 are 25 skills, 21 agents and 32 commands.
- `.\setup.ps1 -Update` updates an existing installation in one command. It asks the domain
  profile, whether to install GitHub Copilot at user level and whether to run the offline suite
  first, then runs the global configuration with the hook update, the Claude Code links,
  `install.ps1 -Profile`, the suite when asked, `install-junctions.ps1 -Sync` and the read-only
  deployment check, and ends with what is still to do by hand. `-Update -Preview` shows every
  step and writes nothing. Chapter 01 of the manual describes it.
- `.\setup.ps1 -UpdateHooks` replaces the `command` and `statusMessage` of a hook entry of
  `~/.claude/settings.json` that the template declares and whose text changed, which `setup.ps1`
  could not do before. A text edit with a timestamped backup, checked before and after writing.
  Without the switch, `setup.ps1` reports how many entries differ.

- `.\setup.ps1 -Update -KeepHooks 'AUTO-SYNC CHECK'` (also with `-UpdateHooks`) leaves a hook entry
  you changed on purpose on this machine exactly as it is: no edit, no backup. The names are the ones
  the output prints, case ignored, brackets optional.

- `scripts/test/run-all-checks.ps1` runs the offline suite and the `verify-*.ps1` of `scripts/test` in one go (not the five
  verifiers of `scripts/local` and the aider-setup skill), runs
  them all even when one fails, and says which failed. `run-offline-tests.ps1` alone never covered
  the PowerShell verifiers. It is part of the update procedure in manual chapter 01.
- `scripts/test/finish-branch.ps1` cleans up after a merged pull request: worktree, local and
  remote branch, plans folder. Dry run until `-Yes`, never `--force`, and it refuses an unmerged
  branch, unpushed commits, a commit pushed to origin after the merge, a modified main clone, a
  dirty worktree, git-ignored files in it (unless `-DiscardIgnored`) and a worktree holding a link. It is the last step in
  the figure of manual chapter 12.

### Fixed
- `setup.ps1 -Update` replaces changed hook commands after the sync instead of before it, skips an
  entry whose script the sync held, skips the hook update when Git Bash or Node.js was not found,
  reports a differing `matcher` or `timeout`, counts a failed `settings.json` edit in its exit code,
  and restores the exact bytes it read (BOM included), not a stale `settings.json.bak`, after a failed
  edit. A held hook config `.json` holds its hook, and an entry with no `statusMessage` is a note, not
  a difference. `-StrictExit` also fails when another session holds the sync lock. `install-junctions.ps1 -Sync
  -StrictExit` (used by `-Update`) exits 1 when the sync throws; the SessionStart form still exits 0.
- `finish-branch.ps1` queries the exact ref on origin and refuses when origin cannot be queried,
  rejects a branch name that starts with a dash, finds links without walking through junctions,
  keeps `gh` warnings out of the JSON it parses and leaves the caller's shell in its own folder.
- `install-junctions.ps1 -Sync -WhatIf` no longer writes. It ignored `-WhatIf` and copied agents
  into `~/.claude` while claiming to preview.
- `install-junctions.ps1` (the links step) no longer calls a plain copy of an agent a `[CONFLICT]`
  when it is byte-for-byte the repository file. `-Sync` makes such copies when Windows refuses a
  link, and the links step then exited 1 on them, so `setup.ps1 -Update` ended in failure on a state
  the sync fixes. A differing copy is still a conflict.
- In `setup.ps1 -Update` the links step is advisory and the final deployment check judges the
  result. In `-Update -Preview` the check lists what the real run would fix and does not fail the
  preview.

### Changed
- Chapter 06 of the manual (the aider pipeline) is brought in line with the local coding
  contract. It names no orchestrating product, so "Claude Code" becomes "interactive harness"
  there, in `docs/aider-setup.md` and in one cell of chapter 12. It says a `local-coder` dispatch
  executes one whole plan, that the aider driver neither validates nor uses the plan header, that
  the R35 bounds govern the review of the pushed branch and not aider's internal loop, and that the
  generated `rules.md` covers R0 to R27 only, so the night's models do not see R35, R36 or R38.
- Chapter 12 of the manual and its process figure are corrected. Memory is consulted through
  `local-writer` before the brainstorm, the review loop ends when the branch is safe to merge (or
  a bound is reached and you are asked), a last memory upkeep writes the lessons to the vault and
  updates the graph, and the wrapper is described as a low-cost cloud model with no model named.
  The chapter now carries the table of when memory is read and written.
- One table in `workflows.md` ("When memory is read and written") now says when the vault and the
  graph are read and written through `local-writer`, who must not read them, and how a write is
  verified. The dispatch stays in the background and the session adapts when the one-line result
  arrives. The review loop of R35 also stops when the branch is safe to merge (suite green, no
  Critical or High finding after re-grading, minors deferred), in every copy of the rule. The hook
  enforces the bounds only, so the findings re-graded as minor are listed in the PR body.

### Fixed
- Memory work through `local-writer` is quiet. The Stop hook reminder shrinks from about 1900 to about 500 characters, tells the session not to narrate the dispatch or repeat the agent's answer unless it reports a failure, and its status message no longer carries detail. `local-writer` returns one line on success and the full account only on failure. The live `settings.json` is not changed by this: replace its Stop entry with the template's by hand, since setup recognises the entry by its first script name and treats the old one as already present.
- The published documentation site no longer has dead cross-links. 73 links from pages
  under `docs/` to files outside it (`README.md`, `Architecture.md`, `.claude/...` rules and
  skills) returned 404 on the site because MkDocs only serves `docs/`. A build hook,
  `scripts/docs/mkdocs_hooks.py`, now sends those links to their GitHub page at build time,
  and the Markdown keeps its relative links. Heading anchors written for GitHub, such as
  `#scopus--scopus-academic-search`, now resolve too. `mkdocs build --strict` goes from 73
  warnings to none. The site updates when the owner next runs `mkdocs gh-deploy` from `main`.
- Heading ids on the site now follow GitHub's slug (a removed dash or slash leaves a double dash),
  so 49 of the 142 heading ids change. A bookmark to the old id of one of those headings lands at
  the top of its page. A repeated heading keeps MkDocs's `_1` suffix where GitHub writes `-1`.

## [0.3.0] - 2026-10-17

### Added
- Rule R38: any coding request beyond one step gets plan files with a header (`executor`,
  `tier`, review `bounds`) before any code. `plan_contract.py` validates the header, the file
  limit of the tier and the size ceilings, and resolves the tier to a resolver role. Every
  step of the process names a skill (R36): brainstorming, writing-plans, executing-plans.
- Review-loop bounds (R35 as amended): `loop_bounds.py` stores `max_rounds`, `max_tokens` and
  `plateau` per branch, and the `review-loop-guard.py` hook refuses `/code-review` or
  `/security-review` past a bound. `token_count.py` counts tokens exactly when tiktoken is
  there and says "estimate" otherwise.
- `local-coder-dispatch-guard.py`: refuses a `local-coder` dispatch with no valid plan. A
  local-coder run now executes one whole plan.
- A role's context window comes from its adoption (`model_resolver.py --adopt-role ... --num-ctx`),
  for the bridge and the budget; `claude-ollama` sets `CLAUDE_CODE_MAX_CONTEXT_TOKENS`.
- Dashboard: `local_calls` and `rounds` sections and Real-Time lanes for each bridge role,
  aider's task budget, plan tasks and review loops.
- Manual chapter 12, "Local coding and the cloud", with its flowchart.

### Changed
- The two hooks only protect a machine whose live `settings.json` declares them; add the two
  entries from `settings.template.json` and see each fire once. The window cap of
  `CLAUDE_CODE_MAX_CONTEXT_TOKENS` with `claude-local` is untried.

## [0.2.2] - 2026-10-17

### Fixed
- `install-junctions.ps1 -Sync` no longer holds hook `.json` configuration files forever: the
  green stamp now hashes them (one shared selection, `scripts/lib/rt-stamp.ps1`), so a hook
  and its settings travel together once the suite is green. A stamp written before this change
  has no `.json` entries, so run `scripts/test/run-offline-tests.ps1` once after pulling.
- `setup.ps1 -InstallPython` would have downgraded the installed `pypdf` to 6.15.0 (11 known
  CVEs). Every `pypdf` pin in the repository (`paper2talk`, `narrative-cv`, `form-service`,
  `deploy/form-service`) is now 6.19.0, which `pip-audit` reports clean, and
  `verify-python-env.ps1` fails when those pins disagree. The `deploy/form-service` tests
  (84) pass under 6.19.0.
- `check-deployment.ps1` compared hook `.py` files only, so held hook configs read "all in
  step". It now compares the `.json` files too, through the same selection as `-Sync`.

## [0.2.1] - 2026-10-16

### Added
- `.github/workflows/review.yml`: on every same-repository pull request, a headless
  `claude-code-action` runs `security-review` and `code-review` at high effort and posts one
  Critical/High/Medium/Low list as a PR comment. A second job copies it to the linked Issue
  with no Anthropic key. It needs a repository secret `ANTHROPIC_API_KEY`, is billed per run,
  and is not a required check (#67).
- `worktree-link-guard.py`: a PreToolUse hook that refuses `git worktree remove` on a worktree
  holding a junction or symbolic link, because the removal follows the link and empties its
  target. It follows `cd`, `pushd`, subshells and `~`, and fails silent when its config is
  missing. It only protects a machine whose `settings.json` declares it (#77).
- Rule R37: never link a dependency folder (`.venv-skills`, `node_modules`) into a worktree.
  Reproduced: a plain `git worktree remove`, with no `--force`, empties the target of a
  junction that git ignores (#77).
- `setup.ps1 -InstallPython -Python <path>`, and `scripts/lib/rt-venv.ps1` as the single
  interpreter resolver (#77).

### Changed
- Every launcher (`run-offline-tests`, `rt-dashboard` `.ps1`/`.sh`, `run-drill`,
  `vault-daemon-autostart`, `tune-new-model`, `claude-switch`, `check-deployment`) finds the
  main clone's `.venv-skills` from a worktree through git, so a worktree needs no link (#77).
- A missing, empty or broken `.venv-skills` is now a refusal that names every path looked at
  and the rebuild command, instead of a silent fall back to the first `python` on `PATH`.
  `-AllowPathFallback` (`--allow-path-fallback` for the shell launcher) accepts `PATH`
  knowingly. A root `.venv` is no longer used. The green stamp records which interpreter
  produced it and is withheld when an interpreter outside the repository's own environment
  left suites NOT RUN (#77).
- `setup.ps1 -InstallPython` chooses its base interpreter instead of taking the first on
  `PATH`: it refuses another account's Python or one whose `python -m venv` fails, builds in
  the main clone, reuses an existing environment, and installs the `scopus` and
  `extract-statistic` dependencies (without `docling`) from a data list, then runs
  `pip-audit` (#77).
- The `rt-dashboard` Repository panel shows the suite interpreter, or why there is none (#77).

### Fixed
- `.venv-skills` of the main clone was emptied on 2026-10-06 and the loss stayed unnoticed
  for a week. The cause is reproduced and closed by the changes above (#76, #77).

## [0.2.0] - 2026-10-16

### Added
- `wp-portfolio-sync` skill: migrates a researcher's final CIHR / Canadian Common CV XML
  export into their WordPress portfolio once, through the REST API, gated by an
  anti-fabrication check before any write. `cihr_cv.py` now recognises both French and
  English CCV export labels. `push_wp.py` snapshots a page's prior content to
  `<data-dir>/backups/` immediately before every write, and cookie authentication can write
  as well as read when `WP_NONCE` is set. `wp-portfolio-agent` (`/portfolio`) drives the
  pipeline with two separate approval pauses, one before the dry run and one before the
  live push.
- `pdf2md` skill (thesis, article, talk) and a local-model fallback reviewer for the
  `deliberation` skill (#69).
- `professor-expertise-finder` skill, agent and `/expertfinder` command (#63).
- `rt-dashboard` voice panel: memory query, then answers in parts, vault first and then the
  project's own code graph (#34, #49).
- `form-service`: stateless `POST /cv/build` endpoint (#47).
- `scripts/local/claude-switch.ps1`: switch a Claude Code session between cloud, Ollama and
  AugureAI, without the LiteLLM proxy (#61).
- Rule R36: skill-first execution, a missing skill is authored here and never installed (#44).

### Changed
- License switched from MIT to PolyForm Noncommercial 1.0.0 (#52).
- Privacy guard: global pre-commit and pre-push hooks, a CI scan, rule R34 and a
  machine-local deny list of real names with a fixture-path check (#40, #71).
- Personal data removed from tracked files: `{{HOME}}` profile path, fictitious fixtures (#37).
- Stale mirrors removed and harness mirrors regenerated, including the Copilot CLI agent
  and VS Code user prompt for the new agent and command (#28, this release).

### Fixed
- Vault daemon survives reboots and a slow Ollama start (#42).

### Documentation
- Student consent form and student-data flows in `NEW_ARCHITECTURE.md` (#55), privacy-guard
  playbook (#57).

## [0.1.0] - 2026-09-26

First tagged version.

### Added
- Documentation restructured from a single 1300-line `README.md` into book-style chapters
  under `docs/manual/` (00-purpose through 11-file-locations), mirroring `Architecture.md`'s
  own layer split.
- GitHub presentation: badges, an `rt-observe` dashboard screenshot as a hero image, a
  Mermaid "at a glance" diagram, `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `SECURITY.md`,
  issue and pull-request templates, `.github/CODEOWNERS`, `.editorconfig`, `.gitattributes`.
- Repository "About" description and topics set on GitHub.

### Notes
- 15 skills, 15 agents, 25+ commands for academic writing (LaTeX, Scopus validation,
  paper/thesis auditing, grant-template conversion) and a local-model-backed dev loop.
