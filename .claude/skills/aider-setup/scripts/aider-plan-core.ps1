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
    $code = "import sys,tiktoken;print(len(tiktoken.get_encoding('cl100k_base').encode(open(sys.argv[1],encoding='utf-8',errors='replace').read(),disallowed_special=())))"
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
# The paragraph of a plan that lists the files it only READS: "**Reads, do not modify:**" up to the next
# blank line. Its files are handed to the model read-only and are never targets. Measured 2026-11-10: they
# were submitted as editable, and three plans edited a file that was not theirs (a shared test fixture, the
# module of the plan before). A file the plan also lists under Files stays a target.
$ReadsBlockPattern = '(?s)\*\*Reads, do not modify:\*\*(.*?)(?:\r?\n[ \t]*\r?\n|\z)'

function Get-PlanText([string]$planPath) {
    $text = Get-Content -LiteralPath $planPath -Raw -Encoding UTF8

    # A leading front matter block (executor, tier, bounds: the plan header of rule R38)
    # describes the plan, it does not name files, so it is skipped. A block that is never
    # closed is NOT treated as swallowing the plan: only a closed block is dropped.
    $lines = $text -split "`n"
    if ($lines.Count -gt 1 -and $lines[0].Trim([char]0xFEFF, ' ', "`r") -eq '---') {
        for ($i = 1; $i -lt $lines.Count; $i++) {
            if ($lines[$i].Trim(' ', "`r") -eq '---') {
                $text = if ($i + 1 -lt $lines.Count) { $lines[($i + 1)..($lines.Count - 1)] -join "`n" } else { "" }
                break
            }
        }
    }
    return $text
}

function Get-PathsInText([string]$text) {
    # No regex. A first version built one by joining escaped extensions, and it
    # matched nothing while the identical pattern typed by hand matched two - an
    # invisible character difference nobody can see in a diff. Splitting on
    # separators and asking Path for the extension cannot fail that way.
    $separators = @(' ', "`t", "`r", "`n", ',', ';', ':', '(', ')', '[', ']',
                    '{', '}', '"', "'", '`', '<', '>', '|', '!', '?')
    $found = New-Object System.Collections.Generic.List[string]

    foreach ($token in $text.Split($separators, [StringSplitOptions]::RemoveEmptyEntries)) {
        # Trailing dots only: a leading dot is part of the name (.claude/x.py), and a path such as
        # ../../evil.py must reach the containment check below intact so that it is refused.
        $word = $token.Trim('*', '#').TrimEnd('.')
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

function Get-PlanTargets([string]$planPath) {
    # The files a plan NAMES, added to the chat as editable rather than left for
    # the model to request. Measured 2026-09-03: with only progress.md editable,
    # a plan run produced NOTHING at all - the model spent its entire reply
    # reasoning about whether it was allowed to touch calc.py, and concluded it
    # was not. The convention already requires every plan step to name its file,
    # so the harness reads them instead of hoping the model asks. The files of the
    # "Reads, do not modify" paragraph are not among them: see Get-PlanReads.
    $text = [regex]::Replace((Get-PlanText $planPath), $ReadsBlockPattern, "")
    $found = Get-PathsInText $text
    return , $found
}

function Get-PlanReads([string]$planPath, [string[]]$targets = @()) {
    # The files a plan only reads, existing ones only (nothing is created for a file that is merely read),
    # given to the model with --read. A file that is also a target stays a target.
    $found = New-Object System.Collections.Generic.List[string]
    foreach ($m in [regex]::Matches((Get-PlanText $planPath), $ReadsBlockPattern)) {
        foreach ($path in (Get-PathsInText $m.Groups[1].Value)) {
            if ((Test-Path -LiteralPath $path -PathType Leaf) -and ($targets -notcontains $path) -and -not $found.Contains($path)) {
                $found.Add($path)
            }
        }
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

# --- The watchdog (aider-watchdog.exe) ---------------------------------------
# A small Go program that reads the CPU of the model server and the GPU while the
# writer or the reviewer should be generating, and stops the process in progress
# when both have gone far under what this machine measured for that model. It
# only stops the process: the plan it was working on is left undone and the
# driver goes on to the next one without writing to progress.md (see
# Test-WatchdogStop). Measured 2026-11-09: a model-written test looped for 6 hours
# with the GPU idle and nothing noticed. Absent program or reference: say so and
# carry on as before, never silently (R8).
function Start-Watchdog([int]$driverPid, [string]$runRecord, [string]$logs) {
    $exe = $null
    foreach ($c in @((Join-Path $PSScriptRoot "aider-watchdog.exe"),
                     (Join-Path $PSScriptRoot "..\watchdog\aider-watchdog.exe"))) {
        if (Test-Path -LiteralPath $c) { $exe = (Resolve-Path -LiteralPath $c).Path; break }
    }
    $reference = $env:AIDER_MODEL_REFERENCE
    if ([string]::IsNullOrEmpty($reference)) { $reference = Join-Path $PSScriptRoot "..\..\..\local-model-config.json" }
    $settings = if ($null -ne $exe) { Join-Path (Split-Path $exe -Parent) "aider-watchdog.json" } else { "" }
    if ($null -eq $exe -or -not (Test-Path -LiteralPath $settings) -or -not (Test-Path -LiteralPath $reference)) {
        Write-Host "  WARNING: watchdog not started (needs aider-watchdog.exe, aider-watchdog.json and a reference file; set AIDER_MODEL_REFERENCE). The run goes on without it." -ForegroundColor Yellow
        return $null
    }
    # One string, quoted by hand: Windows PowerShell 5.1 does not quote the items
    # of an -ArgumentList array, and these paths hold spaces.
    $argLine = 'watch --driver-pid {0} --run-record "{1}" --logs-dir "{2}" --settings "{3}" --reference "{4}"' -f `
        $driverPid, $runRecord, $logs, $settings, (Resolve-Path -LiteralPath $reference).Path
    $p = Start-Process -FilePath $exe -ArgumentList $argLine -WindowStyle Hidden -PassThru
    Start-Sleep -Seconds 2
    if ($p.HasExited) {
        Write-Host ("  WARNING: the watchdog refused to start (exit {0}). The run goes on without it." -f $p.ExitCode) -ForegroundColor Yellow
        return $null
    }
    Write-Host "  watchdog started (pid $($p.Id))"
    return $p
}

function Stop-Watchdog($proc) {
    if ($null -ne $proc -and -not $proc.HasExited) { try { $proc.Kill() } catch { } }
}

# True when the watchdog stopped the process that was working on this plan. The
# signal is consumed, so it counts once. The caller then moves to the next plan
# and writes nothing to progress.md: the plan simply stays undone.
function Test-WatchdogStop([string]$logs, [string]$planName) {
    $signal = Join-Path $logs "watchdog-stop.json"
    if (-not (Test-Path -LiteralPath $signal)) { return $false }
    try { $named = (Get-Content -LiteralPath $signal -Raw -Encoding UTF8 | ConvertFrom-Json).plan } catch { return $false }
    if ($named -ne $planName) { return $false }
    Remove-Item -LiteralPath $signal -Force
    return $true
}

# Re-save a test log as UTF-8 WITH a byte order mark. The test command writes through cmd's redirection, in
# plain bytes with no mark, while until 2026-11-12 every other log of a run was UTF-16 written by Tee-Object, so
# an editor that had guessed UTF-16 for one showed the other as Chinese characters (reported 2026-11-11, the
# content was intact). Every log is now UTF-8 with a mark. A mark is the one signal every editor and Get-Content
# honour, and nothing parses a log as data, so unlike a JSON file it costs nothing here. A log that is already
# UTF-16 (one written by an older driver) is converted, never read as UTF-8.
function Convert-TestLogToUtf8Bom([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) { return }
    $bytes = [System.IO.File]::ReadAllBytes($Path)
    if ($bytes.Length -ge 2 -and $bytes[0] -eq 0xFF -and $bytes[1] -eq 0xFE) {
        $text = [System.Text.Encoding]::Unicode.GetString($bytes)
    } else {
        $text = [System.Text.Encoding]::UTF8.GetString($bytes)
    }
    if ($text.Length -gt 0 -and $text[0] -eq [char]0xFEFF) { $text = $text.Substring(1) }
    [System.IO.File]::WriteAllText($Path, $text, (New-Object System.Text.UTF8Encoding($true)))
}

# A log read as it was written: UTF-8 with a mark since 2026-11-12, or UTF-16 with a mark for a log an older driver wrote.
function Get-LogText([string]$Path) {
    $b = [System.IO.File]::ReadAllBytes($Path)
    if ($b.Length -ge 2 -and $b[0] -eq 0xFF -and $b[1] -eq 0xFE) { return [System.Text.Encoding]::Unicode.GetString($b) }
    $t = [System.Text.Encoding]::UTF8.GetString($b)
    if ($t.Length -gt 0 -and $t[0] -eq [char]0xFEFF) { $t = $t.Substring(1) }
    return $t
}

# The report of a run that blocked: for each plan carrying a [!] line, WHY, in the words of the evidence the
# run already holds. Until 2026-11-11 the end of a run said only "10 plan(s) blocked" and the student had to
# open each log to find out whether the model had hit its reply limit, filled its window or used its three fix
# attempts. Inputs: the text of progress.md, the log folder, how many lines of test output to keep. Output: the
# Markdown text (empty when nothing is blocked). It reads files and runs nothing.
function Get-BlockReport([string]$ledgerText, [string]$logDir, [int]$tailLines = 12) {
    $out = New-Object System.Collections.Generic.List[string]
    $found = 0
    foreach ($section in [regex]::Split($ledgerText, '(?m)^## ')) {
        $lines = @($section -split "\r?\n")
        $heading = ([string]$lines[0]).Trim()
        $blocked = @($lines | Where-Object { $_ -match '^\s*-\s*\[!\]' })
        if ($heading -eq "" -or $blocked.Count -eq 0) { continue }
        $found++
        $base = $heading -replace '\.md$', ''
        $out.Add("## $heading")
        $out.Add("")
        $out.Add("Recorded in progress.md:")
        foreach ($b in $blocked) { $out.Add($b.Trim()) }
        $out.Add("")
        $runLog  = @(Get-ChildItem -LiteralPath $logDir -Filter "*-$base.log" -File -ErrorAction SilentlyContinue | Sort-Object Name | Select-Object -Last 1)
        $testLog = @(Get-ChildItem -LiteralPath $logDir -Filter "*-$base-tests.log" -File -ErrorAction SilentlyContinue | Sort-Object Name | Select-Object -Last 1)
        if ($runLog.Count -gt 0) {
            $t = Get-LogText $runLog[0].FullName
            $hit = [regex]::Match($t, '(?s)has hit a token limit!.*?Input tokens: ([^\r\n]+)\r?\n\s*Output tokens: ([^\r\n]+)\r?\n\s*Total tokens: ([^\r\n]+)')
            if ($hit.Success) {
                $out.Add("The model hit a token limit: input $($hit.Groups[1].Value.Trim()), output $($hit.Groups[2].Value.Trim()), total $($hit.Groups[3].Value.Trim()).")
            }
            if ($t -match 'Only \d+ reflections') { $out.Add("aider used all its fix attempts and the tests were still failing.") }
            $reqs = @([regex]::Matches($t, 'Tokens: ([\d.,k]+) sent, ([\d.,k]+) received') | ForEach-Object { "$($_.Groups[1].Value) sent / $($_.Groups[2].Value) received" })
            if ($reqs.Count -gt 0) { $out.Add("Requests of the run, in order: " + ($reqs -join "; ") + ".") }
            $out.Add("Run log: $($runLog[0].Name)")
        }
        if ($testLog.Count -gt 0) {
            $tt = Get-LogText $testLog[0].FullName
            $names = @([regex]::Matches($tt, '(?m)^(?:FAIL|ERROR): (\S+)|^--- FAIL: (\S+)|^test (\S+) \.\.\. FAILED') |
                       ForEach-Object { ($_.Groups[1].Value + $_.Groups[2].Value + $_.Groups[3].Value) } | Select-Object -Unique)
            if ($names.Count -gt 0) { $out.Add("Failing tests: " + ($names -join ", ") + ".") }
            $tail = @(($tt -split "\r?\n") | Where-Object { $_.Trim() -ne "" } | Select-Object -Last $tailLines)
            $out.Add("End of the test output ($($testLog[0].Name)):")
            $out.Add('```')
            foreach ($l in $tail) { $out.Add($l) }
            $out.Add('```')
        }
        $out.Add("")
    }
    if ($found -eq 0) { return "" }
    return ("# What blocked`n`n" + ($out -join "`n") + "`n")
}

# What the reviewer is told about the plan its code answers to, and what the writer is told about the review that
# reopened the plan. Found 2026-11-11: the reviewer judged the code against the spec alone, so it could not say that
# a step of the plan was missing, and the writer received only the one-line `audit:` items of progress.md, never the
# report with its file, its line and its reason. The plan's front matter is not sent (Get-PlanText drops it).
function Get-AuditPlanBlock([string]$plansDir, [string]$planName) {
    $path = Join-Path $plansDir $planName
    if (-not (Test-Path -LiteralPath $path)) { return "" }
    $text = (Get-PlanText $path).Trim()
    if ($text -eq "") { return "" }
    return "=== THE PLAN THIS CODE IMPLEMENTS ===`n" + $text + "`n`n"
}

function Get-ReopenReport([string]$auditPath, [string]$planName) {
    if (-not (Test-Path -LiteralPath $auditPath)) { return "" }
    $lines = Get-PlanSection (Get-Content -LiteralPath $auditPath -Raw -Encoding UTF8) $planName
    if ($null -eq $lines) { return "" }
    $body = ($lines -join "`n").Trim()
    if ($body -eq "") { return "" }
    return "`n`nThe reviewer's report on this plan, from audit.md. Each finding names the file, the line and why it matters:`n" + $body
}

# --- Plan quality: how closely the code follows the PLAN, not whether its tests pass (2026-11-11) ---
# The owner asked for a measure of what was delivered against what was asked, because a plan whose code fails
# a few tests can still be 80 percent right and cheap to finish, while a green suite says nothing about the
# requirements nobody tested. The reviewer lists the plan's requirements and judges each one; THIS code, not
# the model, counts them, so the number is arithmetic on its judgements and never a figure it made up.

$QualityStatusWeights = @{ full = 1.0; partial = 0.5; missing = 0.0 }

# Share of the final score that comes from the plan's own tests (chosen by the owner 2026-11-12, not measured).
# The reviewer reads code and never runs it, so on 2026-11-12 it scored 100 percent a module whose central
# call raised a TypeError (25 of 26 tests passed): the tests are the evidence it cannot produce. The other
# 80 percent is the reviewer's judgement of the requirements.
$QualityTestWeight = 0.2

# The limit of one test file run by the quality stage, in seconds (the author's choice, unmeasured).
$QualityTestTimeoutSeconds = 300

# The interpreter the test command starts with, or $null when it does not start with one. The quality stage
# runs one test file at a time and needs a command that takes a file; only a Python interpreter is known to.
# Input: the whole test command. Output: the interpreter path as written, or $null.
function Get-TestInterpreter([string]$testCommand) {
    $c = $testCommand.Trim()
    if ($c -eq "") { return $null }
    if ($c.StartsWith('"')) {
        $end = $c.IndexOf('"', 1)
        if ($end -lt 0) { return $null }
        $first = $c.Substring(1, $end - 1)
    } else {
        $first = ($c -split '\s+', 2)[0]
    }
    if ((Split-Path $first -Leaf) -match '^python[\d.]*(\.exe)?$') { return $first }
    return $null
}

# Reads the end of a unittest run. Input: the output text. Output: total tests run and how many passed
# (failures and errors are subtracted). Output that holds no "Ran N tests" line means the file never ran
# (an import error, a syntax error), which counts as one test failed so the plan is not rewarded for it;
# "Ran 0 tests" means the file holds no test and adds nothing.
function Get-TestCounts([string]$output) {
    $ran = [regex]::Matches($output, 'Ran (\d+) tests?')
    if ($ran.Count -eq 0) { return @{ total = 1; passed = 0 } }
    $total = [int]$ran[$ran.Count - 1].Groups[1].Value
    $bad = 0
    $failed = [regex]::Match($output, 'FAILED \(([^)]*)\)')
    if ($failed.Success) {
        foreach ($kind in @("failures", "errors")) {
            $m = [regex]::Match($failed.Groups[1].Value, "$kind=(\d+)")
            if ($m.Success) { $bad += [int]$m.Groups[1].Value }
        }
    }
    return @{ total = $total; passed = [Math]::Max($total - $bad, 0) }
}

# The message that makes the reviewer list and judge the requirements of one plan. Inputs: the plan file, the
# project folder, the token budget for the code shown, and the reviewer brief text. Output: a hashtable with the
# message text, the files shown and the files left out for lack of room (named in the message, so the reviewer
# can say it could not judge them), or $null when the plan names no file that exists.
function Get-QualityPrompt([string]$planPath, [string]$projectRoot, [int]$maxTokens, [string]$briefText = "") {
    $planName = Split-Path $planPath -Leaf
    $targets = Get-PlanTargets $planPath
    $shown = New-Object System.Collections.Generic.List[string]
    $omitted = New-Object System.Collections.Generic.List[string]
    $code = ""
    $used = 0
    foreach ($f in $targets) {
        if (-not (Test-Path -LiteralPath $f -PathType Leaf)) { continue }
        if ((Get-Item -LiteralPath $f).Length -eq 0) { continue }
        $rel = $f
        if ($f.StartsWith($projectRoot, [StringComparison]::OrdinalIgnoreCase)) { $rel = $f.Substring($projectRoot.Length + 1) }
        $n = Get-TokenCount $f
        if ($n -lt 0) { $n = $maxTokens }
        if ($used + $n -gt $maxTokens) { $omitted.Add($rel); continue }
        $used += $n
        $shown.Add($rel)
        $code += "`n`n----- $rel -----`n" + (Get-Content -LiteralPath $f -Raw -Encoding UTF8)
    }
    if ($shown.Count -eq 0) { return $null }
    $note = ""
    if ($omitted.Count -gt 0) {
        $note = "`n`nNot shown, no room: " + ($omitted -join ", ") + ". Mark every requirement that depends only on those files [partial] and say it could not be judged.`n"
    }
    $text = "You are scoring how closely finished code follows its PLAN. You are NOT running tests, you are NOT editing code, and no source file is open for editing: the plan and the code are quoted below, as text. Do not count tests and do not say whether the suite passes: only compare what the plan asks for with what the code does.`n`n" +
            "First list the requirements the plan states: each file it asks for, each function or interface with its signature, each behaviour, each constraint, each test it names. Then write ONE line per requirement, in this exact form, most important first, at most 20 lines:`n" +
            "- [full] <the requirement> - <why, in a few words>   when the code does exactly what the plan says`n" +
            "- [partial] <the requirement> - <what differs or is incomplete>   when it is there but not as the plan says`n" +
            "- [missing] <the requirement> - <what is absent>   when the code does not do it`n`n" +
            "Write these lines in quality.md under the heading '## quality $planName' and write nothing else there: no preamble, no summary, no score. There is no one to answer you: this is an unattended run, so never end your turn with a question, a request for permission or an offer to make fixes. Write the report in English.`n`n" +
            $briefText +
            "=== THE PLAN ===`n" + (Get-PlanText $planPath).Trim() + "`n`n" +
            "=== THE CODE ===" + $code + $note
    return @{ text = $text; shown = $shown.ToArray(); omitted = $omitted.ToArray() }
}

# Reads the reviewer's lines back and does the arithmetic. Inputs: the text of quality.md, the plan name and
# optionally the plan's test counts (a hashtable with total and passed, $null when the tests could not be run).
# Output: counts and a percentage, or scored = $false with the reason when the reviewer wrote no usable line,
# which is reported as "not scored" and never as 0 percent. With test counts the percentage is the reviewer's
# share scaled to (1 - test weight) plus the test weight times the share of tests that pass; without them it is
# the reviewer's alone and testsMeasured is $false, so the report says so.
function Get-QualityScore([string]$qualityText, [string]$planName, $tests = $null) {
    $inside = $false
    $full = 0; $partial = 0; $missing = 0
    $lines = New-Object System.Collections.Generic.List[string]
    foreach ($line in ($qualityText -split "`r?`n")) {
        if ($line -match '^\s*##\s+(.*?)\s*$') {
            $inside = ($Matches[1] -ieq "quality $planName")
            continue
        }
        if (-not $inside) { continue }
        if ($line -match '^\s*[-*]\s*\[(full|partial|missing)\]\s*(.+?)\s*$') {
            $status = $Matches[1].ToLower()
            switch ($status) { "full" { $full++ } "partial" { $partial++ } "missing" { $missing++ } }
            $lines.Add("$status|" + $Matches[2])
        }
    }
    $total = $full + $partial + $missing
    if ($total -eq 0) {
        return @{ plan = $planName; scored = $false; reason = "the reviewer wrote no requirement line under '## quality $planName'"; total = 0; full = 0; partial = 0; missing = 0; percent = $null; reviewer = $null; testsMeasured = $false; testsPassed = 0; testsTotal = 0; lines = @() }
    }
    $points = $full * $QualityStatusWeights.full + $partial * $QualityStatusWeights.partial + $missing * $QualityStatusWeights.missing
    $reviewer = 100.0 * $points / $total
    $measured = ($null -ne $tests) -and ($tests.total -gt 0)
    if ($measured) {
        $percent = (1.0 - $QualityTestWeight) * $reviewer + $QualityTestWeight * 100.0 * $tests.passed / $tests.total
    } else {
        $percent = $reviewer
    }
    return @{ plan = $planName; scored = $true; reason = ""; total = $total; full = $full; partial = $partial; missing = $missing
              percent = [int][math]::Round($percent); reviewer = [int][math]::Round($reviewer)
              testsMeasured = $measured; testsPassed = $(if ($measured) { $tests.passed } else { 0 }); testsTotal = $(if ($measured) { $tests.total } else { 0 })
              lines = $lines.ToArray() }
}

# The Markdown a person reads: one table, then the requirements that are not fully met, per plan. Input: the
# list of score hashtables, in plan order. Output: text.
function Format-QualityReport($scores) {
    $out = New-Object System.Collections.Generic.List[string]
    $out.Add("# Plan quality")
    $out.Add("")
    $weightPercent = [int][math]::Round(100.0 * $QualityTestWeight)
    $out.Add("How closely the code follows each plan. Quality is $(100 - $weightPercent) percent the reviewer model's judgement of the plan's requirements, one by one (full counts 1, partial 0.5, missing 0, counted by the driver, who reads the code and does not run it), plus $weightPercent percent the share of the plan's own tests that pass. A plan whose tests could not be run is scored on the reviewer's judgement alone and the Tests column says so.")
    $out.Add("")
    $out.Add("| Plan | Quality | Reviewer | Tests | Full | Partial | Missing |")
    $out.Add("|---|---:|---:|---:|---:|---:|---:|")
    foreach ($s in $scores) {
        if ($s.scored) {
            $testCell = "not measured"
            if ($s.testsMeasured) { $testCell = "$($s.testsPassed)/$($s.testsTotal)" }
            $out.Add("| $($s.plan) | $($s.percent) % | $($s.reviewer) % | $testCell | $($s.full) | $($s.partial) | $($s.missing) |")
        }
        else { $out.Add("| $($s.plan) | not scored | - | - | - | - | - |") }
    }
    foreach ($s in $scores) {
        $out.Add("")
        $out.Add("## $($s.plan)")
        $out.Add("")
        if (-not $s.scored) { $out.Add("Not scored: $($s.reason).") ; continue }
        $open = @($s.lines | Where-Object { -not $_.StartsWith("full|") })
        if ($open.Count -eq 0) { $out.Add("Every requirement the reviewer listed is fully met.") }
        foreach ($l in $open) { $parts = $l.Split("|", 2); $out.Add("- **$($parts[0])** $($parts[1])") }
    }
    return (($out -join "`n") + "`n")
}
