# Changelog

All notable user-facing changes to this project. Format loosely follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

This file is for someone following releases. For the dated, engineering-level decision log
(what broke, what was measured, why a fix looks the way it does), see
[IMPROVEMENTS.md](IMPROVEMENTS.md).

## [Unreleased]

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
