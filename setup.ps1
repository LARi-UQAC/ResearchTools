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

    Entry point for the three installers as well:
        -InstallJunctions  -> install-junctions.ps1 (Claude Code links in ~/.claude)
        -InstallTools      -> install.ps1 (Copilot/OpenCode/Continue/Aider mirrors;
                              -Personal adds the user-level Copilot install)
        -InstallDaemon     -> .claude\skills\obsidian-cli\scripts\vault-daemon-autostart.ps1
                              -Install (one shortcut in the Startup folder, so the
                              vault event daemon is running at login and raw drops in
                              ~/.claude/obsidian-outbox/raw are consumed instead of
                              piling up)
        -All               -> config generation + junctions + tools, plus the daemon
                              WHEN a vault is configured; with no vault it is skipped
                              with a stated reason, since a login daemon with no vault
                              starts, finds nothing and exits invisibly

.EXAMPLE
    .\setup.ps1
    .\setup.ps1 -ObsidianVault "D:\MyVault" -Force
    .\setup.ps1 -InstallJunctions            # Claude Code global links only
    .\setup.ps1 -InstallTools -Personal      # multi-tool mirrors only (Copilot/OpenCode/...)
    .\setup.ps1 -InstallDaemon               # vault daemon at login only
    .\setup.ps1 -InstallDaemon -Preview      # say what it would install, install nothing
    .\setup.ps1 -All -Personal               # config + junctions + tools + daemon in one pass
#>
param(
    [string]$ObsidianVault = "",
    [switch]$Force,
    [switch]$InstallJunctions,
    [switch]$InstallTools,
    [switch]$InstallDaemon,
    [switch]$All,
    [switch]$Personal,
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

# The daemon decision and its delegation live in their own file so a test can load
# them without executing this script's interactive flow. Same reason rt-sync.ps1 is
# separate from install-junctions.ps1.
. (Join-Path $WorkspaceRoot "scripts\lib\rt-daemon-install.ps1")

Write-Header "ResearchTools — Setup"
Write-Host "  Workspace : $WorkspaceRoot"
Write-Host "  User      : $env:USERNAME"

# ─── InstallJunctions mode ────────────────────────────────────────────────────

# Worst exit code seen from a called installer. install-junctions.ps1 returns 1 when a real
# directory or a real file in ~/.claude shadows this repository, which is a genuine failure:
# the repository version is NOT loaded. This wrapper used to end its installer branches with
# a hardcoded "exit 0", so that conflict was invisible to anyone who reached the installer
# through setup.ps1 instead of running it directly. Every branch below now exits with the
# worst code any installer returned.
$script:InstallerExit = 0

# Recorded in a script-scoped variable rather than returned by the Invoke-* functions: the
# called installer writes through Write-Host, but any stray object it left on the pipeline
# would be indistinguishable from a return value and would silently become the "exit code".
function Set-InstallerExit([string]$label, [int]$code) {
    if ($code -ne 0) {
        Write-Err "$label exited with code $code"
        if ($code -gt $script:InstallerExit) { $script:InstallerExit = $code }
    }
}

function Invoke-JunctionsScript {
    $junctionsScript = Join-Path $WorkspaceRoot "install-junctions.ps1"
    if (-not (Test-Path $junctionsScript)) {
        Write-Err "install-junctions.ps1 not found at: $junctionsScript"
        exit 1
    }
    # Pre-set it: a script that falls off its end without an explicit "exit" leaves
    # $LASTEXITCODE at whatever the previous command set, and Set-StrictMode makes an
    # undefined $LASTEXITCODE a terminating error on the very first read.
    # The two calls stay written out rather than splatted from an array: array splatting
    # passes "-WhatIf" as a positional VALUE, not as a switch (measured here), so a
    # forwarded flag would be silently dropped.
    $global:LASTEXITCODE = 0
    if ($Preview) { & $junctionsScript -WhatIf } else { & $junctionsScript }
    Set-InstallerExit "install-junctions.ps1" $LASTEXITCODE
}

function Invoke-ToolsScript {
    $toolsScript = Join-Path $WorkspaceRoot "install.ps1"
    if (-not (Test-Path $toolsScript)) {
        Write-Err "install.ps1 not found at: $toolsScript"
        exit 1
    }
    $global:LASTEXITCODE = 0
    if ($Personal) { & $toolsScript -Personal } else { & $toolsScript }
    Set-InstallerExit "install.ps1" $LASTEXITCODE
}

function Invoke-DaemonScript {
    # Read at call time rather than at parse time: -All calls this after the vault
    # prompt, so $ObsidianVault may have been filled in by then.
    $userScope = [Environment]::GetEnvironmentVariable("OBSIDIAN_VAULT", "User")
    if ($null -eq $userScope) { $userScope = "" }
    $vault = Get-RtDaemonVault -ObsidianVault $ObsidianVault -UserScopeVault $userScope
    $code = Install-RtVaultDaemon `
        -RepoRoot $WorkspaceRoot `
        -Vault $vault `
        -UserScopeSet:(-not [string]::IsNullOrWhiteSpace($userScope)) `
        -Preview:$Preview
    Set-InstallerExit "vault-daemon-autostart.ps1 -Install" $code
}

if ($InstallJunctions -and -not $All) {
    Invoke-JunctionsScript
    if ($InstallTools)  { Invoke-ToolsScript }
    if ($InstallDaemon) { Invoke-DaemonScript }
    exit $script:InstallerExit
}

if ($InstallTools -and -not $All) {
    Invoke-ToolsScript
    if ($InstallDaemon) { Invoke-DaemonScript }
    exit $script:InstallerExit
}

if ($InstallDaemon -and -not $All) {
    Write-Header "Vault event daemon at login"
    Invoke-DaemonScript
    exit $script:InstallerExit
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

if ($All) {
    Write-Header "Claude Code global links (install-junctions.ps1)"
    Invoke-JunctionsScript
    Write-Header "Multi-tool mirrors (install.ps1)"
    Invoke-ToolsScript
    Write-Header "Vault event daemon at login"
    Invoke-DaemonScript
    Write-Host ""
    if ($script:InstallerExit -ne 0) {
        # Both installers still ran: a junction conflict must not stop the mirrors from
        # being regenerated. Only the final verdict changes, and it says so out loud.
        Write-Err "One or more install steps failed (worst exit code $script:InstallerExit)."
        Write-Host ""
        exit $script:InstallerExit
    }
    Write-Host "All install steps done." -ForegroundColor Green
    Write-Host ""
} else {
    Write-Host ""
    Write-Host "Next steps:"
    Write-Host "  1. Make agents/skills available globally in Claude Code:"
    Write-Host "       .\setup.ps1 -InstallJunctions           # skills: junctions; agents: per-file links"
    Write-Host "       .\setup.ps1 -InstallJunctions -Preview  # preview without making changes"
    Write-Host "     Agent links are SymbolicLinks (needs Developer Mode or admin); the script"
    Write-Host "     falls back to HardLinks - re-run it after a git pull that changes agents."
    Write-Host "  2. Regenerate the multi-tool mirrors (GitHub Copilot, OpenCode, Continue,"
    Write-Host "     Aider) after adding or editing an agent/command/rule, then commit:"
    Write-Host "       .\setup.ps1 -InstallTools    (add -Personal for user-level Copilot)"
    Write-Host "  3. Have the vault event daemon running at login, so raw drops in"
    Write-Host "     ~/.claude/obsidian-outbox/raw are filed instead of piling up:"
    Write-Host "       .\setup.ps1 -InstallDaemon   (needs OBSIDIAN_VAULT at user scope)"
    Write-Host "  Or run everything in one pass next time: .\setup.ps1 -All -Personal"
    Write-Host ""
}
