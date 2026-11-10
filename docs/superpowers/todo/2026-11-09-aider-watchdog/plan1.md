---
executor: local-coder
tier: standard
bounds:
  max_rounds: 3
  max_tokens: 1500000
  plateau: 2
---

# Plan 1 - Settings and references

Return every file you create in full. Tests run with `go test -C .claude/skills/aider-setup/watchdog ./...`.

**Goal:** load the settings of the program and the measured references of the models.

**Spec:** `spec.md`.

## Constraints

Standard library only. No numeric literal in code. A missing settings key is an error that names the key
and the file. Every function has the comment header the spec asks for.

---

### Task 1: settings and references

**Files:**
- Create: `.claude/skills/aider-setup/watchdog/aider-watchdog.json`
- Create: `.claude/skills/aider-setup/watchdog/settings.go`
- Test: `.claude/skills/aider-setup/watchdog/settings_test.go`

**Reads, do not modify:** `.claude/skills/aider-setup/watchdog/go.mod` (it already exists: module
`aiderwatchdog`, `go 1.22`, no requirement; do not create it).

**Interfaces:**
- The settings file keys and first values: `pollSeconds` 30, `negligibleReferencePercent` 5,
  `lowReadings` 6, `watchedStates` `["writing", "auditing"]`, `terminalStates` `["done",
  "done_with_blocked", "failed"]`, `modelServerNames` `["ollama", "llama-server"]`, `ollamaURL`
  `"http://127.0.0.1:11434"`, `callTimeoutSeconds` 30. Each key is `{"value": ..., "provenance": "..."}`
  with a short provenance text, for example "initial value, adjust after measuring" for the numbers and
  "fixed list" for the lists.
- `type settings struct` with one typed field per key; `loadSettings(path string) (settings, error)`
  refuses a missing file, a missing key and an entry whose provenance is empty; the error names the file
  and the key.
- `type dimension struct { Median, Min float64 }`; `type reference struct { NumCtx int; CPU, GPU
  dimension }`; `loadReferences(path string) (map[string]reference, error)` reads
  `models[tag].reference_decode` (fields `num_ctx`, `cpu_percent`, `gpu_percent`, each dimension with
  `median` and `min`). A missing file or a model without that entry gives an empty map; a file that is
  not valid JSON is an error.

**Tests to write first, each failing before the code exists:**
`TestLoadSettingsNamesTheMissingKeyAndFile`; `TestLoadSettingsRefusesAnEntryWithoutProvenance`;
`TestShippedSettingsLoad`; `TestLoadReferencesReadsTheMeasuredEntry`;
`TestLoadReferencesMissingFileIsEmpty`; `TestLoadReferencesRefusesInvalidJSON`.

- [ ] Step 1: write the tests, run `go test`, they fail (the code is absent).
- [ ] Step 2: write the code and the settings file, run `go test`, every test passes.
