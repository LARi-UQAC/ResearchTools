---
executor: local-coder
tier: standard
bounds:
  max_rounds: 3
  max_tokens: 1500000
  plateau: 2
---

# Plan 3 - Go watchdog: the `reference` command

> **For agentic workers:** run by the local coder model through the driver (rule R39). Return every
> file you create or change in full. Tests run with
> `go test -C .claude/skills/aider-setup/watchdog ./...`.

**Goal:** measure, for one installed model as the machine runs it, the CPU of the model server and the
GPU load during a healthy generation, and keep that reference in `local-model-config.json` for the
`watch` command to read.

**Spec:** `spec.md` decision D1.

## Global Constraints

Standard library only. No numeric literal in code: sampling interval, prompt, token counts and timeouts
come from `aider-watchdog.json`. The tag is an argument, never written in the code (R2). Every call has a
timeout. The write into `local-model-config.json` keeps every other model and key with the same values,
goes through a temporary file and a rename, and refuses an existing file it cannot parse. No test
starts a process, opens a socket or sleeps.

## Review Focus

- The measurement is of the model server process, not of the whole machine.
- A model fully on the CPU has a GPU reference near zero: recorded as measured, not as an error.
- The record stores the context length the server reported, because `watch` compares it.

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
- New settings keys, `{value, provenance}` like the others: `sampleSeconds`, `prompt` (a short fixed
  paragraph request), `numPredict`, `warmupNumPredict`, `generationTimeoutSeconds`. Provenance:
  "proposal 2026-11-09". `settings.go` gains the matching typed fields.
- `type stat struct { Median, Min float64 }`; `type referenceRecord struct { MeasuredAt string; NumCtx int;
  DecodeTPS float64; CPU stat; GPU *stat; Samples int; Source string }`.
- `summarize(cpu []float64, gpu []float64) (referenceRecord, error)`: median and minimum of each series;
  `GPU` is nil when `gpu` is empty; an error on an empty `cpu`.
- `measureReference(d refDeps, tag string, s settings) (referenceRecord, error)`: warms the tag with a
  request of `warmupNumPredict` tokens, reads the loaded context length from `/api/ps`, starts one
  generation of `numPredict` tokens in a goroutine and, every `sampleSeconds` until it ends, reads the
  model-server CPU percent of one core (rise of the CPU seconds over elapsed seconds) and the GPU load.
  The decode speed comes from the response's `eval_count` and `eval_duration`. The dependencies (HTTP
  post and get, runner, clock, sleeper) are injected.
- `writeReference(path, tag string, rec referenceRecord) error`: sets `models[tag].reference_decode`
  (fields `measured_at`, `num_ctx`, `decode_tps`, `cpu_percent` and `gpu_percent` each with `median` and
  `min`, `samples`, `source`), keeping every other value, through a temporary file and a rename.
- `main.go` gains the command `aider-watchdog reference --tag T [--config FILE] [--settings FILE]
  [--dry-run]`; `--dry-run` measures nothing and prints what it would do. It prints one JSON line with the
  record; exit 0 done, 2 refusal, 1 failure.

**Tests to write first, each failing before the code exists:**
`TestSummarizeGivesMedianAndMin`; `TestSummarizeWithoutGPUReadingsGivesNilGPU`;
`TestEmptyCPUSamplesAreRefused`; `TestMeasureReadsTheModelServerNotTheMachine`;
`TestDecodeSpeedComesFromTheResponse`; `TestRecordCarriesTheContextLengthTheServerReported`;
`TestWriteKeepsEveryOtherModelAndKey`; `TestWriteRefusesAnUnreadableFile`;
`TestWriteGoesThroughATemporaryFile`; `TestDryRunWritesNothing`.

- [ ] Step 1: write the tests, run `go test`, they fail (code absent).
- [ ] Step 2: write the code, run `go test`, every test passes.
