# Aider Nightly Pipeline & Student Kit

Chapter 11 of the ResearchTools manual. Back to [table of contents](../../README.md).
Skill row: [06-skills.md](06-skills.md). Local-delegation counterpart: [05-agents.md](05-agents.md).

## Overview

A second, independent local-coding pipeline that needs no interactive harness: two local Ollama models
(a writer that codes and tests, a reviewer that never edits, gated by measured token budgets)
run one aider process per plan overnight, driven by `aider-plan.ps1` / `aider-night.ps1`. Owns
the packaging pipeline that assembles the student-facing `aider-kit.zip` from this skill's own
canonical sources.

Full manual, Ollama tuning reference, worked example, and continuity notes:
[docs/aider-setup.md](../aider-setup.md).

## `local-coder` vs. the `aider-setup` pipeline - two lanes, not a duplicate

Both generate code on a local model for free, and it is worth being precise about why one did
not replace the other. Since 2026-10-17 a `local-coder` dispatch executes **one whole plan**. The
prompt carries a line `PLAN: <path>`, the plan opens with a header (`executor`, `tier`,
`bounds`), and the hook `local-coder-dispatch-guard.py` refuses a dispatch with no valid plan.
The agent ticks `progress.md` with its three marks, audits nothing and never commits. It is
**synchronous and in-session**: the calling harness reviews the branch afterwards. `aider-setup`
is **asynchronous, unattended and multi-plan**: it runs a full night with every interactive
harness closed, driving one aider process per plan file for hours with no one watching, with its
own writer and reviewer models, then leaves an audit report for the morning. So the difference
is no longer one step against many. It is one plan in a session, reviewed by the calling
harness, against several plans or a night with no one present. Neither can stand in for the
other: `local-coder` cannot run when nobody is present to dispatch it and review the branch, and
aider's nightly driver has no synchronous entry point a mid-session orchestrator could call. The
original aider-kit integration left `local-coder`'s definition, model resolution, and prompt
untouched for this reason.

<!-- local-coding:begin -->
**Plans and the local coding contract.** Since 2026-10-17 every plan, for aider or for
`local-coder`, opens with a header naming `executor`, `tier` and the review bounds. The aider
driver neither validates nor uses those three keys: it only skips a closed leading front matter
block when it lists the files a plan names (`Get-PlanTargets` in `aider-plan-core.ps1`, proven by
`verify-aider-plan.ps1`). The header is validated by `plan_contract.py` in the harness that
writes the plan. The size limits the driver enforces come from `context-budget.json`, which is
also the single source for every project:

| File | Ceiling in tokens |
|---|---:|
| `spec.md` | 4000 |
| `plan.md` | 4000 |
| `progress.md` | 2048 |
| `audit.md` | 4096 |

The tier-to-role table lives in `plan-tiers.json` and applies to `local-coder`, not to aider,
whose writer and reviewer models are chosen in its own configuration. The review-loop bounds of
R35 do not govern aider's internal writer-reviewer loop. They govern the `/code-review` and
`/security-review` run by the calling harness on the branch the night pushes, before any pull
request, and the night never merges. During a run the Real-Time tab of the dashboard shows the
run's fixed cost and task budget ([chapter 12](12-rt-observe-dashboard.md)). The choice between
the two executors is described in [chapter 10](10-local-coding.md).
<!-- local-coding:end -->

## The nightly run

`aider-setup` is not a wrapper around `local-coder`, and does not go through an interactive
harness at all once installed - the point, since it is built to run when every interactive
harness is closed. Two local Ollama tags do the work: a writer that codes its own tests,
and a reviewer, sandboxed and content-hash checked, that can never edit code however its
prompt is answered. The driver (`aider-plan.ps1`) runs **one aider process per plan file**,
which is what drops the context window between plans; after each plan it runs the test suite,
then the reviewer, which writes `audit.md` and may reopen the plan for one more bounded round.
A plain `cmd` entry point (`aider-night.ps1`/`.bat`) starts a night, holding a wake lock so
Windows' Modern Standby does not throttle an unattended run, and pushes a branch at the end -
merging to a protected branch stays a human decision, made the next morning after reading
`audit.md`. The rules every model follows (`config/rules.md`) are generated at build time from
this repository's own `.claude/rules/*.md`, with the longest ones abridged. The file currently
covers R0 to R27 only (its header reads "Rules: 28 (R0-R27)"), so the night's models do not see
the rules after R27, among them R35 (review bounds), R36 (a skill for every step) and R38 (the
plan header). R28 to R38 were never synced into it, so it was not regenerated with the local
coding contract. A dry run of the generator on 2026-10-17, which
writes nothing, reports 39 rules, R0 to R38, but with no tokenizer in that interpreter no cap was
applied. The capped regeneration measured about 5153 tokens against the 3500 ceiling of the
file on 2026-10-17 (recorded in `IMPROVEMENTS.md`, not re-measured here), which is why it is a
decision for the aider kit. Setup, tuning, and rebuilding the student-facing kit: see
[.claude/skills/aider-setup/SKILL.md](../../.claude/skills/aider-setup/SKILL.md) and its `MANUAL.md`.

---
[← 10 Local coding and the cloud](10-local-coding.md) | [Table of contents](../../README.md) | [12 rt-observe & dashboard →](12-rt-observe-dashboard.md)
