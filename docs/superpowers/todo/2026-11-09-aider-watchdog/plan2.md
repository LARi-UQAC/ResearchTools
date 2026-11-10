---
executor: local-coder
tier: standard
bounds:
  max_rounds: 3
  max_tokens: 1500000
  plateau: 2
---

# Plan 2 - Go watchdog: readings, stop action, loop and command line

> **For agentic workers:** run by the local coder model through the driver (rule R39). Return every
> file you create in full. Tests run with `go test -C .claude/skills/aider-setup/watchdog ./...`.

**Goal:** the part of the program that touches the machine, behind an injected `runner`, plus the loop
that polls, decides and stops the process, and the `watch` command line.

**Spec:** `spec.md` decisions D3 to D7.

## Global Constraints

Standard library only. No numeric literal in code, except the named constant for 100-nanosecond ticks
per second. Every external program and HTTP call goes through an injected function with a timeout from
the settings. Output paths are resolved inside the logs folder and refused otherwise. Nothing printed or
written carries a student report file name (R34). The program never writes the run record or
`progress.md`. No test starts a process, opens a socket, sleeps or reads the real clock.

## Review Focus

- The watchdog's own process and its children are never counted as the driver's work.
- A process still alive after the stop is reported as a failed stop, not a success.
- After a stop the tracker restarts clean, so one stall is not counted twice.
- A stall writes exactly one log line and the signal file; nothing else is ever written.

---

### Task 1: readings, actions, loop and command line

**Files:**
- Create: `.claude/skills/aider-setup/watchdog/readings.go`
- Create: `.claude/skills/aider-setup/watchdog/actions.go`
- Create: `.claude/skills/aider-setup/watchdog/main.go`
- Test: `.claude/skills/aider-setup/watchdog/readings_test.go`
- Test: `.claude/skills/aider-setup/watchdog/actions_test.go`
- Test: `.claude/skills/aider-setup/watchdog/main_test.go`

**Reads, do not modify:** `.claude/skills/aider-setup/watchdog/settings.go` and `tracker.go` (the
`settings`, `reference`, `reading`, `tracker` types and `loadSettings`, `loadReferences`, `newTracker`).

**Interfaces:**
- `type runner func(name string, args []string, timeout time.Duration) (string, error)` and
  `type getter func(url string, timeout time.Duration) ([]byte, error)`.
- `type procRow struct { PID, ParentPID int; Name string; CPUSeconds float64 }`;
  `parseProcessTable(text string) ([]procRow, error)` reads the JSON of `Get-CimInstance Win32_Process |
  Select-Object ProcessId,ParentProcessId,Name,KernelModeTime,UserModeTime | ConvertTo-Json -Compress`, a
  list or a single object; `CPUSeconds` is kernel plus user ticks over the ticks-per-second constant; an
  error on text that is not that shape. `readProcessTable(run runner, timeout time.Duration)`.
- `descendantsOf(rows []procRow, rootPID int, excluded map[int]bool) []procRow` (an excluded pid and
  everything below it are left out); `childHoldingWork(rows []procRow, rootPID int, excluded map[int]bool)
  (procRow, bool)`: the direct child of the root, not excluded, whose subtree has the most CPU seconds.
- `readGPUPercent(run runner, timeout time.Duration) *float64`: the highest line of `nvidia-smi
  --query-gpu=utilization.gpu --format=csv,noheader,nounits`; nil when the program is absent, fails or
  prints no number.
- `readOllamaPS(get getter, url string, timeout time.Duration) (model string, contextLength int, err
  error)`: the first model of `GET <url>/api/ps` (fields `name` and `context_length`); empty model when
  none is loaded.
- `readRunRecord(path string) (state, plan string)`: both empty when the file is missing or unreadable.
- `serverCPUSeconds(rows []procRow, names []string) float64`: CPU seconds summed over processes whose
  name matches one of the names (case-insensitive, without `.exe`).
- `stopWork(run runner, timeout time.Duration, driverPID, selfPID int) (bool, error)`: reads the table,
  picks `childHoldingWork` with the watchdog's own pid excluded, runs `taskkill /PID <pid> /T /F`, reads
  the table again and returns whether that pid is gone.
- `resolveInside(logsDir, name string) (string, error)`; `appendStopLine(logsDir string, at time.Time,
  r reading) error` (one JSON line in `watchdog.log`: time, event `stop`, model, `cpu_percent`,
  `gpu_percent`, plan); `writeStopSignal(logsDir, plan string) error` (`watchdog-stop.json`).
- `watch(opts watchOptions, d deps) int`: each poll reads the process table, returns 0 when the driver pid
  is absent, reads the run record and returns 0 on a terminal state, builds a `reading` (the CPU percent
  is the rise of the server CPU seconds since the previous poll over the elapsed seconds), calls the
  tracker, and on true runs `stopWork`, writes the log line and the signal, and starts a new tracker.
  Sleeps `pollSeconds` between polls through `d.sleep`.
- `main`: `aider-watchdog watch --driver-pid N --run-record PATH --logs-dir DIR --settings FILE
  --reference FILE`. A missing argument, an unreadable settings file or an unknown command prints one JSON
  error line and exits 2. Other commands are added by plan 3.

**Tests to write first, each failing before the code exists:**
`TestParseProcessTableAcceptsAListAndASingleObject`; `TestCPUSecondsComeFromKernelPlusUserTicks`;
`TestTextThatIsNotATableIsRefused`; `TestDescendantsExcludeTheWatchdogAndItsChildren`;
`TestChildHoldingWorkIsTheDirectChildWithTheMostCPU`; `TestServerCPUSecondsMatchesNamesWithoutExe`;
`TestGPUPercentIsTheHighestLine`; `TestMissingNvidiaSmiGivesNil`; `TestReadOllamaPSReturnsModelAndContext`;
`TestNoLoadedModelGivesAnEmptyModel`; `TestCorruptRunRecordReadsAsEmpty`;
`TestStopWorkReportsAProcessStillAlive`; `TestPathOutsideTheLogsFolderIsRefused`;
`TestWatchReturnsZeroOnATerminalState`; `TestWatchReturnsZeroWhenTheDriverIsGone`;
`TestAStallStopsTheChildAndWritesOneLogLineAndTheSignal`;
`TestNoSecondStopUntilTheTrackerIsFilledAgain`; `TestMissingArgumentExitsTwo`.

- [ ] Step 1: write the tests, run `go test`, they fail (code absent).
- [ ] Step 2: write the code, run `go test`, every test passes.
