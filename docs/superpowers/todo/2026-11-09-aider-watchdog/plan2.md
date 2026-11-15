---
executor: local-coder
tier: standard
bounds:
  max_rounds: 3
  max_tokens: 1500000
  plateau: 2
---

# Plan 2 - The stall decision

Return every file you create in full. Tests run with `go test -C .claude/skills/aider-setup/watchdog ./...`.

**Goal:** decide from a series of readings when there is a stall. No program is run, no network call is
made, no clock is read.

**Spec:** `spec.md`, section "What `watch` does".

## Constraints

Standard library only. No numeric literal in code. Every function has the comment header the spec asks
for.

## Cases to cover

- Nothing is judged before a model is loaded, nor when the state is `testing`.
- A dimension whose reference median is negligible (a model fully on the CPU has a GPU reference near
  zero) is ignored.
- A model with no reference, or loaded with a different context than its reference, is never judged.

---

### Task 1: the tracker

**Files:**
- Create: `.claude/skills/aider-setup/watchdog/tracker.go`
- Test: `.claude/skills/aider-setup/watchdog/tracker_test.go`

**Reads, do not modify:** `.claude/skills/aider-setup/watchdog/settings.go` (the types `settings`,
`reference` and `dimension`).

**Interfaces:**
- `type reading struct { Model string; CPUPercent float64; GPUPercent *float64; ContextLength int;
  State, Plan string }`. `Model` is empty when no model is loaded; `GPUPercent` is nil when unread.
- `type tracker struct`; `newTracker(refs map[string]reference, s settings) *tracker`;
  `(t *tracker) update(r reading) bool` returns true when `lowReadings` low readings in a row are
  reached, then resets its count. It judges nothing (returns false, keeps its count) when no model is
  loaded, when the state is not in `watchedStates`, when the model has no reference, or when
  `ContextLength` differs from the reference `NumCtx`. A reading is low when every dimension whose
  reference median is at least `negligibleReferencePercent` is under that dimension's reference minimum;
  a nil GPU reading on a judged GPU dimension means the reading is not judged. A reading that is not low
  resets the count.

**Tests to write first, each failing before the code exists:**
`TestNothingIsJudgedBeforeTheModelIsLoaded`; `TestNothingIsJudgedInTheTestingState`;
`TestAModelWithNoReferenceIsNotJudged`; `TestAModelLoadedWithAnotherContextIsNotJudged`;
`TestHealthyReadingsNeverStall`; `TestLowReadingsInARowMakeAStall`;
`TestOneRecoveredReadingResetsTheCount`; `TestNegligibleGPUReferenceIsIgnored`;
`TestEachModelUsesItsOwnReference`.

- [ ] Step 1: write the tests, run `go test`, they fail (the code is absent).
- [ ] Step 2: write the code, run `go test`, every test passes.
