<#
.SYNOPSIS
  Launch a nightly run detached, holding a wake lock, and record its exit code.

.DESCRIPTION
  A run takes hours. This starts it in a process of its own so it survives the
  terminal, the editor, and a Claude Code session restart - measured 2026-09-03,
  where a run launched this way survived two session restarts and finished
  cleanly.

  It holds a wake lock for its own lifetime and releases it in a finally, because
  the only sleep state this firmware offers is S0 Modern Standby, which does not
  stop the machine but throttles it, and nothing in the log would say so.

.PARAMETER Project
  The project to run.

.PARAMETER LogFile
  Where the transcript goes. Written as UTF-16 by Tee-Object, so read it back
  with -Encoding Unicode or it is unreadable.

.PARAMETER RcFile
  Where the driver's exit code is written, and ONLY when the run ends. Its
  absence is how you know the run is still going.

.PARAMETER Skills
  Run through aider-night.ps1, which loads the per-stage skills. Without it the
  driver is called directly with no skills, which is the A side of the A/B.

.PARAMETER TestCommand
  Passed through. For an A/B comparison both sides must use the SAME command, or
  the difference measured is the harness rather than the skills.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Project,
    [Parameter(Mandatory = $true)][string]$LogFile,
    [Parameter(Mandatory = $true)][string]$RcFile,
    [switch]$Skills,
    [string]$TestCommand = 'python -m unittest discover -s tests -p "test_*.py"'
)

$inner = @'
# No param() block: run-detached.ps1 bakes these in as literals. Start-Process
# joins an ArgumentList with spaces, so a TestCommand containing spaces used to
# arrive as several arguments and this script died during PARAMETER BINDING,
# before its first Out-File - while the launcher had already printed a pid, so
# the run looked started and no log ever appeared.
__RT_BAKED__

Add-Type -Namespace Win32 -Name Power -MemberDefinition @"
[DllImport("kernel32.dll", SetLastError = true)]
public static extern uint SetThreadExecutionState(uint esFlags);
"@

# Decimal, never 0x80000000: PowerShell 5.1 parses that literal as Int32
# -2147483648, which will not cast to UInt32, and the call throws before the
# lock is ever taken. Measured 2026-09-03 - it killed the first launcher.
$ES_CONTINUOUS       = [uint32]2147483648
$ES_SYSTEM_REQUIRED  = [uint32]1
$ES_AWAYMODE         = [uint32]64

try {
    $prev = [Win32.Power]::SetThreadExecutionState($ES_CONTINUOUS -bor $ES_SYSTEM_REQUIRED -bor $ES_AWAYMODE)
    if ($prev -eq 0) { $prev = [Win32.Power]::SetThreadExecutionState($ES_CONTINUOUS -bor $ES_SYSTEM_REQUIRED) }
    # unicode, matching Tee-Object below: PowerShell 5.1 Tee-Object writes UTF-16
# and offers no -Encoding, so every other writer to this file must agree with
# it or the log holds two encodings and no single -Encoding reads it whole.
"WAKELOCK: previous state = $prev" | Out-File -FilePath $LogFile -Encoding unicode
    "START: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')" | Out-File -FilePath $LogFile -Encoding unicode -Append

    Set-Location $Project
    if ($UseSkills -eq "yes") {
        $env:AIDER_TEST_COMMAND = $TestCommand
        & "$HOME\.local\bin\aider-night.ps1" -Project $Project *>&1 |
            ForEach-Object {
                $line = "$(Get-Date -Format 'HH:mm:ss')  $($_.ToString())"
                # Per line, NOT Tee-Object, which does not flush until its
                # pipeline ends - and the pipeline here is the whole night. A
                # refusal printed into that buffer never reaches the log, so a
                # run that cannot start looks exactly like one that is working.
                Add-Content -LiteralPath $LogFile -Value $line -Encoding Unicode
                $line
            }
    } else {
        & "$HOME\.local\bin\aider-plan.ps1" `
            -Config      "$HOME\.config\aider\build\aider.conf.yml.saved" `
            -BudgetFile  "$HOME\.config\aider\context-budget.json" `
            -TestCommand $TestCommand *>&1 |
            ForEach-Object {
                $line = "$(Get-Date -Format 'HH:mm:ss')  $($_.ToString())"
                # Per line, NOT Tee-Object, which does not flush until its
                # pipeline ends - and the pipeline here is the whole night. A
                # refusal printed into that buffer never reaches the log, so a
                # run that cannot start looks exactly like one that is working.
                Add-Content -LiteralPath $LogFile -Value $line -Encoding Unicode
                $line
            }
    }

    # Captured on the line immediately after the call, before anything else runs.
    # A trailing command overwrites it and a failed run then reads as a success.
    $rc = $LASTEXITCODE
    Set-Content -Path $RcFile -Value $rc -Encoding ascii
    "DRIVER EXIT = $rc" | Out-File -FilePath $LogFile -Encoding unicode -Append
    "END: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')" | Out-File -FilePath $LogFile -Encoding unicode -Append
}
finally {
    [void][Win32.Power]::SetThreadExecutionState($ES_CONTINUOUS)
}
'@

function Write-Utf8NoBom([string]$Path, [string]$Text) {
    # A BOM in a .ps1 is tolerated by PowerShell, but the driver and the A/B
    # harness both stopped emitting one on 2026-09-05 and one writer per file
    # is one too many. Same call, same reason.
    [System.IO.File]::WriteAllText($Path, $Text, (New-Object System.Text.UTF8Encoding($false)))
}

$innerPath = Join-Path $env:TEMP ("detached-" + [guid]::NewGuid().ToString("N").Substring(0,8) + ".ps1")
Remove-Item -LiteralPath $RcFile -ErrorAction SilentlyContinue
$useSkills = if ($Skills) { "yes" } else { "no" }
# The value is wrapped as a single-quoted PowerShell literal with '' doubling,
# so it cannot be reinterpreted as code and a quote inside a test command is
# harmless.
function ConvertTo-PsLiteral([string]$Value) { return "'" + $Value.Replace("'", "''") + "'" }
$baked = @(
    ('$Project     = ' + (ConvertTo-PsLiteral $Project)),
    ('$LogFile     = ' + (ConvertTo-PsLiteral $LogFile)),
    ('$RcFile      = ' + (ConvertTo-PsLiteral $RcFile)),
    ('$UseSkills   = ' + (ConvertTo-PsLiteral $useSkills)),
    ('$TestCommand = ' + (ConvertTo-PsLiteral $TestCommand))
) -join [Environment]::NewLine
$inner = $inner.Replace("__RT_BAKED__", $baked)
Write-Utf8NoBom $innerPath $inner

$p = Start-Process -FilePath "powershell.exe" -WindowStyle Hidden -PassThru -ArgumentList @(
    "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $innerPath)

Write-Host "launched pid=$($p.Id)  $(Get-Date -Format 'HH:mm:ss')"
Write-Host "  skills : $useSkills"
Write-Host "  log    : $LogFile      (read with -Encoding Unicode)"
Write-Host "  rc     : $RcFile       (appears only when the run ends)"
