# rt-parallel.ps1 - run several child processes at once and collect their output, for the test runners.
#
# Dot-sourced by scripts\test\run-offline-tests.ps1 and scripts\test\run-all-checks.ps1, and proven by
# scripts\test\verify-parallel-runner.ps1. Windows PowerShell 5.1 has no ForEach-Object -Parallel, so the pool is
# a loop over Start-Process with the output of each child redirected to its own files: nothing is interleaved.

function Read-RtRunnerConfig {
    <#
        --------------------------------------------------------------------------
        Purpose:
            Read scripts\lib\rt-runner.json, every value with its provenance.

        Inputs:
            Path (string): the JSON file

        Outputs:
            config (hashtable): key to value, for cpu_share and poll_ms

        Raises:
            A terminating error naming the key and the file when the file, a key or a provenance is missing (R3).
        --------------------------------------------------------------------------
    #>
    param([Parameter(Mandatory = $true)][string]$Path)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { throw "missing file: $Path" }
    $raw = Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json
    $config = @{}
    foreach ($key in @("cpu_share", "poll_ms", "split_seconds", "chunk_seconds")) {
        $entry = $raw.PSObject.Properties[$key]
        if ($null -eq $entry -or $null -eq $entry.Value.PSObject.Properties["value"]) { throw "missing key '$key' in $Path" }
        if (-not $entry.Value.PSObject.Properties["provenance"] -or -not $entry.Value.provenance) { throw "missing provenance for '$key' in $Path" }
        $config[$key] = $entry.Value.value
    }
    # Windows PowerShell 5.1 reads 0.9 as a decimal and 100 as an int: both are numbers, a string or a boolean is not.
    foreach ($key in @("cpu_share", "poll_ms", "split_seconds", "chunk_seconds")) {
        if ($config[$key] -isnot [ValueType] -or $config[$key] -is [bool]) { throw "$key must be a number in $Path" }
    }
    foreach ($key in @("split_seconds", "chunk_seconds")) {
        if ($config[$key] -le 0) { throw "$key must be above 0 in $Path" }
    }
    $config.cpu_share = [double]$config.cpu_share
    if ($config.cpu_share -le 0 -or $config.cpu_share -gt 1) { throw "cpu_share must be above 0 and at most 1 in ${Path}: $($config.cpu_share)" }
    if ($config.poll_ms -ne [Math]::Floor([double]$config.poll_ms) -or $config.poll_ms -lt 1) { throw "poll_ms must be a positive integer in $Path" }
    $config.poll_ms = [int]$config.poll_ms
    return $config
}

function Get-RtJobCount {
    <#
        --------------------------------------------------------------------------
        Purpose:
            How many child processes may run at once: the number asked for, else the configured share of the
            logical processors, never less than one.

        Inputs:
            Requested (int): a number given on the command line; above 0 it wins
            ConfigPath (string): scripts\lib\rt-runner.json
            LogicalProcessors (int): injected by a test; 0 reads this machine

        Outputs:
            jobs (int): at least 1
        --------------------------------------------------------------------------
    #>
    param(
        [int]$Requested = 0,
        [Parameter(Mandatory = $true)][string]$ConfigPath,
        [int]$LogicalProcessors = 0
    )
    if ($Requested -gt 0) { return $Requested }
    if ($Requested -lt 0) { throw "-Jobs must not be negative: $Requested" }
    $config = Read-RtRunnerConfig -Path $ConfigPath
    if ($LogicalProcessors -le 0) { $LogicalProcessors = [Environment]::ProcessorCount }
    return [Math]::Max(1, [int][Math]::Floor($LogicalProcessors * [double]$config.cpu_share))
}

function Invoke-RtParallel {
    <#
        --------------------------------------------------------------------------
        Purpose:
            Run child processes with at most Jobs of them alive at once. Each child writes its standard output and
            error to its own temporary files, so two children never mix their lines.

        Inputs:
            Items (object[]): each with Name, FilePath, ArgumentString (one string, already quoted) and
                WorkingDirectory (a folder or an empty string)
            Jobs (int): the most children alive at once, at least 1 (1 runs them one after the other)
            PollMs (int): milliseconds between two looks at the children
            OnComplete (scriptblock): called with each result as soon as its child ended, in the order they end

        Outputs:
            results (object[]): in the order of Items, each with Name, ExitCode, Output (standard output then
                standard error) and Seconds
        --------------------------------------------------------------------------
    #>
    param(
        [object[]]$Items = @(),
        [int]$Jobs = 1,
        [int]$PollMs = 100,
        [scriptblock]$OnComplete = $null
    )
    if ($Jobs -lt 1) { throw "Jobs must be at least 1: $Jobs" }
    $list = @($Items)
    if ($list.Count -eq 0) { return @() }
    $results = New-Object 'object[]' $list.Count
    $running = New-Object System.Collections.ArrayList
    $next = 0
    while ($next -lt $list.Count -or $running.Count -gt 0) {
        while ($next -lt $list.Count -and $running.Count -lt $Jobs) {
            $item = $list[$next]
            $outFile = [System.IO.Path]::GetTempFileName()
            $errFile = [System.IO.Path]::GetTempFileName()
            $start = @{
                FilePath = $item.FilePath; ArgumentList = $item.ArgumentString; NoNewWindow = $true; PassThru = $true
                RedirectStandardOutput = $outFile; RedirectStandardError = $errFile
            }
            if ($item.WorkingDirectory) { $start.WorkingDirectory = $item.WorkingDirectory }
            $proc = Start-Process @start
            # Touching the handle keeps the exit code readable after the process ended (Windows PowerShell 5.1).
            $null = $proc.Handle
            [void]$running.Add([pscustomobject]@{
                Index = $next; Proc = $proc; Out = $outFile; Err = $errFile; Watch = [System.Diagnostics.Stopwatch]::StartNew()
            })
            $next++
        }
        $ended = @($running | Where-Object { $_.Proc.HasExited })
        foreach ($child in $ended) {
            $child.Proc.WaitForExit()
            $text = ""
            foreach ($file in @($child.Out, $child.Err)) {
                if (Test-Path -LiteralPath $file) {
                    $part = Get-Content -LiteralPath $file -Raw -ErrorAction SilentlyContinue
                    if ($null -ne $part) { $text += $part }
                }
            }
            Remove-Item -LiteralPath $child.Out, $child.Err -Force -ErrorAction SilentlyContinue
            $result = [pscustomobject]@{
                Name = $list[$child.Index].Name; ExitCode = $child.Proc.ExitCode; Output = $text
                Seconds = [Math]::Round($child.Watch.Elapsed.TotalSeconds, 1)
            }
            $results[$child.Index] = $result
            $running.Remove($child)
            if ($null -ne $OnComplete) { & $OnComplete $result }
        }
        if ($ended.Count -eq 0 -and ($running.Count -ge $Jobs -or $next -ge $list.Count)) { Start-Sleep -Milliseconds $PollMs }
    }
    return $results
}

function Get-RtChunkCount {
    <#
        --------------------------------------------------------------------------
        Purpose:
            Into how many processes a suite is cut: one when it is not slow, else its recorded seconds divided by
            the seconds one process should carry, never more than the jobs or the tests it has.

        Inputs:
            RecordedSeconds (double): the total time of the suite on its last run, 0 when unknown
            TestCount (int): the tests the suite holds
            Jobs (int): the processes allowed at once
            SplitSeconds (double): config key split_seconds; a suite shorter than this is not cut
            ChunkSeconds (double): config key chunk_seconds

        Outputs:
            count (int): at least 1
        --------------------------------------------------------------------------
    #>
    param([double]$RecordedSeconds, [int]$TestCount, [int]$Jobs, [double]$SplitSeconds, [double]$ChunkSeconds)
    if ($Jobs -lt 2 -or $TestCount -lt 2 -or $RecordedSeconds -lt $SplitSeconds) { return 1 }
    $wanted = [int][Math]::Ceiling($RecordedSeconds / $ChunkSeconds)
    return [Math]::Max(1, [Math]::Min($wanted, [Math]::Min($Jobs, $TestCount)))
}

function Split-RtIds {
    <#
        --------------------------------------------------------------------------
        Purpose:
            Deal test ids into Count groups one by one, like cards, so each group holds tests from every part of
            the file: a slow class is spread over the processes instead of landing in one.

        Inputs:
            Ids (string[]): the test ids, in file order
            Count (int): the groups, at least 1

        Outputs:
            groups (object[]): Count arrays of ids, none empty when Count does not exceed the ids
        --------------------------------------------------------------------------
    #>
    param([string[]]$Ids, [int]$Count)
    if ($Count -lt 1) { throw "Count must be at least 1: $Count" }
    $groups = @(for ($i = 0; $i -lt $Count; $i++) { , (New-Object System.Collections.Generic.List[string]) })
    for ($i = 0; $i -lt @($Ids).Count; $i++) { $groups[$i % $Count].Add($Ids[$i]) }
    return @($groups | ForEach-Object { , @($_.ToArray()) })
}

function Merge-RtChunks {
    <#
        --------------------------------------------------------------------------
        Purpose:
            Make one result of the processes a cut suite ran in: the exit code is the first non-zero one, the output
            holds every part, the seconds are the total work (what the next run needs to cut it again).

        Inputs:
            Name (string): the suite
            Chunks (object[]): results of Invoke-RtParallel

        Outputs:
            result (object): Name, ExitCode, Output, Seconds, Chunks
        --------------------------------------------------------------------------
    #>
    param([string]$Name, [object[]]$Chunks)
    $list = @($Chunks)
    $failing = @($list | Where-Object { $_.ExitCode -ne 0 })
    $code = if ($failing.Count -gt 0) { $failing[0].ExitCode } else { 0 }
    $seconds = 0.0
    foreach ($c in $list) { $seconds += [double]$c.Seconds }
    return [pscustomobject]@{
        Name = $Name; ExitCode = $code; Output = (($list | ForEach-Object { $_.Output }) -join "`n")
        Seconds = [Math]::Round($seconds, 1); Chunks = $list.Count
    }
}

function Resolve-RtRetry {
    <#
        --------------------------------------------------------------------------
        Purpose:
            Decide the final outcome of a check that failed while others ran beside it. A failure that does not
            repeat when the check runs alone is reported as passed under parallel load, never hidden.

        Inputs:
            FirstOutcome (string): PASSED, FAILED or NOT RUN, from the parallel run
            AloneOutcome (string): the outcome of the same check run alone, or $null when it was not rerun

        Outputs:
            decision (object): Outcome (the final one) and Flaky (true when it failed in parallel and passed alone)
        --------------------------------------------------------------------------
    #>
    param([Parameter(Mandatory = $true)][string]$FirstOutcome, [string]$AloneOutcome = "")
    if ($FirstOutcome -ne "FAILED" -or -not $AloneOutcome) { return [pscustomobject]@{ Outcome = $FirstOutcome; Flaky = $false } }
    if ($AloneOutcome -eq "PASSED") { return [pscustomobject]@{ Outcome = "PASSED"; Flaky = $true } }
    return [pscustomobject]@{ Outcome = $AloneOutcome; Flaky = $false }
}
