---
executor: cloud
tier: standard
bounds:
  max_rounds: 3
  max_tokens: 1500000
  plateau: 2
---

# Plan 13 - local-coder driver: aider-setup's exact input, one LLM call per plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans, in the session. Plans 13
> and 14 are the LAST code written in the cloud (owner 2026-11-05). Runs before plan 4.

**Goal:** `local-coder` submits to the coder model (today `ornith:9b-gpu`, named only by the resolver,
R2) exactly the files aider-setup submits, sized by the same `context-budget.json`, one LLM call per
plan, and works through every plan of `progress.md` to the end without returning to the cloud. The
only difference from aider-setup is the launcher: a Claude Code wrapper instead of `aider-night`.

**The file set (owner 2026-11-05), identical to `aider-plan.ps1` lines 409-413 and 1056-1065:**

| Order | File | Source of the path | Ceiling |
|---|---|---|---|
| 1 | `conventions.md` | `always_on_files` of `context-budget.json` | `ceilings.conventions.md` |
| 2 | `rules.md` | `always_on_files` | `ceilings.rules.md` |
| 3 | `spec.md` | the effort folder | `ceilings.spec.md` |
| 4 | `plan<N>.md` | the effort folder | `ceilings.plan.md` |
| 5 | skill stage files | `skills.json`, stage `write` (stage `reopen` on a retry) | the stage `ceiling` |
| 6 | `progress.md` | the effort folder | `ceilings.progress.md` |
| 7 | every file the plan names | the same parsing as `Get-PlanTargets` (front matter skipped) | `ceilings.code_file` each |
| 8 | the plan message | the text of `aider-plan.ps1` line 991 | - |

Reply reserve `reserve.reply_tokens`; retries `tests.max_fix_attempts`; window = the coder role's
window. Prompt + reply over the window: refused by exact count, never cut (R8).

**Why (measured 2026-11-05):** with a 16384 window the wrapper sent 1245 to 4225 hand-picked tokens per
file; plan 3 was truncated and rewritten in the cloud (366577 wrapper tokens), plan 4's module failed
three times. The model never saw the rules, the spec or the conventions aider gives it.

## Global Constraints

R0/R3 every number and path from `context-budget.json` and `skills.json`, a missing key or file named.
R8 nothing truncated. R24 every written path resolved inside the repository root and listed by the plan.
R27 headers and why-comments. Tests first, failure paths (R20), bridge and test runner injected (R21).
The vault daemon and `local-writer` keep today's bridge: every new value is passed by the driver.

## Review Focus

- A file of the set silently missing from the prompt (absent on disk must be a refusal).
- A reply file outside the root or not named by the plan, written anyway.
- A plan ticked without its tests having run.

---

### Task 1: bridge accepts a reply holding several files, exact-only budget

**Files:**
- Modify: `.claude/skills/loop-engineer/scripts/ollama_bridge.py`
- Test: `.claude/skills/loop-engineer/scripts/Test/test_ollama_bridge.py`

**Interfaces:** `split_files(text) -> list[tuple[str, str]]`: each fenced block whose first line is
`# file: <relative path>` yields `(path, body)`; prose between blocks ignored; no path, duplicate path
or unterminated fence raises `BridgeError`. `check_budget(..., exact_only=False)`: when true only the
probe count decides (the character pre-filter refused a 4225-token prompt as 32644).

- [ ] Step 1: failing tests (two files in order, prose ignored, the three refusals, exact-only accepts
  what the pre-filter refuses and still refuses over budget). Step 2: FAIL. Step 3: implement.
  Step 4: OK. Step 5: commit `feat(loop-engineer): bridge splits a multi-file reply (#104)`.

### Task 2: `local_coder_driver.py`

**Files:**
- Create: `.claude/skills/loop-engineer/scripts/local_coder_driver.py`
- Test: `.claude/skills/loop-engineer/scripts/Test/test_local_coder_driver.py`
- Modify: `.claude/rules/testing.md`

**Interfaces:**
- `file_set(plan: Path, effort: Path, budget: dict, skills: dict, stage: str) -> list[tuple[str, Path]]`
  the table above, in that order; a missing file or one over its ceiling raises `DriverError` naming it.
- `build_prompt(file_set) -> str`: each file under a header `### <path>`, whole, then the message and
  the reply format of Task 1.
- `run(progress: Path, root: Path, bridge, runner, budget, skills) -> dict`: for every plan of
  `progress.md` with an open line, in ledger order: `plan_contract` validation; exact count against the
  window minus `reply_tokens`; one bridge call with `num_predict=reply_tokens`; write each reply file;
  run every `Test:` file of the plan through `runner`; pass: tick the plan's open lines `[x]` with the
  test summary; fail: retry with stage `reopen` plus the failing output, up to `max_fix_attempts`, then
  `[!]` with the last failing line, and continue with the next plan. Returns per-plan status.
- `main(argv)`: `--progress PATH --root PATH [--dry-run] [--json]`; dry run builds every prompt and
  prints file list and token count, calls nothing, writes nothing (R16). Exit 0 all plans done,
  1 a plan blocked, 2 refusal.

- [ ] Step 1: failing tests (fictitious effort in TEMP): file set and order equal the table; each
  missing file refused by name; a file over its ceiling refused; prompt over window refused before any
  call; a two-file reply written and the plan ticked; outside-root and unnamed paths refused; failing
  tests retried with stage `reopen`, then `[!]`, next plan still run; two plans run in one call of
  `run`; dry run writes nothing; `num_predict` equals `reply_tokens`.
- [ ] Step 2: FAIL. Step 3: implement. Step 4: OK, with `test_ollama_bridge.py`,
  `test_context_budget.py`. Step 5: testing.md lines (R23); commit
  `feat(loop-engineer): local-coder driver with aider-setup's input (#104)`.

### Task 4: a plan reopened by the wrapper's audit runs with the reopen stage

**Owner 2026-11-05:** aider-setup codes with one model and audits with another; in local-coder the
auditor is the wrapper itself. After the driver returns, the wrapper applies `code-review` and
`security-review` to the written files, inside the R35 bounds of the plan header (plan 14), and writes
each finding as a `- [ ] audit: <file>:<line> <finding>` line in the plan's section of `progress.md`.
The driver then reruns that plan. The wrapper never edits code; the driver never audits.

**Files:**
- Modify: `.claude/skills/loop-engineer/scripts/local_coder_driver.py`
- Test: `.claude/skills/loop-engineer/scripts/Test/test_local_coder_driver.py`

**Interfaces:** a plan whose open lines include `- [ ] audit:` lines runs from its first attempt with
skill stage `reopen` and the aider reopen message (`aider-plan.ps1` lines 997-1002, added to
`local-coder-driver.json` as `reopen_message`); the audit lines are ticked with the plan when its tests
pass, or the first one is blocked.

- [ ] Step 1: failing tests: an `audit:` line makes the first attempt use stage `reopen` and the reopen
  message; a plan with no `audit:` line still uses `write`; audit lines ticked on success, first one
  blocked on failure. Step 2: FAIL. Step 3: implement. Step 4: OK.
- [ ] Step 5: commit `feat(loop-engineer): driver reruns a plan reopened by the audit (#104)`.

### Task 3: the coder role at aider's window

- [ ] Step 1: with `opt-local-vram-llm`, sweep the coder tag at `num_ctx` 49152 (aider's input without
  its own overhead, 34548, plus `reply_tokens` 14336). Record tok/s and GPU residency in `progress.md`.
- [ ] Step 2: adopting the tuned tag for the coder role is the owner's. `[!] owner: adopt` until done.
