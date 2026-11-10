# Aider watchdog

## Purpose

`aider-watchdog.exe` is a small Windows command-line program written in Go. It has two commands.

- `watch` runs beside a long job started by a PowerShell script (the parent). While a language model
  should be generating, it reads the CPU load of the model server and the GPU load. When both stay far
  below what was measured earlier for the same model, it stops the parent's current child process and
  records one line.
- `reference` measures that earlier reference for one model and saves it.

## Language and conventions

Go 1.22 or later, standard library only, one module in `.claude/skills/aider-setup/watchdog/`, package
`main`. Code formatted with `gofmt`. Names are unexported camelCase. Every function has a comment header
with its purpose, its inputs, its outputs and, when it returns an error on purpose, the condition.
Errors are returned and wrapped, never ignored. No numeric literal in code: every threshold is read from
`aider-watchdog.json`. Comments are in English and say why, not what. Tests are `_test.go` files beside
the code, run with `go test -C .claude/skills/aider-setup/watchdog ./...`. Tests use fakes: functions
passed in for running a program, for HTTP calls, for the clock and for sleeping. No test starts a
process, opens a socket or sleeps. Use invented plan and model names in tests.

## Files

- `aider-watchdog.json`: the settings. Each key is `{"value": ..., "provenance": "..."}`; `provenance`
  is a short non-empty text saying where the value comes from.
- `local-model-config.json`: the reference file. Under `models`, each key is a model tag and may hold
  `reference_decode`: `num_ctx` (integer), `cpu_percent` and `gpu_percent` (each `{"median", "min"}`).
- The run record: a JSON file written by the parent with the fields `state` (for example `writing`,
  `auditing`, `testing`, `done`, `done_with_blocked`, `failed`) and `plan` (the plan file name).
- The logs folder: where `watch` writes `watchdog.log` and `watchdog-stop.json`.

## What `watch` does

- It reads every `pollSeconds`. It ends with exit code 0 when the parent process no longer exists or the
  run record state is one of `terminalStates`.
- It judges nothing until a model is loaded (listed by `GET <ollamaURL>/api/ps`), the run record state is
  in `watchedStates`, and the loaded model has a reference whose `num_ctx` equals the context length the
  server reports.
- A reading holds the model-server CPU percent of one core (the rise of the CPU seconds of the processes
  named in `modelServerNames` between two polls, over the elapsed seconds) and the GPU load.
- A reading is low when every dimension whose reference median is at least `negligibleReferencePercent`
  is under the reference minimum of that dimension. A dimension with a negligible reference is ignored.
- A stall is `lowReadings` low readings in a row; one reading that is not low resets the count.
- On a stall it stops the direct child of the parent process that holds the work (the child whose
  subtree used the most CPU; never the watchdog itself or its children) with `taskkill /PID <pid> /T /F`,
  checks that the process is gone, appends one JSON line to `watchdog.log` (time, event `stop`, model,
  `cpu_percent`, `gpu_percent`, plan), writes `watchdog-stop.json` with the plan name, and starts again
  with an empty count.
- It writes nothing else. It never changes the run record or any plan file.
- Exit codes: 0 normal end, 2 a missing argument or an unreadable settings file.
