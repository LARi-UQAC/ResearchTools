#Requires -Version 5.1
<#
.SYNOPSIS
    Offline check of the two irreversible writes performed by install-junctions.ps1 -Sync.

.DESCRIPTION
    -Sync writes two files the professor owns and that nothing else in this repository
    touches: ~/.claude/CLAUDE.md (the RT-CONTRACT block, between markers) and
    ~/.claude/settings.json (one SessionStart entry). Everything else -Sync does is
    idempotent link maintenance that can be re-run harmlessly. These two are the ones
    that could corrupt a global configuration, so they get a check of their own.

    It loads scripts\lib\rt-sync.ps1 directly rather than install-junctions.ps1. That
    separation is the whole reason the engine lives in its own file: dot-sourcing the
    installer would execute its legacy junction-creation flow as a side effect, writing
    to the REAL ~/.claude just by running the test.

.SAFETY
    Builds a throwaway directory under $env:TEMP, copies the real settings.json and
    CLAUDE.md into it, and points the writers at the copies. The live files are never
    opened for writing. The first assertion below PROVES the redirection took effect
    before a byte is written, following the precedent set by the obsidian outbox suite -
    a test that silently writes to the thing it is meant to protect is worse than no test.

.NOTES
    Not part of the green-stamp gate, which covers Python suites under .claude\ only.
    This is a safety check in the same family as scripts\audit\check-claude-template.ps1.

.EXAMPLE
    .\scripts\test\verify-sync-writes.ps1
#>

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$Fake     = Join-Path $env:TEMP "rt-sync-verify-$PID"
$failures = 0

function Check([string]$name, [bool]$ok) {
    if ($ok) { Write-Host "  PASS  $name" -ForegroundColor DarkGray }
    else     { Write-Host "  FAIL  $name" -ForegroundColor Red; $script:failures++ }
}

function Get-HookCount([string]$path) {
    $cfg = Get-Content $path -Raw -Encoding UTF8 | ConvertFrom-Json
    $n = 0
    foreach ($evt in $cfg.hooks.PSObject.Properties) {
        foreach ($e in @($evt.Value)) { $n += @($e.hooks).Count }
    }
    return $n
}

Write-Host ""
Write-Host "=== -Sync write safety ===" -ForegroundColor Cyan

$liveSettings = Join-Path $env:USERPROFILE ".claude\settings.json"
$liveClaude   = Join-Path $env:USERPROFILE ".claude\CLAUDE.md"
if (-not (Test-Path $liveSettings) -or -not (Test-Path $liveClaude)) {
    Write-Host "  No live ~/.claude to copy from; nothing to check." -ForegroundColor Yellow
    exit 0
}

if (Test-Path $Fake) { Remove-Item $Fake -Recurse -Force }
New-Item -ItemType Directory -Path $Fake | Out-Null
Copy-Item $liveSettings (Join-Path $Fake "settings.json")
Copy-Item $liveClaude   (Join-Path $Fake "CLAUDE.md")

# The precondition, asserted before anything is written: the live files must be
# untouched by everything that follows, so record their hashes now and re-check at
# the end. Two incidents in this repository's history came from a test that reached
# the real target it was meant to be protecting.
$liveSettingsHash = (Get-FileHash $liveSettings -Algorithm SHA256).Hash
$liveClaudeHash   = (Get-FileHash $liveClaude   -Algorithm SHA256).Hash
Check "redirection target is the temp copy, not ~/.claude" ($Fake -ne (Split-Path $liveSettings -Parent))

# The fixture must start NOT YET INSTALLED, or both functions correctly do
# nothing and the "adds one entry" and "backs up" checks can only pass on a
# machine that has never run -Sync. Measured 2026-08-28 on this machine: they
# failed for exactly that reason, 14 hooks in and 14 out with no .bak, while
# -Sync itself was working perfectly. A check whose verdict depends on the
# host's install state is not a check.
#
# Both edits are surgical, so the copies keep the real files' shape and
# formatting, which is the whole point of driving the functions against them
# rather than against a synthetic sample. No-BOM writes throughout: Windows
# PowerShell's Set-Content -Encoding utf8 prepends a BOM, and ConvertFrom-Json
# throws on a leading U+FEFF.
$utf8NoBom    = New-Object System.Text.UTF8Encoding $false
$fakeSettings = Join-Path $Fake "settings.json"
$fakeClaude   = Join-Path $Fake "CLAUDE.md"

# Update-RtSettings returns early on the literal "install-junctions.ps1".
# Renaming the token leaves the JSON valid and every other byte in place.
$settingsRaw = [System.IO.File]::ReadAllText($fakeSettings)
[System.IO.File]::WriteAllText($fakeSettings, $settingsRaw.Replace(
    "install-junctions.ps1", "install-junctions-NOT-INSTALLED.ps1"), $utf8NoBom)

# Update-RtClaudeMd returns early when the contract block is already identical.
$claudeRaw = [System.IO.File]::ReadAllText($fakeClaude)
$cBegin = "<!-- RT-CONTRACT:BEGIN -->"
$cEnd   = "<!-- RT-CONTRACT:END -->"
$cbi = $claudeRaw.IndexOf($cBegin)
$cei = $claudeRaw.IndexOf($cEnd)
if ($cbi -ge 0 -and $cei -gt $cbi) {
    $claudeRaw = $claudeRaw.Remove($cbi, $cei - $cbi + $cEnd.Length)
    [System.IO.File]::WriteAllText($fakeClaude, $claudeRaw, $utf8NoBom)
}

. (Join-Path $RepoRoot "scripts\lib\rt-sync.ps1")
$script:RtQuiet = $true

$hooksBefore = Get-HookCount (Join-Path $Fake "settings.json")
$envBefore   = (Get-Content (Join-Path $Fake "settings.json") -Raw -Encoding UTF8 | ConvertFrom-Json).env | ConvertTo-Json -Compress

Update-RtSettings $RepoRoot $Fake
Update-RtClaudeMd $RepoRoot $Fake

$hooksAfter = Get-HookCount (Join-Path $Fake "settings.json")
$envAfter   = (Get-Content (Join-Path $Fake "settings.json") -Raw -Encoding UTF8 | ConvertFrom-Json).env | ConvertTo-Json -Compress

Check "settings.json still parses as JSON"          ($hooksAfter -gt 0)
Check "exactly one hook entry added ($hooksBefore -> $hooksAfter)" ($hooksAfter -eq $hooksBefore + 1)
Check "env block byte-identical"                    ($envAfter -eq $envBefore)
Check "settings.json backed up"                     (Test-Path (Join-Path $Fake "settings.json.bak"))
Check "CLAUDE.md backed up"                         (Test-Path (Join-Path $Fake "CLAUDE.md.bak"))

$claudeText = Get-Content (Join-Path $Fake "CLAUDE.md") -Raw -Encoding UTF8
$beginCount = ([regex]::Matches($claudeText, [regex]::Escape("<!-- RT-CONTRACT:BEGIN -->"))).Count
Check "contract block present exactly once"         ($beginCount -eq 1)

# Idempotence. The SessionStart entry means -Sync runs on every session in every
# project, so a second pass that appended again would grow both files without bound.
$sHash = (Get-FileHash (Join-Path $Fake "settings.json") -Algorithm SHA256).Hash
$cHash = (Get-FileHash (Join-Path $Fake "CLAUDE.md")     -Algorithm SHA256).Hash
Update-RtSettings $RepoRoot $Fake
Update-RtClaudeMd $RepoRoot $Fake
Check "settings.json unchanged on a second pass"    ((Get-FileHash (Join-Path $Fake "settings.json") -Algorithm SHA256).Hash -eq $sHash)
Check "CLAUDE.md unchanged on a second pass"        ((Get-FileHash (Join-Path $Fake "CLAUDE.md")     -Algorithm SHA256).Hash -eq $cHash)

# A hand-edit that leaves one marker without its partner must be refused rather than
# guessed at: guessing where the block ends risks eating the professor's own content.
$mangled = $claudeText -replace [regex]::Escape("<!-- RT-CONTRACT:END -->"), "oops"
Set-Content (Join-Path $Fake "CLAUDE.md") -Value $mangled -Encoding utf8 -NoNewline
$mHash = (Get-FileHash (Join-Path $Fake "CLAUDE.md") -Algorithm SHA256).Hash
Update-RtClaudeMd $RepoRoot $Fake
Check "unmatched marker refused, file untouched"    ((Get-FileHash (Join-Path $Fake "CLAUDE.md") -Algorithm SHA256).Hash -eq $mHash)

# Malformed JSON must stop the writer, not be repaired or overwritten.
Set-Content (Join-Path $Fake "settings.json") -Value "{ this is not json" -Encoding utf8 -NoNewline
$jHash = (Get-FileHash (Join-Path $Fake "settings.json") -Algorithm SHA256).Hash
Update-RtSettings $RepoRoot $Fake
Check "unparseable settings.json refused, untouched" ((Get-FileHash (Join-Path $Fake "settings.json") -Algorithm SHA256).Hash -eq $jHash)

# --- what -Sync SELECTS out of .claude\hooks ---------------------------------
# Read off rt-sync.ps1 itself rather than driven, because the copy loop walks the real
# repository and writes into ~/.claude\hooks; the two writes this script drives are the
# only ones it can safely execute. Behavioural proof of the same rule lives in
# verify-setup-writes.ps1, where Install-RtGlobalHooks IS driven against temp copies.
#
# Widened 2026-08-30 from "-Filter *.py" to .py plus .json. A hook may now ship a
# configuration file beside itself (R0 keeps thresholds out of code), and a .py that
# arrived without its .json finds no config and, per R11, disables itself IN SILENCE -
# a gate that looks installed and never fires, which is worse than one that is absent.
$syncText = [System.IO.File]::ReadAllText((Join-Path $RepoRoot "scripts\lib\rt-sync.ps1"))
Check "rt-sync.ps1 selects hook files through Get-RtHookFiles" ($syncText -match 'Get-RtHookFiles\s+-HooksDir\s+\$hooksSrc')
Check "rt-sync.ps1 keeps no inline .py/.json filter of its own"  (-not ($syncText -match "Get-ChildItem \`$hooksSrc"))

# --- the selection itself, DRIVEN (2026-10-16) ----------------------------------------
# Measured: -Sync copied a hook's .json but the stamp hashed only *.py, so every hook
# config read "changed since the last green run" and was HELD forever, whatever the suite
# said. The two selections now share rt-stamp.ps1. Driven against a fictitious tree.
. (Join-Path $RepoRoot "scripts\lib\rt-stamp.ps1")
$Tree = Join-Path $Fake "stamp-tree"
foreach ($d in @(".claude\hooks", ".claude\hooks\Test", ".claude\hooks\git", ".claude\skills\alpha\scripts", ".claude\skills\alpha\scripts\__pycache__")) {
    New-Item -ItemType Directory -Path (Join-Path $Tree $d) -Force | Out-Null
}
foreach ($f in @(".claude\hooks\guard.py", ".claude\hooks\guard.json", ".claude\hooks\notes.txt",
                 ".claude\hooks\Test\fixture.json", ".claude\hooks\git\rules.json",
                 ".claude\skills\alpha\scripts\tool.py", ".claude\skills\alpha\scripts\settings.json",
                 ".claude\skills\alpha\scripts\__pycache__\tool.cpython-311.py")) {
    Set-Content -Path (Join-Path $Tree $f) -Value "x" -Encoding ASCII
}
$names = { param($files) @($files | ForEach-Object { $_.FullName.Substring($Tree.Length + 1) } | Sort-Object) }
$hooks = & $names (Get-RtHookFiles -HooksDir (Join-Path $Tree ".claude\hooks"))
Check "Get-RtHookFiles returns the hook .py and .json, nothing else" (($hooks -join "|") -eq ".claude\hooks\guard.json|.claude\hooks\guard.py")
$code = & $names (Get-RtCodeFiles -RepoRoot $Tree)
Check "the stamp selection includes the hook .json"             ($code -contains ".claude\hooks\guard.json")
Check "the stamp selection includes the hook .py"               ($code -contains ".claude\hooks\guard.py")
Check "the stamp selection includes a skill .py"                ($code -contains ".claude\skills\alpha\scripts\tool.py")
Check "a skill .json is not hashed (nothing copies it)"          (-not ($code -contains ".claude\skills\alpha\scripts\settings.json"))
Check "a .json under hooks\Test or hooks\git is not hashed"       (-not ($code -match "Test\\fixture|git\\rules"))
Check "__pycache__ is excluded"                                  (-not ($code -match "__pycache__"))

# The whole point, end to end: a stamp built from the selection PROVES the .json, and the
# proof dies with the first edit. The old selection (py only) is the negative control.
$entries = [ordered]@{}
foreach ($f in (Get-RtCodeFiles -RepoRoot $Tree)) { $entries[$f.FullName.Substring($Tree.Length + 1)] = (Get-FileHash $f.FullName -Algorithm SHA256).Hash }
$stampNew = [pscustomobject]@{ code_hashes = [pscustomobject]$entries }
$jsonPath = Join-Path $Tree ".claude\hooks\guard.json"
Check "Test-RtProven: an unchanged hook .json is proven"          (Test-RtProven $stampNew $Tree $jsonPath)
Set-Content -Path $jsonPath -Value "changed" -Encoding ASCII
Check "Test-RtProven: an edited hook .json is no longer proven"   (-not (Test-RtProven $stampNew $Tree $jsonPath))
$oldEntries = [ordered]@{}
foreach ($f in (Get-ChildItem (Join-Path $Tree ".claude") -Recurse -File -Include *.py | Where-Object { $_.FullName -notmatch '\\__pycache__\\' })) {
    $oldEntries[$f.FullName.Substring($Tree.Length + 1)] = (Get-FileHash $f.FullName -Algorithm SHA256).Hash
}
$stampOld = [pscustomobject]@{ code_hashes = [pscustomobject]$oldEntries }
Set-Content -Path $jsonPath -Value "x" -Encoding ASCII
Check "(control) the old .py-only stamp could never prove a .json" (-not (Test-RtProven $stampOld $Tree $jsonPath))

# Cannot-disagree check on the REAL repository: everything -Sync would copy from the real
# hooks folder is something the stamp hashes.
# The reference list is enumerated HERE, independently of the shared helper (a direct listing
# of the top-level hook files), so the check cannot pass by construction when the helper's
# filter and the stamp's merge move together (code-review finding).
$independent = @(Get-ChildItem -LiteralPath (Join-Path $RepoRoot ".claude\hooks") -File |
                 Where-Object { $_.Name -like "*.py" -or $_.Name -like "*.json" } | ForEach-Object { $_.FullName })
$realCode    = @(Get-RtCodeFiles -RepoRoot $RepoRoot | ForEach-Object { $_.FullName })
$missing     = @($independent | Where-Object { $realCode -notcontains $_ })
Check "every real hook .py and .json is hashed by the stamp"       ($independent.Count -gt 0 -and $missing.Count -eq 0)
$copied = @(Get-RtHookFiles -HooksDir (Join-Path $RepoRoot ".claude\hooks") | ForEach-Object { $_.FullName })
Check "-Sync's selection equals the independent listing"          (($copied | Sort-Object) -join "|" -eq (($independent | Sort-Object) -join "|"))

# The three places that decide which hook files travel: update path, first-install path and
# the deployment audit. None may keep a filter of its own (the audit's was *.py, which is why
# three held configs read "all in step").
foreach ($site in @(@("scripts\lib\rt-sync.ps1", "the -Sync engine"),
                    @("scripts\lib\rt-global-config.ps1", "the first-install path"),
                    @("scripts\audit\check-deployment.ps1", "the deployment audit"))) {
    $text = [System.IO.File]::ReadAllText((Join-Path $RepoRoot $site[0]))
    Check ("{0} selects hook files through Get-RtHookFiles" -f $site[1]) ($text -match 'Get-RtHookFiles')
}
$auditText = [System.IO.File]::ReadAllText((Join-Path $RepoRoot "scripts\audit\check-deployment.ps1"))
Check "the deployment audit no longer lists hooks with -Filter *.py" (-not ($auditText -match 'hooksRepo\s+-File\s+-Filter\s+\*\.py'))
Check "the runner takes its file list from Get-RtCodeFiles"       ([System.IO.File]::ReadAllText((Join-Path $RepoRoot "scripts\test\run-offline-tests.ps1")) -match 'Get-RtCodeFiles\s+-RepoRoot')

Check "live ~/.claude/settings.json never written"  ((Get-FileHash $liveSettings -Algorithm SHA256).Hash -eq $liveSettingsHash)
Check "live ~/.claude/CLAUDE.md never written"      ((Get-FileHash $liveClaude   -Algorithm SHA256).Hash -eq $liveClaudeHash)

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
