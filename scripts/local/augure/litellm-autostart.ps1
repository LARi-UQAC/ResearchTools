<#
.SYNOPSIS
    Start the local LiteLLM proxy for the AugureAI route, and manage its logon start (Issue #112, plan 3).

.DESCRIPTION
    Plain run: refuse a proxy host other than 127.0.0.1, resolve the .venv-litellm and .venv-skills
    interpreters of the MAIN clone (no PATH fallback), render the proxy config with
    augure_models.py render-config, then start litellm.exe hidden on loopback unless the port is
    already held by LiteLLM. Keys are read at USER scope and passed in the child environment only.

    -Install    create the Startup shortcut to litellm-autostart.bat (one only) and create the master
                key variable at USER scope when it is absent. The key is never overwritten or printed.
    -Uninstall  remove the Startup shortcut only.
    -Status     read-only report: shortcut, port owner, liveness answer, log tail.
    -DryRun     writes nothing and starts nothing; prints what it would do.

    Exit codes (R12), each case stated once:
      0  done, already running, or started.
      2  refusal by design: proxy_host not 127.0.0.1; proxy_port not an integer 1..65535; a settings
         or profile key missing; a key variable unset at User scope; a port held by a process that
         is not this repository's LiteLLM (its PID is named); a missing interpreter environment;
         a missing launcher for -Install.
      1  failure: render-config failed; litellm.exe missing; liveness never answered; a data file
         missing or unreadable.
    A refusal is an exception carrying Data['LitellmRefusal'], created by New-LitellmRefusal.

    Dot-sourcing: set RT_LITELLM_NO_MAIN=1 before dot-sourcing and only the functions are defined.
    The verifier scripts\test\verify-litellm-autostart.ps1 does this.

.NOTES
    Every number, path and variable name comes from augure-settings.json and augure-profiles.json,
    each value as {value, provenance} (R0, R3, R4). Only variable NAMES are stored there.
#>
[CmdletBinding()]
param(
    [switch]$Install,
    [switch]$Uninstall,
    [switch]$Status,
    [switch]$DryRun
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$script:LitellmDir = $PSScriptRoot
$script:LitellmRepo = Split-Path (Split-Path (Split-Path $script:LitellmDir -Parent) -Parent) -Parent
$script:LitellmShortcutName = 'ResearchTools LiteLLM proxy.lnk'
$script:LitellmBatName = 'litellm-autostart.bat'

. (Join-Path $script:LitellmRepo 'scripts\lib\rt-venv.ps1')

function New-LitellmRefusal {
    <#
    .SYNOPSIS
        Build the exception of a refusal by design, so the entry point exits 2 (R12).

    .PARAMETER Message
        The named cause shown to the operator.

    .OUTPUTS
        System.Exception carrying Data['LitellmRefusal'] = $true. Caller throws it.
    #>
    param([Parameter(Mandatory = $true)][string]$Message)
    $ex = New-Object System.InvalidOperationException $Message
    $ex.Data['LitellmRefusal'] = $true
    return $ex
}

function Get-LitellmSettingValue {
    <#
    .SYNOPSIS
        Return the value of a {value, provenance} entry, refusing a missing or unsourced one (R3, R4).

    .PARAMETER Doc
        A parsed data file (PSCustomObject) or a sub-object of it.

    .PARAMETER Key
        The key to read.

    .PARAMETER FileName
        The data file name, quoted in every refusal.

    .OUTPUTS
        The entry's value. Throws a RuntimeException naming the key and the file when refused.
    #>
    param(
        [Parameter(Mandatory = $true)][object]$Doc,
        [Parameter(Mandatory = $true)][string]$Key,
        [string]$FileName = 'augure-settings.json'
    )
    $prop = $Doc.PSObject.Properties[$Key]
    if ($null -eq $prop) { throw (New-LitellmRefusal "'$Key' is missing from $FileName") }
    $entry = $prop.Value
    if ($null -eq $entry -or $null -eq $entry.PSObject.Properties['value']) {
        throw (New-LitellmRefusal "'$Key' in $FileName must be an object with a 'value'")
    }
    $prov = $entry.PSObject.Properties['provenance']
    if ($null -eq $prov -or [string]::IsNullOrWhiteSpace([string]$prov.Value)) {
        throw (New-LitellmRefusal "'$Key' in $FileName has no provenance (R4)")
    }
    return $entry.value
}

function Get-LitellmPort {
    <#
    .SYNOPSIS
        Return proxy_port as an integer 1..65535, refusing anything else (R12: a bad value is exit 2).

    .PARAMETER Settings
        The parsed augure-settings.json.

    .OUTPUTS
        int. Throws a refusal naming proxy_port when the value is not an integer in range.
    #>
    param([Parameter(Mandatory = $true)][object]$Settings)
    $text = [string](Get-LitellmSettingValue -Doc $Settings -Key 'proxy_port')
    $n = 0
    if (($text -notmatch '^\d{1,5}$') -or (-not [int]::TryParse($text, [ref]$n)) -or ($n -lt 1) -or ($n -gt 65535)) {
        throw (New-LitellmRefusal "'proxy_port' in augure-settings.json must be an integer 1..65535 (got '$text')")
    }
    return $n
}

function Test-LitellmOwnership {
    <#
    .SYNOPSIS
        Tell whether a port owner is this repository's LiteLLM proxy, by its command line or by its parent.

    .PARAMETER CommandLine
        The owner's command line ('' when unknown).

    .PARAMETER Created
        The owner's creation time, or $null when unknown.

    .PARAMETER ParentPath
        The executable path of the owner's parent ('' when unknown).

    .PARAMETER ParentCreated
        The parent's creation time, or $null when unknown.

    .PARAMETER LitellmExe
        The full path of this repository's .venv-litellm litellm.exe ('' when unknown).

    .OUTPUTS
        hashtable with Owned (bool) and Via ('command line', 'parent' or '').
        A command line counts when it runs LitellmExe as a whole path. A parent counts when its path
        is LitellmExe exactly and it was created no later than the owner (a reused parent PID fails).
    #>
    param(
        [AllowEmptyString()][string]$CommandLine = '',
        $Created = $null,
        [AllowEmptyString()][string]$ParentPath = '',
        $ParentCreated = $null,
        [AllowEmptyString()][string]$LitellmExe = ''
    )
    if ([string]::IsNullOrEmpty($LitellmExe)) { return @{ Owned = $false; Via = '' } }
    $exe = [IO.Path]::GetFullPath($LitellmExe)
    $pattern = '(?i)' + [regex]::Escape($exe) + '(?=["\s]|$)'
    if ($CommandLine -match $pattern) { return @{ Owned = $true; Via = 'command line' } }
    if (-not [string]::IsNullOrEmpty($ParentPath)) {
        $parentFull = [IO.Path]::GetFullPath($ParentPath)
        if (($parentFull -ieq $exe) -and ($null -ne $Created) -and ($null -ne $ParentCreated) -and ([datetime]$ParentCreated -le [datetime]$Created)) {
            return @{ Owned = $true; Via = 'parent' }
        }
    }
    return @{ Owned = $false; Via = '' }
}

function Read-LitellmJson {
    <#
    .SYNOPSIS
        Read a data file as a PSCustomObject.

    .PARAMETER Path
        The file to read (UTF-8).

    .OUTPUTS
        PSCustomObject. Throws when the file is missing or not JSON.
    #>
    param([Parameter(Mandatory = $true)][string]$Path)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { throw "data file missing: $Path" }
    return (Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json)
}

function Expand-LitellmHome {
    <#
    .SYNOPSIS
        Expand a leading ~ to the user profile folder.

    .PARAMETER Text
        A path, possibly starting with ~/ or ~\.

    .OUTPUTS
        string, not resolved.
    #>
    param([Parameter(Mandatory = $true)][string]$Text)
    $home_ = [Environment]::GetFolderPath('UserProfile')
    if ($Text -eq '~') { return $home_ }
    if ($Text.StartsWith('~/') -or $Text.StartsWith('~\')) { return (Join-Path $home_ $Text.Substring(2)) }
    return $Text
}

function New-LitellmMasterKey {
    <#
    .SYNOPSIS
        Create a new proxy master key: sk- followed by 32 random bytes in base64url.

    .OUTPUTS
        string. The caller stores it; it is never printed.
    #>
    $bytes = New-Object byte[] 32
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try { $rng.GetBytes($bytes) } finally { $rng.Dispose() }
    $b64 = [Convert]::ToBase64String($bytes).TrimEnd('=').Replace('+', '-').Replace('/', '_')
    return ('sk-' + $b64)
}

function Resolve-LitellmStartDecision {
    <#
    .SYNOPSIS
        Decide what a plain run does with the port, without touching the system.

    .PARAMETER PortOwnerPid
        PID of the process listening on the proxy port, or $null when the port is free.

    .PARAMETER PortOwnerName
        Process name of that listener (for example litellm or python).

    .PARAMETER Settings
        The parsed augure-settings.json.

    .OUTPUTS
        hashtable with Action (start, running or refuse) and Reason (text for the operator).
        Throws when a settings key needed for the decision is missing.
    #>
    param(
        $PortOwnerPid,
        [AllowEmptyString()][string]$PortOwnerName = '',
        [AllowEmptyString()][string]$PortOwnerCommandLine = '',
        $PortOwnerCreated = $null,
        [AllowEmptyString()][string]$PortOwnerParentPath = '',
        $PortOwnerParentCreated = $null,
        [AllowEmptyString()][string]$LitellmExe = '',
        [Parameter(Mandatory = $true)][object]$Settings
    )
    $proxyHost = Get-LitellmSettingValue -Doc $Settings -Key 'proxy_host'
    $port = Get-LitellmPort -Settings $Settings
    if ($proxyHost -ne '127.0.0.1') {
        return @{ Action = 'refuse'; Reason = "proxy_host is '$proxyHost' in augure-settings.json; only 127.0.0.1 is allowed (loopback only)" }
    }
    if ($null -eq $PortOwnerPid) {
        return @{ Action = 'start'; Reason = "port $port is free" }
    }
    # litellm.exe is a pip launcher: the socket belongs to the python it starts. That python is
    # LiteLLM only when it runs this repository's litellm.exe, or its parent is that exact file and
    # was created no later than it (a reused parent PID is refused). A name or a word is not proof.
    $own = Test-LitellmOwnership -CommandLine $PortOwnerCommandLine -Created $PortOwnerCreated -ParentPath $PortOwnerParentPath -ParentCreated $PortOwnerParentCreated -LitellmExe $LitellmExe
    if ($own.Owned) {
        return @{ Action = 'running'; Reason = "LiteLLM already holds port $port (PID $PortOwnerPid, matched by its $($own.Via))" }
    }
    return @{ Action = 'refuse'; Reason = "port $port is held by '$PortOwnerName' (PID $PortOwnerPid), not LiteLLM; refusing to start a second listener" }
}

function Get-LitellmPortOwner {
    <#
    .SYNOPSIS
        Find the process listening on a TCP port.

    .PARAMETER Port
        The port number.

    .OUTPUTS
        hashtable with Pid and Name, or $null when nothing listens.
    #>
    param([Parameter(Mandatory = $true)][int]$Port)
    $conn = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($null -eq $conn) { return $null }
    $ownerPid = [int]$conn.OwningProcess
    $proc = Get-Process -Id $ownerPid -ErrorAction SilentlyContinue
    $name = ''
    if ($null -ne $proc) { $name = [string]$proc.ProcessName }
    # The command line, the creation times and the parent's path tell a LiteLLM python from another.
    $cmdLine = ''
    $created = $null
    $parentPath = ''
    $parentCreated = $null
    $cim = Get-CimInstance -ClassName Win32_Process -Filter "ProcessId = $ownerPid" -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($null -ne $cim) {
        $cmdLine = [string]$cim.CommandLine
        $created = $cim.CreationDate
        $parent = Get-CimInstance -ClassName Win32_Process -Filter "ProcessId = $([int]$cim.ParentProcessId)" -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($null -ne $parent) {
            $parentPath = [string]$parent.ExecutablePath
            $parentCreated = $parent.CreationDate
        }
    }
    return @{ Pid = $ownerPid; Name = $name; CommandLine = $cmdLine; Created = $created; ParentPath = $parentPath; ParentCreated = $parentCreated }
}

function Get-LitellmDecisionFromOwner {
    <#
    .SYNOPSIS
        Apply Resolve-LitellmStartDecision to the owner record of Get-LitellmPortOwner (or to a free port).

    .PARAMETER Owner
        The owner hashtable, or $null when the port is free.

    .PARAMETER LitellmExe
        The full path of this repository's litellm.exe.

    .PARAMETER Settings
        The parsed augure-settings.json.

    .OUTPUTS
        The decision hashtable (Action, Reason).
    #>
    param($Owner, [string]$LitellmExe, [Parameter(Mandatory = $true)][object]$Settings)
    if ($null -eq $Owner) {
        return (Resolve-LitellmStartDecision -PortOwnerPid $null -LitellmExe $LitellmExe -Settings $Settings)
    }
    return (Resolve-LitellmStartDecision -PortOwnerPid $Owner.Pid -PortOwnerName $Owner.Name -PortOwnerCommandLine $Owner.CommandLine -PortOwnerCreated $Owner.Created -PortOwnerParentPath $Owner.ParentPath -PortOwnerParentCreated $Owner.ParentCreated -LitellmExe $LitellmExe -Settings $Settings)
}

function New-LitellmChildEnvironment {
    <#
    .SYNOPSIS
        Build the environment of the proxy child: the key variables, read at USER scope only.

    .PARAMETER Settings
        The parsed augure-settings.json (names master_key_env).

    .PARAMETER Profiles
        The parsed augure-profiles.json (names each profile's api_key_env).

    .PARAMETER ReadUserVar
        Scriptblock taking a variable name and returning its User-scope value or $null.

    .OUTPUTS
        hashtable of name to value. Throws naming the variable when one is unset or empty.
    #>
    param(
        [Parameter(Mandatory = $true)][object]$Settings,
        [Parameter(Mandatory = $true)][object]$Profiles,
        [Parameter(Mandatory = $true)][scriptblock]$ReadUserVar
    )
    $names = New-Object System.Collections.Generic.List[string]
    foreach ($p in $Profiles.profiles.PSObject.Properties) {
        $apiVar = Get-LitellmSettingValue -Doc $p.Value -Key 'api_key_env' -FileName 'augure-profiles.json'
        if (-not $names.Contains([string]$apiVar)) { $names.Add([string]$apiVar) }
    }
    $masterVar = [string](Get-LitellmSettingValue -Doc $Settings -Key 'master_key_env')
    if (-not $names.Contains($masterVar)) { $names.Add($masterVar) }

    $childEnv = @{}
    foreach ($name in $names) {
        $value = & $ReadUserVar $name
        if ([string]::IsNullOrEmpty([string]$value)) {
            throw (New-LitellmRefusal "$name is not set at the User scope; the proxy cannot start without it (set it, or run litellm-autostart.ps1 -Install for the master key)")
        }
        $childEnv[$name] = [string]$value
    }
    return $childEnv
}

function New-LitellmShortcut {
    <#
    .SYNOPSIS
        Create a Windows shortcut through WScript.Shell, minimised, pointing at the launcher.

    .PARAMETER Path
        The .lnk file to write.

    .PARAMETER Target
        The file the shortcut runs (litellm-autostart.bat).

    .PARAMETER WorkingDirectory
        The folder the shortcut starts in.

    .PARAMETER Description
        The shortcut description.

    .OUTPUTS
        None. Side effect: writes the .lnk file.
    #>
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Target,
        [Parameter(Mandatory = $true)][string]$WorkingDirectory,
        [string]$Description = 'Start the ResearchTools LiteLLM proxy for AugureAI'
    )
    $shell = New-Object -ComObject WScript.Shell
    $link = $shell.CreateShortcut($Path)
    $link.TargetPath = $Target
    $link.WorkingDirectory = $WorkingDirectory
    $link.Description = $Description
    $link.WindowStyle = 7
    $link.Save()
}

function Install-LitellmAutostart {
    <#
    .SYNOPSIS
        Install the logon start: the Startup shortcut (one) and the master key (created only when absent).

    .PARAMETER Settings
        The parsed augure-settings.json (names master_key_env).

    .PARAMETER StartupFolder
        The folder that holds logon shortcuts (the Startup folder, or a test folder).

    .PARAMETER LauncherPath
        The litellm-autostart.bat the shortcut runs.

    .PARAMETER ReadUserVar
        Scriptblock reading a User-scope variable by name.

    .PARAMETER WriteUserVar
        Scriptblock writing a User-scope variable: name, value.

    .PARAMETER DryRun
        Report what would be done and write nothing.

    .OUTPUTS
        hashtable with ShortcutPath and KeyAction (present, created or would-create). Never the key.
        Throws when the launcher is missing or a settings key is absent.
    #>
    param(
        [Parameter(Mandatory = $true)][object]$Settings,
        [Parameter(Mandatory = $true)][string]$StartupFolder,
        [Parameter(Mandatory = $true)][string]$LauncherPath,
        [Parameter(Mandatory = $true)][scriptblock]$ReadUserVar,
        [Parameter(Mandatory = $true)][scriptblock]$WriteUserVar,
        [switch]$DryRun
    )
    if (-not (Test-Path -LiteralPath $LauncherPath -PathType Leaf)) { throw (New-LitellmRefusal "launcher missing: $LauncherPath") }
    $keyVar = [string](Get-LitellmSettingValue -Doc $Settings -Key 'master_key_env')
    $shortcut = Join-Path $StartupFolder $script:LitellmShortcutName

    $existing = & $ReadUserVar $keyVar
    if (-not [string]::IsNullOrEmpty([string]$existing)) {
        $keyAction = 'present'
    } elseif ($DryRun) {
        $keyAction = 'would-create'
    } else {
        & $WriteUserVar $keyVar (New-LitellmMasterKey)
        $keyAction = 'created'
    }
    Write-Host "  master key $keyVar : $keyAction (the value is never printed)"

    if (Test-Path -LiteralPath $shortcut) {
        Write-Host "  shortcut already present: $shortcut"
    } elseif ($DryRun) {
        Write-Host "  would create shortcut: $shortcut"
    } else {
        New-LitellmShortcut -Path $shortcut -Target $LauncherPath -WorkingDirectory (Split-Path $LauncherPath -Parent)
        Write-Host "  created shortcut: $shortcut"
    }
    return @{ ShortcutPath = $shortcut; KeyAction = $keyAction }
}

function Uninstall-LitellmAutostart {
    <#
    .SYNOPSIS
        Remove the logon shortcut only. A running proxy is left alone.

    .PARAMETER StartupFolder
        The folder that holds the shortcut.

    .OUTPUTS
        hashtable with Removed (bool) and ShortcutPath.
    #>
    param([Parameter(Mandatory = $true)][string]$StartupFolder)
    $shortcut = Join-Path $StartupFolder $script:LitellmShortcutName
    if (Test-Path -LiteralPath $shortcut) {
        Remove-Item -LiteralPath $shortcut -Force
        Write-Host "  removed $shortcut"
        return @{ Removed = $true; ShortcutPath = $shortcut }
    }
    Write-Host "  nothing to remove: no shortcut at $shortcut"
    return @{ Removed = $false; ShortcutPath = $shortcut }
}

function Start-LitellmProcess {
    <#
    .SYNOPSIS
        Start litellm.exe hidden through cmd, with its output appended to the log.

    .PARAMETER ExePath
        Full path of litellm.exe.

    .PARAMETER Arguments
        The argument string (config, host, port).

    .PARAMETER Environment
        The child environment (keys); set on the ProcessStartInfo, never on the command line.

    .PARAMETER LogPath
        The log file the child's stdout and stderr are appended to.

    .OUTPUTS
        System.Diagnostics.Process.
    #>
    param(
        [Parameter(Mandatory = $true)][string]$ExePath,
        [Parameter(Mandatory = $true)][string]$Arguments,
        [Parameter(Mandatory = $true)][hashtable]$Environment,
        [Parameter(Mandatory = $true)][string]$LogPath
    )
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $env:ComSpec
    $psi.Arguments = '/d /c ""' + $ExePath + '" ' + $Arguments + ' >> "' + $LogPath + '" 2>&1"'
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $true
    foreach ($k in $Environment.Keys) { $psi.EnvironmentVariables[$k] = [string]$Environment[$k] }
    return [System.Diagnostics.Process]::Start($psi)
}

function Wait-LitellmLiveness {
    <#
    .SYNOPSIS
        Poll the liveness route until it answers 200 or the total timeout passes.

    .PARAMETER Url
        The liveness URL.

    .PARAMETER TotalTimeoutSec
        Seconds to keep polling in all.

    .PARAMETER RequestTimeoutSec
        Seconds allowed for one request.

    .OUTPUTS
        bool: true when the route answered 200.
    #>
    param(
        [Parameter(Mandatory = $true)][string]$Url,
        [Parameter(Mandatory = $true)][int]$TotalTimeoutSec,
        [Parameter(Mandatory = $true)][int]$RequestTimeoutSec
    )
    $deadline = (Get-Date).AddSeconds($TotalTimeoutSec)
    do {
        try {
            $r = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec $RequestTimeoutSec
            if ($r.StatusCode -eq 200) { return $true }
        } catch {
            # Not up yet: keep polling until the deadline.
        }
        Start-Sleep -Seconds 2
    } while ((Get-Date) -lt $deadline)
    return $false
}

function Invoke-LitellmRenderConfig {
    <#
    .SYNOPSIS
        Run augure_models.py render-config with the .venv-skills interpreter and return its exit code.

    .PARAMETER Python
        The .venv-skills python.exe.

    .PARAMETER ModelsPy
        The augure_models.py script.

    .PARAMETER CfgPath
        The proxy config file to write.

    .PARAMETER DryRun
        Pass --dry-run through.

    .OUTPUTS
        int: the exit code of render-config. Its stdout goes to the host, not the pipeline.
    #>
    param(
        [Parameter(Mandatory = $true)][string]$Python,
        [Parameter(Mandatory = $true)][string]$ModelsPy,
        [Parameter(Mandatory = $true)][string]$CfgPath,
        [switch]$DryRun
    )
    $renderArgs = @($ModelsPy, 'render-config', '--out', $CfgPath)
    if ($DryRun) { $renderArgs += '--dry-run' }
    & $Python @renderArgs | Out-Host
    return $LASTEXITCODE
}

function Initialize-LitellmLogFolder {
    <#
    .SYNOPSIS
        Create the folder that holds the proxy log.

    .PARAMETER LogPath
        The log file whose parent folder is created.

    .OUTPUTS
        None. Side effect: creates the folder when absent.
    #>
    param([Parameter(Mandatory = $true)][string]$LogPath)
    New-Item -ItemType Directory -Path (Split-Path $LogPath -Parent) -Force | Out-Null
}

function Invoke-LitellmLogRotation {
    <#
    .SYNOPSIS
        Rotate the log once, keeping one .1 copy, when it exceeds the configured size.

    .PARAMETER LogPath
        The log file.

    .PARAMETER MaxBytes
        The size above which the log is rotated.

    .OUTPUTS
        None. Side effect: may move the log to <log>.1.
    #>
    param([Parameter(Mandatory = $true)][string]$LogPath, [Parameter(Mandatory = $true)][long]$MaxBytes)
    if ((Test-Path -LiteralPath $LogPath) -and ((Get-Item -LiteralPath $LogPath).Length -gt $MaxBytes)) {
        Move-Item -LiteralPath $LogPath -Destination ($LogPath + '.1') -Force
        Write-Host "  rotated the log at $MaxBytes bytes to $LogPath.1"
    }
}

function Show-LitellmStatus {
    <#
    .SYNOPSIS
        Print a read-only report: shortcut, port owner, liveness and the log tail.

    .PARAMETER Settings
        The parsed augure-settings.json.

    .PARAMETER StartupFolder
        The folder that holds the shortcut.

    .OUTPUTS
        None. Writes to the host only.
    #>
    param([Parameter(Mandatory = $true)][object]$Settings, [Parameter(Mandatory = $true)][string]$StartupFolder)
    $port = Get-LitellmPort -Settings $Settings
    $proxyHost = [string](Get-LitellmSettingValue -Doc $Settings -Key 'proxy_host')
    $liveness = [string](Get-LitellmSettingValue -Doc $Settings -Key 'liveness_path')
    $timeout = [int](Get-LitellmSettingValue -Doc $Settings -Key 'http_timeout_s')
    $logPath = Expand-LitellmHome (Get-LitellmSettingValue -Doc $Settings -Key 'log_path')
    $shortcut = Join-Path $StartupFolder $script:LitellmShortcutName

    Write-Host "=== LiteLLM proxy ==="
    if (Test-Path -LiteralPath $shortcut) { Write-Host "  at login  : installed ($shortcut)" }
    else { Write-Host "  at login  : not installed; run with -Install" }
    $litellmExe = ''
    $litellmPy = Resolve-RtVenvPython -RepoRoot $script:LitellmRepo -VenvName '.venv-litellm'
    if ($null -ne $litellmPy.Python) { $litellmExe = Join-Path (Split-Path $litellmPy.Python -Parent) 'litellm.exe' }
    $owner = Get-LitellmPortOwner -Port $port
    if ($null -eq $owner) { Write-Host "  port $port : free" }
    else {
        $verdict = Get-LitellmDecisionFromOwner -Owner $owner -LitellmExe $litellmExe -Settings $Settings
        $who = if ($verdict.Action -eq 'running') { 'this LiteLLM' } else { 'NOT this LiteLLM (a plain run refuses it)' }
        Write-Host "  port $port : held by '$($owner.Name)' (PID $($owner.Pid)): $who"
    }
    $ok = $false
    try {
        $r = Invoke-WebRequest -Uri ("http://{0}:{1}{2}" -f $proxyHost, $port, $liveness) -UseBasicParsing -TimeoutSec $timeout
        $ok = ($r.StatusCode -eq 200)
    } catch { $ok = $false }
    if ($ok) { Write-Host "  liveness  : answering" } else { Write-Host "  liveness  : not answering" }
    if (Test-Path -LiteralPath $logPath) {
        Write-Host "  log tail  :"
        Get-Content -LiteralPath $logPath -Tail 5 | ForEach-Object { Write-Host "    $_" }
    } else {
        Write-Host "  log       : none yet at $logPath"
    }
}

function Start-LitellmProxy {
    <#
    .SYNOPSIS
        The plain run: render the config, check the port, start the proxy and wait for liveness.

    .PARAMETER Settings
        The parsed augure-settings.json.

    .PARAMETER Profiles
        The parsed augure-profiles.json.

    .PARAMETER DryRun
        Print what would be done; write nothing and start nothing.

    .OUTPUTS
        int: 0 started or running, 2 refusal, 1 failure (R12). Throws on a refusal, which the caller maps to 2.
    #>
    param(
        [Parameter(Mandatory = $true)][object]$Settings,
        [Parameter(Mandatory = $true)][object]$Profiles,
        [switch]$DryRun
    )
    $port = Get-LitellmPort -Settings $Settings
    $proxyHost = [string](Get-LitellmSettingValue -Doc $Settings -Key 'proxy_host')
    $liveness = [string](Get-LitellmSettingValue -Doc $Settings -Key 'liveness_path')
    $startTimeout = [int](Get-LitellmSettingValue -Doc $Settings -Key 'proxy_start_timeout_s')
    $reqTimeout = [int](Get-LitellmSettingValue -Doc $Settings -Key 'http_timeout_s')
    $cfgPath = Expand-LitellmHome (Get-LitellmSettingValue -Doc $Settings -Key 'config_path')
    $logPath = Expand-LitellmHome (Get-LitellmSettingValue -Doc $Settings -Key 'log_path')
    $logMax = [long](Get-LitellmSettingValue -Doc $Settings -Key 'log_max_bytes')

    $litellmPy = Resolve-RtVenvPython -RepoRoot $script:LitellmRepo -VenvName '.venv-litellm'
    if ($null -eq $litellmPy.Python) { throw (New-LitellmRefusal $litellmPy.Message) }
    $exe = Join-Path (Split-Path $litellmPy.Python -Parent) 'litellm.exe'

    $owner = Get-LitellmPortOwner -Port $port
    $decision = Get-LitellmDecisionFromOwner -Owner $owner -LitellmExe $exe -Settings $Settings
    if ($decision.Action -eq 'refuse') { Write-Host "  STOP  $($decision.Reason)"; return 2 }
    if ($decision.Action -eq 'running') { Write-Host "  $($decision.Reason). Nothing to do."; return 0 }

    $skills = Resolve-RtVenvPython -RepoRoot $script:LitellmRepo -VenvName '.venv-skills'
    if ($null -eq $skills.Python) { throw (New-LitellmRefusal $skills.Message) }

    $modelsPy = Join-Path $script:LitellmDir 'augure_models.py'
    $renderCode = Invoke-LitellmRenderConfig -Python $skills.Python -ModelsPy $modelsPy -CfgPath $cfgPath -DryRun:$DryRun
    if ($renderCode -ne 0) { throw "render-config failed (exit $renderCode); see the [AUGURE] line above" }

    $childEnv = New-LitellmChildEnvironment -Settings $Settings -Profiles $Profiles -ReadUserVar $script:DefaultReadUserVar
    $exeDir = Split-Path $exe -Parent
    if (-not (Test-Path -LiteralPath $exe -PathType Leaf)) {
        throw "litellm.exe missing in $exeDir; rebuild the environment with setup.ps1 -InstallPython"
    }
    $arguments = "--config `"$cfgPath`" --host $proxyHost --port $port"
    if ($DryRun) {
        Write-Host "  would start: $exe $arguments"
        Write-Host "  would append output to $logPath"
        return 0
    }

    Initialize-LitellmLogFolder -LogPath $logPath
    Invoke-LitellmLogRotation -LogPath $logPath -MaxBytes $logMax
    # The process started here is the cmd.exe wrapper; the port owner is read again after liveness.
    $null = Start-LitellmProcess -ExePath $exe -Arguments $arguments -Environment $childEnv -LogPath $logPath
    $url = "http://{0}:{1}{2}" -f $proxyHost, $port, $liveness
    if (Wait-LitellmLiveness -Url $url -TotalTimeoutSec $startTimeout -RequestTimeoutSec $reqTimeout) {
        $after = Get-LitellmPortOwner -Port $port
        $listenerPid = 'unknown'
        if ($null -ne $after) { $listenerPid = $after.Pid }
        Write-Host "  LiteLLM started, port owner pid $listenerPid, liveness answering at $url"
        return 0
    }
    Write-Host "  LiteLLM did not answer $url within $startTimeout s; read $logPath"
    return 1
}

$script:DefaultReadUserVar = { param([string]$Name) [Environment]::GetEnvironmentVariable($Name, 'User') }

function Invoke-LitellmMain {
    <#
    .SYNOPSIS
        Entry point of the launcher: dispatch -Install, -Uninstall, -Status or the plain run.

    .PARAMETER Install
        Install the logon start.

    .PARAMETER Uninstall
        Remove the logon shortcut.

    .PARAMETER Status
        Print the read-only report.

    .PARAMETER DryRun
        Write and start nothing.

    .OUTPUTS
        int: 0 done, 2 refusal, 1 failure (R12).
    #>
    param([switch]$Install, [switch]$Uninstall, [switch]$Status, [switch]$DryRun)
    try {
        $settings = Read-LitellmJson (Join-Path $script:LitellmDir 'augure-settings.json')
        $profiles = Read-LitellmJson (Join-Path $script:LitellmDir 'augure-profiles.json')
        $startup = [Environment]::GetFolderPath('Startup')
        $launcher = Join-Path $script:LitellmDir $script:LitellmBatName

        if ($Status) { Show-LitellmStatus -Settings $settings -StartupFolder $startup; return 0 }
        if ($Uninstall) { $null = Uninstall-LitellmAutostart -StartupFolder $startup; return 0 }
        if ($Install) {
            $null = Install-LitellmAutostart -Settings $settings -StartupFolder $startup -LauncherPath $launcher -ReadUserVar $script:DefaultReadUserVar -WriteUserVar { param([string]$Name, [string]$Value) [Environment]::SetEnvironmentVariable($Name, $Value, 'User') } -DryRun:$DryRun
            return 0
        }
        return (Start-LitellmProxy -Settings $settings -Profiles $profiles -DryRun:$DryRun)
    } catch {
        Write-Host "  STOP  $($_.Exception.Message)"
        if ($_.Exception.Data.Contains('LitellmRefusal')) { return 2 }
        return 1
    }
}

if ($env:RT_LITELLM_NO_MAIN -ne '1') {
    exit (Invoke-LitellmMain -Install:$Install -Uninstall:$Uninstall -Status:$Status -DryRun:$DryRun)
}
