#Requires -Version 5.1
<#
.SYNOPSIS
    Offline check of the PATH step of setup.ps1 (-InstallAiderPath): scripts\lib\rt-aider-path.ps1.

.DESCRIPTION
    The aider-setup commands (aider-night.bat, aider-plan.ps1, run-detached.ps1) run in place from the
    ResearchTools clone. This step puts the clone's own scripts folder on the USER Path, so a student types
    the commands from any folder. The decision is pure and driven by injected values, and the one write goes
    through a writer that this check replaces: the real user Path is never opened for writing here.

    It loads scripts\lib\rt-aider-path.ps1 directly, never setup.ps1, which would run its whole interactive
    flow as a side effect.

.EXAMPLE
    .\scripts\test\verify-aider-path.ps1
#>

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$failures = 0
function Check([string]$name, [bool]$ok) {
    if ($ok) { Write-Host "  PASS  $name" -ForegroundColor DarkGray }
    else     { Write-Host "  FAIL  $name" -ForegroundColor Red; $script:failures++ }
}

Write-Host ""
Write-Host "=== aider-setup on the user Path ===" -ForegroundColor Cyan

. (Join-Path $RepoRoot "scripts\lib\rt-aider-path.ps1")

# The user Path of the machine running this check, read once: it must be identical at the end.
$realPathBefore = [Environment]::GetEnvironmentVariable("Path", "User")

$tmp = Join-Path $env:TEMP ("aider-path-" + [guid]::NewGuid().ToString("N").Substring(0, 8))
$scripts = Join-Path $tmp ".claude\skills\aider-setup\scripts"
New-Item -ItemType Directory -Path $scripts -Force | Out-Null

Check "the folder is the scripts folder of the clone that runs setup" ((Get-RtAiderScriptsDir -RepoRoot $tmp) -eq $scripts)

$d = Resolve-RtAiderPathAction -Dir $scripts -CurrentUserPath "C:\Tools;C:\Other" -DirExists $true
Check "an absent folder is added at the end, nothing else moves" ($d.Action -eq "add" -and $d.NewPath -eq "C:\Tools;C:\Other;$scripts")

$d = Resolve-RtAiderPathAction -Dir $scripts -CurrentUserPath "C:\Tools;$scripts;C:\Other" -DirExists $true
Check "a folder already there is reported and the Path is not touched" ($d.Action -eq "already" -and $d.NewPath -eq "C:\Tools;$scripts;C:\Other")

$d = Resolve-RtAiderPathAction -Dir $scripts -CurrentUserPath ("C:\Tools;" + $scripts.ToUpper() + "\;C:\Other") -DirExists $true
Check "the comparison ignores the case and a trailing backslash" ($d.Action -eq "already")

$d = Resolve-RtAiderPathAction -Dir $scripts -CurrentUserPath "" -DirExists $true
Check "an empty Path becomes the folder alone, without a leading separator" ($d.Action -eq "add" -and $d.NewPath -eq $scripts)

$d = Resolve-RtAiderPathAction -Dir $scripts -CurrentUserPath "C:\Tools;" -DirExists $true
Check "a Path ending with a separator gets no doubled separator" ($d.Action -eq "add" -and $d.NewPath -eq "C:\Tools;$scripts")

$d = Resolve-RtAiderPathAction -Dir (Join-Path $tmp "nowhere") -CurrentUserPath "C:\Tools" -DirExists $false
Check "a folder that does not exist is refused and the Path is not touched (the clone has no aider-setup)" ($d.Action -eq "missing" -and $d.NewPath -eq "C:\Tools")

# --- the write -------------------------------------------------------------------------------
$script:store = "C:\Tools"
$writer = { param($value) $script:store = $value }
$reader = { $script:store }
$code = Install-RtAiderPath -RepoRoot $tmp -Preview:$false -Reader $reader -Writer $writer
Check "the write adds the folder to the stored Path and succeeds" ($code -eq 0 -and $script:store -eq "C:\Tools;$scripts")

$code = Install-RtAiderPath -RepoRoot $tmp -Preview:$false -Reader $reader -Writer $writer
Check "a second run changes nothing" ($code -eq 0 -and $script:store -eq "C:\Tools;$scripts")

$script:store = "C:\Tools"
$code = Install-RtAiderPath -RepoRoot $tmp -Preview:$true -Reader $reader -Writer $writer
Check "-Preview writes nothing (R16)" ($code -eq 0 -and $script:store -eq "C:\Tools")

$script:store = "C:\Tools"
$lying = { param($value) $script:store = "C:\Tools" }
$code = Install-RtAiderPath -RepoRoot $tmp -Preview:$false -Reader $reader -Writer $lying
Check "a write that did not take effect is a failure, read back rather than trusted (R9)" ($code -ne 0)

$code = Install-RtAiderPath -RepoRoot (Join-Path $tmp "no-clone") -Preview:$false -Reader $reader -Writer $writer
Check "a clone without the aider-setup scripts is reported as a failure and writes nothing" ($code -ne 0 -and $script:store -eq "C:\Tools")

$script:store = "C:\Tools;C:\Other"
$null = Install-RtAiderPath -RepoRoot $tmp -Preview:$false -Reader $reader -Writer $writer
Check "existing entries keep their order (add-only)" ($script:store.StartsWith("C:\Tools;C:\Other;"))

$setupText = [System.IO.File]::ReadAllText((Join-Path $RepoRoot "setup.ps1"))
Check "setup.ps1 offers -InstallAiderPath and dot-sources the library" (($setupText -match '\[switch\]\$InstallAiderPath') -and ($setupText -match 'rt-aider-path\.ps1'))
Check "setup.ps1 -All runs the PATH step" ($setupText -match '(?s)if \(\$All\) \{.*Invoke-AiderPath')

Remove-Item $tmp -Recurse -Force -ErrorAction SilentlyContinue
Check "the real user Path was never written by this check" ([Environment]::GetEnvironmentVariable("Path", "User") -eq $realPathBefore)

Write-Host ""
if ($failures -eq 0) {
    Write-Host "  All checks passed." -ForegroundColor Green
    Write-Host ""
    exit 0
}
Write-Host "  $failures check(s) failed." -ForegroundColor Red
Write-Host ""
exit 1
