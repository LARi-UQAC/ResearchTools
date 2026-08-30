#Requires -Version 5.1
<#
.SYNOPSIS
    Offline check of setup.ps1 -InstallPython: the decision, the refusals, the dry run.

.DESCRIPTION
    U9 of the CLAUDE*.md consolidation plan. Measured 2026-08-29: no installer in
    this repository created a virtual environment or installed a requirement, while
    run-offline-tests.ps1 resolves .venv-skills\Scripts\python.exe first, so a fresh
    clone read NOT RUN across the paper2talk suites and nothing fixed it.

    What can be checked offline is the layer around pip, which is where the defects
    would be: which requirements files the switch claims to install, whether those
    files exist, what it does when there is no interpreter, and whether -Preview is
    honest. Actually running pip needs a network and minutes, so it is not done here.

.SAFETY
    Every case runs against a throwaway repository root under $env:TEMP. The real
    .venv-skills is recorded before and asserted after, because a test that created
    or wrote to the professor's own environment would be the defect it is checking
    for. No pip process is started at any point.

.NOTES
    Not part of the green-stamp gate, which covers Python suites under .claude\ only.
    Same family as scripts\test\verify-daemon-install.ps1.

.EXAMPLE
    .\scripts\test\verify-python-env.ps1
#>

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$Fake     = Join-Path $env:TEMP "rt-pyenv-verify-$PID"
$failures = 0

function Check([string]$name, [bool]$ok) {
    if ($ok) { Write-Host "  PASS  $name" -ForegroundColor DarkGray }
    else     { Write-Host "  FAIL  $name" -ForegroundColor Red; $script:failures++ }
}

Write-Host ""
Write-Host "=== setup.ps1 -InstallPython ===" -ForegroundColor Cyan

# The real environment, recorded BEFORE anything runs.
$RealVenv   = Join-Path $RepoRoot ".venv-skills"
$venvBefore = Test-Path $RealVenv
$stampBefore = if ($venvBefore) { (Get-Item $RealVenv).LastWriteTimeUtc.Ticks } else { 0 }

. (Join-Path $RepoRoot "scripts\lib\rt-python-env.ps1")

# ------------------------------------------------------- the requirements list ---
# R14: a file this repository claims to install has to exist. The list is the one
# place the switch's scope is stated, so a stale entry here is a silent no-op there.
$reqs = @(Get-RtSuiteRequirements -RepoRoot $RepoRoot)
Check "the list is not empty"                    ($reqs.Count -ge 1)
Check "every requirements file exists"           (@($reqs | Where-Object { -not $_.Exists }).Count -eq 0)
Check "every entry says which suite needs it"    (@($reqs | Where-Object { [string]::IsNullOrWhiteSpace($_.Why) }).Count -eq 0)
Check "paper2talk is covered"                    (@($reqs | Where-Object { $_.Path -match 'paper2talk' }).Count -eq 1)
Check "recommendation-letter is covered"         (@($reqs | Where-Object { $_.Path -match 'recommendation-letter' }).Count -eq 1)

# Scope is deliberately the offline suite. The heavy optional skills must NOT be here:
# docling alone pulls torch, and one CVE in a skill nobody runs would block the switch
# the test suite needs.
Check "scopus is deliberately not installed"     (@($reqs | Where-Object { $_.Path -match 'scopus' }).Count -eq 0)
Check "extract-statistic is not installed"       (@($reqs | Where-Object { $_.Path -match 'extract-statistic' }).Count -eq 0)
Check "geolocalisation is not installed"         (@($reqs | Where-Object { $_.Path -match 'geolocalisation' }).Count -eq 0)

# Negative control: the Exists flag has to be able to say no, or the check above
# passes on a list of files that were never looked for.
$ghost = @(Get-RtSuiteRequirements -RepoRoot (Join-Path $Fake "no-such-repo"))
Check "Exists can report false"                  (@($ghost | Where-Object { $_.Exists }).Count -eq 0)

# ------------------------------------------------------------------ decisions ---
$dNoPy = Resolve-RtPythonEnvAction -VenvPath "D:\v" -VenvExists $false -BasePython ""
Check "no interpreter is an explicit refusal"    ($dNoPy.Action -eq "no-python")
Check "the refusal says what to do"              ($dNoPy.Message -match "install Python")

# No interpreter outranks everything: an existing venv cannot rescue a machine with
# no Python, because pip would be run from an interpreter that is not there.
$dNoPy2 = Resolve-RtPythonEnvAction -VenvPath "D:\v" -VenvExists $true -BasePython ""
Check "no interpreter beats an existing venv"    ($dNoPy2.Action -eq "no-python")

$dCreate = Resolve-RtPythonEnvAction -VenvPath "D:\v" -VenvExists $false -BasePython "C:\Python\python.exe"
Check "absent venv means create"                 ($dCreate.Action -eq "create")
Check "the create names the path"                ($dCreate.Message -match ([regex]::Escape("D:\v")))

$dReuse = Resolve-RtPythonEnvAction -VenvPath "D:\v" -VenvExists $true -BasePython "C:\Python\python.exe"
Check "present venv means reuse"                 ($dReuse.Action -eq "reuse")

# Whitespace is not an interpreter path.
$dWs = Resolve-RtPythonEnvAction -VenvPath "D:\v" -VenvExists $false -BasePython "   "
Check "whitespace is not an interpreter"         ($dWs.Action -eq "no-python")

# ----------------------------------------------------------------- the dry run ---
# R16: a dry run touches nothing. Pointed at the REAL repository root, because that
# is where a slip would create the directory this file exists to protect.
$preview = Install-RtPythonEnv -RepoRoot $RepoRoot -Preview 6>&1 | Out-String
# The code comes from a second call rather than from $LASTEXITCODE: this is a
# function returning a value, not a process, and under StrictMode an undefined
# $LASTEXITCODE is a terminating error. -Preview is side-effect-free by contract,
# which is exactly what the last check in this block proves.
$previewCode = Install-RtPythonEnv -RepoRoot $RepoRoot -Preview 6>$null
Check "-Preview returns 0"                       ($previewCode -eq 0)
Check "-Preview says what it would install"      ($preview -match "Would install")
Check "-Preview names pip-audit"                 ($preview -match "pip-audit")
Check "-Preview names a requirements file"       ($preview -match ([regex]::Escape("requirements.txt")))
Check "-Preview created no environment"          ((Test-Path $RealVenv) -eq $venvBefore)

# --------------------------------------------------------- the missing-file path ---
# A repository root with no requirements files at all: the step must fail by name
# rather than install a shorter list than it announced (R3).
New-Item -ItemType Directory -Path $Fake -Force | Out-Null
$missing = Install-RtPythonEnv -RepoRoot $Fake 6>&1 | Out-String
$missingCode = Install-RtPythonEnv -RepoRoot $Fake 6>$null
Check "a missing requirements file exits 1"      ($missingCode -eq 1)
Check "a missing requirements file fails"        ($missing -match "requirements file not found")
Check "the failure names the path"               ($missing -match ([regex]::Escape("paper2talk")))
Check "nothing was created in the fake root"     (-not (Test-Path (Join-Path $Fake ".venv-skills")))

# ------------------------------------------------------------ setup.ps1 wiring ---
$setup = Get-Content (Join-Path $RepoRoot "setup.ps1") -Raw -Encoding UTF8
Check "setup.ps1 declares -InstallPython"        ($setup -match '\[switch\]\$InstallPython')
Check "setup.ps1 loads rt-python-env.ps1"        ($setup -match ([regex]::Escape("rt-python-env.ps1")))
Check "setup.ps1 documents the switch"           ($setup -match ([regex]::Escape(".\setup.ps1 -InstallPython")))
Check "the switch has its own dispatch branch"   ($setup -match ([regex]::Escape('if ($InstallPython -and -not $All)')))
Check "Next steps names the switch"              ($setup -match "run-offline-tests.ps1 reports PASSED")

# README has to name .venv-skills by that name: the runner resolves it first, and a
# bootstrap block naming any other directory sends the operator somewhere the runner
# will not look.
$readme = Get-Content (Join-Path $RepoRoot "README.md") -Raw -Encoding UTF8
Check "README names .venv-skills"                ($readme -match ([regex]::Escape(".venv-skills")))
Check "README names -InstallPython"              ($readme -match ([regex]::Escape("-InstallPython")))

# ---------------------------------------------------- the professor's own venv ---
$stampAfter = if (Test-Path $RealVenv) { (Get-Item $RealVenv).LastWriteTimeUtc.Ticks } else { 0 }
Check "the real .venv-skills is unchanged"       ($stampAfter -eq $stampBefore)

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
