<#
.SYNOPSIS
  Offline checks on the run record the driver writes. No model, no aider, no
  network, and nothing written outside a temporary directory.

.DESCRIPTION
  The driver spawns processes, so dot-sourcing it would start one. These checks
  therefore EXTRACT the two record functions from aider-plan.ps1 by brace
  matching and run those, which is the same reason verify-sync-writes.ps1 loads
  rt-sync.ps1 rather than install-junctions.ps1.

  Extracting from the driver rather than keeping a copy is the point: a copy
  passes forever after the driver has moved on, which is the failure this file
  exists to prevent.

  The real ~/.aider-plan is hashed before and after and asserted unchanged, the
  same discipline every verifier in this toolkit uses on a live global config.
  Worded without naming the private toolkit on purpose: the build neutralises
  that name, and a bare substitution here produced "the the toolkit repository
  verifiers". Avoiding the word is what makes the shipped copy byte-identical to
  this file, which is the whole point of the build no longer rewriting it.
#>
[CmdletBinding()]
param(
    # Which aider config the driver-driven checks pass to the driver. Left empty
    # it resolves itself, and that resolution is the whole reason the parameter
    # exists: on the machine this was written on the config is the build's saved
    # copy under .config/aider/build/, and on a student's machine that path does
    # not exist at all - setup.ps1 installs ~/.aider.conf.yml, the one file aider
    # finds by name. Until 2026-09-04 the build rewrote this path on its way into
    # the kit, so the shipped copy differed from this source by one line and the
    # fourteen driver-driven checks below had never run against the path a
    # student actually has. One file, one truth, resolved at run time.
    [string]$Config = ""
)

$ErrorActionPreference = "Stop"
# Resolved sibling-first: this file's own parent directory (the repo's
# scripts/) holds the canonical driver once this suite runs from inside
# ResearchTools. A student's installed copy has no such sibling - setup.ps1
# puts everything under $HOME/.local/bin instead - so that stays the fallback,
# never the other way around, or a student's own verifier would resolve to a
# repository that does not exist on their machine.
$scriptsDir = Split-Path $PSScriptRoot -Parent
$driver = Join-Path $scriptsDir "aider-plan.ps1"
if (-not (Test-Path -LiteralPath $driver)) {
    $driver = Join-Path $HOME ".local\bin\aider-plan.ps1"
}

$script:pass = 0
$script:fail = 0
function Check([string]$name, [scriptblock]$body) {
    try {
        $r = & $body
        if ($r) { $script:pass++; "  ok    $name" }
        else    { $script:fail++; "  FAIL  $name" }
    } catch {
        $script:fail++
        "  FAIL  $name  -> $($_.Exception.Message)"
    }
}

# --- Load the real thing ----------------------------------------------------
# Dot-sourced, not extracted. Until the driver was split on 2026-09-03 these
# functions had to be pulled out of it by brace matching, because dot-sourcing
# the driver would have started a model. Now they live in a file that starts
# nothing, so the test loads exactly what the driver loads - and if a function
# moves back, or is renamed, this fails immediately rather than testing a copy.
if (-not (Test-Path -LiteralPath $driver)) { throw "driver not found: $driver" }
$core = Join-Path $scriptsDir "aider-plan-core.ps1"
if (-not (Test-Path -LiteralPath $core)) {
    $core = Join-Path $HOME ".local\bin\aider-plan-core.ps1"
}
if (-not (Test-Path -LiteralPath $core)) { throw "aider-plan-core.ps1 not found: $core" }
. $core

foreach ($required in @("Get-RunRecordDir", "Initialize-RunRecord", "Update-RunRecord", "Get-BlockReport", "Convert-TestLogToUtf8Bom", "Get-LogText", "Get-PlanReads", "Get-PathsInText", "Get-PlanText", "Get-AuditPlanBlock", "Get-ReopenReport", "Get-QualityPrompt", "Get-QualityScore", "Format-QualityReport", "Get-TestCounts", "Get-TestInterpreter")) {
    if (-not (Get-Command $required -CommandType Function -ErrorAction SilentlyContinue)) {
        throw "$required is not defined by aider-plan-core.ps1"
    }
}

# --- Prove the real record directory never receives a record from THIS test --
#
# Not a fingerprint of the whole directory. A real run writes its own record
# there every few seconds, so comparing the directory before and after makes this
# check fail whenever anything else on the machine is working - measured
# 2026-09-03, when a night run in another project turned a green suite red for a
# reason that had nothing to do with the code.
#
# What must be proven is narrower and exact: no record NAMED FOR ONE OF THIS
# TEST'S OWN PROJECTS may appear there. The file name is a hash of the project
# path, so the names are computable, and a concurrent run cannot collide with
# them.
$realRuns = Join-Path $HOME ".aider-plan\runs"
$script:TestProjects = @()

function Record-Name([string]$project) {
    $md5 = [System.Security.Cryptography.MD5]::Create()
    return [BitConverter]::ToString(
        $md5.ComputeHash([Text.Encoding]::UTF8.GetBytes($project.ToLowerInvariant()))
    ).Replace("-", "").Substring(0, 8).ToLowerInvariant() + ".json"
}

function Note-Project([string]$project) {
    $script:TestProjects += $project
    return $project
}

function Leaked-Records {
    if (-not (Test-Path -LiteralPath $realRuns)) { return @() }
    $names = $script:TestProjects | ForEach-Object { Record-Name $_ } | Sort-Object -Unique
    return @(Get-ChildItem -LiteralPath $realRuns -File -EA SilentlyContinue |
             Where-Object { $names -contains $_.Name })
}

# --- A scratch project, and a scratch home ----------------------------------
$scratch = Join-Path $env:TEMP ("recordtest-" + [guid]::NewGuid().ToString("N").Substring(0,8))
$plansDir = Join-Path $scratch "docs\superpowers\plans"
New-Item -ItemType Directory -Force -Path $plansDir | Out-Null
$progress = Join-Path $plansDir "progress.md"
"# Progress`n`n## plan1.md`n- [x] done one`n- [ ] open one`n- [ ] open two`n- [!] blocked one" |
    Set-Content -LiteralPath $progress -Encoding UTF8

# The record directory is redirected through the environment variable the driver
# reads. $HOME itself is READ-ONLY in PowerShell, which is exactly why the driver
# had to stop hardcoding the path: with no override there is no way to test this
# without writing into the operator's real home directory.
$realRecordDir = $env:AIDER_RUN_RECORD_DIR
$env:AIDER_RUN_RECORD_DIR = Join-Path $scratch ".aider-plan\runs"
$runsDir = $env:AIDER_RUN_RECORD_DIR

# Every project this test hands to Initialize-RunRecord, so the leak check can
# name the exact files that must NOT appear in the real directory.
$script:TestProjects = @(
    (Join-Path $scratch "proj"),
    (Join-Path $scratch "other"),
    "C:\Work\Demo",
    "c:\work\demo"
)

Write-Host ""
Write-Host "== the run record, extracted from the driver =="

Check "a dry run creates no record at all" {
    Initialize-RunRecord (Join-Path $scratch "proj") $true
    Update-RunRecord @{ state = "writing" }
    -not (Test-Path -LiteralPath $runsDir)
}

Check "a real run creates exactly one record" {
    Initialize-RunRecord (Join-Path $scratch "proj") $false
    Update-RunRecord @{ state = "starting" }
    @(Get-ChildItem -LiteralPath $runsDir -Filter *.json).Count -eq 1
}

Check "the record is valid JSON" {
    $f = Get-ChildItem -LiteralPath $runsDir -Filter *.json | Select-Object -First 1
    $null = Get-Content -LiteralPath $f.FullName -Raw | ConvertFrom-Json
    $true
}

Check "it declares the schema a reader checks" {
    $f = Get-ChildItem -LiteralPath $runsDir -Filter *.json | Select-Object -First 1
    ((Get-Content -LiteralPath $f.FullName -Raw | ConvertFrom-Json).schema) -eq "aider-plan/run-record/1"
}

Check "it carries this process's pid, which is what proves liveness" {
    $f = Get-ChildItem -LiteralPath $runsDir -Filter *.json | Select-Object -First 1
    ((Get-Content -LiteralPath $f.FullName -Raw | ConvertFrom-Json).pid) -eq $PID
}

Check "the same project reuses the same file, so records do not pile up" {
    $p = Join-Path $scratch "proj"
    Initialize-RunRecord $p $false; Update-RunRecord @{ state = "a" }
    Initialize-RunRecord $p $false; Update-RunRecord @{ state = "b" }
    @(Get-ChildItem -LiteralPath $runsDir -Filter *.json).Count -eq 1
}

Check "a different project gets a different file" {
    Initialize-RunRecord (Join-Path $scratch "other") $false
    Update-RunRecord @{ state = "a" }
    @(Get-ChildItem -LiteralPath $runsDir -Filter *.json).Count -eq 2
}

Check "the file name ignores case, so one project is one record" {
    $runs = Join-Path $scratch ".aider-plan\runs"
    Get-ChildItem -LiteralPath $runs -Filter *.json | Remove-Item -Force
    Initialize-RunRecord "C:\Work\Demo" $false;  Update-RunRecord @{ state = "a" }
    Initialize-RunRecord "c:\work\demo" $false;  Update-RunRecord @{ state = "a" }
    @(Get-ChildItem -LiteralPath $runs -Filter *.json).Count -eq 1
}

# --- The ledger, which is the progression a person reads --------------------
Check "the tick counts are re-read from progress.md, never remembered" {
    Initialize-RunRecord (Join-Path $scratch "proj") $false
    Update-RunRecord @{ state = "writing" }
    $f = Join-Path $scratch ".aider-plan\runs"
    $r1 = Get-Content -LiteralPath $script:RunRecordPath -Raw | ConvertFrom-Json
    "# Progress`n`n## plan1.md`n- [x] one`n- [x] two`n- [x] three`n- [ ] four" |
        Set-Content -LiteralPath $progress -Encoding UTF8
    Update-RunRecord @{ note = "unchanged state" }
    $r2 = Get-Content -LiteralPath $script:RunRecordPath -Raw | ConvertFrom-Json
    ($r1.steps_done -eq 1) -and ($r2.steps_done -eq 3) -and ($r2.steps_open -eq 1)
}

Check "a blocked step is counted as blocked, not as open" {
    "# Progress`n`n## plan1.md`n- [!] blocked`n- [ ] open" |
        Set-Content -LiteralPath $progress -Encoding UTF8
    Update-RunRecord @{ note = "x" }
    $r = Get-Content -LiteralPath $script:RunRecordPath -Raw | ConvertFrom-Json
    ($r.steps_blocked -eq 1) -and ($r.steps_open -eq 1)
}

Check "audit.md's size is read from disk on every update" {
    "## plan1.md`n1. a finding" | Set-Content -LiteralPath (Join-Path $plansDir "audit.md") -Encoding UTF8
    Update-RunRecord @{ note = "x" }
    $r = Get-Content -LiteralPath $script:RunRecordPath -Raw | ConvertFrom-Json
    $r.audit_bytes -gt 0
}

# --- state_since, which is what makes "how long has it been doing this" work -
Check "state_since moves when the state changes" {
    Initialize-RunRecord (Join-Path $scratch "proj") $false
    Update-RunRecord @{ state = "writing" }
    $p = $script:RunRecordPath
    $a = (Get-Content -LiteralPath $p -Raw | ConvertFrom-Json).state_since
    Start-Sleep -Milliseconds 1100
    Update-RunRecord @{ state = "auditing" }
    $b = (Get-Content -LiteralPath $p -Raw | ConvertFrom-Json).state_since
    $a -ne $b
}

Check "state_since does NOT move on an update that keeps the state" {
    $p = $script:RunRecordPath
    $a = (Get-Content -LiteralPath $p -Raw | ConvertFrom-Json).state_since
    Start-Sleep -Milliseconds 1100
    Update-RunRecord @{ note = "still auditing" }
    $b = (Get-Content -LiteralPath $p -Raw | ConvertFrom-Json).state_since
    $a -eq $b
}

Check "updated moves even when the state does not" {
    $p = $script:RunRecordPath
    $a = (Get-Content -LiteralPath $p -Raw | ConvertFrom-Json).updated
    Start-Sleep -Milliseconds 1100
    Update-RunRecord @{ note = "another note" }
    $b = (Get-Content -LiteralPath $p -Raw | ConvertFrom-Json).updated
    $a -ne $b
}

Check "an arbitrary field is merged rather than replacing the record" {
    Update-RunRecord @{ plan = "plan7.md"; round = 3 }
    $r = Get-Content -LiteralPath $script:RunRecordPath -Raw | ConvertFrom-Json
    ($r.plan -eq "plan7.md") -and ($r.round -eq 3) -and ($r.schema -eq "aider-plan/run-record/1")
}

Check "no .tmp file survives, so a reader never catches a half-written record" {
    Update-RunRecord @{ note = "x" }
    @(Get-ChildItem -LiteralPath $runsDir -Filter *.tmp).Count -eq 0
}

Check "an unwritable target is swallowed, never thrown at the run" {
    # The record is a window onto the work, not the work. Point it at a path that
    # cannot be created and require that Update-RunRecord still returns.
    $script:RunRecordPath = "Z:\no-such-drive\record.json"
    Update-RunRecord @{ state = "writing" }
    $true
}

Check "Update-RunRecord before Initialize-RunRecord does nothing and does not throw" {
    $script:RunRecord = $null
    $script:RunRecordPath = ""
    Update-RunRecord @{ state = "writing" }
    $true
}

# --- Teardown ---------------------------------------------------------------
$env:AIDER_RUN_RECORD_DIR = $realRecordDir
Remove-Item -LiteralPath $scratch -Recurse -Force -EA SilentlyContinue

# --- The refusals -----------------------------------------------------------
# These need the driver's own flow, not an extracted function, so the driver is
# INVOKED with -DryRun on a deliberately broken fixture. A dry run starts no
# model: it probes which tag would be resolved and stops, which costs seconds.
#
# Every case asserts exit 2 - a refusal by design (R12) - AND that the message
# names the thing that is missing. A refusal nobody can act on is a crash with
# better manners.

# Resolution order, and it is stated rather than guessed: an explicit -Config
# wins, then this repository's own build copy, then this machine's build copy,
# then the installed ~/.aider.conf.yml that every student has. None of the four
# present is a refusal that NAMES all four (R3, R12) - a silent fallback here
# would report a broken driver when the only thing missing is a config file.
$skillRoot = Split-Path $scriptsDir -Parent
$conf = ""
$confCandidates = @()
if ($Config -ne "") { $confCandidates += $Config }
$confCandidates += (Join-Path $skillRoot "scripts\build\aider.conf.yml.saved")
$confCandidates += (Join-Path $HOME ".config\aider\build\aider.conf.yml.saved")
$confCandidates += (Join-Path $HOME ".aider.conf.yml")
foreach ($candidate in $confCandidates) {
    if (Test-Path -LiteralPath $candidate) { $conf = $candidate; break }
}
if ($conf -eq "") {
    Write-Host "REFUSED: no aider config found. Tried, in order:" -ForegroundColor Red
    $confCandidates | ForEach-Object { Write-Host "  $_" }
    Write-Host "  Pass one with -Config <path>, or install the kit with setup.ps1."
    exit 2
}
Write-Host ("config      : {0}" -f $conf)
$budget = Join-Path $skillRoot "config\context-budget.json"
if (-not (Test-Path -LiteralPath $budget)) {
    $budget = Join-Path $HOME ".config\aider\context-budget.json"
}
# The repository's config\ is the kit TEMPLATE: its always-on paths start with
# the home placeholder that setup.ps1 substitutes on install (forward slashes,
# as setup.ps1's $homeFwd), so the driver is handed a copy carrying this
# machine's home - the same substitution, not a second hand-kept file. The
# token is ASSEMBLED, never written literally, because this file ships in the
# kit and setup.ps1 would otherwise substitute it too (see aider-night.ps1).
$homeToken  = "{{" + "HOME" + "}}"
$budgetText = Get-Content -LiteralPath $budget -Raw -Encoding UTF8
if ($budgetText.Contains($homeToken)) {
    $resolvedDir = Join-Path $env:TEMP ("aider-budget-" + [guid]::NewGuid().ToString("N").Substring(0,8))
    New-Item -ItemType Directory -Force -Path $resolvedDir | Out-Null
    $resolved = Join-Path $resolvedDir "context-budget.json"
    # The always-on files (conventions.md, rules.md) are rendered to THIS skill's own config folder, as the
    # skills are below, and not to ~/.config/aider: that folder holds the installed copy of whoever runs the
    # check, so the result depended on which kit version that machine had installed (R21).
    $budgetText = $budgetText.Replace($homeToken + "/.config/aider", ((Join-Path $skillRoot "config") -replace '\\', '/'))
    [System.IO.File]::WriteAllText($resolved, $budgetText.Replace($homeToken, ($HOME -replace '\\', '/')),
                                   (New-Object System.Text.UTF8Encoding $false))
    # The per-stage skills are mandatory, and the driver looks for skills.json
    # beside the budget file. Render it the same way, pointing its files at this
    # skill's own config folder so the check needs nothing installed.
    $skillsSrc = Join-Path $skillRoot "config\skills.json"
    if (Test-Path -LiteralPath $skillsSrc) {
        $skillsText = Get-Content -LiteralPath $skillsSrc -Raw -Encoding UTF8
        $cfgFwd = ((Join-Path $skillRoot "config") -replace '\\', '/')
        $skillsText = $skillsText.Replace($homeToken + "/.config/aider", $cfgFwd)
        [System.IO.File]::WriteAllText((Join-Path $resolvedDir "skills.json"), $skillsText,
                                       (New-Object System.Text.UTF8Encoding $false))
    }
    Write-Host ("budget      : {0} (template, home substituted)" -f $budget)
    $budget = $resolved
}
$testCmd = 'python -m unittest discover -s Test -p "test_*.py"'

function New-Fixture {
    $root = Join-Path $env:TEMP ("refusal-" + [guid]::NewGuid().ToString("N").Substring(0,8))
    $p = Join-Path $root "docs\superpowers\plans"
    New-Item -ItemType Directory -Force -Path $p, (Join-Path $root "Test") | Out-Null
    Push-Location $root
    & cmd /c "git init -q -b work . 2>NUL"
    "def add(a, b):`n    return a + b" | Set-Content -LiteralPath (Join-Path $root "calc.py") -Encoding UTF8
    "import unittest" | Set-Content -LiteralPath (Join-Path $root "Test\test_calc.py") -Encoding UTF8
    & cmd /c "git add -A 2>NUL"
    & cmd /c "git commit -qm seed 2>NUL"
    Pop-Location
    "# Spec" | Set-Content -LiteralPath (Join-Path $p "spec.md") -Encoding UTF8
    "# Progress`n`n## plan1.md`n- [ ] add is_large to calc.py" | Set-Content -LiteralPath (Join-Path $p "progress.md") -Encoding UTF8
    "# Plan 1`n`n1. Add is_large(n) to calc.py." | Set-Content -LiteralPath (Join-Path $p "plan1.md") -Encoding UTF8
    return $root
}

function Invoke-Driver([string]$root, [hashtable]$extra) {
    Push-Location $root
    try {
        $a = @{ DryRun = $true; Config = $conf; BudgetFile = $budget; TestCommand = $testCmd }
        foreach ($k in $extra.Keys) { $a[$k] = $extra[$k] }
        $out = & $driver @a *>&1
        return @{ code = $LASTEXITCODE; text = (($out | ForEach-Object { $_.ToString() }) -join "`n") }
    } finally { Pop-Location }
}

Write-Host ""
Write-Host "== the refusals, driven through the real driver =="

Check "POSITIVE CONTROL: a complete project starts, or every refusal below is meaningless" {
    $r = Invoke-Driver (New-Fixture) @{}
    ($r.code -eq 0) -and ($r.text -match "Plans: plan1\.md")
}

Check "no plans directory is refused, and it is named" {
    $root = New-Fixture
    Remove-Item -LiteralPath (Join-Path $root "docs") -Recurse -Force
    $r = Invoke-Driver $root @{}
    ($r.code -eq 2) -and ($r.text -match "REFUSED") -and ($r.text -match "plans")
}

Check "a missing spec.md is refused by name" {
    $root = New-Fixture
    Remove-Item -LiteralPath (Join-Path $root "docs\superpowers\plans\spec.md") -Force
    $r = Invoke-Driver $root @{}
    ($r.code -eq 2) -and ($r.text -match "spec\.md")
}

Check "a missing progress.md is refused by name" {
    $root = New-Fixture
    Remove-Item -LiteralPath (Join-Path $root "docs\superpowers\plans\progress.md") -Force
    $r = Invoke-Driver $root @{}
    ($r.code -eq 2) -and ($r.text -match "progress\.md")
}

Check "a run on main is refused before anything starts" {
    $root = New-Fixture
    Push-Location $root; & cmd /c "git switch -c main -q 2>NUL"; Pop-Location
    $r = Invoke-Driver $root @{}
    ($r.code -eq 2) -and ($r.text -match "main")
}

Check "a missing budget file is refused by name, never defaulted" {
    $r = Invoke-Driver (New-Fixture) @{ BudgetFile = "C:\nope\absent-budget.json" }
    ($r.code -eq 2) -and ($r.text -match "absent-budget\.json")
}

Check "a missing config file is refused by name" {
    $r = Invoke-Driver (New-Fixture) @{ Config = "C:\nope\absent.yml" }
    ($r.code -eq 2) -and ($r.text -match "absent\.yml")
}

Check "a budget key that is absent is NAMED rather than defaulted" {
    $root = New-Fixture
    $bad = Join-Path $root "budget-without-window.json"
    $b = Get-Content -LiteralPath $budget -Raw -Encoding UTF8 | ConvertFrom-Json
    $b.PSObject.Properties.Remove("always_on_files")
    ($b | ConvertTo-Json -Depth 8) | Set-Content -LiteralPath $bad -Encoding UTF8
    $r = Invoke-Driver $root @{ BudgetFile = $bad }
    ($r.code -eq 2) -and ($r.text -match "always_on_files")
}

Check "an always-on file that does not exist is refused by its path" {
    $root = New-Fixture
    $bad = Join-Path $root "budget-ghost-file.json"
    $b = Get-Content -LiteralPath $budget -Raw -Encoding UTF8 | ConvertFrom-Json
    $b.always_on_files = @("C:/nope/ghost-rules.md")
    ($b | ConvertTo-Json -Depth 8) | Set-Content -LiteralPath $bad -Encoding UTF8
    $r = Invoke-Driver $root @{ BudgetFile = $bad }
    ($r.code -eq 2) -and ($r.text -match "ghost-rules\.md")
}

Check "a cloud model is refused unless -AllowCloud is passed" {
    $r = Invoke-Driver (New-Fixture) @{ Model = "gpt-4o" }
    ($r.code -eq 2) -and ($r.text -match "not a local model")
}

Check "NEGATIVE CONTROL: -AllowCloud lifts exactly that refusal" {
    $r = Invoke-Driver (New-Fixture) @{ Model = "gpt-4o"; AllowCloud = $true }
    $r.text -notmatch "not a local model"
}

# --- What the dry run must never do -----------------------------------------
Check "the dry run writes NOTHING into the project" {
    $root = New-Fixture
    Push-Location $root
    $before2 = @(& cmd /c "git status --porcelain 2>NUL") | Sort-Object
    Pop-Location
    $null = Invoke-Driver $root @{}
    Push-Location $root
    $after2 = @(& cmd /c "git status --porcelain 2>NUL") | Sort-Object
    Pop-Location
    $added = Compare-Object -ReferenceObject $before2 -DifferenceObject $after2 |
             Where-Object { $_.SideIndicator -eq "=>" }
    ($null -eq $added) -or ($added.Count -eq 0)
}

Check "the dry run names --message-file and never a bare --message" {
    $r = Invoke-Driver (New-Fixture) @{}
    ($r.text -match "--message-file") -and ($r.text -notmatch '--message\s')
}

# --- A plan header must not change the files a plan names (local coding contract) -------
# Every plan now opens with front matter (executor, tier, bounds, R38). Get-PlanTargets
# splits the WHOLE text on separators, so a path-like value inside the header would be added
# to the chat as an editable file. Fictitious names only (R34).
$headerProj = Join-Path $scratch "headerproj"
New-Item -ItemType Directory -Force -Path $headerProj | Out-Null
$proj = (Resolve-Path -LiteralPath $headerProj).Path
$CodeExtensions = @(".py", ".ps1")
$DataExtensions = @(".json")
$planBody = @'
# Plan 1 - fictitious

### Task 1

**Files:**
- Create: `src/world.py`
- Test: `Test/test_world.py`
'@
$planHeader = @'
---
executor: aider
tier: simple
note: hidden/leak.py
bounds:
  max_rounds: 3
  max_tokens: 1500000
  plateau: 2
---

'@
# Get-PlanTargets returns its array wrapped (a leading comma, so one file survives as an array),
# which `@(Get-PlanTargets ...)` would NOT flatten: Count would read 1. The driver assigns it
# directly, so this helper does the same and hands the checks a flat array.
function Get-Targets([string]$plan) { $t = Get-PlanTargets $plan; return $t }
$plainPlan = Join-Path $headerProj "plain.md"
$headedPlan = Join-Path $headerProj "headed.md"
Set-Content -LiteralPath $plainPlan -Value $planBody -Encoding UTF8
Set-Content -LiteralPath $headedPlan -Value ($planHeader + $planBody) -Encoding UTF8

Check "a plan header does not add a file the body does not name" {
    $withHeader = @(Get-Targets $headedPlan)
    ($withHeader | Where-Object { $_ -like "*leak.py" }).Count -eq 0
}

Check "the count of targets is the same with or without the header" {
    @(Get-Targets $headedPlan).Count -eq @(Get-Targets $plainPlan).Count -and
    @(Get-Targets $plainPlan).Count -eq 2
}

Check "NEGATIVE CONTROL: a path-like value in the BODY is still a target" {
    $bodyHit = Join-Path $headerProj "bodyhit.md"
    Set-Content -LiteralPath $bodyHit -Value ($planHeader + $planBody + "`n- Create: ``extra/found.py```n") -Encoding UTF8
    (@(Get-Targets $bodyHit) | Where-Object { $_ -like "*found.py" }).Count -eq 1
}

Check "a header never closed is not read as swallowing the whole plan" {
    $open = Join-Path $headerProj "open.md"
    Set-Content -LiteralPath $open -Value ("---`nexecutor: aider`n" + $planBody) -Encoding UTF8
    @(Get-Targets $open).Count -eq 2
}

Write-Host ""
# --- Files a plan only reads are read-only, never targets (measured 2026-11-10) ---------
New-Item -ItemType Directory -Force -Path (Join-Path $headerProj "lib") | Out-Null
Set-Content -LiteralPath (Join-Path $headerProj "lib\shared.py") -Value "x = 1" -Encoding UTF8
$readsBody = @'
# Plan 2 - fictitious

**Files:**
- Create: `src/world.py`
- Test: `Test/test_world.py`

**Reads, do not modify:** `lib/shared.py` (its `x`), `lib/missing.py` and `src/world.py`.

Nothing else is read here.
'@
$readsPlan = Join-Path $headerProj "reads.md"
Set-Content -LiteralPath $readsPlan -Value $readsBody -Encoding UTF8

Check "a file the plan only reads is not a target" {
    (@(Get-Targets $readsPlan) | Where-Object { $_ -like "*shared.py" -or $_ -like "*missing.py" }).Count -eq 0
}

Check "the files the plan creates stay targets, even one the reads paragraph names again" {
    $t = @(Get-Targets $readsPlan)
    ($t.Count -eq 2) -and (($t | Where-Object { $_ -like "*world.py" -and $_ -notlike "*test_world.py" }).Count -eq 1)
}

Check "the read-only files are listed: existing ones only, never a target" {
    $r = Get-PlanReads $readsPlan (Get-Targets $readsPlan)
    (@($r).Count -eq 1) -and (@($r)[0] -like "*shared.py")
}

Check "NEGATIVE CONTROL: a plan with no reads paragraph has no read-only files" {
    $r = Get-PlanReads $plainPlan @()
    @($r).Count -eq 0
}

Write-Host ""
# --- The reviewer sees the plan, the writer sees the report (found 2026-11-11) -----------
$auditDir = Join-Path $scratch "auditctx"
New-Item -ItemType Directory -Force -Path $auditDir | Out-Null
Set-Content -LiteralPath (Join-Path $auditDir "plan1.md") -Encoding UTF8 -Value ("---`nexecutor: aider`ntier: simple`n---`n`n# Plan 1`n`nBuild the world function.`n")
Set-Content -LiteralPath (Join-Path $auditDir "audit.md") -Encoding UTF8 -Value ("## plan1.md`n1. The world function never closes the file.`n   - File: src/world.py:12`n`n## plan2.md`n1. Something about plan two.`n")

Check "the audit message carries the plan's text, without its front matter" {
    $b = Get-AuditPlanBlock $auditDir "plan1.md"
    ($b -match 'THE PLAN THIS CODE IMPLEMENTS') -and ($b -match 'Build the world function') -and ($b -notmatch 'executor: aider')
}

Check "NEGATIVE CONTROL: a plan that is not there gives no block, and no error" {
    (Get-AuditPlanBlock $auditDir "plan9.md") -eq ""
}

Check "the reopen message carries the reviewer's report on THIS plan only" {
    $r = Get-ReopenReport (Join-Path $auditDir "audit.md") "plan1.md"
    ($r -match 'never closes the file') -and ($r -match 'src/world.py:12') -and ($r -notmatch 'plan two')
}

Check "NEGATIVE CONTROL: no report on the plan, or no audit.md, adds nothing" {
    ((Get-ReopenReport (Join-Path $auditDir "audit.md") "plan7.md") -eq "") -and
    ((Get-ReopenReport (Join-Path $auditDir "absent.md") "plan1.md") -eq "")
}

Write-Host ""
# --- rules.md is checked before every pass (2026-11-11) ---------------------------------
function New-RulesBudget([string]$root, [string]$rulesText) {
    $rulesFile = Join-Path $root "rules.md"
    [System.IO.File]::WriteAllText($rulesFile, $rulesText, (New-Object System.Text.UTF8Encoding $false))
    $bad = Join-Path $root "budget-rules.json"
    $b = Get-Content -LiteralPath $budget -Raw -Encoding UTF8 | ConvertFrom-Json
    $b.always_on_files = @(($rulesFile -replace '\\', '/'))
    ($b | ConvertTo-Json -Depth 8) | Set-Content -LiteralPath $bad -Encoding UTF8
    return $bad
}

Check "a rule defined twice refuses the run and names it" {
    $root = New-Fixture
    $bad = New-RulesBudget $root "# Coding rules`n`n**R0 - one.** Say it.`n`n**R1 - two.** Say it.`n`n**R1 - again.** Say it.`n"
    $r = Invoke-Driver $root @{ BudgetFile = $bad }
    ($r.code -eq 2) -and ($r.text -match 'R1 is defined twice')
}

Check "a gap in the numbering refuses the run and names it" {
    $root = New-Fixture
    $bad = New-RulesBudget $root "**R0 - one.** Say it.`n`n**R2 - two.** Say it.`n"
    $r = Invoke-Driver $root @{ BudgetFile = $bad }
    ($r.code -eq 2) -and ($r.text -match 'missing: R1')
}

Check "a rule over the per-rule cap refuses the run, naming it and its size, and cuts nothing" {
    $root = New-Fixture
    $long = "**R0 - long.** " + (("word " * 400).Trim()) + "`n"
    $bad = New-RulesBudget $root $long
    $r = Invoke-Driver $root @{ BudgetFile = $bad }
    ($r.code -eq 2) -and ($r.text -match 'R0 is \d+ tokens, over the cap of') -and ((Get-Content -LiteralPath (Join-Path $root "rules.md") -Raw) -eq $long)
}

Check "a valid rules file is reported in one line and the run starts" {
    $root = New-Fixture
    $bad = New-RulesBudget $root "**R0 - one.** Say it.`n`n**R1 - two.** Say it.`n"
    $r = Invoke-Driver $root @{ BudgetFile = $bad }
    ($r.text -match 'rules.md: 2 rules R0-R1') -and ($r.text -notmatch 'breaks its own format')
}

Write-Host ""
# --- Plan quality: the reviewer judges requirements, the driver counts them (2026-11-11) -------------
# Tokens are counted as a quarter of the bytes here, so this check needs no tokenizer.
function Get-TokenCount([string]$file) { return [int]((Get-Item -LiteralPath $file).Length / 4) }
New-Item -ItemType Directory -Force -Path (Join-Path $headerProj "src") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $headerProj "Test") | Out-Null
Set-Content -LiteralPath (Join-Path $headerProj "src\world.py") -Value ("def world():`n    return 1`n" + ("# padding line`n" * 40)) -Encoding UTF8
Set-Content -LiteralPath (Join-Path $headerProj "Test\test_world.py") -Value "import unittest`n" -Encoding UTF8

Check "the score is counted from the reviewer's lines: full 1, partial 0.5, missing 0" {
    $t = "## quality plan1.md`n- [full] the world function - there`n- [full] the test file - there`n- [full] one more - ok`n- [partial] the config key - named differently`n- [partial] the exit code - 0 instead of 2`n- [missing] the logging - absent`n"
    $s = Get-QualityScore $t "plan1.md"
    $s.scored -and ($s.full -eq 3) -and ($s.partial -eq 2) -and ($s.missing -eq 1) -and ($s.percent -eq 67) -and ($s.lines.Count -eq 6)
}

Check "only the lines under THIS plan's quality heading count, whatever the case of the status" {
    $t = "## quality plan2.md`n- [missing] a thing - absent`n`n## quality plan1.md`n- [FULL] a - ok`n* [Partial] b - half`n"
    $s = Get-QualityScore $t "plan1.md"
    ($s.total -eq 2) -and ($s.full -eq 1) -and ($s.partial -eq 1) -and ($s.percent -eq 75)
}

Check "NEGATIVE CONTROL: no usable line is 'not scored' with its reason, never 0 percent" {
    $s = Get-QualityScore "## quality plan1.md`nIt looks fine to me.`n" "plan1.md"
    (-not $s.scored) -and ($s.percent -eq $null) -and ($s.reason -match 'no requirement line')
}

Check "the quality message carries the plan without its header, the code, and the instruction not to count tests" {
    $p = Get-QualityPrompt $headedPlan $proj 5000 "=== HOW TO REVIEW: brief ===`nbe careful`n`n"
    ($null -ne $p) -and ($p.text -match 'Build the world function|world') -and ($p.text -notmatch 'executor: aider') -and
    ($p.text -match 'def world') -and ($p.text -match 'NOT running tests') -and ($p.text -match "## quality headed.md") -and
    ($p.text -match 'be careful') -and ($p.shown.Count -eq 2) -and ($p.omitted.Count -eq 0)
}

Check "a file that does not fit is named as left out, so the reviewer can say it could not judge it" {
    Set-Content -LiteralPath (Join-Path $headerProj "Test\test_world.py") -Value ("import unittest`n" + ("# x`n" * 400)) -Encoding UTF8
    $p = Get-QualityPrompt $plainPlan $proj 200 ""
    ($null -ne $p) -and ($p.omitted.Count -ge 1) -and ($p.text -match 'Not shown, no room')
}

Check "NEGATIVE CONTROL: a plan whose files do not exist gives no message" {
    $none = Join-Path $headerProj "nofiles.md"
    Set-Content -LiteralPath $none -Value "Build `nope/absent.py` and its test `nope/test_absent.py`.`n" -Encoding UTF8
    $null -eq (Get-QualityPrompt $none $proj 5000 "")
}

Check "the report has one table with the percentages and lists what is not fully met" {
    $a = Get-QualityScore "## quality plan1.md`n- [full] a - ok`n- [missing] b - absent`n" "plan1.md"
    $b = Get-QualityScore "no lines" "plan2.md"
    $r = Format-QualityReport @($a, $b)
    ($r -match '\| plan1.md \| 50 % \| 50 % \| not measured \| 1 \| 0 \| 1 \|') -and ($r -match '\| plan2.md \| not scored') -and ($r -match '\*\*missing\*\* b - absent') -and ($r -notmatch '\*\*full\*\*')
}

# --- The tests count for 20 percent of the score (owner, 2026-11-12) ---------------------------------
Check "20 percent of the score is the share of tests that pass: reviewer 100 and 25 of 26 tests gives 99" {
    $t = "## quality plan1.md`n- [full] a - ok`n- [full] b - ok`n"
    $s = Get-QualityScore $t "plan1.md" @{ total = 26; passed = 25 }
    $s.scored -and $s.testsMeasured -and ($s.reviewer -eq 100) -and ($s.percent -eq 99) -and ($s.testsPassed -eq 25) -and ($s.testsTotal -eq 26)
}

Check "the reviewer's share is scaled to 80 and the tests fill the other 20: reviewer 50 with every test green gives 60" {
    $t = "## quality plan1.md`n- [full] a - ok`n- [missing] b - absent`n"
    $s = Get-QualityScore $t "plan1.md" @{ total = 10; passed = 10 }
    ($s.reviewer -eq 50) -and ($s.percent -eq 60)
}

Check "NEGATIVE CONTROL: every test red costs the full 20 points, and no measured tests leaves the reviewer's number alone" {
    $t = "## quality plan1.md`n- [full] a - ok`n"
    $red = Get-QualityScore $t "plan1.md" @{ total = 4; passed = 0 }
    $none = Get-QualityScore $t "plan1.md" $null
    $zero = Get-QualityScore $t "plan1.md" @{ total = 0; passed = 0 }
    ($red.percent -eq 80) -and ($none.percent -eq 100) -and (-not $none.testsMeasured) -and ($zero.percent -eq 100) -and (-not $zero.testsMeasured)
}

Check "the report shows the tests as passed over run, and the sentence on the weights" {
    $a = Get-QualityScore "## quality plan1.md`n- [full] a - ok`n" "plan1.md" @{ total = 26; passed = 25 }
    $r = Format-QualityReport @($a)
    ($r -match '\| plan1.md \| 99 % \| 100 % \| 25/26 \| 1 \| 0 \| 0 \|') -and ($r -match '80 percent the reviewer') -and ($r -match '20 percent the share of the plan')
}

Check "unittest output is read: failures and errors are subtracted, a file that never ran counts as one failure" {
    $ok = Get-TestCounts "...`nRan 10 tests in 0.1s`n`nOK`n"
    $bad = Get-TestCounts "Ran 26 tests in 0.1s`n`nFAILED (errors=1)`n"
    $mixed = Get-TestCounts "Ran 8 tests in 0.1s`n`nFAILED (failures=2, errors=1, skipped=1)`n"
    $crash = Get-TestCounts "Traceback (most recent call last):`nSyntaxError: invalid syntax`n"
    $empty = Get-TestCounts "Ran 0 tests in 0.0s`n`nNO TESTS RAN`n"
    ($ok.total -eq 10 -and $ok.passed -eq 10) -and ($bad.total -eq 26 -and $bad.passed -eq 25) -and ($mixed.total -eq 8 -and $mixed.passed -eq 5) -and
    ($crash.total -eq 1 -and $crash.passed -eq 0) -and ($empty.total -eq 0)
}

Check "the test interpreter is the first word of the test command, quoted or not, only when it is Python" {
    ((Get-TestInterpreter '.\.venv\Scripts\python.exe run_tests.py') -eq '.\.venv\Scripts\python.exe') -and
    ((Get-TestInterpreter '"C:\Program Files\Python312\python.exe" -m unittest') -eq 'C:\Program Files\Python312\python.exe') -and
    ((Get-TestInterpreter 'python3 -m pytest') -eq 'python3') -and
    ($null -eq (Get-TestInterpreter 'cargo test')) -and ($null -eq (Get-TestInterpreter '')) -and ($null -eq (Get-TestInterpreter '"unclosed python.exe'))
}

Write-Host ""
Check "a blocked run is reported plan by plan, with the evidence of its logs" {
    $dir = Join-Path ([System.IO.Path]::GetTempPath()) ("bk-" + [guid]::NewGuid().ToString("N").Substring(0, 8))
    New-Item -ItemType Directory -Force -Path $dir | Out-Null
    try {
        $ledger = "# Progress`n`n## plan1.md`n- [x] a`n`n## plan2.md`n- [ ] b`n- [!] tests - suite still failing (exit 1) after the fix loop`n"
        $run = "Tokens: 16k sent, 5.0k received.`nModel m has hit a token limit!`nToken counts below are approximate.`n`nInput tokens: ~31,333 of 65,536`nOutput tokens: ~13,516 of 14,336 -- possibly exceeded output limit!`nTotal tokens: ~44,849 of 65,536`n`nOnly 3 reflections allowed`n"
        [System.IO.File]::WriteAllText((Join-Path $dir "20260101-000000-plan2.log"), $run, [System.Text.Encoding]::Unicode)
        [System.IO.File]::WriteAllText((Join-Path $dir "20260101-000000-plan2-tests.log"), "FAIL: test_one (m.T)`nRan 3 tests`nFAILED (failures=1)`n", (New-Object System.Text.UTF8Encoding($false)))
        $r = Get-BlockReport $ledger $dir
        ($r -match '## plan2.md') -and ($r -match 'suite still failing') -and ($r -match 'input ~31,333 of 65,536') -and
        ($r -match 'output ~13,516 of 14,336') -and ($r -match 'Failing tests: test_one') -and ($r -match 'FAILED \(failures=1\)') -and
        ($r -match '16k sent / 5.0k received') -and ($r -match 'used all its fix attempts') -and ($r -notmatch 'plan1')
    } finally { Remove-Item -LiteralPath $dir -Recurse -Force }
}

Check "NEGATIVE CONTROL: a ledger with no blocked plan gives no report" {
    $dir = Join-Path ([System.IO.Path]::GetTempPath()) ("bk-" + [guid]::NewGuid().ToString("N").Substring(0, 8))
    New-Item -ItemType Directory -Force -Path $dir | Out-Null
    try { (Get-BlockReport "# Progress`n`n## plan1.md`n- [x] a`n" $dir) -eq "" } finally { Remove-Item -LiteralPath $dir -Recurse -Force }
}

Check "a test log is re-saved as UTF-8 with a mark, content intact, once" {
    $f = Join-Path ([System.IO.Path]::GetTempPath()) ("tl-" + [guid]::NewGuid().ToString("N").Substring(0, 8) + ".log")
    try {
        [System.IO.File]::WriteAllBytes($f, [byte[]](0x72, 0xC3, 0xA9, 0x73))   # "r" "e acute" "s" in UTF-8, no mark
        Convert-TestLogToUtf8Bom $f
        Convert-TestLogToUtf8Bom $f                                              # a second pass must not add a second mark
        $b = [System.IO.File]::ReadAllBytes($f)
        ($b.Length -eq 7) -and ($b[0] -eq 0xEF) -and ($b[1] -eq 0xBB) -and ($b[2] -eq 0xBF) -and ($b[4] -eq 0xC3) -and ($b[5] -eq 0xA9)
    } finally { Remove-Item -LiteralPath $f -Force -ErrorAction SilentlyContinue }
}

Check "a UTF-16 test log is converted, never read as UTF-8, and a missing log is left alone" {
    $f = Join-Path ([System.IO.Path]::GetTempPath()) ("tl-" + [guid]::NewGuid().ToString("N").Substring(0, 8) + ".log")
    try {
        [System.IO.File]::WriteAllText($f, "ok " + [char]0xE9, [System.Text.Encoding]::Unicode)
        Convert-TestLogToUtf8Bom $f
        Convert-TestLogToUtf8Bom (Join-Path ([System.IO.Path]::GetTempPath()) "no-such-test-log.log")
        (Get-LogText $f) -eq ("ok " + [char]0xE9)
    } finally { Remove-Item -LiteralPath $f -Force -ErrorAction SilentlyContinue }
}

Write-Host ""
Check "no record from this test reached the real ~/.aider-plan" {
    $leaked = Leaked-Records
    if ($leaked.Count -gt 0) {
        Write-Host ("        leaked: " + (($leaked | ForEach-Object { $_.Name }) -join ", ")) -ForegroundColor Red
    }
    $leaked.Count -eq 0
}

Check "NEGATIVE CONTROL: the leak check can actually report" {
    # A check that has never been shown to fail proves nothing. Plant a record
    # named for one of this test's own projects, require it to be reported, and
    # remove it again.
    if (-not (Test-Path -LiteralPath $realRuns)) { New-Item -ItemType Directory -Force -Path $realRuns | Out-Null }
    $planted = Join-Path $realRuns (Record-Name $script:TestProjects[0])
    $existed = Test-Path -LiteralPath $planted
    if ($existed) { return $false }   # refuse to overwrite a real record
    Set-Content -LiteralPath $planted -Value '{"schema":"planted-by-the-test"}' -Encoding UTF8
    $seen = (Leaked-Records).Count -gt 0
    Remove-Item -LiteralPath $planted -Force
    $seen -and ((Leaked-Records).Count -eq 0)
}

Write-Host ""
Write-Host ("passed {0}, failed {1}" -f $script:pass, $script:fail) -ForegroundColor $(if ($script:fail) { "Red" } else { "Green" })
exit $(if ($script:fail) { 1 } else { 0 })

