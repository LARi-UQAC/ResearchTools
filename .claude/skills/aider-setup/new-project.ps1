<#
.SYNOPSIS
  Create one isolated project directory, ready for the nightly driver.

.DESCRIPTION
  Creates the directory, initialises a git repository on a working branch,
  installs the two branch-protection hooks, writes the docs/superpowers/plans
  skeleton with its three template files, creates tests/, and writes a
  .gitignore, and creates the project's own Python virtual environment. That
  environment is the FIRST thing a project needs, so it is made by default and a
  failure to make it stops the scaffolder rather than warning.

  It REFUSES rather than writing into a directory that already exists: a
  scaffolder that overwrites is a scaffolder nobody can run twice safely.

.PARAMETER Name
  The project's directory name.

.PARAMETER Root
  Where the project directory is created. Required, so no location is assumed.

.PARAMETER Branch
  The working branch. Defaults to "work". Never main or master - the hooks
  refuse commits there, which is the point.

.PARAMETER NoVenv
  Do NOT create .venv. The environment then becomes yours to provide, and the
  test command must name its interpreter explicitly.

.PARAMETER Python
  The interpreter that seeds .venv. Left unset, uv or python chooses, and the
  choice is printed. On a machine with several profiles that choice can land on
  another account's installation, so name it here when it matters.

.PARAMETER DryRun
  Report every path it would create and create nothing.

.EXAMPLE
  .\new-project.ps1 -Name my-project -Root C:\work -DryRun
  .\new-project.ps1 -Name my-project -Root C:\work
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Name,
    [Parameter(Mandatory = $true)][string]$Root,
    [string]$Branch = "work",
    [switch]$NoVenv,
    [string]$Python = "",
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"
$kit = Split-Path -Parent $MyInvocation.MyCommand.Path

function Say($t)  { Write-Host $t }
function Warn($t) { Write-Host $t -ForegroundColor Yellow }
function Fail($lines) { foreach ($l in $lines) { Write-Host $l -ForegroundColor Red } ; exit 2 }

if ($Name -match '[\\/:*?"<>|]') { Fail @("REFUSED: '$Name' is not a usable directory name.") }
if ($Branch -eq "main" -or $Branch -eq "master") {
    Fail @("REFUSED: '$Branch' is a protected branch.",
           "  The hooks refuse every commit there, so a project started on it could never commit.")
}
if (-not (Test-Path -LiteralPath $Root)) {
    Fail @("REFUSED: root directory does not exist: $Root",
           "  Create it yourself, so no directory is invented on your disk.")
}

$proj = Join-Path (Resolve-Path -LiteralPath $Root).Path $Name
if (Test-Path -LiteralPath $proj) {
    Fail @("REFUSED: $proj already exists.",
           "  Use install-hooks.ps1 on it instead, or choose another name.")
}

Say "Project: $proj"
if ($DryRun) { Warn "DRY RUN - nothing will be created" }

$dirs = @(
    $proj,
    (Join-Path $proj "tests"),
    (Join-Path $proj "docs\superpowers\plans"),
    (Join-Path $proj "docs\superpowers\plans\todo")
)
foreach ($d in $dirs) {
    if ($DryRun) { Say "  would create: $d"; continue }
    New-Item -ItemType Directory -Force -Path $d | Out-Null
    Say "  created: $d"
}

# --- git --------------------------------------------------------------------
if (-not $DryRun) {
    Push-Location $proj
    try {
        & git init -q -b $Branch . 2>&1 | Out-Null
        if ($LASTEXITCODE -ne 0) { Fail @("REFUSED: git init failed in $proj") }
        Say "  git repository on branch '$Branch'"
    } finally { Pop-Location }
} else {
    Say "  would run: git init -b $Branch"
}

# --- hooks ------------------------------------------------------------------
$hooksDir = Join-Path $proj ".git\hooks"
foreach ($h in @("pre-commit", "pre-push")) {
    $src = Join-Path $kit "git-hooks\$h"
    $dst = Join-Path $hooksDir $h
    if (-not (Test-Path -LiteralPath $src)) { Fail @("MISSING from the kit: git-hooks\$h") }
    if ($DryRun) { Say "  would install hook: $dst"; continue }
    Copy-Item -LiteralPath $src -Destination $dst -Force
    Say "  installed hook: $dst"
}

# --- plan skeleton ----------------------------------------------------------
$tplRoot = Join-Path $kit "project-template\docs\superpowers\plans"
# The ceilings are SUBSTITUTED into the templates, never written in them. A
# figure typed into a template drifts from the one the driver enforces, and it
# had: the spec template said 8000 tokens against a real ceiling of 4000, and
# the plan and progress templates said nothing at all. So the one place a person
# looks while WRITING a spec was silent twice and wrong by double once.
#
# The INSTALLED budget file is read, not the kit's copy, because the installed
# one is what aider-plan.ps1 reads. Reading the kit's would put a number in the
# template that the driver does not enforce, which is the same defect one step
# further along.
$budgetFile = Join-Path $HOME ".config\aider\context-budget.json"
if (-not (Test-Path -LiteralPath $budgetFile)) {
    Fail @("MISSING: $budgetFile",
           "  Run setup.ps1 first. The plan templates carry the token ceilings the",
           "  driver enforces, and they are read from that file rather than typed in.")
}
try   { $budget = Get-Content -LiteralPath $budgetFile -Raw -Encoding UTF8 | ConvertFrom-Json }
catch { Fail @("$budgetFile does not parse: $($_.Exception.Message)") }

$ceilings = @{}
foreach ($pair in @(@("CEILING_SPEC", "spec.md"),
                    @("CEILING_PLAN", "plan.md"),
                    @("CEILING_PROGRESS", "progress.md"))) {
    # Named rather than defaulted: a missing ceiling means the budget file and
    # the templates disagree about what exists, and a number guessed here would
    # be indistinguishable from a measured one.
    $value = $budget.ceilings.$($pair[1])
    if ($null -eq $value) {
        Fail @("$budgetFile has no ceilings.$($pair[1]), so the template cannot state it.")
    }
    $ceilings[$pair[0]] = [string]$value
}

foreach ($f in @("spec.md", "plan1.md", "progress.md")) {
    $src = Join-Path $tplRoot $f
    $dst = Join-Path $proj "docs\superpowers\plans\$f"
    if (-not (Test-Path -LiteralPath $src)) { Fail @("MISSING from the kit: project-template\...\$f") }
    if ($DryRun) { Say "  would write: $dst"; continue }
    $body = Get-Content -LiteralPath $src -Raw -Encoding UTF8
    foreach ($key in $ceilings.Keys) { $body = $body.Replace("{{$key}}", $ceilings[$key]) }
    # A surviving placeholder would ship a project whose template tells the
    # writer to keep under "{{CEILING_SPEC}} tokens", so it is a refusal.
    if ($body -match "\{\{CEILING_") {
        Fail @("a {{CEILING_...}} placeholder survived in ${f}: the template names one this script does not fill.")
    }
    [System.IO.File]::WriteAllText($dst, $body, (New-Object System.Text.UTF8Encoding($false)))
    Say "  wrote: $dst"
}
Say ("  ceilings stated in them: spec {0}, plan {1}, progress {2} tokens" -f `
     $ceilings["CEILING_SPEC"], $ceilings["CEILING_PLAN"], $ceilings["CEILING_PROGRESS"])

# --- .gitignore -------------------------------------------------------------
$ignore = @(
    ".venv/",
    "__pycache__/",
    "*.pyc",
    ".aider*",
    "docs/superpowers/plans/.logs/"
) -join "`n"
$ignorePath = Join-Path $proj ".gitignore"
if ($DryRun) { Say "  would write: $ignorePath" }
else {
    Set-Content -LiteralPath $ignorePath -Value $ignore -Encoding UTF8
    Say "  wrote: $ignorePath"
}

# --- the project's own Python environment -----------------------------------
# Created BY DEFAULT, and its absence is a refusal rather than a warning.
#
# It used to be opt-in, behind -Venv. That was wrong in a way that only shows up
# later: without the switch no environment was made, and the very next thing this
# script printed was a test command starting `.\.venv\Scripts\python.exe`, which
# then does not exist. The run either refuses at startup or, worse, someone edits
# the command to a bare `python` and the tests silently run against whatever
# interpreter PATH happens to resolve - on a shared machine, that can be another
# account's install entirely. Measured 2026-09-03 on the reference machine, where
# `python` resolved into a different user profile.
#
# A project's tests must run in the project's own environment. -NoVenv exists for
# the person who manages their own, and it says so out loud.
if (-not $NoVenv) {
    if ($DryRun) {
        Say "  would create: $proj\.venv"
        if ($Python -ne "") { Say "               from $Python" }
    }
    else {
        Push-Location $proj
        try {
            # Every redirection happens INSIDE cmd. PowerShell 5.1 wraps a native
            # command's stderr in an ErrorRecord, and with $ErrorActionPreference
            # = "Stop" that terminates the script - `uv venv` writes its progress
            # to stderr, so the environment was created and the scaffolder died
            # anyway. Measured 2026-09-03; it is the same trap as the test command
            # and install-hooks.ps1, one script further along.
            $made = $false
            $pyArg = ""
            if ($Python -ne "") {
                if (-not (Test-Path -LiteralPath $Python)) {
                    Write-Host "REFUSED: -Python names no file: $Python" -ForegroundColor Red
                    exit 2
                }
                $pyArg = " --python `"$Python`""
            }
            else {
                # Your own interpreter before anyone else's. A virtual environment
                # inherits its base Python, and left to itself uv takes the first
                # one it finds - measured 2026-09-03 on a machine with seven user
                # profiles, where that was an administrator account's install. The
                # environment still works; it just depends on a directory this
                # user does not own and may lose access to, and the failure would
                # arrive weeks later looking like a broken project.
                #
                # So a python.exe under this user's own profile wins when there is
                # one. When there is not, uv chooses and the choice is printed.
                # The trailing separator is load-bearing. Measured 2026-09-03:
                # without it, "C:\Users\<name>99\..." passes a StartsWith test
                # against "C:\Users\<name>" because one account name is a prefix
                # of the other, and the administrator's interpreter was selected
                # by the very check written to avoid it. A prefix test is not a
                # containment test; compare on the directory boundary.
                $homeBoundary = $HOME.TrimEnd('\') + '\'
                $ownPythons = @(Get-Command python -All -ErrorAction SilentlyContinue |
                                Where-Object {
                                    $_.Source -and
                                    $_.Source.StartsWith($homeBoundary, [StringComparison]::OrdinalIgnoreCase) -and
                                    # The Microsoft Store alias is a stub that opens
                                    # the Store rather than running Python.
                                    $_.Source -notmatch '\\WindowsApps\\'
                                })
                if ($ownPythons.Count -gt 0) {
                    $pyArg = " --python `"$($ownPythons[0].Source)`""
                }
            }
            if (Get-Command uv -ErrorAction SilentlyContinue) {
                & cmd /c "uv venv .venv$pyArg >NUL 2>&1"
                if ($LASTEXITCODE -eq 0) { $made = $true; Say "  created .venv with uv" }
            }
            if (-not $made) {
                $exe = if ($Python -ne "") { $Python } else { "python" }
                & cmd /c "`"$exe`" -m venv .venv >NUL 2>&1"
                if ($LASTEXITCODE -eq 0) { $made = $true; Say "  created .venv with $exe -m venv" }
            }
            if (-not $made) {
                Write-Host "REFUSED: could not create .venv." -ForegroundColor Red
                Write-Host "  The project's tests must run in the project's own environment."
                Write-Host "  Install uv, or a Python with the venv module, then run this again,"
                Write-Host "  or name the interpreter with -Python <path to python.exe>."
                Write-Host "  Pass -NoVenv only if you deliberately manage the environment yourself."
                exit 2
            }

            # WHICH interpreter seeded it, said out loud. A virtual environment
            # inherits its base Python, and on a shared machine the one PATH
            # resolves can belong to another account: measured 2026-09-03, `uv`
            # seeded a project from an administrator profile's install without
            # anything on screen saying so. Reported rather than guessed, so the
            # choice is yours to accept or to re-make with -Python.
            $cfg = Join-Path $proj ".venv\pyvenv.cfg"
            if (Test-Path -LiteralPath $cfg) {
                $base = (Get-Content -LiteralPath $cfg | Where-Object { $_ -match '^\s*(base-executable|home)\s*=' } |
                         Select-Object -First 1)
                if ($base) { Say "  seeded from: $(($base -split '=',2)[1].Trim())" }
            }
        } finally { Pop-Location }
    }
} else {
    Warn "  no .venv: -NoVenv was passed, so the environment is yours to provide"
}

if ($DryRun) { Say ""; Say "Nothing was created."; exit 0 }

Say ""
Say "Next:" -ForegroundColor Cyan
Say "  1. Write docs\superpowers\plans\spec.md and plan1.md. Every plan step names its file."
Say "  2. List each plan in progress.md under a '## plan<N>.md' heading."
Say "  3. Dry-run the driver:"
Say ""
Say "     cd `"$proj`""
Say "     aider-plan.ps1 -DryRun ``"
Say "       -Config      `"`$HOME\.aider.conf.yml`" ``"
Say "       -BudgetFile  `"`$HOME\.config\aider\context-budget.json`" ``"
Say "       -TestCommand '.\.venv\Scripts\python.exe -m unittest discover -s tests -p `"test_*.py`"'"
Say ""
Say "  The hooks refuse commits on main and master. Check both directions:"
Say "     git commit --allow-empty -m x        # on '$Branch': must SUCCEED"
