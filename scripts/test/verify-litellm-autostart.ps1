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
$script:FakePort = $null
function Get-LitellmPortOwner {
    param([int]$Port)
    return $script:FakePort
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

function New-StartupFolder {
    $folder = Join-Path $Tmp ('startup-' + [guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $folder -Force | Out-Null
    return $folder
}

# ---- 1-4: decisions ---------------------------------------------------------------------
try {
    $d = Resolve-LitellmStartDecision -PortOwnerPid $null -PortOwnerName '' -Settings $Settings
    Check 'free port gives start' ($d.Action -eq 'start') "got $($d.Action)"
} catch { Check 'free port gives start' $false $_.Exception.Message }

try {
    $d = Resolve-LitellmStartDecision -PortOwnerPid 1234 -PortOwnerName 'litellm' -Settings $Settings
    Check 'port held by litellm gives running' ($d.Action -eq 'running') "got $($d.Action)"
} catch { Check 'port held by litellm gives running' $false $_.Exception.Message }

try {
    $d = Resolve-LitellmStartDecision -PortOwnerPid 4321 -PortOwnerName 'python' -Settings $Settings
    Check 'port held by another name refused, PID named' (($d.Action -eq 'refuse') -and ($d.Reason -match '4321')) "got $($d.Action): $($d.Reason)"
} catch { Check 'port held by another name refused, PID named' $false $_.Exception.Message }

try {
    $wide = $Settings | ConvertTo-Json -Depth 10 | ConvertFrom-Json
    $wide.proxy_host.value = '0.0.0.0'
    $d = Resolve-LitellmStartDecision -PortOwnerPid $null -PortOwnerName '' -Settings $wide
    Check 'host 0.0.0.0 refused' ($d.Action -eq 'refuse') "got $($d.Action)"
} catch { Check 'host 0.0.0.0 refused' $false $_.Exception.Message }

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
