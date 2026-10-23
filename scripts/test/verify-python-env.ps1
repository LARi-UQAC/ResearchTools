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
$reqs = @(@(Get-RtEnvironments -RepoRoot $RepoRoot | Where-Object { $_.Name -eq ".venv-skills" })[0].Requirements)
Check "the list is not empty"                    ($reqs.Count -ge 1)
Check "every requirements file exists"           (@($reqs | Where-Object { -not $_.Exists }).Count -eq 0)
Check "every entry says which suite needs it"    (@($reqs | Where-Object { [string]::IsNullOrWhiteSpace($_.Why) }).Count -eq 0)
Check "paper2talk is covered"                    (@($reqs | Where-Object { $_.Path -match 'paper2talk' }).Count -eq 1)
Check "recommendation-letter is covered"         (@($reqs | Where-Object { $_.Path -match 'recommendation-letter' }).Count -eq 1)
# 2026-10-16: the skills the repository RUNS are covered too, not the test suite alone.
Check "scopus is covered"                        (@($reqs | Where-Object { $_.Path -match 'scopus' }).Count -eq 1)
Check "extract-statistic is covered"             (@($reqs | Where-Object { $_.Path -match 'extract-statistic' }).Count -eq 1)
$stat = @($reqs | Where-Object { $_.Path -match 'extract-statistic' })[0]
# D4 (owner, 2026-10-22): docling is installed, torch tree included, so nothing is excluded.
Check "the extract-statistic entry excludes nothing (docling is installed)" ($stat.Exclude.Count -eq 0)
$scopus = @($reqs | Where-Object { $_.Path -match 'scopus' })[0]
Check "scopus excludes nothing"                  ($scopus.Exclude.Count -eq 0)
# 2026-10-22: every requirements.txt under .claude\skills is named in the data file, so a file
# added to a skill later and forgotten here is reported by path.
function Get-RtUnregisteredRequirements([string]$Root, [object[]]$Environments) {
    $named = @{}
    foreach ($e in $Environments) { foreach ($r in @($e.Requirements)) { $named[($r.Path -replace '\\', '/').ToLowerInvariant()] = 1 } }
    $skills = Join-Path $Root ".claude\skills"
    if (-not (Test-Path $skills)) { return @() }
    foreach ($f in @(Get-ChildItem $skills -Recurse -Filter "requirements.txt" -File)) {
        $rel = $f.FullName.Substring($Root.TrimEnd('\').Length + 1) -replace '\\', '/'
        if (-not $named.ContainsKey($rel.ToLowerInvariant())) { $rel }
    }
}
$unregistered = @(Get-RtUnregisteredRequirements $RepoRoot @(Get-RtEnvironments -RepoRoot $RepoRoot))
Check "every requirements.txt under .claude/skills is named in the data file" ($unregistered.Count -eq 0)
foreach ($u in $unregistered) { Write-Host "        not in the data file: $u" -ForegroundColor DarkGray }
$regFix = Join-Path $Fake "registry-root"
$extraReq = Join-Path $regFix ".claude\skills\zeta-fictitious\scripts\requirements.txt"
New-Item -ItemType Directory -Path (Split-Path $extraReq -Parent) -Force | Out-Null
Set-Content $extraReq "acme-widget==1.0" -Encoding ASCII
$regFound = @(Get-RtUnregisteredRequirements $regFix @(Get-RtEnvironments -RepoRoot $regFix))
Check "(control) an unregistered requirements file is reported by its path" ($regFound -contains ".claude/skills/zeta-fictitious/scripts/requirements.txt")

# pypdf is pinned in four requirements files. Measured 2026-10-16 by a pip --dry-run: running
# -InstallPython would have DOWNGRADED the installed pypdf 6.19.0 to the paper2talk pin
# 6.15.0 (11 known CVEs; 6.16.1 elsewhere had 8). Offline, what can be asserted is that the
# pins agree, since a file left behind is exactly how that happened.
$pypdfPins = @()
foreach ($rel in @(".claude\skills\paper2talk\scripts\requirements.txt", ".claude\skills\narrative-cv\scripts\requirements.txt",
                   ".claude\skills\form-service\scripts\requirements.txt", "deploy\form-service\requirements.txt")) {
    $m = [regex]::Match((Get-Content (Join-Path $RepoRoot $rel) -Raw -Encoding UTF8), '(?m)^pypdf==(\S+)')
    $pypdfPins += [pscustomobject]@{ File = $rel; Version = $(if ($m.Success) { $m.Groups[1].Value } else { "" }) }
}
Check "every file that pins pypdf pins it exactly"            (@($pypdfPins | Where-Object { -not $_.Version }).Count -eq 0)
Check "the four pypdf pins agree on one version"              (@($pypdfPins | Select-Object -ExpandProperty Version -Unique).Count -eq 1)
Check "(control) the agreement check can see a stale pin"     (@(@("6.19.0", "6.15.0") | Select-Object -Unique).Count -eq 2)

# 2026-10-22: one pin per library across EVERY requirements file, not pypdf alone. Reads the
# files the data file names for both environments, every requirements.txt under
# .claude\skills (a file not yet in the data file still pins a library a skill runs with),
# and deploy\form-service\requirements.txt.
function Get-RtPinnedVersions([string]$Path) {
    foreach ($line in @(Get-Content -LiteralPath $Path -Encoding UTF8)) {
        $m = [regex]::Match($line, '^\s*([A-Za-z0-9][A-Za-z0-9._-]*)(\[[^\]]*\])?\s*==\s*([^\s;#]+)')
        if ($m.Success) {
            [pscustomobject]@{ Name = ($m.Groups[1].Value.ToLowerInvariant() -replace '[-_.]+', '-'); Version = $m.Groups[3].Value; File = $Path }
        }
    }
}
function Get-RtPinConflicts([string[]]$Files) {
    $pins = @(foreach ($f in $Files) { Get-RtPinnedVersions $f })
    foreach ($g in @($pins | Group-Object Name)) {
        $versions = @($g.Group | Select-Object -ExpandProperty Version -Unique)
        if ($versions.Count -gt 1) {
            [pscustomobject]@{ Name = $g.Name; Detail = (($g.Group | ForEach-Object { "$($_.Version) in $($_.File)" }) -join "; ") }
        }
    }
}
$pinFiles = @(@(Get-RtEnvironments -RepoRoot $RepoRoot) | ForEach-Object { $_.Requirements } | ForEach-Object { $_.Full })
$pinFiles += @(Get-ChildItem (Join-Path $RepoRoot ".claude\skills") -Recurse -Filter "requirements.txt" -File | ForEach-Object { $_.FullName })
$pinFiles += (Join-Path $RepoRoot "deploy\form-service\requirements.txt")
$pinFiles = @($pinFiles | Where-Object { Test-Path -LiteralPath $_ } | Sort-Object -Unique)
$conflicts = @(Get-RtPinConflicts $pinFiles)
Check "no library is pinned to two different versions across the requirements files" ($conflicts.Count -eq 0)
foreach ($c in $conflicts) { Write-Host "        $($c.Name): $($c.Detail)" -ForegroundColor DarkGray }
$pinFix = Join-Path $Fake "pin-fixtures"
New-Item -ItemType Directory -Path $pinFix -Force | Out-Null
Set-Content (Join-Path $pinFix "a.txt") "acme_widget==1.0.0`nshared==2.0" -Encoding ASCII
Set-Content (Join-Path $pinFix "b.txt") "Acme-Widget==1.1.0 ; sys_platform == 'win32'`nshared==2.0" -Encoding ASCII
$fixConflicts = @(Get-RtPinConflicts @((Join-Path $pinFix "a.txt"), (Join-Path $pinFix "b.txt")))
Check "(control) two files pinning one library differently are reported, naming both files" ($fixConflicts.Count -eq 1 -and $fixConflicts[0].Name -eq "acme-widget" -and $fixConflicts[0].Detail -match "a\.txt" -and $fixConflicts[0].Detail -match "b\.txt")

# D5 (owner, 2026-10-22): the nvidia CUDA packages belong in .venv-skills, but PyPI ships them
# for Windows and Linux only (file lists read 2026-10-22), so each line carries a platform marker.
function Get-RtUnmarkedNvidia([string[]]$Lines) {
    @($Lines | Where-Object { $_ -match '^\s*nvidia-[A-Za-z0-9._-]+' -and $_ -notmatch ';\s*sys_platform' })
}
$rtObserve = Get-Content (Join-Path $RepoRoot ".claude\skills\rt-observe\scripts\requirements.txt") -Encoding UTF8
Check "the three nvidia lines carry a platform marker" (@($rtObserve | Where-Object { $_ -match '^\s*nvidia-' }).Count -eq 3 -and @(Get-RtUnmarkedNvidia $rtObserve).Count -eq 0)
Check "(control) an nvidia line without a marker is found" (@(Get-RtUnmarkedNvidia @("nvidia-cublas-cu12==1.0  # same", "requests==2.0")).Count -eq 1)

# D3 (owner, 2026-10-22): requirements-docs.txt alone describes .venv-docs, every line pinned
# exactly, and without the eleven lines pip-audit leaves behind (required by no installed package).
$docsLines = @(Get-Content (Join-Path $RepoRoot "requirements-docs.txt") -Encoding UTF8 | Where-Object { $_ -notmatch '^\s*(#|$)' })
Check "requirements-docs.txt pins every line with an exact version" ($docsLines.Count -ge 1 -and @($docsLines | Where-Object { $_ -notmatch '^\s*[A-Za-z0-9][A-Za-z0-9._\[\]-]*==\S+' }).Count -eq 0)
$orphans = @("cachecontrol", "defusedxml", "filelock", "markdown-it-py", "mdurl", "msgpack", "pyparsing", "rich", "sortedcontainers", "tomli", "tomli-w")
$docsNames = @($docsLines | ForEach-Object { ([regex]::Match($_, '^\s*([A-Za-z0-9][A-Za-z0-9._-]*)').Groups[1].Value.ToLowerInvariant() -replace '[-_.]+', '-') })
Check "requirements-docs.txt holds none of the eleven lines pip-audit leaves behind" (@($docsNames | Where-Object { $orphans -contains $_ }).Count -eq 0)
foreach ($o in @($docsNames | Where-Object { $orphans -contains $_ })) { Write-Host "        orphan still listed: $o" -ForegroundColor DarkGray }

# Negative control: the Exists flag has to be able to say no, or the check above
# passes on a list of files that were never looked for.
$ghost = @(Get-RtEnvironments -RepoRoot (Join-Path $Fake "no-such-repo") | ForEach-Object { $_.Requirements })
Check "Exists can report false"                  (@($ghost | Where-Object { $_.Exists }).Count -eq 0)

$tools = @(@(Get-RtEnvironments -RepoRoot $RepoRoot | Where-Object { $_.Name -eq ".venv-skills" })[0].Tools)
Check "pip-audit is installed by the installer"  (@($tools | Where-Object { $_.Spec -match '^pip-audit==' }).Count -eq 1)

# ------------------------------------------------------- the two environments ---
# 2026-10-22 (D1, D2): one data file declares .venv-skills and .venv-docs. Each rule has a
# failure case against a temp copy of the JSON passed with -Path (R20).
$envs = @()
try { $envs = @(Get-RtEnvironments -RepoRoot $RepoRoot) } catch { Write-Host "  (loader threw: $($_.Exception.Message))" -ForegroundColor Red }
Check "the data file declares three environments: .venv-skills, .venv-docs, .venv-pdf2md" ($envs.Count -eq 3 -and $envs[0].Name -eq ".venv-skills" -and $envs[1].Name -eq ".venv-docs" -and $envs[2].Name -eq ".venv-pdf2md")
# D9 (owner, 2026-10-22): mineru needs gradio, every gradio caps pillow below 13.0.0, so pdf2md
# lives in its own environment and .venv-skills can carry the fixed pillow.
$pdfEnv = @($envs | Where-Object { $_.Name -eq ".venv-pdf2md" })
Check "the .venv-pdf2md environment lists exactly the pdf2md file and no tool" ($pdfEnv.Count -eq 1 -and @($pdfEnv[0].Requirements).Count -eq 1 -and $pdfEnv[0].Requirements[0].Path -eq ".claude/skills/pdf2md/scripts/requirements.txt" -and @($pdfEnv[0].Tools).Count -eq 0)
Check "the pdf2md file is not in .venv-skills" (@(@($envs | Where-Object { $_.Name -eq ".venv-skills" }) | ForEach-Object { $_.Requirements } | Where-Object { $_.Path -match 'pdf2md' }).Count -eq 0)
Check "every environment has a why and every requirement a path and a why" ($envs.Count -ge 1 -and @($envs | Where-Object { [string]::IsNullOrWhiteSpace($_.Why) }).Count -eq 0 -and @($envs | ForEach-Object { $_.Requirements } | Where-Object { [string]::IsNullOrWhiteSpace($_.Path) -or [string]::IsNullOrWhiteSpace($_.Why) }).Count -eq 0)
$docsEnv  = @($envs | Where-Object { $_.Name -eq ".venv-docs" })
Check "the .venv-docs environment lists exactly requirements-docs.txt and no tool" ($docsEnv.Count -eq 1 -and @($docsEnv[0].Requirements).Count -eq 1 -and $docsEnv[0].Requirements[0].Path -eq "requirements-docs.txt" -and @($docsEnv[0].Tools).Count -eq 0)
$skillEnv = @($envs | Where-Object { $_.Name -eq ".venv-skills" })
Check "the .venv-skills environment carries pip-audit as its tool" ($skillEnv.Count -eq 1 -and @($skillEnv[0].Tools | Where-Object { $_.Spec -match '^pip-audit==' }).Count -eq 1)

New-Item -ItemType Directory -Path $Fake -Force | Out-Null
$realData = Get-Content (Join-Path $RepoRoot "scripts\lib\rt-python-requirements.json") -Raw -Encoding UTF8 | ConvertFrom-Json
function Test-BadData([string]$label, [scriptblock]$mutate, [string]$key) {
    $copy = $script:realData | ConvertTo-Json -Depth 20 | ConvertFrom-Json
    try { & $mutate $copy } catch { Check "a data file with $label can be built (schema present)" $false; return }
    $path = Join-Path $script:Fake "bad-$label.json"
    [System.IO.File]::WriteAllText($path, ($copy | ConvertTo-Json -Depth 20), (New-Object System.Text.UTF8Encoding($false)))
    $msg = ""
    try { $null = @(Get-RtEnvironments -RepoRoot $script:RepoRoot -Path $path) } catch { $msg = $_.Exception.Message }
    Check "a data file with $label is refused, naming the file and $key" ($msg -ne "" -and $msg -match [regex]::Escape("bad-$label.json") -and $msg -match [regex]::Escape($key))
}
Test-BadData "no-environments"  { param($d) $d.PSObject.Properties.Remove("environments") } "environments"
Test-BadData "no-name"          { param($d) $d.environments[1].PSObject.Properties.Remove("name") } "environments[1].name"
Test-BadData "duplicate-name"   { param($d) $d.environments[1].name = $d.environments[0].name } "environments[1].name"
Test-BadData "empty-requirements" { param($d) $d.environments[1].requirements = @() } "environments[1].requirements"

# ------------------------------------------------------ the docling exclusion ---
$real = Get-Content (Join-Path $RepoRoot ".claude\skills\extract-statistic\scripts\requirements.txt") -Encoding UTF8
# The exclude key stays supported (D4): proven on the real file with a fixture exclusion.
$kept = @(Get-RtFilteredRequirementLines -Lines $real -Exclude @("docling"))
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
$spell = @("Docling_Core==1.0", "docling.core==1.0", "DOCLING-CORE>=1", "docling-coreutils==1", "requests==2")
$spelled = @(Get-RtFilteredRequirementLines -Lines $spell -Exclude @("docling-core"))
Check "PEP 503: _ . and case spell the same package"     ($spelled.Count -eq 2 -and ($spelled -contains "requests==2") -and ($spelled -contains "docling-coreutils==1"))
Check "an include line is detected (-r, -c, long forms)" ((Test-RtRequirementHasInclude -Lines @("requests==2.0", "-r base.txt")) -and (Test-RtRequirementHasInclude -Lines @("-c c.txt")) -and (Test-RtRequirementHasInclude -Lines @("--requirement=base.txt")))
Check "a plain file has no include (control)"      (-not (Test-RtRequirementHasInclude -Lines $real))
Check "a comment mentioning -r is not an include"  (-not (Test-RtRequirementHasInclude -Lines @("# pip install -r x", "requests==2.0", "")))
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

# A throwaway root holding copies of the requirements files and NO environment, so the
# preview exercises the interpreter-selection path whatever this machine's own
# .venv-skills looks like (R21). Pointed at the real repository, the preview would find
# the existing environment and take the reuse branch instead.
# Every requirements file of every environment, so a fake root is complete for both.
$allReqs = @($envs | ForEach-Object { $_.Requirements })
function New-StubVenv([string]$root, [string]$name) {
    $dir = Join-Path $root "$name\Scripts"
    New-Item -ItemType Directory -Path $dir -Force | Out-Null
    Set-Content -Path (Join-Path $dir "python.exe") -Value "stub" -Encoding ASCII
}
function Remove-StubVenvs([string]$root) {
    foreach ($n in @(".venv-skills", ".venv-docs", ".venv-pdf2md")) { Remove-Item (Join-Path $root $n) -Recurse -Force -ErrorAction SilentlyContinue }
}
$FreshRoot = Join-Path $Fake "fresh-root"
foreach ($r in $allReqs) {
    $dest = Join-Path $FreshRoot ($r.Path -replace '/', '\')
    New-Item -ItemType Directory -Path (Split-Path $dest -Parent) -Force | Out-Null
    Copy-Item $r.Full $dest
}

# ----------------------------------------------------------------- the dry run ---
# R16: a dry run touches nothing. Pointed at a fresh fake root with no environment, so that
# a slip would show as a created directory there, and the real environment is stamped. The
# candidates are injected so the result does not depend on this machine's PATH (R21).
$previewOut  = Install-RtPythonEnv -RepoRoot $FreshRoot -Preview -CandidatePaths @($Foreign, $Py311) -UserProfile $Mine 6>&1 | Out-String
$previewCode = Install-RtPythonEnv -RepoRoot $FreshRoot -Preview -CandidatePaths @($Foreign, $Py311) -UserProfile $Mine 6>$null
Check "-Preview returns 0"                       ($previewCode -eq 0)
Check "-Preview says what it would install"      ($previewOut -match "Would install")
Check "-Preview names pip-audit"                 ($previewOut -match "pip-audit")
Check "-Preview names a requirements file"       ($previewOut -match ([regex]::Escape("requirements.txt")))
Check "-Preview names no exclusion (docling is installed)" ($previewOut -notmatch "without: docling")
Check "-Preview names the interpreter it chose"  ($previewOut -match [regex]::Escape($Py311))
Check "-Preview says the probe is not run"       ($previewOut -match "NOT run")
Check "-Preview created no environment"          ((Test-Path $RealVenv) -eq $venvBefore -and -not (Test-Path (Join-Path $FreshRoot ".venv-skills")))

# Only a foreign interpreter on offer: skipped with the reason, exit 0 (setup carries on).
$refusedOut  = Install-RtPythonEnv -RepoRoot $FreshRoot -Preview -CandidatePaths @($Foreign) -UserProfile $Mine 6>&1 | Out-String
$refusedCode = Install-RtPythonEnv -RepoRoot $FreshRoot -Preview -CandidatePaths @($Foreign) -UserProfile $Mine 6>$null
Check "a foreign-only machine is skipped, exit 0" ($refusedCode -eq 0 -and $refusedOut -match "skipped")
Check "the skip names the foreign interpreter"   ($refusedOut -match [regex]::Escape($Foreign))
Check "the skip does not say it would install"   ($refusedOut -notmatch "Would install")
$noneOut = Install-RtPythonEnv -RepoRoot $FreshRoot -Preview -CandidatePaths @() -UserProfile $Mine 6>&1 | Out-String
Check "no candidate at all is stated"            ($noneOut -match "none was found")

# ------------------------------------------- an existing environment is reused ---
# Code-review finding: a healthy .venv-skills used to be refused, or delayed by a scratch
# venv probe per candidate, because no usable BASE python was on PATH - although pip runs
# from the environment's own interpreter. A fake root with the requirements files and a
# stub venv interpreter, and NO candidate at all, must still preview as a reuse.
$ReuseRoot = Join-Path $Fake "reuse-root"
foreach ($r in $allReqs) {
    $dest = Join-Path $ReuseRoot ($r.Path -replace '/', '\')
    New-Item -ItemType Directory -Path (Split-Path $dest -Parent) -Force | Out-Null
    Copy-Item $r.Full $dest
}
New-StubVenv $ReuseRoot ".venv-skills"
New-StubVenv $ReuseRoot ".venv-docs"
New-StubVenv $ReuseRoot ".venv-pdf2md"
$reuseOut = Install-RtPythonEnv -RepoRoot $ReuseRoot -Preview -CandidatePaths @() -UserProfile $Mine 6>&1 | Out-String
Check "an existing venv is reused with no base python at all" ($reuseOut -match "no base interpreter needed" -and $reuseOut -match "Would install")
Check "the reuse preview does not say it was skipped"        ($reuseOut -notmatch "skipped")
$tripwire2 = { param($p) throw "the probe must not run when the environment exists" }
$pickReuse = Select-RtBasePython -Candidates @($Py312) -UserProfile $Mine -Probe $tripwire2 -SkipProbe
Check "(control) selection without an environment still works" ($pickReuse.Python -eq $Py312)
Remove-StubVenvs $ReuseRoot
$noVenvOut = Install-RtPythonEnv -RepoRoot $ReuseRoot -Preview -CandidatePaths @() -UserProfile $Mine 6>&1 | Out-String
Check "(control) the same root WITHOUT the venv is skipped, naming why" ($noVenvOut -match "skipped" -and $noVenvOut -match "none was found")

# No profile known: ownership cannot be judged, and nothing throws.
$noProfile = $null
try { $noProfile = Test-RtInterpreterOwner -Path $Py311 -UserProfile "" } catch { $noProfile = "THREW: $($_.Exception.Message)" }
Check "an empty profile does not throw and does not refuse" ($noProfile -eq "")

# -Python while an environment exists is SAID to be ignored, never swallowed.
$ignoredOut = Install-RtPythonEnv -RepoRoot $ReuseRoot -Preview -Python $Py311 -CandidatePaths @() -UserProfile $Mine 6>&1 | Out-String
New-StubVenv $ReuseRoot ".venv-skills"
New-StubVenv $ReuseRoot ".venv-docs"
New-StubVenv $ReuseRoot ".venv-pdf2md"
$ignoredOut2 = Install-RtPythonEnv -RepoRoot $ReuseRoot -Preview -Python $Py311 -CandidatePaths @() -UserProfile $Mine 6>&1 | Out-String
Check "-Python is reported ignored when the environment exists" ($ignoredOut2 -match "-Python was ignored")
Check "(control) with no environment -Python is not reported ignored" ($ignoredOut -notmatch "was ignored")
Remove-StubVenvs $ReuseRoot

# A profile directly under a drive root has no profiles folder above it.
Check "a drive-root profile does not make a machine-wide install foreign" ((Test-RtInterpreterOwner -Path "D:\Program Files\Python311\python.exe" -UserProfile "D:\alice") -eq "")

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
    foreach ($r in $allReqs) {
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

# --------------------------------------------- both environments, process order ---
# 2026-10-22 (D1): -InstallPython builds .venv-skills then .venv-docs. Every process goes
# through the injected runner, so the order and the failure paths are proven with no
# interpreter executed. The runner records each call and, for `-m venv`, leaves a stub
# interpreter where the environment would be (what the installer reads back, R9). The
# scratch probe (`--without-pip`) is dropped from the order: it is not part of the install.
$script:Calls = @()
$script:FailPattern = ""
$Runner = {
    param($Exe, $Arguments)
    $a = @($Arguments)
    $joined = $a -join ' '
    $script:Calls += [pscustomobject]@{ Exe = [string]$Exe; Args = $joined }
    if ($script:FailPattern -and $joined -match $script:FailPattern) { return 1 }
    if ($a.Count -ge 2 -and $a[0] -eq '-m' -and $a[1] -eq 'venv') {
        $made = Join-Path $a[-1] 'Scripts\python.exe'
        New-Item -ItemType Directory -Path (Split-Path $made -Parent) -Force | Out-Null
        Set-Content -Path $made -Value 'stub' -Encoding ASCII
    }
    return 0
}
function New-RunRoot([string]$name, [switch]$NoDocsFile) {
    $root = Join-Path $script:Fake $name
    foreach ($r in $script:allReqs) {
        if ($NoDocsFile -and $r.Path -eq "requirements-docs.txt") { continue }
        $dest = Join-Path $root ($r.Path -replace '/', '\')
        New-Item -ItemType Directory -Path (Split-Path $dest -Parent) -Force | Out-Null
        Copy-Item $r.Full $dest
    }
    return $root
}
function Invoke-Install([string]$root, [hashtable]$extra = @{}) {
    $script:Calls = @()
    try {
        $items = @(Install-RtPythonEnv -RepoRoot $root -UserProfile $script:Mine -ProcessRunner $script:Runner @extra 6>&1)
    } catch {
        return [pscustomobject]@{ Code = $null; Text = "THREW: $($_.Exception.Message)"; Calls = @() }
    }
    $codes = @($items | Where-Object { $_ -is [int] })
    $text  = ($items | Where-Object { $_ -isnot [int] } | ForEach-Object { "$_" }) -join "`n"
    $real  = @($script:Calls | Where-Object { $_.Args -notmatch 'without-pip' })
    return [pscustomobject]@{ Code = $(if ($codes.Count) { $codes[-1] } else { $null }); Text = $text; Calls = $real }
}

$PreviewRoot = New-RunRoot "both-preview"
$pv = Invoke-Install $PreviewRoot @{ Preview = $true; CandidatePaths = @($Py311) }
$skillsAt = $pv.Text.IndexOf(".venv-skills"); $docsAt = $pv.Text.IndexOf(".venv-docs"); $docsFileAt = $pv.Text.IndexOf("requirements-docs.txt")
Check "the preview names .venv-skills and .venv-docs and lists requirements-docs.txt under the second" ($pv.Code -eq 0 -and $skillsAt -ge 0 -and $docsAt -gt $skillsAt -and $docsFileAt -gt $docsAt)
Check "the preview calls the runner zero times"  ($pv.Calls.Count -eq 0 -and -not (Test-Path (Join-Path $PreviewRoot ".venv-docs")))

$NoDocsRoot = New-RunRoot "no-docs-file" -NoDocsFile
$nd = Invoke-Install $NoDocsRoot @{ CandidatePaths = @($Py311) }
Check "a missing requirements-docs.txt returns 1, names the file, creates neither folder and calls the runner zero times" ($nd.Code -eq 1 -and $nd.Text -match "requirements-docs\.txt" -and -not (Test-Path (Join-Path $NoDocsRoot ".venv-skills")) -and -not (Test-Path (Join-Path $NoDocsRoot ".venv-docs")) -and $script:Calls.Count -eq 0)

$OrderRoot = New-RunRoot "order"
$or = Invoke-Install $OrderRoot @{ CandidatePaths = @($Py311) }
$skPy = Join-Path $OrderRoot ".venv-skills\Scripts\python.exe"
$dcPy = Join-Path $OrderRoot ".venv-docs\Scripts\python.exe"
$skillReqCount = @($skillEnv[0].Requirements).Count
$kinds = @($or.Calls | ForEach-Object {
    if ($_.Args -match '^-m venv ') { if ($_.Args -match 'venv-docs') { "venv-docs" } elseif ($_.Args -match 'venv-pdf2md') { "venv-pdf2md" } else { "venv-skills" } }
    elseif ($_.Args -match '^-m pip install' -and $_.Args -match 'rt-tools-') { "tool" }
    elseif ($_.Args -match '^-m pip install' -and $_.Args -match 'requirements-docs') { "docs-file" }
    elseif ($_.Args -match '^-m pip install' -and $_.Args -match 'pdf2md') { "pdf2md-file" }
    elseif ($_.Args -match '^-m pip install') { "skills-file" }
    elseif ($_.Args -match '^-m pip_audit') { "audit" }
    else { "other:" + $_.Args } })
$expected = @("venv-skills", "tool") + @(1..$skillReqCount | ForEach-Object { "skills-file" }) + @("venv-docs", "docs-file", "venv-pdf2md", "pdf2md-file") + @(1..($skillReqCount + 3) | ForEach-Object { "audit" })
Check "with a recording runner the calls come in order: venv skills, tool, skills files, venv docs, docs file, then pip_audit on every file" ($or.Code -eq 0 -and ($kinds -join ',') -eq ($expected -join ','))
if (($kinds -join ',') -ne ($expected -join ',')) { Write-Host "        got: $($kinds -join ',')" -ForegroundColor DarkGray }
$audits = @($or.Calls | Where-Object { $_.Args -match '^-m pip_audit' })
Check "every pip_audit call uses the skills interpreter, none the docs one" ($audits.Count -ge 1 -and @($audits | Where-Object { $_.Exe -ne $skPy }).Count -eq 0)
Check "no pip install of pip-audit is made with the docs interpreter" (@($or.Calls | Where-Object { $_.Exe -eq $dcPy -and ($_.Args -match 'rt-tools-' -or $_.Args -match 'pip-audit') }).Count -eq 0)
Check "pip install of the docs file uses the docs interpreter" (@($or.Calls | Where-Object { $_.Args -match 'requirements-docs' -and $_.Args -match 'pip install' -and $_.Exe -eq $dcPy }).Count -eq 1)

$script:FailPattern = 'pip install.*requirements-docs'
$FailDocsRoot = New-RunRoot "fail-docs"
$fd = Invoke-Install $FailDocsRoot @{ CandidatePaths = @($Py311) }
Check "a runner failing on the docs file returns 1 while the skills environment was installed and reported ready" ($fd.Code -eq 1 -and $fd.Text -match ("Environment ready: " + [regex]::Escape((Join-Path $FailDocsRoot ".venv-skills\Scripts\python.exe"))) -and @($fd.Calls | Where-Object { $_.Args -match 'pip install' -and $_.Exe -like '*venv-skills*' }).Count -eq ($skillReqCount + 1))

$script:FailPattern = '^-m venv .*\.venv-skills'
$FailSkillsRoot = New-RunRoot "fail-skills"
$fs = Invoke-Install $FailSkillsRoot @{ CandidatePaths = @($Py311) }
Check "a runner failing on the skills venv creation still attempts the docs environment and returns 1" ($fs.Code -eq 1 -and @($fs.Calls | Where-Object { $_.Args -match '^-m venv .*\.venv-docs' }).Count -eq 1)
$script:FailPattern = ""

$StubRoot = New-RunRoot "two-stubs"
New-StubVenv $StubRoot ".venv-skills"
New-StubVenv $StubRoot ".venv-docs"
New-StubVenv $StubRoot ".venv-pdf2md"
$st = Invoke-Install $StubRoot @{ CandidatePaths = @() }
Check "three stub existing environments are reused with no base interpreter and no venv call" ($st.Code -eq 0 -and @($st.Calls | Where-Object { $_.Args -match '^-m venv' }).Count -eq 0 -and $st.Text -notmatch "skipped" -and @($st.Calls | Where-Object { $_.Args -match 'requirements-docs' -and $_.Exe -like '*venv-docs*' }).Count -ge 1)

# ------------------------------------------------------------ setup.ps1 wiring ---
$setupText = Get-Content (Join-Path $RepoRoot "setup.ps1") -Raw -Encoding UTF8
Check "setup.ps1 contains no InstallDocs and no -InstallDocs" ($setupText -notmatch 'InstallDocs')
$setup = Get-Content (Join-Path $RepoRoot "setup.ps1") -Raw -Encoding UTF8
Check "setup.ps1 declares -InstallPython"        ($setup -match '\[switch\]\$InstallPython')
Check "setup.ps1 declares -Python"               ($setup -match '\[string\]\$Python')
Check "setup.ps1 loads rt-venv.ps1 first"        ($setup.IndexOf("rt-venv.ps1") -ge 0 -and $setup.IndexOf("rt-venv.ps1") -lt $setup.IndexOf("rt-python-env.ps1"))
Check "setup.ps1 loads rt-python-env.ps1"        ($setup -match ([regex]::Escape("rt-python-env.ps1")))
Check "setup.ps1 passes -Python through"         ($setup -match 'Install-RtPythonEnv[^\r\n]*-Python \$Python')
Check "setup.ps1 documents the switch"           ($setup -match ([regex]::Escape(".\setup.ps1 -InstallPython")))
Check "the switch has its own dispatch branch"   ($setup -match ([regex]::Escape('if ($InstallPython -and -not $All)')))
Check "Next steps names the switch"              ($setup -match "run-offline-tests.ps1 reports PASSED")
Check "the help names the three environments"    ($setup -match '-InstallPython\s+-> \.venv-skills, \.venv-docs and \.venv-pdf2md')

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
