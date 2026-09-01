<#
.SYNOPSIS
    Start the rt-observe dashboard. Thin wrapper, no logic.

.DESCRIPTION
    The canonical launcher lives beside its module, in
    .claude\skills\rt-observe\scripts\rt-dashboard.ps1 (R18). This file exists
    only so the command is one tab-completion away from the repository root, the
    same shape as START_APPLICATION.ps1.

    Every parameter is forwarded to the canonical launcher unchanged.

.EXAMPLE
    .\rt-dashboard.ps1 -DryRun

.EXAMPLE
    .\rt-dashboard.ps1 -Open
#>
[CmdletBinding()]
param(
    [switch]$Open,
    [switch]$DryRun,
    [int]$Port = 0,
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$Rest
)

$canonical = Join-Path $PSScriptRoot '.claude\skills\rt-observe\scripts\rt-dashboard.ps1'
if (-not (Test-Path $canonical)) {
    [Console]::Error.WriteLine("rt-dashboard: the canonical launcher is missing ($canonical).")
    exit 2
}

& $canonical @PSBoundParameters
exit $LASTEXITCODE
