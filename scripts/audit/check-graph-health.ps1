#Requires -Version 5.1
<#
.SYNOPSIS
    Read-only report on the graphify knowledge graph: what is in it, what is
    missing from it, and how old it is.

.DESCRIPTION
    The graph is one of the two memories this workspace runs on, and it is the
    one nothing could interrogate. `local-writer` routes every "what is in this
    code" question to it, the Stop hook fires its GRAPHIFY clause whenever this
    directory exists, and until now the only trace of a failed build was a
    *.log file that .gitignore excludes. A confident reply built on a pack that
    is missing the answer is the worst failure mode of the whole design, so the
    graph's own state has to be askable.

    Measured 2026-08-30 on this repository, which is why the check exists:
    graph.json carried 5311 nodes and 7312 links, every one of them
    `_origin: ast`, with .graphify_semantic.json holding zero nodes and
    graphify_extraction.log reporting `11/11 semantic chunk(s) failed` and
    `189/189 dispatched file(s) produced no nodes`. The build still wrote a
    5.9 MB graph.json and exited 0. Nothing said a word.

    Reported here:
      contents   node and link counts, the _origin mix, the file_type mix, and
                 the histogram of source-file extensions
      coverage   how many files the graph claims to cover contributed no node
                 at all, broken down by extension
      freshness  covered files whose modification time is newer than
                 graph.json's. Deliberately mtime, never git: the professor
                 runs git himself and no check here may invoke it

    WRITES NOTHING. Point it at any repository with -RepoRoot.

.PARAMETER RepoRoot
    Repository to inspect. Defaults to two levels above this script. The tests
    drive fixture trees under $env:TEMP through this parameter.

.PARAMETER RecentCount
    How many of the most recently modified stale files to name. Specified by
    the audit plan (2026-08-30), not measured. Display only; it never changes
    the verdict.

.PARAMETER Json
    Emit the report as a single JSON object on stdout and suppress the human
    text, so a caller reads a field instead of matching prose (R17).

.PARAMETER Quiet
    Suppress the human text without emitting JSON.

.NOTES
    Exit codes (R12):
      0  current, OR no graphify-out/ at all (a skip, not a failure - most
         projects have no graph, and a check that fails on their behalf gets
         turned off, R11)
      1  findings: a covered source file is newer than the graph
      3  graph.json is present but unreadable or malformed

    A graph carrying no semantic node is a NOTE, never a finding. Measured
    2026-08-30 through the sanctioned path: this graph holds the code and the
    structure of every .md file, and no layer that read what those files SAY -
    asked why the Obsidian CLI write path is forbidden, it returned 109 nodes of
    file, command and test-class names and none of the three measured reasons.
    Building that other layer is a deliberate, token-costing run, so a check
    that failed until someone paid for it would simply be switched off.

    Uncovered files are reported but never fail the run: a .png, a .json or a
    .txt producing no AST node is the normal state of an AST pass, and a check
    that is permanently red for a reason nobody intends to fix is noise.

.EXAMPLE
    .\scripts\audit\check-graph-health.ps1
    .\scripts\audit\check-graph-health.ps1 -Json | ConvertFrom-Json
#>

[CmdletBinding()]
param(
    [string]$RepoRoot,
    [int]$RecentCount = 3,
    [switch]$Json,
    [switch]$Quiet
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# graphify's own convention for where it writes a graph; the Stop hook keys on
# the same name.
$GraphDirName = "graphify-out"

if (-not $RepoRoot) { $RepoRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent }

$showText = (-not $Quiet) -and (-not $Json)
function Say([string]$text, [string]$colour = "Gray") { if ($showText) { Write-Host $text -ForegroundColor $colour } }
function SayHeader([string]$text) { if ($showText) { Write-Host ""; Write-Host "=== $text ===" -ForegroundColor Cyan } }
function SayFinding([string]$text) { if ($showText) { Write-Host "  [!!]  $text" -ForegroundColor Yellow } }

# StrictMode makes a missing property an error rather than $null, and graphify
# nodes do not all carry the same keys.
function Get-Prop($obj, [string]$name) {
    if ($null -eq $obj) { return $null }
    $p = $obj.PSObject.Properties[$name]
    if ($p) { return $p.Value }
    return $null
}

function Format-Mix($counter) {
    if ($counter.Count -eq 0) { return "(none)" }
    $parts = $counter.GetEnumerator() | Sort-Object -Property Value -Descending | ForEach-Object { "$($_.Key) $($_.Value)" }
    return ($parts -join ", ")
}

function Norm([string]$p) {
    if (-not $p) { return "" }
    return ($p -replace '\\', '/').TrimStart('./').ToLowerInvariant()
}

function Stamp([datetime]$t) { $t.ToString("yyyy-MM-dd HH:mm") }

$report = [ordered]@{
    repo_root             = $RepoRoot
    graph_path            = $null
    skipped               = $false
    skip_reason           = $null
    nodes                 = 0
    links                 = 0
    origin                = [ordered]@{}
    file_type             = [ordered]@{}
    extensions            = [ordered]@{}
    semantic_nodes        = 0
    covered_from          = $null
    covered_files         = 0
    uncovered_files       = 0
    uncovered_by_extension = [ordered]@{}
    missing_from_disk     = 0
    graph_mtime           = $null
    stale_count           = 0
    stale_recent          = @()
    notes                 = @()
    findings              = @()
    exit_code             = 0
}

function Emit([int]$code) {
    $report.exit_code = $code
    if ($Json) { Write-Output ($report | ConvertTo-Json -Depth 6) }
    exit $code
}

$graphDir  = Join-Path $RepoRoot $GraphDirName
$graphFile = Join-Path $graphDir "graph.json"

SayHeader "graphify graph health"
Say "  repo  : $RepoRoot"

if (-not (Test-Path -LiteralPath $graphDir -PathType Container)) {
    $report.skipped = $true
    $report.skip_reason = "no $GraphDirName directory"
    Say "  [--]  no $GraphDirName\ here - nothing to check (skip, R11)"
    Emit 0
}
if (-not (Test-Path -LiteralPath $graphFile -PathType Leaf)) {
    $report.skipped = $true
    $report.skip_reason = "no graph.json"
    Say "  [--]  $GraphDirName\ exists but holds no graph.json - nothing to check (skip)"
    Emit 0
}

$report.graph_path = $graphFile
$graphItem  = Get-Item -LiteralPath $graphFile
$graphMtime = $graphItem.LastWriteTime
$report.graph_mtime = $graphMtime.ToString("s")
Say ("  graph : {0}  ({1}, {2:N0} bytes)" -f $graphFile, (Stamp $graphMtime), $graphItem.Length)

try {
    $graph = Get-Content -LiteralPath $graphFile -Raw -Encoding UTF8 | ConvertFrom-Json
} catch {
    Say ""
    if ($showText) { Write-Host "  [ERR] graph.json does not parse: $($_.Exception.Message)" -ForegroundColor Red }
    $report.findings = @("unreadable")
    Emit 3
}

$nodes = Get-Prop $graph "nodes"
if ($null -eq $nodes) {
    if ($showText) { Write-Host "  [ERR] graph.json carries no 'nodes' array" -ForegroundColor Red }
    $report.findings = @("unreadable")
    Emit 3
}
$nodes = @($nodes)
$links = Get-Prop $graph "links"
if ($null -eq $links) { $links = Get-Prop $graph "edges" }
$links = @($links)

$report.nodes = $nodes.Count
$report.links = $links.Count

$originMix = @{}
$typeMix   = @{}
$extMix    = @{}
$sourceSet = @{}
foreach ($n in $nodes) {
    $o = Get-Prop $n "_origin";    if (-not $o) { $o = "(none)" }
    $t = Get-Prop $n "file_type";  if (-not $t) { $t = "(none)" }
    $s = Get-Prop $n "source_file"
    $e = if ($s) { [System.IO.Path]::GetExtension($s) } else { "" }
    if (-not $e) { $e = "(none)" }
    $originMix[$o] = 1 + $(if ($originMix.ContainsKey($o)) { $originMix[$o] } else { 0 })
    $typeMix[$t]   = 1 + $(if ($typeMix.ContainsKey($t))   { $typeMix[$t] }   else { 0 })
    $extMix[$e]    = 1 + $(if ($extMix.ContainsKey($e))    { $extMix[$e] }    else { 0 })
    if ($s) { $sourceSet[(Norm $s)] = $true }
}
foreach ($k in ($originMix.Keys | Sort-Object)) { $report.origin[$k]     = $originMix[$k] }
foreach ($k in ($typeMix.Keys   | Sort-Object)) { $report.file_type[$k]  = $typeMix[$k] }
foreach ($k in ($extMix.Keys    | Sort-Object)) { $report.extensions[$k] = $extMix[$k] }

# A semantic node is any node the AST pass did not produce. Zero of them means
# the model half of the extraction never landed, whatever the build's exit code
# said.
$report.semantic_nodes = @($nodes | Where-Object { (Get-Prop $_ "_origin") -ne "ast" }).Count

Say ""
Say "  -- contents --"
Say ("  nodes {0}   links {1}" -f $report.nodes, $report.links)
Say ("  origin     : {0}" -f (Format-Mix $originMix))
Say ("  file_type  : {0}" -f (Format-Mix $typeMix))
Say ("  source ext : {0}" -f (Format-Mix $extMix))

# What the graph CLAIMS to cover. manifest.json is graphify's own record of the
# files it dispatched; without it the only honest answer is the set of files
# that did produce a node, and the report says which of the two it used rather
# than letting a caller assume (R8: an unannounced fallback is the defect).
$manifestFile = Join-Path $graphDir "manifest.json"
$covered = @()
if (Test-Path -LiteralPath $manifestFile -PathType Leaf) {
    try {
        $manifest = Get-Content -LiteralPath $manifestFile -Raw -Encoding UTF8 | ConvertFrom-Json
        $covered = @($manifest.PSObject.Properties.Name)
        $report.covered_from = "manifest.json"
    } catch {
        $covered = @($sourceSet.Keys)
        $report.covered_from = "graph node source_file values (manifest.json does not parse)"
    }
} else {
    $covered = @($sourceSet.Keys)
    $report.covered_from = "graph node source_file values (no manifest.json)"
}
$report.covered_files = $covered.Count

$uncoveredExt = @{}
$uncovered = @()
foreach ($c in $covered) {
    if (-not $sourceSet.ContainsKey((Norm $c))) {
        $uncovered += $c
        $e = [System.IO.Path]::GetExtension($c); if (-not $e) { $e = "(none)" }
        $uncoveredExt[$e] = 1 + $(if ($uncoveredExt.ContainsKey($e)) { $uncoveredExt[$e] } else { 0 })
    }
}
$report.uncovered_files = $uncovered.Count
foreach ($k in ($uncoveredExt.Keys | Sort-Object)) { $report.uncovered_by_extension[$k] = $uncoveredExt[$k] }

Say ""
Say ("  -- coverage (from {0}, {1} file(s)) --" -f $report.covered_from, $report.covered_files)
Say ("  contributed no node : {0}  ({1})" -f $report.uncovered_files, (Format-Mix $uncoveredExt))

# Freshness by modification time, never by git: this check must work in a
# session that is forbidden to invoke git at all.
$stale = @()
$absent = 0
foreach ($c in $covered) {
    $p = Join-Path $RepoRoot ($c -replace '/', '\')
    if (-not (Test-Path -LiteralPath $p -PathType Leaf)) { $absent++; continue }
    $t = (Get-Item -LiteralPath $p).LastWriteTime
    if ($t -gt $graphMtime) { $stale += [pscustomobject]@{ path = $c; mtime = $t } }
}
$report.missing_from_disk = $absent
$stale = @($stale | Sort-Object -Property mtime -Descending)
$report.stale_count = $stale.Count
$report.stale_recent = @($stale | Select-Object -First $RecentCount | ForEach-Object {
    [ordered]@{ path = $_.path; mtime = $_.mtime.ToString("s") }
})

Say ""
Say "  -- freshness --"
if ($absent -gt 0) { Say ("  [--]  {0} covered file(s) no longer on disk" -f $absent) }
if ($stale.Count -eq 0) {
    Say "  [OK]  no covered file is newer than the graph"
} else {
    SayFinding ("{0} covered file(s) modified after the graph was built" -f $stale.Count)
    foreach ($s in ($stale | Select-Object -First $RecentCount)) {
        Say ("        {0}  {1}" -f (Stamp $s.mtime), $s.path)
    }
}

# A graph with no semantic node is REPORTED and does not fail the run. Decided
# 2026-08-30, after the state was measured through the sanctioned path: the
# graph holds the code and the structure of every .md file, and no layer that
# read what those files SAY. Asked "why is the Obsidian CLI write path
# forbidden", it returned 109 nodes of file, command and test-class names and
# none of the three measured reasons. That is the intended shape here, since
# building the other layer is a deliberate, token-costing run and not something
# a health check should nag about on every invocation. It stays visible as a
# note so nobody mistakes the graph for a memory of intent.
$notes = @()
if ($report.semantic_nodes -eq 0) { $notes += "ast-only" }
$report.notes = $notes

$findings = @()
if ($stale.Count -gt 0) { $findings += "stale" }
$report.findings = $findings

Say ""
Say "  -- verdict --"
if ($notes -contains "ast-only") {
    Say "  [--]  AST-ONLY (expected here, not a failure): 0 node carries a non-ast origin," "DarkGray"
    Say "        so this graph answers STRUCTURE - what calls what, which file holds which" "DarkGray"
    Say "        symbol - and never MEANING. Ask it why a decision was taken and it returns" "DarkGray"
    Say "        names, not reasons. Why-questions go to the vault, through local-writer." "DarkGray"
}
if ($findings -contains "stale") {
    SayFinding ("STALE: {0} source file(s) are newer than graph.json." -f $stale.Count)
    Say        "        Point 'graphify update <path>' at them; never edit graph.json."
}
if ($findings.Count -eq 0) {
    Say "  [OK]  graph is complete and current." "Green"
    Emit 0
}
Say ("  {0} finding(s): {1}" -f $findings.Count, ($findings -join ", "))
Emit 1
