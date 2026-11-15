---
executor: local-coder
tier: standard
bounds:
  max_rounds: 3
  max_tokens: 1500000
  plateau: 2
---

# Plan 5 - The watch loop and the command line

Return every file you create in full. Tests run with `go test -C .claude/skills/aider-setup/watchdog ./...`.

**Goal:** the loop that polls the machine, feeds the tracker and stops the process, and the `watch`
command line.

**Spec:** `spec.md`.

## Constraints

Standard library only. No numeric literal in code. The program never changes the run record or any plan
file. No test starts a process, opens a socket, sleeps or reads the real clock: the clock, the sleep, the
runner and the getter are passed in.

## Cases to cover

- After a stop the tracker starts clean, so one stall is not counted twice.
- A stall writes exactly one log line and the signal file, and nothing else.

---

### Task 1: loop and command line

**Files:**
- Create: `.claude/skills/aider-setup/watchdog/main.go`
- Test: `.claude/skills/aider-setup/watchdog/main_test.go`

**Reads, do not modify:** `.claude/skills/aider-setup/watchdog/settings.go`,
`.claude/skills/aider-setup/watchdog/tracker.go`, `.claude/skills/aider-setup/watchdog/readings.go` and
`.claude/skills/aider-setup/watchdog/actions.go` (all their types and functions).

**Interfaces:**
- `type watchOptions struct` (parent pid, run record path, logs folder, settings, references) and
  `type deps struct` (the runner, the getter, a clock `now() time.Time` and `sleep(time.Duration)`).
- `watch(opts watchOptions, d deps) int`: each poll reads the process table; returns 0 when the parent pid
  is absent; reads the run record and returns 0 when its state is in `terminalStates`; reads the model
  from the server and the GPU load; builds a `reading` whose CPU percent is the rise of the model-server
  CPU seconds since the previous poll over the elapsed seconds; calls the tracker; and when it returns
  true runs `stopWork`, writes the log line and the signal file, and creates a new tracker. Sleeps
  `pollSeconds` between polls through `d.sleep`.
- `main` reads the command line `aider-watchdog watch --driver-pid N --run-record PATH --logs-dir DIR
  --settings FILE --reference FILE`. A missing argument, an unreadable settings file or an unknown command
  prints one JSON error line and exits with code 2.

**Tests to write first, each failing before the code exists:**
`TestWatchReturnsZeroOnATerminalState`; `TestWatchReturnsZeroWhenTheParentIsGone`;
`TestAStallStopsTheChildAndWritesOneLogLineAndTheSignal`;
`TestNoSecondStopUntilTheTrackerIsFilledAgain`; `TestNothingIsWrittenWithoutAStall`;
`TestMissingArgumentExitsTwo`; `TestUnknownCommandExitsTwo`.

- [ ] Step 1: write the tests, run `go test`, they fail (the code is absent).
- [ ] Step 2: write the code, run `go test`, every test passes.
