# Aider watchdog - spec

## Why

2026-11-09, aider-setup kit: a test written by the writer model looped for 6 hours while the GPU sat
at 0 percent and nothing reported it. The owner asked for a daemon that reads the CPU and the GPU.

## What

One small script, started by the kit driver when it starts, stopped when the run ends. While the
writer or the reviewer should be generating, it reads the CPU of the model server and the GPU load. If
both fall far below what this machine measured for the same model, it stops the process in progress
and the driver moves on to the next plan. The plan stays undone: progress.md is not touched and the plan
is not marked blocked.

## Language and conventions

Python 3.11, standard library only. Functions named `verb_complement`, each with a header (Purpose,
Inputs, Outputs, Raises). Type annotations. No numeric literal in code: thresholds come from
`aider-watchdog.json`. Comments in English, stating why. Tests in the `Test` folder, with fakes for
the processes, the GPU, the model server and the clock: no test starts a process or sleeps.

## Decisions

- D1 The reference is measured, not fixed. After the model is loaded and generating, the first readings
  of the model-server CPU and of the GPU become that model's reference. A new model (the reviewer after
  the writer) gets its own reference.
- D2 Validation of the machine tuning: once the model is loaded, the script compares the context length
  the server reports with the `num_ctx` of the model's tuned Modelfile and logs a `config_mismatch` line
  when they differ. It never stops the run for that.
- D3 Nothing is judged until the model is loaded and until the run record state is `writing` or
  `auditing`. The test phase is not watched in this version.
- D4 A stall is `low_readings` consecutive readings in which every dimension that has a real reference
  (CPU, GPU) is under `low_fraction` of it. The script then stops the driver's direct child that holds
  the work, with its subtree, and writes the signal file `watchdog-stop.json` (the plan name).
- D5 One log, `watchdog.log` in the plans `.logs` folder, one JSON line per event: time, event, model,
  CPU percent, GPU percent, plan. Only a stall and a `config_mismatch` write a line.
- D6 The script never writes the run record or `progress.md`. Exit codes: 0 normal end, 2 refusal.

## Driver patch (by hand, owner approval)

In `aider-plan.ps1`: start the script after `Initialize-RunRecord`, stop it at the end of the run, and
when `watchdog-stop.json` names the current plan after a child returns, delete the signal and move to
the next plan without writing to `progress.md`.
