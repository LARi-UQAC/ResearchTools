#Requires -Version 5.1
<#
.SYNOPSIS
    Run the offline suite and every verify-*.ps1 check in one go, and say which failed.

.DESCRIPTION
    run-offline-tests.ps1 runs only the Python suites. The PowerShell verifiers
    (verify-setup-writes.ps1, verify-sync-writes.ps1 and the others) are separate scripts,
    so a green suite does not cover them. This script runs the suite first and then each
    verifier in name order, each in its own PowerShell process so one that calls exit cannot
    stop the others. Every check runs even when an earlier one fails. The exit code is 0 only
    when all of them exit 0.

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
    [switch]$DryRun
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

$results = @()
foreach ($c in $checks) {
    Write-Host ""
    Write-Host "=== $($c.Name) ===" -ForegroundColor Cyan
    $started = Get-Date
    $global:LASTEXITCODE = 0
    if ($c.Kind -eq "suite" -and $Python) {
        & powershell -NoProfile -ExecutionPolicy Bypass -File $c.Path -Python $Python
    } else {
        & powershell -NoProfile -ExecutionPolicy Bypass -File $c.Path
    }
    $code = $LASTEXITCODE
    $seconds = [Math]::Round(((Get-Date) - $started).TotalSeconds, 1)
    $results += [PSCustomObject]@{ name = $c.Name; exit_code = $code; seconds = $seconds }
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
