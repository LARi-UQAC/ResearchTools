<#
.SYNOPSIS
  A/B harness: run the same fixture with and without skills, on criteria fixed in advance.

.DESCRIPTION
  Comparing two nights of model output is easy to do badly. Two runs of the same
  model on the same input differ anyway, so a difference between run A and run B
  cannot be attributed to the skills unless the question was decided beforehand.

  This script therefore does three things and refuses to do a fourth:

    fixture   build a byte-identical starting point, from a fixed seed
    snapshot  record ONE finished run against the criteria below
    compare   put two snapshots side by side

  It does NOT score, rank, or declare a winner. The criteria are counts, and a
  count is evidence; the judgement stays with the person reading it.

.PARAMETER Mode
  fixture | snapshot | compare

.EXAMPLE
  aider-ab.ps1 fixture  -Out C:\temp\ab-noskills
  aider-ab.ps1 snapshot -Project C:\temp\ab-noskills -Out C:\temp\a.json -Label "no skills"
  aider-ab.ps1 compare  -A C:\temp\a.json -B C:\temp\b.json
#>
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [ValidateSet("fixture", "snapshot", "compare")]
    [string]$Mode,

    [string]$Out = "",
    [string]$Project = "",
    [string]$Label = "",
    [string]$A = "",
    [string]$B = ""
)

$ErrorActionPreference = "Stop"

# ---------------------------------------------------------------------------
# THE CRITERIA, FIXED BEFORE ANY COMPARISON RUN.
#
# Written 2026-09-03, after the no-skills run produced its audit and BEFORE the
# skills run existed. Each one is a count or a yes/no that can be read off the
# working tree, so no judgement enters the measurement. Two of them are
# pre-registered PREDICTIONS rather than neutral counts, and they are the reason
# this comparison is worth three hours:
#
#   mocks_config     The no-skills audit complained that the tests read the real
#                    config.json and are therefore brittle. writing-good-tests.md
#                    says the opposite in Principle 2 - "mock the slow or
#                    external operation and keep what the test depends on real" -
#                    and a local config file is neither slow nor external. So the
#                    skill is predicted to make the writer KEEP it real, which is
#                    what the auditor objects to.
#
#   audit_reopened   If the two skills disagree, the audit reopens the plan and
#                    the writer does not concede. Rounds are bounded at 2, so the
#                    run terminates either way; what changes is whether the
#                    finding survives.
#
# A criterion added after seeing a result is not a criterion, it is a story.
# ---------------------------------------------------------------------------

function Write-Utf8NoBom([string]$Path, [string]$Text) {
    # Set-Content -Encoding UTF8 writes a BYTE ORDER MARK on PowerShell 5.1,
    # and a BOM in front of a JSON object makes json.load refuse the file at
    # character 0. Not hypothetical here: ab-runs/A-no-skills.json, this
    # script's own output, was found on 2026-09-05 needing encoding=utf-8-sig
    # to be read at all, and it was archived rather than the writer being
    # fixed. This is the writer.
    [System.IO.File]::WriteAllText($Path, $Text, (New-Object System.Text.UTF8Encoding($false)))
}

function New-Fixture([string]$root) {
    $plans = Join-Path $root "docs\superpowers\plans"
    New-Item -ItemType Directory -Force -Path $plans, (Join-Path $root "tests") | Out-Null
    Push-Location $root
    try {
        # Every git call goes through cmd with its stderr swallowed there.
        # PowerShell 5.1 wraps a native command's stderr in an ErrorRecord, and
        # $ErrorActionPreference = "Stop" then kills the script. Measured
        # 2026-09-04: `git add -A` printed "warning: LF will be replaced by CRLF"
        # and the fixture builder died on a WARNING, which is the same defect the
        # manual already records for the test command and for install-hooks.ps1.
        & cmd /c "git init -q -b night . 2>NUL"
        "def add(a, b):`n    return a + b" | Set-Content calc.py -Encoding utf8 -NoNewline
        "import unittest`nfrom calc import add`n`n`nclass T(unittest.TestCase):`n    def test_add(self):`n        self.assertEqual(add(1,1),2)`n" |
            Set-Content "tests\test_calc.py" -Encoding utf8 -NoNewline
        & cmd /c "git add -A 2>NUL"
        & cmd /c "git commit -qm seed 2>NUL"
        "# Spec`n`nCalculator in calc.py, tests in tests/. Thresholds come from config.json, never written in the code." |
            Set-Content "$plans\spec.md" -Encoding utf8
        "# Progress`n`n## plan1.md`n- [ ] add is_large to calc.py, with its test`n`n## plan2.md`n- [ ] add multiply to calc.py, with its test" |
            Set-Content "$plans\progress.md" -Encoding utf8
        "# Plan 1`n`n1. Add is_large(n) to calc.py using the large-value threshold of 100.`n2. Add its test to tests/test_calc.py." |
            Set-Content "$plans\plan1.md" -Encoding utf8
        "# Plan 2`n`n1. Add multiply(a, b) to calc.py returning a * b.`n2. Add its test to tests/test_calc.py, including a zero case." |
            Set-Content "$plans\plan2.md" -Encoding utf8
        # The seed commit's tree hash is the proof that two fixtures are the same
        # starting point. Comparing anything else would compare two experiments.
        $tree = (& git rev-parse "HEAD^{tree}").Trim()
        Write-Host "fixture : $root"
        Write-Host "seed tree: $tree"
    } finally { Pop-Location }
}

function Hide-Home([string]$text) {
    # A snapshot exists to be compared, quoted and pasted into a report, so the
    # account name must not ride along in it. One implementation, used on every
    # path the snapshot carries: a second copy is how one caller gets forgotten.
    if ($null -eq $text -or $text -eq "") { return $text }
    return $text.Replace($HOME, "~").Replace(($HOME -replace '\\', '/'), "~")
}

function Get-Snapshot([string]$root, [string]$label) {
    $plans   = Join-Path $root "docs\superpowers\plans"
    $todo    = Join-Path $plans "todo"
    $auditMd = Join-Path $plans "audit.md"
    $testFile = Join-Path $root "tests\test_calc.py"
    $calcFile = Join-Path $root "calc.py"

    # [string] is load-bearing, not decoration. PowerShell 5.1 decorates every
    # string Get-Content returns with PSPath, PSParentPath and friends, and
    # ConvertTo-Json then serialises the lot as an object whose text sits under a
    # 'value' key. Measured 2026-09-03: the audit text came back as
    # @{value=...; PSPath=C:\Users\<account>\...}, which is unreadable AND puts
    # the full home path into a file made to be compared and shared.
    $testBody  = if (Test-Path $testFile) { [string](Get-Content $testFile -Raw -Encoding UTF8) } else { "" }
    $calcBody  = if (Test-Path $calcFile) { [string](Get-Content $calcFile -Raw -Encoding UTF8) } else { "" }
    $auditBody = if (Test-Path $auditMd)  { [string](Get-Content $auditMd  -Raw -Encoding UTF8) } else { "" }

    Push-Location $root
    try {
        $commits = @(& git log --format="%h %an %s")
        # symbolic-ref first, for the unborn-HEAD reason given in
        # aider-night.ps1: a snapshot may be taken of a fixture that has not
        # committed yet, and rev-parse fatals there. A snapshot never refuses -
        # an unreadable branch is recorded as such rather than stopping a
        # comparison that has already cost hours of GPU time.
        $branch  = (& cmd /c "git symbolic-ref --short HEAD 2>NUL")
        if (-not $branch) { $branch = (& cmd /c "git rev-parse --abbrev-ref HEAD 2>NUL") }
        $branch  = if ($branch) { $branch.Trim() } else { "(unreadable)" }
    } finally { Pop-Location }

    # A finding is a numbered line in audit.md. Counting them is mechanical;
    # deciding whether each names something real is NOT, and is left to the
    # reader, which is why the findings themselves are carried in the snapshot.
    $findings = @([regex]::Matches($auditBody, '(?m)^\s*\d+\.\s') | ForEach-Object { $_.Value }).Count

    $snapshot = [ordered]@{
        label            = $label
        taken            = (Get-Date -Format "yyyy-MM-ddTHH:mm:ss")
        project          = (Hide-Home $root)
        branch           = $branch

        # --- did the run finish -------------------------------------------
        plans_archived   = @(if (Test-Path $todo) { Get-ChildItem $todo -Filter "plan*.md" -File } else { @() }).Count
        spec_archived    = (Test-Path (Join-Path $todo "spec.md"))
        audit_bytes      = $auditBody.Length
        commits          = $commits.Count
        aider_commits    = @($commits | Where-Object { $_ -match '\(aider\)' }).Count

        # --- what the writer produced --------------------------------------
        tests_written    = @([regex]::Matches($testBody, '(?m)^\s*def test_')).Count
        failure_paths    = @([regex]::Matches($testBody, 'assertRaises|pytest\.raises')).Count
        uses_config_file = (Test-Path (Join-Path $root "config.json"))
        literal_100      = ($calcBody -match '(?<![\w.])100(?![\w.])')
        functions        = @([regex]::Matches($calcBody, '(?m)^def \w+')).Count

        # --- the two pre-registered predictions ----------------------------
        mocks_config     = ($testBody -match 'unittest\.mock|@patch|with patch\(')
        audit_reopened   = ($auditBody -match 'config\.json|brittle|mock')

        # --- carried so a person can judge, not so a script can score ------
        audit_findings   = $findings
        audit_text       = (Hide-Home $auditBody)

        # --- the sources themselves, so a criterion invented LATER can still
        # be computed on a run that is long finished -------------------------
        # Added 2026-09-04. Until then this function read both files and kept
        # only derived counters, so a snapshot could answer questions asked
        # before the run and no other. The measured consequence: the sharpest
        # reading the A/B produced - one writer extracted a helper and raised a
        # named error, the other documented that error and raised nothing - could
        # not be recomputed from the snapshots at all, and depended on two
        # fixtures sitting in %TEMP%, which Disk Cleanup empties.
        #
        # A criterion added after seeing a result is still not a criterion. This
        # does not change that. It changes something else: whether the EVIDENCE
        # survives long enough for the next run to be measured against it.
        calc_body        = (Hide-Home $calcBody)
        test_body        = (Hide-Home $testBody)
    }

    # --- error handling, in three directions that only work together --------
    # Added 2026-09-04, and each returns a LIST of names rather than a count: a
    # count is believed, a list is checked. Subtracting two totals was the first
    # attempt and it is arithmetic, not matching - four documented and four
    # asserted can still be four mismatches, and the counter would report zero
    # while the gap persisted.
    #
    # Every one of the three is vacuously perfect on some input, which is why
    # each ships with its mirror: "documented but never tested" is empty for code
    # carrying no docstrings, and "asserted but only accidental" is empty for code
    # that asserts nothing. What makes a measurement honest is that it can fail in
    # both directions.
    $documented = @()
    foreach ($m in [regex]::Matches($calcBody, '(?s)Raises:\s*\n(.*?)(?:\n\s*-{5,}|\n\s*""")')) {
        $documented += @([regex]::Matches($m.Groups[1].Value, '(?m)^\s*([A-Z]\w*(?:Error|Exception))\s*:') |
                         ForEach-Object { $_.Groups[1].Value })
    }
    $asserted = @([regex]::Matches($testBody, 'assertRaises\(\s*([A-Z]\w*(?:Error|Exception))\s*\)') |
                  ForEach-Object { $_.Groups[1].Value })
    # A raise the module writes ITSELF. The difference this catches is the whole
    # point: assertRaises(TypeError) scores the same whether the module decided to
    # raise it or whether `str + int` refused on its own, and those are opposite
    # amounts of design.
    $raised = @([regex]::Matches($calcBody, '(?m)^\s*raise\s+([A-Z]\w*(?:Error|Exception))\b') |
                ForEach-Object { $_.Groups[1].Value })

    # Binary mode needs no encoding, so counting it would be a false positive.
    $openNoEncoding = @()
    foreach ($m in [regex]::Matches($calcBody, 'open\(([^)]*)\)')) {
        # NOT $args: that is a PowerShell automatic variable, and assigning to it
        # inside a function is a side effect nobody reading this would expect.
        $openArgs = $m.Groups[1].Value
        if ($openArgs -match 'encoding') { continue }
        if ($openArgs -match '["''][rwax]*b[rwax]*["'']') { continue }
        $openNoEncoding += ("open(" + $openArgs.Trim() + ")")
    }

    $snapshot | Add-Member -NotePropertyName documented_exceptions -NotePropertyValue $documented
    $snapshot | Add-Member -NotePropertyName asserted_exceptions   -NotePropertyValue $asserted
    $snapshot | Add-Member -NotePropertyName raised_exceptions     -NotePropertyValue $raised
    $snapshot | Add-Member -NotePropertyName documented_untested   -NotePropertyValue @($documented | Where-Object { $asserted -notcontains $_ })
    $snapshot | Add-Member -NotePropertyName asserted_undocumented -NotePropertyValue @($asserted   | Where-Object { $documented -notcontains $_ })
    $snapshot | Add-Member -NotePropertyName asserted_deliberate   -NotePropertyValue @($asserted   | Where-Object { $raised     -contains $_ })
    $snapshot | Add-Member -NotePropertyName asserted_accidental   -NotePropertyValue @($asserted   | Where-Object { $raised     -notcontains $_ })
    $snapshot | Add-Member -NotePropertyName raised_unasserted     -NotePropertyValue @($raised     | Where-Object { $asserted   -notcontains $_ })
    $snapshot | Add-Member -NotePropertyName open_without_encoding -NotePropertyValue $openNoEncoding
    # The single most robust number of the set. A writer who stops writing `raise`
    # has stopped deciding how the code fails, whatever else it produces, and that
    # shows up as one integer before anyone reads a line.
    $snapshot | Add-Member -NotePropertyName deliberate_raises     -NotePropertyValue $raised.Count
    return $snapshot
}

switch ($Mode) {

    "fixture" {
        if ($Out -eq "") { $Out = Join-Path $env:TEMP ("ab-" + (Get-Random)) }
        if (Test-Path $Out) {
            Write-Host "REFUSED: $Out already exists. A fixture must start empty." -ForegroundColor Red
            exit 2
        }
        New-Item -ItemType Directory -Force -Path $Out | Out-Null
        New-Fixture (Resolve-Path -LiteralPath $Out).Path
    }

    "snapshot" {
        if ($Project -eq "" -or -not (Test-Path $Project)) {
            Write-Host "REFUSED: -Project must name an existing run directory." -ForegroundColor Red
            exit 2
        }
        $snap = Get-Snapshot (Resolve-Path -LiteralPath $Project).Path $Label
        $json = $snap | ConvertTo-Json -Depth 6
        if ($Out -ne "") { Write-Utf8NoBom $Out $json; Write-Host "snapshot -> $Out" }
        else { $json }
    }

    "compare" {
        foreach ($f in @($A, $B)) {
            if ($f -eq "" -or -not (Test-Path $f)) {
                Write-Host "REFUSED: -A and -B must both name snapshot files." -ForegroundColor Red
                exit 2
            }
        }
        $x = Get-Content $A -Raw -Encoding UTF8 | ConvertFrom-Json
        $y = Get-Content $B -Raw -Encoding UTF8 | ConvertFrom-Json

        $rows = @("plans_archived", "spec_archived", "audit_bytes", "commits",
                  "aider_commits", "tests_written", "failure_paths",
                  "uses_config_file", "literal_100", "functions",
                  "mocks_config", "audit_reopened", "audit_findings",
                  # Added 2026-09-04. deliberate_raises sits directly under
                  # failure_paths on purpose: measured that day, failure_paths
                  # read A=1 B=3, which looks like B covering three times more
                  # error handling, while B's module contained no `raise` at all
                  # and its three paths were TypeErrors Python gives away from
                  # `str + int`. The column below is what stops that reading.
                  "deliberate_raises")

        # Lists, printed apart from the scalar table because a name is the
        # evidence and a count is only a claim about it.
        $listRows = @("documented_untested", "asserted_undocumented",
                      "asserted_deliberate", "asserted_accidental",
                      "raised_unasserted", "open_without_encoding")

        Write-Host ""
        Write-Host ("{0,-20} {1,-24} {2,-24} {3}" -f "criterion", $x.label, $y.label, "")
        Write-Host ("{0,-20} {1,-24} {2,-24} {3}" -f ("-" * 18), ("-" * 22), ("-" * 22), "----")
        foreach ($r in $rows) {
            # A field one snapshot has and the other does not is NOT a difference
            # in the runs, it is a difference in the harness that measured them.
            # Measured 2026-09-04, immediately after deliberate_raises was added:
            # against an older snapshot it printed blank against 0 and marked the
            # row "differs", which reads as a finding about the code and is a
            # finding about the file format. The lists below already said so; the
            # scalar rows did not, and that asymmetry is how a wrong reading
            # survives.
            $hasX = $null -ne $x.PSObject.Properties[$r]
            $hasY = $null -ne $y.PSObject.Properties[$r]
            if (-not ($hasX -and $hasY)) {
                Write-Host ("{0,-20} {1,-24} {2,-24}{3}" -f $r,
                            $(if ($hasX) { "$($x.$r)" } else { "not measured" }),
                            $(if ($hasY) { "$($y.$r)" } else { "not measured" }),
                            "  <-- older snapshot, not comparable")
                continue
            }
            $differs = if ("$($x.$r)" -ne "$($y.$r)") { "  <-- differs" } else { "" }
            Write-Host ("{0,-20} {1,-24} {2,-24}{3}" -f $r, "$($x.$r)", "$($y.$r)", $differs)
        }
        # --- the three directions, printed as names ----------------------------
        # A snapshot taken before 2026-09-04 carries none of these fields. Say so
        # rather than printing six empty rows, which would read as six clean bills
        # of health on a run that was never measured for them.
        $haveLists = ($null -ne $x.PSObject.Properties['documented_untested']) -and
                     ($null -ne $y.PSObject.Properties['documented_untested'])
        Write-Host ""
        if (-not $haveLists) {
            Write-Host "error-handling directions: NOT AVAILABLE - one of these snapshots"
            Write-Host "predates 2026-09-04 and does not carry the fields. Re-snapshot the"
            Write-Host "fixture rather than reading absence as absence of a problem."
        } else {
            Write-Host ("{0,-24} {1,-26} {2}" -f "error handling", $x.label, $y.label)
            Write-Host ("{0,-24} {1,-26} {2}" -f ("-" * 22), ("-" * 24), ("-" * 24))
            foreach ($r in $listRows) {
                $xs = if (@($x.$r).Count) { (@($x.$r) -join ", ") } else { "none" }
                $ys = if (@($y.$r).Count) { (@($y.$r) -join ", ") } else { "none" }
                $differs = if ($xs -ne $ys) { "  <-- differs" } else { "" }
                Write-Host ("{0,-24} {1,-26} {2}{3}" -f $r, $xs, $ys, $differs)
            }
            Write-Host ""
            Write-Host "Each of those six is vacuously clean on some input, so read them in"
            Write-Host "pairs: documented_untested is empty for code with no docstrings, and"
            Write-Host "asserted_accidental is empty for code that asserts nothing. A"
            Write-Host "measurement is honest when it can fail in both directions."
        }

        Write-Host ""
        Write-Host "Two runs of one model on one input differ by themselves. Nothing above"
        Write-Host "attributes a difference to the skills; with one run each, a single"
        Write-Host "differing row is an observation and not a result. The two rows worth"
        Write-Host "reading are mocks_config and audit_reopened, which were predicted"
        Write-Host "before either run, from a disagreement between the two skills."
        Write-Host ""
        Write-Host "=== audit, $($x.label) ==="; Write-Host $x.audit_text
        Write-Host "=== audit, $($y.label) ==="; Write-Host $y.audit_text
    }
}
