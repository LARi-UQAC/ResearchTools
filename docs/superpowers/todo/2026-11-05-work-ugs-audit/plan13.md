---
executor: cloud
tier: standard
bounds:
  max_rounds: 3
  max_tokens: 1500000
  plateau: 2
---

# Plan 13 - local-coder driver: the full aider budget in front of the local model

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans, in the session. This plan
> and plan 14 are the LAST code written in the cloud (owner 2026-11-05). Runs before plan 4.

**Goal:** A deterministic driver runs a whole `progress.md` on the coder role: for each open task it puts
every needed file in front of the local model, with aider-setup's budget, and writes the files the
reply carries. The wrapper only launches it.

**Why (measured 2026-11-05, plans 3 and 4):** the coder tag's window is 16384, so the wrapper sent
1245 to 4225 tokens of hand-picked prompt; aider's own budget for one step is 18548 tokens of input
(rules, conventions, spec, plan, progress, skill stage) plus 16000 per file read, and 14336 of reply.
Plan 3's output was truncated and rewritten in the cloud (366577 wrapper tokens); plan 4's module failed
three attempts. The model was never given what it needed.

**Spec:** this plan; `context-budget.json` (aider-setup) is the single budget (R26, D9 of R38).

## Global Constraints

R0/R3 every number from `context-budget.json` or `skills.json`, a missing key named. R8: a file over its
ceiling or a prompt over the window is refused, never cut. R27 headers, why-comments. R20 failure paths.
R21 bridge injected in tests, no daemon. Tests first. The vault daemon and `local-writer` keep today's
bridge behaviour: every new value is passed explicitly by the driver, no bridge default changes.

## Review Focus

- A file silently dropped from the prompt (a rule file absent on disk must be a refusal, not an omission).
- A reply file whose path escapes the repository root, or names a file the task did not list (R24).
- A test that passes because the driver wrote nothing.

---

### Task 1: bridge accepts a reply holding several files, with an exact count

**Files:**
- Modify: `.claude/skills/loop-engineer/scripts/ollama_bridge.py`
- Test: `.claude/skills/loop-engineer/scripts/Test/test_ollama_bridge.py`

**Interfaces (produces):** `split_files(text: str) -> list[tuple[str, str]]`: every fenced block whose
opening fence line is followed by a first line `# file: <relative path>` (or the info string
`lang path=<relative path>`) yields `(path, body)`; prose between blocks is ignored; a block with no
path, a duplicate path, or an unterminated fence raises `BridgeError`. `check_budget` gains
`exact_only: bool = False`: when true the character pre-filter is skipped and only the probe count
decides (the pre-filter refused a measured 4225-token prompt as 32644).

- [ ] Step 1: failing tests: two files parsed in order; prose ignored; missing path, duplicate path,
  unterminated fence each refused; `exact_only` accepts a prompt the pre-filter would refuse and still
  refuses one over the probe budget. Step 2: run, FAIL. Step 3: implement. Step 4: run, OK.
- [ ] Step 5: commit `feat(loop-engineer): bridge splits a multi-file reply, exact-only budget (#104)`.

### Task 2: `local_coder_driver.py`

**Files:**
- Create: `.claude/skills/loop-engineer/scripts/local_coder_driver.py`
- Test: `.claude/skills/loop-engineer/scripts/Test/test_local_coder_driver.py`
- Modify: `.claude/skills/aider-setup/config/context-budget.json`
- Modify: `.claude/rules/testing.md`

**Interfaces (produces):**
- `context-budget.json` gains `local_coder` with `{value, provenance}`: `always_on` (paths of
  `config/rules.md`, `config/conventions.md`, resolved beside the file), `skill_stage` (`write`, read
  from `skills.json`), `max_retries` 3, `test_timeout_s` 600. Window and reply come from existing keys:
  the role window (`model_resolver.window_for_role`), `reserve.reply_tokens`.
- `build_prompt(task: dict, root: Path, budget: dict) -> str`: in this order, each under its own header:
  always-on files, skill stage bundle, `spec.md`, the task's `plan<N>.md`, `progress.md`, every file the
  plan's task names (whole), then the instruction: the open task line and the reply format of Task 1.
  Each part checked against its ceiling (`ceilings.*`, `code_file` for a named file). Raises
  `DriverError` naming the part.
- `open_tasks(progress: Path) -> list[dict]`: `{plan, line, text}` for every `- [ ]` in plan order.
- `run(progress: Path, root: Path, bridge, runner, budget) -> dict`: per task, exact-count check against
  the role window minus `reply_tokens`; bridge call with `num_predict=reply_tokens`; write each reply
  file (path resolved inside `root`, listed by the task, else refused); run the plan's test command
  through `runner`; on pass tick `[x]` with the test summary, on failure retry up to `max_retries`, then
  `[!]` with the last failing test line and move on. Returns counts and per-task status.
- `main(argv)`: `--progress PATH --root PATH [--dry-run] [--json]`; dry run builds every prompt and
  prints its token count, calls nothing, writes nothing (R16). Exit 0 all done, 1 a task blocked, 2 refusal.

- [ ] Step 1: failing tests (fictitious plan and progress in TEMP, bridge and runner faked): prompt holds
  every part in order; a missing always-on file refused by name; a part over its ceiling refused; a
  prompt over the window refused before any bridge call; a two-file reply written and ticked; a path
  outside root and an unlisted path refused; failing tests retried then `[!]` and the next task still
  run; dry run writes nothing; bridge called with `num_predict` equal to `reply_tokens`.
- [ ] Step 2: run, FAIL. Step 3: implement. Step 4: run, OK, plus `test_context_budget.py` and
  `test_ollama_bridge.py` still OK.
- [ ] Step 5: add both script lines to `.claude/rules/testing.md` (R23); commit
  `feat(loop-engineer): local-coder driver with the aider budget (#104)`.

### Task 3: the coder role at aider's window

- [ ] Step 1: with `opt-local-vram-llm`, sweep the coder tag at `num_ctx` 49152 (input 34548 + reply
  14336 = 48884, the window this driver needs). Record decode tok/s and GPU residency in `progress.md`.
- [ ] Step 2: adoption of the tuned tag for the coder role is the owner's (`model_resolver.py`). Mark
  `[!] owner: adopt` until done; plan 4 runs locally only after it.
