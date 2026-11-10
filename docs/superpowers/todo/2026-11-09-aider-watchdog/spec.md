# Aider watchdog - spec

## Why

2026-11-09, aider-setup kit: a test written by the writer model looped for 6 hours while the GPU sat
at 0 percent and nothing reported it. The owner asked for a daemon that reads the CPU and the GPU.

## What

One small Go program, `aider-watchdog.exe`, started by the kit driver when it starts and stopped when
the run ends. While the writer or the reviewer should be generating, it reads the CPU of the model
server and the GPU load. If both fall far below what this machine measured for the same model, it stops
the process in progress and the driver moves on to the next plan. The plan stays undone: progress.md is
not touched and the plan is not marked blocked. The same program has a second command, `reference`,
that measures that reference. No Python anywhere.

## Language and conventions

Go 1.22 or later, standard library only, one module in `.claude/skills/aider-setup/watchdog/`, package
`main`. Code formatted by `gofmt`; names are unexported `verbComplement` camelCase (the Go form of the
verb-complement rule); every function has a comment header with Purpose, Inputs, Outputs and, when it
returns an error on purpose, the condition. Errors are returned and wrapped, never ignored, and a panic
is never a control flow. No numeric literal in code: thresholds come from `aider-watchdog.json`. Comments
in English, stating why. Tests are `_test.go` files beside the code and run with
`go test -C .claude/skills/aider-setup/watchdog ./...`. Tests use fakes (a `runner` function for every
external program and HTTP call, a clock and a sleeper passed in): no test starts a process, opens a
socket or sleeps.

## Decisions

- D1 The reference is measured on this machine. `aider-watchdog reference --tag T` loads the tuned model
  as the machine runs it, samples the model-server CPU and the GPU load during one healthy generation,
  and writes the median and the minimum under `models[T].reference_decode` of `local-model-config.json`
  with the context length the server reported. The other models and keys keep their values (their order
  may change). Why a measurement: the skill opt-local-vram-llm recorded only the context, the decode
  speed and the GPU residency, and has no entry for the kit models, which are too large for the card.
  A model with no reference is not judged.
- D2 Validation of the machine tuning: once the model is loaded, the program compares the context length
  the server reports with the reference `num_ctx`. When they differ, that model is not judged. Nothing
  is written.
- D3 Nothing is judged until the model is loaded (listed by the server at `/api/ps`) and the run record
  state is `writing` or `auditing`. The test phase is not watched in this version.
- D4 A stall is `lowReadings` consecutive readings in which every dimension with a real reference (CPU,
  GPU) is under the minimum measured in the reference run. The program then stops the driver's direct
  child that holds the work, with its subtree (`taskkill /T /F`), and writes the signal file
  `watchdog-stop.json` (the plan name).
- D5 One log, `watchdog.log` in the plans `.logs` folder, one JSON line per stop: time, event, model,
  CPU percent, GPU percent, plan. Only a stop writes a line.
- D6 The program never writes the run record or `progress.md`. Exit codes: 0 normal end, 2 refusal.
- D7 The CPU of the model server is the rise of the kernel plus user CPU seconds of the processes named
  in the settings, from `Get-CimInstance Win32_Process` through PowerShell, as a percent of one core.
  The GPU load is `nvidia-smi --query-gpu=utilization.gpu`; absent, it is an unknown reading.

## Driver patch (by hand, owner approval)

The program only stops the process. The driver must know that it did, so it can go on to the next plan
instead of running its own failure path (which writes a `[!]` line in `progress.md`). In
`aider-plan.ps1`: start `aider-watchdog.exe watch` after `Initialize-RunRecord`, giving it the driver
pid, the run record, the logs folder, the settings and the reference file; stop it at the end of the
run; and after each child returns, if `watchdog-stop.json` names the current plan, delete the signal and
move to the next plan without writing to `progress.md`. The plan stays undone and is replayed at the
next run. The test command for Go plans is `go test -C <module folder> ./...`.

## Needs from outside the kit

The Go toolchain (the cloud installs it, the kit has no permission). Where the kit finds the reference
file for students is decided with the driver patch.
