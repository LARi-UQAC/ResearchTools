#Requires -Version 5.1
<#
.SYNOPSIS
    Runs every offline Python test suite in ResearchTools and records a green stamp.

.DESCRIPTION
    The self-improvement loop needs one command that can answer "does everything still
    pass". This is it. It DISCOVERS suites rather than reading a list, so a test added
    next month is picked up with no list to update - which is what makes "every previous
    test still passes" true over time rather than only on the day it was written.

    SCOPE
      Python suites matching .claude\**\Test\test_*.py, and nothing else.
      scripts\audit\check-claude-template.ps1 is a PowerShell drift check, not a test,
      and lives outside .claude\. It is deliberately NOT part of this gate and must not
      be reported as a missing suite.

    THREE OUTCOMES, NOT TWO
      PASSED   ran, every assertion held.
      FAILED   ran, an assertion or an error. This is the only outcome that means red.
      NOT RUN  could not import a THIRD-PARTY dependency (pypdf, jinja2, python-pptx...).

    The third outcome exists because "all tests must pass" would otherwise let one
    uninstalled package block every future self-improvement, permanently. The distinction
    being drawn is between "this code is wrong" and "this machine cannot check that
    code", and only the first should stop a fix. A missing module that DOES resolve
    inside the repository is first-party, so it is a real defect and counts as FAILED -
    see Get-MissingModuleKind, which decides this by looking for the module in the repo
    rather than by consulting a hardcoded list of package names that would rot.

    GREEN STAMP
      On green (no FAILED) it writes .rt-green.json: timestamp, resolved interpreter,
      per-suite outcomes, and A HASH PER CODE FILE. On any FAILED it DELETES that file.
      install-junctions.ps1 -Sync reads the per-file hashes to decide, file by file,
      whether the content on disk is content the suite actually passed. Per-file rather
      than one hash for the repository: a single repo-wide hash would mean any edit in
      progress anywhere freezes all propagation, which with sixteen files modified today
      would be the normal state rather than the exception.

.EXAMPLE
    .\scripts\test\run-offline-tests.ps1
    .\scripts\test\run-offline-tests.ps1 -Quiet
    .\scripts\test\run-offline-tests.ps1 -Python "D:\tools\py311\python.exe"
    .\scripts\test\run-offline-tests.ps1 -AllowPathFallback

.PARAMETER Python
    An explicit interpreter. It must exist; a path that does not is a refusal.

.PARAMETER AllowPathFallback
    Accept the first python on PATH when .venv-skills is absent or empty. Without it
    the run REFUSES (R8) and names the rebuild command: measured 2026-10-16, a week
    passed unnoticed after .venv-skills was emptied because this runner used to fall
    through to PATH, which on that machine was another account's Python. The
    interpreter in use is always printed.
#>
param(
    [switch]$Quiet,
    [string]$Python = "",
    [switch]$AllowPathFallback
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepoRoot  = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$StampPath = Join-Path $RepoRoot ".rt-green.json"

function Write-Line([string]$text, [string]$colour = "Gray") {
    if (-not $Quiet) { Write-Host $text -ForegroundColor $colour }
}

# ── Interpreter ───────────────────────────────────────────────────────────────
# "The project Python" is ambiguous on a machine carrying several virtual
# environments, and a suite silently run under the wrong interpreter is worse than one
# not run at all. The decision lives in scripts\lib\rt-venv.ps1, shared with every
# other launcher (R18): it finds the MAIN clone's .venv-skills from a worktree with no
# link, and refuses instead of reaching for PATH unless -AllowPathFallback is given.
. (Join-Path $RepoRoot "scripts\lib\rt-venv.ps1")

# ── Missing-module classification ─────────────────────────────────────────────
# Returns "third-party" (-> NOT RUN) or "first-party" (-> FAILED), or $null when the
# output carries no ModuleNotFoundError at all.
#
# Deciding by searching the repository rather than by matching a list of known package
# names: a list would need editing every time a skill takes a new dependency, and the
# day it falls behind it silently reclassifies a real defect as an excused absence.
function Get-MissingModuleKind([string]$output) {
    $m = [regex]::Match($output, "ModuleNotFoundError: No module named '([^']+)'")
    if (-not $m.Success) { return $null }

    $top = ($m.Groups[1].Value -split '\.')[0]

    $asModule  = Join-Path $RepoRoot ".claude"
    $hitFile   = Get-ChildItem -Path $asModule -Recurse -File -Filter "$top.py" -ErrorAction SilentlyContinue | Select-Object -First 1
    $hitPkg    = Get-ChildItem -Path $asModule -Recurse -Directory -Filter $top -ErrorAction SilentlyContinue | Select-Object -First 1

    if ($null -ne $hitFile -or $null -ne $hitPkg) { return "first-party" }
    return "third-party"
}

# ── Code files whose content the stamp vouches for ────────────────────────────
# The selection lives in scripts\lib\rt-stamp.ps1, shared with the -Sync engine: it hashes
# the .py files AND the hook .json configurations that -Sync copies. It used to hash .py
# only, so every hook config read "changed since the last green run" and was held forever.
. (Join-Path $RepoRoot "scripts\lib\rt-stamp.ps1")
function Get-CodeFiles {
    Get-RtCodeFiles -RepoRoot $RepoRoot
}

# ── Run ───────────────────────────────────────────────────────────────────────

Write-Line ""
Write-Line "=== ResearchTools - offline test suite ===" "Cyan"

$resolved = Resolve-RtVenvPython -RepoRoot $RepoRoot -Python $Python -AllowPathFallback:$AllowPathFallback
# $suitePython, not $python: PowerShell variables are case-insensitive, so $python IS the
# [string]$Python parameter, which coerces a null result to "" and turns the refusal below
# into dead code (code-review finding, reproduced in PowerShell 5.1).
$suitePython = $resolved.Python
if ($null -eq $suitePython) {
    Write-Host ""
    foreach ($line in ($resolved.Message -split "`n")) { Write-Host "  $line" -ForegroundColor Red }
    Write-Host "  Cannot establish a green stamp; removing any stale one." -ForegroundColor Red
    if (Test-Path $StampPath) { Remove-Item $StampPath -Force }
    exit 1
}
if ($resolved.Source -eq "path-fallback") {
    foreach ($line in ($resolved.Message -split "`n")) { Write-Host "  $line" -ForegroundColor Yellow }
}
Write-Line "  Interpreter : $suitePython  ($($resolved.Source))"

$suites = @(Get-ChildItem -Path (Join-Path $RepoRoot ".claude") -Recurse -File -Filter "test_*.py" -ErrorAction SilentlyContinue |
          Where-Object { $_.DirectoryName -match '\\Test$' } |
          Sort-Object FullName)

Write-Line "  Suites      : $($suites.Count) discovered"
Write-Line ""

$results  = @()
$failed   = @()
$notRun   = @()
$passed   = 0
$started  = Get-Date

foreach ($suite in $suites) {
    $rel = $suite.FullName.Substring($RepoRoot.Length + 1)

    $outFile = [System.IO.Path]::GetTempFileName()
    $errFile = [System.IO.Path]::GetTempFileName()

    # Start-Process with file redirection rather than `2>&1`: in PowerShell 5.1,
    # redirecting a native executable's stderr inline wraps each line in an ErrorRecord
    # and sets $? to false even on a clean exit, which would misreport every suite.
    $proc = Start-Process -FilePath $suitePython -ArgumentList @("`"$($suite.FullName)`"") `
                          -WorkingDirectory $RepoRoot -NoNewWindow -Wait -PassThru `
                          -RedirectStandardOutput $outFile -RedirectStandardError $errFile

    $output = ""
    if (Test-Path $outFile) { $output += (Get-Content $outFile -Raw -ErrorAction SilentlyContinue) }
    if (Test-Path $errFile) { $output += (Get-Content $errFile -Raw -ErrorAction SilentlyContinue) }
    Remove-Item $outFile, $errFile -Force -ErrorAction SilentlyContinue

    if ($null -eq $output) { $output = "" }

    if ($proc.ExitCode -eq 0) {
        $results += [pscustomobject]@{ suite = $rel; outcome = "PASSED" }
        $passed++
        Write-Line "  [PASS]    $rel" "DarkGray"
    }
    else {
        $kind = Get-MissingModuleKind $output
        if ($kind -eq "third-party") {
            $mod = [regex]::Match($output, "ModuleNotFoundError: No module named '([^']+)'").Groups[1].Value
            $results += [pscustomobject]@{ suite = $rel; outcome = "NOT RUN"; missing = $mod }
            $notRun  += [pscustomobject]@{ suite = $rel; missing = $mod }
            Write-Line "  [NOT RUN] $rel  (missing '$mod')" "Yellow"
        }
        else {
            $firstProblem = ($output -split "`n" |
                Where-Object { $_ -match '^(FAIL|ERROR)[: ]|^\w*Error:|^AssertionError' } |
                Select-Object -First 1)
            if ($null -eq $firstProblem) { $firstProblem = "exit code $($proc.ExitCode)" }
            $results += [pscustomobject]@{ suite = $rel; outcome = "FAILED"; detail = $firstProblem.Trim() }
            $failed  += [pscustomobject]@{ suite = $rel; detail = $firstProblem.Trim(); output = $output }
            Write-Host "  [FAIL]    $rel" -ForegroundColor Red
        }
    }
}

$elapsed = [int]((Get-Date) - $started).TotalSeconds

# ── Verdict ───────────────────────────────────────────────────────────────────

Write-Line ""
Write-Host "  PASSED $passed   FAILED $($failed.Count)   NOT RUN $($notRun.Count)   ($elapsed s)" `
           -ForegroundColor $(if ($failed.Count -gt 0) { "Red" } else { "Green" })

if ($notRun.Count -gt 0) {
    Write-Line ""
    Write-Line "  Not run - install the package to include these in the gate:" "Yellow"
    $notRun | Group-Object missing | ForEach-Object {
        Write-Line "    pip install $($_.Name)    ($($_.Count) suite(s))" "Yellow"
    }
}

if ($failed.Count -gt 0) {
    Write-Host ""
    Write-Host "  FAILING SUITES:" -ForegroundColor Red
    foreach ($f in $failed) {
        Write-Host "    $($f.suite)" -ForegroundColor Red
        Write-Host "      $($f.detail)" -ForegroundColor DarkRed
    }
    if (Test-Path $StampPath) {
        Remove-Item $StampPath -Force
        Write-Host ""
        Write-Host "  .rt-green.json removed - the repository is not in a proven state." -ForegroundColor Red
    }
    Write-Host ""
    exit 1
}

# ── A PATH python cannot vouch for suites it could not run ───────────────────
# -AllowPathFallback is an informed choice, but the stamp gates what install-junctions.ps1
# -Sync copies into ~/.claude. NOT RUN does not fail a run, so a PATH python missing the
# repository's packages would otherwise write a green stamp from a partial run.
if (-not (Test-RtStampAllowed -InterpreterSource $resolved.Source -NotRunCount $notRun.Count)) {
    if (Test-Path $StampPath) { Remove-Item $StampPath -Force }
    Write-Host ""
    Write-Host "  No green stamp: $($notRun.Count) suite(s) were NOT RUN under a python taken from PATH." -ForegroundColor Yellow
    Write-Host "  Rebuild the environment (setup.ps1 -InstallPython) and run again for a stamp." -ForegroundColor Yellow
    Write-Host ""
    exit 1
}

# ── Green: write the stamp ────────────────────────────────────────────────────

$hashes = @{}
foreach ($f in Get-CodeFiles) {
    $rel = $f.FullName.Substring($RepoRoot.Length + 1)
    $hashes[$rel] = (Get-FileHash -Path $f.FullName -Algorithm SHA256).Hash
}

$stamp = [ordered]@{
    generated   = (Get-Date).ToString("s")
    interpreter = $suitePython
    interpreter_source = $resolved.Source
    elapsed_s   = $elapsed
    suites      = @{ passed = $passed; failed = 0; not_run = $notRun.Count; discovered = $suites.Count }
    outcomes    = $results
    code_hashes = $hashes
}

$stamp | ConvertTo-Json -Depth 6 | Set-Content -Path $StampPath -Encoding utf8

Write-Line ""
Write-Line "  GREEN - .rt-green.json written ($($hashes.Count) code file hashes)" "Green"
Write-Line ""
exit 0
