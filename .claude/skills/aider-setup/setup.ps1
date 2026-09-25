<#
.SYNOPSIS
  Install the aider kit for the current user.

.DESCRIPTION
  Copies the kit's configuration into <home>/.config/aider/, writes
  <home>/.aider.conf.yml (the one file aider finds by name), and puts the two
  scripts in <home>/.local/bin so they can be called by name.

  Every {{HOME}} placeholder in the kit's files is replaced with the target
  home directory, so nothing installed names anyone else's machine.

  It ADDS and never silently replaces: a file that already exists is kept, and
  reported as kept, unless -Force is passed. -DryRun reports every path it
  would write and writes nothing.

.PARAMETER HomeDir
  Where to install. Defaults to your own home directory. It exists so this
  script can be verified against a scratch directory rather than only against
  the real home - a check that can only be run for real is not a check.

.PARAMETER Force
  Overwrite files that already exist.

.PARAMETER DryRun
  Report everything, write nothing.

.EXAMPLE
  .\setup.ps1 -DryRun
  .\setup.ps1
  .\setup.ps1 -HomeDir C:\temp\probe -DryRun
#>
[CmdletBinding()]
param(
    [string]$HomeDir = $HOME,
    [switch]$DryRun,
    [switch]$Force,
    # Do NOT install aider into its own environment. For someone who manages
    # their own installation; the default is to install it, because a setup that
    # only copies files reports success for a machine that cannot run.
    [switch]$NoInstall
)

$ErrorActionPreference = "Stop"
$kit = Split-Path -Parent $MyInvocation.MyCommand.Path

function Say($t)  { Write-Host $t }
function Warn($t) { Write-Host $t -ForegroundColor Yellow }
function Good($t) { Write-Host $t -ForegroundColor Green }

if (-not (Test-Path -LiteralPath $HomeDir)) {
    if ($DryRun) { Warn "target home does not exist yet: $HomeDir" }
    else { New-Item -ItemType Directory -Force -Path $HomeDir | Out-Null }
}
$target = (Resolve-Path -LiteralPath $HomeDir -ErrorAction SilentlyContinue)
if ($target) { $HomeDir = $target.Path }
$homeFwd = $HomeDir -replace '\\', '/'

$binDir = Join-Path $HomeDir ".local\bin"
$cfgDir = Join-Path $HomeDir ".config\aider"

$targets = @(
    @{ src = "config\conventions.md";      dst = (Join-Path $cfgDir "conventions.md") },
    @{ src = "config\rules.md";            dst = (Join-Path $cfgDir "rules.md") },
    @{ src = "config\model-settings.yml";  dst = (Join-Path $cfgDir "model-settings.yml") },
    @{ src = "config\context-budget.json"; dst = (Join-Path $cfgDir "context-budget.json") },
    @{ src = "MANUAL.md";                  dst = (Join-Path $cfgDir "MANUAL.md") },
    @{ src = "config\aider.conf.yml";      dst = (Join-Path $HomeDir ".aider.conf.yml") },
    @{ src = "bin\aider-plan.ps1";         dst = (Join-Path $binDir "aider-plan.ps1") },
    # The driver's pure half. Installed as a peer of the driver because the
    # driver resolves it through $PSScriptRoot and exits 2 by name when it is not
    # beside it: install one without the other and every run refuses.
    @{ src = "bin\aider-plan-core.ps1";    dst = (Join-Path $binDir "aider-plan-core.ps1") },
    @{ src = "bin\aider-rules-sync.py";    dst = (Join-Path $binDir "aider-rules-sync.py") },
    # The GPU probe and its configuration. The manual tells a student to
    # re-measure the load time, the resident size and the CPU/GPU split on their
    # own card; until 2026-09-03 it named no tool for doing it. Every number the
    # probe uses lives in the .json beside it, so the two travel together or the
    # probe refuses by key name.
    @{ src = "bin\aider-gpu-probe.py";     dst = (Join-Path $binDir "aider-gpu-probe.py") },
    @{ src = "bin\aider-gpu-probe.json";   dst = (Join-Path $binDir "aider-gpu-probe.json") },
    # The two test suites. A student who cannot verify their own installation has
    # to trust it, and the first thing they would find out otherwise is a night
    # spent on a driver that was never going to run.
    @{ src = "bin\Test\test_aider_gpu_probe.py";  dst = (Join-Path $binDir "Test\test_aider_gpu_probe.py") },
    @{ src = "bin\Test\verify-aider-plan.ps1";    dst = (Join-Path $binDir "Test\verify-aider-plan.ps1") },
    # The night entry point: one command, skills already wired. The .bat exists
    # so that nothing has to be known about execution policy.
    @{ src = "bin\aider-night.ps1";        dst = (Join-Path $binDir "aider-night.ps1") },
    @{ src = "bin\aider-night.bat";        dst = (Join-Path $binDir "aider-night.bat") },
    @{ src = "config\skills.json";         dst = (Join-Path $cfgDir "skills.json") },
    # The tuning chain, added 2026-09-05. It shipped in the archive before this
    # and was never installed, so README.md told a reader to run ollama-tune.bat
    # and read CONFIG_OLLAMA.md while neither existed anywhere the installed kit
    # could see - they lived only in the extracted folder, and a student who
    # tidied that away lost the whole tuning workflow.
    @{ src = "CONFIG_OLLAMA.md";           dst = (Join-Path $cfgDir "CONFIG_OLLAMA.md") },
    @{ src = "ollama-tune.ps1";            dst = (Join-Path $binDir "ollama-tune.ps1") },
    @{ src = "ollama-tune.bat";            dst = (Join-Path $binDir "ollama-tune.bat") },
    @{ src = "bin\aider-thread-probe.py";   dst = (Join-Path $binDir "aider-thread-probe.py") },
    @{ src = "bin\aider-thread-probe.json"; dst = (Join-Path $binDir "aider-thread-probe.json") },
    @{ src = "bin\aider-ollama-config.py";  dst = (Join-Path $binDir "aider-ollama-config.py") },
    @{ src = "bin\Test\test_aider_thread_probe.py";  dst = (Join-Path $binDir "Test\test_aider_thread_probe.py") },
    @{ src = "bin\Test\test_aider_ollama_config.py"; dst = (Join-Path $binDir "Test\test_aider_ollama_config.py") },
    # The detached launcher. Step 7 of the manual names it as THE way to
    # run a night, and it is what carried the run that survived two
    # session restarts. Shipped at bin/ rather than bin/Test/ because it
    # is a run helper and not a test.
    @{ src = "bin\run-detached.ps1";       dst = (Join-Path $binDir "run-detached.ps1") },
    # The ten defects of 2026-09-05/06 and the checker for them. Seven were
    # invisible to inspection and visible only to a run.
    @{ src = "bin\aider-defect-check.py";  dst = (Join-Path $binDir "aider-defect-check.py") },
    @{ src = "bin\aider-defects.json";     dst = (Join-Path $binDir "aider-defects.json") },
    @{ src = "bin\Test\verify-audit-prompt.ps1"; dst = (Join-Path $binDir "Test\verify-audit-prompt.ps1") }
)

# The skill bundles are a TREE, not a file, so they are copied after the flat
# list rather than enumerated in it: a bundle that gains a page must not need
# this installer edited, or the page silently stops being installed and the
# model reads an instruction naming a document it does not have.
# Whole directories, copied file by file rather than enumerated: a bundle that
# gains a page, or a rules directory that gains a rule, must not need this
# installer edited. rules-local is here for the same reason the skills are: the
# generated rules.md tells the reader to edit the source and re-run the sync, and
# on a student machine this directory IS that source.
$dirTargets = @(
    @{ src = (Join-Path $kit "config\skills");      dst = (Join-Path $cfgDir "skills");      label = "config\skills" },
    @{ src = (Join-Path $kit "config\rules-local"); dst = (Join-Path $cfgDir "rules-local"); label = "config\rules-local" },
    # The worked example: the planning prompt AND the plan documents it produced.
    # A tree rather than a file list, so an example that gains a plan does not
    # need this installer edited. Installed rather than left in the archive
    # because the hardest step for a student is writing plans that fit the token
    # ceilings, and a set that does is worth having on disk to copy from.
    @{ src = (Join-Path $kit "examples");           dst = (Join-Path $cfgDir "examples");    label = "examples" }
)

Say "Installing into: $HomeDir"
if ($DryRun) { Warn "DRY RUN - nothing will be written" }
Say ""

$written = 0
$kept    = 0
foreach ($t in $targets) {
    $src = Join-Path $kit $t.src
    $dst = $t.dst
    if (-not (Test-Path -LiteralPath $src)) {
        Write-Host "MISSING from the kit: $($t.src)" -ForegroundColor Red
        exit 2
    }
    if ((Test-Path -LiteralPath $dst) -and -not $Force) {
        Warn "  kept (already exists): $dst"
        $kept++
        continue
    }
    if ($DryRun) { Say "  would write: $dst"; $written++; continue }
    $dir = Split-Path -Parent $dst
    if (-not (Test-Path -LiteralPath $dir)) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
    # Read AND write are explicit about encoding, and neither uses Set-Content.
    # Measured 2026-09-04 on the first scratch install anyone had ever done:
    # PowerShell 5.1's `-Encoding UTF8` writes a BYTE ORDER MARK, and aider's YAML
    # parser refuses the file it produces - "Couldn't parse config file: did not
    # find expected <document start>". Every student would have installed an
    # unusable ~/.aider.conf.yml, and no check caught it because the file is
    # perfectly valid until it is copied. The read side is the mirror defect:
    # Get-Content -Raw with no -Encoding reads a BOM-less UTF-8 file as cp1252,
    # which turns every accented character in MANUAL.md and rules.md to mojibake.
    $text = (Get-Content -LiteralPath $src -Raw -Encoding UTF8) -replace '\{\{HOME\}\}', $homeFwd
    [System.IO.File]::WriteAllText($dst, $text, (New-Object System.Text.UTF8Encoding($false)))
    Say "  wrote: $dst"
    $written++
}

foreach ($t in $dirTargets) {
    if (-not (Test-Path -LiteralPath $t.src)) {
        Write-Host "MISSING from the kit: $($t.label)" -ForegroundColor Red
        exit 2
    }
    foreach ($f in (Get-ChildItem -LiteralPath $t.src -Recurse -File)) {
        $rel = $f.FullName.Substring($t.src.Length).TrimStart('\')
        $dst = Join-Path $t.dst $rel
        if ((Test-Path -LiteralPath $dst) -and -not $Force) {
            Warn "  kept (already exists): $dst"
            $kept++
            continue
        }
        if ($DryRun) { Say "  would write: $dst"; $written++; continue }
        $dir = Split-Path -Parent $dst
        if (-not (Test-Path -LiteralPath $dir)) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
        # Read and written as UTF8 explicitly: these files carry em dashes and
        # check marks, and PowerShell 5.1's default encoding turns them into
        # mojibake that the model then reads as the instruction. The write goes
        # through .NET for the reason given above: Set-Content -Encoding UTF8
        # emits a BOM, and a BOM at the head of a skill file is one more character
        # the model reads as content.
        $text = (Get-Content -LiteralPath $f.FullName -Raw -Encoding UTF8) -replace '\{\{HOME\}\}', $homeFwd
        [System.IO.File]::WriteAllText($dst, $text, (New-Object System.Text.UTF8Encoding($false)))
        Say "  wrote: $dst"
        $written++
    }
}

Say ""
Say ("{0} file(s) written, {1} kept" -f $written, $kept)

# --- what the machine still needs -------------------------------------------
Say ""
Say "Checks:"

# Is the bin directory reachable by name? Reported rather than assumed: a
# script that is installed but not on PATH looks installed and is not callable.
$onPath = $false
foreach ($entry in ($env:PATH -split ';')) {
    if ($entry.Trim().TrimEnd('\') -ieq $binDir.TrimEnd('\')) { $onPath = $true; break }
}
if ($onPath) { Good "  PATH        contains $binDir" }
else {
    Warn "  PATH        does NOT contain $binDir"
    Warn "              aider-plan.ps1 will not be callable by name until it does."
    Warn "              Add it for your user, then open a NEW terminal:"
    Warn ("              [Environment]::SetEnvironmentVariable('PATH', " +
          "[Environment]::GetEnvironmentVariable('PATH','User') + ';' + '$binDir', 'User')")
}

foreach ($exe in @("aider", "ollama", "uv", "git", "python")) {
    $found = Get-Command $exe -ErrorAction SilentlyContinue
    if ($found) { Good ("  {0,-11} {1}" -f $exe, $found.Source) }
    else        { Warn ("  {0,-11} NOT FOUND on PATH" -f $exe) }
}

# --- aider's own isolated environment ---------------------------------------
# Installed HERE, not left as an instruction. `uv tool install` builds aider its
# own virtual environment, isolated from the system Python and from every
# project, which is the arrangement this kit assumes everywhere else. Leaving it
# as step 1 of a list meant a student could copy the files, see "17 file(s)
# written", and have nothing runnable - the setup reported success for a machine
# that could not start.
#
# Every redirection is INSIDE cmd: PowerShell 5.1 wraps a native command's stderr
# in an ErrorRecord and $ErrorActionPreference = "Stop" then kills the script.
# uv writes its progress to stderr, so without this the install would succeed and
# the installer would die on it. Measured 2026-09-03, three times in three
# different scripts of this kit.
Say ""
Say "Aider's environment:"

if ($NoInstall) {
    Warn "  skipped: -NoInstall was passed, so aider is yours to install"
} elseif ($DryRun) {
    Say "  would run: uv tool install --force --python python3.12 --with pip aider-chat@latest"
} elseif (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host "  REFUSED: uv is not on PATH, so aider cannot be installed into its" -ForegroundColor Red
    Write-Host "           own environment." -ForegroundColor Red
    Write-Host "           Install it from https://docs.astral.sh/uv/ and run setup again,"
    Write-Host "           or pass -NoInstall and install aider yourself."
    exit 2
} else {
    Say "  installing aider into its own environment (this takes a minute)..."
    & cmd /c "uv tool install --force --python python3.12 --with pip aider-chat@latest >NUL 2>&1"
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  REFUSED: uv tool install failed (exit $LASTEXITCODE)." -ForegroundColor Red
        Write-Host "           Run it yourself to see why:"
        Write-Host "           uv tool install --force --python python3.12 --with pip aider-chat@latest"
        exit 2
    }
    # The effect, not the exit code (R9): uv can return 0 having installed into a
    # location that is not on PATH, and an aider nobody can call is not installed.
    $aider = Get-Command aider -ErrorAction SilentlyContinue
    if ($aider) { Good "  aider       $($aider.Source)" }
    else {
        Warn "  aider installed, but not callable by name yet."
        Warn "              Open a NEW terminal, or add uv's tool directory to PATH:"
        Warn "              uv tool update-shell"
    }
}

Say ""
Say "Next:"
Say "  1. ollama pull qwen3.8:latest"
Say "  2. ollama pull gemma4:31b-maxctx"
Say "  3. set the OLLAMA_* variables - MANUAL.md section 2"
Say "  4. measure the machine, then TUNE - MANUAL.md step 4. NOT optional:"
Say ("     " + (Join-Path $binDir "ollama-tune.bat"))
Say ("     python " + (Join-Path $binDir "aider-ollama-config.py") + " --model <base> --report <report> --yes")
Say "     It builds the tuned tag and writes the two files that make the tuning"
Say "     take effect: model-settings.yml, and ~\.aider.model.metadata.json."
Say "     Without the second, aider asks Ollama for the window and is told the"
Say "     ARCHITECTURE maximum, so every budget is computed against a window"
Say "     several times larger than the one allocated. The driver refuses that"
Say "     state rather than running in it, so skipping this stops the first night."
Say "  5. create a project:  .\new-project.ps1 -Name <name> -Root <dir>"
Say "     It creates the project's own .venv for you; nothing to do by hand."
Say ""
Say "Prove the installation before spending a night on it:"
Say ("  powershell -NoProfile -File " + (Join-Path $binDir "Test\verify-aider-plan.ps1"))
Say "     the driver's own checks; it prints how many it ran. No model, no network, nothing written outside a"
Say "     temporary directory. It drives the real driver in dry-run mode, so it"
Say "     also proves aider itself starts."
Say ("  python " + (Join-Path $binDir "Test\test_aider_gpu_probe.py"))
Say "     the offline checks on the GPU probe. Then measure your own card:"
Say ("  python " + (Join-Path $binDir "aider-gpu-probe.py") + " --help")
