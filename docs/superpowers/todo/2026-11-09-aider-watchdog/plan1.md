---
executor: local-coder
tier: standard
bounds:
  max_rounds: 3
  max_tokens: 1500000
  plateau: 2
---

# Plan 1 - Go watchdog: settings, reference and the stall decision

> **For agentic workers:** run by the local coder model through the driver (rule R39). Return every
> file you create in full. The tests are Go tests, run with
> `go test -C .claude/skills/aider-setup/watchdog ./...`.

**Goal:** the pure part of the watchdog: read its settings, read the measured references, and decide
from a stream of readings when to say "stall". No process, no network, no clock.

**Spec:** `spec.md` decisions D1 to D4, "Language and conventions".

## Global Constraints

Standard library only. No numeric literal in code: every threshold comes from `aider-watchdog.json`. A
missing settings key is an error that names the key and the file. Fictitious plan and model names in
tests (R34). Every function has the comment header the spec asks for.

## Review Focus

- Nothing is judged before the model is loaded, and not in the `testing` state.
- A dimension whose reference median is negligible (a model fully on the CPU has a GPU reference near
  zero) is ignored, so it can neither hide nor cause a stall.
- A model with no reference, or loaded with another context than the one in its reference, is never
  judged.

---

### Task 1: module, settings, references and tracker

**Files:**
- Create: `.claude/skills/aider-setup/watchdog/go.mod`
- Create: `.claude/skills/aider-setup/watchdog/aider-watchdog.json`
- Create: `.claude/skills/aider-setup/watchdog/settings.go`
- Create: `.claude/skills/aider-setup/watchdog/tracker.go`
- Test: `.claude/skills/aider-setup/watchdog/settings_test.go`
- Test: `.claude/skills/aider-setup/watchdog/tracker_test.go`

**Interfaces:**
- `go.mod`: module `aiderwatchdog`, Go 1.22, no requirement.
- `aider-watchdog.json`: each key is `{"value": ..., "provenance": "..."}`. Keys: `pollSeconds` 30,
  `negligibleReferencePercent` 5, `lowReadings` 6, `watchedStates` `["writing", "auditing"]`,
  `terminalStates` `["done", "done_with_blocked", "failed"]`, `modelServerNames` `["ollama",
  "llama-server"]`, `ollamaURL` `"http://127.0.0.1:11434"`, `callTimeoutSeconds` 30. Provenance of the
  numbers: "proposal 2026-11-09, to be tuned by the owner"; of the lists and the URL: "specified". The
  threshold of a low reading is not here: it is the minimum measured in the reference.
- `type settings struct` with one typed field per key; `loadSettings(path string) (settings, error)`
  refusing a missing file, a missing key or an entry without a non-empty provenance, the error naming the
  file and the key.
- `type dimension struct { Median, Min float64 }`; `type reference struct { NumCtx int; CPU, GPU
  dimension }`; `loadReferences(path string) (map[string]reference, error)` reads
  `models[tag].reference_decode` (fields `num_ctx`, `cpu_percent`, `gpu_percent`, each dimension with
  `median` and `min`); a missing file or entry gives an empty map, an unparsable file is an error.
- `type reading struct { Model string; CPUPercent float64; GPUPercent *float64; ContextLength int;
  State, Plan string }` (`Model` empty when no model is loaded, `GPUPercent` nil when unread).
- `type tracker struct`, `newTracker(refs map[string]reference, s settings) *tracker`, and
  `(t *tracker) update(r reading) bool` returning true once `lowReadings` consecutive readings are low,
  then resetting its count. It judges nothing (returns false and keeps its count) for no model loaded, a
  state not in `watchedStates`, a model with no reference, or a context length different from the
  reference `NumCtx`. A reading is low when every dimension whose reference median is at least
  `negligibleReferencePercent` is under that dimension's reference minimum; a nil GPU reading on a judged
  GPU dimension means the reading is not judged. One reading that is not low resets the count.

**Tests to write first, each failing before the code exists:**
`TestLoadSettingsNamesTheMissingKeyAndFile`; `TestLoadSettingsRefusesAnEntryWithoutProvenance`;
`TestShippedSettingsLoad`; `TestLoadReferencesReadsTheMeasuredEntry`;
`TestLoadReferencesMissingFileIsEmpty`; `TestLoadReferencesRefusesUnparsableFile`;
`TestNothingIsJudgedBeforeTheModelIsLoaded`; `TestNothingIsJudgedInTheTestingState`;
`TestAModelWithNoReferenceIsNotJudged`; `TestAModelLoadedWithAnotherContextIsNotJudged`;
`TestHealthyReadingsNeverStall`; `TestLowReadingsInARowMakeAStall`;
`TestOneRecoveredReadingResetsTheCount`; `TestNegligibleGPUReferenceIsIgnored`;
`TestEachModelUsesItsOwnReference`.

- [ ] Step 1: write the tests, run `go test`, they fail (code absent).
- [ ] Step 2: write the code and the settings file, run `go test`, every test passes.
