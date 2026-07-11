#Requires -Version 5.1
<#
.SYNOPSIS
    ResearchTools setup — generates machine-local settings.json and CLAUDE.md
    from the versioned templates. Run once after cloning the repository.

.DESCRIPTION
    Auto-detects Git Bash, Node.js, and your user profile path.
    Optionally configures the Obsidian vault path for the Obsidian-integration
    section of CLAUDE.md. Writes two files that are tracked in the repository
    (the templates produce committed repo content, not machine-local copies):
        .claude\settings.json
        CLAUDE.md

.EXAMPLE
    .\setup.ps1
    .\setup.ps1 -ObsidianVault "D:\MyVault" -Force
#>
param(
    [string]$ObsidianVault = "",
    [switch]$Force,
    [switch]$InstallJunctions,
    [switch]$Preview
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# ─── Helpers ──────────────────────────────────────────────────────────────────

function Write-Header([string]$text) {
    Write-Host ""
    Write-Host "=== $text ===" -ForegroundColor Cyan
}

function Write-Ok([string]$text)   { Write-Host "  [OK]  $text" -ForegroundColor Green }
function Write-Warn([string]$text) { Write-Host "  [!!]  $text" -ForegroundColor Yellow }
function Write-Err([string]$text)  { Write-Host "  [ERR] $text" -ForegroundColor Red }

function Find-FirstExisting([string[]]$paths) {
    foreach ($p in $paths) {
        if (Test-Path $p) { return $p }
    }
    return $null
}

# ─── Resolve workspace root (directory of this script) ────────────────────────

$WorkspaceRoot = $PSScriptRoot
if (-not $WorkspaceRoot) {
    $WorkspaceRoot = (Get-Location).Path
}

Write-Header "ResearchTools — Setup"
Write-Host "  Workspace : $WorkspaceRoot"
Write-Host "  User      : $env:USERNAME"

# ─── InstallJunctions mode ────────────────────────────────────────────────────

if ($InstallJunctions) {
    $junctionsScript = Join-Path $WorkspaceRoot "install-junctions.ps1"
    if (-not (Test-Path $junctionsScript)) {
        Write-Err "install-junctions.ps1 not found at: $junctionsScript"
        exit 1
    }
    if ($Preview) { & $junctionsScript -WhatIf } else { & $junctionsScript }
    exit 0
}

# ─── Detect Git Bash ──────────────────────────────────────────────────────────

Write-Header "Detecting Git Bash"
$gitBashCandidates = @(
    "$env:USERPROFILE\AppData\Local\Programs\Git\bin\bash.exe",
    "C:\Program Files\Git\bin\bash.exe",
    "C:\Program Files (x86)\Git\bin\bash.exe"
)
$gitBashPath = Find-FirstExisting $gitBashCandidates
if ($gitBashPath) {
    Write-Ok "Found: $gitBashPath"
} else {
    Write-Warn "Git Bash not found in standard locations."
    $gitBashPath = Read-Host "  Enter full path to bash.exe (or press Enter to skip)"
    if (-not $gitBashPath) { $gitBashPath = "C:\\Program Files\\Git\\bin\\bash.exe" }
}

# ─── Detect Node.js ───────────────────────────────────────────────────────────

Write-Header "Detecting Node.js"
$nodePath = $null
try {
    $nodeWhere = (where.exe node 2>$null | Select-Object -First 1)
    if ($nodeWhere -and (Test-Path $nodeWhere)) { $nodePath = $nodeWhere }
} catch {}

if (-not $nodePath) {
    $nodeCandidates = @(
        "C:\Program Files\nodejs\node.exe",
        "C:\Program Files (x86)\nodejs\node.exe",
        "$env:APPDATA\nvm\current\node.exe"
    )
    $nodePath = Find-FirstExisting $nodeCandidates
}

if ($nodePath) {
    Write-Ok "Found: $nodePath"
} else {
    Write-Warn "Node.js not found in standard locations."
    $nodePath = Read-Host "  Enter full path to node.exe (or press Enter to skip)"
    if (-not $nodePath) { $nodePath = "C:\\Program Files\\nodejs\\node.exe" }
}

# ─── Detect Obsidian vault ────────────────────────────────────────────────────

Write-Header "Obsidian vault (optional)"
if (-not $ObsidianVault) {
    $ObsidianVault = Read-Host "  Vault path (press Enter to skip Obsidian integration)"
}
if ($ObsidianVault) {
    Write-Ok "Vault: $ObsidianVault"
} else {
    $ObsidianVault = "NOT_CONFIGURED"
    Write-Warn "Skipped — Obsidian placeholders will remain as NOT_CONFIGURED"
}

# Detect Obsidian executable
$obsidianExe = Find-FirstExisting @(
    "$env:LOCALAPPDATA\Programs\Obsidian\Obsidian.exe",
    "C:\Program Files\Obsidian\Obsidian.exe"
)
if (-not $obsidianExe) { $obsidianExe = "NOT_CONFIGURED" }

# ─── Summary + confirmation ───────────────────────────────────────────────────

Write-Header "Configuration summary"
Write-Host "  WORKSPACE_ROOT  = $WorkspaceRoot"
Write-Host "  USERPROFILE     = $env:USERPROFILE"
Write-Host "  GIT_BASH_PATH   = $gitBashPath"
Write-Host "  NODE_PATH       = $nodePath"
Write-Host "  OBSIDIAN_VAULT  = $ObsidianVault"
Write-Host "  OBSIDIAN_EXE    = $obsidianExe"
Write-Host ""

$settingsTarget = Join-Path $WorkspaceRoot ".claude\settings.json"
$claudeTarget   = Join-Path $WorkspaceRoot "CLAUDE.md"

if (-not $Force) {
    $existing = @()
    if (Test-Path $settingsTarget) { $existing += ".claude\settings.json" }
    if (Test-Path $claudeTarget)   { $existing += "CLAUDE.md" }
    if ($existing.Count -gt 0) {
        Write-Warn "These tracked files exist and will be regenerated (commit the result): $($existing -join ', ')"
    }
    $confirm = Read-Host "Proceed? [Y/n]"
    if ($confirm -match '^[Nn]') {
        Write-Host "Aborted." -ForegroundColor Yellow
        exit 0
    }
}

# ─── Generate files ───────────────────────────────────────────────────────────

function Invoke-TemplateSubstitution([string]$templatePath, [string]$outputPath, [hashtable]$vars) {
    if (-not (Test-Path $templatePath)) {
        Write-Err "Template not found: $templatePath"
        exit 1
    }
    $content = Get-Content -Path $templatePath -Raw -Encoding UTF8
    foreach ($key in $vars.Keys) {
        # Escape backslashes for JSON templates (double-escape needed in JSON strings)
        $value = $vars[$key]
        $content = $content -replace [regex]::Escape("{{$key}}"), $value
    }
    Set-Content -Path $outputPath -Value $content -Encoding UTF8 -NoNewline
}

Write-Header "Generating files"

# Escape backslashes for JSON (paths inside JSON need \\)
$wsRootJson  = $WorkspaceRoot  -replace '\\', '\\\\'
$upJson      = $env:USERPROFILE -replace '\\', '\\\\'
$gitBashJson = $gitBashPath    -replace '\\', '\\\\'
$nodeJson    = $nodePath       -replace '\\', '\\\\'

$settingsVars = @{
    WORKSPACE_ROOT = $wsRootJson
    USERPROFILE    = $upJson
    GIT_BASH_PATH  = $gitBashJson
    NODE_PATH      = $nodeJson
}
Invoke-TemplateSubstitution `
    (Join-Path $WorkspaceRoot ".claude\settings.template.json") `
    $settingsTarget `
    $settingsVars
Write-Ok "Created: .claude\settings.json"

$claudeVars = @{
    OBSIDIAN_VAULT = $ObsidianVault
    OBSIDIAN_EXE   = $obsidianExe
    WORKSPACE_ROOT = $WorkspaceRoot
    USERPROFILE    = $env:USERPROFILE
}
Invoke-TemplateSubstitution `
    (Join-Path $WorkspaceRoot "CLAUDE.template.md") `
    $claudeTarget `
    $claudeVars
Write-Ok "Created: CLAUDE.md"

# ─── Validation ───────────────────────────────────────────────────────────────

Write-Header "Validation"
$remaining = Select-String -Path $settingsTarget, $claudeTarget -Pattern '\{\{[A-Z_]+\}\}' -ErrorAction SilentlyContinue
if ($remaining) {
    Write-Warn "Unreplaced placeholders detected:"
    $remaining | ForEach-Object { Write-Warn "  $($_.Filename):$($_.LineNumber) — $($_.Line.Trim())" }
} else {
    Write-Ok "No unreplaced placeholders."
}

Write-Host ""
Write-Host "Setup complete." -ForegroundColor Green
Write-Host ""
Write-Host "Next steps:"
Write-Host "  1. Make agents/skills available globally in Claude Code:"
Write-Host "       .\setup.ps1 -InstallJunctions           # skills: junctions; agents: per-file links"
Write-Host "       .\setup.ps1 -InstallJunctions -Preview  # preview without making changes"
Write-Host "     Agent links are SymbolicLinks (needs Developer Mode or admin); the script"
Write-Host "     falls back to HardLinks - re-run it after a git pull that changes agents."
Write-Host "  2. Regenerate the multi-tool agent mirrors (GitHub Copilot, OpenCode,"
Write-Host "     Continue, Aider) after adding or editing an agent, then commit:"
Write-Host "       .\install.ps1            (add -Personal for user-level Copilot install)"
Write-Host ""
