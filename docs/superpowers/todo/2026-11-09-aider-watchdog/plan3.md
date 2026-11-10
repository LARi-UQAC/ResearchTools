---
executor: local-coder
tier: standard
bounds:
  max_rounds: 3
  max_tokens: 1500000
  plateau: 2
---

# Plan 3 - The `reference` command

Return every file you create or change in full. Tests run with
`go test -C .claude/skills/aider-setup/watchdog ./...`.

**Goal:** `aider-watchdog reference --tag T` measures, for one installed model, the CPU load of the
model server and the GPU load during a healthy generation, and saves the result in the reference file
that `watch` reads.

**Spec:** `spec.md`.

## Constraints

Standard library only. No numeric literal in code: the sampling interval, the prompt, the token counts and
the timeouts come from `aider-watchdog.json`. The model tag is an argument; no model name appears in the
code. Every call has a timeout. Writing the reference file keeps the values of every other model and key,
goes through a temporary file and a rename, and refuses an existing file that is not valid JSON. No test
starts a process, opens a socket or sleeps.

## Cases to cover

- The measurement covers the model-server processes, not the whole machine.
- A model fully on the CPU has a GPU load near zero: record it as measured, not as an error.
- The record keeps the context length the server reported, because `watch` compares it.

---

### Task 1: the reference measurement

**Files:**
- Create: `.claude/skills/aider-setup/watchdog/reference.go`
- Modify: `.claude/skills/aider-setup/watchdog/settings.go`
- Modify: `.claude/skills/aider-setup/watchdog/aider-watchdog.json`
- Modify: `.claude/skills/aider-setup/watchdog/main.go`
- Test: `.claude/skills/aider-setup/watchdog/reference_test.go`

**Reads, do not modify:** `.claude/skills/aider-setup/watchdog/readings.go` (`runner`, `getter`,
`readProcessTable`, `serverCPUSeconds`, `readGPUPercent`, `readOllamaPS`).

**Interfaces:**
- New settings keys, in the same `{value, provenance}` form: `sampleSeconds`, `prompt` (a short fixed
  request for one paragraph of text), `numPredict`, `warmupNumPredict`, `generationTimeoutSeconds`.
  `settings.go` gets the matching typed fields.
- `type stat struct { Median, Min float64 }`; `type referenceRecord struct { MeasuredAt string; NumCtx int;
  DecodeTPS float64; CPU stat; GPU *stat; Samples int; Source string }`.
- `summarize(cpu []float64, gpu []float64) (referenceRecord, error)`: the median and the minimum of each
  series; `GPU` is nil when `gpu` is empty; an empty `cpu` is an error.
- `measureReference(d refDeps, tag string, s settings) (referenceRecord, error)`: warms the tag with a
  request of `warmupNumPredict` tokens, reads the loaded context length from `/api/ps`, starts one
  generation of `numPredict` tokens in a goroutine and, every `sampleSeconds` until it ends, reads the
  model-server CPU percent of one core (the rise of the CPU seconds over the elapsed seconds) and the GPU
  load. The decode speed comes from the response fields `eval_count` and `eval_duration`. The HTTP post
  and get, the runner, the clock and the sleep are injected.
- `writeReference(path, tag string, rec referenceRecord) error`: sets `models[tag].reference_decode`
  (fields `measured_at`, `num_ctx`, `decode_tps`, `cpu_percent` and `gpu_percent` each with `median` and
  `min`, `samples`, `source`), keeping every other value, through a temporary file and a rename.
- `main.go` gets the command `aider-watchdog reference --tag T [--config FILE] [--settings FILE]
  [--dry-run]`. `--dry-run` measures nothing and prints what it would do. It prints one JSON line with the
  record. Exit 0 done, 2 a refusal such as a missing tag, 1 a failure.

**Tests to write first, each failing before the code exists:**
`TestSummarizeGivesMedianAndMin`; `TestSummarizeWithoutGPUReadingsGivesNilGPU`;
`TestEmptyCPUSamplesAreRefused`; `TestMeasureReadsTheModelServerNotTheMachine`;
`TestDecodeSpeedComesFromTheResponse`; `TestRecordCarriesTheContextLengthTheServerReported`;
`TestWriteKeepsEveryOtherModelAndKey`; `TestWriteRefusesInvalidJSON`;
`TestWriteGoesThroughATemporaryFile`; `TestDryRunWritesNothing`.

- [ ] Step 1: write the tests, run `go test`, they fail (the code is absent).
- [ ] Step 2: write the code, run `go test`, every test passes.
