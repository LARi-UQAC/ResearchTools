<#
.SYNOPSIS
    Run the vault event daemon's end-to-end drill: phases 0 to 6, two windows,
    and a teardown that puts the vault back.

.DESCRIPTION
    The drill (vault_daemon_e2e.py) needs a daemon running in one process and
    itself in another, and it CLEANS UP NOTHING: every note it causes to be
    filed stays in the vault when it ends. Running it by hand therefore means
    six phases, two terminals, and a manual walk back through the journal, and
    the walk is the part that gets skipped when it is late.

    This script is the harness around that. It refuses before it starts rather
    than half way through, records the journal baseline BEFORE the daemon can
    write anything, and undoes everything filed after that baseline at the end,
    even when the drill fails.

    The teardown itself is not implemented here. It is
    `vault_journal.py --undo-since`, which is covered by the offline suite,
    because a walk backwards through the journal is the one step in this
    procedure that can damage the vault, and PowerShell that spawns processes
    cannot be tested offline. What stays here is sequencing and refusals.

.PARAMETER Vault
    The vault root. Defaults to OBSIDIAN_VAULT. There is no built-in path: a
    vault that is not configured is an explicit stop (R1, R3), because a
    default guessed here would be a different vault on someone else's machine.

.PARAMETER Only
    Comma-separated step names, passed through to the drill. Step names:
    filed, parked, containment, collision, drain, undo, lock, residency.
    Run `filed` before `collision`; a collision needs a note to collide with.

.PARAMETER WithEviction
    Let step 9 load the coder-role model. It evicts the writer from the card
    and leaves the GPU holding a different model than it found, so it is off
    by default and worth a separate run.

.PARAMETER SkipTests
    Skip phase 0.2, the offline suite. Only for a re-run minutes after a green
    one; the suite is what says the code about to touch the vault is the code
    that passed.

.PARAMETER KeepVaultChanges
    Skip phase 6. The drill's notes stay in the vault and the journal indices
    are printed so they can be undone by hand later.

.PARAMETER Yes
    Do not prompt before the teardown writes. Without it the teardown previews,
    shows what it would undo, and asks (R16).

.EXAMPLE
    .\run-drill.ps1
    .\run-drill.ps1 -Only filed,parked -SkipTests
    .\run-drill.ps1 -Yes -KeepVaultChanges

.NOTES
    Run NO other Claude Code session while this is going. The journal is
    machine-global and the teardown undoes everything recorded after its
    baseline, so a note another session flushes mid-drill would be undone too.
#>
[CmdletBinding()]
param(
    [string]$Vault = $env:OBSIDIAN_VAULT,
    [string]$Only,
    [switch]$WithEviction,
    [switch]$SkipTests,
    [switch]$KeepVaultChanges,
    [switch]$Yes,
    [double]$StepTimeout = 300
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$Scripts  = $PSScriptRoot
$RepoRoot = Split-Path (Split-Path (Split-Path (Split-Path $Scripts -Parent) -Parent) -Parent) -Parent
$Outbox   = Join-Path $env:USERPROFILE ".claude\obsidian-outbox"
$Journal  = Join-Path $env:USERPROFILE ".claude\vault-journal.jsonl"
$Daemon   = Join-Path $Scripts "vault_daemon.py"
$Drill    = Join-Path $Scripts "vault_daemon_e2e.py"
$JournalTool = Join-Path $Scripts "vault_journal.py"

function Say([string]$text, [string]$colour = "Gray") { Write-Host $text -ForegroundColor $colour }
function Phase([string]$text) { Write-Host ""; Write-Host "=== $text ===" -ForegroundColor Cyan }
function Die([string]$text) { Write-Host "  STOP  $text" -ForegroundColor Red; exit 1 }

# The suite's interpreter when it exists, so the drill runs under the same
# Python the tests passed on, not whatever `python` happens to mean today.
$Python = Join-Path $RepoRoot ".venv-skills\Scripts\python.exe"
if (-not (Test-Path $Python)) { $Python = "python" }

# ---------------------------------------------------------------- phase 0 ---
Phase "Phase 0 - preconditions"

if ([string]::IsNullOrWhiteSpace($Vault)) {
    Die @"
OBSIDIAN_VAULT is not set and -Vault was not given.
Set it once, then open a NEW terminal (a running shell keeps its old block,
and under VS Code the whole editor has to restart):
  [Environment]::SetEnvironmentVariable('OBSIDIAN_VAULT', '<your vault>', 'User')
"@
}
if (-not (Test-Path $Vault -PathType Container)) { Die "vault does not exist: $Vault" }
Say "  vault      : $Vault"
Say "  interpreter: $Python"

# No 2>&1 on a native command: Windows PowerShell wraps each stderr line in an
# ErrorRecord and sets $? false even on exit 0, which would read as "ollama is
# broken" whenever it merely printed a warning.
$ps = ""
try { $ps = (ollama ps | Out-String) } catch { $ps = "" }
if ($ps -match "Forever") {
    Say "  model      : resident, keep-alive Forever" "DarkGreen"
} else {
    Say "  model      : NOT reported resident. The first event pays the load time and" "Yellow"
    Say "               may blow the 72 s budget for reasons that are not the daemon's." "Yellow"
}

if ($SkipTests) {
    Say "  suite      : skipped by -SkipTests" "Yellow"
} else {
    Say "  suite      : running the offline suite, about two minutes"
    & (Join-Path $RepoRoot "scripts\test\run-offline-tests.ps1") | Out-Host
    if ($LASTEXITCODE -ne 0) { Die "the offline suite is red; fix that before touching the vault" }
}

# ---------------------------------------------------------------- phase 1 ---
Phase "Phase 1 - no daemon may already be running"

$liveCheck = @"
import sys
sys.path.insert(0, r'$Scripts')
import outbox_io, vault_lock
from pathlib import Path
cfg = outbox_io.load_config()
stale = outbox_io.require(cfg, 'lock', 'stale_after_s')
lock = Path.home() / '.claude' / 'vault-daemon.lock'
print('LIVE' if vault_lock.held_by_live_holder(lock, stale) else 'FREE')
"@
$state = (& $Python -c $liveCheck).Trim()
if ($state -eq "LIVE") {
    Die "another daemon holds the singleton lock. Stop it first; one daemon per machine."
}
Say "  singleton lock: free (a lock file left by a dead daemon is reclaimed on start)"

# ---------------------------------------------------------------- phase 2 ---
Phase "Phase 2 - clear leftovers from an interrupted run"

$leftovers = @(Get-ChildItem $Outbox -Recurse -Filter "e2e-drill-*" -File -ErrorAction SilentlyContinue)
if ($leftovers.Count -eq 0) {
    Say "  nothing to clear"
} else {
    foreach ($f in $leftovers) { Say "  removing $($f.FullName.Substring($Outbox.Length + 1))" }
    $leftovers | Remove-Item -Force
}
$stranded = @(Get-ChildItem (Join-Path $Outbox "state") -Filter "*.json" -File -ErrorAction SilentlyContinue)
if ($stranded.Count -gt 0) {
    Say "  $($stranded.Count) state file(s) left by a crash mid-event: $($stranded.Name -join ', ')" "Yellow"
}
# Never *.md in the outbox root: those are queued notes waiting for the flush.

# ------------------------------------------------------- journal baseline ---
$baseline = [int](& $Python $JournalTool --journal $Journal --count).Trim()
Say "  journal baseline: $baseline undoable record(s). Everything after this index is the drill's."

# ---------------------------------------------------------------- phase 3 ---
Phase "Phase 3 - window 1, the daemon"

$daemonCmd = "`$env:OBSIDIAN_VAULT = '$Vault'; " +
             "Write-Host 'DAEMON WINDOW - leave this open, Ctrl+C stops it' -ForegroundColor Cyan; " +
             "& '$Python' '$Daemon'"
$window = Start-Process powershell -PassThru -ArgumentList @(
    "-NoExit", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", $daemonCmd)
Say "  spawned daemon window, pid $($window.Id)"

$deadline = (Get-Date).AddSeconds(60)
do {
    Start-Sleep -Milliseconds 500
    $state = (& $Python -c $liveCheck).Trim()
} while ($state -ne "LIVE" -and (Get-Date) -lt $deadline)
if ($state -ne "LIVE") {
    Die "the daemon did not take its singleton lock within 60 s; read its window"
}
Say "  daemon holds the singleton lock, so it is up and watching" "DarkGreen"

# ---------------------------------------------------------------- phase 4 ---
$drillExit = 1
try {
    Phase "Phase 4 - window 2, the drill"

    $env:OBSIDIAN_VAULT = $Vault
    # Not $args: that is an automatic variable, and shadowing it in a script
    # that also has a param block is how a later reader loses an afternoon.
    $drillArgs = @($Drill, "--timeout", $StepTimeout)
    if ($Only) { $drillArgs += @("--only", $Only) }
    if ($WithEviction) { $drillArgs += "--with-eviction" }

    Say "  dry run first: writes nothing, proves the vault resolved"
    & $Python @drillArgs | Out-Host

    Say "  the drill itself. Budget 5 to 15 minutes." "Yellow"
    & $Python @($drillArgs + "--yes") | Out-Host
    $drillExit = $LASTEXITCODE

    # ------------------------------------------------------------ phase 5 ---
    Phase "Phase 5 - what to read"
    if ($drillExit -eq 0) {
        Say "  every step passed" "DarkGreen"
    } else {
        Say "  some step FAILED; the JSON above names which and why" "Yellow"
    }
    Say "  Read three things: the confidence values against which events routed"
    Say "  correctly (that is what daemon.classify_confidence_min is tuned from),"
    Say "  the phantom step's volume (phantom_max_per_drain), and the drain's"
    Say "  accept-to-reject ratio. A drain that rejects almost nothing means the"
    Say "  shared-mechanism test stopped being applied and the vault is growing a"
    Say "  hairball, which looks healthier than disconnection and is worse."
    Say "  Both dials live in daemon-config.json beside this script."
}
finally {
    # ------------------------------------------------------------ phase 6 ---
    Phase "Phase 6 - put the vault back"

    if ($KeepVaultChanges) {
        Say "  skipped by -KeepVaultChanges. To undo later, newest first:" "Yellow"
        Say "    $Python $JournalTool --journal `"$Journal`" --vault `"$Vault`" --undo-since $baseline --yes"
    } else {
        Say "  preview of what would be undone (nothing is written yet):"
        & $Python $JournalTool --journal $Journal --vault $Vault --undo-since $baseline | Out-Host

        $go = $Yes
        if (-not $go) {
            $answer = Read-Host "  Undo everything after index $baseline ? [y/N]"
            $go = ($answer -eq "y" -or $answer -eq "Y")
        }
        if ($go) {
            & $Python $JournalTool --journal $Journal --vault $Vault --undo-since $baseline --yes | Out-Host
            if ($LASTEXITCODE -ne 0) {
                Say "  some record was REFUSED. The usual reason is benign: the drill's own" "Yellow"
                Say "  step 7 already undid the last record, so undoing it again finds the" "Yellow"
                Say "  file smaller than the size the record claims. Read the JSON above and" "Yellow"
                Say "  check anything else by hand." "Yellow"
            } else {
                Say "  vault restored to the state it had before the drill" "DarkGreen"
            }
        } else {
            Say "  left in place at your request. The command above undoes it later." "Yellow"
        }
    }

    Phase "Stopping the daemon window"
    if ($window -and -not $window.HasExited) {
        Stop-Process -Id $window.Id -Force -ErrorAction SilentlyContinue
        Say "  daemon window closed"
    }
    # The daemon is killed rather than asked to stop, so its singleton lock is
    # left behind. That is correct and self-healing: the holder is gone, so the
    # next start reclaims it by the dead-pid rule.
}

exit $drillExit
