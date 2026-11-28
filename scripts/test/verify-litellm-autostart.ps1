<#
.SYNOPSIS
    Verifies scripts\local\augure\litellm-autostart.ps1 without starting anything (Issue #112, plan 3).

.DESCRIPTION
    The launcher is dot-sourced with RT_LITELLM_NO_MAIN=1, so only its functions are defined.
    The User environment reader, the port probe, the shortcut writer and the Startup folder are
    all replaced or injected (R21): no real process, no network, no registry write, no Startup
    write. The real User environment is read before and after to prove it was not written.

    Exit 0 when every check passes, 1 on any failure (R12).
#>
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$Repo     = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$DataDir  = Join-Path $Repo 'scripts\local\augure'
$Launcher = Join-Path $DataDir 'litellm-autostart.ps1'
$Bat      = Join-Path $DataDir 'litellm-autostart.bat'

$script:Pass = 0
$script:Fail = 0

function Check {
    param([string]$Name, [bool]$Ok, [string]$Detail = '')
    if ($Ok) {
        $script:Pass++
        Write-Output "PASS  $Name"
    } else {
        $script:Fail++
        $msg = "FAIL  $Name"
        if ($Detail) { $msg += " - $Detail" }
        Write-Output $msg
    }
}

function Get-ThrownMessage {
    param([scriptblock]$Block)
    try { & $Block | Out-Null; return '' } catch { return $_.Exception.Message }
}

function Finish-Verification {
    Write-Output ("RESULT: {0} passed, {1} failed" -f $script:Pass, $script:Fail)
    if ($script:Fail -gt 0) { exit 1 }
    exit 0
}

if (-not (Test-Path -LiteralPath $Launcher -PathType Leaf)) {
    Check 'launcher exists' $false "missing $Launcher"
    Finish-Verification
}

$RealUserKeyBefore = [Environment]::GetEnvironmentVariable('LITELLM_MASTER_KEY', 'User')

$env:RT_LITELLM_NO_MAIN = '1'
. $Launcher
Remove-Item Env:RT_LITELLM_NO_MAIN -ErrorAction SilentlyContinue

$Settings = Get-Content -LiteralPath (Join-Path $DataDir 'augure-settings.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$Profiles = Get-Content -LiteralPath (Join-Path $DataDir 'augure-profiles.json') -Raw -Encoding UTF8 | ConvertFrom-Json

# ---- shadows: nothing real is reached -------------------------------------------------
$script:PortProbes = New-Object System.Collections.ArrayList
$script:PortProbeIndex = 0
function Get-LitellmPortOwner {
    param([int]$Port)
    if ($script:PortProbeIndex -lt $script:PortProbes.Count) {
        $answer = $script:PortProbes[$script:PortProbeIndex]
        $script:PortProbeIndex++
        return $answer
    }
    return $null
}
function Reset-PortProbes {
    param([object[]]$Answers)
    $script:PortProbes = New-Object System.Collections.ArrayList
    foreach ($a in $Answers) { [void]$script:PortProbes.Add($a) }
    $script:PortProbeIndex = 0
}

$script:RenderExit = 0
$script:LivenessAnswer = $true
$script:WrapperPid = 99
$script:FakeVenvDir = ''
function Resolve-RtVenvPython {
    param([string]$RepoRoot, [string]$VenvName)
    return @{ Python = (Join-Path $script:FakeVenvDir 'python.exe'); Message = '' }
}
function Invoke-LitellmRenderConfig {
    param([string]$Python, [string]$ModelsPy, [string]$CfgPath, [switch]$DryRun)
    return $script:RenderExit
}
$script:StartCount = 0
function Start-LitellmProcess {
    param([string]$ExePath, [string]$Arguments, [hashtable]$Environment, [string]$LogPath)
    $script:StartCount++
    return [pscustomobject]@{ Id = $script:WrapperPid }
}
$script:SettingsForRun = $null
function Read-LitellmJson {
    param([string]$Path)
    if ($Path -like '*augure-settings.json') {
        if ($null -ne $script:SettingsForRun) { return $script:SettingsForRun }
        return $Settings
    }
    return $Profiles
}
$script:StatusAlive = $true
function Invoke-WebRequest {
    param([string]$Uri, [switch]$UseBasicParsing, [int]$TimeoutSec)
    if ($script:StatusAlive) { return [pscustomobject]@{ StatusCode = 200 } }
    throw 'not answering (shadowed)'
}
function Wait-LitellmLiveness {
    param([string]$Url, [int]$TotalTimeoutSec, [int]$RequestTimeoutSec)
    return $script:LivenessAnswer
}
function Initialize-LitellmLogFolder {
    param([string]$LogPath)
}
function Invoke-LitellmLogRotation {
    param([string]$LogPath, [long]$MaxBytes)
}

$script:ShortcutCalls = 0
function New-LitellmShortcut {
    param([string]$Path, [string]$Target, [string]$WorkingDirectory, [string]$Description)
    $script:ShortcutCalls++
    Set-Content -LiteralPath $Path -Value "target=$Target" -Encoding ASCII
}

$script:Store = @{}
$script:WriteCount = 0
$ReadUser = { param([string]$Name) if ($script:Store.ContainsKey($Name)) { $script:Store[$Name] } else { $null } }
$WriteUser = { param([string]$Name, [string]$Value) $script:WriteCount++; $script:Store[$Name] = $Value }

$Tmp = Join-Path ([IO.Path]::GetTempPath()) ('litellm-verify-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $Tmp -Force | Out-Null
$FakeBat = Join-Path $Tmp 'fixture-launcher.bat'
Set-Content -LiteralPath $FakeBat -Value '@echo off' -Encoding ASCII
$script:FakeVenvDir = Join-Path $Tmp 'fakevenv'
New-Item -ItemType Directory -Path $script:FakeVenvDir -Force | Out-Null
Set-Content -LiteralPath (Join-Path $script:FakeVenvDir 'litellm.exe') -Value '' -Encoding ASCII
$script:FakeExe = Join-Path $script:FakeVenvDir 'litellm.exe'
$OwnCmd = '"' + $script:FakeExe + '" --config x.yaml --port 4000'

function New-StartupFolder {
    $folder = Join-Path $Tmp ('startup-' + [guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $folder -Force | Out-Null
    return $folder
}

# ---- 1-4: decisions ---------------------------------------------------------------------
$T0 = Get-Date '2026-11-27T10:00:00'
$T1 = $T0.AddMinutes(5)
function Invoke-DecisionCase {
    # Defaults: a python owner (pid 4321) that is not LiteLLM, against this repo's litellm.exe.
    param([string]$Name, [hashtable]$Case, [string]$Expect, [string]$ReasonPattern = '')
    $full = @{ PortOwnerPid = 4321; PortOwnerName = 'python'; PortOwnerCommandLine = 'python.exe worker.py'; LitellmExe = $script:FakeExe }
    foreach ($k in $Case.Keys) { $full[$k] = $Case[$k] }
    try {
        $d = Resolve-LitellmStartDecision @full -Settings $Settings
        $ok = ($d.Action -eq $Expect) -and (($ReasonPattern -eq '') -or ($d.Reason -match $ReasonPattern))
        Check $Name $ok "got $($d.Action): $($d.Reason)"
    } catch { Check $Name $false $_.Exception.Message }
}

Invoke-DecisionCase 'free port gives start' @{ PortOwnerPid = $null; LitellmExe = $script:FakeExe } 'start'
Invoke-DecisionCase 'port held by a bare process named litellm, no path, refused' @{ PortOwnerPid = 1234; PortOwnerName = 'litellm'; LitellmExe = $script:FakeExe } 'refuse'
Invoke-DecisionCase 'python running this repo litellm gives running' (@{ PortOwnerCommandLine = $OwnCmd }) 'running'
Invoke-DecisionCase 'node server from litellm-dashboard refused, PID named' @{ PortOwnerPid = 5555; PortOwnerName = 'node'; PortOwnerCommandLine = 'node C:\dev\litellm-dashboard\server.js'; LitellmExe = $script:FakeExe } 'refuse' '5555'
Invoke-DecisionCase 'python running a different venv litellm refused' @{ PortOwnerPid = 4321; PortOwnerName = 'python'; PortOwnerCommandLine = '"C:\other\.venv-litellm\Scripts\python.exe" "C:\other\.venv-litellm\Scripts\litellm.exe" --port 4000'; LitellmExe = $script:FakeExe } 'refuse'
Invoke-DecisionCase 'python with no litellm evidence refused, PID named' (@{ PortOwnerCommandLine = 'python.exe worker.py' }) 'refuse' '4321'
Invoke-DecisionCase 'parent at exact path created before child gives running' (@{ PortOwnerCommandLine = 'python.exe worker.py'; PortOwnerCreated = $T1; PortOwnerParentPath = $script:FakeExe; PortOwnerParentCreated = $T0 }) 'running'
Invoke-DecisionCase 'parent at exact path created at the same time as child gives running' (@{ PortOwnerCommandLine = 'python.exe worker.py'; PortOwnerCreated = $T0; PortOwnerParentPath = $script:FakeExe; PortOwnerParentCreated = $T0 }) 'running'
Invoke-DecisionCase 'parent at exact path created AFTER child refused (reused PID)' (@{ PortOwnerCommandLine = 'python.exe worker.py'; PortOwnerCreated = $T0; PortOwnerParentPath = $script:FakeExe; PortOwnerParentCreated = $T1 }) 'refuse'
Invoke-DecisionCase 'parent named litellm.exe at another path refused' (@{ PortOwnerCommandLine = 'python.exe worker.py'; PortOwnerCreated = $T1; PortOwnerParentPath = 'C:\other\litellm.exe'; PortOwnerParentCreated = $T0 }) 'refuse'
Invoke-DecisionCase 'parent at exact path with unknown creation time refused' (@{ PortOwnerCommandLine = 'python.exe worker.py'; PortOwnerCreated = $T1; PortOwnerParentPath = $script:FakeExe; PortOwnerParentCreated = $null }) 'refuse'

try {
    $wide = $Settings | ConvertTo-Json -Depth 10 | ConvertFrom-Json
    $wide.proxy_host.value = '0.0.0.0'
    $d = Resolve-LitellmStartDecision -PortOwnerPid $null -PortOwnerName '' -Settings $wide
    Check 'host 0.0.0.0 refused' ($d.Action -eq 'refuse') "got $($d.Action)"
} catch { Check 'host 0.0.0.0 refused' $false $_.Exception.Message }

try {
    $badPort = $Settings | ConvertTo-Json -Depth 10 | ConvertFrom-Json
    $badPort.proxy_port.value = '4000x'
    $msg = Get-ThrownMessage { Resolve-LitellmStartDecision -PortOwnerPid $null -PortOwnerName '' -LitellmExe $script:FakeExe -Settings $badPort }
    Check 'proxy_port 4000x refused by name' ($msg -match 'proxy_port') "message: $msg"
} catch { Check 'proxy_port 4000x refused by name' $false $_.Exception.Message }

# ---- 5-6: child environment -------------------------------------------------------------
try {
    $script:Store = @{ 'AUGUREAI_API_KEY' = 'user-scope-value-52-characters-long-xxxxxxxxxxxx'; 'LITELLM_MASTER_KEY' = 'sk-user-master' }
    $stale = 'stale-process-value-48-characters-long-xxxxxxxxxxxx'
    $prevStale = [Environment]::GetEnvironmentVariable('AUGUREAI_API_KEY', 'Process')
    [Environment]::SetEnvironmentVariable('AUGUREAI_API_KEY', $stale, 'Process')
    try {
        $childEnv = New-LitellmChildEnvironment -Settings $Settings -Profiles $Profiles -ReadUserVar $ReadUser
    } finally {
        [Environment]::SetEnvironmentVariable('AUGUREAI_API_KEY', $prevStale, 'Process')
    }
    Check 'child env holds the User-scope key' ($childEnv['AUGUREAI_API_KEY'] -eq $script:Store['AUGUREAI_API_KEY'])
    Check 'child env does not hold the stale process value' (-not ($childEnv.Values -contains $stale))
    Check 'child env holds the master key' ($childEnv['LITELLM_MASTER_KEY'] -eq 'sk-user-master')
} catch { Check 'child environment built from User scope' $false $_.Exception.Message }

try {
    $script:Store = @{ 'LITELLM_MASTER_KEY' = 'sk-user-master' }
    $msg = Get-ThrownMessage { New-LitellmChildEnvironment -Settings $Settings -Profiles $Profiles -ReadUserVar $ReadUser }
    Check 'missing key variable refused, name given' ($msg -match 'AUGUREAI_API_KEY') "message: $msg"
} catch { Check 'missing key variable refused, name given' $false $_.Exception.Message }

# ---- 7: -DryRun -------------------------------------------------------------------------
try {
    $script:Store = @{}
    $script:WriteCount = 0
    $startup = New-StartupFolder
    $null = Install-LitellmAutostart -Settings $Settings -StartupFolder $startup -LauncherPath $FakeBat -ReadUserVar $ReadUser -WriteUserVar $WriteUser -DryRun
    Check 'dry run creates no shortcut' (@(Get-ChildItem -LiteralPath $startup -Force).Count -eq 0)
    Check 'dry run writes no variable' (($script:WriteCount -eq 0) -and ($script:Store.Count -eq 0))
} catch { Check 'dry run writes nothing' $false $_.Exception.Message }

# ---- 8-9: -Install twice, key never printed ---------------------------------------------
try {
    $script:Store = @{}
    $script:WriteCount = 0
    $startup = New-StartupFolder
    $null = Install-LitellmAutostart -Settings $Settings -StartupFolder $startup -LauncherPath $FakeBat -ReadUserVar $ReadUser -WriteUserVar $WriteUser
    $key1 = $script:Store['LITELLM_MASTER_KEY']
    $captured = Install-LitellmAutostart -Settings $Settings -StartupFolder $startup -LauncherPath $FakeBat -ReadUserVar $ReadUser -WriteUserVar $WriteUser *>&1 | Out-String
    $key2 = $script:Store['LITELLM_MASTER_KEY']
    Check 'install twice leaves one shortcut' (@(Get-ChildItem -LiteralPath $startup -Filter '*.lnk').Count -eq 1)
    Check 'install twice leaves the master key unchanged' (($key1 -eq $key2) -and ($script:WriteCount -eq 1))
    Check 'master key has sk- prefix and 43 base64url characters' ($key1 -match '^sk-[A-Za-z0-9_-]{43}$')
    Check 'master key never appears in captured output' ((-not [string]::IsNullOrEmpty($key1)) -and (-not $captured.Contains($key1)))

    $null = Uninstall-LitellmAutostart -StartupFolder $startup
    Check 'uninstall removes the shortcut only' ((@(Get-ChildItem -LiteralPath $startup -Filter '*.lnk').Count -eq 0) -and ($script:Store['LITELLM_MASTER_KEY'] -eq $key1))
} catch { Check 'install and uninstall behaviour' $false $_.Exception.Message }

# ---- 10: missing settings key -----------------------------------------------------------
try {
    $broken = $Settings | ConvertTo-Json -Depth 10 | ConvertFrom-Json
    $broken.PSObject.Properties.Remove('proxy_port')
    $msg = Get-ThrownMessage { Resolve-LitellmStartDecision -PortOwnerPid $null -PortOwnerName '' -Settings $broken }
    Check 'missing settings key refused, name given' ($msg -match 'proxy_port') "message: $msg"
} catch { Check 'missing settings key refused, name given' $false $_.Exception.Message }

# ---- 11a: exit codes (R12) and the PID reported on success ------------------------------
# Plain run through Invoke-LitellmMain with every process, network and folder effect shadowed.
# Write-Host goes to the information stream, so the captured output is read from *>&1.
function Invoke-PlainRun {
    param([hashtable]$Store, [object[]]$Probes, [int]$RenderExit = 0, [bool]$Liveness = $true)
    $script:DefaultReadUserVar = { param([string]$Name) if ($Store.ContainsKey($Name)) { $Store[$Name] } else { $null } }
    Reset-PortProbes -Answers $Probes
    $script:RenderExit = $RenderExit
    $script:LivenessAnswer = $Liveness
    $script:StartCount = 0
    $collected = @(Invoke-LitellmMain *>&1)
    $codes = @($collected | Where-Object { $_ -is [int] })
    $code = if ($codes.Count -gt 0) { $codes[-1] } else { -1 }
    $text = ($collected | Where-Object { $_ -isnot [int] } | Out-String)
    return @{ Code = $code; Text = $text; Starts = $script:StartCount }
}

try {
    $r = Invoke-PlainRun -Store @{ AUGUREAI_API_KEY = 'k-augure'; LITELLM_MASTER_KEY = 'sk-m' } -Probes @($null) -RenderExit 3
    Check 'render-config failure exits 1, not 2' ($r.Code -eq 1) "got exit $($r.Code): $($r.Text)"
} catch { Check 'render-config failure exits 1, not 2' $false $_.Exception.Message }

try {
    $r = Invoke-PlainRun -Store @{ LITELLM_MASTER_KEY = 'sk-m' } -Probes @($null)
    Check 'missing key variable still exits 2' ($r.Code -eq 2) "got exit $($r.Code): $($r.Text)"
} catch { Check 'missing key variable still exits 2' $false $_.Exception.Message }

try {
    $owner = @{ Pid = 4242; Name = 'python'; CommandLine = 'python.exe C:\venv\Scripts\litellm.exe --config x'; ParentName = '' }
    $r = Invoke-PlainRun -Store @{ AUGUREAI_API_KEY = 'k-augure'; LITELLM_MASTER_KEY = 'sk-m' } -Probes @($null, $owner)
    Check 'success line reports the port owner PID, not the wrapper' (($r.Code -eq 0) -and ($r.Text -match 'pid 4242') -and ($r.Text -notmatch 'pid 99')) "exit $($r.Code): $($r.Text)"
} catch { Check 'success line reports the port owner PID, not the wrapper' $false $_.Exception.Message }

try {
    $owner = @{ Pid = 4242; Name = 'python'; CommandLine = 'python.exe C:\venv\Scripts\litellm.exe --config x'; ParentName = '' }
    $r = Invoke-PlainRun -Store @{ AUGUREAI_API_KEY = 'k-augure'; LITELLM_MASTER_KEY = 'sk-m' } -Probes @($null, $owner) -Liveness $false
    Check 'liveness never answering is a failure, exit 1' ($r.Code -eq 1) "got exit $($r.Code)"
} catch { Check 'liveness never answering is a failure, exit 1' $false $_.Exception.Message }

# ---- 11b: owners that must be refused or accepted by the plain run (review round 2) ------
try {
    $nodeOwner = @{ Pid = 5555; Name = 'node'; CommandLine = 'node C:\dev\litellm-dashboard\server.js'; ParentPath = ''; Created = $T1; ParentCreated = $null }
    $r = Invoke-PlainRun -Store @{ AUGUREAI_API_KEY = 'k-augure'; LITELLM_MASTER_KEY = 'sk-m' } -Probes @($nodeOwner)
    Check 'plain run refuses a litellm-dashboard node owner: exit 2, nothing started' (($r.Code -eq 2) -and ($r.Starts -eq 0)) "exit $($r.Code), starts $($r.Starts): $($r.Text)"
} catch { Check 'plain run refuses a litellm-dashboard node owner: exit 2, nothing started' $false $_.Exception.Message }

try {
    $ownOwner = @{ Pid = 4321; Name = 'python'; CommandLine = $OwnCmd; ParentPath = ''; Created = $T1; ParentCreated = $null }
    $r = Invoke-PlainRun -Store @{ AUGUREAI_API_KEY = 'k-augure'; LITELLM_MASTER_KEY = 'sk-m' } -Probes @($ownOwner)
    Check 'plain run on this repo litellm owner: exit 0, nothing started' (($r.Code -eq 0) -and ($r.Starts -eq 0)) "exit $($r.Code), starts $($r.Starts): $($r.Text)"
} catch { Check 'plain run on this repo litellm owner: exit 0, nothing started' $false $_.Exception.Message }

try {
    $script:SettingsForRun = $Settings | ConvertTo-Json -Depth 10 | ConvertFrom-Json
    $script:SettingsForRun.proxy_port.value = '4000x'
    $r = Invoke-PlainRun -Store @{ AUGUREAI_API_KEY = 'k-augure'; LITELLM_MASTER_KEY = 'sk-m' } -Probes @($null)
    $script:SettingsForRun = $null
    Check 'proxy_port 4000x exits 2 and starts nothing' (($r.Code -eq 2) -and ($r.Starts -eq 0)) "exit $($r.Code), starts $($r.Starts): $($r.Text)"
} catch { $script:SettingsForRun = $null; Check 'proxy_port 4000x exits 2 and starts nothing' $false $_.Exception.Message }

# ---- 11c: -Status names the owner (review round 2) ----------------------------------------
try {
    $script:StatusAlive = $true
    $ownOwner = @{ Pid = 4321; Name = 'python'; CommandLine = $OwnCmd; ParentPath = ''; Created = $T1; ParentCreated = $null }
    Reset-PortProbes -Answers @($ownOwner)
    $statusText = (Invoke-LitellmMain -Status *>&1 | Out-String)
    Check '-Status says the owner is this LiteLLM when running' ($statusText -match 'this LiteLLM') "text: $statusText"
} catch { Check '-Status says the owner is this LiteLLM when running' $false $_.Exception.Message }

try {
    $nodeOwner = @{ Pid = 5555; Name = 'node'; CommandLine = 'node C:\dev\litellm-dashboard\server.js'; ParentPath = ''; Created = $T1; ParentCreated = $null }
    Reset-PortProbes -Answers @($nodeOwner)
    $statusText = (Invoke-LitellmMain -Status *>&1 | Out-String)
    Check '-Status says a foreign owner is NOT this LiteLLM' ($statusText -match 'NOT this LiteLLM') "text: $statusText"
} catch { Check '-Status says a foreign owner is NOT this LiteLLM' $false $_.Exception.Message }

# ---- 11: the batch file -----------------------------------------------------------------
if (Test-Path -LiteralPath $Bat -PathType Leaf) {
    $batText = Get-Content -LiteralPath $Bat -Raw
    Check 'bat runs the launcher hidden' (($batText -match 'litellm-autostart\.ps1') -and ($batText -match '-WindowStyle Hidden'))
} else {
    Check 'bat runs the launcher hidden' $false "missing $Bat"
}

# ---- 12: the real User environment was not written --------------------------------------
$RealUserKeyAfter = [Environment]::GetEnvironmentVariable('LITELLM_MASTER_KEY', 'User')
Check 'real User environment untouched' ($RealUserKeyBefore -eq $RealUserKeyAfter)

Remove-Item -LiteralPath $Tmp -Recurse -Force -ErrorAction SilentlyContinue
Finish-Verification
