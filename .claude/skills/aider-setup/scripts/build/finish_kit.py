"""finish_kit.py - generalise the remaining repo references and add the parts
the kit needs to be usable on a machine that is not the one it was built on."""

import pathlib
import sys

import kit_manifest

OUT = pathlib.Path(sys.argv[1])

# --- generalise the toolkit's own name --------------------------------------
for rel in ("config/rules.md", "config/model-settings.yml"):
    f = OUT / rel
    t = f.read_text(encoding="utf-8")
    t = t.replace("Write it in ResearchTools, with a test.",
                  "Write it in the toolkit repository, with a test.")
    t = t.replace("calls the ResearchTools script with project-specific paths",
                  "calls the toolkit script with project-specific paths")
    t = t.replace("harness goes to ResearchTools;", "harness goes to the toolkit repository;")
    t = t.replace("from ResearchTools they stay behind", "from a shared toolkit they stay behind")
    f.write_text(t, encoding="utf-8")

# --- git hooks, per repository ----------------------------------------------
(OUT / "git-hooks").mkdir(exist_ok=True)
(OUT / "git-hooks/pre-commit").write_text("""#!/bin/sh
# Refuse a commit on a protected branch. Installed per repository, into
# .git/hooks/, by install-hooks.ps1 - never through a global core.hooksPath,
# which git also honours when resolving --git-path and which therefore makes a
# delegating hook re-run itself for ever.

branch=$(git symbolic-ref --short HEAD 2>/dev/null) || exit 0
[ -n "$branch" ] || exit 0

case "$branch" in
  main|master)
    echo "pre-commit refused: commit on protected branch '$branch'." >&2
    echo "  Branch first:  git switch -c <name>" >&2
    echo "  Then open a pull request; a human merges it." >&2
    exit 1
    ;;
esac
exit 0
""", encoding="utf-8", newline="\n")

(OUT / "git-hooks/pre-push").write_text("""#!/bin/sh
# Refuse a direct push to a protected branch.
# stdin: <local ref> <local sha> <remote ref> <remote sha>, one line per ref.

refs=$(cat)

echo "$refs" | while read -r _local_ref _local_sha remote_ref _remote_sha; do
  case "$remote_ref" in
    refs/heads/main|refs/heads/master)
      echo "pre-push refused: direct push to '$remote_ref'." >&2
      echo "  Push your own branch, then open a pull request." >&2
      exit 1
      ;;
  esac
done || exit 1
exit 0
""", encoding="utf-8", newline="\n")

# --- the student installer --------------------------------------------------
(OUT / "setup.ps1").write_text(r"""<#
.SYNOPSIS
  Install the aider kit for the current user.

.DESCRIPTION
  Copies the kit's configuration into ~/.config/aider/, writes ~/.aider.conf.yml
  (the one file aider finds by name), and puts the two scripts on PATH in
  ~/.local/bin. Every {{HOME}} placeholder is replaced with your own home
  directory, so nothing in the kit names anyone's machine.

  It ADDS and never silently replaces: an existing file is left alone unless
  -Force is passed, and -DryRun reports everything and writes nothing.

.EXAMPLE
  .\setup.ps1 -DryRun
  .\setup.ps1
#>
[CmdletBinding()]
param(
    [switch]$DryRun,
    [switch]$Force
)

$ErrorActionPreference = "Stop"
$kit = Split-Path -Parent $MyInvocation.MyCommand.Path
$home_ = $HOME -replace '\\', '/'

function Say($t)  { Write-Host $t }
function Warn($t) { Write-Host $t -ForegroundColor Yellow }

$targets = @(
    @{ src = "config\conventions.md";     dst = "$HOME\.config\aider\conventions.md" },
    @{ src = "config\rules.md";           dst = "$HOME\.config\aider\rules.md" },
    @{ src = "config\model-settings.yml"; dst = "$HOME\.config\aider\model-settings.yml" },
    @{ src = "config\context-budget.json";dst = "$HOME\.config\aider\context-budget.json" },
    @{ src = "MANUAL.md";                 dst = "$HOME\.config\aider\MANUAL.md" },
    @{ src = "config\aider.conf.yml";     dst = "$HOME\.aider.conf.yml" },
    @{ src = "bin\aider-plan.ps1";        dst = "$HOME\.local\bin\aider-plan.ps1" },
    @{ src = "bin\aider-rules-sync.py";   dst = "$HOME\.local\bin\aider-rules-sync.py" }
)

Say "Installing for: $HOME"
if ($DryRun) { Warn "DRY RUN - nothing will be written" }

foreach ($t in $targets) {
    $src = Join-Path $kit $t.src
    $dst = $t.dst
    if (-not (Test-Path -LiteralPath $src)) {
        Write-Host "MISSING from the kit: $($t.src)" -ForegroundColor Red
        exit 2
    }
    if ((Test-Path -LiteralPath $dst) -and -not $Force) {
        Warn "  kept (already exists): $dst"
        continue
    }
    $text = (Get-Content -LiteralPath $src -Raw) -replace '\{\{HOME\}\}', $home_
    if ($DryRun) { Say "  would write: $dst"; continue }
    $dir = Split-Path -Parent $dst
    if (-not (Test-Path -LiteralPath $dir)) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
    Set-Content -LiteralPath $dst -Value $text -Encoding UTF8 -NoNewline
    Say "  wrote: $dst"
}

Say ""
Say "Next:"
Say "  1. uv tool install --force --python python3.12 --with pip aider-chat@latest"
Say "  2. ollama pull qwen3.8:latest"
Say "  3. ollama pull gemma4:31b-maxctx"
Say "  4. read MANUAL.md section 2 and set the OLLAMA_* variables"
Say "  5. in a project:  .\install-hooks.ps1  then  aider-plan.ps1 -DryRun ..."
Say ""
Say "~/.local/bin must be on PATH."
""", encoding="utf-8")

# --- per-project hook installer ---------------------------------------------
(OUT / "install-hooks.ps1").write_text(r"""<#
.SYNOPSIS
  Install the branch-protection hooks into ONE repository.

.DESCRIPTION
  Writes pre-commit and pre-push into this repository's .git/hooks. They refuse
  a commit or a push on main and master, so aider's automatic commits can only
  land on a working branch.

  Per repository on purpose. A global core.hooksPath would apply to every
  repository on the machine, and git honours it when resolving --git-path,
  which makes a hook that delegates to a repository's own hook re-run itself
  until the commit is killed.

.EXAMPLE
  .\install-hooks.ps1 -Path C:\work\my-project
#>
[CmdletBinding()]
param(
    [string]$Path = ".",
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"
$kit  = Split-Path -Parent $MyInvocation.MyCommand.Path
$proj = (Resolve-Path -LiteralPath $Path).Path

Push-Location $proj
try {
    # The redirection happens INSIDE cmd, not in PowerShell. Measured
    # 2026-09-03: `2>$null` does not stop PowerShell 5.1 wrapping a native
    # command's stderr in an ErrorRecord, and with $ErrorActionPreference =
    # "Stop" that terminates the script - so pointing this at a directory which
    # is not a repository printed a NativeCommandError stack trace and the
    # refusal three lines below was never reached. It is the same defect the
    # manual records for the test command, one script further along.
    $gitDir = (& cmd /c "git rev-parse --git-dir 2>NUL")
    if ($LASTEXITCODE -ne 0) {
        Write-Host "REFUSED: $proj is not a git repository." -ForegroundColor Red
        exit 2
    }
} finally { Pop-Location }

$hooksDir = Join-Path $proj ($gitDir + "\hooks")
foreach ($name in @("pre-commit", "pre-push")) {
    $src = Join-Path $kit "git-hooks\$name"
    $dst = Join-Path $hooksDir $name
    if ($DryRun) { Write-Host "  would write: $dst"; continue }
    if (-not (Test-Path -LiteralPath $hooksDir)) { New-Item -ItemType Directory -Force -Path $hooksDir | Out-Null }
    Copy-Item -LiteralPath $src -Destination $dst -Force
    Write-Host "  installed: $dst"
}

if (-not $DryRun) {
    Write-Host ""
    Write-Host "Check them, in both directions:" -ForegroundColor Cyan
    Write-Host "  git switch main   ; git commit --allow-empty -m x   -> must be REFUSED"
    Write-Host "  git switch -c work; git commit --allow-empty -m x   -> must SUCCEED"
}
""", encoding="utf-8")

# --- project template -------------------------------------------------------
tpl = OUT / "project-template/docs/superpowers/plans"
tpl.mkdir(parents=True, exist_ok=True)

(tpl / "spec.md").write_text("""# Spec

What is being built, and why. Prose, not a list. **Ceiling {{CEILING_SPEC}}
tokens**, substituted by new-project.ps1 from the context-budget.json the
driver actually enforces, so this figure cannot disagree with it.

This file is the anchor. Every plan is checked against it, including by the
audit pass, which is asked whether anything the spec requires was never
delivered by any plan.

Replace this text.
""", encoding="utf-8")

(tpl / "plan1.md").write_text("""# Plan 1

One stage. A numbered list of steps. **Ceiling {{CEILING_PLAN}} tokens**, and
the same ceiling applies to every plan file, not to the set of them.

**Every step names the file it touches.** A step reading "add a subtract
function", with no filename, made the model create a second module instead of
editing the one that already existed.

1. Add subtract(a, b) to calc.py returning a - b.
2. Add its test to Test/test_calc.py, including the wrong-type case.

Replace these steps.
""", encoding="utf-8")

(tpl / "progress.md").write_text("""# Progress

**Ceiling {{CEILING_PROGRESS}} tokens.** It is a ledger, not a report: one
`## <filename>` section per plan and one line per step. The harness re-reads
it on every call, so prose here is paid for on every call of every plan.

One `## <filename>` section per plan. The heading must match the plan's
filename exactly: the harness reads that section to decide whether the plan is
finished.

Three marks, and only three:

- `- [ ]` not done
- `- [x]` done, with a short result after the text
- `- [!]` blocked, with one line saying what blocked it

The harness adds its own lines here: `- [x] tests pass` after the suite runs,
and `- [ ] audit: ...` for anything the audit says must be fixed before the
next plan starts.

## plan1.md
- [ ] add subtract to calc.py, with its test
""", encoding="utf-8")

# --- README -----------------------------------------------------------------
(OUT / "README.md").write_text("""# Aider nightly coding kit - v0.1

**Goal.** Orient you: what this kit is, how to get it running, and where every
file lives.

**Contents.** A short overview and the file inventory. The procedure is
`MANUAL.md`, step by step; the Ollama settings for your hardware are
`CONFIG_OLLAMA.md`; the coding rules the model obeys are `config/rules.md`. This
file points at those rather than repeating them.

Two local models, one driver. One writes code and its tests, a different one
reviews at the end of every plan and can never edit. Nothing leaves the machine.

## Start here

Read **MANUAL.md**. It is eight numbered steps from a bare machine to a project
that codes overnight.

| Step | What it does |
|---|---|
| 1 | install uv, aider and Ollama, and set the daemon variables |
| 2 | unblock the files and run `setup.ps1` |
| 3 | test the computer: prove the tools offline, then measure the hardware |
| 4 | tune Ollama and build the tag you actually run |
| 5 | create a project |
| 6 | write the three inputs, or take the worked example |
| 7 | dry run, then run the night |
| 8 | read the result |

Steps 1 and 2 are roughly this, but read them rather than pasting: each carries
a reason and a check.

```powershell
winget install --id=astral-sh.uv -e
uv tool install --force --python python3.12 --with pip aider-chat@latest
cd "$HOME\\aider-kit"
Get-ChildItem -Recurse -Include *.ps1,*.bat | Unblock-File
.\\setup.ps1 -DryRun
.\\setup.ps1
```

## Before you trust a number

Every measured figure in this kit was taken on one machine, and yours is not
that machine. `ollama-tune.bat` measures yours, and `CONFIG_OLLAMA.md` says what
the numbers mean.

Two readings mislead, and both are worth knowing before you debug anything:

- `ollama ps` reports a **memory** ratio, not a layer ratio. For the real split
  read `offloaded N/M layers` from the Ollama server log.
- Task Manager's GPU graphs default to the 3D engine. CUDA work appears under
  `Cuda` or `Compute_0`, so a busy card can read 0 percent. Use
  `nvidia-smi --query-gpu=utilization.gpu --format=csv`.

## Proving it works, before spending a night on it

Each of these prints its own count of checks and whether they passed. Read that
count rather than a number quoted here.

```powershell
python bin\\Test\\test_aider_gpu_probe.py        # the GPU probe
python bin\\Test\\test_aider_thread_probe.py     # the measurement probe
python bin\\Test\\test_aider_ollama_config.py    # the configurator
bin\\Test\\verify-aider-plan.ps1                 # the driver
```

All four are offline: no model is loaded, no network is used, and no Ollama
installation is needed.

## What is in here

| Path | What it is |
|---|---|
| `MANUAL.md` | the procedure, in eight steps. Read this first |
| `CONFIG_OLLAMA.md` | how to configure Ollama for YOUR machine, and what each measurement means |
| `setup.ps1` | installs the kit into your home directory. Adds, never silently replaces |
| `new-project.ps1` | scaffolds one project: git, hooks, plans skeleton, tests, its own venv |
| `install-hooks.ps1` | the branch-protection hooks alone, for a repository you already have |
| `ollama-tune.bat`, `ollama-tune.ps1` | measures this machine: bandwidth, threads, GPU offload, context cost |
| `config/aider.conf.yml` | the one file aider finds by name |
| `config/model-settings.yml` | per-model settings. The `num_ctx` here overrides a tuned tag's own Modelfile |
| `config/conventions.md` | the working protocol the model reads on every call |
| `config/rules.md` | the coding rules, generated. Do not edit |
| `config/rules-local/` | where a rule of your own goes, as a bolded `**Rn - statement.**` |
| `config/context-budget.json` | every token ceiling, each with a comment saying where its number came from |
| `config/skills.json` | which skill reaches the model at which stage, and its ceiling |
| `config/skills/` | the skill files themselves, copied so no upstream update can change them mid-project |
| `examples/robot-planning-prompt.md` | the prompt that produced the worked example, and why it is shaped that way |
| `examples/robot-planner-plans/` | the nine documents it produced: a seven-plan robot simulator that fits the ceilings |
| `bin/aider-night.ps1`, `bin/aider-night.bat` | the night entry point: one command, skills wired |
| `bin/aider-plan.ps1` | the driver: plans, tests, audit, archiving |
| `bin/aider-plan-core.ps1` | the driver's pure half. It must sit beside the driver, which refuses without it |
| `bin/aider-rules-sync.py` | regenerates `rules.md` from a rules directory |
| `bin/aider-gpu-probe.py`, `.json` | measures which model and context actually puts layers on YOUR card |
| `bin/aider-thread-probe.py`, `.json` | measures what bounds a model here: memory bandwidth, threads, offload, window cost |
| `bin/aider-ollama-config.py` | turns the budget plus a measurement into a tuned tag, and reads the tag back |
| `bin/Test/` | the offline suites for all of the above |
| `git-hooks/` | per-repository branch protection |
| `project-template/` | the three documents a project starts from |

## What a skill does here, and what it does not

A skill is a Markdown file handed to the model as read-only context at one stage
of the loop. It is not code, it is not executed, and it cannot edit anything.
`config/skills.json` decides which file reaches the model when. Some are
third-party: `config/skills/LICENSE-superpowers.txt` records their licence and
states which were modified and how.

## What is proven, and what is not

The offline suites above prove the tools. What they do not prove is a night: that
takes hours of real model time on real hardware, and the only way to know your
machine handles it is to run one. Start with the worked example in `examples/`,
which is known to fit the ceilings.
""", encoding="utf-8")

# What this step adds to the kit that build_kit.py never wrote, and so never
# declared. The verifier compares the declaration against the assembled tree,
# so a file added here and left undeclared reads exactly like a leak.
kit_manifest.declare(OUT, (
    "git-hooks/pre-commit",
    "git-hooks/pre-push",
    "setup.ps1",
    "install-hooks.ps1",
    "project-template/docs/superpowers/plans/spec.md",
    "project-template/docs/superpowers/plans/plan1.md",
    "project-template/docs/superpowers/plans/progress.md",
    "README.md",
))

print("kit finished")
