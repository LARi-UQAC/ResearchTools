#Requires -Version 5.1
<#
.SYNOPSIS
    Fails when the generated mirrors are stale: a canonical agent, skill, command or rule changed
    and install.ps1 was not re-run (Issue #102).

.DESCRIPTION
    Calls Test-RtMirrorsFresh (scripts\lib\rt-mirrors-fresh.ps1), which copies the tracked and
    untracked-not-ignored files to TEMP, runs install.ps1 -Profile <active> THERE and reports
    every file the run changed or created. The real tree is never written (R16).

    Sections:
      a. the real repository: fresh, and its working tree unchanged afterwards;
      b. negative control (R20) on a fictitious repository whose install.ps1 copies src.md to
         mirror.md: fresh as built, then src.md edited without re-running it -> reported;
      c. an install.ps1 that fails -> Ok false with the error, never a pass.

    run-all-checks.ps1 discovers this file by its name.

.EXAMPLE
    .\scripts\test\verify-mirrors-fresh.ps1
#>
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
. (Join-Path $RepoRoot "scripts\lib\rt-mirrors-fresh.ps1")
. (Join-Path $RepoRoot "scripts\lib\rt-update.ps1")
$Tmp = Join-Path $env:TEMP "rt-mirrors-fresh-$PID"
$failures = 0

function Check([string]$name, [bool]$ok) {
    if ($ok) { Write-Host "  PASS  $name" -ForegroundColor DarkGray }
    else     { Write-Host "  FAIL  $name" -ForegroundColor Red; $script:failures++ }
}

function New-FakeRepo([string]$Dir, [string]$InstallBody) {
    <# Purpose: a git repository with src.md, mirror.md and the given install.ps1 body. #>
    New-Item -ItemType Directory -Path $Dir -Force | Out-Null
    $enc = New-Object System.Text.UTF8Encoding($false)
    [IO.File]::WriteAllText((Join-Path $Dir "src.md"), "rule one`n", $enc)
    [IO.File]::WriteAllText((Join-Path $Dir "mirror.md"), "rule one`n", $enc)
    [IO.File]::WriteAllText((Join-Path $Dir "install.ps1"), $InstallBody, $enc)
    $ErrorActionPreference = "Continue"
    & git -C $Dir init -q 2>&1 | Out-Null
    & git -C $Dir add -A 2>&1 | Out-Null
}

Write-Host ""
Write-Host "=== mirrors fresh: install.ps1 changes nothing ===" -ForegroundColor Cyan
try {
    # a. the real repository
    $profileName = Get-RtActiveProfile -ClaudeMdPath (Join-Path $RepoRoot ".claude\CLAUDE.md")
    Check "the active profile is readable" ([bool]$profileName)
    $before = (& git -C $RepoRoot status --porcelain 2>$null | Out-String)
    $res = Test-RtMirrorsFresh -Root $RepoRoot -ProfileName $profileName
    if (-not $res.Ok) {
        foreach ($d in $res.Differs) { Write-Host "        stale: $d" -ForegroundColor Red }
        if ($res.Error) { Write-Host "        error: $($res.Error)" -ForegroundColor Red }
        Write-Host "        remedy: run .\install.ps1 -Profile $profileName and commit the regenerated files" -ForegroundColor Yellow
    }
    Check "the real repository: install.ps1 would change no file" ($res.Ok)
    $after = (& git -C $RepoRoot status --porcelain 2>$null | Out-String)
    Check "the real working tree is unchanged by the check (R16)" ($before -eq $after)

    # b. negative control on a fictitious repository
    $copyBody = "param([string]`$Profile)`r`nCopy-Item -LiteralPath (Join-Path `$PSScriptRoot 'src.md') -Destination (Join-Path `$PSScriptRoot 'mirror.md') -Force`r`nexit 0`r`n"
    $fake = Join-Path $Tmp "fake"
    New-FakeRepo $fake $copyBody
    $res = Test-RtMirrorsFresh -Root $fake -ProfileName "fixture"
    Check "(control) a repository whose mirror matches its source is fresh" ($res.Ok -and @($res.Differs).Count -eq 0)
    Add-Content -LiteralPath (Join-Path $fake "src.md") -Value "rule two"
    $res = Test-RtMirrorsFresh -Root $fake -ProfileName "fixture"
    Check "(R20) a source edited without re-running install is reported" ((-not $res.Ok) -and (@($res.Differs) -contains "mirror.md"))
    Check "(R20) only the stale mirror is named, not the edited source" (-not (@($res.Differs) -contains "src.md"))
    Check "the fictitious repository itself is untouched (still stale)" ([IO.File]::ReadAllText((Join-Path $fake "mirror.md")) -eq "rule one`n")

    # c. an install.ps1 that fails
    $bad = Join-Path $Tmp "bad"
    New-FakeRepo $bad "param([string]`$Profile)`r`nWrite-Output 'boom in install'`r`nexit 3`r`n"
    $res = Test-RtMirrorsFresh -Root $bad -ProfileName "fixture"
    Check "(failure) a failing install.ps1 is never a pass, with its exit code" ((-not $res.Ok) -and $res.Error -match "exited 3 ")
    Check "(failure) the error carries the install output" ($res.Error -match "boom in install")
    # review round 1 (#7): judge THIS run's copy, not every rt-mirror-copy-* of a shared TEMP
    Check "this run's TEMP copy is removed" ($res.CopyPath -and -not (Test-Path -LiteralPath $res.CopyPath))

    # d. review round 1 (#8): a tracked path with an accent reaches the copy
    $accent = Join-Path $Tmp "accent"
    $fileName = "r" + [char]0x00E8 + "gle.md"
    New-FakeRepo $accent ("param([string]`$Profile)`r`nif (-not (Test-Path -LiteralPath (Join-Path `$PSScriptRoot ('r' + [char]0x00E8 + 'gle.md')))) { exit 4 }`r`nexit 0`r`n")
    [IO.File]::WriteAllText((Join-Path $accent $fileName), "accented`n", (New-Object System.Text.UTF8Encoding($false)))
    $ErrorActionPreference = "Continue"   # git warns about line endings on stderr
    & git -C $accent add -A 2>&1 | Out-Null
    $ErrorActionPreference = "Stop"
    $res = Test-RtMirrorsFresh -Root $accent -ProfileName "fixture"
    Check "(review #8) a file named with an accent is copied (install.ps1 finds it)" ($res.Ok)

    # e. review round 2: a file that cannot be copied is an error, even for a caller on Continue
    $locked = Join-Path $Tmp "locked"
    New-FakeRepo $locked $copyBody
    $ErrorActionPreference = "Continue"
    $handle = [IO.File]::Open((Join-Path $locked "src.md"), "Open", "ReadWrite", "None")
    try { $res = Test-RtMirrorsFresh -Root $locked -ProfileName "fixture" } finally { $handle.Dispose() }
    $ErrorActionPreference = "Stop"
    Check "(review round 2) an uncopyable file gives Ok=false with an error, never a partial pass" ((-not $res.Ok) -and $res.Error -match "copy")
}
finally {
    Remove-Item -LiteralPath $Tmp -Recurse -Force -ErrorAction SilentlyContinue
}

Write-Host ""
if ($failures -eq 0) { Write-Host "  All checks passed." -ForegroundColor Green; Write-Host ""; exit 0 }
Write-Host "  $failures check(s) failed." -ForegroundColor Red
Write-Host ""
exit 1
