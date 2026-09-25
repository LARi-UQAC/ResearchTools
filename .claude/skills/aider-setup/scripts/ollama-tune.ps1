<#
.SYNOPSIS
  Measure this machine, then say how to configure Ollama for it.

.DESCRIPTION
  Two halves.

  The ARITHMETIC half reads context-budget.json and computes the smallest
  context window that can hold the prompt this harness actually assembles. That
  number is not a preference: below it a plan does not run at all, and above it
  every extra token is paid for in model weights pushed off the GPU.

  The MEASUREMENT half drives aider-thread-probe.py over four axes - memory
  bandwidth, CPU threads, forced GPU offload, and the context window - and reads
  back what the daemon actually did rather than what it was asked for.

  It then writes the recommendation into the RESULTS block of CONFIG_OLLAMA.md
  and prints the same thing to the shell.

  Nothing here changes an Ollama setting. It measures and recommends; applying
  the result is a deliberate edit the operator makes.

.PARAMETER Phase
  floor      the arithmetic only. No daemon, no model, seconds.
  bandwidth  DRAM read bandwidth against reader count. No daemon, ~2 min.
  threads    decode against num_thread. Reloads the model per rung.
  layers     decode against forced num_gpu, once per rung.
  repeat     the same, but every rung several times, interleaved. Use this
             before believing a small difference: one run cannot separate
             two settings that sit inside the machine's own noise.
  context    decode, KV size and layer placement against num_ctx.
  quick      floor + bandwidth + a three-point threads and two-point layers run.
  full       every axis at every configured rung. Budget an hour.

.PARAMETER Apply
  Write the RESULTS block into CONFIG_OLLAMA.md. Without it the file is left
  alone and the recommendation is printed only.

.NOTES
  Read CONFIG_OLLAMA.md for what the numbers mean and how to act on them.
#>
[CmdletBinding()]
param(
    [ValidateSet("floor", "promptfloor", "bandwidth", "threads", "layers",
                 "repeat", "context", "quick", "full")]
    [string]$Phase = "quick",
    [string]$ProjectPath = "",
    [int]$Repeats = 1,
    [string]$BudgetFile = "",
    [string]$Probe = "",
    [string]$ConfigOllamaMd = "",
    [switch]$Apply,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

# Every number this script prints or writes is formatted with the invariant
# culture. Measured 2026-09-05: on a French-locale machine the -f operator and
# .ToString() both use the CURRENT culture, so the report written to
# CONFIG_OLLAMA.md carried "66,3 GB/s" and "3,51 tok/s" beside "98.99 percent",
# two decimal separators in one document. Setting it on the thread fixes every
# format string at once rather than per call site, which is what a per-call fix
# would have missed on the next line someone adds.
[System.Threading.Thread]::CurrentThread.CurrentCulture =
    [System.Globalization.CultureInfo]::InvariantCulture

# --- locating the pieces ----------------------------------------------------
# Each is resolved, then checked, then named in the refusal if absent. A default
# that silently points at a file this machine happens to have is how a student's
# run fails on their machine instead of here.

# Two layouts have to work: this file beside the probe in ~/.local/bin during
# development, and this file at the root of an installed kit with the probe in
# bin/. Each list is tried in order and the first hit wins; nothing is assumed.
function Resolve-First([string[]]$candidates, [string]$fallback) {
    foreach ($c in $candidates) {
        if ($c -and (Test-Path -LiteralPath $c)) { return (Resolve-Path -LiteralPath $c).Path }
    }
    return $fallback
}

if ($Probe -eq "") {
    $Probe = Resolve-First @(
        (Join-Path $PSScriptRoot "aider-thread-probe.py"),
        (Join-Path $PSScriptRoot "bin\aider-thread-probe.py"),
        (Join-Path $HOME ".local\bin\aider-thread-probe.py")
    ) (Join-Path $PSScriptRoot "aider-thread-probe.py")
}
if ($BudgetFile -eq "") {
    $BudgetFile = Resolve-First @(
        (Join-Path $PSScriptRoot "config\context-budget.json"),
        (Join-Path $PSScriptRoot "..\config\context-budget.json"),
        (Join-Path $HOME ".config\aider\context-budget.json")
    ) (Join-Path $HOME ".config\aider\context-budget.json")
}
if ($ConfigOllamaMd -eq "") {
    $ConfigOllamaMd = Resolve-First @(
        (Join-Path $PSScriptRoot "CONFIG_OLLAMA.md"),
        (Join-Path $PSScriptRoot "..\CONFIG_OLLAMA.md"),
        (Join-Path $HOME ".config\aider\CONFIG_OLLAMA.md")
    ) (Join-Path $HOME ".config\aider\CONFIG_OLLAMA.md")
}

function Stop-WithReason([string[]]$lines) {
    foreach ($l in $lines) { Write-Host $l -ForegroundColor Red }
    exit 2
}

if (-not (Test-Path -LiteralPath $Probe)) {
    Stop-WithReason @("REFUSED: the probe was not found at $Probe",
                      "  Pass -Probe <path to aider-thread-probe.py>.")
}
if (-not (Test-Path -LiteralPath $BudgetFile)) {
    Stop-WithReason @("REFUSED: context budget not found at $BudgetFile",
                      "  Pass -BudgetFile <path to context-budget.json>.",
                      "  Without it the minimum window cannot be computed, and a",
                      "  guessed minimum is the one number that must not be guessed.")
}

# Python: the probe is Python and aider ships one. Resolved rather than assumed.
$python = $null
foreach ($candidate in @("python", "python3", "py")) {
    $found = Get-Command $candidate -ErrorAction SilentlyContinue
    if ($found) { $python = $found.Source; break }
}
if (-not $python) {
    Stop-WithReason @("REFUSED: no Python interpreter found on PATH.",
                      "  Tried: python, python3, py.",
                      "  aider itself is Python, so if aider runs, one of these exists.")
}

# --- the arithmetic ---------------------------------------------------------

try { $budget = Get-Content -LiteralPath $BudgetFile -Raw -Encoding UTF8 | ConvertFrom-Json }
catch { Stop-WithReason @("REFUSED: $BudgetFile does not parse as JSON.", "  $($_.Exception.Message)") }

function Get-Ceiling($ceilings, [string]$name) {
    $value = $ceilings.$name
    if ($null -eq $value) {
        Stop-WithReason @("REFUSED: ceilings.$name is absent from $BudgetFile.",
                          "  The floor cannot be computed without it (R3).")
    }
    return [int]$value
}

$replyTokens   = [int]$budget.reserve.reply_tokens
$harnessTokens = [int]$budget.reserve.harness_overhead_tokens
$mapTokens     = [int]$budget.repo_map_tokens
$ceilings      = $budget.ceilings

$cConventions = Get-Ceiling $ceilings "conventions.md"
$cRules       = Get-Ceiling $ceilings "rules.md"
$cSpec        = Get-Ceiling $ceilings "spec.md"
$cProgress    = Get-Ceiling $ceilings "progress.md"
$cPlan        = Get-Ceiling $ceilings "plan.md"
$cCode        = Get-Ceiling $ceilings "code_file"

# The three reserves are present on every call and hold no file at all.
$reserves = $replyTokens + $harnessTokens + $mapTokens
# Always-on: the driver passes both as --read on every invocation.
$alwaysOn = $cConventions + $cRules
# Protocol: spec and the ledger are re-read every call, and exactly ONE plan is
# loaded at a time because the context is dropped between plans.
$protocol = $cSpec + $cProgress + $cPlan

# The skill cost, which the first version of this script omitted entirely and so
# under-reported the floor by up to 5000 tokens. The ceilings live in
# skills.json rather than context-budget.json, and only ONE stage is active per
# call, so the floor takes the largest stage rather than their sum.
$skillCeiling = 0
$skillNote = "no skills.json found, so no skill cost is counted"
$skillsJson = Join-Path (Split-Path -Parent $BudgetFile) "skills.json"
if (Test-Path -LiteralPath $skillsJson) {
    try {
        $skills = Get-Content -LiteralPath $skillsJson -Raw -Encoding UTF8 | ConvertFrom-Json
        $stageCeilings = @()
        foreach ($stage in $skills.stages.PSObject.Properties) {
            if ($stage.Name.StartsWith("_")) { continue }
            $ceiling = $stage.Value.ceiling
            if ($null -ne $ceiling) { $stageCeilings += [int]$ceiling }
        }
        if ($stageCeilings.Count -gt 0) {
            $skillCeiling = ($stageCeilings | Measure-Object -Maximum).Maximum
            $skillNote = "largest of $($stageCeilings.Count) stage ceiling(s): " +
                         (($stageCeilings | Sort-Object -Descending) -join ", ")
        } else {
            $skillNote = "skills.json declares no stage ceiling"
        }
    } catch {
        $skillNote = "skills.json did not parse: $($_.Exception.Message)"
    }
}

$floorCeiling = $reserves + $alwaysOn + $protocol + $skillCeiling

# A working window is the floor plus what a plan step actually puts in front of
# the model: one new source file and its test, at the OUTPUT ceiling.
#
# This used to use ceilings.code_file, the 16000-token READ ceiling, which made
# the working minimum 107768 and forced a 131072-token window. That was wrong in
# the expensive direction: an edit sends a SEARCH/REPLACE diff rather than the
# file, and measured 2026-09-05 across six real run logs the largest plan
# message was 119 tokens. Sizing the window for two maximal files being read in
# spent about 2.2 GB of VRAM on KV cache for a case the harness does not
# generate.
$cCodeOut = $cCode
if ($null -ne $ceilings.code_file_output) { $cCodeOut = [int]$ceilings.code_file_output }
$cTestOut = $cCodeOut
if ($null -ne $ceilings.test_file_output) { $cTestOut = [int]$ceilings.test_file_output }

$workingMinimum = $floorCeiling + $cCodeOut + $cTestOut
# Kept and reported separately rather than dropped: a plan that opens two large
# EXISTING files really does need this, and a reader choosing a window should
# see both numbers instead of being handed one and told to trust it.
$readWorstCase = $floorCeiling + (2 * $cCode)

# The same floor with the files as they are RIGHT NOW, which is much smaller and
# is what a small project actually pays. Measured with the same tokenizer aider
# uses for its own estimates; unavailable is stated rather than guessed (R11).
$measuredFloor = $null
$measuredNote = ""
$tokenScript = @'
import sys
try:
    import tiktoken
except Exception as exc:
    print("UNAVAILABLE tiktoken: %s" % exc)
    raise SystemExit(0)
enc = tiktoken.get_encoding("cl100k_base")
total = 0
for path in sys.argv[1:]:
    try:
        total += len(enc.encode(open(path, encoding="utf-8", errors="replace").read()))
    except OSError:
        pass
print("TOKENS %d" % total)
'@
$tokenScriptPath = Join-Path $env:TEMP ("ollama-tune-tokens-" + [guid]::NewGuid().ToString("N") + ".py")
[System.IO.File]::WriteAllText($tokenScriptPath, $tokenScript, (New-Object System.Text.UTF8Encoding $false))
$alwaysOnPaths = @()
foreach ($p in @($budget.always_on_files)) { if ($p) { $alwaysOnPaths += [string]$p } }
try {
    $measured = & $python $tokenScriptPath @alwaysOnPaths 2>&1 | Out-String
    if ($measured -match "TOKENS\s+(\d+)") {
        $measuredFloor = $reserves + [int]$Matches[1]
        $measuredNote = "always-on files measured at $([int]$Matches[1]) tokens"
    } else {
        $measuredNote = "not measured: " + ($measured.Trim() -split "`n")[0]
    }
} catch {
    $measuredNote = "not measured: $($_.Exception.Message)"
} finally {
    Remove-Item -LiteralPath $tokenScriptPath -Force -ErrorAction SilentlyContinue
}

function Format-Int([int]$n) { return $n.ToString("N0", [Globalization.CultureInfo]::InvariantCulture) }

$floorLines = @()
$floorLines += "Minimum input tokens, computed from $([IO.Path]::GetFileName($BudgetFile))"
$floorLines += ""
$floorLines += "  reply reserve                    {0,9}" -f (Format-Int $replyTokens)
$floorLines += "  harness overhead                 {0,9}" -f (Format-Int $harnessTokens)
$floorLines += "  repo map (--map-tokens)          {0,9}" -f (Format-Int $mapTokens)
$floorLines += "  ------------------------------------------"
$floorLines += "  reserves, holding no file        {0,9}" -f (Format-Int $reserves)
$floorLines += ""
$floorLines += "  conventions.md   (every call)    {0,9}" -f (Format-Int $cConventions)
$floorLines += "  rules.md         (every call)    {0,9}" -f (Format-Int $cRules)
$floorLines += "  spec.md          (every call)    {0,9}" -f (Format-Int $cSpec)
$floorLines += "  progress.md      (every call)    {0,9}" -f (Format-Int $cProgress)
$floorLines += "  plan<N>.md       (one at a time)  {0,9}" -f (Format-Int $cPlan)
$floorLines += "  skills, largest stage            {0,9}   ($skillNote)" -f (Format-Int $skillCeiling)
$floorLines += "  ------------------------------------------"
$floorLines += "  MINIMUM WINDOW, zero source code {0,9}" -f (Format-Int $floorCeiling)
$floorLines += "  + one new file and its test      {0,9}   <- size the window for this" -f (Format-Int $workingMinimum)
$floorLines += "  + two EXISTING files at 16000    {0,9}   (only if a plan opens two large ones)" -f (Format-Int $readWorstCase)
if ($null -ne $measuredFloor) {
    $floorLines += ""
    $floorLines += "  reserves + always-on as they ARE {0,9}   ($measuredNote)" -f (Format-Int $measuredFloor)
    $floorLines += "  ... plus this project's spec.md, progress.md and current plan,"
    $floorLines += "      which are project-specific and so not measured from here."
} else {
    $floorLines += ""
    $floorLines += "  today's measured floor: $measuredNote"
}

Write-Host ""
Write-Host "=============================================================" -ForegroundColor Cyan
foreach ($l in $floorLines) { Write-Host $l }
Write-Host "=============================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Only ONE plan is loaded at a time: the harness drops the context"
Write-Host "between plans, so plan<N>.md is counted once and not summed."
Write-Host ""

# --- the empirical floor ----------------------------------------------------
# The floor above is what the ceilings PERMIT. This is what the harness actually
# sent, which is a different and usually much smaller number. The driver writes
# every message it hands the model to docs/superpowers/plans/.logs, so the
# evidence already exists on any machine that has run a night; nothing here needs
# the daemon, the GPU or a model.
#
# The distinction that matters: a message file holds the instruction and, for an
# audit, the embedded source. It does NOT hold conventions.md, rules.md, the repo
# map or aider's own scaffolding, because those are added on top as --read files
# and harness overhead. So the window a message implies is the message plus those.

if ($Phase -eq "promptfloor") {
    $searchRoots = @()
    if ($ProjectPath -ne "") { $searchRoots += $ProjectPath }
    else { $searchRoots += (Get-Location).Path }

    $logFiles = @()
    foreach ($root in $searchRoots) {
        if (-not (Test-Path -LiteralPath $root)) { continue }
        $logDir = Join-Path $root "docs\superpowers\plans\.logs"
        if (Test-Path -LiteralPath $logDir) {
            $logFiles += Get-ChildItem -LiteralPath $logDir -Filter "*prompt*.txt" -File -ErrorAction SilentlyContinue
        }
    }

    if ($logFiles.Count -eq 0) {
        Write-Host "No prompt logs found." -ForegroundColor Yellow
        Write-Host "  Looked in: $((($searchRoots | ForEach-Object { Join-Path $_ 'docs\superpowers\plans\.logs' }) -join '; '))"
        Write-Host ""
        Write-Host "  This phase measures what the harness ACTUALLY sent, so it needs"
        Write-Host "  at least one run's logs. Run a night, or a single plan, then come"
        Write-Host "  back. Until then the floor above - computed from the ceilings in"
        Write-Host "  context-budget.json - is the only figure available, and it is an"
        Write-Host "  upper bound rather than a measurement."
        Write-Host ""
        Write-Host "  Point it at a project with -ProjectPath <path>."
        exit 0
    }

    $countScript = @'
import sys, json, os
try:
    import tiktoken
except Exception as exc:
    print(json.dumps({"error": "tiktoken unavailable: %s" % exc}))
    raise SystemExit(0)
enc = tiktoken.get_encoding("cl100k_base")
out = []
for path in sys.argv[1:]:
    try:
        text = open(path, encoding="utf-8", errors="replace").read()
    except OSError as exc:
        continue
    out.append({"name": os.path.basename(path), "tokens": len(enc.encode(text))})
print(json.dumps(out))
'@
    $countPath = Join-Path $env:TEMP ("ollama-tune-count-" + [guid]::NewGuid().ToString("N") + ".py")
    [System.IO.File]::WriteAllText($countPath, $countScript, (New-Object System.Text.UTF8Encoding $false))
    try {
        $raw = & $python $countPath @($logFiles | ForEach-Object { $_.FullName }) 2>&1 | Out-String
    } finally {
        Remove-Item -LiteralPath $countPath -Force -ErrorAction SilentlyContinue
    }
    try { $counted = $raw | ConvertFrom-Json }
    catch {
        Stop-WithReason @("REFUSED: the token counter did not return JSON.",
                          "  " + ($raw.Trim() -split "`n")[0])
    }
    if ($counted.PSObject.Properties.Name -contains "error") {
        Stop-WithReason @("REFUSED: $($counted.error)",
                          "  Without a tokenizer this phase can only count bytes, and a",
                          "  byte count is not a token count.")
    }

    # Classified by the driver's own naming: a plan message is written as
    # <stamp>-<plan>-r<round>-prompt.txt, an audit as *-audit-prompt.txt or
    # *-audit-<batch>-prompt.txt. They are reported apart because the audit
    # embeds source and the plan step does not, so their maxima are different
    # questions.
    $planRows  = @($counted | Where-Object { $_.name -notlike "*audit*" })
    $auditRows = @($counted | Where-Object { $_.name -like "*audit*" })

    function Summarise($rows, [string]$label) {
        if ($rows.Count -eq 0) { return @("  $label none found") }
        $t = @($rows | ForEach-Object { [int]$_.tokens })
        $max = ($t | Measure-Object -Maximum).Maximum
        $avg = [int](($t | Measure-Object -Average).Average)
        $biggest = ($rows | Sort-Object -Property tokens -Descending)[0]
        return @(("  {0,-22} n={1,-4} max={2,8}  mean={3,8}   largest: {4}" -f `
                  $label, $rows.Count, (Format-Int $max), (Format-Int $avg), $biggest.name))
    }

    $allTokens = @($counted | ForEach-Object { [int]$_.tokens })
    $observedMax = ($allTokens | Measure-Object -Maximum).Maximum
    # What that message implies for the window: the message itself, plus
    # everything aider adds around it, plus room to reply.
    $impliedWindow = $observedMax + $harnessTokens + $mapTokens + $alwaysOn +
                     $skillCeiling + $replyTokens

    Write-Host "=============================================================" -ForegroundColor Cyan
    Write-Host "Empirical floor: what the harness actually sent"
    Write-Host ""
    foreach ($l in (Summarise $planRows  "plan messages")) { Write-Host $l }
    foreach ($l in (Summarise $auditRows "audit messages")) { Write-Host $l }
    Write-Host ""
    Write-Host ("  largest message observed        {0,9}" -f (Format-Int $observedMax))
    Write-Host ("  + harness overhead              {0,9}" -f (Format-Int $harnessTokens))
    Write-Host ("  + repo map                      {0,9}" -f (Format-Int $mapTokens))
    Write-Host ("  + conventions.md and rules.md   {0,9}" -f (Format-Int $alwaysOn))
    Write-Host ("  + skills, largest stage         {0,9}" -f (Format-Int $skillCeiling))
    Write-Host ("  + reply reserve                 {0,9}" -f (Format-Int $replyTokens))
    Write-Host "  ------------------------------------------"
    Write-Host ("  WINDOW THIS RUN ACTUALLY NEEDED {0,9}" -f (Format-Int $impliedWindow)) -ForegroundColor Green
    Write-Host ("  against the ceiling floor of    {0,9}" -f (Format-Int $workingMinimum))
    Write-Host "=============================================================" -ForegroundColor Cyan
    Write-Host ""
    if ($impliedWindow -lt $workingMinimum) {
        $saved = $workingMinimum - $impliedWindow
        Write-Host ("The ceilings reserve {0} tokens more than this run needed." -f (Format-Int $saved))
        Write-Host "Every one of those is KV cache that displaced model weights off the"
        Write-Host "card. Section 1.1 of CONFIG_OLLAMA.md has the arithmetic."
    } else {
        Write-Host "This run needed at least as much as the ceilings reserve, so there is"
        Write-Host "nothing to reclaim: the allowances are sized correctly for this project."
    }
    Write-Host ""
    Write-Host "One caution. This is the largest message SEEN, not the largest possible."
    Write-Host "progress.md grows with every plan, so a ceiling set from a short project"
    Write-Host "will be too small later. Leave headroom above the figure above rather"
    Write-Host "than setting a ceiling equal to it."
    exit 0
}

# --- the measurement --------------------------------------------------------

$reportDir = Join-Path $env:TEMP ("ollama-tune-" + (Get-Date -Format "yyyyMMdd-HHmmss"))
$phasesToRun = @()
switch ($Phase) {
    "floor"     { $phasesToRun = @() }
    "bandwidth" { $phasesToRun = @(@{name="bandwidth"; probeArgs=@("--mode","bandwidth")}) }
    "threads"   { $phasesToRun = @(@{name="sweep";     probeArgs=@("--mode","sweep")}) }
    "layers"    { $phasesToRun = @(@{name="gpu_layers";probeArgs=@("--mode","gpulayers")}) }
    "repeat"    {
        # The careful run: every offload rung measured several times, so a
        # difference smaller than the machine's own noise is not mistaken for
        # a result. Measured 2026-09-05, one setting varied 16 percent across
        # three runs - wider than the gap between settings.
        if ($Repeats -lt 2) { $Repeats = 3 }
        $phasesToRun = @(@{name="gpu_layers"; probeArgs=@("--mode","gpulayers")})
    }
    "context"   { $phasesToRun = @(@{name="context";   probeArgs=@("--mode","context")}) }
    "quick" {
        $phasesToRun = @(
            @{name="bandwidth";  probeArgs=@("--mode","bandwidth")},
            @{name="sweep";      probeArgs=@("--mode","sweep","--threads","8","14","20")},
            @{name="gpu_layers"; probeArgs=@("--mode","gpulayers","--num-gpu","5","12")}
        )
    }
    "full" {
        $phasesToRun = @(
            @{name="bandwidth";  probeArgs=@("--mode","bandwidth")},
            @{name="sweep";      probeArgs=@("--mode","sweep")},
            @{name="gpu_layers"; probeArgs=@("--mode","gpulayers")},
            @{name="context";    probeArgs=@("--mode","context")}
        )
    }
}

if ($DryRun) {
    Write-Host "DRY RUN - nothing will be loaded and nothing written." -ForegroundColor Yellow
    Write-Host "  probe        $Probe"
    Write-Host "  interpreter  $python"
    Write-Host "  phase        $Phase"
    foreach ($p in $phasesToRun) {
        $shown = $p.probeArgs
        if ($Repeats -gt 1) { $shown = $shown + @("--repeats", "$Repeats") }
        Write-Host ("  would run    python aider-thread-probe.py " + ($shown -join " "))
    }
    if ($Apply) { Write-Host "  would write  $ConfigOllamaMd" }
    else        { Write-Host "  would write  nothing (pass -Apply to update CONFIG_OLLAMA.md)" }
    exit 0
}

$results = @{}
if ($phasesToRun.Count -gt 0) {
    New-Item -ItemType Directory -Force -Path $reportDir | Out-Null
    foreach ($p in $phasesToRun) {
        $json = Join-Path $reportDir ($p.name + ".json")
        Write-Host ("--- phase: " + $p.name) -ForegroundColor Cyan
        $argv = @($Probe) + $p.probeArgs + @("--json", $json)
        if ($Repeats -gt 1) { $argv += @("--repeats", "$Repeats") }
        & $python @argv
        if ($LASTEXITCODE -ne 0) {
            Write-Host ("  phase " + $p.name + " exited " + $LASTEXITCODE +
                        " - its rows are used only if the report parsed") -ForegroundColor Yellow
        }
        if (Test-Path -LiteralPath $json) {
            try { $results[$p.name] = Get-Content -LiteralPath $json -Raw -Encoding UTF8 | ConvertFrom-Json }
            catch { Write-Host "  report did not parse: $json" -ForegroundColor Yellow }
        }
        Write-Host ""
    }
}

# --- the recommendation -----------------------------------------------------
# Each line either cites a measurement or says it is absent. A recommendation
# with no measurement behind it is the thing this script exists to replace.

function Get-BestRow($rows, [string]$field) {
    $usable = @($rows | Where-Object { $null -ne $_.$field })
    if ($usable.Count -eq 0) { return $null }
    return ($usable | Sort-Object -Property $field -Descending)[0]
}

$rec = @()
$rec += "Recommended Ollama configuration for this machine"
$rec += ""

# num_ctx: the smallest configured rung that holds the working minimum.
$ctxRows = @()
if ($results.ContainsKey("context")) { $ctxRows = @($results["context"].context) }
$recommendedCtx = $null
if ($ctxRows.Count -gt 0) {
    $granted = @($ctxRows | Where-Object { $null -ne $_.n_ctx_granted } |
                 Sort-Object -Property n_ctx_granted)
    foreach ($row in $granted) {
        if ([int]$row.n_ctx_granted -ge $workingMinimum) { $recommendedCtx = [int]$row.n_ctx_granted; break }
    }
    if ($null -eq $recommendedCtx -and $granted.Count -gt 0) {
        $largest = [int]$granted[-1].n_ctx_granted
        $rec += "  num_ctx      NO measured window holds the working minimum of"
        $rec += "               $(Format-Int $workingMinimum) tokens. The largest the daemon granted was"
        $rec += "               $(Format-Int $largest). Either lower the ceilings in context-budget.json"
        $rec += "               or accept plans that touch fewer, smaller files."
    }
}
if ($null -ne $recommendedCtx) {
    $rec += "  num_ctx      $recommendedCtx"
    $rec += "               smallest measured window holding the $(Format-Int $workingMinimum)-token working minimum"
} elseif ($ctxRows.Count -eq 0) {
    $rec += "  num_ctx      >= $(Format-Int $workingMinimum) (arithmetic only - run -Phase context to measure the cost)"
}

# num_gpu: the forced-offload rung with the best decode.
$layerRows = @()
if ($results.ContainsKey("gpu_layers")) { $layerRows = @($results["gpu_layers"].gpu_layers) }
$bestLayer = Get-BestRow $layerRows "decode_tps"
if ($bestLayer) {
    $rec += "  num_gpu      $($bestLayer.layers_offloaded)"
    $rec += "               measured $($bestLayer.decode_tps) tok/s, best of $($layerRows.Count) offload rung(s)"
    $baseline = @($layerRows | Where-Object { $null -ne $_.layers_offloaded } |
                  Sort-Object -Property layers_offloaded)[0]
    if ($baseline -and $baseline.decode_tps -and $baseline.layers_offloaded -ne $bestLayer.layers_offloaded) {
        $gain = 100.0 * ($bestLayer.decode_tps - $baseline.decode_tps) / $baseline.decode_tps
        $rec += ("               against {0} tok/s at {1} layers, the allocator's own choice: {2:N1} percent" -f `
                 $baseline.decode_tps, $baseline.layers_offloaded, $gain)
    }
} else {
    $rec += "  num_gpu      not measured - run -Phase layers"
}

# num_thread: best decode, with the spread stated so the precision is not overread.
$threadRows = @()
if ($results.ContainsKey("sweep")) { $threadRows = @($results["sweep"].sweep) }
$bestThread = Get-BestRow $threadRows "decode_tps"
if ($bestThread) {
    # The fastest rung is NOT automatically the right one. Measured 2026-09-05,
    # 20 threads returned 3.41 tok/s at 99.4 percent CPU while 14 returned 3.39
    # at 81.3 - a 0.6 percent gain for a machine that is then unusable for
    # anything else. So the recommendation is the LOWEST rung that is within
    # tolerance of the best, and the best is reported beside it.
    $tolerance = 3.0
    if ($null -ne $budget.report -and $null -ne $budget.report.tie_tolerance_pct) {
        $tolerance = [double]$budget.report.tie_tolerance_pct
    }
    $threshold = [double]$bestThread.decode_tps * (1.0 - ($tolerance / 100.0))
    $withinTolerance = @($threadRows |
        Where-Object { $null -ne $_.decode_tps -and $null -ne $_.num_thread_granted -and
                       [double]$_.decode_tps -ge $threshold } |
        Sort-Object -Property num_thread_granted)
    $pick = if ($withinTolerance.Count -gt 0) { $withinTolerance[0] } else { $bestThread }

    $rec += "  num_thread   $($pick.num_thread_granted)"
    $rec += ("               {0} tok/s at {1} percent CPU" -f $pick.decode_tps, $pick.cpu_pct_mean)
    if ($pick.num_thread_granted -ne $bestThread.num_thread_granted) {
        $rec += ("               the fastest rung was {0} threads at {1} tok/s and {2} percent CPU," -f `
                 $bestThread.num_thread_granted, $bestThread.decode_tps, $bestThread.cpu_pct_mean)
        $rec += ("               within {0} percent, so the lower rung is preferred: the CPU left" -f $tolerance)
        $rec += "               over is what keeps the machine usable while a night runs"
    }

    # Noise can only be estimated from REPEATS of one rung. The previous version
    # reported max-minus-min across every rung and called it spread, which
    # labelled the genuine 4-to-20-thread signal as measurement scatter.
    $repeatNoise = $null
    foreach ($grp in ($threadRows | Where-Object { $null -ne $_.decode_tps -and $null -ne $_.num_thread_granted } |
                      Group-Object -Property num_thread_granted)) {
        if ($grp.Count -lt 2) { continue }
        $v = @($grp.Group | ForEach-Object { [double]$_.decode_tps })
        $lo = ($v | Measure-Object -Minimum).Minimum
        $hi = ($v | Measure-Object -Maximum).Maximum
        if ($lo -gt 0) {
            $pct = 100.0 * ($hi - $lo) / $lo
            if ($null -eq $repeatNoise -or $pct -gt $repeatNoise) { $repeatNoise = $pct }
        }
    }
    if ($null -ne $repeatNoise) {
        $rec += ("               run-to-run noise on a repeated rung: {0:N0} percent" -f $repeatNoise)
    } else {
        $rec += "               run-to-run noise NOT measured: no rung was run twice."
        $rec += "               Raise sweep.repeats before separating rungs that look close."
    }
} else {
    $rec += "  num_thread   not measured - run -Phase threads"
}

# The bandwidth ceiling, which is why a thread count stops helping.
$bwRows = @()
if ($results.ContainsKey("bandwidth")) { $bwRows = @($results["bandwidth"].bandwidth) }
$bestBw = Get-BestRow $bwRows "gb_per_s"
if ($bestBw) {
    $rec += ""
    $rec += ("  DRAM read bandwidth peaks at {0:N1} GB/s with {1} concurrent readers." -f `
             $bestBw.gb_per_s, $bestBw.workers)
    $rec += "  Weights read from system RAM are bounded by that figure, which is why"
    $rec += "  moving layers onto the card is worth more than adding threads."
}

$rec += ""
$rec += "Apply these in the Modelfile of a tuned tag, or as options on the request."
$rec += "Nothing in this script changes an Ollama setting: that stays a deliberate edit."

Write-Host "=============================================================" -ForegroundColor Green
foreach ($l in $rec) { Write-Host $l }
Write-Host "=============================================================" -ForegroundColor Green
Write-Host ""

# --- writing the results block ----------------------------------------------

if (-not $Apply) {
    Write-Host "Not written. Pass -Apply to update $([IO.Path]::GetFileName($ConfigOllamaMd))." -ForegroundColor Yellow
    exit 0
}
if (-not (Test-Path -LiteralPath $ConfigOllamaMd)) {
    Stop-WithReason @("REFUSED: $ConfigOllamaMd does not exist, so there is no",
                      "  RESULTS block to fill. Nothing was written.")
}

$beginMark = "<!-- RESULTS:BEGIN -->"
$endMark   = "<!-- RESULTS:END -->"
$doc = [System.IO.File]::ReadAllText($ConfigOllamaMd)
if (($doc.IndexOf($beginMark) -lt 0) -or ($doc.IndexOf($endMark) -lt 0)) {
    Stop-WithReason @("REFUSED: $ConfigOllamaMd carries no RESULTS block.",
                      "  Expected the markers $beginMark and $endMark.",
                      "  Nothing was written, rather than appending to the end of a",
                      "  document and hoping a reader finds it.")
}

$block = @()
$block += $beginMark
$block += ""
$block += "> Measured on this machine " + (Get-Date -Format "yyyy-MM-dd HH:mm") +
          " by ``ollama-tune.ps1 -Phase $Phase``."
$block += ""
$block += '```'
$block += $floorLines
$block += ""
$block += $rec
$block += '```'
$block += ""
$block += $endMark

$before = $doc.Substring(0, $doc.IndexOf($beginMark))
$after  = $doc.Substring($doc.IndexOf($endMark) + $endMark.Length)
$newDoc = $before + ($block -join "`r`n") + $after
# UTF8 without a BOM: PowerShell 5.1's own -Encoding UTF8 writes one, and a BOM
# breaks a reader that parses the file as plain text.
[System.IO.File]::WriteAllText($ConfigOllamaMd, $newDoc, (New-Object System.Text.UTF8Encoding $false))
Write-Host "RESULTS block written to $ConfigOllamaMd" -ForegroundColor Green
exit 0
