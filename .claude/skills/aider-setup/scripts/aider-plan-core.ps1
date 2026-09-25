<#
.SYNOPSIS
  The driver's pure functions: budget arithmetic, the ledger, plan discovery,
  the run record. Nothing here starts a process.

.DESCRIPTION
  Dot-sourced by aider-plan.ps1, so every function keeps the caller's scope and
  reads the same script variables it always did.

  The split exists for two reasons, both measured 2026-09-03.

  SIZE. The driver reached 17028 tokens against the 16000-token ceiling it
  ENFORCES on a project's source files (and never checked against itself). Moving
  these 15 functions out returns it to about 13500.

  TESTABILITY. PowerShell that spawns a process cannot be tested offline, which
  is why verify-sync-writes.ps1 loads rt-sync.ps1 rather than the installer, and
  why tune-new-model.ps1 keeps its logic in tune_preflight.py. Everything here is
  reachable by a test without starting aider, git, cmd or a model.

  What stays in the entry point, deliberately: Invoke-Aider, Invoke-PlanAudit,
  Invoke-TestCommand, Wait-ModelsUnloaded and Resolve-AiderModel, plus the 861
  lines of main flow. That flow is the next thing to break up, and it is a larger
  job than this one - stated here so nobody reads this split as finishing it.
#>
function Write-Section($text) { Write-Host ""; Write-Host "== $text" -ForegroundColor Cyan }

function Write-Refusal($lines) { foreach ($l in $lines) { Write-Host $l -ForegroundColor Red } }

function Get-RunRecordDir {
    # Resolved from the environment with a documented default, never written as a
    # literal (R1). This is not decoration: $HOME is READ-ONLY in PowerShell, so
    # with the path hardcoded there is no way to point the record anywhere else,
    # and the only way to test it would be to write into the operator's real home.
    # Measured 2026-09-03, when the first attempt at a test died on
    # "Impossible de remplacer la variable HOME".
    if ($env:AIDER_RUN_RECORD_DIR) { return $env:AIDER_RUN_RECORD_DIR }
    return (Join-Path $HOME ".aider-plan\runs")
}

function Initialize-RunRecord([string]$project, [bool]$dryRun) {
    if ($dryRun) { return }
    $dir = Get-RunRecordDir
    if (-not (Test-Path -LiteralPath $dir)) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
    # The project path decides the file name, so one project has one record that
    # a later run overwrites, rather than a directory nobody prunes.
    $md5 = [System.Security.Cryptography.MD5]::Create()
    $hash = [BitConverter]::ToString(
        $md5.ComputeHash([Text.Encoding]::UTF8.GetBytes($project.ToLowerInvariant()))
    ).Replace("-", "").Substring(0, 8).ToLowerInvariant()
    $script:RunRecordPath = Join-Path $dir "$hash.json"
    $script:RunRecord = [ordered]@{
        schema       = "aider-plan/run-record/1"
        run_id       = "$(Get-Date -Format 'yyyyMMdd-HHmmss')-$hash"
        pid          = $PID
        project      = $project
        started      = (Get-Date -Format "s")
        updated      = (Get-Date -Format "s")
        state        = "starting"
        state_since  = (Get-Date -Format "s")
        branch       = ""
        model_writer = ""
        model_audit  = ""
        window       = 0
        working_set  = 0
        skills       = $false
        plan         = ""
        plan_index   = 0
        plan_count   = 0
        round        = 0
        plans_done   = 0
        steps_done   = 0
        steps_open   = 0
        steps_blocked = 0
        tests_exit   = $null
        audit_bytes  = 0
        note         = ""
    }
}

function Update-RunRecord([hashtable]$fields) {
    if ($null -eq $script:RunRecord -or $script:RunRecordPath -eq "") { return }
    try {
        if ($fields.ContainsKey("state") -and $fields["state"] -ne $script:RunRecord["state"]) {
            $script:RunRecord["state_since"] = (Get-Date -Format "s")
        }
        foreach ($k in $fields.Keys) { $script:RunRecord[$k] = $fields[$k] }
        $script:RunRecord["updated"] = (Get-Date -Format "s")

        # The ledger is the progression, so it is re-counted on every update
        # rather than tracked, which would drift from the file the model writes.
        if (Test-Path -LiteralPath $progress) {
            $ledger = Get-Content -LiteralPath $progress -Raw -Encoding UTF8
            $script:RunRecord["steps_done"]    = ([regex]::Matches($ledger, '(?m)^\s*-\s*\[x\]')).Count
            $script:RunRecord["steps_open"]    = ([regex]::Matches($ledger, '(?m)^\s*-\s*\[\s\]')).Count
            $script:RunRecord["steps_blocked"] = ([regex]::Matches($ledger, '(?m)^\s*-\s*\[!\]')).Count
        }
        $auditFile = Join-Path $plansDir "audit.md"
        if (Test-Path -LiteralPath $auditFile) {
            $script:RunRecord["audit_bytes"] = (Get-Item -LiteralPath $auditFile).Length
        }

        # Atomic: a reader polling this file must never catch a half-written one.
        $tmp = "$script:RunRecordPath.tmp"
        Write-Utf8NoBom $tmp ($script:RunRecord | ConvertTo-Json -Depth 4)
        Move-Item -LiteralPath $tmp -Destination $script:RunRecordPath -Force
    } catch {
        # A record that cannot be written must never take the run down with it.
        # It is a window onto the work, not the work.
    }
}

function Get-TokenCount([string]$file) {
    if (-not (Test-Path -LiteralPath $venvPython)) { return -1 }
    $code = "import sys,tiktoken;print(len(tiktoken.get_encoding('cl100k_base').encode(open(sys.argv[1],encoding='utf-8',errors='replace').read())))"
    $out = & $venvPython -c $code $file 2>$null
    if ($LASTEXITCODE -ne 0) { return -1 }
    return [int]$out
}

function Get-BudgetValue($obj, [string]$path) {
    # Walks a dotted path and REFUSES on a missing key, naming it and the file,
    # rather than substituting a plausible number nobody chose (R3).
    $node = $obj
    foreach ($seg in $path.Split('.')) {
        if ($null -eq $node -or -not ($node.PSObject.Properties.Name -contains $seg)) {
            Write-Refusal @("REFUSED: key '$path' is missing from $BudgetFile")
            exit 2
        }
        $node = $node.$seg
    }
    return $node
}

function Get-FileCeiling([string]$fileName) {
    # One ceiling per file, by name. plan1.md, plan2.md and so on all answer to
    # the single "plan.md" key, since only one is ever loaded at a time.
    $key = $fileName
    if ($fileName -match '^plan\d+\.md$') { $key = "plan.md" }
    if ($ceilings.PSObject.Properties.Name -contains $key) { return [int]$ceilings.$key }
    Write-Refusal @("REFUSED: no ceiling for '$fileName' in $BudgetFile",
                    "  Add a `"$key`" key under `"ceilings`".")
    exit 2
}

# The window is asked of aider, never declared: a number written in a file would
# silently disagree with whatever model is actually loaded.
function Get-ModelWindow([string]$tag) {
    # Both files are registered, and the metadata one is not optional.
    #
    # model-settings.yml carries extra_params.num_ctx, which is what aider SENDS,
    # but max_input_tokens - the number every budget below is computed against -
    # comes from litellm metadata. With no metadata registered, aider falls back
    # to asking Ollama, and Ollama answers with the ARCHITECTURE's native context
    # length regardless of the num_ctx baked into the tag. Measured 2026-09-05: a
    # tag tuned to 65536 reported 262144, so the driver sized audit batches
    # against a window four times larger than the one in force, and Ollama
    # truncates an over-long prompt to num_ctx//2+2 while reporting success.
    if (-not (Test-Path -LiteralPath $venvPython)) { return -1 }
    $py = "import sys,os;from aider.models import Model,register_models,register_litellm_models;" +
          "p=[q for q in sys.argv[2:] if os.path.exists(q)];" +
          "s=[q for q in p if q.endswith('.yml')];m=[q for q in p if q.endswith('.json')];" +
          "register_models(s) if s else None;register_litellm_models(m) if m else None;" +
          "i=Model(sys.argv[1]).info or {};print(i.get('max_input_tokens') or 0)"
    $settings = Join-Path $HOME ".config\aider\model-settings.yml"
    if ($Config -ne "") {
        $sibling = Join-Path (Split-Path -Parent (Resolve-Path -LiteralPath $Config).Path) "model-settings.yml"
        if (Test-Path -LiteralPath $sibling) { $settings = $sibling }
    }
    $metadata = Join-Path $HOME ".aider.model.metadata.json"
    $out = & $venvPython -c $py $tag $settings $metadata 2>$null
    if ($LASTEXITCODE -ne 0) { return -1 }
    return [int]$out
}

function Resolve-SkillStage($stage, $entry, $file) {
    $paths = @()
    if ($entry.bundle) {
        $dir = $entry.bundle
        if (-not (Test-Path -LiteralPath $dir)) {
            Write-Refusal @("REFUSED: skill bundle for stage '$stage' does not exist:", "  $dir")
            exit 2
        }
        $skillMd = Join-Path $dir "SKILL.md"
        if (-not (Test-Path -LiteralPath $skillMd)) {
            Write-Refusal @("REFUSED: skill bundle for stage '$stage' has no SKILL.md:", "  $dir")
            exit 2
        }
        $paths += (Resolve-Path -LiteralPath $skillMd).Path
        $body = Get-Content -LiteralPath $skillMd -Raw -Encoding UTF8
        foreach ($ref in ([regex]::Matches($body, '(?<![\w/\\])[\w\-]+\.md(?![\w])') |
                          ForEach-Object { $_.Value } | Sort-Object -Unique)) {
            if ($ref -ieq "SKILL.md") { continue }
            $refPath = Join-Path $dir $ref
            if (-not (Test-Path -LiteralPath $refPath)) {
                Write-Refusal @("REFUSED: stage '$stage' skill names a file it does not have:",
                                "  SKILL.md refers to '$ref', absent from $dir",
                                "  A skill quoting a document the model cannot read is worse",
                                "  than no skill: it knows there is a rule it cannot see.")
                exit 2
            }
            $paths += (Resolve-Path -LiteralPath $refPath).Path
        }
    }
    foreach ($f in @($entry.files)) {
        if ($null -eq $f -or $f -eq "") { continue }
        if (-not (Test-Path -LiteralPath $f)) {
            Write-Refusal @("REFUSED: skill file for stage '$stage' listed in $file does not exist:", "  $f")
            exit 2
        }
        $paths += (Resolve-Path -LiteralPath $f).Path
    }
    return $paths
}

# --- Helpers ---------------------------------------------------------------
function Get-PlanTargets([string]$planPath) {
    # The files a plan NAMES, added to the chat as editable rather than left for
    # the model to request. Measured 2026-09-03: with only progress.md editable,
    # a plan run produced NOTHING at all - the model spent its entire reply
    # reasoning about whether it was allowed to touch calc.py, and concluded it
    # was not. The convention already requires every plan step to name its file,
    # so the harness reads them instead of hoping the model asks.
    #
    # No regex. A first version built one by joining escaped extensions, and it
    # matched nothing while the identical pattern typed by hand matched two - an
    # invisible character difference nobody can see in a diff. Splitting on
    # separators and asking Path for the extension cannot fail that way.
    $text = Get-Content -LiteralPath $planPath -Raw -Encoding UTF8
    $separators = @(' ', "`t", "`r", "`n", ',', ';', ':', '(', ')', '[', ']',
                    '{', '}', '"', "'", '`', '<', '>', '|', '!', '?')
    $found = New-Object System.Collections.Generic.List[string]

    foreach ($token in $text.Split($separators, [StringSplitOptions]::RemoveEmptyEntries)) {
        $word = $token.Trim('.', '*', '#')
        if ($word -eq "") { continue }
        $ext = [System.IO.Path]::GetExtension($word)
        # Code OR data: a plan legitimately creates a config file, and a file
        # the plan names but the harness never adds is a step the model cannot
        # carry out.
        $planExts = @($CodeExtensions) + @($DataExtensions)
        if ($ext -eq "" -or ($planExts -notcontains $ext.ToLower())) { continue }

        # .Replace, not -replace: the latter is a REGEX operation whose
        # replacement string swallowed the backslash entirely, turning
        # tests/test_calc.py into teststest_calc.py and, worse, making
        # ../../evil.py look contained rather than refused.
        $rel = $word.Replace('/', [System.IO.Path]::DirectorySeparatorChar)
        try { $resolved = [System.IO.Path]::GetFullPath((Join-Path $proj $rel)) }
        catch { continue }

        # A file that does not exist yet is still a target: aider creates it.
        # What is refused is a path escaping the project (R24).
        if (-not $resolved.StartsWith($proj, [StringComparison]::OrdinalIgnoreCase)) {
            Write-Host "  ignored (outside the project): $word" -ForegroundColor Yellow
            continue
        }
        if (-not $found.Contains($resolved)) { $found.Add($resolved) }
    }
    return , $found.ToArray()
}

function Get-PlanSection([string]$ledgerText, [string]$planName) {
    # The ledger carries one "## <filename>" section per file. Returns the
    # section's lines, or $null when the section is absent - which is a finding
    # in itself, never a pass.
    $lines = $ledgerText -split "`r?`n"
    $inside = $false
    $body = @()
    foreach ($line in $lines) {
        if ($line -match '^\s*##\s+(\S+)\s*$') {
            if ($inside) { break }
            if ($Matches[1] -eq $planName) { $inside = $true; continue }
        }
        if ($inside) { $body += $line }
    }
    if (-not $inside) { return $null }
    return , $body
}

function Repair-AuditPlacement([string]$progressPath, [string]$planName) {
    # Reopen lines the audit wrote under the WRONG heading are moved under the
    # plan just audited. Measured 2026-09-06: an audit of plan2 put both of its
    # reopen lines under '## plan1.md', so plan2 read as finished, plan3 started,
    # and three real defects in planner.py were recorded where nothing would ever
    # look. The prompt already asked for the right heading; this checks the
    # effect rather than repeating the instruction.
    #
    # Returns the number of lines moved, so the caller can say so out loud.
    if (-not (Test-Path -LiteralPath $progressPath)) { return 0 }
    $lines = @(Get-Content -LiteralPath $progressPath -Encoding UTF8)
    $heading = '## ' + $planName

    # Which section each line sits in, so a misplaced one can be recognised.
    $current = ''
    $moved = @()
    $kept = @()
    foreach ($line in $lines) {
        if ($line -match '^\s*##\s+(\S+)\s*$') { $current = '## ' + $Matches[1] }
        if ($line -match '^\s*-\s*\[ \]\s*audit:' -and $current -ne $heading) {
            $moved += $line.Trim()
            continue
        }
        $kept += $line
    }
    if ($moved.Count -eq 0) { return 0 }

    # Re-insert at the END of the audited plan's section, which is where the
    # instruction asked for them.
    $out = @()
    $placed = $false
    for ($i = 0; $i -lt $kept.Count; $i++) {
        $out += $kept[$i]
        if ($kept[$i].Trim() -ne $heading) { continue }
        # Walk to the end of this section, then drop the lines in.
        $j = $i + 1
        while ($j -lt $kept.Count -and $kept[$j] -notmatch '^\s*##\s+\S+\s*$') {
            $out += $kept[$j]; $j++
        }
        $out += $moved
        $i = $j - 1
        $placed = $true
    }
    # No such heading: leave the file exactly as it was rather than inventing
    # a section, and report nothing moved so the caller does not claim a repair.
    if (-not $placed) { return 0 }
    Write-Utf8NoBom $progressPath (($out -join [Environment]::NewLine) + [Environment]::NewLine)
    return $moved.Count
}

function Test-IsExempt([string]$stem) {
    foreach ($pat in $testExempt) { if ($stem -like $pat) { return $true } }
    return $false
}

function Find-TestFile([string]$relPath) {
    # Returns the first existing test file for a source file, or $null.
    $stem = [System.IO.Path]::GetFileNameWithoutExtension($relPath)
    $ext  = [System.IO.Path]::GetExtension($relPath)
    $dir  = Split-Path $relPath -Parent
    foreach ($pat in $testPatterns) {
        $candidate = $pat.Replace("{stem}", $stem).Replace("{ext}", $ext)
        foreach ($base in @($proj, (Join-Path $proj $dir))) {
            $full = Join-Path $base $candidate
            if (Test-Path -LiteralPath $full) { return $full }
        }
    }
    return $null
}

function Write-Utf8NoBom([string]$Path, [string]$Text) {
    # Set-Content -Encoding UTF8 writes a BYTE ORDER MARK on PowerShell 5.1.
    # That is the defect the kit's install gate exists for - it is what made
    # aider answer 'did not find expected <document start>' on a config that
    # looked perfect - and the driver was committing it too: measured
    # 2026-09-05, every ~/.aider-plan/runs/*.json and every progress.md the
    # ledger had touched began with EF BB BF. The rt-observe adapter only
    # survives it by reading utf-8-sig, which is a workaround written around
    # the defect rather than a fix, and any other reader using plain utf-8
    # gets a JSONDecodeError on character 0.
    #
    # No trailing newline is added: every caller passes the exact bytes it
    # wants, as Set-Content -NoNewline did.
    [System.IO.File]::WriteAllText($Path, $Text, (New-Object System.Text.UTF8Encoding($false)))
}

function Add-LedgerLine([string]$sectionName, [string]$line) {
    # Inserts at the end of the "## <sectionName>" section, never at the end of
    # the file: a line appended to the file lands in whichever section happens
    # to be last, and the per-plan completeness check then reads the wrong one.
    $text  = Get-Content -LiteralPath $progress -Raw -Encoding UTF8
    $lines = $text -split "`r?`n"
    $start = -1
    $end   = $lines.Count
    for ($i = 0; $i -lt $lines.Count; $i++) {
        if ($lines[$i] -match '^\s*##\s+(\S+)\s*$') {
            if ($Matches[1] -eq $sectionName) { $start = $i; continue }
            if ($start -ge 0) { $end = $i; break }
        }
    }
    if ($start -lt 0) {
        # No such section: append one rather than dropping the record.
        $out = $text.TrimEnd() + "`r`n`r`n## $sectionName`r`n$line`r`n"
    } else {
        # Already there: say nothing and change nothing. Measured 2026-09-06 on
        # the night run, where progress.md ended up carrying "- [x] tests pass"
        # twice, one of them in the PREVIOUS plan's section. Whether the second
        # came from this function or from the writer model editing the ledger
        # itself, a ledger line means "this happened" and repeating it says
        # nothing new, while a duplicate is read by the completeness check as an
        # extra step.
        for ($j = $start + 1; $j -lt $end; $j++) {
            if ($lines[$j].Trim() -eq $line.Trim()) { return }
        }
        while ($end -gt $start + 1 -and $lines[$end - 1].Trim() -eq "") { $end-- }
        $head = $lines[0..($end - 1)]
        $tail = @()
        if ($end -lt $lines.Count) { $tail = $lines[$end..($lines.Count - 1)] }
        $out = (($head + @($line) + $tail) -join "`r`n")
    }
    Write-Utf8NoBom $progress $out
}
