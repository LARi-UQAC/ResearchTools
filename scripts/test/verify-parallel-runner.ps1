#Requires -Version 5.1
<#
.SYNOPSIS
    Offline check of the parallel test runners: scripts\lib\rt-parallel.ps1, scripts\lib\rt-runner.json,
    scripts\test\run-offline-tests.ps1 and scripts\test\run-all-checks.ps1.

.DESCRIPTION
    Measured by the owner 2026-11-16: the runners ran one suite at a time and left the machine at 20 to 25 percent
    CPU. The runners now start up to 90 percent of the logical processors worth of child processes at once. What is
    proven here, with real child processes under $env:TEMP and fictitious names (R34):
      - the number of jobs (the share of the processors, never below one, a number asked for wins, a bad
        configuration is refused by key);
      - the pool: children really overlap with Jobs above one and never overlap with Jobs 1, results come back in the
        order of the items whatever the order they ended in, an exit code and both output streams are kept, an empty
        list and a Jobs below one are handled;
      - the decision on a check that fails under load (rerun alone: flaky, or a real failure);
      - run-all-checks.ps1 over a fixture folder: the verifiers overlap, a failing one does not stop the others,
        the exit code and the report are the same as when they run one after the other (-Jobs 1).
    Nothing reads or writes the live repository or ~/.claude.

.EXAMPLE
    .\scripts\test\verify-parallel-runner.ps1
#>

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$Tmp      = Join-Path $env:TEMP "rt-parallel-runner-$PID"
$failures = 0
. (Join-Path $RepoRoot "scripts\lib\rt-parallel.ps1")
$ShippedConfig = Join-Path $RepoRoot "scripts\lib\rt-runner.json"

function Check([string]$name, [bool]$ok) {
    if ($ok) { Write-Host "  PASS  $name" -ForegroundColor DarkGray }
    else     { Write-Host "  FAIL  $name" -ForegroundColor Red; $script:failures++ }
}

function Write-Text([string]$Path, [string]$Text) {
    $dir = Split-Path $Path -Parent
    if (-not (Test-Path -LiteralPath $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
    [System.IO.File]::WriteAllText($Path, $Text, (New-Object System.Text.UTF8Encoding($false)))
}

function Throws([scriptblock]$Block, [string]$Pattern) {
    try { & $Block | Out-Null; return $false } catch { return ($_.Exception.Message -match $Pattern) }
}

# A child that sleeps, then prints "<start ms> <end ms>" and exits with the given code.
function New-Sleeper([string]$Name, [int]$Seconds, [int]$Code = 0) {
    $path = Join-Path $Tmp "$Name.ps1"
    Write-Text $path ("`$s = [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()`r`nStart-Sleep -Seconds $Seconds`r`n" +
        "`$e = [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()`r`nWrite-Output `"`$s `$e`"`r`n" +
        "[Console]::Error.WriteLine('err-of-$Name')`r`nexit $Code`r`n")
    return [pscustomobject]@{ Name = $Name; FilePath = "powershell"; WorkingDirectory = ""
                              ArgumentString = "-NoProfile -ExecutionPolicy Bypass -File `"$path`"" }
}

function Get-Interval($result) {
    $m = [regex]::Match($result.Output, "(\d{12,}) (\d{12,})")
    return [pscustomobject]@{ Start = [int64]$m.Groups[1].Value; End = [int64]$m.Groups[2].Value }
}

function Test-AllOverlap($results) {
    $iv = @($results | ForEach-Object { Get-Interval $_ })
    foreach ($a in $iv) { foreach ($b in $iv) { if ($a.Start -ge $b.End) { return $false } } }
    return $true
}

Write-Host ""
Write-Host "=== parallel runners ===" -ForegroundColor Cyan
New-Item -ItemType Directory -Path $Tmp -Force | Out-Null

try {
    # --- the number of jobs ---------------------------------------------------------------
    Write-Host ""
    Write-Host "  -- the number of jobs --" -ForegroundColor DarkCyan
    $cfg = Read-RtRunnerConfig -Path $ShippedConfig
    Check "the shipped share is 0.9 and the poll is a positive integer" ($cfg.cpu_share -eq 0.9 -and $cfg.poll_ms -ge 1)
    $raw = Get-Content -LiteralPath $ShippedConfig -Raw | ConvertFrom-Json
    Check "every shipped key carries a provenance" (@(@($raw.PSObject.Properties) | Where-Object { -not $_.Value.provenance }).Count -eq 0)
    Check "20 logical processors give 18 jobs" ((Get-RtJobCount -ConfigPath $ShippedConfig -LogicalProcessors 20) -eq 18)
    Check "4 logical processors give 3 jobs" ((Get-RtJobCount -ConfigPath $ShippedConfig -LogicalProcessors 4) -eq 3)
    Check "1 logical processor still gives one job" ((Get-RtJobCount -ConfigPath $ShippedConfig -LogicalProcessors 1) -eq 1)
    Check "a number asked for wins over the share" ((Get-RtJobCount -Requested 5 -ConfigPath $ShippedConfig -LogicalProcessors 20) -eq 5)
    Check "with nothing injected the count reads this machine and is at least one" ((Get-RtJobCount -ConfigPath $ShippedConfig) -ge 1)
    Check "(refusal) a negative -Jobs is refused" (Throws { Get-RtJobCount -Requested -2 -ConfigPath $ShippedConfig } "negative")
    $rest = '"poll_ms": {"value": 100, "provenance": "x"}, "split_seconds": {"value": 60, "provenance": "x"}, "chunk_seconds": {"value": 60, "provenance": "x"}, "rerun_jobs": {"value": 4, "provenance": "x"}, "priority": {"value": "High", "provenance": "x"}'
    Write-Text (Join-Path $Tmp "badprio.json") ('{"cpu_share": {"value": 0.5, "provenance": "x"}, ' + $rest.Replace('"priority": {"value": "High"', '"priority": {"value": "Turbo"') + '}')
    Write-Text (Join-Path $Tmp "over.json") ('{"cpu_share": {"value": 1.5, "provenance": "x"}, ' + $rest + '}')
    Check "(refusal) a share above 1 is refused naming the file" (Throws { Get-RtJobCount -ConfigPath (Join-Path $Tmp "over.json") } "cpu_share.*over\.json")
    Write-Text (Join-Path $Tmp "zero.json") ('{"cpu_share": {"value": 0, "provenance": "x"}, ' + $rest + '}')
    Check "(refusal) a share of 0 is refused" (Throws { Get-RtJobCount -ConfigPath (Join-Path $Tmp "zero.json") } "cpu_share")
    Write-Text (Join-Path $Tmp "nokey.json") '{"cpu_share": {"value": 0.5, "provenance": "x"}, "poll_ms": {"value": 100, "provenance": "x"}, "chunk_seconds": {"value": 60, "provenance": "x"}}'
    Check "(refusal) a missing key is named" (Throws { Read-RtRunnerConfig -Path (Join-Path $Tmp "nokey.json") } "missing key 'split_seconds'")
    Write-Text (Join-Path $Tmp "badsplit.json") ('{"cpu_share": {"value": 0.5, "provenance": "x"}, "poll_ms": {"value": 100, "provenance": "x"}, "split_seconds": {"value": 0, "provenance": "x"}, "chunk_seconds": {"value": 60, "provenance": "x"}, "rerun_jobs": {"value": 4, "provenance": "x"}, "priority": {"value": "High", "provenance": "x"}}')
    Check "(refusal) a split_seconds of 0 is refused" (Throws { Read-RtRunnerConfig -Path (Join-Path $Tmp "badsplit.json") } "split_seconds must be above 0")
    Write-Text (Join-Path $Tmp "noprov.json") ('{"cpu_share": {"value": 0.5}, ' + $rest + '}')
    Check "(refusal) a missing provenance is named" (Throws { Read-RtRunnerConfig -Path (Join-Path $Tmp "noprov.json") } "provenance for 'cpu_share'")
    Check "(refusal) a missing file is named" (Throws { Read-RtRunnerConfig -Path (Join-Path $Tmp "absent.json") } "missing file")

    # --- the pool -------------------------------------------------------------------------
    Write-Host ""
    Write-Host "  -- the pool --" -ForegroundColor DarkCyan
    $four = @(1..4 | ForEach-Object { New-Sleeper "s$_" 2 })
    $watch = [System.Diagnostics.Stopwatch]::StartNew()
    $par = @(Invoke-RtParallel -Items $four -Jobs 4 -PollMs 50)
    $parSeconds = $watch.Elapsed.TotalSeconds
    Check "four children with Jobs 4 all overlap in time" ((Test-AllOverlap $par))
    # the wall time is judged below, against the same four children run one after the other: an absolute limit fails
    # when this check runs beside a dozen others (measured 2026-11-16: 90 s for the whole verifier under run-all-checks)
    $watch.Restart()
    $ser = @(Invoke-RtParallel -Items $four -Jobs 1 -PollMs 50)
    $serSeconds = $watch.Elapsed.TotalSeconds
    $ivs = @($ser | ForEach-Object { Get-Interval $_ })
    $noOverlap = $true
    for ($i = 1; $i -lt $ivs.Count; $i++) { if ($ivs[$i].Start -lt $ivs[$i - 1].End) { $noOverlap = $false } }
    Check "(control) with Jobs 1 no child starts before the previous one ended" $noOverlap
    Check "(control) and the wall time is at least the sum of the sleeps" ($serSeconds -ge 7.5)
    Check "four children with Jobs 4 take clearly less wall time than the same four with Jobs 1" ($parSeconds -lt ($serSeconds - 2))
    $two = @(Invoke-RtParallel -Items $four -Jobs 2 -PollMs 50)
    $ivs = @($two | ForEach-Object { Get-Interval $_ })
    $maxAlive = 0
    foreach ($a in $ivs) {
        $alive = @($ivs | Where-Object { $_.Start -le $a.Start -and $_.End -gt $a.Start }).Count
        if ($alive -gt $maxAlive) { $maxAlive = $alive }
    }
    Check "Jobs 2 never has more than two children alive at once" ($maxAlive -eq 2)

    # results in the order of the items, whatever the order they ended in
    $slow = New-Sleeper "slow" 3
    $fast = New-Sleeper "fast" 1 3
    $endedOrder = New-Object System.Collections.ArrayList
    $mixed = @(Invoke-RtParallel -Items @($slow, $fast) -Jobs 2 -PollMs 50 -OnComplete { param($r) [void]$endedOrder.Add($r.Name) })
    Check "OnComplete is called as each child ends (fast first)" (($endedOrder -join ",") -eq "fast,slow")
    Check "the results stay in the order of the items (slow first)" (($mixed | ForEach-Object { $_.Name }) -join "," -eq "slow,fast")
    Check "an exit code is kept" ($mixed[1].ExitCode -eq 3 -and $mixed[0].ExitCode -eq 0)
    Check "standard output and standard error are both kept" ($mixed[1].Output -match "err-of-fast" -and $mixed[1].Output -match "\d{12,} \d{12,}")
    Check "the seconds of a child are measured" ($mixed[0].Seconds -ge 2.5 -and $mixed[1].Seconds -lt $mixed[0].Seconds)
    Check "an empty list gives nothing" (@(Invoke-RtParallel -Items @() -Jobs 3).Count -eq 0)
    Check "(refusal) Jobs below one is refused" (Throws { Invoke-RtParallel -Items $four -Jobs 0 } "at least 1")

    # --- priority --------------------------------------------------------------------------
    Write-Host ""
    Write-Host "  -- priority --" -ForegroundColor DarkCyan
    $prioPath = Join-Path $Tmp "prio.ps1"
    Write-Text $prioPath "Start-Sleep -Milliseconds 800`r`nWrite-Output ('PRIO ' + (Get-Process -Id `$PID).PriorityClass)`r`n"
    $prioItem = [pscustomobject]@{ Name = "prio"; FilePath = "powershell"; WorkingDirectory = ""
                                   ArgumentString = "-NoProfile -ExecutionPolicy Bypass -File `"$prioPath`"" }
    $high = @(Invoke-RtParallel -Items @($prioItem) -Jobs 1 -PollMs 50 -Priority "High")[0]
    $plain = @(Invoke-RtParallel -Items @($prioItem) -Jobs 1 -PollMs 50)[0]
    Check "a child started with -Priority High really runs at High" ($high.Output -match "PRIO High")
    Check "(control) without -Priority it keeps the normal class" ($plain.Output -match "PRIO Normal")
    Check "the shipped priority is a valid class and is not RealTime (it freezes input, and only an administrator gets it)" ($cfg.priority -eq "High")
    Check "Set-RtOwnPriority with nothing does nothing and says so" ((Set-RtOwnPriority -Priority "") -eq $false)
    Check "(refusal) an unknown priority class in the configuration is refused" (Throws { Read-RtRunnerConfig -Path (Join-Path $Tmp "badprio.json") } "priority must be one of")

    # --- cutting a slow suite -------------------------------------------------------------
    Write-Host ""
    Write-Host "  -- cutting a slow suite --" -ForegroundColor DarkCyan
    Check "a suite under split_seconds is not cut" ((Get-RtChunkCount -RecordedSeconds 59 -TestCount 100 -Jobs 18 -SplitSeconds 60 -ChunkSeconds 60) -eq 1)
    Check "a suite of 720 recorded seconds is cut in 12 shares of about a minute" ((Get-RtChunkCount -RecordedSeconds 720 -TestCount 122 -Jobs 18 -SplitSeconds 60 -ChunkSeconds 60) -eq 12)
    Check "it is never cut in more processes than jobs" ((Get-RtChunkCount -RecordedSeconds 720 -TestCount 122 -Jobs 4 -SplitSeconds 60 -ChunkSeconds 60) -eq 4)
    Check "nor in more than it has tests" ((Get-RtChunkCount -RecordedSeconds 720 -TestCount 3 -Jobs 18 -SplitSeconds 60 -ChunkSeconds 60) -eq 3)
    Check "(control) with one job, an unknown time (0) or one test it is never cut" (
        (Get-RtChunkCount -RecordedSeconds 720 -TestCount 122 -Jobs 1 -SplitSeconds 60 -ChunkSeconds 60) -eq 1 -and
        (Get-RtChunkCount -RecordedSeconds 0 -TestCount 122 -Jobs 18 -SplitSeconds 60 -ChunkSeconds 60) -eq 1 -and
        (Get-RtChunkCount -RecordedSeconds 720 -TestCount 1 -Jobs 18 -SplitSeconds 60 -ChunkSeconds 60) -eq 1)
    $groups = @(Split-RtIds -Ids @("A.t1", "A.t2", "B.t1", "B.t2", "C.t1") -Count 2)
    Check "ids are dealt one by one, so every group gets tests from each class" ((@($groups[0]) -join ",") -eq "A.t1,B.t1,C.t1" -and (@($groups[1]) -join ",") -eq "A.t2,B.t2")
    Check "no id is lost or doubled" ((@($groups | ForEach-Object { $_ }) | Sort-Object) -join "," -eq "A.t1,A.t2,B.t1,B.t2,C.t1")
    Check "(refusal) a Count below 1 is refused" (Throws { Split-RtIds -Ids @("A.t1") -Count 0 } "at least 1")
    $merged = Merge-RtChunks -Name "suite" -Chunks @(
        [pscustomobject]@{ Name = "suite#1"; ExitCode = 0; Output = "one"; Seconds = 1.5 },
        [pscustomobject]@{ Name = "suite#2"; ExitCode = 5; Output = "two"; Seconds = 2.0 },
        [pscustomobject]@{ Name = "suite#3"; ExitCode = 7; Output = "three"; Seconds = 0.5 })
    Check "a merged result takes the first failing exit code, every output and the total seconds" ($merged.ExitCode -eq 5 -and $merged.Output -match "one" -and $merged.Output -match "three" -and $merged.Seconds -eq 4 -and $merged.Name -eq "suite")
    $okMerged = Merge-RtChunks -Name "suite" -Chunks @([pscustomobject]@{ Name = "a"; ExitCode = 0; Output = ""; Seconds = 1 }, [pscustomobject]@{ Name = "b"; ExitCode = 0; Output = ""; Seconds = 1 })
    Check "(control) shares that all pass merge to exit 0" ($okMerged.ExitCode -eq 0)

    # the real cut, with a fixture test file and the real interpreter
    . (Join-Path $RepoRoot "scripts\lib\rt-venv.ps1")
    $resolved = Resolve-RtVenvPython -RepoRoot $RepoRoot -Python "" -AllowPathFallback
    Check "an interpreter is found to run the id lister" ($null -ne $resolved.Python)
    if ($null -ne $resolved.Python) {
        $fixture = Join-Path $Tmp "test_fixture_suite.py"
        Write-Text $fixture ("import time`r`nimport unittest`r`n`r`nclass Alpha(unittest.TestCase):`r`n    def test_a1(self):`r`n        time.sleep(1)`r`n" +
            "    def test_a2(self):`r`n        time.sleep(1)`r`n    def test_a3(self):`r`n        self.fail('planted')`r`n`r`n" +
            "class Beta(unittest.TestCase):`r`n    def test_b1(self):`r`n        time.sleep(1)`r`n    def test_b2(self):`r`n        time.sleep(1)`r`n`r`n" +
            "if __name__ == '__main__':`r`n    unittest.main()`r`n")
        $lister = Join-Path $RepoRoot "scripts\test\list_test_ids.py"
        $ErrorActionPreference = "Continue"
        $listed = & $resolved.Python $lister $fixture 2>&1 | Out-String
        $listCode = $LASTEXITCODE
        $none = & $resolved.Python $lister (Join-Path $Tmp "absent.py") 2>&1 | Out-String
        $noneCode = $LASTEXITCODE
        Write-Text (Join-Path $Tmp "test_broken_suite.py") "import not_a_module_anywhere`r`n"
        $broken = & $resolved.Python $lister (Join-Path $Tmp "test_broken_suite.py") 2>&1 | Out-String
        $brokenCode = $LASTEXITCODE
        $ErrorActionPreference = "Stop"
        $ids = @($listed -split "`r?`n" | ForEach-Object { if ($_ -match '^TESTID (.+)$') { $Matches[1] } })
        Check "the lister prints every test id of the file, in file order, without running a test" ($listCode -eq 0 -and ($ids -join ",") -eq "Alpha.test_a1,Alpha.test_a2,Alpha.test_a3,Beta.test_b1,Beta.test_b2")
        Check "(refusal) a missing file is exit 2 and a file that cannot be imported is exit 1, nothing printed as an id" ($noneCode -eq 2 -and $brokenCode -eq 1 -and $none -notmatch "TESTID" -and $broken -notmatch "TESTID")
        $shares = @(Split-RtIds -Ids $ids -Count 2)
        $chunkItems = @(for ($k = 0; $k -lt $shares.Count; $k++) {
            [pscustomobject]@{ Name = "fixture#$($k + 1)"; FilePath = $resolved.Python; WorkingDirectory = $Tmp
                               ArgumentString = "`"$fixture`" " + (@($shares[$k]) -join " ") }
        })
        $chunkRuns = @(Invoke-RtParallel -Items $chunkItems -Jobs 2 -PollMs 50)
        Check "each share runs only its own tests (3 and 2 tests) when the file ends in unittest.main()" ($chunkRuns[0].Output -match "Ran 3 tests" -and $chunkRuns[1].Output -match "Ran 2 tests")
        $mergedFixture = Merge-RtChunks -Name "fixture" -Chunks $chunkRuns
        Check "a planted failure in one share makes the merged suite fail and names it" ($mergedFixture.ExitCode -ne 0 -and $mergedFixture.Output -match "planted")
        Check "(control) the share without the planted failure passes" ($chunkRuns[1].ExitCode -eq 0)
    }

    # --- a failure under load -------------------------------------------------------------
    Write-Host ""
    Write-Host "  -- a failure under load --" -ForegroundColor DarkCyan
    $d = Resolve-RtRetry -FirstOutcome "FAILED" -AloneOutcome "PASSED"
    Check "failed in parallel and passed alone is passed and flaky" ($d.Outcome -eq "PASSED" -and $d.Flaky)
    $d = Resolve-RtRetry -FirstOutcome "FAILED" -AloneOutcome "FAILED"
    Check "(control) failed again alone is a real failure, not flaky" ($d.Outcome -eq "FAILED" -and -not $d.Flaky)
    $d = Resolve-RtRetry -FirstOutcome "PASSED"
    Check "(control) a pass is never rerun and never flaky" ($d.Outcome -eq "PASSED" -and -not $d.Flaky)
    $d = Resolve-RtRetry -FirstOutcome "NOT RUN" -AloneOutcome "PASSED"
    Check "(control) a not-run suite is left as it is" ($d.Outcome -eq "NOT RUN" -and -not $d.Flaky)
    $d = Resolve-RtRetry -FirstOutcome "FAILED"
    Check "a failure that was not rerun stays failed" ($d.Outcome -eq "FAILED" -and -not $d.Flaky)

    # --- run-all-checks.ps1 over a fixture -----------------------------------------------
    Write-Host ""
    Write-Host "  -- run-all-checks.ps1 --" -ForegroundColor DarkCyan
    $Fx = Join-Path $Tmp "checks"
    foreach ($n in @("verify-a", "verify-b", "verify-c")) {
        $code = if ($n -eq "verify-b") { 3 } else { 0 }
        Write-Text (Join-Path $Fx "$n.ps1") ("Start-Sleep -Seconds 3`r`nSet-Content -LiteralPath (Join-Path `$PSScriptRoot '$n.ran') -Value 'x'`r`nexit $code`r`n")
    }
    $runAll = Join-Path $RepoRoot "scripts\test\run-all-checks.ps1"
    $reportPar = Join-Path $Tmp "par.json"
    $reportSer = Join-Path $Tmp "ser.json"
    $watch.Restart()
    $outPar = & powershell -NoProfile -ExecutionPolicy Bypass -File $runAll -TestDir $Fx -SkipSuite -Jobs 3 -ReportPath $reportPar *>&1 | Out-String
    $codePar = $LASTEXITCODE
    $tPar = $watch.Elapsed.TotalSeconds
    $ranPar = @(Get-ChildItem -LiteralPath $Fx -Filter "*.ran").Count
    Get-ChildItem -LiteralPath $Fx -Filter "*.ran" | Remove-Item -Force
    $watch.Restart()
    & powershell -NoProfile -ExecutionPolicy Bypass -File $runAll -TestDir $Fx -SkipSuite -Jobs 1 -ReportPath $reportSer *>&1 | Out-Null
    $codeSer = $LASTEXITCODE
    $tSer = $watch.Elapsed.TotalSeconds
    Check "with -Jobs 3 a failing verifier gives exit 1 and every verifier ran" ($codePar -eq 1 -and $ranPar -eq 3)
    Check "with -Jobs 1 the exit code is the same" ($codeSer -eq 1)
    Check "the three verifiers of 3 s each take less time together than one after the other" ($tPar -lt ($tSer - 2))
    $rp = Get-Content -LiteralPath $reportPar -Raw | ConvertFrom-Json
    $rs = Get-Content -LiteralPath $reportSer -Raw | ConvertFrom-Json
    Check "the report lists every check in name order with its exit code, parallel or not" `
        ((($rp.checks | ForEach-Object { "$($_.name)=$($_.exit_code)" }) -join ",") -eq "verify-a.ps1=0,verify-b.ps1=3,verify-c.ps1=0" -and
         (($rs.checks | ForEach-Object { "$($_.name)=$($_.exit_code)" }) -join ",") -eq "verify-a.ps1=0,verify-b.ps1=3,verify-c.ps1=0")
    Check "the report counts passed and failed" ($rp.passed -eq 2 -and $rp.failed -eq 1)
    Check "the summary names the failing check" ($outPar -match "FAIL\s+verify-b\.ps1")
    Check "each verifier prints its own block with its exit code" ($outPar -match "verify-b\.ps1\s+\(exit 3")
    $ErrorActionPreference = "Continue"   # a child's stderr is output here, its exit code is what is checked
    & powershell -NoProfile -ExecutionPolicy Bypass -File $runAll -TestDir $Fx -SkipSuite -Jobs -1 *>&1 | Out-Null
    $codeNegative = $LASTEXITCODE
    $ErrorActionPreference = "Stop"
    Check "(refusal) a negative -Jobs is refused with a non-zero exit" ($codeNegative -ne 0)

    # --- wiring, read as text -------------------------------------------------------------
    Write-Host ""
    Write-Host "  -- wiring --" -ForegroundColor DarkCyan
    $suiteText = Get-Content -LiteralPath (Join-Path $RepoRoot "scripts\test\run-offline-tests.ps1") -Raw
    Check "failed items are rerun together, a few at a time, not one after the other" ($suiteText -match "rerun_jobs" -and $suiteText -notmatch "-Jobs 1 -PollMs")
    Check "run-offline-tests.ps1 has -Jobs, uses the pool and reruns a failure alone" ($suiteText -match "\[int\]\`$Jobs" -and $suiteText -match "Invoke-RtParallel" -and $suiteText -match "Resolve-RtRetry")
    Check "run-offline-tests.ps1 keeps no Start-Process of its own" ($suiteText -notmatch "Start-Process")
    Check "run-offline-tests.ps1 records the seconds of each suite in the stamp" ($suiteText -match "seconds = \`$run\.Seconds")
    $allText = Get-Content -LiteralPath $runAll -Raw
    Check "run-all-checks.ps1 has -Jobs and uses the pool for the verifiers" ($allText -match "\[int\]\`$Jobs" -and $allText -match "Invoke-RtParallel")
    Check "no literal share or poll is written in the two runners (R0)" ($suiteText -notmatch "0\.9" -and $allText -notmatch "0\.9")
}
finally {
    Remove-Item -LiteralPath $Tmp -Recurse -Force -ErrorAction SilentlyContinue
}

Write-Host ""
if ($failures -eq 0) { Write-Host "All parallel runner checks passed." -ForegroundColor Green; exit 0 }
Write-Host "$failures parallel runner check(s) failed." -ForegroundColor Red
exit 1
