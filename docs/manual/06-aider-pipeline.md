# Aider Nightly Pipeline & Student Kit

Chapter 06 of the ResearchTools manual. Back to [table of contents](../../README.md).
Skill row: [04-skills.md](04-skills.md). Local-delegation counterpart: [10-agents.md](10-agents.md).

## Overview

A second, independent local-coding harness that needs no Claude Code: two local Ollama models
(a writer that codes and tests, a reviewer that never edits, gated by measured token budgets)
run one aider process per plan overnight, driven by `aider-plan.ps1` / `aider-night.ps1`. Owns
the packaging pipeline that assembles the student-facing `aider-kit.zip` from this skill's own
canonical sources.

Full manual, Ollama tuning reference, worked example, and continuity notes:
[docs/aider-setup.md](../aider-setup.md).

## `local-coder` vs. the `aider-setup` pipeline - two lanes, not a duplicate

Both generate code on a local model for free, and it is worth being precise about why one did
not replace the other. `local-coder` is **synchronous, in-session, single-step**: the cloud
orchestrator (loop-engineer, a plan step) hands it one precise task - implement this function
against this failing test - and reviews the result immediately, inside a running Claude Code
session. `aider-setup` is **asynchronous, unattended, whole-plan**: it runs a full night with
Claude Code closed entirely, driving one aider process per plan file for hours with no one
watching, then leaves an audit report for the morning. Neither can stand in for the other -
`local-coder` cannot run when nobody is present to dispatch and review it, and Aider's nightly
driver has no synchronous entry point a mid-session orchestrator could call. The aider-kit
integration deliberately left `local-coder`'s definition, model resolution, and prompt untouched
for this reason.

## The nightly run

`aider-setup` is not a wrapper around `local-coder`, and does not go through Claude Code at
all once installed - the point, since it is built to run when Claude Code and every model it
drives are both closed. Two local Ollama tags do the work: a writer that codes its own tests,
and a reviewer, sandboxed and content-hash checked, that can never edit code however its
prompt is answered. The driver (`aider-plan.ps1`) runs **one aider process per plan file**,
which is what drops the context window between plans; after each plan it runs the test suite,
then the reviewer, which writes `audit.md` and may reopen the plan for one more bounded round.
A plain `cmd` entry point (`aider-night.ps1`/`.bat`) starts a night, holding a wake lock so
Windows' Modern Standby does not throttle an unattended run, and pushes a branch at the end -
merging to a protected branch stays a human decision, made the next morning after reading
`audit.md`. The rules every model follows (`config/rules.md`) are generated at build time from
this repository's own `.claude/rules/*.md`, so they cannot drift from what every other harness
enforces. Setup, tuning, and rebuilding the student-facing kit: see
[.claude/skills/aider-setup/SKILL.md](../../.claude/skills/aider-setup/SKILL.md) and its `MANUAL.md`.

---
[← 05 Security audit](05-security-audit.md) | [Table of contents](../../README.md) | [07 rt-observe & dashboard →](07-rt-observe-dashboard.md)
