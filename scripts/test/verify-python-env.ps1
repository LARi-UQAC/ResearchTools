#Requires -Version 5.1
<#
.SYNOPSIS
    Offline check of setup.ps1 -InstallPython: the decisions, the refusals, the dry run.

.DESCRIPTION
    U9 of the CLAUDE*.md consolidation plan. Measured 2026-08-29: no installer in
    this repository created a virtual environment or installed a requirement, while
    run-offline-tests.ps1 resolves .venv-skills\Scripts\python.exe first, so a fresh
    clone read NOT RUN across the paper2talk suites and nothing fixed it.

    Extended 2026-10-16 after .venv-skills was emptied and could not be rebuilt
    reliably: the first python on PATH belonged to another account, the only other
    interpreter under this account could not create a venv, and the package list
    left out the scopus and extract-statistic skills. What is checked here, all with
    injected candidates and fictitious account names (R34):
      - the package list (JSON data, R6) and its docling exclusion, in both directions
      - an interpreter outside the current profile is refused (and a machine-wide one
        is not)
      - an interpreter that cannot create a venv is refused, and the refusal names it
      - -Python is never quietly replaced by another candidate
      - -Preview chooses the interpreter, names what it would install, writes nothing
      - run from a linked worktree, the environment targets the main clone

    What stays unproven offline is pip itself and the scratch `python -m venv` probe
    (both need a real interpreter and the network). No pip process is started here
    and no interpreter is executed.

.SAFETY
    Every case runs against a throwaway tree under $env:TEMP. The real .venv-skills
    is recorded before and asserted after, because a test that created or wrote to
    the professor's own environment would be the defect it is checking for.

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

. (Join-Path $RepoRoot "scripts\lib\rt-venv.ps1")
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
# 2026-10-16: the skills the repository RUNS are covered too, not the test suite alone.
Check "scopus is covered"                        (@($reqs | Where-Object { $_.Path -match 'scopus' }).Count -eq 1)
Check "extract-statistic is covered"             (@($reqs | Where-Object { $_.Path -match 'extract-statistic' }).Count -eq 1)
$stat = @($reqs | Where-Object { $_.Path -match 'extract-statistic' })[0]
Check "extract-statistic drops docling (torch)"  ($stat.Exclude -contains "docling")
$scopus = @($reqs | Where-Object { $_.Path -match 'scopus' })[0]
Check "scopus excludes nothing"                  ($scopus.Exclude.Count -eq 0)
# Still deliberately out of scope.
Check "geolocalisation is not installed"         (@($reqs | Where-Object { $_.Path -match 'geolocalisation' }).Count -eq 0)

# Negative control: the Exists flag has to be able to say no, or the check above
# passes on a list of files that were never looked for.
$ghost = @(Get-RtSuiteRequirements -RepoRoot (Join-Path $Fake "no-such-repo"))
Check "Exists can report false"                  (@($ghost | Where-Object { $_.Exists }).Count -eq 0)

$tools = @(Get-RtToolRequirements)
Check "pip-audit is installed by the installer"  (@($tools | Where-Object { $_.Spec -match '^pip-audit==' }).Count -eq 1)

# ------------------------------------------------------ the docling exclusion ---
$real = Get-Content (Join-Path $RepoRoot ".claude\skills\extract-statistic\scripts\requirements.txt") -Encoding UTF8
$kept = @(Get-RtFilteredRequirementLines -Lines $real -Exclude $stat.Exclude)
$isReq = { param($l, $n) $l -match ('^\s*' + [regex]::Escape($n) + '\b') -and $l -notmatch '^\s*#' }
Check "the real file carries docling to begin with" (@($real | Where-Object { & $isReq $_ "docling" }).Count -ge 1)
Check "docling is gone from the filtered lines"  (@($kept | Where-Object { & $isReq $_ "docling" }).Count -eq 0)
Check "pymupdf4llm survives the filter"          (@($kept | Where-Object { & $isReq $_ "pymupdf4llm" }).Count -ge 1)
Check "markitdown survives the filter"           (@($kept | Where-Object { & $isReq $_ "markitdown" }).Count -ge 1)
Check "comments that mention docling are kept"   (@($kept | Where-Object { $_ -match '^\s*#.*[Dd]ocling' }).Count -ge 1)
$sample = @("docling==2.1", "docling-core==1.0", "Docling[x]>=3", "# docling is heavy", "", "requests==2.0")
$out = @(Get-RtFilteredRequirementLines -Lines $sample -Exclude @("docling"))
Check "exact name dropped, extras and case included" (-not ($out -contains "docling==2.1") -and -not ($out -contains "Docling[x]>=3"))
Check "a longer name sharing the prefix stays"   ($out -contains "docling-core==1.0")
Check "an empty exclusion list changes nothing"  (@(Get-RtFilteredRequirementLines -Lines $sample -Exclude @()).Count -eq $sample.Count)

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
Check "whitespace is not an interpreter"        ($dWs.Action -eq "no-python")

# ----------------------------------------------- which interpreter may be used ---
# Fictitious accounts. The caller's profile is alpha-user; bravo-admin is "another
# account", the shape of the 2026-10-16 case (an admin account's Python on PATH).
$Users   = Join-Path $Fake "Users"
$Mine    = Join-Path $Users "alpha-user"
$Foreign = Join-Path $Users "bravo-admin\Python313\python.exe"
$Py311   = Join-Path $Mine "Python311\python.exe"
$Py312   = Join-Path $Mine "Python312\python.exe"
$Machine = Join-Path $Fake "ProgramFiles\Python311\python.exe"
foreach ($p in @($Foreign, $Py311, $Py312, $Machine)) {
    New-Item -ItemType Directory -Path (Split-Path $p -Parent) -Force | Out-Null
    Set-Content -Path $p -Value "stub" -Encoding ASCII
}

Check "another account's interpreter is refused" ((Test-RtInterpreterOwner -Path $Foreign -UserProfile $Mine) -match "another account")
Check "the caller's own interpreter is accepted" ((Test-RtInterpreterOwner -Path $Py311 -UserProfile $Mine) -eq "")
Check "a machine-wide interpreter is accepted"   ((Test-RtInterpreterOwner -Path $Machine -UserProfile $Mine) -eq "")
Check "a sibling folder sharing the prefix is NOT mine" ((Test-RtInterpreterOwner -Path (Join-Path $Users "alpha-user2\python.exe") -UserProfile $Mine) -match "another account")

# py launcher output, parsed as text
$pyText = @"
 -V:3.13 *        D:\profiles\bravo-admin\Python313\python.exe
 -V:3.12          D:\profiles\alpha-user\Python312\python.exe
 -V:3.11          D:\profiles\alpha-user\Python311\python.exe
a line that is not a listing
"@
$parsed = @(Get-RtPyLauncherPaths -Text $pyText)
Check "py launcher output yields three paths"    ($parsed.Count -eq 3)
Check "py launcher: garbage yields nothing"      (@(Get-RtPyLauncherPaths -Text "no pythons here").Count -eq 0)

# The probe is injected: a stand-in for "python -m venv works". 3.12 plays the
# interpreter that lacks venvlauncher.exe.
$probe = { param($p) if ($p -eq $script:Py312) { "python -m venv failed (exit 1): venvlauncher.exe not found" } else { "" } }
$pickOk = Select-RtBasePython -Candidates @($Foreign, $Py312, $Py311) -UserProfile $Mine -Probe $probe
Check "the first usable candidate is chosen"     ($pickOk.Python -eq $Py311)
Check "both rejects are reported"                ($pickOk.Rejected.Count -eq 2)
Check "the foreign one is rejected for its owner" (@($pickOk.Rejected | Where-Object { $_.Path -eq $Foreign -and $_.Reason -match "another account" }).Count -eq 1)
Check "the venv-less one is rejected for its probe" (@($pickOk.Rejected | Where-Object { $_.Path -eq $Py312 -and $_.Reason -match "venvlauncher" }).Count -eq 1)
Check "a choice carries no refusal text"         ([string]::IsNullOrEmpty($pickOk.Message))

$pickNone = Select-RtBasePython -Candidates @($Foreign, $Py312) -UserProfile $Mine -Probe $probe
Check "no usable candidate: nothing chosen"      ([string]::IsNullOrEmpty($pickNone.Python))
Check "the refusal names the foreign candidate"  ($pickNone.Message -match [regex]::Escape($Foreign))
Check "the refusal names the failing candidate and why" ($pickNone.Message -match [regex]::Escape($Py312) -and $pickNone.Message -match "venvlauncher")
Check "the refusal says what to do"              ($pickNone.Message -match "-Python")

$pickEmpty = Select-RtBasePython -Candidates @() -UserProfile $Mine -Probe $probe
Check "no candidate at all is a refusal that says so" ([string]::IsNullOrEmpty($pickEmpty.Python) -and $pickEmpty.Message -match "none was found")

# An explicit -Python is never replaced, even when a good candidate exists.
$pickExplicit = Select-RtBasePython -Candidates @($Py311) -Explicit $Foreign -UserProfile $Mine -Probe $probe
Check "an explicit foreign interpreter is refused, not swapped" ([string]::IsNullOrEmpty($pickExplicit.Python))
$pickExplicit2 = Select-RtBasePython -Candidates @($Py311) -Explicit (Join-Path $Fake "absent.exe") -UserProfile $Mine -Probe $probe
Check "an explicit missing interpreter is refused" ([string]::IsNullOrEmpty($pickExplicit2.Python) -and $pickExplicit2.Message -match "does not exist")
$pickExplicit3 = Select-RtBasePython -Candidates @($Foreign) -Explicit $Py311 -UserProfile $Mine -Probe $probe
Check "an explicit good interpreter wins"        ($pickExplicit3.Python -eq $Py311)

# SkipProbe (the preview) must not call the probe at all.
$tripwire = { param($p) throw "probe must not run in a preview" }
$pickSkip = Select-RtBasePython -Candidates @($Py312) -UserProfile $Mine -Probe $tripwire -SkipProbe
Check "-SkipProbe never calls the probe"         ($pickSkip.Python -eq $Py312)

# The probe itself, with a real process. Failure path (R20): a stub that is not an
# executable cannot create a venv, and the reason must be non-empty. Success path: a
# real interpreter, when one resolves here (skipped, not failed, when none does). The
# scratch environment lives in TEMP and the probe removes it; nothing under the real
# repository is written.
$probeBad = Test-RtVenvCreates -Python $Py312 -TimeoutSeconds 60
Check "the probe rejects a stub that is not an interpreter" (-not [string]::IsNullOrEmpty($probeBad))
$ownVenv = Resolve-RtVenvPython -RepoRoot $RepoRoot
if ($null -ne $ownVenv.Python) {
    $probeGood = Test-RtVenvCreates -Python $ownVenv.Python -TimeoutSeconds 120
    Check "the probe accepts an interpreter that can build a venv" ([string]::IsNullOrEmpty($probeGood))
} else {
    Write-Host "  SKIP  probe success path (no suite interpreter on this machine)" -ForegroundColor Yellow
}
Check "the probe left no scratch folder behind"  (@(Get-ChildItem $env:TEMP -Filter "rt-venv-probe-*" -ErrorAction SilentlyContinue).Count -eq 0)

# ----------------------------------------------------------------- the dry run ---
# R16: a dry run touches nothing. Pointed at the REAL repository root, because that
# is where a slip would create the directory this file exists to protect. The
# candidates are injected so the result does not depend on this machine's PATH (R21).
$previewOut  = Install-RtPythonEnv -RepoRoot $RepoRoot -Preview -CandidatePaths @($Foreign, $Py311) -UserProfile $Mine 6>&1 | Out-String
$previewCode = Install-RtPythonEnv -RepoRoot $RepoRoot -Preview -CandidatePaths @($Foreign, $Py311) -UserProfile $Mine 6>$null
Check "-Preview returns 0"                       ($previewCode -eq 0)
Check "-Preview says what it would install"      ($previewOut -match "Would install")
Check "-Preview names pip-audit"                 ($previewOut -match "pip-audit")
Check "-Preview names a requirements file"       ($previewOut -match ([regex]::Escape("requirements.txt")))
Check "-Preview names the docling exclusion"     ($previewOut -match "without: docling")
Check "-Preview names the interpreter it chose"  ($previewOut -match [regex]::Escape($Py311))
Check "-Preview says the probe is not run"       ($previewOut -match "NOT run")
Check "-Preview created no environment"          ((Test-Path $RealVenv) -eq $venvBefore)

# Only a foreign interpreter on offer: skipped with the reason, exit 0 (setup carries on).
$refusedOut  = Install-RtPythonEnv -RepoRoot $RepoRoot -Preview -CandidatePaths @($Foreign) -UserProfile $Mine 6>&1 | Out-String
$refusedCode = Install-RtPythonEnv -RepoRoot $RepoRoot -Preview -CandidatePaths @($Foreign) -UserProfile $Mine 6>$null
Check "a foreign-only machine is skipped, exit 0" ($refusedCode -eq 0 -and $refusedOut -match "skipped")
Check "the skip names the foreign interpreter"   ($refusedOut -match [regex]::Escape($Foreign))
Check "the skip does not say it would install"   ($refusedOut -notmatch "Would install")
$noneOut = Install-RtPythonEnv -RepoRoot $RepoRoot -Preview -CandidatePaths @() -UserProfile $Mine 6>&1 | Out-String
Check "no candidate at all is stated"            ($noneOut -match "none was found")

# --------------------------------------------------------- the missing-file path ---
# A repository root with no requirements files at all: the step must fail by name
# rather than install a shorter list than it announced (R3).
New-Item -ItemType Directory -Path (Join-Path $Fake "empty-root") -Force | Out-Null
$EmptyRoot = Join-Path $Fake "empty-root"
$missing = Install-RtPythonEnv -RepoRoot $EmptyRoot -CandidatePaths @($Py311) -UserProfile $Mine 6>&1 | Out-String
$missingCode = Install-RtPythonEnv -RepoRoot $EmptyRoot -CandidatePaths @($Py311) -UserProfile $Mine 6>$null
Check "a missing requirements file exits 1"      ($missingCode -eq 1)
Check "a missing requirements file fails"        ($missing -match "requirements file not found")
Check "the failure names the path"               ($missing -match ([regex]::Escape("paper2talk")))
Check "nothing was created in the empty root"    (-not (Test-Path (Join-Path $EmptyRoot ".venv-skills")))

# ------------------------------------------------ run from a linked worktree ---
# The environment belongs to the MAIN clone. Real git, so the lookup is the real one.
if ($null -ne (Get-Command git -ErrorAction SilentlyContinue)) {
    $Main = Join-Path $Fake "gamma-clone"
    $Wt   = Join-Path $Fake "gamma-linked"
    New-Item -ItemType Directory -Path $Main -Force | Out-Null
    $saved = $ErrorActionPreference; $ErrorActionPreference = "Continue"
    & git -C $Main init --quiet 2>$null | Out-Null
    & git -C $Main -c user.name=Fictitious -c user.email=fictitious@example.org commit --quiet --allow-empty -m init 2>$null | Out-Null
    & git -C $Main worktree add --quiet --detach $Wt 2>$null | Out-Null
    $ErrorActionPreference = $saved
    foreach ($r in $reqs) {
        $dest = Join-Path $Wt ($r.Path -replace '/', '\')
        New-Item -ItemType Directory -Path (Split-Path $dest -Parent) -Force | Out-Null
        Copy-Item $r.Full $dest
    }
    $wtOut = Install-RtPythonEnv -RepoRoot $Wt -Preview -CandidatePaths @($Py311) -UserProfile $Mine 6>&1 | Out-String
    Check "from a worktree the preview names the main clone" ($wtOut -match "linked worktree" -and $wtOut -match [regex]::Escape((Get-RtMainRepoRoot -RepoRoot $Wt)))
    Check "from a worktree nothing is created there"          (-not (Test-Path (Join-Path $Wt ".venv-skills")))
    Check "from a worktree nothing is created in the main clone" (-not (Test-Path (Join-Path $Main ".venv-skills")))
} else {
    Write-Host "  SKIP  worktree target (git is not installed)" -ForegroundColor Yellow
}

# ------------------------------------------------------------ setup.ps1 wiring ---
$setup = Get-Content (Join-Path $RepoRoot "setup.ps1") -Raw -Encoding UTF8
Check "setup.ps1 declares -InstallPython"        ($setup -match '\[switch\]\$InstallPython')
Check "setup.ps1 declares -Python"               ($setup -match '\[string\]\$Python')
Check "setup.ps1 loads rt-venv.ps1 first"        ($setup.IndexOf("rt-venv.ps1") -ge 0 -and $setup.IndexOf("rt-venv.ps1") -lt $setup.IndexOf("rt-python-env.ps1"))
Check "setup.ps1 loads rt-python-env.ps1"        ($setup -match ([regex]::Escape("rt-python-env.ps1")))
Check "setup.ps1 passes -Python through"         ($setup -match 'Install-RtPythonEnv[^\r\n]*-Python \$Python')
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
