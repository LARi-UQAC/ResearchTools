---
executor: local-coder
tier: standard
bounds:
  max_rounds: 3
  max_tokens: 1500000
  plateau: 2
---

# Plan 4 - Stopping the process and writing the record

Return every file you create in full. Tests run with `go test -C .claude/skills/aider-setup/watchdog ./...`.

**Goal:** find the child process that holds the work, stop it, and write the one log line and the signal
file.

**Spec:** `spec.md`, section "What `watch` does".

## Constraints

Standard library only. No numeric literal in code. Output files are resolved inside the logs folder and
refused otherwise. Nothing is printed or written that contains the name of a student file. No test starts
a process or reads the real clock.

## Cases to cover

- The watchdog's own process and its children are never counted as the parent's work.
- A process still alive after the stop is reported as a failed stop.

---

### Task 1: actions

**Files:**
- Create: `.claude/skills/aider-setup/watchdog/actions.go`
- Test: `.claude/skills/aider-setup/watchdog/actions_test.go`

**Reads, do not modify:** `.claude/skills/aider-setup/watchdog/readings.go` (the types `runner` and
`procRow`, and `readProcessTable`) and `.claude/skills/aider-setup/watchdog/tracker.go` (the type
`reading`).

**Interfaces:**
- `descendantsOf(rows []procRow, rootPID int, excluded map[int]bool) []procRow`: every descendant of the
  root; an excluded pid and everything below it are left out.
- `childHoldingWork(rows []procRow, rootPID int, excluded map[int]bool) (procRow, bool)`: the direct child
  of the root, not excluded, whose subtree has the most CPU seconds.
- `stopWork(run runner, timeout time.Duration, parentPID, selfPID int) (bool, error)`: reads the table,
  picks `childHoldingWork` with the watchdog's own pid excluded, runs `taskkill /PID <pid> /T /F`, reads
  the table again and returns whether that pid is gone.
- `resolveInside(logsDir, name string) (string, error)` returns the path of a file of the logs folder and
  refuses a name that would leave it.
- `appendStopLine(logsDir string, at time.Time, r reading) error` appends one JSON line to the file
  `watchdog.log` (time, event `stop`, model, `cpu_percent`, `gpu_percent`, plan).
- `writeStopSignal(logsDir, plan string) error` writes the signal file named in the spec (a JSON file) with the plan name.

**Tests to write first, each failing before the code exists:**
`TestDescendantsExcludeTheWatchdogAndItsChildren`;
`TestChildHoldingWorkIsTheDirectChildWithTheMostCPU`; `TestStopWorkReportsAProcessStillAlive`;
`TestStopWorkReportsAGoneProcess`; `TestPathOutsideTheLogsFolderIsRefused`;
`TestAppendStopLineWritesOneJSONLine`; `TestWriteStopSignalNamesThePlan`.

- [ ] Step 1: write the tests, run `go test`, they fail (the code is absent).
- [ ] Step 2: write the code, run `go test`, every test passes.
