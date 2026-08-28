#Requires -Version 5.1
<#
.SYNOPSIS
    Read-only drift check: does the live ~/.claude actually match this repository?

.DESCRIPTION
    install-junctions.ps1 -Sync PUSHES the repository into ~/.claude. This answers the
    separate question of whether the push actually took, and it is the check that would
    have caught the defect this whole self-improvement loop was built around: sixteen of
    seventeen agents in ~/.claude/agents/ had silently become detached real-file copies,
    frozen weeks behind the repository, while the installer reported EXISTS and moved on.
    Nothing looked wrong until the content was compared.

    Verified here:
      agents    every .claude/agents/*.md has a live counterpart with an identical hash
      skills    every .claude/skills/<dir> has a live junction (a missing one is why
                /texcheck worked in the repo and did not exist in a manuscript folder)
      hooks     every .claude/hooks/*.py matches its deployed copy
      CLAUDE.md the RT-CONTRACT block is present exactly once and well-formed
      settings  the SessionStart sync entry is present, and the file still parses
      stamp     .rt-green.json exists and its per-file hashes still describe the code

    WRITES NOTHING. Run it after a -Sync, after a git pull, or whenever an agent behaves
    like an older version of itself.

.NOTES
    A PowerShell gotcha worth remembering, because it produced a silently wrong result
    the first time this check was written ad hoc: PowerShell variables are CASE
    INSENSITIVE, so a loop variable $h overwrites an outer $h ome path variable named $H.
    Every path built from it afterwards became garbage, Join-Path failed on each
    iteration, the mismatch counter stayed at zero, and the check cheerfully reported
    "0 mismatched" while having compared nothing at all. Distinct names, not distinct
    casing. This is exactly the class of green-looking failure the check exists to stop.

.EXAMPLE
    .\scripts\audit\check-deployment.ps1
    .\scripts\audit\check-deployment.ps1 -Quiet
#>
param(
    [switch]$Quiet
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepoRoot   = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$HomeClaude = Join-Path $env:USERPROFILE ".claude"
$problems   = 0
$checked    = 0

function Say([string]$text, [string]$colour = "Gray") {
    if (-not $Quiet) { Write-Host $text -ForegroundColor $colour }
}
function Problem([string]$text) {
    Write-Host "  $text" -ForegroundColor Red
    $script:problems++
}

Say ""
Say "=== ResearchTools deployment check ===" "Cyan"
Say "  repo : $RepoRoot"
Say "  live : $HomeClaude"

if (-not (Test-Path $HomeClaude)) {
    Say "  No ~/.claude on this machine; nothing deployed, nothing to check." "Yellow"
    exit 0
}

# --- Agents: content, not existence ------------------------------------------
# Existence was never the problem. A detached hardlink and a fresh copy are
# indistinguishable on inspection, which is why the drift went unnoticed for weeks.
Say ""
Say "  agents"
$agentsRepo = Join-Path $RepoRoot ".claude\agents"
if (Test-Path $agentsRepo) {
    foreach ($agent in (Get-ChildItem $agentsRepo -File -Filter *.md)) {
        $checked++
        $live = Join-Path (Join-Path $HomeClaude "agents") $agent.Name
        if (-not (Test-Path $live)) {
            Problem "MISSING  agents\$($agent.Name)"
            continue
        }
        $a = (Get-FileHash $live         -Algorithm SHA256).Hash
        $b = (Get-FileHash $agent.FullName -Algorithm SHA256).Hash
        if ($a -ne $b) {
            $liveAge = (Get-Item $live).LastWriteTime.ToString("yyyy-MM-dd")
            Problem "STALE    agents\$($agent.Name)  (live $liveAge, differs from repo)"
        }
    }
}

# --- Skills: a junction must exist, or the skill does not exist elsewhere -----
Say "  skills"
$skillsRepo = Join-Path $RepoRoot ".claude\skills"
if (Test-Path $skillsRepo) {
    foreach ($skill in (Get-ChildItem $skillsRepo -Directory)) {
        $checked++
        $live = Join-Path (Join-Path $HomeClaude "skills") $skill.Name
        if (-not (Test-Path $live)) {
            Problem "MISSING  skills\$($skill.Name)  (works in the repo, absent everywhere else)"
        }
        elseif ((Get-Item $live -Force).LinkType -ne "Junction") {
            Problem "NOTLINK  skills\$($skill.Name)  (real directory shadowing the repo)"
        }
    }
}

# --- Hooks -------------------------------------------------------------------
Say "  hooks"
$hooksRepo = Join-Path $RepoRoot ".claude\hooks"
if (Test-Path $hooksRepo) {
    foreach ($hook in (Get-ChildItem $hooksRepo -File -Filter *.py)) {
        $checked++
        $live = Join-Path (Join-Path $HomeClaude "hooks") $hook.Name
        if (-not (Test-Path $live)) {
            Problem "MISSING  hooks\$($hook.Name)  (declared in settings but not deployed)"
        }
        elseif ((Get-FileHash $live -Algorithm SHA256).Hash -ne (Get-FileHash $hook.FullName -Algorithm SHA256).Hash) {
            Problem "STALE    hooks\$($hook.Name)"
        }
    }
}

# --- The contract block ------------------------------------------------------
Say "  contract block"
$liveClaudeMd = Join-Path $HomeClaude "CLAUDE.md"
if (Test-Path $liveClaudeMd) {
    $checked++
    $text  = [System.IO.File]::ReadAllText($liveClaudeMd)
    $nOpen  = ([regex]::Matches($text, "RT-CONTRACT:BEGIN")).Count
    $nClose = ([regex]::Matches($text, "RT-CONTRACT:END")).Count
    if ($nOpen -eq 0) {
        Problem "ABSENT   RT-CONTRACT block  (the loop's instruction never reaches a foreign session)"
    } elseif ($nOpen -ne 1 -or $nClose -ne 1) {
        Problem "MALFORM  RT-CONTRACT markers  (open=$nOpen close=$nClose, expected 1 and 1)"
    }
} else {
    Problem "ABSENT   ~/.claude/CLAUDE.md"
}

# --- The SessionStart sync entry ---------------------------------------------
Say "  settings entry"
$liveSettings = Join-Path $HomeClaude "settings.json"
if (Test-Path $liveSettings) {
    $checked++
    $raw = [System.IO.File]::ReadAllText($liveSettings)
    try { $null = $raw | ConvertFrom-Json } catch { Problem "INVALID  settings.json does not parse" }
    if (-not $raw.Contains("install-junctions.ps1")) {
        Problem "ABSENT   SessionStart sync entry  (drift will not self-repair)"
    }
} else {
    Problem "ABSENT   ~/.claude/settings.json"
}

# --- The green stamp ---------------------------------------------------------
# Not a deployment fact, but the gate that decides whether code may deploy at all,
# so a stale stamp explains a held sync and belongs in the same report.
Say "  green stamp"
$stampPath = Join-Path $RepoRoot ".rt-green.json"
if (-not (Test-Path $stampPath)) {
    Problem "ABSENT   .rt-green.json  (run scripts\test\run-offline-tests.ps1; code will be held)"
} else {
    $checked++
    $stamp = Get-Content $stampPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $drift = 0
    foreach ($item in $stamp.code_hashes.PSObject.Properties) {
        $f = Join-Path $RepoRoot $item.Name
        if (Test-Path $f) {
            if ((Get-FileHash $f -Algorithm SHA256).Hash -ne $item.Value) { $drift++ }
        }
    }
    if ($drift -gt 0) {
        Problem "STALE    .rt-green.json  ($drift code file(s) changed since the last green run)"
    }
}

# --- Verdict -----------------------------------------------------------------
Write-Host ""
if ($problems -eq 0) {
    Write-Host "  $checked item(s) checked, all in step." -ForegroundColor Green
    Write-Host ""
    exit 0
}
Write-Host "  $checked item(s) checked, $problems problem(s)." -ForegroundColor Red
Write-Host "  Run .\install-junctions.ps1 -Sync to push the repository into ~/.claude." -ForegroundColor Yellow
Write-Host ""
exit 1
