#Requires -Version 5.1
<#
.SYNOPSIS
    Offline check of setup.ps1 -InstallDaemon: the delegation, the skip, the refusals.

.DESCRIPTION
    The autostart script's own refusals (no vault configured, a vault that does not
    exist) are already proven by running it. What was untested is the layer setup.ps1
    adds on top: which vault a login-started daemon would actually see, when -All
    installs the Startup entry and when it deliberately does not, and that the
    delegation reaches vault-daemon-autostart.ps1 at all.

    It loads scripts\lib\rt-daemon-install.ps1 directly. That separation is why the
    file exists: dot-sourcing setup.ps1 would run its whole interactive flow -
    prompts, template substitution, both installers - just by being tested.

.SAFETY
    The delegation cases point Install-RtVaultDaemon at a throwaway repository root
    under $env:TEMP whose vault-daemon-autostart.ps1 is a stub that records its
    arguments and exits. The real autostart script is never called, so no shortcut
    can be created; the last two checks assert that against the professor's actual
    Startup folder, listing it before and after.

.NOTES
    Not part of the green-stamp gate, which covers Python suites under .claude\ only.
    Same family as scripts\test\verify-sync-writes.ps1.

.EXAMPLE
    .\scripts\test\verify-daemon-install.ps1
#>

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$Fake     = Join-Path $env:TEMP "rt-daemon-verify-$PID"
$failures = 0

function Check([string]$name, [bool]$ok) {
    if ($ok) { Write-Host "  PASS  $name" -ForegroundColor DarkGray }
    else     { Write-Host "  FAIL  $name" -ForegroundColor Red; $script:failures++ }
}

Write-Host ""
Write-Host "=== setup.ps1 -InstallDaemon ===" -ForegroundColor Cyan

# The real Startup folder, recorded BEFORE anything runs. Two incidents in this
# repository's history came from a test that reached the real target it was meant
# to be protecting, so the precondition is captured first and asserted last.
$Startup      = [Environment]::GetFolderPath("Startup")
$RealShortcut = Join-Path $Startup "ResearchTools vault daemon.lnk"
$startupBefore = @(Get-ChildItem $Startup -Force -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Name) -join "|"
$shortcutBefore = Test-Path $RealShortcut

. (Join-Path $RepoRoot "scripts\lib\rt-daemon-install.ps1")

# ---------------------------------------------------------------- vault choice ---
# User scope wins: the Startup shortcut passes no -Vault, so the login daemon reads
# the user environment block and nothing else.
Check "no vault anywhere resolves to empty"      ((Get-RtDaemonVault -ObsidianVault "" -UserScopeVault "") -eq "")
Check "user scope wins over the argument"        ((Get-RtDaemonVault -ObsidianVault "D:\Arg" -UserScopeVault "D:\User") -eq "D:\User")
Check "argument used when user scope is unset"   ((Get-RtDaemonVault -ObsidianVault "D:\Arg" -UserScopeVault "") -eq "D:\Arg")
Check "NOT_CONFIGURED is not a vault"            ((Get-RtDaemonVault -ObsidianVault "NOT_CONFIGURED" -UserScopeVault "") -eq "")
Check "whitespace is not a vault"                ((Get-RtDaemonVault -ObsidianVault "   " -UserScopeVault "  ") -eq "")

# ------------------------------------------------------------------- the stub ---
$stubDir    = Join-Path $Fake ".claude\skills\obsidian-cli\scripts"
$markerFile = Join-Path $Fake "invoked.txt"
New-Item -ItemType Directory -Path $stubDir -Force | Out-Null

$stubTemplate = @'
param([switch]$Install, [string]$Vault = "")
Set-Content -Path "__MARKER__" -Value "Install=$Install Vault=$Vault" -Encoding utf8
exit __CODE__
'@

function Set-Stub([int]$code) {
    if (Test-Path $markerFile) { Remove-Item $markerFile -Force }
    $body = $stubTemplate.Replace("__MARKER__", $markerFile).Replace("__CODE__", "$code")
    Set-Content -Path (Join-Path $stubDir "vault-daemon-autostart.ps1") -Value $body -Encoding utf8
}

# ---------------------------------------------------------- skip, not failure ---
# A login daemon with no vault would start, find nothing and exit invisibly. It is
# refused out loud, and -All must carry on rather than report a failed install.
Set-Stub 0
$code = Install-RtVaultDaemon -RepoRoot $Fake -Vault ""
Check "no vault: exit 0 (a skip, not a failure)" ($code -eq 0)
Check "no vault: autostart never invoked"        (-not (Test-Path $markerFile))

# ------------------------------------------------------------------ delegation ---
Set-Stub 0
$code = Install-RtVaultDaemon -RepoRoot $Fake -Vault "D:\MyVault" -UserScopeSet
Check "vault set: exit 0"                        ($code -eq 0)
Check "vault set: autostart invoked"             (Test-Path $markerFile)
if (Test-Path $markerFile) {
    $recorded = (Get-Content $markerFile -Raw).Trim()
    Check "invoked with -Install"                ($recorded -match "Install=True")
    Check "the vault is forwarded"               ($recorded -match ([regex]::Escape("Vault=D:\MyVault")))
}

# ---------------------------------------------------------------------- R16 ----
# -Preview says what it would do and touches nothing.
Set-Stub 0
$code = Install-RtVaultDaemon -RepoRoot $Fake -Vault "D:\MyVault" -UserScopeSet -Preview
Check "preview: exit 0"                          ($code -eq 0)
Check "preview: autostart never invoked"         (-not (Test-Path $markerFile))

# ------------------------------------------------------------------ refusals ---
# A non-zero code from the autostart script must reach setup.ps1's worst-exit-code
# accounting, not be swallowed into a green run.
Set-Stub 3
$code = Install-RtVaultDaemon -RepoRoot $Fake -Vault "D:\MyVault" -UserScopeSet
Check "autostart failure propagates (3)"         ($code -eq 3)

$empty = Join-Path $Fake "no-such-repo"
New-Item -ItemType Directory -Path $empty -Force | Out-Null
$code = Install-RtVaultDaemon -RepoRoot $empty -Vault "D:\MyVault" -UserScopeSet
Check "missing autostart script: exit 1"         ($code -eq 1)

# The warning path: a vault known only as an argument cannot be seen at login. It
# still installs (the operator asked for it), but it must say so.
Set-Stub 0
$warned = Install-RtVaultDaemon -RepoRoot $Fake -Vault "D:\MyVault" 6>&1 | Out-String
Check "user scope unset: warns about USER scope" ($warned -match "USER scope")
Check "user scope unset: still installs"         (Test-Path $markerFile)

# ------------------------------------------------------- setup.ps1 wiring ------
# Static, because running setup.ps1 means prompts and template writes. These guard
# the four points where the switch could be silently dropped.
$setup = Get-Content (Join-Path $RepoRoot "setup.ps1") -Raw -Encoding UTF8
Check "setup.ps1 declares -InstallDaemon"        ($setup -match '\[switch\]\$InstallDaemon')
Check "setup.ps1 loads rt-daemon-install.ps1"    ($setup -match ([regex]::Escape("rt-daemon-install.ps1")))
Check "setup.ps1 documents the switch"           ($setup -match ([regex]::Escape(".\setup.ps1 -InstallDaemon")))
$allBlock = $setup.Substring($setup.IndexOf('if ($All) {'))
Check "-All calls the daemon step"               ($allBlock -match "Invoke-DaemonScript")

# ------------------------------------------------- the professor's own profile ---
$startupAfter = @(Get-ChildItem $Startup -Force -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Name) -join "|"
Check "real Startup folder unchanged"            ($startupAfter -eq $startupBefore)
Check "no real Startup shortcut created"         ((Test-Path $RealShortcut) -eq $shortcutBefore)

Remove-Item $Fake -Recurse -Force -ErrorAction SilentlyContinue

Write-Host ""
if ($failures -eq 0) {
    Write-Host "  All checks passed." -ForegroundColor Green
    Write-Host ""
    exit 0
}
Write-Host "  $failures check(s) failed." -ForegroundColor Red
Write-Host ""
exit 1
