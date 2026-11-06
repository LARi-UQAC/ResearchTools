---
executor: local-coder
tier: standard
bounds:
  max_rounds: 3
  max_tokens: 1500000
  plateau: 2
---

# Plan 1 - The dispatch guard checks the aider kit, not a resolver role

> **For agentic workers:** run by the local coder model through the aider kit (rule R39). Return every
> file you change in full. The test file runs as a script (`unittest.main()` at its end).

**Goal:** the guard that judges a `local-coder` dispatch no longer asks the resolver for a role. It checks
that the aider kit is installed, as the section "Guard" of the spec says.

**Spec:** the section "Guard" of the spec.

## Global Constraints

No value is written in the code that the configuration should hold (R0). Every configuration entry has a
`value` and a `provenance`, and a missing key is named in the error (R3). A failure of the hook itself exits
0 in silence (R11). Every function carries the Purpose, Inputs and Outputs header, and Raises when it raises
on purpose. Fictitious folders in tests (R34), built under a temporary directory.

## Review Focus

- The kit folder missing a required file: refusal that names the file.
- The resolver is no longer imported or consulted, and the old resolver key is gone from the configuration.
- A broken or missing configuration still exits 0 with no output.

---

### Task 1: the guard, its configuration and its test

**Files:**
- Modify: `.claude/hooks/local-coder-dispatch-guard.py`
- Modify: `.claude/hooks/local-coder-dispatch-guard.json`
- Modify: `.claude/hooks/Test/test_local_coder_dispatch_guard.py`

**Interfaces:**
- `kit_missing(config_dir: Path, bin_dir: Path, required: dict) -> str | None`: `required` maps a folder
  label (`config`, `bin`) to the list of file names the folder must hold. Returns None when every file
  exists, else one sentence naming the first missing file and its folder and saying to install the aider kit.
- `judge` stops taking a resolver and stops calling the plan resolution. After the header and executor
  checks it calls `kit_missing` with the configured folders and files, and returns its sentence.
- The configuration drops the resolver entry and gains `kit_config_dir`, `kit_bin_dir` and `kit_files`.

**Tests to write first, each failing before the code changes:** the dispatch is refused when a kit file is
missing and the reason names that file; it is allowed when all three files exist; the resolver is never
called (a test that fails if it is); a missing configuration key is named and still exits 0 silently; the
other existing refusals (no plan line, broken header, wrong executor, plan outside the repository) keep
their tests. Remove the tests that staged a resolver.

- Test: `.claude/hooks/Test/test_local_coder_dispatch_guard.py`

- [ ] Step 1: change the tests, run the file, the new ones fail.
- [ ] Step 2: change the guard and its configuration, run the file, every test passes.
