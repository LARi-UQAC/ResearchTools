<#
.SYNOPSIS
    The PATH half of setup.ps1 for aider-setup, in its own file so a test can load it.

.DESCRIPTION
    The aider-setup commands run in place from the ResearchTools clone, so nothing is installed or copied.
    What a student needs is the clone's scripts folder on the USER Path, to type aider-night.bat or
    aider-plan.ps1 from any folder. That folder differs for every student (it is wherever they cloned the
    repository), which is why the value comes from the clone that runs setup.ps1 and is never written in a file.

    The decision is pure. The only write is Install-RtAiderPath's call to the writer, and a test replaces the
    reader and the writer, so the real user Path is never opened for writing by a check. Dot-sourcing setup.ps1
    to test it would run its interactive flow as a side effect (the reason rt-daemon-install.ps1 exists too).

    Add-only: existing entries keep their order and are never removed, as with the other user-scope variables
    setup.ps1 sets. The new value is read back after the write (R9).
#>

Set-StrictMode -Version Latest

function Get-RtAiderScriptsDir {
    <#
    .SYNOPSIS
        The scripts folder of aider-setup in the given clone.
    #>
    param([Parameter(Mandatory = $true)][string]$RepoRoot)
    return (Join-Path $RepoRoot ".claude\skills\aider-setup\scripts")
}

function Resolve-RtAiderPathAction {
    <#
    .SYNOPSIS
        What to do with the user Path: add the folder, report it is already there, or refuse a missing folder.

    .OUTPUTS
        Hashtable with Action ('add', 'already' or 'missing') and NewPath (the Path to store).
    #>
    param(
        [Parameter(Mandatory = $true)][string]$Dir,
        [AllowEmptyString()][string]$CurrentUserPath = "",
        [Parameter(Mandatory = $true)][bool]$DirExists
    )
    if (-not $DirExists) { return @{ Action = "missing"; NewPath = $CurrentUserPath } }

    $wanted = $Dir.TrimEnd('\').ToLowerInvariant()
    $entries = @($CurrentUserPath -split ';' | Where-Object { $_ -ne "" })
    foreach ($entry in $entries) {
        if ($entry.TrimEnd('\').ToLowerInvariant() -eq $wanted) {
            return @{ Action = "already"; NewPath = $CurrentUserPath }
        }
    }
    $new = if ($entries.Count -eq 0) { $Dir } else { ($entries -join ';') + ';' + $Dir }
    return @{ Action = "add"; NewPath = $new }
}

function Install-RtAiderPath {
    <#
    .SYNOPSIS
        Put the clone's aider-setup scripts folder on the user Path. Returns an exit code.

    .DESCRIPTION
        0 done, already there, or previewed. 1 when the folder does not exist in this clone or when the stored
        value does not hold the folder after the write. Reader and Writer default to the user environment block
        and exist so that a test never touches it.
    #>
    param(
        [Parameter(Mandatory = $true)][string]$RepoRoot,
        [switch]$Preview,
        [scriptblock]$Reader = { [Environment]::GetEnvironmentVariable("Path", "User") },
        [scriptblock]$Writer = { param($value) [Environment]::SetEnvironmentVariable("Path", $value, "User") }
    )
    $dir = Get-RtAiderScriptsDir -RepoRoot $RepoRoot
    $current = & $Reader
    if ($null -eq $current) { $current = "" }
    $decision = Resolve-RtAiderPathAction -Dir $dir -CurrentUserPath $current -DirExists (Test-Path -LiteralPath $dir -PathType Container)

    switch ($decision.Action) {
        "missing" {
            Write-Host "  [FAIL] $dir does not exist: this clone has no aider-setup scripts folder." -ForegroundColor Red
            return 1
        }
        "already" {
            Write-Host "  [OK]   the aider-setup scripts folder is already on your user Path." -ForegroundColor DarkGray
            return 0
        }
    }
    if ($Preview) {
        Write-Host "  [PREVIEW] would add to your user Path: $dir" -ForegroundColor Magenta
        return 0
    }
    & $Writer $decision.NewPath
    $after = & $Reader
    if ($null -eq $after -or -not $after.Contains($dir)) {
        Write-Host "  [FAIL] the user Path was written but does not hold $dir." -ForegroundColor Red
        return 1
    }
    Write-Host "  [ADDED] $dir is on your user Path. Open a new terminal to use it." -ForegroundColor Green
    return 0
}
