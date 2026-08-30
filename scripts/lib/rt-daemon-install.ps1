<#
.SYNOPSIS
    The vault-daemon half of setup.ps1, in its own file so a test can load it.

.DESCRIPTION
    setup.ps1 -InstallDaemon (and -All, conditionally) delegates to
    .claude\skills\obsidian-cli\scripts\vault-daemon-autostart.ps1 -Install, which
    creates one shortcut in the current user's Startup folder. That write is
    irreversible from the test's point of view - it lands in the professor's own
    profile - so the decision and the delegation live here rather than inside
    setup.ps1, exactly as the -Sync engine lives in rt-sync.ps1: dot-sourcing
    setup.ps1 would run its whole interactive flow as a side effect, prompts and
    template writes included, just by being tested.

    Nothing here writes to the Startup folder itself. The one function that can
    is Install-RtVaultDaemon, and it only ever invokes the autostart script by
    path, which the test replaces with a stub.

.NOTES
    Why a login daemon needs a USER-scope OBSIDIAN_VAULT: the Startup shortcut
    points at vault-daemon-autostart.bat, which passes no -Vault, so the daemon
    reads the user environment block. A value that exists only as a setup.ps1
    argument, or only in the shell that ran setup, is invisible at login.
#>

Set-StrictMode -Version Latest

function Get-RtDaemonVault {
    <#
    .SYNOPSIS
        The vault a login-started daemon would actually see, or '' for none.
    #>
    param(
        [AllowEmptyString()][string]$ObsidianVault = "",
        [AllowEmptyString()][string]$UserScopeVault = ""
    )
    # User scope wins on purpose: it is the only one the login daemon can read.
    if (-not [string]::IsNullOrWhiteSpace($UserScopeVault)) { return $UserScopeVault }
    # setup.ps1 substitutes this literal into CLAUDE.md when the user skipped the
    # vault prompt, so it reaches this function as an ordinary string.
    if ($ObsidianVault -eq "NOT_CONFIGURED") { return "" }
    if (-not [string]::IsNullOrWhiteSpace($ObsidianVault)) { return $ObsidianVault }
    return ""
}

function Install-RtVaultDaemon {
    <#
    .SYNOPSIS
        Install the Startup entry for the vault event daemon. Returns an exit code.

    .DESCRIPTION
        0 means installed, previewed, or deliberately skipped; a non-zero code is
        the autostart script's own, or 1 when that script is missing. A missing
        vault is a SKIP and not a failure: a login daemon with no vault starts,
        finds nothing and exits invisibly, which is the failure mode this
        repository keeps legislating against, so it is refused out loud instead.
    #>
    param(
        [Parameter(Mandatory = $true)][string]$RepoRoot,
        [AllowEmptyString()][string]$Vault = "",
        [switch]$UserScopeSet,
        [switch]$Preview
    )

    $autostart = Join-Path $RepoRoot ".claude\skills\obsidian-cli\scripts\vault-daemon-autostart.ps1"

    if ([string]::IsNullOrWhiteSpace($Vault)) {
        Write-Host "  [!!]  Vault daemon skipped: no Obsidian vault configured." -ForegroundColor Yellow
        Write-Host "        Set one, then re-run:  .\setup.ps1 -InstallDaemon -ObsidianVault '<path>'"
        return 0
    }

    if (-not (Test-Path $autostart)) {
        Write-Host "  [ERR] vault-daemon-autostart.ps1 not found at: $autostart" -ForegroundColor Red
        return 1
    }

    if ($Preview) {
        Write-Host "  [--]  Would run: $autostart -Install -Vault '$Vault'"
        return 0
    }

    if (-not $UserScopeSet) {
        Write-Host "  [!!]  OBSIDIAN_VAULT is not set at USER scope. The Startup entry will be" -ForegroundColor Yellow
        Write-Host "        created, but the daemon reads the user environment block at login" -ForegroundColor Yellow
        Write-Host "        and would find nothing. Set it once:" -ForegroundColor Yellow
        Write-Host "          [Environment]::SetEnvironmentVariable('OBSIDIAN_VAULT', '$Vault', 'User')"
    }

    $global:LASTEXITCODE = 0
    & $autostart -Install -Vault $Vault
    return $LASTEXITCODE
}
