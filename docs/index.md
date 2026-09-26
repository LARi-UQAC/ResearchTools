# ResearchTools Documentation

This page is a landing point for GitHub Pages (Settings → Pages → Deploy from a branch →
`main` / `/docs`) — enabling that setting turns this folder into a browsable site with no
build step. Nothing here duplicates the manual; every link below points at the same file a
Claude Code session or a plain GitHub browse would read.

## Start here

The manual lives in [`manual/`](manual/00-purpose.md), one chapter per topic:

| # | Chapter |
|---|---|
| 00 | [Purpose & overview](manual/00-purpose.md) |
| 01 | [Installation](manual/01-installation.md) |
| 02 | [Profiles & environment](manual/02-profiles.md) |
| 03 | [Token management](manual/03-token-management.md) |
| 04 | [Skills](manual/04-skills.md) |
| 05 | [Security audit](manual/05-security-audit.md) |
| 06 | [Aider nightly pipeline](manual/06-aider-pipeline.md) |
| 07 | [rt-observe & dashboard](manual/07-rt-observe-dashboard.md) |
| 08 | [Commands](manual/08-commands.md) |
| 09 | [ThesisTracker integration](manual/09-thesistracker-integration.md) |
| 10 | [Agents](manual/10-agents.md) |
| 11 | [File locations](manual/11-file-locations.md) |

## Deep-dive references

Longer, single-topic documents that a manual chapter points into rather than repeats:

- [aider-setup.md](aider-setup.md) — the aider nightly pipeline, full manual
- [rt-observe.md](rt-observe.md) — the toolkit-state dashboard, full reference
- [authoring-and-mirrors.md](authoring-and-mirrors.md) — adding or editing an agent, skill,
  or command, and regenerating the per-tool mirrors
- [contributor-notes.md](contributor-notes.md) — shared conventions (English-only definition
  files, agent/skill layout, local-model routing, git/GitHub workflow)

## Elsewhere in the repository

- [../README.md](../README.md) — repository root entry point
- [../Architecture.md](../Architecture.md) — this repository's own 7-layer component
  architecture
- [../NEW_ARCHITECTURE.md](../NEW_ARCHITECTURE.md) — the architecture shared with the
  sibling repository ThesisTracker
- [../CONTRIBUTING.md](../CONTRIBUTING.md) · [../CODE_OF_CONDUCT.md](../CODE_OF_CONDUCT.md)
