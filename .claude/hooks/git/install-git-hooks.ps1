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

# Every hook name githooks(5) documents (git 2.53), minus three: pre-commit, which has its
# own script and chains at its end, and the two below. _chain stands in for the rest so a
# repository's own .git/hooks keep running under a global core.hooksPath.
$ChainNames = @(
    "applypatch-msg", "pre-applypatch", "post-applypatch", "pre-merge-commit",
    "prepare-commit-msg", "commit-msg", "post-commit", "pre-rebase", "post-checkout",
    "post-merge", "pre-push", "pre-receive", "update", "proc-receive", "post-receive",
    "post-update", "push-to-checkout", "pre-auto-gc", "post-rewrite", "sendemail-validate",
    "fsmonitor-watchman", "p4-changelist", "p4-prepare-changelist", "p4-post-changelist",
    "p4-pre-submit"
)
# NOT chained, deliberately: they fire several times per ordinary command, and a chain
# script spawns a shell each time. Measured 2026-10-02 on Windows: 10 add+commit+status
# cycles took 575 ms each with no hook, 3598 ms with these two chained. A repository that
# needs its own copy of one sets `git config core.hooksPath .git/hooks` locally (its
# commits then rely on the privacy-scan CI alone).
$ExcludedHooks = @("reference-transaction", "post-index-change")
# A file in -Target is ours when it carries one of these markers; anything else belongs to
# another hook manager and is never overwritten.
$OwnMarkers = @("installed by install-git-hooks.ps1", 'title = "LARi privacy guard"')

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
$report = @{ target = $targetN; previous_hooks_path = $current; dry_run = [bool]$DryRun; files = @();
             not_chained = $ExcludedHooks }

if ($Uninstall) {
    if ($currentN -ne $targetN) {
        $report.status = "unchanged"; $report.message = "core.hooksPath does not point to $targetN"
        Write-Report $report 0
    }
    if ($DryRun) {
        $report.status = "dry-run"; $report.message = "would unset core.hooksPath; files would stay in $targetN"
        Write-Report $report 0
    }
    & git config --global --unset core.hooksPath
    # R9: a native command's failure does not throw in PowerShell; read the effect back.
    if (Get-NormalPath (& git config --global --get core.hooksPath 2>$null)) {
        $report.status = "failed"; $report.message = "core.hooksPath is still set after --unset"
        Write-Report $report 1
    }
    $report.status = "uninstalled"
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

# Path equality with core.hooksPath does not prove this guard owns the directory: another
# manager may already keep its hooks there. Refuse before writing anything.
$foreign = @($plan | Where-Object {
    $dest = Join-Path $Target $_.to
    if (-not (Test-Path -LiteralPath $dest)) { return $false }
    $text = Get-Content -LiteralPath $dest -Raw -ErrorAction SilentlyContinue
    -not ($OwnMarkers | Where-Object { $text -and $text.Contains($_) })
} | ForEach-Object { $_.to })
if ($foreign.Count -gt 0) {
    $report.status = "refused"; $report.foreign_files = $foreign
    $report.message = "$targetN already holds hooks this guard did not install: $($foreign -join ', ')"
    Write-Report $report 2
}

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
