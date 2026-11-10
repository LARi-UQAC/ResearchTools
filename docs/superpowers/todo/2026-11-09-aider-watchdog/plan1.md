---
executor: local-coder
tier: standard
bounds:
  max_rounds: 3
  max_tokens: 1500000
  plateau: 2
---

# Plan 1 - Settings, references and the stall decision

Return every file you create in full. Tests run with `go test -C .claude/skills/aider-setup/watchdog ./...`.

**Goal:** the part of the program that decides. It reads the settings, reads the reference file, and
decides from a series of readings when there is a stall. It runs no program, makes no network call and
reads no clock.

**Spec:** `spec.md`.

## Constraints

Standard library only. No numeric literal in code. A missing settings key is an error that names the key
and the file. Every function has the comment header the spec asks for.

## Cases to cover

- Nothing is judged before a model is loaded, nor when the state is `testing`.
- A dimension whose reference median is negligible (a model fully on the CPU has a GPU reference near
  zero) is ignored.
- A model with no reference, or loaded with a different context than its reference, is never judged.

---

### Task 1: module, settings, references and tracker

**Files:**
- Create: `.claude/skills/aider-setup/watchdog/aider-watchdog.json`
- Create: `.claude/skills/aider-setup/watchdog/settings.go`
- Create: `.claude/skills/aider-setup/watchdog/tracker.go`
- Test: `.claude/skills/aider-setup/watchdog/settings_test.go`
- Test: `.claude/skills/aider-setup/watchdog/tracker_test.go`

**Reads, do not modify:** `.claude/skills/aider-setup/watchdog/go.mod` (it already exists: module
`aiderwatchdog`, `go 1.22`, no requirement; do not create it).

**Interfaces:**
- `aider-watchdog.json` keys and first values: `pollSeconds` 30, `negligibleReferencePercent` 5,
  `lowReadings` 6, `watchedStates` `["writing", "auditing"]`, `terminalStates` `["done",
  "done_with_blocked", "failed"]`, `modelServerNames` `["ollama", "llama-server"]`, `ollamaURL`
  `"http://127.0.0.1:11434"`, `callTimeoutSeconds` 30. Each `provenance` is a short text, for example
  "initial value, adjust after measuring" for the numbers and "fixed list" for the lists.
- `type settings struct` with one typed field per key; `loadSettings(path string) (settings, error)`
  refuses a missing file, a missing key and an entry whose provenance is empty; the error names the file
  and the key.
- `type dimension struct { Median, Min float64 }`; `type reference struct { NumCtx int; CPU, GPU
  dimension }`; `loadReferences(path string) (map[string]reference, error)` reads
  `models[tag].reference_decode` (fields `num_ctx`, `cpu_percent`, `gpu_percent`, each dimension with
  `median` and `min`). A missing file or a model without that entry gives an empty map; a file that is
  not valid JSON is an error.
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
`TestLoadSettingsNamesTheMissingKeyAndFile`; `TestLoadSettingsRefusesAnEntryWithoutProvenance`;
`TestShippedSettingsLoad`; `TestLoadReferencesReadsTheMeasuredEntry`;
`TestLoadReferencesMissingFileIsEmpty`; `TestLoadReferencesRefusesInvalidJSON`;
`TestNothingIsJudgedBeforeTheModelIsLoaded`; `TestNothingIsJudgedInTheTestingState`;
`TestAModelWithNoReferenceIsNotJudged`; `TestAModelLoadedWithAnotherContextIsNotJudged`;
`TestHealthyReadingsNeverStall`; `TestLowReadingsInARowMakeAStall`;
`TestOneRecoveredReadingResetsTheCount`; `TestNegligibleGPUReferenceIsIgnored`;
`TestEachModelUsesItsOwnReference`.

- [ ] Step 1: write the tests, run `go test`, they fail (the code is absent).
- [ ] Step 2: write the code and the settings file, run `go test`, every test passes.
