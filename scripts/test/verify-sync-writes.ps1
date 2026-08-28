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
