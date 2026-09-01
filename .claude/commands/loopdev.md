# Run the budget-bounded loop-engineering dev loop

Develop one feature through a design -> plan -> code -> comment -> test -> review -> score ->
correct loop that stops on a composite quality gate or a hard budget cap. Thin wrapper over
the `loop-engineer` skill - read `.claude/skills/loop-engineer/SKILL.md` and
`references/LOOP.md`, then follow the pipeline and the model tiering exactly. The best cloud
model (Fable 5) orchestrates and judges, cheaper tiers act, and code and comments are
generated locally by the `local-coder` / `local-writer` agents so the heavy work is free.

Option contract:

```
/loopdev --budget <max_usd> [--score <min_score>] [--max-iters N] [--patience N] [--no-merge-pr] "<feature request>"
```

Procedure:

1. Parse `$ARGUMENTS` for the flags and the feature request. `--budget` is required; refuse to
   start without it (no silent unbounded spend). Defaults: `--score 90`, `--max-iters 10`,
   `--patience 2`.
2. Confirm the environment: Ollama running with the local models (`ollama list`, and
   `model_resolver.py --resolve --role <writer|coder>` naming a qualified tag for each role -
   there is no fallback tag, an unqualified role is a stop), and the review plugins installed. The
   Agent SDK runs on your subscription auth - no gateway, no API key.
3. Run the driver:
   ```
   python ".claude/skills/loop-engineer/scripts/loop_engineer.py" --loop --budget <max_usd> --score <min_score> "<feature request>"
   ```
   Use `--dry-run --reports r1.json r2.json` to exercise the loop-control logic offline
   (guards, ledger) without the SDK or models.
4. The loop wraps evaluate -> correct -> rescore. It stops on the composite gate (tests green
   AND no CRITICAL/HIGH AND aggregate >= min_score), or on a hard stop: budget cap, max
   iterations, no-progress plateau, or a security regression. Security is a hard floor.
5. On a gate pass the loop stops at "ready to merge": the branch is pushed and a PR opened
   (token permitting, unless `--no-merge-pr`). The merge to a protected branch is
   human-gated - present the result and wait for explicit confirmation before merging.

Report at the end:

- The final aggregate score, per-axis sub-scores, and which stop rule ended the loop
- The spend vs the cap and the iteration count (from `loop-budget.md` / `loop-run-log.md`)
- The branch / PR at the merge gate, and any CRITICAL/HIGH findings that remain
- The `PROCESS.md` checkbox state

Never let the local model perform a merge, branch delete, or force-push; those stay with a
cloud subagent or the human. Apply the pipeline directly; the only interactive checkpoint is
the human merge confirmation.

$ARGUMENTS
