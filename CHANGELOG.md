# Changelog

All notable user-facing changes to this project. Format loosely follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

This file is for someone following releases. For the dated, engineering-level decision log
(what broke, what was measured, why a fix looks the way it does), see
[IMPROVEMENTS.md](IMPROVEMENTS.md).

## [Unreleased]

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
