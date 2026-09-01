<#
.SYNOPSIS
    Start the vault event daemon at Windows login, and manage that arrangement.

.DESCRIPTION
    The daemon watches ~/.claude/obsidian-outbox/raw and files what lands there.
    Nothing starts it, so drops accumulate in a folder nobody opens - which is
    the gap the outbox flush hook now reports at SessionStart. This script is
    the other half of that answer: have it running already.

    Started from the Startup folder there is no console to read, so everything
    the daemon prints goes to a log beside the outbox, rotated once at the size
    in daemon-config.json. A hidden daemon with no log is a daemon whose death
    nobody notices, which would be worse than not running it at all.

    Two facts make this safe to run at login rather than by hand.

    The singleton lock admits ONE daemon per machine, so a second login, a
    manual start, or a double-click cannot produce two daemons classifying the
    same drop twice. This script asks vault_lock whether the current holder is
    alive rather than testing for the lock file, because a daemon killed with
    its window leaves the file behind and that is not a running daemon.

    And the local model daemon is usually NOT up yet at login. That is fine:
    the poll loop catches the bridge error, says so, and keeps watching, so the
    first drop after Ollama comes up is filed normally. It does mean the log's
    first lines are often bridge errors, and they are not a fault.

.PARAMETER Install
    Create a shortcut in the current user's Startup folder. Nothing else on the
    machine is touched, and -Uninstall removes exactly that shortcut.

.PARAMETER Uninstall
    Remove the Startup shortcut. The daemon already running is left alone.

.PARAMETER Status
    Report whether a daemon holds the lock, where the log is, how big it is,
    and whether the Startup shortcut exists. Changes nothing.

.PARAMETER Vault
    Vault root, defaulting to OBSIDIAN_VAULT. There is no built-in path (R1):
    a vault that is not configured is an explicit stop, because at login a
    guessed default would silently file notes into the wrong place.

.EXAMPLE
    .\vault-daemon-autostart.ps1 -Status
    .\vault-daemon-autostart.ps1 -Install
    .\vault-daemon-autostart.ps1            # start it now, in the background

.NOTES
    OBSIDIAN_VAULT must be set at USER scope, not just in a terminal: a process
    launched from the Startup folder inherits the user environment block and
    nothing a shell exported.
#>
[CmdletBinding()]
param(
    [switch]$Install,
    [switch]$Uninstall,
    [switch]$Status,
    [string]$Vault = $env:OBSIDIAN_VAULT
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$Scripts   = $PSScriptRoot
$RepoRoot  = Split-Path (Split-Path (Split-Path (Split-Path $Scripts -Parent) -Parent) -Parent) -Parent
$Daemon    = Join-Path $Scripts "vault_daemon.py"
$Log       = Join-Path $env:USERPROFILE ".claude\vault-daemon.log"
$Startup   = [Environment]::GetFolderPath("Startup")
$Shortcut  = Join-Path $Startup "ResearchTools vault daemon.lnk"
$Launcher  = Join-Path $Scripts "vault-daemon-autostart.bat"

function Say([string]$t, [string]$c = "Gray") { Write-Host $t -ForegroundColor $c }
function Die([string]$t) { Write-Host "  STOP  $t" -ForegroundColor Red; exit 1 }

$Python = Join-Path $RepoRoot ".venv-skills\Scripts\python.exe"
if (-not (Test-Path $Python)) { $Python = "python" }

# Asked of vault_lock, never inferred from the file existing.
$LiveCheck = @"
import sys
sys.path.insert(0, r'$Scripts')
import outbox_io, vault_lock
from pathlib import Path
cfg = outbox_io.load_config()
print('LIVE' if vault_lock.held_by_live_holder(
    Path.home() / '.claude' / 'vault-daemon.lock',
    outbox_io.require(cfg, 'lock', 'stale_after_s')) else 'FREE')
"@

function Get-DaemonState { (& $Python -c $LiveCheck).Trim() }

# ------------------------------------------------------------------ status ---
if ($Status) {
    Write-Host ""
    Write-Host "=== vault daemon ===" -ForegroundColor Cyan
    $state = Get-DaemonState
    if ($state -eq "LIVE") { Say "  daemon    : RUNNING (holds the singleton lock)" "DarkGreen" }
    else                   { Say "  daemon    : not running" "Yellow" }
    Say "  vault     : $(if ([string]::IsNullOrWhiteSpace($Vault)) { 'NOT CONFIGURED' } else { $Vault })"
    if (Test-Path $Log) {
        $size = (Get-Item $Log).Length
        Say "  log       : $Log ($size bytes, last written $((Get-Item $Log).LastWriteTime))"
        Say "  last lines:"
        Get-Content $Log -Tail 5 | ForEach-Object { Say "    $_" }
    } else {
        Say "  log       : none yet at $Log"
    }
    if (Test-Path $Shortcut) { Say "  at login  : installed ($Shortcut)" "DarkGreen" }
    else                     { Say "  at login  : not installed; run this script with -Install" "Yellow" }
    exit 0
}

# --------------------------------------------------------------- uninstall ---
if ($Uninstall) {
    if (Test-Path $Shortcut) {
        Remove-Item $Shortcut -Force
        Say "  removed $Shortcut" "DarkGreen"
        Say "  a daemon already running is left alone; close its process to stop it."
    } else {
        Say "  nothing to remove: no shortcut at $Shortcut"
    }
    exit 0
}

# ----------------------------------------------------------------- install ---
if ($Install) {
    if (-not (Test-Path $Launcher)) { Die "launcher missing: $Launcher" }
    if ([string]::IsNullOrWhiteSpace($Vault)) {
        Die @"
OBSIDIAN_VAULT is not set, so a daemon started at login would find no vault and
exit doing nothing. Set it at USER scope first, then run -Install again:
  [Environment]::SetEnvironmentVariable('OBSIDIAN_VAULT', '<your vault>', 'User')
"@
    }
    $shell = New-Object -ComObject WScript.Shell
    $link = $shell.CreateShortcut($Shortcut)
    $link.TargetPath = $Launcher
    $link.WorkingDirectory = $Scripts
    $link.Description = "Start the ResearchTools Obsidian vault event daemon"
    $link.WindowStyle = 7          # minimized; the log is what you read
    $link.Save()
    Say "  installed $Shortcut" "DarkGreen"
    Say "  it starts the daemon at your next login. To start it now, run this"
    Say "  script with no arguments. To undo, run it with -Uninstall."
    exit 0
}

# ------------------------------------------------------------------- start ---
if ([string]::IsNullOrWhiteSpace($Vault)) {
    Die "OBSIDIAN_VAULT is not set and -Vault was not given; refusing to guess a vault"
}
if (-not (Test-Path $Vault -PathType Container)) { Die "vault does not exist: $Vault" }

if ((Get-DaemonState) -eq "LIVE") {
    Say "  a daemon is already running; one per machine is the rule. Nothing to do." "Yellow"
    exit 0
}

# Rotate once, at the configured size. Keeping .1 rather than deleting, because
# the run worth reading is usually the one that just ended.
$cap = [int](& $Python -c @"
import sys
sys.path.insert(0, r'$Scripts')
import outbox_io
print(outbox_io.require(outbox_io.load_config(), 'daemon', 'log_max_bytes'))
"@).Trim()
if ((Test-Path $Log) -and (Get-Item $Log).Length -gt $cap) {
    Move-Item $Log "$Log.1" -Force
    Say "  rotated the log at $cap bytes to $Log.1"
}

$command = "`$env:OBSIDIAN_VAULT = '$Vault'; " +
           "& '$Python' '$Daemon' *>> '$Log'"
$proc = Start-Process powershell -PassThru -WindowStyle Hidden -ArgumentList @(
    "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", $command)

Start-Sleep -Seconds 3
if ((Get-DaemonState) -eq "LIVE") {
    Say "  daemon started, pid $($proc.Id), logging to $Log" "DarkGreen"
    exit 0
}
Say "  the daemon did not take its lock within 3 s. It may still be starting;" "Yellow"
Say "  read the log, and re-run with -Status:" "Yellow"
Say "    $Log" "Yellow"
exit 1
