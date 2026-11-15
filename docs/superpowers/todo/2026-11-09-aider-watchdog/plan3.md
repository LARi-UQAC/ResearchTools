---
executor: local-coder
tier: standard
bounds:
  max_rounds: 3
  max_tokens: 1500000
  plateau: 2
---

# Plan 3 - Readings of the machine

Return every file you create in full. Tests run with `go test -C .claude/skills/aider-setup/watchdog ./...`.

**Goal:** read the process table, the GPU load, the model server and the run record, behind injected
functions so that tests need no real program.

**Spec:** `spec.md`.

## Constraints

Standard library only. No numeric literal in code, except one named constant for 100-nanosecond ticks
per second. Every external program and every HTTP call goes through an injected function and has a
timeout. No test starts a process, opens a socket or sleeps.

---

### Task 1: readings

**Files:**
- Create: `.claude/skills/aider-setup/watchdog/readings.go`
- Test: `.claude/skills/aider-setup/watchdog/readings_test.go`

**Interfaces:**
- `type runner func(name string, args []string, timeout time.Duration) (string, error)` and
  `type getter func(url string, timeout time.Duration) ([]byte, error)`.
- `type procRow struct { PID, ParentPID int; Name string; CPUSeconds float64 }`;
  `parseProcessTable(text string) ([]procRow, error)` reads the JSON of `Get-CimInstance Win32_Process |
  Select-Object ProcessId,ParentProcessId,Name,KernelModeTime,UserModeTime | ConvertTo-Json -Compress`, a
  list or a single object; `CPUSeconds` is kernel plus user ticks over the ticks-per-second constant; text
  of another shape is an error. `readProcessTable(run runner, timeout time.Duration) ([]procRow, error)`
  runs that command through `powershell`.
- `serverCPUSeconds(rows []procRow, names []string) float64`: the CPU seconds summed over the processes
  whose name matches one of the names (case-insensitive, without `.exe`).
- `readGPUPercent(run runner, timeout time.Duration) *float64`: the highest line of `nvidia-smi
  --query-gpu=utilization.gpu --format=csv,noheader,nounits`; nil when the program is absent, fails or
  prints no number.
- `readOllamaPS(get getter, url string, timeout time.Duration) (model string, contextLength int, err
  error)`: the first model of `GET <url>/api/ps` (fields `name` and `context_length`); an empty model when
  none is loaded.
- `readRunRecord(path string) (state, plan string)`: both empty when the file is missing or unreadable.

**Tests to write first, each failing before the code exists:**
`TestParseProcessTableAcceptsAListAndASingleObject`; `TestCPUSecondsComeFromKernelPlusUserTicks`;
`TestTextThatIsNotATableIsRefused`; `TestServerCPUSecondsMatchesNamesWithoutExe`;
`TestGPUPercentIsTheHighestLine`; `TestMissingNvidiaSmiGivesNil`;
`TestReadOllamaPSReturnsModelAndContext`; `TestNoLoadedModelGivesAnEmptyModel`;
`TestCorruptRunRecordReadsAsEmpty`.

- [ ] Step 1: write the tests, run `go test`, they fail (the code is absent).
- [ ] Step 2: write the code, run `go test`, every test passes.
