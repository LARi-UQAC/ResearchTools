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

foreach ($required in @("Get-RunRecordDir", "Initialize-RunRecord", "Update-RunRecord")) {
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
$testCmd = 'python -m unittest discover -s tests -p "test_*.py"'

function New-Fixture {
    $root = Join-Path $env:TEMP ("refusal-" + [guid]::NewGuid().ToString("N").Substring(0,8))
    $p = Join-Path $root "docs\superpowers\plans"
    New-Item -ItemType Directory -Force -Path $p, (Join-Path $root "tests") | Out-Null
    Push-Location $root
    & cmd /c "git init -q -b work . 2>NUL"
    "def add(a, b):`n    return a + b" | Set-Content -LiteralPath (Join-Path $root "calc.py") -Encoding UTF8
    "import unittest" | Set-Content -LiteralPath (Join-Path $root "tests\test_calc.py") -Encoding UTF8
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

