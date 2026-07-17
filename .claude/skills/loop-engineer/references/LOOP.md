# LOOP.md - loop-engineering contract

The contract for a live loop run. The driver (`scripts/loop_engineer.py`) and the scorer
(`scripts/loop_audit.py`) implement it; this file is the human-facing source of truth for the
model tiering, the pipeline, and the safety gates. Read it before a live run.

## Model tiering

Cost lever is effort as much as model: reserve the top model for judgment, push routine work
down, and generate locally.

| Stage | Model | Effort | Why |
|---|---|---|---|
| Design (brainstorming), arbitration | Fable 5 | xhigh | judgment |
| Plan (writing-plans) | Opus | high | structured planning |
| Execute, TDD, review panel, correct | Sonnet | high | routine agentic work |
| Local agents' cloud wrapper | Haiku | medium | frames the task, drives the bridge |
| Code / comments / scoring arithmetic | local (qwen3.5:9b / ornith:9b) | - | free, on the GPU |

Routing: cloud runs on the user's subscription auth (no gateway, no API key). Local models are
reached only through the Bash bridge inside the `local-coder` / `local-writer` agents
(`ollama run <model>`), because subscription auth cannot resolve a local model name as an
`AgentDefinition` model. Until the 9B models are imported, the bridge falls back to
`qwen2.5-coder:7b`.

## Pipeline

Per feature, branch-isolated: design -> plan -> branch -> TDD tests -> code -> comment ->
run tests + review panel -> score -> correct, looping the evaluate/correct/rescore sub-cycle
(steps run/review -> correct -> score). See `SKILL.md` for the numbered steps and which
model/agent owns each.

## Stop gate

Composite (default): `tests green AND no CRITICAL AND no HIGH AND aggregate >= min_score`
(min_score default 90). Hard stops, in order after a gate check: budget cap (`--budget`,
SDK `max_budget_usd`), max iterations (`--max-iters`, SDK `max_turns`), security regression
vs the previous iteration, no-progress plateau (`--patience`).

## Safety gates (non-negotiable)

- Security hard floor: any CRITICAL finding, a betterleaks block, or a CRITICAL pip-audit CVE
  fails the gate regardless of the aggregate.
- Human-gated merge: the loop stops at "ready to merge". The local model never runs
  state-changing git (merge, branch delete, force-push); a Sonnet subagent creates the branch
  and the merge to a protected branch waits for explicit user confirmation.
- Reviewers are installed/first-party only by default. `ai-firstify`, if enabled, runs
  audit-only so it scores rather than restructures code.

## Reviewer report schema (fed to loop_audit)

Each review pass writes one report JSON that `loop_audit.score` consumes:

```json
{
  "tests": {"passed": 0, "failed": 0, "errored": 0},
  "hooks": {"betterleaks_blocked": false, "pip_audit_criticals": 0},
  "findings": [
    {"source": "code-review", "axis": "correctness", "severity": "HIGH", "summary": "..."}
  ]
}
```

Axes: correctness, security, tests, tech-debt, style, ai-first. Severities: CRITICAL, HIGH,
MEDIUM, LOW (unknown -> MEDIUM).

## Ledger artifacts

Written under the run directory, loop-audit-compatible names:

- `PROCESS.md` - todo/checkbox state (started, tests green, score >= min, gate passed, merge).
- `loop-run-log.md` - append-only table: iter, aggregate, tests, security-floor, gate, cost.
- `loop-budget.md` - cap, spent, remaining, iterations.
- `STATE.md` (optional) - free-form notes the orchestrator wants to persist across sessions.
