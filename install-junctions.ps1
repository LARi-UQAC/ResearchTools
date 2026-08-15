#Requires -Version 5.1
<#
.SYNOPSIS
    Creates junctions/symlinks from ~/.claude into this ResearchTools workspace
    so that Claude Code loads all agents, skills, rules, and commands globally.

.DESCRIPTION
    LAYOUT ASYMMETRY (do not "fix" one to match the other):
      skills/ are FOLDER-based  (skills/<name>/SKILL.md)  -> one Junction per sub-folder.
      agents/ are FILE-based    (agents/<name>.md, YAML frontmatter) -> one link per FILE.
    Claude Code discovers agents by scanning flat *.md files in .claude/agents/;
    a directory junction there is invisible to discovery.

    For agents/, one per-file link is created per *.md (SymbolicLink; HardLink
    fallback when symlink privilege is missing - enable Windows Developer Mode
    for true symlinks; hardlinks detach when git pull rewrites a file, so re-run
    this script after pulls that change agents). Stale directory junctions from
    the old per-folder layout are removed automatically when they point into
    this repository.

    For skills/ sub-directories, one Junction is created per entry.

    For rules/ and commands/, the strategy adapts to what already exists in
    ~/.claude:

      Target does not exist      -> whole-directory Junction  (no admin needed)
      Target is already a Junction -> EXISTS / CONFLICT (reported, not touched)
      Target is a real directory -> per-file SymbolicLink for each missing file
                                    (requires Administrator; the script re-launches
                                    itself elevated automatically when needed)

    The workspace is the single source of truth. git pull immediately updates
    all linked entries.

    SAFETY:
    - Never overwrites an existing real directory or real file.
    - Warns and skips on conflict; nothing is deleted automatically.
    - Does NOT link settings.json or CLAUDE.md (machine-local files).

.EXAMPLE
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
function Write-Created([string]$text)  { Write-Host "  [CREATED]  $text" -ForegroundColor Green }
function Write-Exists([string]$text)   { Write-Host "  [EXISTS]   $text" -ForegroundColor DarkGray }
function Write-Conflict([string]$text) { Write-Host "  [CONFLICT] $text" -ForegroundColor Red }
function Write-Skipped([string]$text)  { Write-Host "  [SKIPPED]  $text" -ForegroundColor Yellow }
function Write-WhatIf([string]$text)   { Write-Host "  [WHATIF]   $text" -ForegroundColor Magenta }
function Write-Info([string]$text)     { Write-Host "  [INFO]     $text" -ForegroundColor Cyan }

$stats = @{ Created = 0; AlreadyExists = 0; Conflicts = 0; Skipped = 0 }
$script:conflictPaths = @()

function New-JunctionSafe([string]$linkPath, [string]$target) {
    if (Test-Path $linkPath) {
        $item = Get-Item $linkPath -Force
        if ($item.LinkType -eq "Junction") {
            Write-Exists "$linkPath  ->  $target"
            $stats.AlreadyExists++
        } else {
            Write-Conflict "$linkPath exists as a real directory — skipping (remove manually to replace)"
            $stats.Conflicts++
            $script:conflictPaths += $linkPath
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
    if (Test-Path $linkPath -PathType Leaf) {
        $item = Get-Item $linkPath -Force
        if ($item.LinkType -eq "SymbolicLink" -or $item.LinkType -eq "HardLink") {
            Write-Exists "$linkPath  ->  $target"
            $stats.AlreadyExists++
        } else {
            Write-Conflict "$linkPath exists as a real file — skipping (remove manually to replace)"
            $stats.Conflicts++
            $script:conflictPaths += $linkPath
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
    try {
        New-Item -ItemType SymbolicLink -Path $linkPath -Target $target -ErrorAction Stop | Out-Null
        Write-Created "Symlink:  $linkPath"
    } catch {
        # No symlink privilege (Developer Mode off, not elevated): hard link on same volume
        New-Item -ItemType HardLink -Path $linkPath -Target $target -ErrorAction Stop | Out-Null
        Write-Created "Hardlink: $linkPath  (enable Developer Mode for symlinks; re-run after git pull)"
    }
    $stats.Created++
}

# New-MixedDirLink handles rules/ and commands/ with the hybrid strategy.
# Returns $true if per-file symlinks were attempted (signals admin may be required).
function New-MixedDirLink([string]$source, [string]$linkPath) {
    if (-not (Test-Path $source)) {
        Write-Skipped "$source not found in repo"
        return $false
    }

    if (-not (Test-Path $linkPath)) {
        # Fast path: target absent -> whole-directory junction, no admin needed
        New-JunctionSafe $linkPath $source
        return $false
    }

    $item = Get-Item $linkPath -Force
    if ($item.LinkType -eq "Junction") {
        Write-Exists "$linkPath  ->  $source"
        $stats.AlreadyExists++
        return $false
    }

    # Real directory exists from another project: use per-file symlinks
    Write-Info "$linkPath is a real directory — switching to per-file symlinks"
    Get-ChildItem $source -File | ForEach-Object {
        New-SymlinkSafe (Join-Path $linkPath $_.Name) $_.FullName
    }
    return $true
}

# ─── Admin check ──────────────────────────────────────────────────────────────

function Test-IsAdmin {
    ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator)
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
    # Cleanup pass: remove stale per-FOLDER junctions from the old layout.
    # Only junctions whose target is inside this repo's agents dir; real
    # directories are never touched.
    $homeAgents = Join-Path $homeClaude "agents"
    if (Test-Path $homeAgents) {
        Get-ChildItem $homeAgents -Force -ErrorAction SilentlyContinue |
            Where-Object { $_.PSIsContainer -and $_.LinkType -eq "Junction" -and $_.Target -like "$agentsSource*" } |
            ForEach-Object {
                if ($WhatIf) { Write-WhatIf "Would remove stale junction: $($_.FullName)" }
                else { $_.Delete(); Write-Info "Removed stale junction: $($_.FullName)" }
            }
    }
    $testJunction = Join-Path $homeClaude "__test_junction__"
    if (Test-Path $testJunction) {
        Write-Skipped "$testJunction still present — remove manually if unwanted"
    }

    # Agents are FILE-based: one link per flat <name>.md (see header note).
    Get-ChildItem $agentsSource -File -Filter *.md | ForEach-Object {
        New-SymlinkSafe (Join-Path $homeClaude "agents\$($_.Name)") $_.FullName
    }
} else {
    Write-Skipped "agents/ not found in repo"
}

# ─── Skills ───────────────────────────────────────────────────────────────────

Write-Header "Skills"
$skillsSource = Join-Path $repoClaudeDir "skills"
if (Test-Path $skillsSource) {
    Get-ChildItem $skillsSource -Directory | ForEach-Object {
        New-JunctionSafe (Join-Path $homeClaude "skills\$($_.Name)") $_.FullName
    }
} else {
    Write-Skipped "skills/ not found in repo"
}

# ─── Rules ────────────────────────────────────────────────────────────────────

Write-Header "Rules"
$needsAdminRules    = New-MixedDirLink (Join-Path $repoClaudeDir "rules")    (Join-Path $homeClaude "rules")

# ─── Commands ─────────────────────────────────────────────────────────────────

Write-Header "Commands"
$needsAdminCommands = New-MixedDirLink (Join-Path $repoClaudeDir "commands") (Join-Path $homeClaude "commands")

# ─── Elevation if per-file symlinks are pending ───────────────────────────────

if (($needsAdminRules -or $needsAdminCommands) -and -not $WhatIf) {
    if (-not (Test-IsAdmin)) {
        Write-Host ""
        Write-Host "  Per-file symlinks required but no admin privileges." -ForegroundColor Yellow
        Write-Host "  Re-launching elevated to complete the symlink creation..." -ForegroundColor Yellow
        $argList = "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`""
        Start-Process powershell -ArgumentList $argList -Verb RunAs -Wait
    }
}

# ─── Summary ──────────────────────────────────────────────────────────────────

Write-Header "Summary"
Write-Host "  Created      : $($stats.Created)"
Write-Host "  Already exist: $($stats.AlreadyExists)"
Write-Host "  Conflicts    : $($stats.Conflicts)"  $(if ($stats.Conflicts -gt 0) { "(resolve manually)" })

if ($stats.Conflicts -gt 0) {
    Write-Host ""
    Write-Host "  CONFLICTING ENTRIES (shadowing this repository):" -ForegroundColor Red
    $script:conflictPaths | ForEach-Object { Write-Host "    $_" -ForegroundColor Red }
    Write-Host "  A real directory here means the repository version is NOT loaded." -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "Done." -ForegroundColor Green
Write-Host "Claude Code will now load agents and skills from this repository"
Write-Host "in any workspace where no local .claude/agents/ or .claude/skills/ override them."
Write-Host ""
