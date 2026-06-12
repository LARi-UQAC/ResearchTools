#Requires -Version 5.1
#Requires -RunAsAdministrator
<#
.SYNOPSIS
    Creates directory junctions and file symlinks from ~/.claude into this
    ResearchTools workspace so that Claude Code loads all agents, skills,
    rules, and commands globally (from any project directory).

.DESCRIPTION
    For each subfolder under .claude/agents/, .claude/skills/, .claude/rules/,
    and each .md file under .claude/commands/, creates a Junction (directory)
    or SymbolicLink (file) in the user's ~/.claude directory pointing back to
    the corresponding item in this workspace.

    The workspace is the single source of truth. git pull in the workspace
    immediately updates all linked entries — no manual sync required.

    SAFETY:
    - Never overwrites an existing real directory (non-junction).
    - Warns and skips on conflict; nothing is deleted automatically.
    - Does NOT link settings.json or CLAUDE.md (those are machine-local).

.EXAMPLE
    # Run PowerShell as Administrator, then:
    .\install-junctions.ps1
    .\install-junctions.ps1 -WhatIf
#>
param(
    [switch]$WhatIf
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# ─── Helpers ──────────────────────────────────────────────────────────────────

function Write-Header([string]$text) {
    Write-Host ""
    Write-Host "=== $text ===" -ForegroundColor Cyan
}
function Write-Created([string]$text) { Write-Host "  [CREATED]  $text" -ForegroundColor Green }
function Write-Exists([string]$text)  { Write-Host "  [EXISTS]   $text" -ForegroundColor DarkGray }
function Write-Conflict([string]$text){ Write-Host "  [CONFLICT] $text" -ForegroundColor Red }
function Write-Skipped([string]$text) { Write-Host "  [SKIPPED]  $text" -ForegroundColor Yellow }
function Write-WhatIf([string]$text)  { Write-Host "  [WHATIF]   $text" -ForegroundColor Magenta }

$stats = @{ Created = 0; AlreadyExists = 0; Conflicts = 0; Skipped = 0 }

function New-JunctionSafe([string]$linkPath, [string]$target) {
    if (Test-Path $linkPath) {
        $item = Get-Item $linkPath -Force
        if ($item.LinkType -eq "Junction") {
            Write-Exists "$linkPath  ->  $target"
            $stats.AlreadyExists++
        } else {
            Write-Conflict "$linkPath exists as a real directory — skipping (remove manually to replace)"
            $stats.Conflicts++
        }
        return
    }
    if ($WhatIf) {
        Write-WhatIf "Would create Junction: $linkPath  ->  $target"
        $stats.Created++
        return
    }
    $parent = Split-Path $linkPath -Parent
    if (-not (Test-Path $parent)) { New-Item -ItemType Directory -Path $parent -Force | Out-Null }
    New-Item -ItemType Junction -Path $linkPath -Target $target | Out-Null
    Write-Created "Junction: $linkPath"
    $stats.Created++
}

function New-SymlinkSafe([string]$linkPath, [string]$target) {
    if (Test-Path $linkPath) {
        $item = Get-Item $linkPath -Force
        if ($item.LinkType -eq "SymbolicLink") {
            Write-Exists "$linkPath  ->  $target"
            $stats.AlreadyExists++
        } else {
            Write-Conflict "$linkPath exists as a real file — skipping (remove manually to replace)"
            $stats.Conflicts++
        }
        return
    }
    if ($WhatIf) {
        Write-WhatIf "Would create Symlink: $linkPath  ->  $target"
        $stats.Created++
        return
    }
    $parent = Split-Path $linkPath -Parent
    if (-not (Test-Path $parent)) { New-Item -ItemType Directory -Path $parent -Force | Out-Null }
    New-Item -ItemType SymbolicLink -Path $linkPath -Target $target | Out-Null
    Write-Created "Symlink:  $linkPath"
    $stats.Created++
}

# ─── Paths ────────────────────────────────────────────────────────────────────

$repoClaudeDir = Join-Path $PSScriptRoot ".claude"
$homeClaude    = Join-Path $env:USERPROFILE ".claude"

Write-Header "ResearchTools — Install Junctions"
Write-Host "  Repo .claude : $repoClaudeDir"
Write-Host "  Home .claude : $homeClaude"
if ($WhatIf) { Write-Host "  Mode: WhatIf (no changes will be made)" -ForegroundColor Magenta }

# ─── Agents ───────────────────────────────────────────────────────────────────

Write-Header "Agents"
$agentsSource = Join-Path $repoClaudeDir "agents"
if (Test-Path $agentsSource) {
    Get-ChildItem $agentsSource -Directory | ForEach-Object {
        $linkPath = Join-Path $homeClaude "agents\$($_.Name)"
        New-JunctionSafe $linkPath $_.FullName
    }
} else {
    Write-Skipped "agents/ not found in repo"
}

# ─── Skills ───────────────────────────────────────────────────────────────────

Write-Header "Skills"
$skillsSource = Join-Path $repoClaudeDir "skills"
if (Test-Path $skillsSource) {
    Get-ChildItem $skillsSource -Directory | ForEach-Object {
        $linkPath = Join-Path $homeClaude "skills\$($_.Name)"
        New-JunctionSafe $linkPath $_.FullName
    }
} else {
    Write-Skipped "skills/ not found in repo"
}

# ─── Rules ────────────────────────────────────────────────────────────────────

Write-Header "Rules"
$rulesSource = Join-Path $repoClaudeDir "rules"
if (Test-Path $rulesSource) {
    Get-ChildItem $rulesSource -File -Filter "*.md" | ForEach-Object {
        $linkPath = Join-Path $homeClaude "rules\$($_.Name)"
        New-SymlinkSafe $linkPath $_.FullName
    }
} else {
    Write-Skipped "rules/ not found in repo"
}

# ─── Commands ─────────────────────────────────────────────────────────────────

Write-Header "Commands"
$commandsSource = Join-Path $repoClaudeDir "commands"
if (Test-Path $commandsSource) {
    Get-ChildItem $commandsSource -File -Filter "*.md" | ForEach-Object {
        $linkPath = Join-Path $homeClaude "commands\$($_.Name)"
        New-SymlinkSafe $linkPath $_.FullName
    }
} else {
    Write-Skipped "commands/ not found in repo"
}

# ─── Summary ──────────────────────────────────────────────────────────────────

Write-Header "Summary"
Write-Host "  Created      : $($stats.Created)"
Write-Host "  Already exist: $($stats.AlreadyExists)"
Write-Host "  Conflicts    : $($stats.Conflicts)"  $(if ($stats.Conflicts -gt 0) { "(resolve manually)" })

if ($stats.Conflicts -gt 0) {
    Write-Host ""
    Write-Host "  To resolve a conflict, remove the real directory/file and re-run:" -ForegroundColor Yellow
    Write-Host "    Remove-Item -Path <conflicting-path> -Recurse -Force" -ForegroundColor Yellow
    Write-Host "    .\install-junctions.ps1" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "Done." -ForegroundColor Green
Write-Host "Claude Code will now load agents and skills from this repository"
Write-Host "in any workspace where no local .claude/agents/ or .claude/skills/ override them."
Write-Host ""
