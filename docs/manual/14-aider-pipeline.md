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

## `local-coder` and the `aider-setup` pipeline - one harness at two scales

Since 2026-11-06 `local-coder` no longer has a driver of its own. It is the aider kit run on **one
plan**: the plan is mounted as the only plan of a small kit project outside the repository (`new-project.ps1`), `aider-plan.ps1` runs it with the kit's writer
model and its required reviewer audit, and the kit starts without a wrapper. The per-stage skills
(write, audit, reopen) are mandatory, for a single plan as for a night: there is no switch to turn them off. `aider-night.ps1` is
the same engine for **several plans or an unattended night**: it adds the working branch, the wake
lock and the optional push. A plan opens with a header (`executor`, `tier`, `bounds`) validated by
`plan_contract.py`. The R35 review is done by the cloud session before the pull request, and a
finding becomes an `- [ ] audit:` line that the kit runs again. The old text driver
(`local_coder_driver.py`) is retired: it asked a small model for tool-like output in plain text and
its replies were refused.

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
run's fixed cost and task budget ([chapter 10](10-rt-observe-dashboard.md)). The choice between
the two executors is described in [chapter 11](11-local-coding.md).
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
`audit.md`. The rules every model follows (`config/rules.md`) are 26 coding rules curated by hand
in `config/rules-local/aider-kit.md` since 2026-11-07, in plain words and with no reference to this
toolkit: constants and configuration, errors, tests, function headers, naming, comments and layout.
The generator only assembles that file. Rules about documents, agents or process (the review bounds,
the plan header, the skill-first rule) are left out on purpose, because a model that writes code
cannot apply them. The file measures 1618 tokens
(`token_count.py`, 2026-11-07) against a ceiling of 2000. Setup, tuning, and rebuilding the student-facing kit: see
[.claude/skills/aider-setup/SKILL.md](../../.claude/skills/aider-setup/SKILL.md) and its `MANUAL.md`.

---
[← 13 3D CAD design, CNC, 3D printing](13-cad-design.md) | [Table of contents](../../README.md) | [15 Security audit and guards →](15-security-audit.md)
