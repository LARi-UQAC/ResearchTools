# Changelog

All notable user-facing changes to this project. Format loosely follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

This file is for someone following releases. For the dated, engineering-level decision log
(what broke, what was measured, why a fix looks the way it does), see
[IMPROVEMENTS.md](IMPROVEMENTS.md).

## [Unreleased]

### Added
- `wp-portfolio-sync` skill: migrates a researcher's final CIHR / Canadian Common CV XML
  export into their WordPress portfolio once, through the REST API, gated by an
  anti-fabrication check before any write. `cihr_cv.py` now recognises both French and
  English CCV export labels. `push_wp.py` snapshots a page's prior content to
  `<data-dir>/backups/` immediately before every write, and cookie authentication can write
  as well as read when `WP_NONCE` is set. `wp-portfolio-agent` (`/portfolio`) drives the
  pipeline with two separate approval pauses, one before the dry run and one before the
  live push.

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
