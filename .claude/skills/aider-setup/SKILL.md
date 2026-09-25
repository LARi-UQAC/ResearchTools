---
name: aider-setup
description: "Set up and maintain the aider nightly local-coding pipeline: two local Ollama models (a writer that codes and tests, a reviewer that never edits) run one aider process per plan overnight, with no Claude Code involved, driven by aider-plan.ps1/aider-night.ps1 and gated by measured token budgets. Use this skill whenever the user wants to install, tune, or fix the aider kit on this machine; asks to run, resume, or debug an overnight aider plan; wants the distribution zip for students rebuilt or republished; or asks about the GPU/context-window tuning that decides num_ctx, num_gpu and num_thread for a local model. Triggers on: aider-setup, aider kit, aider nightly pipeline, run aider overnight, tune aider models, rebuild aider-kit.zip, aider-plan, aider-night."
allowed-tools: [Read, Write, Edit, Bash, PowerShell]
permissions: [read, write]
---

# aider-setup — the aider nightly local-coding pipeline

Aider has no notion of Claude Code, so this is not a wrapper around it: it is a second,
independent local-coding pipeline that runs at night, when Claude Code and the model it drives
are both closed. The full procedure — installation, the daily-use commands, GPU/context tuning,
every measured failure mode and its fix — lives in [MANUAL.md](MANUAL.md); read it before
changing anything here. This file is the entry point and the map of what lives where.

## The three pieces, and why they have three different lifetimes

| Piece | Kind | When it runs | Needs Claude Code |
|---|---|---|---|
| This skill | Claude Code skill | daytime, once per machine, to set up or fix the pipeline | yes |
| `R26` (plan shape) and `R29` (no literal code in a plan, applies to this kit's writer model too) in [../../rules/workflows.md](../../rules/workflows.md) | rule | whenever any harness writes or executes a plan | no — both bind every harness that writes or runs `docs/superpowers/plans/` |
| `scripts/aider-night.ps1` / `.bat` | plain `cmd` entry point | at night, everything else closed | **no** |

A skill is a Claude Code construct and cannot run when Claude Code is not running, which is why
the nightly runner is a bare PowerShell/`cmd` pair rather than a skill script invoked by name.

## What is in this directory

| Path | What |
|---|---|
| `MANUAL.md` | the whole procedure, source of truth for a human running this |
| `CONFIG_OLLAMA.md` | the GPU/context-window tuning guide, with its measured blocks templated per machine |
| `EXAMPLE-PROMPT-robot.md` + `examples/robot-planner-plans/` | one worked planning prompt and the seven-plan set it produced, so a plan set that fits the token ceilings can be read rather than guessed at |
| `config/conventions.md` | the working protocol handed to the model on every call (`--read`) |
| `config/model-settings.yml` | per-model settings for the writer and reviewer tags |
| `config/context-budget.json` | every token figure this pipeline uses, each with a `_comment` stating provenance (R13) |
| `config/aider.conf.yml` | the aider config template `setup.ps1` installs |
| `config/rules.md` | **generated** — never edit. Regenerated at build time by `scripts/aider-rules-sync.py` from the canonical `.claude/rules/*.md` of this repository plus `config/rules-local/` |
| `config/rules-local/aider-kit.md` | rules this kit adds on top of the canonical set (R27) |
| `config/skills.json` + `config/skills/` | the stage-to-skill-bundle map (write / audit / reopen) and the bundles themselves, MIT-licensed third-party files |
| `scripts/aider-plan.ps1` + `scripts/aider-plan-core.ps1` | the driver (entry point) and its pure half (budget, ledger, refusals — dot-sourced, never spawns a process) |
| `scripts/aider-night.ps1` / `.bat` | the nightly `cmd` entry point: branch, run every plan, push, never merge |
| `scripts/run-detached.ps1` | runs a night detached, holding a wake lock so Modern Standby does not throttle it |
| `scripts/aider-rules-sync.py` | derives `config/rules.md` from `.claude/rules/*.md` |
| `scripts/aider-gpu-probe.py` / `aider-thread-probe.py` / `aider-ollama-config.py` | measure which `(model, num_ctx)` puts layers on the GPU, sweep the thread/bandwidth axes, and turn the measured numbers into a tuned Ollama tag |
| `scripts/aider-defect-check.py` + `aider-defects.json` | tells a reader whether a run hit one of the defect signatures this pipeline has already measured and fixed once |
| `scripts/aider-ab.ps1` | the A/B test harness: `fixture`, `snapshot`, `compare` |
| `scripts/ollama-tune.ps1` / `.bat` | the tuning test a `CONFIG_OLLAMA.md` recommendation is built from |
| `scripts/Test/` | offline suites — see [../../rules/testing.md](../../rules/testing.md) |
| `scripts/build/` | **the packaging pipeline that produces the student-facing `aider-kit.zip` from this directory's own canonical sources.** See below |
| `install-hooks.ps1`, `new-project.ps1`, `setup.ps1`, `git-hooks/`, `project-template/` | what the assembled kit installs on a student's or the operator's own machine |

## Building the distribution zip

The kit handed to students is assembled **from this skill's own files**, never from a copy
living elsewhere, so there is one source of truth rather than a copy that drifts. Run from
`scripts/build/`:

```powershell
$out = "$env:TEMP\kit-$(Get-Random)"
python build_kit.py       $out aider.conf.yml.saved
python finish_kit.py      $out
python newproject_ps1.py  $out
python patch_setup.py     $out
.\verify-kit-install.ps1  -Kit $out
```

`verify-kit-install.ps1` is the gate: it installs the assembled kit into a scratch home and
**runs the driver from that installation**, because a kit that is green on every static check
can still ship a config the installed aider refuses to read — see its own header for the
2026-09-04 measurement that is why it exists. `build_kit.py` refuses to finish if any of seven
machine-identifying terms (the operator's account name, the repository's own name, the GPU
model, ...) survive into the assembled tree, with a negative control proving the detector can
fail. `aider.conf.yml.saved` is a machine-local test fixture (gitignored — see `.gitignore`),
not a build input read by `build_kit.py` itself; it is the *second* CLI argument the operator
passes, and it is also what `verify-kit-install.ps1` defaults to when driving a real dry run
against this machine's own installed aider.

`config/rules.md` is the one file in this tree that is never hand-edited and never committed
as a static copy that could go stale: `build_kit.py` regenerates it at build time by invoking
`scripts/aider-rules-sync.py` against `.claude/rules/` of this repository, so the kit can never
ship a rules file the repository's own rules have moved past.

## Registration

Routed from [../../CLAUDE.md](../../CLAUDE.md)'s tooling table, [../../rules/testing.md](../../rules/testing.md)'s
script-surface inventory and offline-test block, [../../rules/workflows.md](../../rules/workflows.md)'s flows
table (R26) and [../../rules/code-style.md](../../rules/code-style.md) (R27), `mirror-policy.json`
(rules live, agents/commands/skills by design — this harness receives none of them), and
`.claude/skills/rt-observe/harnesses.json` (the `aider` adapter). See `README.md` and
`Architecture.md` for the authoritative inventory entries.
