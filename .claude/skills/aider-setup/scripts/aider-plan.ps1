<#
.SYNOPSIS
  Run a project's numbered plans through aider, one plan per process, then audit.

.DESCRIPTION
  Layout, all under the project's docs/superpowers/plans/ :

      spec.md          what is being built. Read-only for the model.
      plan1.md ...     one numbered plan per stage. Read-only for the model.
      progress.md      the ledger, one "## <filename>" section per file.
      todo/            where a completed file is archived.
      audit.md         written by the audit pass at the end.

  The context window is dropped between plans because each plan runs in a NEW
  aider process. That is the only drop that is guaranteed: asking a model to
  forget leaves whatever it chose to keep, whereas a process that has exited
  holds nothing.

  Archiving happens here and never in the model, because moving a file is a
  filesystem operation with an exact rule - every box in that plan's section is
  [x] - and a model asked to tidy up will eventually move the wrong one.

  The audit pass hands every source file to aider as READ-ONLY, so it cannot
  edit code even if it decides it should. It writes audit.md and nothing else.

  The protocol itself lives in ~/.config/aider/conventions.md, which
  ~/.aider.conf.yml reads into every run.

  Written 2026-09-02.

.PARAMETER Path
  Project directory. Defaults to the current directory.

.PARAMETER TokenCeiling
  Budget for spec.md, progress.md and each plan. They are re-read on every run.

.PARAMETER CodeCeiling
  Budget for a source file. Over it, the audit is asked to name a split.

.PARAMETER Strict
  Turn an over-budget protocol file from a warning into a stop.

.PARAMETER NoAudit
  Run the plans and review nothing: neither the per-plan audit nor the final
  pass. Measured 2026-09-03: the per-plan audit is the slow half of a run - 46
  minutes against 19 for the plan itself - so a switch that left it running was
  a switch that saved nothing, whatever its name suggested.

.PARAMETER DryRun
  Report everything and start nothing.

.EXAMPLE
  aider-plan.ps1 -DryRun
  aider-plan.ps1
  aider-plan.ps1 -Path C:\work\myproject -NoAudit
#>
[CmdletBinding()]
param(
    [string]$Path = ".",
    [int]$TokenCeiling = 4000,
    [int]$CodeCeiling = 16000,
    [switch]$Strict,
    [switch]$NoAudit,
    [switch]$DryRun,
    [string]$Model = "",
    [string]$Config = "",
    [string]$BudgetFile = "",
    [string]$TestCommand = "",
    [string]$Round = "",
    [switch]$AllowCloud,
    # Bind a skill to each stage of the run. Off by default, and when it is off
    # this file is never opened, so the pipeline behaves exactly as it did
    # before. A SWITCH rather than a third run mode on purpose: -DryRun -Skills
    # rehearses the new mode, which a separate mode could not have done.
    [switch]$Skills,
    [string]$SkillsFile = "",
    [string[]]$CodeExtensions = @(".py", ".ps1", ".js", ".ts", ".tsx", ".jsx",
                                  ".cs", ".c", ".h", ".cpp", ".java", ".go",
                                  ".rs", ".rb", ".sh", ".sql", ".m"),
    # What a plan may name as a file to CREATE, which is wider than what
    # counts as source. Measured 2026-09-05: the example's plan1 step 1 says
    # "Create config.json", and .json was on neither list, so the file was
    # never added to the chat and the step could not be carried out. The
    # requirements.txt convention had the same hole. Deliberately NOT .md:
    # spec.md, progress.md and the plans are the protocol, and a plan that
    # could rewrite them could rewrite its own instructions.
    [string[]]$DataExtensions = @(".json", ".txt", ".toml", ".yml", ".yaml",
                                  ".cfg", ".ini", ".csv")
)

$ErrorActionPreference = "Stop"

# --- the pure half ----------------------------------------------------------
# Dot-sourced, not imported: these functions read this script's own variables -
# $progress, $plansDir, $budget - and dot-sourcing is what keeps them in one
# scope. A missing file is an explicit stop rather than a run that dies later on
# a command nobody can find (R3, R8).
$corePath = Join-Path $PSScriptRoot "aider-plan-core.ps1"
if (-not (Test-Path -LiteralPath $corePath)) {
    Write-Host "REFUSED: aider-plan-core.ps1 is missing from $PSScriptRoot." -ForegroundColor Red
    Write-Host "  It carries the budget, ledger and run-record functions this script calls."
    exit 2
}
. $corePath

# --- The run record: what the harness is doing, right now -------------------
#
# The transcript is written through Write-Host and tee'd to a file, and
# Tee-Object does not flush until its pipeline ends. Measured 2026-09-03: the
# plan-1 log sat at ZERO bytes for eighteen minutes while the plan was being
# written correctly. So while a run is in flight there is nothing to look at,
# and an empty log reads as a hang.
#
# This record is the fix, and it is also the contract a viewer reads. It is
# rewritten at every state transition, whole and atomically, so a reader either
# sees the previous state or the next one and never half of either. It is small
# on purpose: state, where in the plan set, and the tick counts out of
# progress.md, which is the progression a person actually wants.
#
# Never written during a dry run, which is documented to write nothing.
$script:RunRecord = $null
$script:RunRecordPath = ""

# --- Resolve the layout ----------------------------------------------------
$proj     = (Resolve-Path -LiteralPath $Path).Path
# -Round names a SUBDIRECTORY of the plans directory, with its own spec,
# progress, audit and plan files, so a correction pass can be kept beside the
# first attempt instead of overwriting it. The whole layout follows it - todo/,
# .logs/, the audit sandboxes - because every path below derives from this one.
# Empty means the plans directory itself, which is the ordinary case.
$plansDir = Join-Path $proj "docs\superpowers\plans"
if ($Round -ne "") {
    $plansDir = Join-Path $plansDir $Round
    if (-not (Test-Path -LiteralPath $plansDir)) {
        Write-Refusal @("REFUSED: -Round '$Round' names no directory at $plansDir.",
                        "  A round is a directory holding its own spec.md, progress.md and",
                        "  plan files, created deliberately - never one this driver invents.")
        exit 2
    }
}
$todoDir  = Join-Path $plansDir "todo"
$spec     = Join-Path $plansDir "spec.md"
$progress = Join-Path $plansDir "progress.md"
$auditMd  = Join-Path $plansDir "audit.md"

Write-Section "Project: $proj"

if (-not (Test-Path -LiteralPath $plansDir)) {
    Write-Refusal @("REFUSED: $plansDir is missing.",
                    "  Plans, spec and progress all live under docs\superpowers\plans\.")
    exit 2
}
foreach ($required in @($spec, $progress)) {
    if (-not (Test-Path -LiteralPath $required)) {
        Write-Refusal @("REFUSED: $(Split-Path $required -Leaf) is missing from $plansDir.",
                        "  The protocol needs spec.md and progress.md before any plan runs.")
        exit 2
    }
}

# --- Refuse to run a whole night against a protected branch ----------------
# Commits are on and ~/.git-hooks/pre-commit refuses main and master, so a run
# started there would fail every commit until morning.
Push-Location $proj
try {
    $branch = (& git symbolic-ref --short HEAD 2>$null)
    if ($LASTEXITCODE -ne 0) { $branch = $null }
} finally { Pop-Location }

if ($null -eq $branch) {
    Write-Host "WARNING: not on a branch (no git repo, or detached HEAD)." -ForegroundColor Yellow
    Write-Host "  aider's commits and its /undo will not work here." -ForegroundColor Yellow
} elseif ($branch -eq "main" -or $branch -eq "master") {
    Write-Refusal @("REFUSED: on protected branch '$branch'.",
                    "  Every commit would be refused by the pre-commit hook.",
                    "  Branch first:  git switch -c <name>")
    exit 2
} else {
    Write-Host "Branch: $branch"
}

# --- Discover the plans, in numeric order ----------------------------------
# Sorted by the number in the name, so plan10 follows plan9 rather than plan1.
$plans = @(Get-ChildItem -LiteralPath $plansDir -Filter "plan*.md" -File |
           Where-Object { $_.BaseName -match '^plan(\d+)$' } |
           Sort-Object { [int]([regex]::Match($_.BaseName, '\d+').Value) })

if ($plans.Count -eq 0 -and $NoAudit) {
    Write-Refusal @("REFUSED: no plan<N>.md left in $plansDir and -NoAudit was passed.",
                    "  Nothing to do.")
    exit 2
}
if ($plans.Count -eq 0) {
    Write-Host "Plans: none left - going straight to the audit pass."
} else {
    Write-Host ("Plans: " + (($plans | ForEach-Object { $_.Name }) -join ", "))
}

Initialize-RunRecord $proj ([bool]$DryRun)
Update-RunRecord @{ state = "starting"; branch = $branch; plan_count = $plans.Count
                    model_writer = $resolved; skills = [bool]$Skills }

# --- Token counting --------------------------------------------------------
# Counted with tiktoken out of aider's own environment. cl100k_base is not the
# local model's tokenizer, so the figure is an estimate within a few percent,
# which is all a ceiling needs.
$venvPython = Join-Path (& uv tool dir).Trim() "aider-chat\Scripts\python.exe"

# --- Which model will actually run -----------------------------------------
# Asked of aider rather than assumed, because aider resolves a model from its
# own merged configuration and, failing that, from whatever API key happens to
# be in the environment. Measured 2026-09-02: with no config file reachable it
# silently chose gemini/gemini-2.5-pro-exp-03-25 - a paid cloud model - because
# GEMINI_API_KEY was set. Unattended, that spends a quota all night with nothing
# said. So the model is resolved first, printed, and refused when it is not a
# local tag.
$baseArgs = @()
if ($Config -ne "") {
    if (-not (Test-Path -LiteralPath $Config)) {
        Write-Refusal @("REFUSED: config file not found: $Config")
        exit 2
    }
    $baseArgs += @("--config", (Resolve-Path -LiteralPath $Config).Path)
}
if ($Model -ne "") { $baseArgs += @("--model", $Model) }

function Resolve-AiderModel([string[]]$probeArgs) {
    # Assigned, never emitted: a PowerShell function returns everything it
    # writes, and this one must return only the tag.
    #
    # The four suppression flags are what keep this probe from writing into the
    # project, which a dry run is documented never to do. Measured 2026-09-03,
    # each combination in its own fresh repository, and each flag removes exactly
    # one artefact that the previous one exposed:
    #
    #   no extra flags                -> .gitignore              (aider adds '.aider*')
    #   --no-gitignore                -> .aider.chat.history.md, .aider.tags.cache.v4/
    #   + --map-tokens 0              -> .aider.chat.history.md
    #   + the three history redirects -> nothing
    #
    # The resolved tag was identical in all four, so suppression does not change
    # the answer this probe exists to give. The first artefact is invisible once a
    # real run has happened, since .gitignore then already exists - which is why
    # only a first dry run, on a student's machine, ever saw it.
    $sink = Join-Path $env:TEMP ("aider-probe-" + [guid]::NewGuid().ToString("N"))
    $null = New-Item -ItemType Directory -Force -Path $sink
    try {
        $quiet = @("--no-gitignore", "--map-tokens", "0",
                   "--chat-history-file",  (Join-Path $sink "chat.md"),
                   "--input-history-file", (Join-Path $sink "input.txt"),
                   "--llm-history-file",   (Join-Path $sink "llm.txt"))
        $out = & aider @probeArgs --no-check-update --exit --no-show-model-warnings @quiet 2>&1 | Out-String
    }
    finally {
        Remove-Item -LiteralPath $sink -Recurse -Force -ErrorAction SilentlyContinue
    }
    if ($out -match '(?m)^\s*(?:Main model|Model):\s*(\S+)') { return $Matches[1] }
    return $null
}

Write-Section "Model"
Push-Location $proj
try { $resolved = Resolve-AiderModel $baseArgs } finally { Pop-Location }

if ($null -eq $resolved) {
    Write-Refusal @("REFUSED: could not determine which model aider would use.",
                    "  Pass -Config <path to aider.conf.yml> or -Model <tag>.")
    exit 2
}
Write-Host "  $resolved"
if ($resolved -notlike "ollama_chat/*" -and $resolved -notlike "ollama/*" -and -not $AllowCloud) {
    Write-Refusal @("REFUSED: '$resolved' is not a local model.",
                    "  An unattended run on a paid API can spend a quota all night.",
                    "  Pass -Config to name the local configuration, -Model to pin a tag,",
                    "  or -AllowCloud if a cloud model is genuinely what you want.")
    exit 2
}

# --- The context budget ----------------------------------------------------
# Every number below is either measured here or read from context-budget.json.
# None is written in this script (R0), and a key missing from the file is named
# rather than defaulted (R3).
if ($BudgetFile -eq "") {
    if ($Config -ne "") { $BudgetFile = Join-Path (Split-Path -Parent (Resolve-Path -LiteralPath $Config).Path) "context-budget.json" }
    else                { $BudgetFile = Join-Path $HOME ".config\aider\context-budget.json" }
}
if (-not (Test-Path -LiteralPath $BudgetFile)) {
    Write-Refusal @("REFUSED: context budget file not found: $BudgetFile",
                    "  Pass -BudgetFile, or place context-budget.json beside the aider config.")
    exit 2
}
try { $budget = Get-Content -LiteralPath $BudgetFile -Raw -Encoding UTF8 | ConvertFrom-Json }
catch {
    Write-Refusal @("REFUSED: $BudgetFile does not parse as JSON.", "  $($_.Exception.Message)")
    exit 2
}

$replyReserve   = [int](Get-BudgetValue $budget "reserve.reply_tokens")
$harnessReserve = [int](Get-BudgetValue $budget "reserve.harness_overhead_tokens")
$mapTokens      = [int](Get-BudgetValue $budget "repo_map_tokens")
$ceilings       = Get-BudgetValue $budget "ceilings"
$codeCeiling    = [int](Get-BudgetValue $budget "ceilings.code_file")
# The per-file OUTPUT ceiling, distinct from ceilings.code_file, which bounds a
# file the model READS. This one bounds what it writes, and the reply has to
# hold every file a plan creates at once.
$codeFileOutputCeiling = [int](Get-BudgetValue $budget "ceilings.code_file_output")
$maxFilesTouched= [int](Get-BudgetValue $budget "plan.max_files_touched")

$auditMargin    = [int](Get-BudgetValue $budget "audit.batch_safety_margin_tokens")
$auditMaxFiles  = [int](Get-BudgetValue $budget "audit.max_files_per_batch")
$alwaysOnFiles  = @(Get-BudgetValue $budget "always_on_files")

$ollamaBase     = [string](Get-BudgetValue $budget "ollama.api_base")
$unloadWait     = [int](Get-BudgetValue $budget "ollama.unload_wait_seconds")
$unloadPoll     = [int](Get-BudgetValue $budget "ollama.unload_poll_seconds")
$auditModel     = [string](Get-BudgetValue $budget "audit.model")
$auditPerPlan   = [bool](Get-BudgetValue $budget "audit.per_plan")
$auditRounds    = [int](Get-BudgetValue $budget "audit.max_rounds_per_plan")
$testsRequired  = [bool](Get-BudgetValue $budget "tests.required")
$testPatterns   = @(Get-BudgetValue $budget "tests.file_patterns")
$testExempt     = @(Get-BudgetValue $budget "tests.exempt_name_patterns")
$testCmd        = [string](Get-BudgetValue $budget "tests.command")
if ($TestCommand -ne "") { $testCmd = $TestCommand }
if ($testsRequired -and $testCmd -eq "") {
    Write-Refusal @("REFUSED: tests are required but no test command is set.",
                    "  Pass -TestCommand `"<command>`", or set tests.command in $BudgetFile.",
                    "  It is deliberately not guessed: running the wrong command and reading",
                    "  its success is worse than running none.")
    exit 2
}

# The command line still wins, so a one-off run can override the file.
if ($PSBoundParameters.ContainsKey('CodeCeiling')) { $codeCeiling = $CodeCeiling }

Write-Section "Context budget"
$settingsFile = Join-Path $HOME ".config\aider\model-settings.yml"
if ($Config -ne "") {
    $sibling = Join-Path (Split-Path -Parent (Resolve-Path -LiteralPath $Config).Path) "model-settings.yml"
    if (Test-Path -LiteralPath $sibling) { $settingsFile = $sibling }
}
$window = Get-ModelWindow $resolved
if ($window -le 0) {
    Write-Refusal @("REFUSED: aider reports no context window for '$resolved'.",
                    "  Without it nothing here can be budgeted; declare max_input_tokens",
                    "  in a model metadata file, or pin a tag aider knows.")
    exit 2
}

# The window aider REPORTS must equal the num_ctx model-settings.yml SENDS.
# They come from different places - metadata versus extra_params - and when
# the metadata is absent aider answers with the architecture's native maximum
# instead, which on a tuned tag is several times the truth. Every budget below
# is computed from this number, so a wrong one is not a wrong report, it is a
# night spent sizing prompts against a window that was never allocated.
$declaredCtx = 0
if (Test-Path -LiteralPath $settingsFile) {
    # No YAML parser here on purpose: one entry, one key, and adding a
    # dependency to read a single integer costs more than it saves.
    $inEntry = $false
    foreach ($line in (Get-Content -LiteralPath $settingsFile -Encoding UTF8)) {
        if ($line -match '^\s*-\s+name:\s*(\S+)') {
            $inEntry = ($Matches[1] -eq $resolved)
            continue
        }
        if ($inEntry -and $line -match '^\s+num_ctx:\s*(\d+)') {
            $declaredCtx = [int]$Matches[1]
            break
        }
    }
}
if ($declaredCtx -gt 0 -and $window -ne $declaredCtx) {
    Write-Refusal @(
        "REFUSED: the window this run would budget against is not the one it will get.",
        "  aider reports max_input_tokens : $window",
        "  model-settings.yml sends num_ctx: $declaredCtx",
        "  The second is what Ollama allocates. The first is what every budget",
        "  below is computed from, and it comes from litellm metadata - so this",
        "  usually means ~/.aider.model.metadata.json has no entry for",
        "  '$resolved' and aider fell back to asking Ollama, which answers with",
        "  the architecture's native maximum whatever the tag bakes in.",
        "  Fix: run aider-ollama-config.py, which writes both files from the",
        "  same computation. Manual step 4.")
    exit 2
}

$alwaysOn = 0
$alwaysOnArgs = @()
# Collected across BOTH the always-on files and the protocol files: declared
# here rather than at the protocol section, where it used to be reset and
# silently discarded every over-budget always-on file.
$over = @()
foreach ($f in $alwaysOnFiles) {
    if (-not (Test-Path -LiteralPath $f)) {
        Write-Refusal @("REFUSED: always-on file listed in $BudgetFile does not exist:", "  $f")
        exit 2
    }
    $n = Get-TokenCount $f
    $label = Split-Path $f -Leaf
    if ($n -lt 0) {
        Write-Refusal @("REFUSED: cannot measure always-on file: $f")
        exit 2
    }
    $ceil = Get-FileCeiling $label
    $flag = ""
    if ($n -gt $ceil) { $flag = " OVER"; $over += $label }
    Write-Host ("  {0,-24} {1,7} / {2,-6} always loaded{3}" -f $label, $n, $ceil, $flag)
    $alwaysOn += $n
    # Supplied HERE and not left to the config's own `read:` list. Measured
    # 2026-09-02: a --read on the command line REPLACES the config's read list
    # rather than adding to it, so every driver run had silently dropped
    # conventions.md and rules.md - the model was executing plans without ever
    # seeing a single coding rule, and nothing said so.
    $alwaysOnArgs += @("--read", (Resolve-Path -LiteralPath $f).Path)
}

# --- Skills, one bundle per stage ------------------------------------------
# A skill is read-only prose. aider has no skill system: nothing invokes these
# files and nothing enforces them, exactly as with conventions.md. They make the
# rules this pipeline already has harder to ignore, and add no capability.
#
# A skill is its SKILL.md PLUS every Markdown file that SKILL.md names, resolved
# beside it. Measured 2026-09-03: test-driven-development/SKILL.md refers to
# writing-good-tests.md, so passing the SKILL.md alone hands the model an
# instruction naming a document it does not have - worse than passing nothing.
# One level of resolution only, and a named file that is absent is a refusal by
# name, never a silent skip.
$skillFiles = @{ write = @(); audit = @(); reopen = @() }
$skillCost  = @{ write = 0;  audit = 0;  reopen = 0 }

if ($Skills) {
    $sf = $SkillsFile
    if ($sf -eq "") {
        $sf = if ($BudgetFile -ne "") {
                  Join-Path (Split-Path -Parent (Resolve-Path -LiteralPath $BudgetFile).Path) "skills.json"
              } else {
                  Join-Path $HOME ".config\aider\skills.json"
              }
    }
    if (-not (Test-Path -LiteralPath $sf)) {
        Write-Refusal @("REFUSED: -Skills was passed but no skills file was found:", "  $sf",
                        "  Pass -SkillsFile <path>, or drop -Skills to run without them.")
        exit 2
    }
    try { $skillCfg = Get-Content -LiteralPath $sf -Raw -Encoding UTF8 | ConvertFrom-Json }
    catch {
        Write-Refusal @("REFUSED: $sf does not parse as JSON:", "  $($_.Exception.Message)")
        exit 2
    }
    foreach ($stage in @("write", "audit", "reopen")) {
        $entry = $skillCfg.stages.$stage
        if ($null -eq $entry) {
            Write-Refusal @("REFUSED: $sf declares no '$stage' stage.",
                            "  All three of write, audit and reopen are required, because a",
                            "  stage silently running without its skill is the defect this",
                            "  switch exists to avoid.")
            exit 2
        }
        $paths = Resolve-SkillStage $stage $entry $sf
        $n = 0
        foreach ($p in $paths) {
            $c = Get-TokenCount $p
            if ($c -lt 0) { Write-Refusal @("REFUSED: cannot measure skill file: $p"); exit 2 }
            $n += $c
        }
        $skillFiles[$stage] = $paths
        $skillCost[$stage]  = $n
        $ceil = [int]$entry.ceiling
        $flag = ""
        if ($ceil -gt 0 -and $n -gt $ceil) { $flag = " OVER"; $over += "skill:$stage" }
        Write-Host ("  {0,-24} {1,7} / {2,-6} skill, {3} file(s){4}" -f
                    "(skill: $stage)", $n, $(if ($ceil -gt 0) { $ceil } else { "-" }), $paths.Count, $flag)
    }
}
# Only ONE stage is ever loaded at a time, so the worst case is the largest of
# them, not their sum. Charging the sum would refuse budgets that are fine.
$skillWorst = 0
foreach ($stage in @("write", "audit", "reopen")) {
    if ($skillCost[$stage] -gt $skillWorst) { $skillWorst = $skillCost[$stage] }
}
if ($Skills) {
    Write-Host ("  {0,-24} {1,7}  worst stage, charged to the budget" -f "(skill: worst case)", $skillWorst)
}

Write-Host ("  {0,-24} {1,7}  repo map" -f "(--map-tokens)", $mapTokens)
Write-Host ("  {0,-24} {1,7}  reserved for the reply" -f "(reply)", $replyReserve)
Write-Host ("  {0,-24} {1,7}  reserved for aider itself" -f "(harness)", $harnessReserve)

$workingBudget = $window - $alwaysOn - $mapTokens - $replyReserve - $harnessReserve - $skillWorst
Write-Host ("  {0,-24} {1,7}  window" -f "", $window)
Write-Host ("  {0,-24} {1,7}  left for the working set" -f "", $workingBudget) -ForegroundColor Green
if ($workingBudget -le 0) {
    Write-Refusal @("REFUSED: the fixed cost already exceeds the window.",
                    "  Shrink conventions.md, rules.md or the reserves in $BudgetFile.")
    exit 2
}
$baseArgs += @("--map-tokens", "$mapTokens")
$baseArgs += $alwaysOnArgs

Update-RunRecord @{ window = $window; working_set = $workingBudget; model_audit = $auditModel }

Write-Section "Protocol files (one ceiling per file)"
$protocolFiles = @($spec, $progress) + @($plans | ForEach-Object { $_.FullName })
if (Test-Path -LiteralPath $auditMd) { $protocolFiles += $auditMd }
foreach ($f in $protocolFiles) {
    $n = Get-TokenCount $f
    $name = Split-Path $f -Leaf
    $ceil = Get-FileCeiling $name
    if ($n -lt 0) {
        Write-Host ("  {0,-16} {1,6} / {2,-6} not counted" -f $name, "?", $ceil) -ForegroundColor Yellow
    } elseif ($n -gt $ceil) {
        Write-Host ("  {0,-16} {1,6} / {2,-6} OVER" -f $name, $n, $ceil) -ForegroundColor Yellow
        $over += $name
    } else {
        Write-Host ("  {0,-16} {1,6} / {2,-6}" -f $name, $n, $ceil)
    }
}
if ($over.Count -gt 0 -and $Strict) {
    Write-Refusal @("REFUSED (-Strict): over budget: $($over -join ', ')")
    exit 2
}

# --- Source files, and the per-file code ceiling ---------------------------
Push-Location $proj
try {
    $tracked = @(& git ls-files 2>$null)
    if ($LASTEXITCODE -ne 0) { $tracked = @() }
} finally { Pop-Location }

$sourceFiles = @()
$sourceTokens = @{}
foreach ($rel in $tracked) {
    $ext = [System.IO.Path]::GetExtension($rel)
    if ($CodeExtensions -contains $ext) {
        $sourceFiles += (Join-Path $proj ($rel.Replace('/', [System.IO.Path]::DirectorySeparatorChar)))
    }
}

Write-Section "Source files (ceiling $codeCeiling)"
$fat = @()
if ($sourceFiles.Count -eq 0) {
    Write-Host "  none tracked yet"
} else {
    foreach ($f in $sourceFiles) {
        $n = Get-TokenCount $f
        $sourceTokens[$f] = $n
        if ($n -gt $codeCeiling) {
            $rel = $f.Substring($proj.Length + 1)
            Write-Host ("  {0,-46} {1,6} OVER" -f $rel, $n) -ForegroundColor Yellow
            $fat += $rel
        }
    }
    Write-Host ("  {0} file(s) counted, {1} over the ceiling" -f $sourceFiles.Count, $fat.Count)
}

function Invoke-TestCommand([string]$logPath) {
    # Run by the DRIVER, never by the model: a fixed command the operator chose,
    # not one a model invented. Returns the exit code; output goes to the log.
    # The redirection happens INSIDE cmd, so PowerShell never sees the process's
    # stderr stream at all. In PowerShell 5.1, `& native 2>&1` wraps every
    # stderr line in an ErrorRecord, and with $ErrorActionPreference = "Stop"
    # that terminates the script. Measured 2026-09-02: `python -m unittest`
    # writes its results to stderr, so a suite of three passing tests killed the
    # driver with NativeCommandError and the run was reported as a failure.
    Push-Location $proj
    $prev = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        & cmd /c "$testCmd > `"$logPath`" 2>&1"
        $code = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $prev
        Pop-Location
    }
    if (Test-Path -LiteralPath $logPath) { Get-Content -LiteralPath $logPath | Out-Host }
    return [int]$code
}

function Wait-ModelsUnloaded([string]$why) {
    # Evict whatever is resident and WAIT for the daemon to say so before the
    # next model is asked for. OLLAMA_MAX_LOADED_MODELS=1 is meant to make the
    # swap exclusive, but nothing guarantees the eviction finishes before the
    # new load starts, and these two tags are 20 GB and 19 GB on a 32 GB
    # machine. 39 GB transiently is how a machine stops - one did, 2026-09-02.
    #
    # The caller's state is saved and RESTORED on the way out. Measured
    # 2026-09-03: without this, the record was left saying "evicting - unloading
    # qwen3.8 before the audit model loads" for the whole 46 minutes of the audit
    # that followed, because Invoke-PlanAudit sets its state BEFORE calling here
    # and never sets it again. A reader watching the record would have concluded
    # the eviction had hung and killed a healthy run - which is exactly the advice
    # this session gave before the defect was found.
    #
    # The state is restored in a finally, because every exit from the loop below
    # is a `return`.
    $callerState = if ($null -ne $script:RunRecord) { $script:RunRecord["state"] } else { $null }
    $callerNote  = if ($null -ne $script:RunRecord) { $script:RunRecord["note"] }  else { $null }
    try {
    $deadline = (Get-Date).AddSeconds($unloadWait)
    $first = $true
    while ((Get-Date) -lt $deadline) {
        $loaded = @()
        try {
            $ps = Invoke-RestMethod -Uri "$ollamaBase/api/ps" -TimeoutSec 15 -ErrorAction Stop
            if ($ps.models) { $loaded = @($ps.models | ForEach-Object { $_.name }) }
        } catch {
            # The daemon is unreachable. Say so and carry on: refusing here would
            # stop a run for a condition aider itself will report far better.
            Write-Host "  (cannot reach $ollamaBase to check residency)" -ForegroundColor Yellow
            return
        }
        if ($loaded.Count -eq 0) {
            if (-not $first) { Write-Host "  memory released" -ForegroundColor Green }
            return
        }
        if ($first) {
            Write-Host ("  unloading {0} before {1}" -f ($loaded -join ", "), $why)
            # A swap is three minutes of apparent silence, so it gets a state of
            # its own: without it a reader sees nothing happening and assumes a
            # hang.
            Update-RunRecord @{ state = "evicting"
                                note  = ("unloading " + ($loaded -join ", ") + " before " + $why) }
            foreach ($m in $loaded) {
                $body = @{ model = $m; keep_alive = 0 } | ConvertTo-Json -Compress
                try { $null = Invoke-RestMethod -Uri "$ollamaBase/api/generate" -Method Post -Body $body -ContentType "application/json" -TimeoutSec 60 } catch { }
            }
            $first = $false
        }
        Start-Sleep -Seconds $unloadPoll
    }
    Write-Host "  WARNING: a model was still resident after $unloadWait s" -ForegroundColor Yellow
    }
    finally {
        # Only if this function actually changed it. A swap that found nothing
        # resident never wrote "evicting", and restoring then would rewrite the
        # record for no reason and move `updated` on every poll.
        if ($null -ne $script:RunRecord -and
            $script:RunRecord["state"] -eq "evicting" -and $callerState -ne "evicting") {
            Update-RunRecord @{ state = $callerState; note = $callerNote }
        }
    }
}

function Invoke-PlanAudit([string]$planName, [string[]]$changedFiles, [string]$logPath) {
    # A DIFFERENT model reviews than the one that wrote the code.
    #
    # The source files are embedded in the MESSAGE, not handed over with --read,
    # and that is the whole design of this pass. Measured twice, 2026-09-02 and
    # 2026-09-03: given the sources as read-only files, the reviewer analysed
    # them correctly, found a real defect, and then ended its turn asking for
    # edit access. Its own log shows why, and it is not a wording problem:
    #
    #   "According to the rules: 'Only create SEARCH/REPLACE blocks for files
    #    that the user has added to the chat!' ... Since the audit findings
    #    require changes to tests/test_calc.py, and that file is read-only,
    #    I must ask for it."
    #
    # It was obeying aider's own system prompt, which outranks anything passed
    # in --message. No instruction of mine can win that argument. So the code
    # arrives as prompt text: there is then no read-only file in the chat to ask
    # for, and the only file it can act on is audit.md.
    $argv = @()
    if ($Config -ne "") { $argv += @("--config", (Resolve-Path -LiteralPath $Config).Path) }
    $argv += @("--model", $auditModel)
    # No repo map either: the code under review is in the message, in full, so a
    # map of summaries adds nothing but tokens and more filenames to ask about.
    $argv += @("--map-tokens", "0")
    $argv += $alwaysOnArgs

    $sourceBlock = ""
    foreach ($f in $changedFiles) {
        $rel = $f
        if ($f.StartsWith($proj, [StringComparison]::OrdinalIgnoreCase)) { $rel = $f.Substring($proj.Length + 1) }
        $body = Get-Content -LiteralPath $f -Raw -Encoding UTF8
        $sourceBlock += "`n`n----- $rel -----`n$body"
    }
    $specBody = Get-Content -LiteralPath $spec -Raw -Encoding UTF8

    $auditSkillBlock = ""
    foreach ($sp in $skillFiles["audit"]) {
        $auditSkillBlock += "=== HOW TO REVIEW: " + (Split-Path $sp -Leaf) + " ===`n" +
                            (Get-Content -LiteralPath $sp -Raw -Encoding UTF8) + "`n`n"
    }

    $msg = "You are reviewing code. Write a report. You are NOT editing code, and " +
           "no source file is open for editing in this chat - the code is quoted " +
           "below, as text. Asking for a file would end your turn with nothing " +
           "written, which is a failed review.`n`n" +
           # Asking a QUESTION is the same failure as asking for a file, and
           # the prompt forbade only the second. Measured 2026-09-06: the
           # reviewer ended its turn with "Voulez-vous que je procede aux
           # corrections ?" and wrote nothing, so the plan was blocked as
           # unaudited. Nobody is there to answer at 06:00.
           "There is no one to answer you: this is an unattended run. Never end " +
           "your turn with a question, a request for permission, or an offer to " +
           "make the fixes. Write the report and stop.`n`n" +
           "The only file you may edit is audit.md. Append to it, under a heading " +
           "'## $planName', your findings worst first, each naming the file, the " +
           "line, what is wrong and why it matters. Look at least for: a value " +
           "hard-coded where configuration belongs, a silent fallback, a missing " +
           "error path, a return code trusted where the effect should have been " +
           "verified, and a test that asserts only the happy path.`n`n" +
           "If you find nothing wrong, still write one line under that heading " +
           "saying the plan was reviewed and no problem was found. Writing nothing " +
           "is never the right answer.`n`n" +
           # The heading is ALREADY in audit.md on a second round, and that is
           # exactly when this failed: the reviewer read the section as done and
           # wrote only the ledger line. Measured 2026-09-06, plan1 round 2.
           # Single quotes INSIDE the double-quoted string. Written with
           # embedded double quotes on 2026-09-06 it became "If a " followed
           # by ##, which PowerShell reads as a COMMENT - so this clause, the
           # English instruction and the whole audit.md-before-ledger rule
           # were cut from the prompt. The file still parsed, the prompt file
           # was 991 bytes ending mid-word, and nothing reported it.
           "If a '## $planName' heading is already in audit.md from an earlier " +
           "round, APPEND under it anyway. A heading being present does not mean " +
           "this round has been reported; only your writing does.`n`n" +
           # Both audit prompts say this. The final-pass one was measured
           # writing its report in French on 2026-09-06 because nothing had
           # said otherwise, and this one had the same silence.
           "Write the report in English.`n`n" +
           # An ORDER, not a pair of equals. audit.md is the report; the ledger
           # line is its consequence, and a consequence whose cause was never
           # written is a line nobody can act on because nothing says why.
           "THEN, and only for a finding you have just written into audit.md, add " +
           "to progress.md under the heading '## $planName' ONE unticked line " +
           "'- [ ] audit: <what to fix>'. No line at all if there is nothing. Add " +
           "nothing else there, tick nothing, and leave every other section alone. " +
           "A ledger line whose finding is not in audit.md is a FAILED review: the " +
           "run is blocked and your report is the only thing that could have " +
           "explained it.`n`n" +
           # The skill goes HERE and nowhere earlier. The instruction above
           # forbids the reviewer from asking for a file; the reviewer brief
           # this stage loads was written for a subagent that MAY ask for one.
           # Measured: a full cycle once ran where the reviewer analysed
           # correctly, asked permission to fix the code, and audit.md came out
           # zero bytes. A skill placed before the guard is a skill that can
           # undo it. It is embedded as text rather than passed with --read for
           # the same reason the source is: the ordering is then ours, not
           # aider's.
           $auditSkillBlock +
           "=== THE SPECIFICATION THIS CODE IS MEASURED AGAINST ===`n" +
           $specBody + "`n`n" +
           "=== THE CODE THIS PLAN PRODUCED OR CHANGED ===" +
           $sourceBlock

    # --message-file, NEVER --message, and this is not a preference.
    #
    # PowerShell does not escape a multi-line argument containing double quotes
    # when it invokes a native executable. Measured 2026-09-03, reproduced
    # outside aider: passing
    #     def f():
    #         return "hello"
    # to a native command delivered exactly `"def f():` and dropped the rest.
    #
    # The damage was invisible and looked like a hallucinating model. Embedding
    # the source in --message stripped every string literal, so the reviewer
    # correctly reported seven NameErrors on `config.json`, `utf-8` and
    # `large_threshold` in code that was perfectly valid and whose tests had
    # just passed. It was reading faithfully; the harness had mangled the input.
    $msgFile = Join-Path $logDir ("$stamp-" + [System.IO.Path]::GetFileNameWithoutExtension($planName) + "-audit-prompt.txt")
    Write-Utf8NoBom $msgFile $msg

    # --- The review runs in a SANDBOX, and that is a harness rule now --------
    #
    # Embedding the source in the message removed the reviewer's REASON to ask
    # for a file. It did not remove its ABILITY to write one. Measured
    # 2026-09-06 on plan 5: the reviewer emitted SEARCH/REPLACE blocks for
    # tests/test_render_map.py, render_map.py and config.json; aider ADDED each
    # of those files to the chat by itself, because --yes answers that prompt
    # too; it applied the edits and committed them - while audit.md stayed at
    # 235 bytes and the plan was blocked as unaudited. The comment above, that
    # "the only file it can act on is audit.md", was an assumption and not a
    # mechanism.
    #
    # So the review now happens in a directory holding ONLY the two files it
    # may write. A source file it names does not exist there, so an edit block
    # creates a stray nobody reads instead of rewriting the project. The
    # instruction stays in the prompt, but nothing depends on it any more.
    $sandbox = Join-Path $logDir ("$stamp-" + [System.IO.Path]::GetFileNameWithoutExtension($planName) + "-audit-sandbox")
    if (Test-Path -LiteralPath $sandbox) { Remove-Item -LiteralPath $sandbox -Recurse -Force }
    New-Item -ItemType Directory -Force -Path $sandbox | Out-Null
    $sandAudit    = Join-Path $sandbox "audit.md"
    $sandProgress = Join-Path $sandbox "progress.md"
    Copy-Item -LiteralPath $auditMd  -Destination $sandAudit    -Force
    Copy-Item -LiteralPath $progress -Destination $sandProgress -Force

    # --no-git: there is no repository in the sandbox, so there is nothing for
    # the reviewer to commit into. The night's commits are the writer's
    # business and never the reviewer's.
    $argv += @($sandAudit, $sandProgress, "--message-file", $msgFile, "--yes",
               "--no-git", "--no-check-update", "--no-suggest-shell-commands")

    # Judged by the EFFECT rather than by trusting the sandbox to have worked
    # (R9).
    $before = Get-ProjectFingerprint
    $code = Invoke-Aider $argv $logPath $sandbox
    $null = Restore-ProjectIfTouched $before

    # The report comes back only NOW, after the guard has run, so restoring a
    # trespass can never also discard the reviewer's own output.
    Copy-Item -LiteralPath $sandAudit    -Destination $auditMd  -Force
    Copy-Item -LiteralPath $sandProgress -Destination $progress -Force

    # Anything else left in the sandbox is an edit the reviewer TRIED to make to
    # the code. Kept beside the log rather than deleted: it is the record of
    # what it would have changed, and it is worth reading.
    $strays = @(Get-ChildItem -LiteralPath $sandbox -Recurse -File |
                Where-Object { $_.Name -ne "audit.md" -and $_.Name -ne "progress.md" })
    if ($strays.Count -gt 0) {
        Write-Host ("  the reviewer tried to edit {0} file(s) it may not touch; kept in {1}" -f $strays.Count, $sandbox) -ForegroundColor Yellow
    }
    return $code
}

function Get-ProjectFingerprint() {
    # CONTENT hashes, not `git status` lines, and that distinction is the whole
    # value of this function. The first version compared porcelain output, so a
    # file the WRITER had already modified read as " M widget.py" both before
    # and after the reviewer rewrote it - the same line, no difference seen, no
    # restore. A stub reviewer walked straight through it. Whether the writer's
    # work happens to be committed before the audit is not something this guard
    # may depend on.
    #
    # A copy of every file that is already dirty is taken at the same time,
    # because git can restore a tracked-clean file and cannot restore one whose
    # pre-audit state exists nowhere but the working tree. That set is normally
    # empty and never large.
    $backup = Join-Path $logDir ("$stamp-preaudit-" + [guid]::NewGuid().ToString("N").Substring(0, 8))
    $hashes = @{}
    $saved  = @{}
    $dirty  = @{}
    foreach ($line in @(& cmd /c "git -C ""$proj"" status --porcelain 2>NUL")) {
        if ($line.Length -gt 3) { $dirty[$line.Substring(3).Trim('"')] = $line.Substring(0, 2) }
    }
    foreach ($f in Get-ChildItem -LiteralPath $proj -Recurse -File -Force -ErrorAction SilentlyContinue) {
        $rel = $f.FullName.Substring($proj.Length + 1).Replace("\", "/")
        if ($rel -like ".git/*" -or $rel -like "*/__pycache__/*" -or $rel -like ".venv/*") { continue }
        # aider's own bookkeeping, which it rewrites on every invocation
        # including the audit. Measured 2026-09-07 on the first sandboxed audit:
        # the guard correctly saw .aider.chat.history.md change and "restored"
        # it, which is both noise and a small hazard, since that file is aider's
        # and not the project's.
        if ($rel -like ".aider.*" -or $rel -like "*/.aider.*") { continue }
        # The driver's own logs and sandboxes live under the plans directory and
        # change constantly by design, so they are not the project.
        if ($rel -like "docs/superpowers/plans/.logs/*") { continue }
        $hashes[$rel] = (Get-FileHash -LiteralPath $f.FullName -Algorithm SHA256).Hash
        if ($dirty.ContainsKey($rel)) {
            $dst = Join-Path $backup $rel
            New-Item -ItemType Directory -Force -Path (Split-Path -Parent $dst) | Out-Null
            Copy-Item -LiteralPath $f.FullName -Destination $dst -Force
            $saved[$rel] = $dst
        }
    }
    return @{
        head   = (& cmd /c "git -C ""$proj"" rev-parse HEAD 2>NUL")
        hashes = $hashes
        saved  = $saved
        backup = $backup
    }
}

function Restore-ProjectIfTouched($before) {
    # The reviewer may not change the code. That was an instruction in the
    # prompt until 2026-09-06, when plan 5's reviewer emitted SEARCH/REPLACE
    # blocks for three source files it had never been given, aider ADDED each of
    # them to the chat by itself because --yes answers that prompt too, applied
    # the edits and committed them - while audit.md stayed at 235 bytes and the
    # plan was recorded as unaudited.
    #
    # Both audit paths now run in a sandbox, so this should stay silent for
    # ever. It exists anyway, because a rule with no check is what the previous
    # version of this file had, and one audit path was fixed while the other was
    # not - which is exactly what this guard caught.
    $after = Get-ProjectFingerprint
    $touched = $false

    if ($after.head -ne $before.head) {
        Write-Host ("  REVIEWER COMMITTED to the project ({0} -> {1}); reverting." -f $before.head, $after.head) -ForegroundColor Red
        & cmd /c "git -C ""$proj"" reset --hard ""$($before.head)"" 2>&1" | Out-Host
        $touched = $true
    }

    foreach ($rel in @($after.hashes.Keys)) {
        $was = $before.hashes[$rel]
        if ($was -eq $after.hashes[$rel]) { continue }
        Write-Host ("  REVIEWER TOUCHED {0} while auditing; restoring." -f $rel) -ForegroundColor Red
        $full = Join-Path $proj ($rel.Replace("/", "\"))
        if ($null -eq $was) {
            # It did not exist before the review, so removing it restores the
            # project exactly.
            Remove-Item -LiteralPath $full -Force -ErrorAction SilentlyContinue
        } elseif ($before.saved.ContainsKey($rel)) {
            # It was already modified before the review, so git holds no copy of
            # what it looked like. Ours does.
            Copy-Item -LiteralPath $before.saved[$rel] -Destination $full -Force
        } else {
            # Clean before the review, so the committed content IS the answer.
            # Restored file by file: a blanket `git checkout -- .` would also
            # discard the writer's own uncommitted work, which is not this
            # guard's to take.
            & cmd /c "git -C ""$proj"" checkout -- ""$rel"" 2>&1" | Out-Host
        }
        $touched = $true
    }

    # A file the reviewer DELETED is a change too, and the loop above only walks
    # what exists now.
    foreach ($rel in @($before.hashes.Keys | Where-Object { -not $after.hashes.ContainsKey($_) })) {
        Write-Host ("  REVIEWER DELETED {0} while auditing; restoring." -f $rel) -ForegroundColor Red
        $full = Join-Path $proj ($rel.Replace("/", "\"))
        if ($before.saved.ContainsKey($rel)) { Copy-Item -LiteralPath $before.saved[$rel] -Destination $full -Force }
        else { & cmd /c "git -C ""$proj"" checkout -- ""$rel"" 2>&1" | Out-Host }
        $touched = $true
    }

    if (-not $touched -and (Test-Path -LiteralPath $before.backup)) {
        Remove-Item -LiteralPath $before.backup -Recurse -Force -ErrorAction SilentlyContinue
    }
    return $touched
}


function Invoke-Aider([string[]]$argv, [string]$logPath, [string]$workDir = "") {
    # Everything the pipeline produces goes to the host and to the log, never to
    # this function's OUTPUT stream. A PowerShell function returns every object
    # it writes, so a bare Tee-Object here made the caller's $code an array of
    # aider's entire output plus the exit code: `$code -ne 0` was then true on a
    # successful run, and a completed plan was reported as a failure and never
    # archived. Measured 2026-09-02 on a run whose work had in fact landed.
    #
    # The audit pass runs somewhere else on purpose - see Invoke-PlanAudit.
    # Every other caller omits $workDir and gets the project, as before.
    if ($workDir -eq "") { $workDir = $proj }
    Push-Location $workDir
    $prev = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        & aider @argv 2>&1 | Tee-Object -FilePath $logPath | Out-Host
        return [int]$LASTEXITCODE
    } finally {
        $ErrorActionPreference = $prev
        Pop-Location
    }
}


$logDir = Join-Path $plansDir ".logs"
if (-not $DryRun) {
    New-Item -ItemType Directory -Force -Path $logDir | Out-Null
    New-Item -ItemType Directory -Force -Path $todoDir | Out-Null
}
$stamp  = Get-Date -Format "yyyyMMdd-HHmmss"
$failed = 0
# Counted separately from $failed, because the two now mean different things.
# $failed says the run needs a person; $blockedPlans says how many plans that
# person has to read. A run where every plan ran and two are blocked is not the
# same event as a run whose final audit pass produced nothing, and the run record
# has to be able to tell them apart.
$blockedPlans = 0

# --- One plan per process --------------------------------------------------
:plans foreach ($plan in $plans) {
    # Labelled, because every failure exit below sits inside the rounds
    # while-loop and a bare break or continue would act on THAT loop: a bare
    # break would start the next plan silently, a bare continue would re-enter
    # the same plan for ever.
    #
    # Every one of those exits is `continue plans`, never `break plans`, since
    # 2026-09-04. A blocked plan marks itself in the ledger and the run carries
    # on to the next one. The rule it replaces stopped the WHOLE night on the
    # first plan that could not be finished, and the measured cost of that was
    # not hypothetical: on 2026-09-03 the audit round limit fired on the last
    # plan at 03:25, which cost only the final pass, but the same line firing on
    # plan1 would have thrown away every plan after it - code that compiles,
    # whose tests pass, and whose only fault is a review finding nobody had time
    # to act on. A failing suite is now the student's to read in progress.md in
    # the morning, not a reason to have produced nothing by then.
    $round = 1
    while ($true) {
    $roundLabel = ""
    if ($round -gt 1) { $roundLabel = " (round $round)" }
    Write-Section "Plan: $($plan.Name)$roundLabel"
    Update-RunRecord @{ state = "writing"; plan = $plan.Name; round = $round
                        plan_index = ([array]::IndexOf($plans, $plan) + 1)
                        note = "the writer model is editing" }

    $message = "Execute $($plan.Name). Follow the working protocol you were given. " +
               "Every source file you create or change must have a matching test file, " +
               "written in the same step as the code and not deferred: a step is not done " +
               "until its test exists and passes. " +
               "Tick every completed step in the '## $($plan.Name)' section of progress.md " +
               "as you finish it, mark a blocked step [!] with one line saying what blocked " +
               "it, and write into progress.md anything the next plan needs to know. Do not " +
               "read or act on any other plan, and do not move or rename any file."
    if ($round -gt 1) {
        $message = "The audit reopened this plan. In the '## $($plan.Name)' section of " +
                   "progress.md, address every line still marked '- [ ]', including the ones " +
                   "beginning 'audit:'. Fix the code and its tests, then tick each line you " +
                   "resolved. Mark '- [!]' with one line of reason only if a fix is genuinely " +
                   "impossible. Do not read or act on any other plan, and do not move or " +
                   "rename any file."
    }

    $argv = @() + $baseArgs
    if ($testCmd -ne "") {
        # aider's own loop: it runs the tests after an edit and feeds a failure
        # back to the model, bounded at max_reflections = 3 in base_coder.py.
        # The command is fixed and comes from configuration, so nothing the
        # model writes ever reaches a command line.
        $argv += @("--auto-test", "--test-cmd", $testCmd)
    }
    # Files the plan names become editable; everything else stays read-only.
    $targets = Get-PlanTargets $plan.FullName
    if ($targets.Count -gt $maxFilesTouched) {
        Write-Refusal @("REFUSED: $($plan.Name) names $($targets.Count) files, over the limit of $maxFilesTouched.",
                        "  " + (($targets | ForEach-Object { Split-Path $_ -Leaf }) -join ", "),
                        "  A plan that needs more than $maxFilesTouched files is two plans.")
        Add-LedgerLine $plan.Name "- [!] this plan names $($targets.Count) files, over the limit of $maxFilesTouched - split it in two"
        $failed = 1; $blockedPlans++; continue plans
    }
    if ($targets.Count -gt 0) {
        Write-Host ("  editable: " + (($targets | ForEach-Object { Split-Path $_ -Leaf }) -join ", "))
    } else {
        Write-Host "  editable: progress.md only - this plan names no source file" -ForegroundColor Yellow
    }
    # Does the output this plan PERMITS fit in one reply? The whole plan is
    # answered in a single completion, so the reply reserve has to cover every
    # file it creates, not one of them. Measured 2026-09-05: it did not, and
    # the reply was cut mid-word at exactly the reserve, leaving created-but-
    # empty files and a suite that then reported 'Ran 0 tests ... OK'.
    #
    # A warning rather than a refusal: the estimate counts only files that do
    # not exist yet, which overcounts a small new file and undercounts a full
    # rewrite, and stopping a night on an estimate that rough would cost more
    # than it saves. It names the files so the reader can judge it.
    # CODE files only. Charging a two-line requirements.txt the full
    # code_file_output ceiling made this fire on five plans out of seven,
    # and a warning that fires on nearly everything is one a reader learns to
    # skip - which is the same as not having it. Counting only the files that
    # can actually be thousands of tokens leaves it firing on the plan that is
    # genuinely at risk.
    $newTargets = @($targets | Where-Object {
        (-not (Test-Path -LiteralPath $_)) -and
        ($CodeExtensions -contains ([System.IO.Path]::GetExtension($_).ToLower()))
    })
    if ($newTargets.Count -gt 0) {
        $worstOutput = $newTargets.Count * $codeFileOutputCeiling
        if ($worstOutput -gt $replyReserve) {
            Write-Host ('  WARNING: this plan creates {0} new file(s); at the {1}-token ceiling that is {2} tokens of output, and one reply holds {3}.' -f $newTargets.Count, $codeFileOutputCeiling, $worstOutput, $replyReserve) -ForegroundColor Yellow
            Write-Host ('    new: ' + (($newTargets | ForEach-Object { Split-Path $_ -Leaf }) -join ', '))
            Write-Host '    If the reply is cut, the files are created EMPTY and the suite reports 0 tests. Split the plan.'
        }
    }

    $argv += @("--read", $spec, "--read", $plan.FullName)
    # Round 1 is work being written; a later round is work RECEIVING a review,
    # which is a different skill and not a coincidence - the audit having put a
    # step back is exactly what "receiving code review" describes.
    $stageForRound = if ($round -le 1) { "write" } else { "reopen" }
    foreach ($sp in $skillFiles[$stageForRound]) { $argv += @("--read", $sp) }
    # Every --read pair goes in BEFORE the positional files, which is why
    # progress.md is appended here rather than on the line above.
    $argv += @($progress)
    $argv += $targets

    # --message-file for the same reason the audit uses it: PowerShell mangles a
    # multi-line or quote-bearing argument on its way to a native executable.
    # This message happens to carry neither today, which is why it has always
    # worked, but a later edit that adds either would fail silently and look
    # like a model defect. Measured 2026-09-03 on the audit message.
    $planMsgFile = Join-Path $logDir "$stamp-$($plan.BaseName)-r$round-prompt.txt"
    if (-not $DryRun) { Write-Utf8NoBom $planMsgFile $message }

    $argv += @(
               "--message-file", $planMsgFile, "--yes", "--no-check-update",
               # --yes approves shell commands the model suggests, and nobody is
               # at the machine overnight to read one first. Measured 2026-09-02:
               # a one-step fixture plan produced an unrequested `python -c ...`
               # that ran unattended. Cutting the suggestion is narrower than
               # dropping --yes, which would stall on every file aider adds.
               "--no-suggest-shell-commands")

    if ($DryRun) {
        Write-Host "  would run: aider $($argv -join ' ')"
        if ($testCmd -ne "") { Write-Host "  would then run the tests: $testCmd" }
        if ($auditPerPlan -and $auditModel -ne "" -and -not $NoAudit) {
            Write-Host "  would then audit with $auditModel, up to $auditRounds round(s)"
        }
        # break, NOT continue: this sits inside the per-plan rounds while-loop,
        # and a continue here re-enters that loop on the same plan for ever.
        # Measured 2026-09-02 - the dry run printed plan1 without end.
        break
    }

    Push-Location $proj
    try { $headBefore = (& git rev-parse HEAD 2>$null); if ($LASTEXITCODE -ne 0) { $headBefore = $null } }
    finally { Pop-Location }

    $code = Invoke-Aider $argv (Join-Path $logDir "$stamp-$($plan.BaseName).log")
    Write-Host "  exit=$code"

    # --- Tests: coverage first, then the suite -----------------------------
    # Both judged by the driver. aider's own loop may already have fixed a
    # failure, but its exit code says nothing about whether the suite passes
    # now, so the suite is run again here and THAT is what the ledger records.
    $changedSource = @()
    if ($testCmd -ne "") {
        $changed = @()
        if ($null -ne $headBefore) {
            Push-Location $proj
            try {
                $changed = @(& git diff --name-only "$headBefore..HEAD" 2>$null)
                if ($LASTEXITCODE -ne 0) { $changed = @() }
            } finally { Pop-Location }
        }

        $missing = @()
        if ($testsRequired) {
            foreach ($rel in $changed) {
                $ext = [System.IO.Path]::GetExtension($rel)
                if ($CodeExtensions -notcontains $ext) { continue }
                $stem = [System.IO.Path]::GetFileNameWithoutExtension($rel)
                if (Test-IsExempt $stem) { continue }
                if ($null -eq (Find-TestFile $rel)) { $missing += $rel }
            }
        }

        if ($missing.Count -gt 0) {
            Write-Host ("  BLOCKED: no test file for: {0} -> next plan" -f ($missing -join ", ")) -ForegroundColor Yellow
            Add-LedgerLine $plan.Name ("- [!] tests - no test file for " + ($missing -join ", "))
            $failed = 1; $blockedPlans++; continue plans
        }

        Write-Host "  running tests: $testCmd"
        Update-RunRecord @{ state = "testing"; note = "running the test command" }
        $testCode = Invoke-TestCommand (Join-Path $logDir "$stamp-$($plan.BaseName)-tests.log")
        if ($testCode -ne 0) {
            # A red suite is the student's to read in the morning, not a reason to
            # abandon every plan after this one. The ledger carries the exit code
            # and the log path, and the run carries on.
            Write-Host "  BLOCKED: tests fail (exit $testCode) after aider's fix attempts -> next plan" -ForegroundColor Yellow
            Add-LedgerLine $plan.Name "- [!] tests - suite still failing (exit $testCode) after the fix loop"
            Update-RunRecord @{ tests_exit = $testCode
                                note = "the suite still failed after aider's three fix attempts" }
            $failed = 1; $blockedPlans++; continue plans
        }
        # Exit 0 is not enough. `unittest discover` finding NO test exits 0 and
        # prints "Ran 0 tests ... OK", so a plan whose reply was truncated - the
        # file created and left empty, which is what a cut-off edit block leaves
        # behind - was recorded as `- [x] tests pass` on 2026-09-05. A suite that
        # ran nothing has proven nothing, and calling that a pass is the one
        # failure a student cannot see in the morning.
        #
        # Conservative on purpose: -TestCommand is the caller's, so only the two
        # signatures this kit can actually produce are treated as zero. Anything
        # unrecognised is left alone rather than guessed at.
        $testLog = Join-Path $logDir "$stamp-$($plan.BaseName)-tests.log"
        $ranNothing = $false
        if (Test-Path -LiteralPath $testLog) {
            $logText = Get-Content -LiteralPath $testLog -Raw -ErrorAction SilentlyContinue
            if ($logText -and ($logText -match 'Ran 0 tests' -or $logText -match 'no tests ran')) {
                $ranNothing = $true
            }
        }
        if ($ranNothing) {
            Write-Host "  BLOCKED: the suite ran ZERO tests, which is not a pass -> next plan" -ForegroundColor Yellow
            Write-Host "    Usually the reply was truncated: aider writes a file only after it has"
            Write-Host "    parsed a complete edit block, so the file exists and is empty."
            Add-LedgerLine $plan.Name "- [!] tests - the suite ran 0 tests, so nothing was proven"
            Update-RunRecord @{ tests_exit = 0
                                note = "the suite ran zero tests; the plan produced no test to run" }
            $failed = 1; $blockedPlans++; continue plans
        }
        Write-Host "  tests pass" -ForegroundColor Green
        Update-RunRecord @{ tests_exit = 0; note = "tests pass" }
        Add-LedgerLine $plan.Name "- [x] tests pass"
        $changedSource = @()
        foreach ($rel in $changed) {
            if ($CodeExtensions -contains [System.IO.Path]::GetExtension($rel)) {
                $changedSource += (Join-Path $proj ($rel.Replace('/', [System.IO.Path]::DirectorySeparatorChar)))
            }
        }
    }

    # The outcome is read out of progress.md and never out of the exit code:
    # aider exits 0 having done nothing as readily as having done the work (R9).
    $ledger  = Get-Content -LiteralPath $progress -Raw -Encoding UTF8
    $section = Get-PlanSection $ledger $plan.Name

    if ($null -eq $section) {
        # No section to write into. Add-LedgerLine creates one rather than
        # dropping the record, which is what makes "carry on" safe here: a plan
        # that ran with no ledger section would otherwise fail in silence, and
        # progress.md would look untroubled in the morning.
        Write-Host "  BLOCKED: progress.md has no '## $($plan.Name)' section -> creating one, next plan" -ForegroundColor Yellow
        Add-LedgerLine $plan.Name "- [!] this section was missing from progress.md, so the plan could not be tracked"
        $failed = 1; $blockedPlans++; continue plans
    }
    $sectionText = ($section -join "`n")
    if ($sectionText -match '(?m)^\s*-\s*\[!\]') {
        Write-Host "  BLOCKED: a step is marked blocked -> next plan" -ForegroundColor Yellow
        $failed = 1; $blockedPlans++; continue plans
    }
    if ($sectionText -match '(?m)^\s*-\s*\[\s\]') {
        Write-Host "  BLOCKED: steps remain unticked -> next plan" -ForegroundColor Yellow
        Add-LedgerLine $plan.Name "- [!] the writer left steps unticked in this section"
        $failed = 1; $blockedPlans++; continue plans
    }
    if ($code -ne 0) {
        Write-Host "  BLOCKED: aider exited $code -> next plan" -ForegroundColor Yellow
        Add-LedgerLine $plan.Name "- [!] aider exited $code on this plan"
        $failed = 1; $blockedPlans++; continue plans
    }

    # --- Gemma4 reviews what Qwen3.8 just wrote ----------------------------
    if ($auditPerPlan -and $auditModel -ne "" -and $changedSource.Count -gt 0 -and -not $NoAudit) {
        Write-Host "  audit by $auditModel"
        Update-RunRecord @{ state = "auditing"; note = "the reviewer is reading the code; it cannot edit it" }
        Wait-ModelsUnloaded "the audit model loads"

        # Measure the report BEFORE the pass, so "the audit wrote something" is a
        # fact rather than an inference.
        $auditSizeBefore = 0
        if (Test-Path -LiteralPath $auditMd) { $auditSizeBefore = (Get-Item -LiteralPath $auditMd).Length }

        $null = Invoke-PlanAudit $plan.Name $changedSource (Join-Path $logDir "$stamp-$($plan.BaseName)-audit-r$round.log")

        # An audit that produced NOTHING is a failed audit, not a clean one.
        # Measured 2026-09-03: the reviewer analysed the code correctly, found a
        # real missing failure-path test, then asked permission to fix it and
        # ended its turn. audit.md stayed at zero bytes, no ledger line was
        # reopened, and this block therefore printed "audit clean" for two plans
        # in a row. Judging the effect is the whole difference (R9).
        $auditSizeAfter = 0
        if (Test-Path -LiteralPath $auditMd) { $auditSizeAfter = (Get-Item -LiteralPath $auditMd).Length }

        if ($auditSizeAfter -le $auditSizeBefore) {
            Write-Host ("  STOP: the audit wrote nothing to audit.md ({0} bytes before, {1} after)." -f $auditSizeBefore, $auditSizeAfter) -ForegroundColor Yellow
            Write-Host "        Its log is the only record of what it thought: $stamp-$($plan.BaseName)-audit-r$round.log" -ForegroundColor Yellow
            # The reviewer may have written its findings into the LEDGER and
            # not into the report, which is what happened on 2026-09-06. That
            # is worth naming here: the lines are visible, their reasons are
            # not, and a reader who is told which lines can act on them.
            $orphans = @()
            if (Test-Path -LiteralPath $progress) {
                $sectionNow = Get-PlanSection (Get-Content -LiteralPath $progress -Raw -Encoding UTF8) $plan.Name
                if ($sectionNow) {
                    $orphans = @($sectionNow | Where-Object { $_ -match '^\s*-\s*\[ \]\s*audit:' })
                }
            }
            if ($orphans.Count -gt 0) {
                Write-Host ("        It DID write {0} audit line(s) into progress.md, with no finding behind them:" -f $orphans.Count) -ForegroundColor Yellow
                foreach ($o in $orphans) { Write-Host ("          " + $o.Trim()) -ForegroundColor Yellow }
            }
            Add-LedgerLine $plan.Name "- [!] audit - the reviewer wrote no report, so this plan is NOT audited"
            $failed = 1; $blockedPlans++; continue plans
        }
        Write-Host ("  audit report grew by {0} bytes" -f ($auditSizeAfter - $auditSizeBefore))

        # Before asking whether this plan is finished, make sure the answer is
        # not being decided by lines that landed in the wrong section. Measured
        # 2026-09-06: an audit put both of plan2's reopen lines under
        # '## plan1.md', so plan2 read as finished, plan3 started, and three
        # real defects were recorded where nothing would look again.
        $movedLines = Repair-AuditPlacement $progress $plan.Name
        if ($movedLines -gt 0) {
            Write-Host ("  moved {0} audit line(s) into this plan's section, where the reviewer was asked to put them" -f $movedLines) -ForegroundColor Yellow
        }

        $ledger  = Get-Content -LiteralPath $progress -Raw -Encoding UTF8
        $section = Get-PlanSection $ledger $plan.Name
        $openNow = (($section -join "`n") -match '(?m)^\s*-\s*\[\s\]')

        if ($openNow) {
            if ($round -ge $auditRounds) {
                Write-Host "  BLOCKED: audit still asks for fixes after $round round(s) -> next plan" -ForegroundColor Yellow
                Add-LedgerLine $plan.Name "- [!] audit - findings still open after $round round(s), stopped by the round limit"
                $failed = 1; $blockedPlans++; continue plans
            }
            Write-Host "  audit reopened the plan - round $($round + 1)" -ForegroundColor Yellow
            Wait-ModelsUnloaded "the writer returns"
            $round++
            continue
        }
        Write-Host "  audit clean" -ForegroundColor Green
    }

    Move-Item -LiteralPath $plan.FullName -Destination (Join-Path $todoDir $plan.Name) -Force
    Write-Host "  complete -> todo\$($plan.Name)" -ForegroundColor Green
    Update-RunRecord @{ state = "archiving"
                        plans_done = ([array]::IndexOf($plans, $plan) + 1)
                        note = "$($plan.Name) is done and archived to todo/" }
    Wait-ModelsUnloaded "the next plan starts"
    break
}
}

# --- The audit pass --------------------------------------------------------
# Runs even when plans are blocked, since 2026-09-04. audit.md is precisely what
# the student reads to pick the work back up, and withholding it from the run
# that needed it most was the wrong way round. The cycle archiving further down
# still refuses to move spec.md and progress.md while any step is open, so
# nothing is filed as finished that is not.
if (-not $NoAudit) {
    Write-Section "Audit pass"

    # The audit is a step of the ledger, not a phase that happens beside it, so
    # progress.md carries it like any other. The driver writes the section and
    # later ticks it, rather than the model: the tick means "audit.md exists on
    # disk", which is a fact the driver can check and the model can only assert.
    $ledger = Get-Content -LiteralPath $progress -Raw -Encoding UTF8
    # The section is called "final audit" and NOT "audit.md". Every other
    # section in this ledger is named after a plan file, so the reviewer read
    # "## audit.md" as one more of those and wrote its whole report under a
    # heading that names the file it was writing into - measured 2026-09-07,
    # where the final report appears in audit.md under "## audit.md", reading as
    # though the report had audited itself.
    if ($ledger -notmatch '(?m)^\s*##\s+final audit\s*$') {
        if (-not $DryRun) {
            Add-Content -LiteralPath $progress -Encoding UTF8 `
                -Value "`r`n## final audit`r`n- [ ] code audited and reviewed, problems listed"
        }
        if ($DryRun) { Write-Host "  would add the 'final audit' step to progress.md" }
        else          { Write-Host "  added the 'final audit' step to progress.md" }
    }

    if ($sourceFiles.Count -eq 0) {
        Write-Host "  nothing tracked to audit."
    } else {
        # Pack the source files into batches that FIT. Handing every file at
        # once is what breaks the window: forty files at the 16000-token ceiling
        # is 640000 tokens against a 262144 window, and aider would silently
        # send a prompt the daemon then truncates. Each batch is one aider pass
        # appending to the same audit.md.
        $auditBudget = $workingBudget - $auditMargin
        $specTokens  = Get-TokenCount $spec
        $progTokens  = Get-TokenCount $progress
        if ($specTokens -gt 0) { $auditBudget -= $specTokens }
        if ($progTokens -gt 0) { $auditBudget -= $progTokens }

        Write-Host ("  budget per batch: {0} tokens, at most {1} files" -f $auditBudget, $auditMaxFiles)

        $batches = @()
        $current = @()
        $currentTokens = 0
        foreach ($f in $sourceFiles) {
            $n = $sourceTokens[$f]
            if ($null -eq $n -or $n -lt 0) { $n = $codeCeiling }   # unmeasurable: assume the worst
            if ($n -gt $auditBudget) {
                # One file alone larger than a whole batch. It is reported and
                # skipped rather than sent to be truncated in silence.
                Write-Host ("  SKIPPED {0} - {1} tokens exceeds a whole batch" -f (Split-Path $f -Leaf), $n) -ForegroundColor Yellow
                continue
            }
            if ($current.Count -ge $auditMaxFiles -or ($currentTokens + $n) -gt $auditBudget) {
                $batches += , $current
                $current = @()
                $currentTokens = 0
            }
            $current += $f
            $currentTokens += $n
        }
        if ($current.Count -gt 0) { $batches += , $current }

        Write-Host ("  {0} file(s) in {1} batch(es)" -f $sourceFiles.Count, $batches.Count)

        $fatNote = ""
        if ($fat.Count -gt 0) {
            $fatNote = " These files are over the $codeCeiling-token ceiling and each needs a " +
                       "named split in the audit: " + ($fat -join ", ") + "."
        }

        $batchIndex = 0
        foreach ($batch in $batches) {
            $batchIndex++
            $names = ($batch | ForEach-Object { Split-Path $_ -Leaf }) -join ", "
            $of = " (batch $batchIndex of $($batches.Count))"
            if ($batches.Count -eq 1) { $of = "" }
            Write-Host ("  batch {0}: {1} file(s) - {2}" -f $batchIndex, $batch.Count, $names)

            $auditMessage = "Write audit.md$of. Every source file is read-only: do not edit any " +
                            "of them and propose no rewrite. Append to what audit.md already " +
                            "contains rather than replacing it, under the heading " +
                            "'## final audit', creating that heading if it is not there. " +
                            "List the problems you find, " +
                            "worst first, each with the file, the line, what is wrong and why " +
                            "it matters. Check at least hard-coded values that belong in " +
                            "configuration, silent fallbacks, missing error paths, a return " +
                            "code trusted where the effect should have been verified, and " +
                            "anything spec.md asked for that no plan delivered.$fatNote If you " +
                            "find nothing in these files, say so in one line. " +
                            # Measured 2026-09-06: the reviewer wrote its report in
                            # French - "Le plan a ete revise et aucun probleme n''a ete
                            # trouve." - while every other file in the kit is in
                            # English. Nothing had told it which language to use, so
                            # it chose, and a student reads a report in a language the
                            # rest of the pipeline does not use.
                            "Write the report in English. There is no one to " +
                            "answer you: this is an unattended run, so never end your " +
                            "turn with a question, a request for permission, or an " +
                            "offer to make the fixes. Write the report and stop."

            # The reviewer brief is appended to the INSTRUCTION rather than
            # passed with --read, so its position is decided here and not by
            # aider. Same rule as the per-plan audit: the guard that forbids
            # editing and asking comes first, the skill second. One mechanism,
            # one ordering rule, so the two audit paths cannot drift.
            foreach ($sp in $skillFiles["audit"]) {
                $auditMessage += "`n`n=== HOW TO REVIEW: " + (Split-Path $sp -Leaf) + " ===`n" +
                                 (Get-Content -LiteralPath $sp -Raw -Encoding UTF8)
            }

            $argv = @() + $baseArgs
            $argv += @("--read", $spec, "--read", $progress)
            foreach ($f in $batch) { $argv += @("--read", $f) }

            # --message-file, for the reason given on the per-plan audit: a
            # native executable never receives a quote-bearing argument intact
            # from PowerShell.
            $batchMsgFile = Join-Path $logDir "$stamp-audit-$batchIndex-prompt.txt"
            if (-not $DryRun) { Write-Utf8NoBom $batchMsgFile $auditMessage }

            # The same sandbox as the per-plan audit, for the same measured
            # reason - and this is the path that proved the point. The per-plan
            # audit was sandboxed first and this one was not, so a stub reviewer
            # driven through the whole driver still rewrote a project file: two
            # audit paths, one rule, and fixing one of them fixes nothing.
            #
            # The batch files stay --read at their ABSOLUTE paths, so they
            # resolve from the sandbox and nothing has to be copied. Only the
            # one file the reviewer may write moves.
            $auditSandbox = Join-Path $logDir "$stamp-audit-$batchIndex-sandbox"
            $sandBatchAudit = Join-Path $auditSandbox "audit.md"
            $argv += @($sandBatchAudit, "--message-file", $batchMsgFile, "--yes",
                       "--no-git", "--no-check-update", "--no-suggest-shell-commands")

            if ($DryRun) {
                Write-Host ("    would audit {0} read-only file(s) into audit.md" -f $batch.Count)
                continue
            }

            if (Test-Path -LiteralPath $auditSandbox) { Remove-Item -LiteralPath $auditSandbox -Recurse -Force }
            New-Item -ItemType Directory -Force -Path $auditSandbox | Out-Null
            Copy-Item -LiteralPath $auditMd -Destination $sandBatchAudit -Force

            $before = Get-ProjectFingerprint
            $code = Invoke-Aider $argv (Join-Path $logDir "$stamp-audit-$batchIndex.log") $auditSandbox
            $null = Restore-ProjectIfTouched $before

            # After the guard, never before: restoring a trespass must not also
            # discard the reviewer's own report.
            Copy-Item -LiteralPath $sandBatchAudit -Destination $auditMd -Force

            $strays = @(Get-ChildItem -LiteralPath $auditSandbox -Recurse -File |
                        Where-Object { $_.Name -ne "audit.md" })
            if ($strays.Count -gt 0) {
                Write-Host ("    the reviewer tried to edit {0} file(s) it may not touch; kept in {1}" -f $strays.Count, $auditSandbox) -ForegroundColor Yellow
            }
            Write-Host "    exit=$code"
        }

        if (-not $DryRun) {
            # Judged by the effect, never by the exit code: aider returns 0 on a
            # failed API call having written nothing (measured 2026-09-02).
            $auditWritten = $false
            if (Test-Path -LiteralPath $auditMd) {
                $auditWritten = ((Get-Item -LiteralPath $auditMd).Length -gt 0)
            }
            if (-not $auditWritten) {
                Write-Host "  STOP: no audit.md was written." -ForegroundColor Yellow
                $failed = 1
            } else {
                Write-Host "  audit.md written" -ForegroundColor Green
                # Tick the ledger's audit step now that the file is on disk.
                $ledger = Get-Content -LiteralPath $progress -Raw -Encoding UTF8
                $ticked = $ledger -replace '(?m)^(\s*)-\s*\[\s\](\s*code audited and reviewed.*)$', '$1- [x]$2'
                if ($ticked -ne $ledger) {
                    Write-Utf8NoBom $progress $ticked
                    Write-Host "  ticked the audit step in progress.md" -ForegroundColor Green
                }
            }
        }
    }
}

# --- Archive spec and progress when the whole cycle is done ----------------
if ($failed -eq 0 -and -not $DryRun -and -not $NoAudit) {
    $remaining = @(Get-ChildItem -LiteralPath $plansDir -Filter "plan*.md" -File |
                   Where-Object { $_.BaseName -match '^plan(\d+)$' })
    $ledger = Get-Content -LiteralPath $progress -Raw -Encoding UTF8
    $openSteps = ($ledger -match '(?m)^\s*-\s*\[[\s!]\]')

    if ($remaining.Count -eq 0 -and -not $openSteps) {
        Write-Section "Cycle complete"
        foreach ($f in @($spec, $progress)) {
            Move-Item -LiteralPath $f -Destination (Join-Path $todoDir (Split-Path $f -Leaf)) -Force
            Write-Host "  archived -> todo\$(Split-Path $f -Leaf)" -ForegroundColor Green
        }
        Write-Host "  audit.md stays in place: it is what a person acts on next."
    }
}

Write-Section "Done"

# The night installs NOTHING, by decision: it runs unattended with --yes, so an
# install step would mean pip fetching a package name a local model chose at
# 3 a.m. with nobody reading it. conventions.md tells the model to DECLARE what
# it imports instead. Declaring is only useful if somebody is told, so this is
# where the telling happens - a file nobody mentions is a file nobody reads.
$reqFile = Join-Path $proj "requirements.txt"
if (Test-Path -LiteralPath $reqFile) {
    $reqLines = @(Get-Content -LiteralPath $reqFile |
                  ForEach-Object { $_.Trim() } |
                  Where-Object { $_ -ne '' -and -not $_.StartsWith('#') })
    if ($reqLines.Count -gt 0) {
        Write-Host ("  requirements.txt declares {0} package(s), NONE installed:" -f $reqLines.Count) -ForegroundColor Yellow
        foreach ($r in $reqLines) { Write-Host "    $r" }
        Write-Host "  Read it, then install it yourself:" -ForegroundColor Yellow
        Write-Host "    .\.venv\Scripts\python.exe -m pip install -r requirements.txt"
    }
}
if ($blockedPlans -gt 0) {
    Write-Host ("  {0} plan(s) blocked. Every plan still ran; read the [!] lines in progress.md." -f $blockedPlans) -ForegroundColor Yellow
}
# Three states, not two. "done_with_blocked" is a run that did everything it was
# asked to do and produced work a person must now read - it is neither a clean
# run nor a run that stopped, and a dashboard showing it green would hide the
# very lines the student is meant to open.
Update-RunRecord @{ state = $(if ($failed -eq 0) { "done" }
                              elseif ($blockedPlans -gt 0) { "done_with_blocked" }
                              else { "failed" })
                    blocked_plans = $blockedPlans
                    note  = $(if ($failed -eq 0) { "the run finished cleanly" }
                              elseif ($blockedPlans -gt 0) { "every plan ran; $blockedPlans carry a [!] in progress.md - read them and audit.md" }
                              else { "the run stopped; read the transcript and audit.md" }) }
exit $failed
