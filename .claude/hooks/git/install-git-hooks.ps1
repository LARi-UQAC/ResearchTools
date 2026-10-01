<#
.SYNOPSIS
    Install the global privacy-guard git hooks (core.hooksPath) for every repository on this machine.

.DESCRIPTION
    Copies pre-commit and privacy-rules.toml to -Target, copies _chain there under every other
    client-side hook name (so each repository's own .git/hooks keep running, since a global
    core.hooksPath disables them), then sets `git config --global core.hooksPath` to -Target and
    reads it back (R9). A global core.hooksPath already pointing elsewhere is REFUSED rather than
    overwritten: another hook manager owns it. -Uninstall unsets core.hooksPath when it points to
    -Target and leaves the files. Prints a human summary and, with -Json, one JSON object (R17).

.PARAMETER Target
    Directory the hooks are installed into. Default: ~/.config/git/hooks.

.PARAMETER DryRun
    Print what would be done and change nothing (R16).

.PARAMETER Uninstall
    Unset the global core.hooksPath if it points to -Target.

.PARAMETER Json
    Also print the machine-readable report.

.OUTPUTS
    Exit 0 done (or dry run), 2 refused by design (another core.hooksPath, missing source file),
    1 failure (the read-back does not match what was written).
#>
param(
    [string]$Target = (Join-Path $HOME ".config\git\hooks"),
    [switch]$DryRun,
    [switch]$Uninstall,
    [switch]$Json
)

$ErrorActionPreference = "Stop"

# Git's client-side hook names that _chain stands in for (git-scm.com/docs/githooks).
# pre-commit is excluded: it has its own script, which chains at its end.
$ChainNames = @(
    "applypatch-msg", "pre-applypatch", "post-applypatch", "pre-merge-commit",
    "prepare-commit-msg", "commit-msg", "post-commit", "pre-rebase", "post-checkout",
    "post-merge", "pre-push", "post-rewrite", "pre-auto-gc"
)

function Get-NormalPath([string]$Path) {
    <# Purpose: compare two spellings of one directory. Inputs: Path. Outputs: full path, forward slashes, no trailing slash. #>
    if (-not $Path) { return "" }
    return ([System.IO.Path]::GetFullPath($Path) -replace '\\', '/').TrimEnd('/')
}

function Write-Report([hashtable]$Report, [int]$Code) {
    <# Purpose: print the human summary and the optional JSON, then exit. Inputs: report, exit code. #>
    Write-Host ("privacy guard hooks: {0} - {1}" -f $Report.status, $Report.message)
    if ($Json) { $Report | ConvertTo-Json -Depth 4 }
    exit $Code
}

$source  = $PSScriptRoot
$targetN = Get-NormalPath $Target
$current = (& git config --global --get core.hooksPath 2>$null)
$currentN = Get-NormalPath $current
$report = @{ target = $targetN; previous_hooks_path = $current; dry_run = [bool]$DryRun; files = @() }

if ($Uninstall) {
    if ($currentN -ne $targetN) {
        $report.status = "unchanged"; $report.message = "core.hooksPath does not point to $targetN"
        Write-Report $report 0
    }
    if (-not $DryRun) { & git config --global --unset core.hooksPath }
    $report.status = $(if ($DryRun) { "dry-run" } else { "uninstalled" })
    $report.message = "core.hooksPath unset; files left in $targetN"
    Write-Report $report 0
}

if ($current -and $currentN -ne $targetN) {
    $report.status = "refused"
    $report.message = "global core.hooksPath already points to $current; not overwritten"
    Write-Report $report 2
}

foreach ($name in @("pre-commit", "_chain", "privacy-rules.toml")) {
    if (-not (Test-Path -LiteralPath (Join-Path $source $name))) {
        $report.status = "refused"; $report.message = "source file missing: $name"
        Write-Report $report 2
    }
}

$plan = @(
    @{ from = "pre-commit"; to = "pre-commit" },
    @{ from = "privacy-rules.toml"; to = "privacy-rules.toml" }
) + ($ChainNames | ForEach-Object { @{ from = "_chain"; to = $_ } })
$report.files = $plan | ForEach-Object { $_.to }

$bl = Get-Command betterleaks -ErrorAction SilentlyContinue
if (-not $bl) {
    $bl = Get-ChildItem -Path (Join-Path $env:LOCALAPPDATA "Microsoft\WinGet\Packages") -Filter betterleaks.exe -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
}
$report.betterleaks = [bool]$bl

if ($DryRun) {
    $report.status = "dry-run"
    $report.message = "would copy $($plan.Count) files to $targetN and set global core.hooksPath"
    Write-Report $report 0
}

New-Item -ItemType Directory -Force -Path $Target | Out-Null
foreach ($step in $plan) {
    Copy-Item -LiteralPath (Join-Path $source $step.from) -Destination (Join-Path $Target $step.to) -Force
}
& git config --global core.hooksPath $targetN

# R9: verify the effect, not the exit codes.
$after = Get-NormalPath (& git config --global --get core.hooksPath)
$bad = $plan | Where-Object {
    (Get-FileHash -LiteralPath (Join-Path $Target $_.to)).Hash -ne (Get-FileHash -LiteralPath (Join-Path $source $_.from)).Hash
}
if ($after -ne $targetN -or $bad) {
    $report.status = "failed"; $report.message = "read-back mismatch (core.hooksPath=$after, files differing: $($bad.Count))"
    Write-Report $report 1
}
$report.status = "installed"
$report.message = "$($plan.Count) files in $targetN; core.hooksPath set" + $(if (-not $bl) { "; WARNING betterleaks not found, only the account-name check will run" } else { "" })
Write-Report $report 0
