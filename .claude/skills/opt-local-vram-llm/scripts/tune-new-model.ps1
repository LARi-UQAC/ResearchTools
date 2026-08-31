<#
.SYNOPSIS
    Take a model you just downloaded from "it is on disk" to the adoption gate,
    and stop there.

.DESCRIPTION
    Five steps separate a pulled model from one the resolver serves. Four of them
    are mechanical and get skipped or reordered when done by hand; the fifth is a
    decision. This harness runs the first three, prints the comparison, and stops.

      1. Tune it for this card      vram_optimizer.py <tag> --role <role>
      2. Score it, writing nothing  model_resolver.py --score <tuned> --role <role>
      3. Compare the whole field    model_resolver.py --matrix
      4. Adopt it, or do not        model_resolver.py --qualify <tuned> --role <role>
      5. Confirm what is served     model_resolver.py --resolve --role <role>

    Step 4 changes which model every local agent executes, so it stays a command a
    person types. This script prints it and refuses to run it: a harness that
    adopted on its own would make "the tag we measured" and "the tag we run" the
    same event, and nobody would ever see the numbers before they took effect.

    The refusals and the comparison are NOT implemented here. They live in
    tune_preflight.py beside this file, where the offline suite reaches them,
    because PowerShell that spawns processes cannot be tested offline. What stays
    here is sequencing. Same division as run-drill.ps1 and vault_journal.py.

.PARAMETER BaseTag
    The tag as installed, exactly as `ollama list` spells it. There is no default
    and no fallback: this script names no model (R2), and a resolver that names no
    qualified model is an explicit stop, never a substitution.

.PARAMETER Role
    Which role the candidate is being measured for.

.PARAMETER DryRun
    Run every refusal and the sweep's own dry run, then stop before anything is
    built. Touches neither Ollama nor the daemon (R16).

.PARAMETER Yes
    Do not prompt before the sweep. Without it the sweep is previewed and
    confirmed, because it restarts the Ollama daemon between KV cache values.

.PARAMETER OutDir
    Where the JSON reports are written (R17). Defaults under TEMP, never the
    current directory, which may be a manuscript folder.

.EXAMPLE
    .\tune-new-model.ps1 <tag> -Role writer -DryRun
    .\tune-new-model.ps1 <tag> -Role coder -Yes

.NOTES
    The sweep restarts the Ollama daemon once per KV cache value and leaves it on
    the value it chose. Do not run a local agent against the card while it works.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, Position = 0)][string]$BaseTag,
    [Parameter(Mandatory = $true)][ValidateSet("writer", "coder")][string]$Role,
    [switch]$DryRun,
    [switch]$Yes,
    [string]$OutDir
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$Scripts   = $PSScriptRoot
$RepoRoot  = Split-Path (Split-Path (Split-Path (Split-Path $Scripts -Parent) -Parent) -Parent) -Parent
$Optimizer = Join-Path $Scripts "vram_optimizer.py"
$Preflight = Join-Path $Scripts "tune_preflight.py"
$Resolver  = Join-Path $RepoRoot ".claude\skills\loop-engineer\scripts\model_resolver.py"

function Say([string]$text, [string]$colour = "Gray") { Write-Host $text -ForegroundColor $colour }
function Phase([string]$text) { Write-Host ""; Write-Host "=== $text ===" -ForegroundColor Cyan }
function Die([string]$text) { Write-Host "  STOP  $text" -ForegroundColor Red; exit 1 }

# The suite's interpreter when it exists, so this runs under the same Python the
# tests passed on rather than whatever `python` means in this shell today.
$Python = Join-Path $RepoRoot ".venv-skills\Scripts\python.exe"
if (-not (Test-Path $Python)) { $Python = "python" }

foreach ($required in @($Optimizer, $Preflight, $Resolver)) {
    if (-not (Test-Path $required)) { Die "missing script: $required" }
}

if (-not $OutDir) {
    $safe = ($BaseTag -replace '[^A-Za-z0-9\.\-]', '-')
    $OutDir = Join-Path $env:TEMP "rt-tune-$safe"
}

# ---------------------------------------------------------------- phase 0 ---
Phase "Phase 0 - preconditions"
Say "  base tag   : $BaseTag"
Say "  role       : $Role"
Say "  interpreter: $Python"
Say "  reports    : $OutDir"

$global:LASTEXITCODE = 0
& $Python $Preflight --phase tune --tag $BaseTag | Out-Host
if ($LASTEXITCODE -ne 0) {
    Die "preflight refused; nothing was built. The reason is printed above."
}
Say "  installed, and it is a base tag" "DarkGreen"

$TunedTag = (& $Python $Preflight --tuned-tag --tag $BaseTag).Trim()
if ([string]::IsNullOrWhiteSpace($TunedTag)) { Die "could not derive the tuned tag name" }
Say "  the sweep will build: $TunedTag"

# Created only now: a refusal above must leave no empty report directory behind.
if (-not (Test-Path $OutDir)) { New-Item -ItemType Directory -Path $OutDir -Force | Out-Null }

# ---------------------------------------------------------------- phase 1 ---
Phase "Phase 1 - tune it for this card"

Say "  dry run first: probes and prints the Modelfile, touches nothing"
& $Python $Optimizer $BaseTag --role $Role --dry-run | Out-Host
if ($LASTEXITCODE -ne 0) { Die "the sweep refused during its dry run; read its message above" }

if ($DryRun) {
    Phase "Stopped by -DryRun"
    Say "  Nothing was built, measured or adopted. Re-run without -DryRun to sweep."
    exit 0
}

$go = $Yes
if (-not $go) {
    Say "  The sweep restarts the Ollama daemon once per KV cache value and leaves" "Yellow"
    Say "  it on the value it chose. It takes minutes, not seconds." "Yellow"
    $answer = Read-Host "  Sweep $BaseTag for the $Role role now? [y/N]"
    $go = ($answer -eq "y" -or $answer -eq "Y")
}
if (-not $go) { Say "  Left alone at your request." "Yellow"; exit 0 }

& $Python $Optimizer $BaseTag --role $Role | Out-Host
if ($LASTEXITCODE -ne 0) {
    Die "the sweep failed or found nothing admissible. It restores the daemon axis on its own; read its message above."
}
Say "  swept, measured, and declared as a candidate" "DarkGreen"

# ---------------------------------------------------------------- phase 2 ---
Phase "Phase 2 - score it against the frozen task set, writing nothing"

& $Python $Preflight --phase score --tag $TunedTag | Out-Host
if ($LASTEXITCODE -ne 0) { Die "the sweep left no scorable tag; the reason is printed above" }

$scoreJson = Join-Path $OutDir "score.json"
& $Python $Resolver --score $TunedTag --role $Role --json | Tee-Object -FilePath $scoreJson | Out-Host
if ($LASTEXITCODE -ne 0) { Say "  scoring reported a non-zero exit; the JSON above says why" "Yellow" }
Say "  written: $scoreJson"

# ---------------------------------------------------------------- phase 3 ---
Phase "Phase 3 - compare it with every other candidate"
Say "  --matrix scores EVERY declared and installed tag on EVERY task, including"
Say "  roles a tag is not declared for. A candidate scored only on its own role is"
Say "  not comparable."

$matrixJson = Join-Path $OutDir "matrix.json"
& $Python $Resolver --matrix --json | Set-Content -Path $matrixJson -Encoding utf8
if ($LASTEXITCODE -ne 0 -or -not (Test-Path $matrixJson)) {
    Die "--matrix produced nothing; without it there is no comparison to show"
}
Say "  written: $matrixJson"

# An unadopted role is not an error here: it is the ordinary state of a machine
# that has never qualified a tag, and the summary says so rather than inventing
# an incumbent to compare against.
$global:LASTEXITCODE = 0
$incumbent = ""
try { $incumbent = (& $Python $Resolver --resolve --role $Role 2>$null | Select-Object -Last 1) } catch { $incumbent = "" }
if ($LASTEXITCODE -ne 0) { $incumbent = "" }
if ($null -eq $incumbent) { $incumbent = "" }
$incumbent = $incumbent.Trim()

# ---------------------------------------------------------------- phase 4 ---
Phase "Phase 4 - the decision, which is yours"

$summaryArgs = @($Preflight, "--summarize", $matrixJson, "--tag", $TunedTag, "--role", $Role)
if ($incumbent) { $summaryArgs += @("--incumbent", $incumbent) }
& $Python @summaryArgs | Out-Host

Say ""
Say "  Nothing above changed which tag is served. Steps 4 and 5 are yours to run." "Yellow"
exit 0
