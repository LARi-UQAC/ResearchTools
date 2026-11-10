---
executor: local-coder
tier: standard
bounds:
  max_rounds: 3
  max_tokens: 1500000
  plateau: 2
---

# Plan 2 - Readings, stop action, loop and command line

Return every file you create in full. Tests run with `go test -C .claude/skills/aider-setup/watchdog ./...`.

**Goal:** the part of the program that touches the machine, behind injected functions, plus the loop
that polls, decides and stops the process, and the `watch` command line.

**Spec:** `spec.md`.

## Constraints

Standard library only. No numeric literal in code, except one named constant for 100-nanosecond ticks
per second. Every external program and every HTTP call goes through an injected function and has a
timeout read from the settings. Output files are resolved inside the logs folder and refused otherwise.
Nothing is printed or written that contains the name of a student file. The program never writes the run
record or any plan file. No test starts a process, opens a socket, sleeps or reads the real clock.

## Cases to cover

- The watchdog's own process and its children are never counted as the parent's work.
- A process still alive after the stop is reported as a failed stop.
- After a stop the tracker starts clean, so one stall is not counted twice.
- A stall writes exactly one log line and the signal file, and nothing else.

---

### Task 1: readings, actions, loop and command line

**Files:**
- Create: `.claude/skills/aider-setup/watchdog/readings.go`
- Create: `.claude/skills/aider-setup/watchdog/actions.go`
- Create: `.claude/skills/aider-setup/watchdog/main.go`
- Test: `.claude/skills/aider-setup/watchdog/readings_test.go`
- Test: `.claude/skills/aider-setup/watchdog/actions_test.go`
- Test: `.claude/skills/aider-setup/watchdog/main_test.go`

**Reads, do not modify:** `.claude/skills/aider-setup/watchdog/settings.go` and
`.claude/skills/aider-setup/watchdog/tracker.go` (the `settings`, `reference`, `reading` and `tracker`
types and the functions `loadSettings`, `loadReferences`, `newTracker`).

**Interfaces:**
- `type runner func(name string, args []string, timeout time.Duration) (string, error)` and
  `type getter func(url string, timeout time.Duration) ([]byte, error)`.
- `type procRow struct { PID, ParentPID int; Name string; CPUSeconds float64 }`;
  `parseProcessTable(text string) ([]procRow, error)` reads the JSON of `Get-CimInstance Win32_Process |
  Select-Object ProcessId,ParentProcessId,Name,KernelModeTime,UserModeTime | ConvertTo-Json -Compress`, a
  list or a single object; `CPUSeconds` is kernel plus user ticks over the ticks-per-second constant; text
  of another shape is an error. `readProcessTable(run runner, timeout time.Duration) ([]procRow, error)`
  runs that command through `powershell`.
- `descendantsOf(rows []procRow, rootPID int, excluded map[int]bool) []procRow`: every descendant of the
  root; an excluded pid and everything below it are left out.
  `childHoldingWork(rows []procRow, rootPID int, excluded map[int]bool) (procRow, bool)`: the direct child
  of the root, not excluded, whose subtree has the most CPU seconds.
- `readGPUPercent(run runner, timeout time.Duration) *float64`: the highest line of `nvidia-smi
  --query-gpu=utilization.gpu --format=csv,noheader,nounits`; nil when the program is absent, fails or
  prints no number.
- `readOllamaPS(get getter, url string, timeout time.Duration) (model string, contextLength int, err
  error)`: the first model of `GET <url>/api/ps` (fields `name` and `context_length`); an empty model when
  none is loaded.
- `readRunRecord(path string) (state, plan string)`: both empty when the file is missing or unreadable.
- `serverCPUSeconds(rows []procRow, names []string) float64`: the CPU seconds summed over the processes
  whose name matches one of the names (case-insensitive, without `.exe`).
- `stopWork(run runner, timeout time.Duration, parentPID, selfPID int) (bool, error)`: reads the table,
  picks `childHoldingWork` with the watchdog's own pid excluded, runs `taskkill /PID <pid> /T /F`, reads
  the table again and returns whether that pid is gone.
- `resolveInside(logsDir, name string) (string, error)` returns the path of a file of the logs folder and
  refuses a name that would leave it. `appendStopLine(logsDir string, at time.Time, r reading) error`
  appends one JSON line to `watchdog.log`. `writeStopSignal(logsDir, plan string) error` writes
  `watchdog-stop.json` with the plan name.
- `watch(opts watchOptions, d deps) int`: each poll reads the process table; returns 0 when the parent pid
  is absent; reads the run record and returns 0 on a terminal state; builds a `reading`; calls the
  tracker; and on true runs `stopWork`, writes the log line and the signal and creates a new tracker.
  Sleeps `pollSeconds` between polls through `d.sleep`.
- `main`: `aider-watchdog watch --driver-pid N --run-record PATH --logs-dir DIR --settings FILE
  --reference FILE`. A missing argument, an unreadable settings file or an unknown command prints one JSON
  error line and exits 2.

**Tests to write first, each failing before the code exists:**
`TestParseProcessTableAcceptsAListAndASingleObject`; `TestCPUSecondsComeFromKernelPlusUserTicks`;
`TestTextThatIsNotATableIsRefused`; `TestDescendantsExcludeTheWatchdogAndItsChildren`;
`TestChildHoldingWorkIsTheDirectChildWithTheMostCPU`; `TestServerCPUSecondsMatchesNamesWithoutExe`;
`TestGPUPercentIsTheHighestLine`; `TestMissingNvidiaSmiGivesNil`;
`TestReadOllamaPSReturnsModelAndContext`; `TestNoLoadedModelGivesAnEmptyModel`;
`TestCorruptRunRecordReadsAsEmpty`; `TestStopWorkReportsAProcessStillAlive`;
`TestPathOutsideTheLogsFolderIsRefused`; `TestWatchReturnsZeroOnATerminalState`;
`TestWatchReturnsZeroWhenTheParentIsGone`; `TestAStallStopsTheChildAndWritesOneLogLineAndTheSignal`;
`TestNoSecondStopUntilTheTrackerIsFilledAgain`; `TestMissingArgumentExitsTwo`.

- [ ] Step 1: write the tests, run `go test`, they fail (the code is absent).
- [ ] Step 2: write the code, run `go test`, every test passes.
