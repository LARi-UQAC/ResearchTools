---
description: "Run the bounded develop-and-improve loop"
---

Develop one feature through a design -> plan -> code -> comment -> test -> review -> score ->
correct loop that stops on a quality gate or on a bound the owner declared. Thin wrapper over
the `loop-engineer` skill: read `.claude/skills/loop-engineer/SKILL.md` and
`references/LOOP.md`, then follow the pipeline and the model tiering. The best cloud model
orchestrates and judges, cheaper tiers act, and code and comments are generated locally by the
`local-coder` / `local-writer` agents so the heavy work is free.

Option contract:

```
/loopdev [--score <min_score>] [--no-merge-pr] "<feature request>"
```

This is a procedure the session follows. The driver flag `loop_engineer.py --loop` is not wired
(it exits at once), so nothing here calls it. The bounds come from `loop_bounds.py`.

Skills (R36: any task needs one): design with `superpowers:brainstorming`, plan files with
`superpowers:writing-plans`, execution with `superpowers:executing-plans`. A similar toolset such
as speckit may replace them, and each step still names its skill.

Procedure:

1. Parse `the file(s) or topic given after the command in the chat message (if none was given, use the file currently open in the editor)` for the flags and the feature request. The default for `--score` is 90.
2. Confirm the environment: Ollama running with the local models (`ollama list`, and
   `model_resolver.py --resolve --role <writer|coder>` naming a qualified tag for each role -
   there is no fallback tag, an unqualified role is a stop), and the review plugins installed.
   Claude Code has one API endpoint per process and no per-subagent endpoint, so the local
   models are reached only through the bridge, never as a subagent model.
3. Ask the owner the three review bounds with `AskUserQuestion` (max rounds, max tokens, plateau),
   unless the plan header already carries them. Then declare them:
   ```
   python .claude/skills/loop-engineer/scripts/loop_bounds.py init --max-rounds N --max-tokens N --plateau N
   ```
4. Run the pipeline steps of the skill. At each review round invoke the review skills, fix the
   findings with a failing test first, then record the round:
   ```
   python .claude/skills/loop-engineer/scripts/loop_bounds.py tick --findings N
   ```
   The hook `review-loop-guard.py` refuses a review skill past a bound.
5. Stop at the first of: the composite gate (tests green AND no CRITICAL/HIGH AND aggregate >=
   min_score), `max_rounds`, `max_tokens`, `plateau`, or a security regression. Say which one
   ended the loop. When a bound ends it before the gate, report what remains and ask whether to
   raise a bound.
6. On a gate pass, push the branch and open a PR (unless `--no-merge-pr`). The merge to a
   protected branch is human-gated: present the result and wait for explicit confirmation.

`loop_engineer.py --dry-run --reports r1.json r2.json` still exercises the scoring and guard
logic offline, without the SDK or models.

Report at the end:

- The final aggregate score, per-axis sub-scores, and which stop ended the loop
- The rounds used against `max_rounds` and the tokens against `max_tokens` (`loop_bounds.py status`)
- The branch / PR at the merge gate, and any CRITICAL/HIGH findings that remain
- The `PROCESS.md` checkbox state

Never let the local model perform a merge, branch delete, or force-push; those stay with a
cloud subagent or the human.

the file(s) or topic given after the command in the chat message (if none was given, use the file currently open in the editor)

