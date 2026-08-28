---
name: loop-engineer
description: "Budget-bounded develop-and-improve loop: design, plan, code, comment, test, review, score, and correct in a loop until a composite quality gate is met or a hard budget/iteration/no-progress stop is hit. Keeps the best cloud model (Fable 5) as orchestrator and judge, uses cheaper cloud tiers (Opus to plan, Sonnet to execute and review) for the actions, and delegates code and comments to the local-coder / local-writer agents over the Bash bridge so the heavy generation is free. Trigger on: /loopdev, 'loop engineering', 'run the improve loop', 'develop this until the score/budget', requests to iterate on code under a cost cap with an automatic quality gate."
allowed-tools: [Read, Write, Edit, Bash, Skill, Agent]
permissions: [read]
---

# Loop engineer - budget-bounded develop-and-improve loop

Run one feature through a design -> plan -> code -> comment -> test -> review -> score ->
correct loop, repeating the evaluate/correct/rescore sub-cycle until a composite quality gate
is met or a hard stop is hit. The point is high-quality code at a fraction of the cloud cost:
the best model judges, cheaper tiers act, and the local models generate.

The score contract and the stop rules are in `scripts/loop_audit.py` (the scorer) and
`scripts/loop_engineer.py` (the driver). Read `references/LOOP.md` before a live run - it is
the contract for the pipeline, the model tiering, and the safety gates.

## Option contract

```
/loopdev --budget <max_usd> [--score <min_score>] [--max-iters N] [--patience N] [--no-merge-pr] "<feature request>"
```

- `--budget` (required): hard cost cap in USD. Maps to the Agent SDK `max_budget_usd`; the run
  stops with `error_max_budget_usd` when hit.
- `--score` (default 90): the aggregate threshold inside the composite gate. A literal 100 is
  opt-in and, because zero findings across the reviewers is asymptotic, will usually stop on
  budget rather than on score.
- `--max-iters` (default 10), `--patience` (default 2): the iteration cap and the no-progress
  window.
- `--no-merge-pr`: stop at "ready to merge" without opening a PR.

## Pipeline (per feature, branch-isolated)

1. Design - `brainstorming` on **Fable 5** (judgment).
2. Plan - `writing-plans` on **Opus**.
3. Branch `feat/<slug>` - a **Sonnet** subagent with write-capable git (never the local model).
4. TDD - `test-driven-development` on **Sonnet**: write the failing tests for the acceptance
   criteria first.
5. Code - the **local-coder** agent (the resolver's coder-role model over the bridge) implements against the tests.
   At task start it consults the vault (GardeFous / Apprentissages for the module, the project
   `Decisions.md` / `CodeReview.md`) and folds the constraints into the bridge prompt.
6. Comment / doc - the **local-writer** agent (the resolver's writer-role model over the bridge). It consults the
   vault's `Methodes` and prior writing decisions the same way.
7. Run tests + review panel - **Sonnet** runs `rtk pytest` (deterministic green/red) and the
   installed reviewers on the diff: `/code-review`, `/security-guidance`, `pr-review-toolkit`
   (silent-failure-hunter, type-design-analyzer), `systematic-debugging`. Each emits findings.
8. Score - `scripts/loop_audit.py` (run by **local-coder**, deterministic) aggregates the
   findings + test result + betterleaks/pip-audit hook status into per-axis sub-scores, an
   aggregate 0-100, and the gate booleans; appends to the ledger.
9. Correct - `writing-plans` then `executing-plans` on the findings (**Sonnet** + local-coder).
   On error recovery / at the checkpoint, local-coder re-consults the vault so the learning
   captured last iteration is not repeated. `executing-plans` itself never reads the vault.
10. Doc / journal - **local-writer** is the single vault writer: it captures a project log as
    an appended dated section in the project's own `Decisions.md` (and `CodeReview.md`) under
    `10_Projets/<nature>/<projet>/`, and any reusable learning as an atomic note under
    `30_Ressources/<Technology>/`. There is no daily note. It drafts the note and deposits it in
    `~/.claude/obsidian-outbox/` with a first-line directive; the `obsidian-outbox-flush.py` hook
    is the only write path for that new or appended content - it writes through the filesystem
    and verifies the effect by file size, never a fallback. The one sanctioned exception is
    `vault_consolidate.py --apply --yes`, an in-place maintenance edit of links in notes that
    already exist, run by this same writer through the filesystem and verified by re-reading the
    file. It also updates `/doc` output, `PROCESS.md`, and memory.
    `local-coder` never writes to the vault - it hands any learning to local-writer. Captures
    also fire at the error/checkpoint (step 9) and gate (step 12), not only here.
11. Convergence check - the loop wraps steps 7 -> 9 -> 8. Stop on the composite gate, the
    budget cap, the max-iterations cap, a no-progress plateau, or a security regression.
12. Human-gated finish - on a gate pass, local-coder commits + pushes the branch and opens a
    PR (token permitting); the merge to a protected branch waits for explicit user confirmation.

## Vault reads and writes (who does what, when)

- **Reads.** Steps 1-2 (Design / Plan, on Fable 5 / Opus) consult the vault and bake the
  learnings into the plan (orchestrator-mediated). Once the loop is executing, vault reads are
  done ONLY by the local agents (steps 5, 6, 9); `executing-plans` and the Sonnet review panel
  do not read.
- **Writes.** `local-writer` is the single vault writer: it drafts the note and deposits it in
  `~/.claude/obsidian-outbox/` with a first-line directive; the `obsidian-outbox-flush.py` hook
  is the only write path for creating or appending content - it writes through the filesystem and
  verifies the effect by file size, never a fallback. The one sanctioned exception is
  `vault_consolidate.py --apply --yes`, an in-place maintenance edit of existing links, run by
  this same writer through the filesystem and verified by re-reading the file, never through the
  Obsidian CLI. `local-coder` reads only and hands learnings to local-writer. No two agents write
  concurrently, and no external tool writes the same vault.
- **Loop closure.** A capture always lands first in the outbox, not directly in the vault; the
  `obsidian-outbox-flush.py` hook only runs at SessionStart and SessionEnd, so within a running
  session a note written at iteration N would otherwise sit unflushed. `local-coder`'s outbox
  scan (see its definition) closes that gap by reading pending outbox files directly at the next
  iteration. **The hook writes through the filesystem and verifies the effect by file size, with
  no dependency on the Obsidian process; the note lands regardless of whether Obsidian is running,
  and Obsidian will reload it the next time it runs.**

See the "Capture de connaissances" and "Lecture du coffre" sections of the global `CLAUDE.md`.

## Stop gate

Composite (default): `tests green AND no CRITICAL AND no HIGH AND aggregate >= min_score`.
Security is a hard floor: any CRITICAL finding, a betterleaks block, or a CRITICAL pip-audit
CVE fails the gate regardless of the aggregate. Hard stops: budget cap, max iterations,
no-progress plateau, security regression vs the previous iteration.

## Reviewers

Installed / first-party only: `/code-review`, `/security-guidance`, `pr-review-toolkit`,
`systematic-debugging`, plus the betterleaks and pip-audit hooks. `tech-debt` and
`ai-firstify` are optional add-ons the user installs deliberately (`ai-firstify` must be run
audit-only inside the loop so it scores rather than restructures code); they are off by
default.

## Authoring loop (ScholarEval-gated variant)

The same loop applies to writing, not just code. Instead of the code reviewers and
`loop_audit.py`, the score comes from the `scholar-evaluation` skill (prose quality), and the
actors are the authoring agents. This variant is driven by the `authoring-loop` agent (run it
by name at the top level of a session). Use it to iterate a review, paper section, thesis
chapter, or reviewer response up to a target ScholarEval score under a budget.

The five steps:

1. **Define the subject** - the topic (new review) or the draft to improve, the target `.tex`,
   `min_score` (ScholarEval overall), and `max_budget`.
2. **Author** - dispatch the matching authoring agent (`/litreview` / `scopus-researcher`,
   `latex-writer`, `/replyreviewer` / `reviewer-response`, etc.) on the best cloud model
   (**Fable 5**) to write or revise against the current improvement plan.
3. **Audit** - run the `scholar-evaluation` skill on the draft on a cheap model (**Sonnet** or
   **Haiku**) to get the ScholarEval overall score and the improvement plan.
4. **Loop** - go back to step 2 until the overall reaches `min_score`, the spend reaches
   `max_budget`, or the score plateaus. A revision that lowers the score is discarded (keep the
   previous draft) rather than carried forward.
5. **Memory** - `local-writer` (Haiku wrapper + the resolver's writer-role model) records what was learned
   (what raised the score, what plateaued, residual weaknesses) to the project memory.

Differences from the code loop: the gate is the single ScholarEval overall (plus a regression
guard) rather than the multi-axis code score with a security hard floor; the budget is advisory
(the orchestrator tracks `/usage` and the ledger and stops) unless the run is wrapped in this
skill's SDK driver, which is the way to get a hard `max_budget_usd` cap. See
`.claude/agents/authoring-loop.md` for the full pipeline, routing, and session-resilience rules.

## Environment and safety

- Standalone Agent SDK program; runs on the user's subscription auth (no gateway, no API key).
- The local models are reached through `ollama_bridge.py` (the Ollama HTTP API, not
  `ollama run`) inside the local-coder / local-writer agents. There is NO fallback tag: the
  bridge asks `model_resolver.py`, and a resolver that names no qualified model is an
  explicit stop. Each agent passes its own `--role` (`coder` / `writer`), so the two roles
  can be served by different tags; without it both get the single overall `current` tag,
  which is how the coder side was being served a writer model scoring 0/3 on coder tasks.
- State-changing git (merge, branch delete) is never done by the local model; the merge is
  human-gated.
- Install the SDK in this skill's own `.venv` and validate `requirements.txt` with
  `pip-audit` before use.

## Running

Live run (needs claude-agent-sdk + Ollama + the review plugins):

```bash
python scripts/loop_engineer.py --loop --budget 2.00 --score 90 "add input validation to X"
```

Control-logic dry run (offline, no SDK/models - drives the guards over precomputed reports):

```bash
python scripts/loop_engineer.py --dry-run --budget 1.00 --score 90 --reports r1.json r2.json
```

Offline tests:

```bash
python scripts/Test/test_loop_audit.py
python scripts/Test/test_loop_guards.py
```

## Artifacts

Written under the run directory (loop-audit-compatible names): `PROCESS.md` (todo/checkbox
state), `loop-run-log.md` (per-iteration score + cost), `loop-budget.md` (spend vs cap).
