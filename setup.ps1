#Requires -Version 5.1
<#
.SYNOPSIS
    ResearchTools setup — detects this machine's paths and fills the gaps in the
    GLOBAL Claude Code configuration. Run once after cloning the repository.

.DESCRIPTION
    Auto-detects Git Bash, Node.js, and your user profile path, and optionally
    records the Obsidian vault path used by the vault integration.

    It writes NOTHING into the repository. A file a script generates is never a
    tracked file: the two templates carry THIS machine's absolute paths once
    substituted, so their destination is ~/.claude, not a path under the clone.
        .claude\settings.template.json  -> ~/.claude/settings.json
        CLAUDE.template.md              -> ~/.claude/CLAUDE.md
    Both templates stay the single hand-written sources, and both destinations are
    filled additively: what is missing is added, what the operator already has is
    left alone.

    Entry point for the three installers as well:
        -InstallJunctions  -> install-junctions.ps1 (Claude Code links in ~/.claude)
        -InstallTools      -> install.ps1 (Copilot/OpenCode/Continue/Aider mirrors;
                              -Personal adds the user-level Copilot install)
        -InstallDaemon     -> .claude\skills\obsidian-cli\scripts\vault-daemon-autostart.ps1
                              -Install (one shortcut in the Startup folder, so the
                              vault event daemon is running at login and raw drops in
                              ~/.claude/obsidian-outbox/raw are consumed instead of
                              piling up)
        -InstallPython     -> .venv-skills (always in the MAIN clone, even when run
                              from a worktree) plus the packages the repository's
                              skills import: paper2talk, recommendation-letter,
                              scopus and extract-statistic minus docling (torch is
                              too heavy), listed in scripts\lib\rt-python-requirements.json,
                              then pip-audit on each file. The base interpreter is
                              CHOSEN: -Python, or a PATH / py-launcher candidate that
                              belongs to the current profile and can really create a
                              virtual environment. Otherwise it refuses and names each
                              candidate with the reason. docling and geolocalisation
                              stay manual, documented in README.md
        -UpdateHooks       -> with the config generation: also REPLACE the command and
                              statusMessage of a hook entry of ~/.claude/settings.json
                              that the template declares and whose text changed. A text
                              edit, one backup per run, parsed before and after writing,
                              restored if the read-back fails. An entry it cannot match
                              with certainty is reported and left alone. Without the
                              switch such entries are only reported. Use -Preview first.
        -KeepHooks <names> -> with -UpdateHooks or -Update: leave these hook entries exactly as
                              they are on this machine (a deliberate local variant, for
                              example a changed folder-name guard). Names are the ones the
                              output prints, for example 'AUTO-SYNC CHECK', case ignored.
        -Update            -> the whole update of an existing installation in one command.
                              Asks first (domain profile, GitHub Copilot at user level,
                              and whether to run the offline suite first), then runs, in
                              order: the global configuration with -UpdateHooks, the
                              Claude Code links, install.ps1 -Profile <name> [-Personal],
                              the offline suite when asked, install-junctions.ps1 -Sync
                              and scripts\audit\check-deployment.ps1 (read-only). The
                              user-scope OBSIDIAN_VAULT is reused with no prompt. With
                              -NonInteractive the profile must come from -Profile.
                              -RunSuite answers the suite question. Use -Preview first:
                              links and sync run as WhatIf, install.ps1 and the suite
                              are skipped, nothing is written.
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
    .\setup.ps1 -InstallPython               # .venv-skills for the offline test suite and the skills
    .\setup.ps1 -InstallPython -Preview      # choose the interpreter, say what would install, write nothing
    .\setup.ps1 -InstallPython -Python "C:\Users\<you>\AppData\Local\Programs\Python\Python311\python.exe"
    .\setup.ps1 -Update -Preview             # the whole update, written nowhere: shows every step
    .\setup.ps1 -Update                      # asks the profile and Copilot, then updates everything
    .\setup.ps1 -Update -Profile engineering -Personal -RunSuite -NonInteractive -Force
    .\setup.ps1 -UpdateHooks -Preview        # list the hook entries it would update, write nothing
    .\setup.ps1 -UpdateHooks                 # update them (backup settings.json.bak-<date-time>)
    .\setup.ps1 -Update -KeepHooks 'AUTO-SYNC CHECK'   # update everything, keep that local hook as it is
    .\setup.ps1 -All -NonInteractive        # scripted bootstrap; refuses rather than assuming
    .\setup.ps1 -All -Personal               # config + junctions + tools + daemon in one pass
#>
param(
    [string]$ObsidianVault = "",
    [switch]$Force,
    [switch]$InstallJunctions,
    [switch]$InstallTools,
    [switch]$InstallDaemon,
    [switch]$InstallPython,
    [string]$Python = "",
    [switch]$UpdateHooks,
    [string[]]$KeepHooks = @(),
    [switch]$Update,
    # -Profile also works ($PROFILE is a PowerShell automatic variable, hence the alias),
    # the same spelling as install.ps1.
    [Alias('Profile')][string]$DomainProfile = "",
    [switch]$RunSuite,
    [switch]$All,
    [switch]$Personal,
    [switch]$Preview,
    [switch]$NonInteractive
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

# The Python-environment step, separate for the same reason. It needs rt-venv.ps1's
# main-clone lookup, so that file is loaded first.
. (Join-Path $WorkspaceRoot "scripts\lib\rt-venv.ps1")
. (Join-Path $WorkspaceRoot "scripts\lib\rt-python-env.ps1")

# The two GLOBAL writers, separate for the same reason: verify-setup-writes.ps1
# drives them against temp copies without running this script's prompts.
. (Join-Path $WorkspaceRoot "scripts\lib\rt-global-config.ps1")

# The pure half of -Update (profiles, answers, the ordered plan), for the same reason.
. (Join-Path $WorkspaceRoot "scripts\lib\rt-update.ps1")

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
    # Advisory: -Update runs this step BEFORE the sync, and the sync replaces a stale plain copy of an
    # agent that this step reports as a conflict. A conflict is then only a warning here, judged by the final
    # deployment check, which reads the state the update leaves. Without the switch, as before, it fails the run.
    param([switch]$Advisory)
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
    if ($Advisory -and $LASTEXITCODE -ne 0) {
        Write-Warn "install-junctions.ps1 reported conflicts (exit $LASTEXITCODE): the sync below refreshes stale copies, and the check at the end judges the result"
        return
    }
    Set-InstallerExit "install-junctions.ps1" $LASTEXITCODE
}

function Invoke-ToolsScript {
    # ProfileName: given by -Update, which has already asked and validated it. Empty keeps
    # the old behaviour, where install.ps1 asks for the profile itself.
    param([string]$ProfileName = "")
    $toolsScript = Join-Path $WorkspaceRoot "install.ps1"
    if (-not (Test-Path $toolsScript)) {
        Write-Err "install.ps1 not found at: $toolsScript"
        exit 1
    }
    $global:LASTEXITCODE = 0
    if ($ProfileName) {
        if ($Personal) { & $toolsScript -Profile $ProfileName -Personal } else { & $toolsScript -Profile $ProfileName }
    } else {
        if ($Personal) { & $toolsScript -Personal } else { & $toolsScript }
    }
    Set-InstallerExit "install.ps1" $LASTEXITCODE
}

function Invoke-SyncScript {
    # install-junctions.ps1 -Sync copies into ~/.claude the files a green offline-suite run
    # has proven, and HOLDS the rest. It says which; this wrapper only records the exit code.
    $junctionsScript = Join-Path $WorkspaceRoot "install-junctions.ps1"
    if (-not (Test-Path $junctionsScript)) {
        Write-Err "install-junctions.ps1 not found at: $junctionsScript"
        exit 1
    }
    $global:LASTEXITCODE = 0
    if ($Preview) { & $junctionsScript -Sync -WhatIf } else { & $junctionsScript -Sync }
    Set-InstallerExit "install-junctions.ps1 -Sync" $LASTEXITCODE
}

function Invoke-SuiteScript {
    # run-offline-tests.ps1 refuses, naming every path it looked at, when .venv-skills is
    # absent. Its failure is recorded and the update goes on, since the sync that follows
    # then reports the files it holds.
    $suiteScript = Join-Path $WorkspaceRoot "scripts\test\run-offline-tests.ps1"
    if (-not (Test-Path $suiteScript)) {
        Write-Err "run-offline-tests.ps1 not found at: $suiteScript"
        exit 1
    }
    $global:LASTEXITCODE = 0
    & $suiteScript
    Set-InstallerExit "run-offline-tests.ps1" $LASTEXITCODE
}

function Invoke-CheckScript {
    # Read-only: it only reports whether ~/.claude matches the repository.
    $checkScript = Join-Path $WorkspaceRoot "scripts\audit\check-deployment.ps1"
    if (-not (Test-Path $checkScript)) {
        Write-Err "check-deployment.ps1 not found at: $checkScript"
        exit 1
    }
    $global:LASTEXITCODE = 0
    & $checkScript
    if ($Preview) {
        # Nothing was fixed in a preview, so what the check lists is what the real update would do.
        Write-Host "  [--]  preview: the problems above are what the real update would fix" -ForegroundColor DarkGray
        return
    }
    Set-InstallerExit "check-deployment.ps1" $LASTEXITCODE
}

function Read-RtAnswer {
    # U13: with -NonInteractive a prompt is a refusal, not an assumption. Measured
    # defect: with no console attached Read-Host returns empty and the run proceeded
    # anyway, so a scripted bootstrap silently took every default. Refusing names the
    # switch that would have supplied the answer. Exit 2 is refusal by design (R12).
    param(
        [Parameter(Mandatory = $true)][string]$Prompt,
        [Parameter(Mandatory = $true)][string]$Switch
    )
    if ($NonInteractive) {
        Write-Err "-NonInteractive: this run needs an answer for '$Prompt'."
        Write-Host "        Supply it with $Switch, or drop -NonInteractive." -ForegroundColor Yellow
        exit 2
    }
    return Read-Host $Prompt
}

function Invoke-PythonEnvironment {
    $code = Install-RtPythonEnv -RepoRoot $WorkspaceRoot -Preview:$Preview -Python $Python
    Set-InstallerExit "python environment (.venv-skills)" $code
}

function Invoke-VaultEnvironment {
    # U8: nothing in this repository used to set OBSIDIAN_VAULT, yet the guard hook,
    # the flush hook, the daemon, the drill and the autostart script all read it, so
    # setup reported success and every one of them then refused. Add-only: a value
    # already stored is reported and kept unless -Force confirms a repoint.
    param([AllowEmptyString()][string]$Vault = "")

    if ([string]::IsNullOrWhiteSpace($Vault)) { return }

    $current = [Environment]::GetEnvironmentVariable("OBSIDIAN_VAULT", "User")
    if ($null -eq $current) { $current = "" }

    $decision = Resolve-RtVaultEnvironmentAction `
        -Vault $Vault `
        -CurrentUserScope $current `
        -PathExists (Test-Path -LiteralPath $Vault -PathType Container) `
        -Confirmed:$Force

    $null = Set-RtVaultEnvironment -Decision $decision -Vault $Vault -Preview:$Preview
}

function Invoke-DaemonScript {
    # Read at call time rather than at parse time: -All calls this after the vault
    # prompt, so $ObsidianVault may have been filled in by then.
    $userScope = [Environment]::GetEnvironmentVariable("OBSIDIAN_VAULT", "User")
    if ($null -eq $userScope) { $userScope = "" }
    $vault = Get-RtDaemonVault -ObsidianVault $ObsidianVault -UserScopeVault $userScope

    # Offer the USER-scope variable before installing the Startup entry, then re-read
    # it: without this the warning below fires on a machine this very run just fixed.
    Invoke-VaultEnvironment -Vault $vault
    $userScope = [Environment]::GetEnvironmentVariable("OBSIDIAN_VAULT", "User")
    if ($null -eq $userScope) { $userScope = "" }
    $code = Install-RtVaultDaemon `
        -RepoRoot $WorkspaceRoot `
        -Vault $vault `
        -UserScopeSet:(-not [string]::IsNullOrWhiteSpace($userScope)) `
        -Preview:$Preview
    Set-InstallerExit "vault-daemon-autostart.ps1 -Install" $code
}

# --- -Update: every question first, then the steps run without another prompt -----------

$script:UpdatePlan = @()
if ($Update) { $UpdateHooks = $true }   # -Update implies the hook update
if ($Update) {
    if ($InstallJunctions -or $InstallTools -or $InstallDaemon -or $InstallPython -or $All) {
        Write-Warn "-Update runs its own steps; the -Install* and -All switches are ignored."
        $InstallJunctions = $false; $InstallTools = $false; $InstallDaemon = $false
        $InstallPython = $false; $All = $false
    }

    Write-Header "Update: questions"
    $availableProfiles = Get-RtProfileNames -ProfilesDir (Join-Path $WorkspaceRoot "profiles")
    $currentProfile = Get-RtActiveProfile -ClaudeMdPath (Join-Path $WorkspaceRoot ".claude\CLAUDE.md")
    $profileAnswer = $DomainProfile
    if (-not $profileAnswer) {
        $profileAnswer = Read-RtAnswer `
            "  Domain profile ($($availableProfiles -join ', '); Enter keeps '$currentProfile')" "-Profile <name>"
    }
    $chosenProfile = Resolve-RtUpdateProfile -Answer $profileAnswer -Available $availableProfiles -Current $currentProfile
    if ($null -eq $chosenProfile) {
        Write-Err "Unknown domain profile '$profileAnswer'. Valid profiles: $($availableProfiles -join ', ')"
        exit 2
    }
    Write-Ok "Profile: $chosenProfile"

    if (-not $Personal -and -not $NonInteractive) {
        $copilotAnswer = Read-RtAnswer "  Also install GitHub Copilot at user level? [y/N]" "-Personal"
        if ($copilotAnswer -match '^[YyOo]') { $Personal = $true }
    }
    Write-Ok "GitHub Copilot at user level: $(if ($Personal) { 'yes' } else { 'no' })"

    if (-not $RunSuite -and -not $NonInteractive -and -not $Preview) {
        $suiteAnswer = Read-RtAnswer `
            "  Run the offline test suite first (about 15 minutes), so the sync can copy changed hooks and agents? [y/N]" "-RunSuite"
        if ($suiteAnswer -match '^[YyOo]') { $RunSuite = $true }
    }
    Write-Ok "Offline suite before the sync: $(if ($RunSuite -and -not $Preview) { 'yes' } elseif ($Preview) { 'not in preview' } else { 'no' })"

    $script:UpdatePlan = Resolve-RtUpdatePlan -Profile $chosenProfile -Personal ([bool]$Personal) `
        -RunSuite ([bool]$RunSuite) -Preview ([bool]$Preview)
    Write-Header "Update: the steps"
    $stepNumber = 0
    foreach ($step in $script:UpdatePlan) {
        $stepNumber++
        $note = if ($step.Skipped) { "  (skipped: $($step.Reason))" } elseif ($step.WhatIf) { "  (WhatIf)" } else { "" }
        Write-Host "  $stepNumber. $($step.Label)$note"
    }
    $script:UpdateProfile = $chosenProfile
}

if ($InstallPython -and -not $All) {
    Write-Header "Python environment for the offline test suite"
    Invoke-PythonEnvironment
    if ($InstallJunctions) { Invoke-JunctionsScript }
    if ($InstallTools)     { Invoke-ToolsScript }
    if ($InstallDaemon)    { Invoke-DaemonScript }
    exit $script:InstallerExit
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
    $gitBashPath = Read-RtAnswer "  Enter full path to bash.exe (or press Enter to skip)" "bash.exe on PATH"
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
    $nodePath = Read-RtAnswer "  Enter full path to node.exe (or press Enter to skip)" "node.exe on PATH"
    if (-not $nodePath) { $nodePath = "C:\\Program Files\\nodejs\\node.exe" }
}

# ─── Detect Obsidian vault ────────────────────────────────────────────────────

Write-Header "Obsidian vault (optional)"
if (-not $ObsidianVault -and $Update) {
    # An update asks nothing it can read: the vault already stored at user scope is reused.
    $storedVault = [Environment]::GetEnvironmentVariable("OBSIDIAN_VAULT", "User")
    if ($storedVault) { $ObsidianVault = $storedVault }
}
if (-not $ObsidianVault -and -not $Update) {
    $ObsidianVault = Read-RtAnswer "  Vault path (press Enter to skip Obsidian integration)" "-ObsidianVault <path>"
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

if (-not $Force -and -not $Update) {
    # -Update already asked everything it needs, and showed its steps, so it does not ask again.
    $confirm = Read-RtAnswer "Proceed? [Y/n]" "-Force"
    if ($confirm -match '^[Nn]') {
        Write-Host "Aborted." -ForegroundColor Yellow
        exit 0
    }
}

# Substitution, escaping and the two global writers live in
# scripts\lib\rt-global-config.ps1, dot-sourced above. There is deliberately no
# second copy here: two substitution engines mean two escaping rules, which is
# how the same value came to be spelled two different ways in one file.

Write-Header "Global Claude Code configuration"

$homeClaude = Join-Path $env:USERPROFILE ".claude"
Write-Host "  target : $homeClaude"
Write-Host "  Nothing is written into the repository, and nothing you already have in a"
Write-Host "  global file is removed, replaced or reformatted. Only what is missing is added."
Write-Host ""

# Markdown: values go in as they are. JSON: backslashes and quotes escaped once,
# by the one function that owns that rule.
$claudeVars = @{
    OBSIDIAN_VAULT = $ObsidianVault
    OBSIDIAN_EXE   = $obsidianExe
    WORKSPACE_ROOT = $WorkspaceRoot
    USERPROFILE    = $env:USERPROFILE
}
$settingsVars = @{
    WORKSPACE_ROOT = ConvertTo-RtJsonScalar $WorkspaceRoot
    USERPROFILE    = ConvertTo-RtJsonScalar $env:USERPROFILE
    GIT_BASH_PATH  = ConvertTo-RtJsonScalar $gitBashPath
    NODE_PATH      = ConvertTo-RtJsonScalar $nodePath
}

$claudeResult = Install-RtGlobalClaudeMd `
    -TemplatePath (Join-Path $WorkspaceRoot "CLAUDE.template.md") `
    -TargetPath (Join-Path $homeClaude "CLAUDE.md") `
    -Vars $claudeVars `
    -Preview:$Preview

switch ($claudeResult.Action) {
    "created"        { Write-Ok   "CLAUDE.md: $($claudeResult.Message)" }
    "kept"           { Write-Ok   "CLAUDE.md: $($claudeResult.Message)" }
    "preview-create" { Write-Host "  [--]  CLAUDE.md: $($claudeResult.Message)" -ForegroundColor DarkGray }
    default          { Write-Err  "CLAUDE.md: $($claudeResult.Message)" }
}
if ($claudeResult.Placeholders.Count -gt 0) {
    Write-Warn "unreplaced placeholder(s): $($claudeResult.Placeholders -join ', ')"
}

# Hooks BEFORE the settings merge, deliberately: the merge is what DECLARES them, and a hook
# declared with no script behind it makes the interpreter exit non-zero, which refuses every
# tool in that hook's matcher. Script first, declaration second, so that ordering can never
# produce the 2026-08-27 state even transiently.
$hooksResult = Install-RtGlobalHooks `
    -SourceDir (Join-Path $WorkspaceRoot ".claude\hooks") `
    -TargetDir (Join-Path $homeClaude "hooks") `
    -Preview:$Preview

switch ($hooksResult.Action) {
    "installed" { Write-Ok   "hooks: $($hooksResult.Message)" }
    "noop"      { Write-Ok   "hooks: $($hooksResult.Message)" }
    "preview"   { Write-Host "  [--]  hooks: $($hooksResult.Message)" -ForegroundColor DarkGray }
    default     { Write-Err  "hooks: $($hooksResult.Message)" }
}
foreach ($name in $hooksResult.Installed) {
    Write-Host "        + hooks\$name"
}
if ($hooksResult.Differing.Count -gt 0) {
    Write-Warn "hook(s) present but differing from the repository, left as they are: $($hooksResult.Differing -join ', ')"
    Write-Warn "  run install-junctions.ps1 -Sync to update them (gated on the offline suite being green)"
}

$settingsResult = Merge-RtGlobalSettings `
    -TemplatePath (Join-Path $WorkspaceRoot ".claude\settings.template.json") `
    -TargetPath (Join-Path $homeClaude "settings.json") `
    -Vars $settingsVars `
    -UpdateChanged:$UpdateHooks `
    -KeepHooks $KeepHooks `
    -BackupStamp (Get-Date -Format "yyyy-MM-dd-HHmm") `
    -Preview:$Preview

switch ($settingsResult.Action) {
    "created"        { Write-Ok   "settings.json: $($settingsResult.Message)" }
    "merged"         { Write-Ok   "settings.json: $($settingsResult.Message)" }
    "updated"        { Write-Ok   "settings.json: $($settingsResult.Message)" }
    "unchanged"      { Write-Ok   "settings.json: $($settingsResult.Message)" }
    "preview-create" { Write-Host "  [--]  settings.json: $($settingsResult.Message)" -ForegroundColor DarkGray }
    "preview-merge"  { Write-Host "  [--]  settings.json: $($settingsResult.Message)" -ForegroundColor DarkGray }
    default          { Write-Err  "settings.json: $($settingsResult.Message)" }
}
foreach ($entry in $settingsResult.Added) {
    Write-Host "        + $($entry.Event): $($entry.Token)"
}
foreach ($entry in $settingsResult.Updated) {
    Write-Host "        ~ $($entry.Event): $($entry.Token) (command and statusMessage replaced)"
}
foreach ($entry in $settingsResult.Kept) {
    Write-Host "        = $($entry.Event): $($entry.Token) (kept as it is, as asked with -KeepHooks)"
}
if (@($settingsResult.Updated).Count -gt 0 -and $Preview) {
    Write-Warn "an entry above that is a deliberate local variant of yours is replaced too: add -KeepHooks '<name>' to leave it as it is"
}
if (-not $UpdateHooks -and @($settingsResult.Differs).Count -gt 0) {
    Write-Warn "$(@($settingsResult.Differs).Count) hook entr(y/ies) of settings.json differ from the template: $((@($settingsResult.Differs) | ForEach-Object { $_.Token }) -join ', ')"
    Write-Warn "  run .\setup.ps1 -UpdateHooks -Preview to see them, then .\setup.ps1 -UpdateHooks (add -KeepHooks '<name>' to leave one as it is)"
}
foreach ($entry in $settingsResult.Skipped) {
    Write-Warn "not added ($($entry.Event): $($entry.Token)) - $($entry.Reason)"
}

Write-Host ""
Write-Host "Setup complete." -ForegroundColor Green

if ($Update) {
    # The first step (the configuration above) is done. The others run in the plan's order,
    # a failure is recorded and does not stop the later, read-only steps.
    $stepNumber = 1
    foreach ($step in $script:UpdatePlan) {
        if ($step.Id -eq "config") { continue }
        $stepNumber++
        Write-Header "Update $stepNumber of $(@($script:UpdatePlan).Count): $($step.Label)"
        if ($step.Skipped) { Write-Host "  [--]  skipped: $($step.Reason)" -ForegroundColor DarkGray; continue }
        switch ($step.Id) {
            "junctions" { Invoke-JunctionsScript -Advisory }
            "tools"     { Invoke-ToolsScript -ProfileName $step.Profile }
            "suite"     { Invoke-SuiteScript }
            "sync"      { Invoke-SyncScript }
            "check"     { Invoke-CheckScript }
        }
    }
    Write-Host ""
    if ($script:InstallerExit -ne 0) {
        Write-Err "The update finished with a failure (worst exit code $script:InstallerExit): read the lines above."
    } else {
        Write-Host "Update steps done." -ForegroundColor Green
    }
    Write-Host ""
    Write-Host "Still to do by hand:"
    Write-Host "  - Close and reopen VS Code and Claude Code: hooks and rules are read at session start."
    Write-Host "    The [HOOKS ACTIVE] line at the start of the session must say 0 missing."
    Write-Host "  - If the sync said some files were held, the offline suite was not green for them:"
    Write-Host "    run  .\setup.ps1 -Update -RunSuite  (about 15 minutes), or fix the failing suite first."
    Write-Host "  - install.ps1 -Profile records the profile in .claude\CLAUDE.md, a tracked file:"
    Write-Host "    git status will show it. Keep it or restore it with git, as you prefer."
    Write-Host ""
    exit $script:InstallerExit
}

if ($All) {
    Write-Header "Claude Code global links (install-junctions.ps1)"
    Invoke-JunctionsScript
    Write-Header "Multi-tool mirrors (install.ps1)"
    Invoke-ToolsScript
    Write-Header "Vault event daemon at login"
    Invoke-DaemonScript
    Write-Header "Python environment for the offline test suite"
    Invoke-PythonEnvironment
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
    Write-Host "  4. Create the Python environment the offline test suite resolves first,"
    Write-Host "     so run-offline-tests.ps1 reports PASSED instead of NOT RUN:"
    Write-Host "       .\setup.ps1 -InstallPython           # .venv-skills + the suite packages"
    Write-Host "     The optional skill dependencies (scopus, extract-statistic, geolocalisation)"
    Write-Host "     stay manual - see the Prerequisites table in README.md."
    Write-Host "  Or run everything in one pass next time: .\setup.ps1 -All -Personal"
    Write-Host ""
}
