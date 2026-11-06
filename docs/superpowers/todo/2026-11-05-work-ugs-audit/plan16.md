---
executor: local-coder
tier: standard
bounds:
  max_rounds: 3
  max_tokens: 1500000
  plateau: 2
---

# Plan 16 - the driver writes the bridge log

> **For agentic workers:** this plan is executed by the local coder model through the driver (rule
> R39). Nothing in it is code to copy: build what each interface says.

**Goal:** every model call the driver makes leaves the same records in the bridge log that a call
through the bridge leaves, so the dashboard section `local_calls` shows the coder role generating,
idle or failed during a driver run.

**Why (measured 2026-11-05):** the driver posts to the daemon directly, without the bridge's
generation loop. Its calls write nothing to the bridge log, and the dashboard reads only that log.

## Global Constraints

R2: no model name. R19: no wall clock inside the logic; a clock is injected. R27: every function
carries the Purpose, Inputs and Outputs header, and Raises when it raises on purpose. R20: each new
test asserts a failure path too. The log is a side channel: it never changes what the driver
generates, writes or ticks. No prompt text, no reply text and no hash is ever logged.

## Review Focus

- A record written with a field name the dashboard collector does not read.
- A log failure that stops a run, or a run that logs nothing and says nothing.
- A `--dry-run` that writes a record.

---

### Task 1: log the calls of the driver

**Files:**
- Modify: `.claude/skills/loop-engineer/scripts/local_coder_driver.py`
- Test: `.claude/skills/loop-engineer/scripts/Test/test_local_coder_driver.py`

**Interfaces (names are fixed, the dashboard reads them):**

1. The class `BridgeDeps` gains two optional constructor parameters, `log_path` and `clock`.
   `log_path` defaults to the bridge's own default log path. `clock` is a function returning the UTC
   time as an ISO string, or None, in which case every `at` field is None.
2. The method `generate` of `BridgeDeps` gains an optional last parameter `meta`, a dict with the keys
   `role`, `plan` (the plan path as a string) and `attempt` (an int). With `meta` None nothing is
   logged.
3. `_run_plan` passes `meta` on every model call: the role of the plan's contract, the plan path and
   the attempt number. The stand-in dependency of the existing tests accepts the new parameter.
4. `main` gives `BridgeDeps` the bridge's real clock for a real run. A `--dry-run` and an audit
   sandbox command give it none and log nothing.

**Records, appended through the bridge's own append function:**

- Before the post, a start record with `event` set to `start`, then `at`, `role`, `tag`, `num_ctx`
  (the window passed to `generate`), `plan` and `attempt`.
- After a reply, an attempt record with `at`, `role`, `tag`, `num_ctx`, `prompt_tokens`,
  `completion_tokens`, `plan`, `attempt` and `accepted` set to None (the driver knows later whether
  the tests passed). The two token fields come from the daemon's reply counts for the prompt and for
  the generation, and are None when the reply omits them, never 0.
- When the post raises the bridge's error, a failed record with `event` set to `failed`, then `at`,
  `role`, `tag`, `attempt` and `error` (the first 300 characters of the message). The error is then
  raised again unchanged.
- When the append itself raises an operating system error, `generate` prints one line starting with
  `LOG-FAILED:` on the error stream and goes on with the call.

**Tests to write first, each failing before the code exists:**

1. A call with `meta` writes a start record and then an attempt record, in that order, with the
   fields above. The test builds `BridgeDeps` and replaces its bridge attribute with a stand-in
   offering the few functions `generate` uses, so no daemon is needed.
2. The token fields equal the reply counts, and are None when the reply carries none.
3. The attempt record carries every key the dashboard reads: `at`, `role`, `tag`, `plan`,
   `prompt_tokens`, `completion_tokens`, `accepted`.
4. A post that raises writes a start record then a failed record, and the error still reaches the
   caller.
5. With `meta` None nothing is written. With `clock` None the `at` fields are None.
6. An append that raises an operating system error does not stop the call, which returns its
   reply, and the `LOG-FAILED:` line is printed.
7. A `--dry-run` through `main` writes no record.
8. A run through `_run_plan` with the existing stand-in passes the role, the plan path and the
   attempt number, and a second attempt after a failing test passes attempt 2.

- Test: `.claude/skills/loop-engineer/scripts/Test/test_local_coder_driver.py`

- [ ] Step 1: write the tests, run the file, they fail for the missing parameters.
- [ ] Step 2: build the interfaces, run the file, every test passes, the 33 earlier ones included.

## After this plan

The cloud session updates the test inventory line and the driver paragraph of the manual chapter 11
(prose), then reads the produced code for the review under R35.
