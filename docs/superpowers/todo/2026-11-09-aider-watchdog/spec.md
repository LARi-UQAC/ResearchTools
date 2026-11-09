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

- D1 The reference is measured on this machine, not fixed and not guessed. `vram_reference.py` of the
  skill opt-local-vram-llm (plan 2) loads a tuned model as the machine runs it, samples the model-server
  CPU and the GPU load during one healthy generation, and keeps the median and the minimum in
  `local-model-config.json` under `models[tag].reference_decode`, with the context length the server
  reported. The watchdog reads that file; each model (writer, reviewer) has its own reference. A model
  with no reference is not judged. Why a new script: that skill recorded only the context, the decode
  speed and the GPU residency, never the CPU or the load during generation, and it has no entry for the
  kit models, which are too large for the card and were tuned by the kit's own scripts.
- D2 Validation of the machine tuning: once the model is loaded, the script compares the context length
  the server reports with the `num_ctx` of the model's tuned Modelfile. When they differ, the machine
  is not running as tuned, the reference would mean nothing, and that model is not judged. Nothing is
  written.
- D3 Nothing is judged until the model is loaded (listed by the server) and until the run record state is
  `writing` or `auditing`. The test phase is not watched in this version.
- D4 A stall is `low_readings` consecutive readings in which every dimension that has a real reference
  (CPU, GPU) is under the minimum measured in the reference run, which no healthy generation went under. The script then stops the driver's direct child that holds
  the work, with its subtree, and writes the signal file `watchdog-stop.json` (the plan name).
- D5 One log, `watchdog.log` in the plans `.logs` folder, one JSON line per stop: time, event, model,
  CPU percent, GPU percent, plan. Only a stop writes a line.
- D6 The script never writes the run record or `progress.md`. Exit codes: 0 normal end, 2 refusal.

## Driver patch (by hand, owner approval)

The daemon only stops the process. The driver must know that it did, so it can go on to the next plan
instead of running its own failure path (which writes a `[!]` line in `progress.md`). In
`aider-plan.ps1`: start the script after `Initialize-RunRecord`, giving it the reference file; stop it at
the end of the run; and after each child returns, if `watchdog-stop.json` names the current plan, delete
the signal and move to the next plan without writing to `progress.md`. The plan stays undone and is
replayed at the next run.
