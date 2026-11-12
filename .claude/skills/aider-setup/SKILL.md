---
name: aider-setup
description: "Run, set up and maintain the aider local-coding kit: two local Ollama models (a writer that codes and tests, a reviewer that audits and never edits) execute the plans of a project, one plan or a whole night, from a plain command line with no Claude Code involved, gated by measured token budgets. Use this skill to code one plan or several plans on local models, to mount or clean a project (spec, plans, progress), to read a run (progress, audit, quality), to start a night from a DOS or PowerShell shell, to install or tune the kit, or to rebuild the student zip. Triggers on: aider-setup, aider kit, aider-plan, aider-night, run a plan on the local model, run aider overnight, mount a kit project, tune aider models, rebuild aider-kit.zip."
allowed-tools: [Read, Write, Edit, Bash, PowerShell]
permissions: [read, write]
---

# aider-setup - the aider local-coding kit

The kit is a pipeline of its own. Aider knows nothing about Claude Code, and nothing here needs it:
everything below runs from a plain command line. A wrapper (the `local-coder` agent) only adds a cloud
model that mounts one plan, starts the kit and reviews the result. The detailed manual,
[MANUAL.md](MANUAL.md), covers installation, GPU tuning and every measured failure; it is not needed to run.

## 1. Run it from a command line

Nothing is installed or copied: the scripts run from where they are, in
`C:\Martin Otis\OutilsLogiciels\ResearchTools\.claude\skills\aider-setup\scripts`, and read the `config` folder
next to it. Run `.\setup.ps1 -InstallAiderPath` once from the ResearchTools clone to put that `scripts` folder on your user `PATH` (add-only, specific to your machine), then type the commands below from any folder. Two entry points, both
PowerShell scripts that need no Claude Code. Close the other programs first (the
browser, the editors, Claude Code): a 21 GB writer and a 21 GB reviewer cannot both be resident in 32 GB, so the
driver loads one model at a time and unloads it before the next stage, and everything else steals that memory.

| Goal | Command (from a DOS shell or PowerShell) |
|---|---|
| A night: one or many plans, a working branch, a wake lock, push offered, never a merge | `aider-night.bat C:\work\my-project` (switches: `-DryRun`, `-Branch NAME`, `-NoAudit`, `-Push`, `-PullRequest`) |
| One plan, or the plans of a project without the night wrapper | `aider-plan.ps1 -Path C:\work\my-project -TestCommand '<test command>'` (add `-DryRun` first; `-QualityOnly` scores the code a run left behind) |
| A long run that survives closing the terminal | `run-detached.ps1 -Project <project> -LogFile <log> -RcFile <rc> -TestCommand '<test command>'`; the `.rc` file appears only when the run ends |

- **The test command** is the project's own interpreter and test files, relative to the project, for example
  `.\.venv\Scripts\python.exe -m unittest discover -s Test -p "test_*.py"`. `aider-plan.ps1` takes it with
  `-TestCommand`, `aider-night` and `run-detached` with the environment variable `AIDER_TEST_COMMAND`. With none, a
  required test is a refusal, never a silent skip. Go and Rust projects use `go test -C <module> ./...` and
  `cargo test --manifest-path <crate>/Cargo.toml`.
- **Always run `-DryRun` first.** It starts no model, writes nothing and catches a missing plan, an over-budget
  file or a missing key in seconds.
- **Never** pass `-AllowCloud` or a cloud `-Model`, and do not use `-NoAudit` unless you only want the code: the
  review by the second model is part of the kit. The per-stage skills (write, audit, reopen) are mandatory and
  have no switch.
- **Which configuration it reads.** In order: beside an explicit `-Config` or `-BudgetFile`; else the `config` folder
  next to the `scripts` folder (this repository, or an unpacked student kit); else `~/.config/aider`, which only a
  kit installed by `setup.ps1` for the student zip uses. The log line `configuration : ... (kit layout)` says which.
  The configuration files name their own files by relative paths (`rules.md`, `skills/code-reviewer.md`), so they hold
  nothing specific to a machine.
- **The watchdog** starts with the driver when `watchdog\aider-watchdog.exe` (built from the Go sources of that folder,
  git-ignored) and `config\model-reference.json` (the load of each model while it works, measured on this machine by
  `aider-watchdog reference`, git-ignored) exist; `AIDER_MODEL_REFERENCE` can name another reference file. Without them
  the output says `WARNING: watchdog not started` and the run goes on unprotected: check for `watchdog started (pid N)`
  in the first lines of the log.
- **Refusals before anything starts**: battery power, the branch `main` or `master`, no config, a non-local model,
  tests required with no test command, a missing budget key, an always-on file that does not exist. Each names
  what is missing.

## 2. Build a project, then clean it

One project is its own directory with its own git repository and its own `.venv`.

1. `new-project.ps1 -Name my-project -Root C:\work` (from the kit folder; `-Python` picks the interpreter,
   `-Branch` the branch, `-DryRun` previews). Use a path without a space. It creates the directory, git on a
   working branch (never `main`), the two branch hooks, `docs\superpowers\plans\` with its three templates,
   `Test\` and the `.venv`. It refuses an existing directory. Git needs `user.name` and `user.email` set.
2. Write the three inputs in `docs\superpowers\plans\`, replacing the templates:
   - `spec.md`: what is built, and the section **"Language and conventions"** (language, case of names,
     documentation comment, test folder and command, dependencies file). Without that section the model must
     not guess a language. Re-read on every call, so keep it under its ceiling.
   - `plan<N>.md`, one stage each, ordered steps. **Every step names the file it touches** by its path from the
     project root; a step with no file cannot run. At most ten files per plan. Files the plan only reads go in a
     paragraph that starts `**Reads, do not modify:**`. The file is named `plan1.md` for a single plan, and the
     driver reads only names of the form `plan<digits>.md`.
   - `progress.md`: one `## plan<N>.md` section per plan and one line per file, `- [ ] create <path> as
     plan<N>.md describes` (or `modify`). Marks: `- [ ]` open, `- [x]` done, `- [~]` done in part (a line says what is left; it does not stop the plan),
     `- [!]` blocked (a line says why; it stops the plan).
3. Copy into the project, with their relative paths, every existing file the plan reads or changes, and what its
   tests import. Never the whole repository: the audit reads every source file of the project. Create an EMPTY
   `audit.md` beside the inputs. Install the libraries the spec declares into the project's `.venv`: the kit
   never installs anything. Commit this baseline.
4. **Clean the documents for the small writer model**, which sees only the project and takes every sentence as a
   fact about its own world. Run `python plan_clean.py <project>\docs\superpowers\plans` (a dry run), then add
   `--write`. It removes a front matter header, rule and decision numbers, the "run by the local coder" wording,
   and the instruction "run the file", and it lists every line it could not fix: rewrite or delete each one, and
   run it again until it reports no hit left. Run it on the mounted project, never on the source plans. By hand,
   remove what it cannot see for itself: people, roles and other tools ("the owner", "the cloud", "the
   session"), dates and the story of a value, where a document came from ("condensed from..."), other plans or
   projects, a header written for another program, a bare file name (it creates an empty file at the root),
   any question or choice left to someone else (the model cannot ask), and any instruction to run a command (the
   harness runs the tests). Keep, for each file, its path, what it holds, its signatures and types, the name and
   meaning of each test, the exact values, the commands that run in the project. The dry run also says "Split the
   plan" when a plan creates more files than one reply can hold: split it before the run, because a cut reply
   leaves the files empty.

## 3. Read the result

```powershell
cd C:\work\my-project
git log --oneline
Get-Content docs\superpowers\plans\progress.md
Get-Content docs\superpowers\plans\audit.md
```

- `progress.md`: `- [!]` lines say where a plan stopped and why. A non-zero exit means a plan was blocked; every
  other plan still ran. `blocks.md` (written when a plan blocked) gives the token counts and the failing tests, and
  tells which of the three causes happened: reply cut at the limit (split the plan), window filled (make the plan
  produce less per reply), or three fix attempts used (a test that contradicts the plan is a plan defect).
- `audit.md`: the reviewer's findings, each naming a file and a line. Read them against the code.
- `quality.md`: one percentage per plan, 80 percent the reviewer's plan-versus-code judgement and 20 percent the
  share of the plan's own test files that pass. A plan at 80 with failing tests is code to finish, not to rewrite;
  a plan the reviewer could not score reads "not scored", never 0.
- `requirements.txt`: read it before installing; it is the one place a run can ask your machine to fetch a package.
  Install with `.\.venv\Scripts\python.exe -m pip install -r requirements.txt`.
- A stalled run: the optional watchdog (started by the driver, `watchdog started (pid N)` in the output) stops a
  child whose model server stays idle and writes one line to `docs\superpowers\plans\.logs\watchdog.log`; the plan
  is then left unticked. Installing it is in the manual.
- Logs are UTF-8 with a byte order mark. The driver passes `--no-detect-urls` to aider so that it never opens
  the URLs found in a plan.

## 4. Where things are

| Path | What |
|---|---|
| `MANUAL.md` | installation, GPU and context tuning, the worked example, every measured failure |
| `CONFIG_OLLAMA.md` | the tuning guide, with its measured blocks templated per machine |
| `config/conventions.md`, `config/rules.md` | the working protocol and the coding rules handed to the model on every call; both hand-written, the only copies. `scripts/aider-rules-check.py` validates the rules before every run |
| `config/skills.json` + `config/skills/` | the stage-to-brief map (write, audit, reopen) and the briefs, written in our own words |
| `config/context-budget.json`, `model-settings.yml`, `aider.conf.yml` | every token figure with its provenance, the per-model settings, and the aider config template `setup.ps1` installs |
| `scripts/aider-plan.ps1` + `aider-plan-core.ps1` | the driver and its pure half (budget, ledger, marks, quality score) |
| `scripts/aider-night.ps1` / `.bat`, `run-detached.ps1` | the night entry point and the detached launcher (it runs the `aider-night.ps1` beside it) |
| `scripts/plan_clean.py` + `plan-clean.json` | the mechanical cleaning of a mounted spec and plans |
| `scripts/aider-defect-check.py` + `aider-defects.json` | tells whether a run hit a defect signature already measured and fixed |
| `scripts/aider-gpu-probe.py`, `aider-thread-probe.py`, `aider-ollama-config.py`, `ollama-tune.ps1`, `aider-ab.ps1` | GPU and thread measurements, tuned tags, the A/B harness |
| `new-project.ps1`, `setup.ps1`, `install-hooks.ps1`, `git-hooks/`, `project-template/`, `watchdog/` | what the kit installs on a machine: scaffolder, installer, branch hooks, the three templates, the Go watchdog sources |
| `scripts/Test/` | offline suites, listed in [../../rules/testing.md](../../rules/testing.md) |
| `scripts/build/` | assembles the student `aider-kit.zip` from this directory (see section 5) |

Rules of plan shape (R26, R29) bind every harness and are in [../../rules/workflows.md](../../rules/workflows.md).
A skill cannot run when Claude Code is closed, which is why the night is a bare PowerShell and `cmd` pair.

## 5. Install, tune and build the zip

- **Install** applies only to the student zip: `setup.ps1` from the unpacked kit copies the scripts to `~/.local/bin`
  and the configuration to `~/.config/aider`. In ResearchTools nothing is installed.
- **Tune** a model for this GPU with the probes and `aider-ollama-config.py` (MANUAL, step 4).
- **Build the zip** from this skill's own files, never from a copy elsewhere. From `scripts/build/`:

```powershell
$out = "$env:TEMP\kit-$(Get-Random)"
python build_kit.py       $out aider.conf.yml.saved
python finish_kit.py      $out
python newproject_ps1.py  $out
python patch_setup.py     $out
.\verify-kit-install.ps1  -Kit $out
```

`verify-kit-install.ps1` is the gate: it installs the assembled kit into a scratch home and runs the driver from that
installation. `build_kit.py` refuses to finish if a machine-identifying term survives into the tree. `aider.conf.yml.saved`
is a machine-local, git-ignored fixture. The kit carries `watchdog/` as source only, never the `.exe`.

## Registration

Routed from [../../CLAUDE.md](../../CLAUDE.md)'s tooling table, [../../rules/testing.md](../../rules/testing.md),
[../../rules/workflows.md](../../rules/workflows.md) (R26), [../../rules/code-style.md](../../rules/code-style.md),
`mirror-policy.json` (this harness receives no agents, commands or skills) and `.claude/skills/rt-observe/harnesses.json`
(the `aider` adapter).
