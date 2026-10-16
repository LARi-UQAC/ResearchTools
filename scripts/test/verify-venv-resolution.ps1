#Requires -Version 5.1
<#
.SYNOPSIS
    Offline check of scripts\lib\rt-venv.ps1 and of every launcher that must use it.

.DESCRIPTION
    Measured 2026-10-16: .venv-skills was emptied on 2026-10-06 and the loss stayed
    invisible for a week, because each launcher fell through to the first python on
    PATH without saying so, and because a worktree could only reach the main clone's
    environment through a junction (which `git worktree remove` then followed).

    Every case runs against throwaway repositories under $env:TEMP, built with real
    `git init` and `git worktree add` so the resolution is proven against the command
    the helper actually calls. Fictitious folder names only (R34). The real
    .venv-skills is recorded before and asserted after, and nothing here writes to it.
    No pip process is started and no interpreter is executed.

    Both directions are asserted (R20): a worktree finds the main environment with no
    link, and when no environment exists anywhere the helper refuses and names the
    paths instead of reaching for PATH.

.EXAMPLE
    .\scripts\test\verify-venv-resolution.ps1
#>

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$Scratch  = Join-Path $env:TEMP "rt-venv-verify-$PID"
$failures = 0

function Check([string]$name, [bool]$ok) {
    if ($ok) { Write-Host "  PASS  $name" -ForegroundColor DarkGray }
    else     { Write-Host "  FAIL  $name" -ForegroundColor Red; $script:failures++ }
}

# Used only for read-back at the end: the real environment must be untouched.
$RealVenv    = Join-Path $RepoRoot ".venv-skills"
$realBefore  = if (Test-Path $RealVenv) { (Get-Item $RealVenv).LastWriteTimeUtc.Ticks } else { 0 }

Write-Host ""
Write-Host "=== rt-venv.ps1: interpreter resolution ===" -ForegroundColor Cyan

. (Join-Path $RepoRoot "scripts\lib\rt-venv.ps1")

# --- scratch repositories ------------------------------------------------------
New-Item -ItemType Directory -Path $Scratch -Force | Out-Null
try {
$Main = Join-Path $Scratch "alpha-clone"
$Wt   = Join-Path $Scratch "alpha-worktree"
New-Item -ItemType Directory -Path $Main -Force | Out-Null

function Invoke-Git([string[]]$GitArgs) {
    $saved = $ErrorActionPreference; $ErrorActionPreference = "Continue"
    $global:LASTEXITCODE = 0
    & git -C $Main -c user.name=Fictitious -c user.email=fictitious@example.org @GitArgs 2>$null | Out-Null
    $ErrorActionPreference = $saved
    if ($global:LASTEXITCODE -ne 0) { throw "git $($GitArgs -join ' ') failed" }
}
Invoke-Git @("init", "--quiet")
Invoke-Git @("commit", "--quiet", "--allow-empty", "-m", "init")
Invoke-Git @("worktree", "add", "--quiet", "--detach", $Wt)

function New-FakeVenv([string]$Root) {
    $scripts = Join-Path $Root ".venv-skills\Scripts"
    New-Item -ItemType Directory -Path $scripts -Force | Out-Null
    Set-Content -Path (Join-Path $scripts "python.exe") -Value "stub" -Encoding ASCII
}

# --- Get-RtMainRepoRoot ----------------------------------------------------------
$mainFull = [System.IO.Path]::GetFullPath($Main).TrimEnd('\')
Check "main clone resolves to itself"                ((Get-RtMainRepoRoot -RepoRoot $Main) -ieq $mainFull)
Check "a worktree resolves to the main clone"        ((Get-RtMainRepoRoot -RepoRoot $Wt) -ieq $mainFull)
$plain = Join-Path $Scratch "not-a-repo"
New-Item -ItemType Directory -Path $plain -Force | Out-Null
Check "a folder outside any repository resolves to itself without throwing" ((Get-RtMainRepoRoot -RepoRoot $plain) -ieq ([System.IO.Path]::GetFullPath($plain).TrimEnd('\')))

# --- refusal first: nothing anywhere ----------------------------------------------
# PATH is shadowed so the assertion does not depend on this machine's python (R21).
function Find-RtPathPython { return "C:\fictitious\pathpython\python.exe" }

$none = Resolve-RtVenvPython -RepoRoot $Wt
Check "no environment anywhere: Python is null"      ($null -eq $none.Python)
Check "no environment anywhere: Source is none"      ($none.Source -eq "none")
Check "the refusal does NOT silently use PATH"       ($none.Message -notmatch "pathpython")
Check "the refusal names the worktree path"          ($none.Message -match [regex]::Escape((Join-Path $Wt ".venv-skills")))
Check "the refusal names the main clone path"        ($none.Message -match [regex]::Escape((Join-Path $mainFull ".venv-skills")))
Check "the refusal gives the rebuild command"        ($none.Message -match "setup\.ps1.*-InstallPython")
Check "the rebuild command targets the MAIN clone"   ($none.Rebuild -match [regex]::Escape($mainFull))

# --- an EMPTY folder is the 2026-10-06 state ---------------------------------------
New-Item -ItemType Directory -Path (Join-Path $Main ".venv-skills") -Force | Out-Null
$empty = Resolve-RtVenvPython -RepoRoot $Main
Check "an empty .venv-skills is refused"             ($null -eq $empty.Python)
Check "the refusal says the folder is empty"         ($empty.Message -match "EMPTY")
Check "the refusal names the missing interpreter"    ($empty.Message -match [regex]::Escape("Scripts\python.exe"))

# --- a worktree reaches the main environment with no link ---------------------------
New-FakeVenv $Main
$viaWt = Resolve-RtVenvPython -RepoRoot $Wt
Check "worktree finds the main clone's interpreter"  ($viaWt.Python -ieq (Join-Path $mainFull ".venv-skills\Scripts\python.exe"))
Check "its source is main-repo-venv"                 ($viaWt.Source -eq "main-repo-venv")
Check "no link or folder was created in the worktree" (-not (Test-Path (Join-Path $Wt ".venv-skills")))
Check "a found interpreter carries no refusal text"  ([string]::IsNullOrEmpty($viaWt.Message))

$viaMain = Resolve-RtVenvPython -RepoRoot $Main
Check "the main clone resolves its own environment"  ($viaMain.Source -eq "venv")

# --- an own environment in the worktree wins -----------------------------------------
New-FakeVenv $Wt
$own = Resolve-RtVenvPython -RepoRoot $Wt
Check "a worktree's own environment is preferred"    ($own.Source -eq "venv" -and $own.Python -ieq (Join-Path $Wt ".venv-skills\Scripts\python.exe"))
Remove-Item (Join-Path $Wt ".venv-skills") -Recurse -Force

# --- a PATH python cannot write a green stamp from a partial run ------------------------
Check "path-fallback with suites NOT RUN: no stamp"           (-not (Test-RtStampAllowed -InterpreterSource "path-fallback" -NotRunCount 3))
Check "path-fallback with nothing NOT RUN: stamp allowed"     (Test-RtStampAllowed -InterpreterSource "path-fallback" -NotRunCount 0)
Check "an environment with suites NOT RUN keeps today's rule" (Test-RtStampAllowed -InterpreterSource "main-repo-venv" -NotRunCount 3)
Check "an explicit -Python with suites NOT RUN keeps it too"  (Test-RtStampAllowed -InterpreterSource "explicit" -NotRunCount 3)

# --- only .venv-skills is looked for, and the refusal says a root .venv is not used -------
Check "the refusal says a root .venv is not used"             ($none.Message -match "root \.venv is not used")

# --- PATH only on request, and said ---------------------------------------------------
Remove-Item (Join-Path $Main ".venv-skills") -Recurse -Force
$fb = Resolve-RtVenvPython -RepoRoot $Wt -AllowPathFallback
Check "-AllowPathFallback returns PATH python"       ($fb.Python -eq "C:\fictitious\pathpython\python.exe")
Check "the fallback is labelled path-fallback"       ($fb.Source -eq "path-fallback")
Check "the fallback prints a warning naming the path" ($fb.Message -match "pathpython" -and $fb.Message -match "AllowPathFallback")
function Find-RtPathPython { return "" }
$fb2 = Resolve-RtVenvPython -RepoRoot $Wt -AllowPathFallback
Check "-AllowPathFallback with no PATH python still refuses" ($null -eq $fb2.Python -and $fb2.Message -match "no python on PATH")

# --- explicit -Python ---------------------------------------------------------------
$fake = Join-Path $Scratch "chosen-python.exe"
Set-Content -Path $fake -Value "stub" -Encoding ASCII
$ex = Resolve-RtVenvPython -RepoRoot $Wt -Python $fake
Check "an explicit existing -Python is used"         ($ex.Python -eq $fake -and $ex.Source -eq "explicit")
$exBad = Resolve-RtVenvPython -RepoRoot $Wt -Python (Join-Path $Scratch "absent-python.exe")
Check "an explicit -Python that does not exist is refused, not skipped" ($null -eq $exBad.Python -and $exBad.Message -match "absent-python")

# --- the REAL runner, executed: a refusal must stop it and clear the stale stamp -------
# Code-review finding: in run-offline-tests.ps1 the local `$python` was the SAME variable as
# the `[string]$Python` parameter (PowerShell is case-insensitive), which turned a $null
# result into "" and made the refusal dead code - the stamp stayed and the runner failed
# later with an unrelated error. Reading the text could not have caught that; running it does.
# A copy of the runner and the helper sits in a scratch tree with no environment anywhere.
$Runner = Join-Path $Scratch "runner-tree"
New-Item -ItemType Directory -Path (Join-Path $Runner "scripts\test"), (Join-Path $Runner "scripts\lib") -Force | Out-Null
Copy-Item (Join-Path $RepoRoot "scripts\test\run-offline-tests.ps1") (Join-Path $Runner "scripts\test\")
Copy-Item (Join-Path $RepoRoot "scripts\lib\rt-venv.ps1") (Join-Path $Runner "scripts\lib\")
$stamp = Join-Path $Runner ".rt-green.json"

function Invoke-Runner([string[]]$RunnerArgs) {
    Set-Content -Path $stamp -Value '{"stale": true}' -Encoding ASCII
    # Child stderr arrives as ErrorRecords under 2>&1; with the script's Stop preference
    # the first one would end THIS script. It is the child's output that is judged.
    $ErrorActionPreference = "Continue"
    $text =& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $Runner "scripts\test\run-offline-tests.ps1") @RunnerArgs 2>&1 | Out-String
    [pscustomobject]@{ Exit = $LASTEXITCODE; Text = $text; StampKept = (Test-Path $stamp) }
}

$refused = Invoke-Runner @()
Check "the runner refuses with no environment: exit 1"          ($refused.Exit -eq 1)
Check "the runner prints the refusal naming the path"           ($refused.Text -match "no suite interpreter" -and $refused.Text -match [regex]::Escape(".venv-skills"))
Check "the runner prints the rebuild command"                   ($refused.Text -match "-InstallPython")
Check "the refusal clears the stale green stamp"                (-not $refused.StampKept)
Check "the refusal never reaches a suite"                       ($refused.Text -notmatch "Suites\s+:")

$refusedBad = Invoke-Runner @("-Python", (Join-Path $Scratch "absent-python.exe"))
Check "a nonexistent -Python is refused too and clears the stamp" ($refusedBad.Exit -eq 1 -and $refusedBad.Text -match "does not exist" -and -not $refusedBad.StampKept)

# Positive control, without which every check above passes on a runner that refuses always:
# an existing interpreter is accepted and reported with its source.
$accepted = Invoke-Runner @("-Python", $fake)
Check "(control) an existing -Python gets past the refusal"     ($accepted.Text -match "Interpreter :" -and $accepted.Text -match "\(explicit\)" -and $accepted.Text -notmatch "no suite interpreter")

# --- vault-daemon-autostart -Status is a report: with no environment it must say so and
# write NOTHING to the daemon log (code-review finding: it used to append a "refused to
# start" line there, which reads as a failed login-time start). Run for real in a scratch
# tree at the script's own depth.
$AutoRoot = Join-Path $Scratch "autostart-tree"
$AutoDir  = Join-Path $AutoRoot ".claude\skills\obsidian-cli\scripts"
New-Item -ItemType Directory -Path $AutoDir, (Join-Path $AutoRoot "scripts\lib") -Force | Out-Null
Copy-Item (Join-Path $RepoRoot ".claude\skills\obsidian-cli\scripts\vault-daemon-autostart.ps1") $AutoDir
Copy-Item (Join-Path $RepoRoot "scripts\lib\rt-venv.ps1") (Join-Path $AutoRoot "scripts\lib\")
# USERPROFILE is NOT redirected: that breaks [Environment]::GetFolderPath("Startup") and the
# script dies before reaching the check. The real log is compared before and after instead.
$RealLog = Join-Path $env:USERPROFILE ".claude\vault-daemon.log"
$logBefore = if (Test-Path $RealLog) { (Get-Item $RealLog).Length } else { -1 }
$ErrorActionPreference = "Continue"
$statusText = & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $AutoDir "vault-daemon-autostart.ps1") -Status 2>&1 | Out-String
$statusExit = $LASTEXITCODE
$ErrorActionPreference = "Stop"
$logAfter = if (Test-Path $RealLog) { (Get-Item $RealLog).Length } else { -1 }
Check "-Status with no environment says it cannot determine"  ($statusText -match "cannot determine")
Check "-Status with no environment exits 1"                    ($statusExit -eq 1)
Check "-Status names the rebuild command"                      ($statusText -match "-InstallPython")
Check "-Status wrote nothing to the daemon log"                ($logAfter -eq $logBefore)

# --- wiring: every launcher uses the helper and none keeps its own copy (R18) ---------
Write-Host ""
Write-Host "=== launchers use the shared helper ===" -ForegroundColor Cyan
$ps1Callers = @(
    "scripts\test\run-offline-tests.ps1",
    "scripts\local\claude-switch.ps1",
    ".claude\skills\rt-observe\scripts\rt-dashboard.ps1",
    ".claude\skills\obsidian-cli\scripts\run-drill.ps1",
    ".claude\skills\obsidian-cli\scripts\vault-daemon-autostart.ps1",
    ".claude\skills\opt-local-vram-llm\scripts\tune-new-model.ps1"
)
foreach ($rel in $ps1Callers) {
    $path = Join-Path $RepoRoot $rel
    $txt  = Get-Content $path -Raw -Encoding UTF8
    $name = Split-Path $rel -Leaf
    Check "$name loads rt-venv.ps1"                  ($txt -match [regex]::Escape("rt-venv.ps1"))
    Check "$name calls Resolve-RtVenvPython"         ($txt -match "Resolve-RtVenvPython")
    # The old private copy joined this exact relative path onto a root.
    Check "$name builds no .venv-skills path itself" ($txt -notmatch [regex]::Escape('.venv-skills\Scripts\python.exe'))
}
$sh = Get-Content (Join-Path $RepoRoot ".claude\skills\rt-observe\scripts\rt-dashboard.sh") -Raw -Encoding UTF8
Check "rt-dashboard.sh asks git for the common dir"  ($sh -match "git-common-dir")

} finally {
    Remove-Item $Scratch -Recurse -Force -ErrorAction SilentlyContinue
}
$realAfter = if (Test-Path $RealVenv) { (Get-Item $RealVenv).LastWriteTimeUtc.Ticks } else { 0 }
Check "the real .venv-skills is unchanged"           ($realAfter -eq $realBefore)

Write-Host ""
if ($failures -eq 0) {
    Write-Host "  All checks passed." -ForegroundColor Green
    Write-Host ""
    exit 0
}
Write-Host "  $failures check(s) failed." -ForegroundColor Red
Write-Host ""
exit 1
