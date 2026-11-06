---
executor: local-coder
tier: standard
bounds:
  max_rounds: 3
  max_tokens: 1500000
  plateau: 2
---

# Plan 16 - the driver writes the bridge log

> **For agentic workers:** executed by the local coder model through the driver (rule R39). Nothing
> here is code to copy: build what each interface says. Return both files in full.

**Goal:** every model call of the driver leaves the same records in the bridge log that a call through
the bridge leaves, so the dashboard section `local_calls` shows the coder role generating, idle or
failed during a driver run.

**Why (measured 2026-11-05):** the driver posts to the daemon directly, without the bridge's
generation loop, so its calls write nothing to the bridge log, which is all the dashboard reads.

## Global Constraints

R2: no model name. R19: the clock is injected, the real one only as a default of this boundary class.
R27: every function carries the Purpose, Inputs and Outputs header. R20: each new test asserts a
failure path too. The log is a side channel: it never changes what is generated or returned. No prompt
text, no reply text and no hash is ever logged.

## Review Focus

- A record written with a field name the dashboard collector does not read.
- A log failure that stops a call, or one that logs nothing and says nothing.
- A call to `contract`, `tag`, `window` or `count` that writes a record.

---

### Task 1: log the calls

**Files:**
- Modify: `.claude/skills/loop-engineer/scripts/driver_deps.py`
- Test: `.claude/skills/loop-engineer/scripts/Test/test_driver_deps.py`

**Interfaces:**

1. `BridgeDeps.__init__(root, log_path=None, clock=None)`. `log_path` None means the bridge's default
   log path, read from the bridge object at call time. `clock` is a function returning the UTC time as
   an ISO string. When None, the bridge object's own real clock function is used at call time.
2. `contract(plan)` also remembers the plan path (as a string) and the resolved role, and resets an
   attempt counter to 0. Its return value does not change. The driver calls it once per plan, so the
   plan, the role and the attempt number reach `generate` without any change to the driver.
3. `generate` adds 1 to the attempt counter, then writes the records below through the bridge object's
   own append function. Its arguments and return value do not change.

**Records:**

- Before the post, a start record: `event` is `start`, then `at`, `role`, `tag`, `num_ctx` (the window
  passed in), `plan`, `attempt`.
- After a reply, an attempt record: `at`, `role`, `tag`, `num_ctx`, `prompt_tokens`,
  `completion_tokens`, `plan`, `attempt`, `accepted` set to None (known only after the tests). The two
  token fields are the daemon reply's counts for the prompt and the generation, None when the reply
  omits them, never 0.
- When the post raises the bridge's error: a failed record with `event` set to `failed`, then `at`,
  `role`, `tag`, `attempt`, `error` (the first 300 characters of the message); the error is raised
  again unchanged.
- When the append raises an operating system error, print one line starting with `LOG-FAILED:` on the
  error stream and carry on with the call.

**Tests to write first, each failing before the code exists.** The test builds `BridgeDeps` and
replaces its bridge attribute with a stand-in object offering the few names `generate` uses, so no
daemon is needed. The stand-in records what the append function receives. Fictitious plan paths only.

1. After `contract`, a call writes a start record then an attempt record, in that order, with the
   fields above, and `plan` and `role` come from the contract call.
2. The token fields equal the reply counts, and are None when the reply carries none.
3. The attempt record holds every key the dashboard reads: `at`, `role`, `tag`, `plan`,
   `prompt_tokens`, `completion_tokens`, `accepted`.
4. A post that raises writes a start record then a failed record, and the error still reaches the
   caller.
5. Two calls after one `contract` carry attempt 1 then 2, and a new `contract` resets it to 1.
6. With `clock` given, `at` is its value; with none, `at` comes from the stand-in's real clock.
7. An append that raises an operating system error does not stop the call, which returns its reply, and
   the `LOG-FAILED:` line is printed.
8. `tag`, `window` and `count` write no record.

- Test: `.claude/skills/loop-engineer/scripts/Test/test_driver_deps.py`

- [ ] Step 1: write the tests, run the file, they fail for the missing parameters.
- [ ] Step 2: build the interfaces, run the file, every test passes.

## After this plan

The cloud updates the test inventory line and the driver paragraph of the manual chapter 11, then
reads the produced code for the review under R35.
