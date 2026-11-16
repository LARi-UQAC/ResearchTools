#Requires -Version 5.1
<#
.SYNOPSIS
    Run the offline suite and every verify-*.ps1 of this folder in one go, and say which failed.

.DESCRIPTION
    run-offline-tests.ps1 runs only the Python suites. The PowerShell verifiers
    (verify-setup-writes.ps1, verify-sync-writes.ps1 and the others) are separate scripts,
    so a green suite does not cover them. This script runs the suite first and then each
    verifier in name order, each in its own PowerShell process so one that calls exit cannot
    stop the others. Every check runs even when an earlier one fails. The exit code is 0 only
    when all of them exit 0.

    Not run, because they live elsewhere: scripts\local\Test\verify-claude-switch.ps1, the three
    verify-*.ps1 of .claude\skills\aider-setup\scripts\Test and verify-kit-install.ps1 of its
    scripts\build folder. Run those by name.

    verify-graph-health.ps1 is left out by default: vault-access-guard.py refuses it to every
    caller but local-writer (it reads the code graph). Dispatch local-writer for that one.

    The suite takes about 15 minutes. -SkipSuite or -Only run less. -DryRun lists what would
    run and runs nothing.

.PARAMETER Only
    Run only these checks, a name with or without .ps1, for example:
    -Only verify-setup-writes,verify-sync-writes. An unknown name is a refusal (exit 2).

.PARAMETER SkipSuite
    Leave run-offline-tests.ps1 out.

.PARAMETER Exclude
    File names to leave out. Default: verify-graph-health.ps1.

.PARAMETER Python
    Passed to run-offline-tests.ps1 as its -Python, when you want to name the interpreter.

.PARAMETER ReportPath
    Also write a JSON report: each check with its exit code and seconds, and the counts.

.PARAMETER TestDir
    The folder holding the checks. Defaults to this script's folder. Exists so the checks of
    this script can be proven against a throwaway folder.

.PARAMETER DryRun
    List the checks in run order and run none of them.

.PARAMETER Jobs
    How many processes run at once. 0 (the default) takes the share of the logical processors written in
    scripts\lib\rt-runner.json (90 percent, chosen by the owner 2026-11-16). The Python suites run first, side by
    side inside run-offline-tests.ps1, then the verify-*.ps1 run side by side, each in its own process. 1 runs
    everything one after the other, as before.

.NOTES
    Exit codes: 0 every check passed (or a dry run), 1 at least one failed, 2 refused (an
    unknown -Only name, or no suite script).

.EXAMPLE
    .\scripts\test\run-all-checks.ps1
    .\scripts\test\run-all-checks.ps1 -DryRun
    .\scripts\test\run-all-checks.ps1 -SkipSuite
    .\scripts\test\run-all-checks.ps1 -Only verify-setup-writes,verify-sync-writes
#>
param(
    [string[]]$Only = @(),
    [switch]$SkipSuite,
    [string[]]$Exclude = @("verify-graph-health.ps1"),
    [string]$Python = "",
    [string]$ReportPath = "",
    [string]$TestDir = $PSScriptRoot,
    [switch]$DryRun,
    [int]$Jobs = 0
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

. (Join-Path $PSScriptRoot "..\lib\rt-checks.ps1")

# A single "-Only a,b" typed in a shell may arrive as one string.
$onlyNames = @($Only | ForEach-Object { $_ -split ',' } | Where-Object { $_ })

try {
    $checks = @(Get-RtCheckList -TestDir $TestDir -Exclude $Exclude -Only $onlyNames -SkipSuite:$SkipSuite)
} catch [System.ArgumentException] {
    Write-Host "[REFUSED] $($_.Exception.Message)" -ForegroundColor Red
    exit 2
}

Write-Host ""
Write-Host "=== run-all-checks: $($checks.Count) check(s) ===" -ForegroundColor Cyan
foreach ($c in $checks) { Write-Host "  - $($c.Name)" }

if ($DryRun) {
    Write-Host ""
    Write-Host "Dry run: nothing was run." -ForegroundColor DarkGray
    exit 0
}

. (Join-Path $PSScriptRoot "..\lib\rt-parallel.ps1")
$runnerConfig = Join-Path $PSScriptRoot "..\lib\rt-runner.json"
$jobCount = Get-RtJobCount -Requested $Jobs -ConfigPath $runnerConfig
$runnerSettings = Read-RtRunnerConfig -Path $runnerConfig
$pollMs   = [int]$runnerSettings.poll_ms
$priority = [string]$runnerSettings.priority
# This script and every check it starts run at the priority class of rt-runner.json (inherited by what they start).
$null = Set-RtOwnPriority -Priority $priority

$results = @()

# Phase 1: the Python suites. The suite script runs its own suites side by side, so it gets the machine to itself.
foreach ($c in @($checks | Where-Object { $_.Kind -eq "suite" })) {
    Write-Host ""
    Write-Host "=== $($c.Name) ===" -ForegroundColor Cyan
    $started = Get-Date
    $global:LASTEXITCODE = 0
    $suiteArgs = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $c.Path)
    if ($Python) { $suiteArgs += @("-Python", $Python) }
    if ($Jobs -gt 0) { $suiteArgs += @("-Jobs", "$Jobs") }
    & powershell @suiteArgs
    $code = $LASTEXITCODE
    $seconds = [Math]::Round(((Get-Date) - $started).TotalSeconds, 1)
    $results += [PSCustomObject]@{ name = $c.Name; exit_code = $code; seconds = $seconds }
}

# Phase 2: the PowerShell verifiers, up to $jobCount at once, each in its own process. Each prints its own block when
# it ends, so the lines of two checks never mix. Every check runs even when one fails.
$verifiers = @($checks | Where-Object { $_.Kind -ne "suite" })
if ($verifiers.Count -gt 0) {
    Write-Host ""
    Write-Host "=== $($verifiers.Count) verifier(s), $([Math]::Min($jobCount, $verifiers.Count)) at once ===" -ForegroundColor Cyan
    $items = @($verifiers | ForEach-Object {
        [PSCustomObject]@{
            Name = $_.Name; FilePath = "powershell"; WorkingDirectory = ""
            ArgumentString = "-NoProfile -ExecutionPolicy Bypass -File `"$($_.Path)`""
        }
    })
    $ran = @(Invoke-RtParallel -Items $items -Jobs $jobCount -PollMs $pollMs -Priority $priority -OnComplete {
        param($run)
        Write-Host ""
        Write-Host "=== $($run.Name)  (exit $($run.ExitCode), $($run.Seconds)s) ===" -ForegroundColor Cyan
        Write-Host $run.Output
    })
    foreach ($run in $ran) {
        $results += [PSCustomObject]@{ name = $run.Name; exit_code = $run.ExitCode; seconds = $run.Seconds }
    }
}

$failed = @($results | Where-Object { $_.exit_code -ne 0 })
Write-Host ""
Write-Host "=== Summary ===" -ForegroundColor Cyan
foreach ($r in $results) {
    $tag = if ($r.exit_code -eq 0) { "PASS" } else { "FAIL" }
    $color = if ($r.exit_code -eq 0) { "DarkGray" } else { "Red" }
    Write-Host ("  {0}  {1}  (exit {2}, {3}s)" -f $tag, $r.name, $r.exit_code, $r.seconds) -ForegroundColor $color
}

if ($ReportPath) {
    $report = [PSCustomObject]@{
        checks = $results
        passed = $results.Count - $failed.Count
        failed = $failed.Count
    }
    [System.IO.File]::WriteAllText($ReportPath, ($report | ConvertTo-Json -Depth 5), (New-Object System.Text.UTF8Encoding($false)))
}

Write-Host ""
if ($failed.Count -eq 0) {
    Write-Host "All $($results.Count) check(s) passed." -ForegroundColor Green
    exit 0
}
Write-Host "$($failed.Count) of $($results.Count) check(s) failed: $((@($failed | ForEach-Object { $_.name })) -join ', ')" -ForegroundColor Red
exit 1
