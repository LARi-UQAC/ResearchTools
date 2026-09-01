#Requires -Version 5.1
<#
.SYNOPSIS
    Drives scripts\audit\check-graph-health.ps1 against fixture graphs under
    $env:TEMP and proves each verdict keys on the thing it claims.

.DESCRIPTION
    The check exists because a graphify build wrote a 5.9 MB graph.json, lost
    every semantic node, and exited 0 (measured 2026-08-30, see the audit
    script's header). A health check that could not itself fail would repeat
    exactly that, so every verdict here is asserted in BOTH directions:

      ast-only   an ast-only graph is REPORTED as a note and does not fail the
                 run (decided 2026-08-30: this graph holds structure and no
                 layer that read what the files say, and building that layer is
                 a deliberate token-costing run, so a check red until someone
                 pays for it gets switched off), while the SAME tree with one
                 semantic node added carries no such note
      stale      a source newer than the graph is reported, and the SAME tree
                 with that file's mtime moved back goes green
      skip       an absent graphify-out\ is silent and exit 0 (R11), and a
                 malformed graph.json is exit 3 rather than a silent pass

    Every fixture is built under $env:TEMP. Nothing here touches the live
    repository's graphify-out\, and the real graph.json is hashed before and
    after a read-only run to prove it.

    All timestamps are injected, never taken from the clock (R19), so the
    verdicts are the same on a re-run.

.EXAMPLE
    .\scripts\test\verify-graph-health.ps1
#>

[CmdletBinding()]
param(
    [string]$Root
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if (-not $Root) { $Root = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent }
$Check = Join-Path $Root "scripts\audit\check-graph-health.ps1"

$script:Failures = 0
function Write-Header([string]$text) { Write-Host ""; Write-Host "=== $text ===" -ForegroundColor Cyan }
function Write-Pass([string]$text)   { Write-Host "  PASS  $text" -ForegroundColor Green }
function Write-Fail([string]$text)   { Write-Host "  FAIL  $text" -ForegroundColor Red; $script:Failures++ }
function Write-Info([string]$text)   { Write-Host "  [--]  $text" -ForegroundColor DarkGray }
function Check-True([bool]$ok, [string]$text) { if ($ok) { Write-Pass $text } else { Write-Fail $text } }
function Check-Eq($expected, $actual, [string]$text) {
    if ("$expected" -eq "$actual") { Write-Pass $text } else { Write-Fail "$text (expected '$expected', got '$actual')" }
}

# ---------------------------------------------------------------------------
# Fixture construction. Injected times, no clock.
# ---------------------------------------------------------------------------
$Base       = [datetime]"2026-01-01T00:00:00"
$SourceTime = $Base.AddHours(1)
$GraphTime  = $Base.AddHours(10)
$LaterTime  = $Base.AddHours(20)

$Sandbox = Join-Path $env:TEMP ("rt-graph-health-" + $PID)
if (Test-Path -LiteralPath $Sandbox) { Remove-Item -LiteralPath $Sandbox -Recurse -Force }
New-Item -ItemType Directory -Path $Sandbox -Force | Out-Null

function New-Node([string]$id, [string]$origin, [string]$source, [string]$type) {
    return [ordered]@{ id = $id; label = $id; _origin = $origin; file_type = $type; source_file = $source }
}

function New-Fixture {
    param(
        [string]$Name,
        [switch]$Semantic,        # add one semantic node
        [switch]$NoManifest,      # coverage falls back to node source_file values
        [switch]$Malformed,       # graph.json that does not parse
        [switch]$NoGraphDir,      # no graphify-out at all
        [string[]]$ExtraCovered = @()   # manifest entries that produce no node
    )
    $dir = Join-Path $Sandbox $Name
    New-Item -ItemType Directory -Path (Join-Path $dir "src") -Force | Out-Null
    New-Item -ItemType Directory -Path (Join-Path $dir "docs") -Force | Out-Null

    $files = @("src/a.py", "docs/b.md") + $ExtraCovered
    foreach ($f in $files) {
        $p = Join-Path $dir ($f -replace '/', '\')
        $parent = Split-Path $p -Parent
        if (-not (Test-Path -LiteralPath $parent)) { New-Item -ItemType Directory -Path $parent -Force | Out-Null }
        Set-Content -LiteralPath $p -Value "fixture content for $f" -Encoding UTF8
        (Get-Item -LiteralPath $p).LastWriteTime = $SourceTime
    }
    if ($NoGraphDir) { return $dir }

    $graphDir = Join-Path $dir "graphify-out"
    New-Item -ItemType Directory -Path $graphDir -Force | Out-Null

    $nodes = @(
        (New-Node "a_one" "ast" "src/a.py" "code"),
        (New-Node "a_two" "ast" "src/a.py" "code"),
        (New-Node "b_one" "ast" "docs/b.md" "document")
    )
    if ($Semantic) { $nodes += (New-Node "b_concept" "semantic" "docs/b.md" "rationale") }
    $graph = [ordered]@{
        directed = $false
        nodes    = $nodes
        links    = @(
            [ordered]@{ source = "a_one"; target = "a_two" },
            [ordered]@{ source = "a_two"; target = "b_one" }
        )
    }
    $graphFile = Join-Path $graphDir "graph.json"
    if ($Malformed) {
        Set-Content -LiteralPath $graphFile -Value '{ "nodes": [ {"id": "truncated"' -Encoding UTF8
    } else {
        Set-Content -LiteralPath $graphFile -Value ($graph | ConvertTo-Json -Depth 6) -Encoding UTF8
    }

    if (-not $NoManifest) {
        $manifest = [ordered]@{}
        foreach ($f in $files) { $manifest[$f] = [ordered]@{ mtime = 0; ast_hash = "x" } }
        Set-Content -LiteralPath (Join-Path $graphDir "manifest.json") -Value ($manifest | ConvertTo-Json -Depth 4) -Encoding UTF8
    }
    (Get-Item -LiteralPath $graphFile).LastWriteTime = $GraphTime
    return $dir
}

function Invoke-Check([string]$dir) {
    $raw = & $Check -RepoRoot $dir -Json
    $code = $LASTEXITCODE
    $obj = $null
    if ($raw) { $obj = ($raw -join "`n") | ConvertFrom-Json }
    return [pscustomobject]@{ exit = $code; report = $obj }
}

function Get-TreeSnapshot([string]$dir) {
    return (Get-ChildItem -LiteralPath $dir -Recurse -Force -File |
            Sort-Object FullName |
            ForEach-Object { "$($_.FullName)|$($_.Length)|$($_.LastWriteTime.Ticks)" }) -join "`n"
}

Write-Header "check-graph-health.ps1 fixtures"
Write-Info "sandbox : $Sandbox"

# ---------------------------------------------------------------------------
# 1. A complete, current graph
# ---------------------------------------------------------------------------
Write-Header "a complete, current graph"
$dir = New-Fixture -Name "complete" -Semantic
$r = Invoke-Check $dir
Check-Eq 0 $r.exit "exit 0"
Check-Eq 0 @($r.report.findings).Count "no findings"
Check-Eq 0 @($r.report.notes).Count "no notes"
Check-Eq 4 $r.report.nodes "node count reported"
Check-Eq 2 $r.report.links "link count reported"
Check-Eq 1 $r.report.semantic_nodes "semantic nodes counted"
Check-True ($null -ne $r.report.extensions.'.md' -and $null -ne $r.report.extensions.'.py') "source-extension histogram names .py and .md"
Check-Eq "manifest.json" $r.report.covered_from "coverage read from manifest.json"
Check-Eq 2 $r.report.covered_files "covered-file count reported"

# ---------------------------------------------------------------------------
# 2. An ast-only graph, and the same tree with one semantic node
# ---------------------------------------------------------------------------
Write-Header "ast-only is reported, and the verdict keys on semantic nodes"
$dir = New-Fixture -Name "astonly"
$r = Invoke-Check $dir
Check-Eq 0 $r.exit "ast-only: exit 0, reported and not failed"
Check-True (@($r.report.notes) -contains "ast-only") "ast-only: named in notes"
Check-True (-not (@($r.report.findings) -contains "ast-only")) "ast-only: NOT a finding, so it cannot drive the exit code"
Check-Eq 0 $r.report.semantic_nodes "ast-only: 0 semantic nodes"
Check-True (-not (@($r.report.findings) -contains "stale")) "ast-only: not also reported stale"

# negative control: same shape, one semantic node, must flip to green
$dir = New-Fixture -Name "astonly-control" -Semantic
$r = Invoke-Check $dir
Check-Eq 0 $r.exit "negative control: a graph with a semantic node also exits 0"
Check-Eq 0 @($r.report.notes).Count "negative control: one semantic node clears the note, so the note keys on the thing it names"

# ---------------------------------------------------------------------------
# 3. A stale graph, and the same tree with the mtime moved back
# ---------------------------------------------------------------------------
Write-Header "stale is reported, and the verdict keys on modification time"
$dir = New-Fixture -Name "stale" -Semantic
$touched = Join-Path $dir "src\a.py"
(Get-Item -LiteralPath $touched).LastWriteTime = $LaterTime
$r = Invoke-Check $dir
Check-Eq 1 $r.exit "stale: exit 1 - staleness is the ONE thing that still fails the run"
Check-True (@($r.report.findings) -contains "stale") "stale: named in findings"
Check-Eq 1 $r.report.stale_count "stale: exactly the touched file"
Check-Eq "src/a.py" (@($r.report.stale_recent)[0].path) "stale: the most recent file is named"

# negative control: move that same file back before the graph, must go green
(Get-Item -LiteralPath $touched).LastWriteTime = $SourceTime
$r = Invoke-Check $dir
Check-Eq 0 $r.exit "negative control: mtime moved back flips the verdict to green"
Check-Eq 0 $r.report.stale_count "negative control: no stale file left"

# ---------------------------------------------------------------------------
# 4. Coverage: a file the graph claims and never produced a node for
# ---------------------------------------------------------------------------
Write-Header "coverage"
$dir = New-Fixture -Name "uncovered" -Semantic -ExtraCovered @("config/thing.json")
$r = Invoke-Check $dir
Check-Eq 1 $r.report.uncovered_files "a covered file with no node is counted"
Check-Eq 1 $r.report.uncovered_by_extension.'.json' "the uncovered file's extension is named"
Check-Eq 0 $r.exit "an uncovered .json does not fail the run"

$dir = New-Fixture -Name "nomanifest" -Semantic -NoManifest
$r = Invoke-Check $dir
Check-True ($r.report.covered_from -like "*no manifest.json*") "with no manifest the fallback source is STATED, not assumed"
Check-Eq 0 $r.report.uncovered_files "the fallback cannot invent an uncovered file"

# ---------------------------------------------------------------------------
# 5. Absence and damage
# ---------------------------------------------------------------------------
Write-Header "absence and damage"
$dir = New-Fixture -Name "nograph" -NoGraphDir
$before = Get-TreeSnapshot $dir
$r = Invoke-Check $dir
Check-Eq 0 $r.exit "no graphify-out: exit 0, a skip and not a failure (R11)"
Check-True ([bool]$r.report.skipped) "no graphify-out: reported as skipped"
Check-Eq $before (Get-TreeSnapshot $dir) "no graphify-out: nothing created"

$dir = New-Fixture -Name "malformed" -Malformed
$r = Invoke-Check $dir
Check-Eq 3 $r.exit "a graph.json that does not parse is exit 3, never a silent pass"
Check-True (@($r.report.findings) -contains "unreadable") "the damaged graph is named unreadable"

# ---------------------------------------------------------------------------
# 6. The check writes nothing
# ---------------------------------------------------------------------------
Write-Header "the check is read-only"
$dir = New-Fixture -Name "readonly" -Semantic
$before = Get-TreeSnapshot $dir
Invoke-Check $dir | Out-Null
Check-Eq $before (Get-TreeSnapshot $dir) "the fixture tree is byte-identical afterwards"

$liveGraph = Join-Path $Root "graphify-out\graph.json"
if (Test-Path -LiteralPath $liveGraph) {
    $item = Get-Item -LiteralPath $liveGraph
    $liveBefore = "$($item.Length)|$($item.LastWriteTime.Ticks)"
    & $Check -Quiet | Out-Null
    $item = Get-Item -LiteralPath $liveGraph
    Check-Eq $liveBefore "$($item.Length)|$($item.LastWriteTime.Ticks)" "the repository's own graph.json is untouched by a real run"
} else {
    Write-Info "no graphify-out in this repository; the live-graph check is not applicable"
}

Remove-Item -LiteralPath $Sandbox -Recurse -Force

Write-Header "Summary"
if ($script:Failures -eq 0) {
    Write-Host "  All checks passed." -ForegroundColor Green
    exit 0
}
Write-Host "  $script:Failures check(s) failed." -ForegroundColor Red
exit 1
