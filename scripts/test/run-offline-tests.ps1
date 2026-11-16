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

.PARAMETER Jobs
    How many suites run at once. 0 (the default) takes the share of the logical processors written in
    scripts\lib\rt-runner.json (90 percent, chosen by the owner 2026-11-16); 1 runs them one after the other, as
    before. A suite that fails under parallel load is run again alone: if it passes alone it is reported as
    flaky under load and counted as passed, if it fails again it is a real failure.

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
    [switch]$AllowPathFallback,
    [int]$Jobs = 0
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
# The suites run side by side (scripts\lib\rt-parallel.ps1), the share of processors is in scripts\lib\rt-runner.json.
. (Join-Path $RepoRoot "scripts\lib\rt-parallel.ps1")

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
$flaky    = @()
$passed   = 0
$started  = Get-Date

# ── How many suites run at once ───────────────────────────────────────────────
# One suite is one python process, so the suites are independent and run side by side: sequentially the
# machine sat at 20 to 25 percent CPU (measured by the owner 2026-11-16). -Jobs 1 gives the old sequential run.
$runnerConfig = Join-Path $RepoRoot "scripts\lib\rt-runner.json"
$jobCount = Get-RtJobCount -Requested $Jobs -ConfigPath $runnerConfig
$runnerSettings = Read-RtRunnerConfig -Path $runnerConfig
$pollMs   = [int]$runnerSettings.poll_ms
Write-Line "  Parallel    : $jobCount suite(s) at once"

# The slowest suites start first, so the run does not end on one long suite started last. The time of each suite
# (the total work, in seconds) is kept in .rt-suite-times.json, written after every run even a red one, since a red
# run deletes the stamp; a suite it does not know starts before the known ones.
$TimesPath = Join-Path $RepoRoot ".rt-suite-times.json"
$previousSeconds = @{}
if (Test-Path $TimesPath) {
    try {
        $timesDoc = Get-Content $TimesPath -Raw -Encoding UTF8 | ConvertFrom-Json
        foreach ($p in $timesDoc.PSObject.Properties) { $previousSeconds[[string]$p.Name] = [double]$p.Value }
    } catch { $previousSeconds = @{} }
}
$splitSeconds = [double]$runnerSettings.split_seconds
$chunkSeconds = [double]$runnerSettings.chunk_seconds
function Get-SuiteRel($suite) { $suite.FullName.Substring($RepoRoot.Length + 1) }
$startOrder = @($suites | Sort-Object -Property `
    @{ Expression = { if ($previousSeconds.ContainsKey((Get-SuiteRel $_))) { $previousSeconds[(Get-SuiteRel $_)] } else { [double]::MaxValue } }; Descending = $true }, `
    @{ Expression = { $_.Length }; Descending = $true })

# File redirection of each child (done inside Invoke-RtParallel) rather than `2>&1`: in PowerShell 5.1,
# redirecting a native executable's stderr inline wraps each line in an ErrorRecord
# and sets $? to false even on a clean exit, which would misreport every suite.
function New-SuiteItem($suite) {
    [pscustomobject]@{ Name = (Get-SuiteRel $suite); FilePath = $suitePython
                       ArgumentString = "`"$($suite.FullName)`""; WorkingDirectory = $RepoRoot }
}

# PASSED, FAILED or NOT RUN for one finished suite, with the first problem line or the missing module.
function Get-SuiteVerdict($run) {
    $output = if ($null -eq $run.Output) { "" } else { $run.Output }
    if ($run.ExitCode -eq 0) { return [pscustomobject]@{ Outcome = "PASSED"; Detail = ""; Missing = "" } }
    if ((Get-MissingModuleKind $output) -eq "third-party") {
        $mod = [regex]::Match($output, "ModuleNotFoundError: No module named '([^']+)'").Groups[1].Value
        return [pscustomobject]@{ Outcome = "NOT RUN"; Detail = ""; Missing = $mod }
    }
    $firstProblem = ($output -split "`n" |
        Where-Object { $_ -match '^(FAIL|ERROR)[: ]|^\w*Error:|^AssertionError' } |
        Select-Object -First 1)
    if ($null -eq $firstProblem) { $firstProblem = "exit code $($run.ExitCode)" }
    return [pscustomobject]@{ Outcome = "FAILED"; Detail = $firstProblem.Trim(); Missing = "" }
}

$onDone = {
    param($run)
    $verdict = Get-SuiteVerdict $run
    switch ($verdict.Outcome) {
        "PASSED"  { Write-Line ("  [PASS]    {0}  ({1}s)" -f $run.Name, $run.Seconds) "DarkGray" }
        "NOT RUN" { Write-Line "  [NOT RUN] $($run.Name)  (missing '$($verdict.Missing)')" "Yellow" }
        default   { Write-Host "  [FAIL]    $($run.Name)  (first run)" -ForegroundColor Red }
    }
}

# A slow suite is cut into several processes, a share of its tests each: one suite of 122 tests that start git, a shell
# and a scanner took 12 minutes alone while the others ended in about 2, and the machine sat at 10 percent CPU. Only a
# suite whose recorded time reaches split_seconds is cut, and only when it ends in unittest.main() so that the test
# ids can be given on its command line; its ids are read by scripts\test\list_test_ids.py without running a test.
$listScript = Join-Path $PSScriptRoot "list_test_ids.py"
$candidates = @($startOrder | Where-Object {
    $jobCount -gt 1 -and $previousSeconds.ContainsKey((Get-SuiteRel $_)) -and $previousSeconds[(Get-SuiteRel $_)] -ge $splitSeconds -and
    (Select-String -LiteralPath $_.FullName -Pattern 'unittest\.main\(' -Quiet)
})
$idsOf = @{}
if ($candidates.Count -gt 0) {
    $listItems = @($candidates | ForEach-Object {
        [pscustomobject]@{ Name = (Get-SuiteRel $_); FilePath = $suitePython; WorkingDirectory = $RepoRoot
                           ArgumentString = "`"$listScript`" `"$($_.FullName)`"" }
    })
    foreach ($listed in @(Invoke-RtParallel -Items $listItems -Jobs $jobCount -PollMs $pollMs)) {
        if ($listed.ExitCode -eq 0) {
            $idsOf[$listed.Name] = @($listed.Output -split "`r?`n" | ForEach-Object { if ($_ -match '^TESTID (.+)$') { $Matches[1].Trim() } })
        }
    }
}

$items = @()
$itemSuite = @()   # the suite each item belongs to, same index as $items
foreach ($suite in $startOrder) {
    $rel = Get-SuiteRel $suite
    $ids = @(if ($idsOf.ContainsKey($rel)) { $idsOf[$rel] })
    $count = if ($ids.Count -gt 0) {
        Get-RtChunkCount -RecordedSeconds $previousSeconds[$rel] -TestCount $ids.Count -Jobs $jobCount `
                         -SplitSeconds $splitSeconds -ChunkSeconds $chunkSeconds
    } else { 1 }
    if ($count -gt 1) {
        $groups = @(Split-RtIds -Ids $ids -Count $count)
        for ($k = 0; $k -lt $groups.Count; $k++) {
            $items += [pscustomobject]@{ Name = "$rel#$($k + 1)"; FilePath = $suitePython; WorkingDirectory = $RepoRoot
                                         ArgumentString = "`"$($suite.FullName)`" " + (@($groups[$k]) -join " ") }
            $itemSuite += $rel
        }
        Write-Line "  [SPLIT]   $rel  ($($ids.Count) tests in $($groups.Count) processes, $([int]$previousSeconds[$rel]) s recorded)" "DarkGray"
    } else {
        $items += New-SuiteItem $suite
        $itemSuite += $rel
    }
}

$ranFirst = @(Invoke-RtParallel -Items $items -Jobs $jobCount -PollMs $pollMs -OnComplete $onDone)

# An item that fails while others run beside it is run again ALONE (a whole suite, or one share of a cut suite). A
# failure that repeats is a real failure; one that does not repeat is reported as flaky under load (a shared file, a
# timing), never hidden and never counted red.
if ($jobCount -gt 1) {
    for ($i = 0; $i -lt $ranFirst.Count; $i++) {
        $first = $ranFirst[$i]
        if ((Get-SuiteVerdict $first).Outcome -ne "FAILED") { continue }
        Write-Line "  [RERUN]   $($first.Name)  (alone, after a failure under parallel load)" "Yellow"
        $alone = @(Invoke-RtParallel -Items @($items[$i]) -Jobs 1 -PollMs $pollMs)[0]
        $decision = Resolve-RtRetry -FirstOutcome "FAILED" -AloneOutcome (Get-SuiteVerdict $alone).Outcome
        $ranFirst[$i] = $alone
        if ($decision.Flaky) {
            $flaky += [pscustomobject]@{ suite = $first.Name; detail = (Get-SuiteVerdict $first).Detail }
            Write-Line "  [PASS]    $($first.Name)  (flaky under parallel load, passed alone)" "Yellow"
        }
    }
}

# One result per suite: the shares of a cut suite are merged (first failing exit code, every output, total seconds).
$runByName = @{}
foreach ($rel in @($itemSuite | Select-Object -Unique)) {
    $mine = @(for ($i = 0; $i -lt $ranFirst.Count; $i++) { if ($itemSuite[$i] -eq $rel) { $ranFirst[$i] } })
    $runByName[$rel] = if ($mine.Count -eq 1) { $mine[0] } else { Merge-RtChunks -Name $rel -Chunks $mine }
}

# The time of every suite, for the next run: the slowest start first and a slow one is cut. Written whatever the verdict.
try {
    $times = [ordered]@{}
    foreach ($key in $runByName.Keys) { $times[$key] = $runByName[$key].Seconds }
    ($times | ConvertTo-Json) | Set-Content -LiteralPath $TimesPath -Encoding UTF8
} catch { Write-Line "  (could not write .rt-suite-times.json: $($_.Exception.Message))" "Yellow" }

foreach ($suite in $suites) {
    $rel = Get-SuiteRel $suite
    $run = $runByName[$rel]
    $verdict = Get-SuiteVerdict $run
    switch ($verdict.Outcome) {
        "PASSED" {
            $results += [pscustomobject]@{ suite = $rel; outcome = "PASSED"; seconds = $run.Seconds }
            $passed++
        }
        "NOT RUN" {
            $results += [pscustomobject]@{ suite = $rel; outcome = "NOT RUN"; missing = $verdict.Missing; seconds = $run.Seconds }
            $notRun  += [pscustomobject]@{ suite = $rel; missing = $verdict.Missing }
        }
        default {
            $results += [pscustomobject]@{ suite = $rel; outcome = "FAILED"; detail = $verdict.Detail; seconds = $run.Seconds }
            $failed  += [pscustomobject]@{ suite = $rel; detail = $verdict.Detail; output = $run.Output }
            Write-Host "  [FAIL]    $rel  (also alone)" -ForegroundColor Red
        }
    }
}

$elapsed = [int]((Get-Date) - $started).TotalSeconds

# ── Verdict ───────────────────────────────────────────────────────────────────

Write-Line ""
Write-Host "  PASSED $passed   FAILED $($failed.Count)   NOT RUN $($notRun.Count)   ($elapsed s, $jobCount at once)" `
           -ForegroundColor $(if ($failed.Count -gt 0) { "Red" } else { "Green" })

if ($flaky.Count -gt 0) {
    Write-Line ""
    Write-Line "  FLAKY under parallel load (failed with others running, passed alone; they are counted as passed):" "Yellow"
    foreach ($f in $flaky) { Write-Line "    $($f.suite)  $($f.detail)" "Yellow" }
    Write-Line "  Run with -Jobs 1 to see whether the suite itself depends on the others." "Yellow"
}

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
    jobs        = $jobCount
    flaky       = @($flaky | ForEach-Object { $_.suite })
    suites      = @{ passed = $passed; failed = 0; not_run = $notRun.Count; discovered = $suites.Count }
    outcomes    = $results
    code_hashes = $hashes
}

$stamp | ConvertTo-Json -Depth 6 | Set-Content -Path $StampPath -Encoding utf8

Write-Line ""
Write-Line "  GREEN - .rt-green.json written ($($hashes.Count) code file hashes)" "Green"
Write-Line ""
exit 0
