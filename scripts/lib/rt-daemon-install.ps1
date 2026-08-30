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

function Resolve-RtVaultEnvironmentAction {
    <#
    .SYNOPSIS
        Decide what to do about OBSIDIAN_VAULT at USER scope. Writes nothing.

    .DESCRIPTION
        U8 of the CLAUDE*.md consolidation plan. No installer in this repository
        used to set the variable, yet vault-access-guard.py, obsidian-outbox-flush.py,
        vault_daemon.py, run-drill.ps1 and vault-daemon-autostart.ps1 all read it,
        so a fresh machine reported a successful setup and every one of them then
        refused.

        The decision is separated from the write so it can be driven by injected
        values in the offline check: the live user environment block is never read
        here and never written here.

        Add-only, in the shape of the other global writers. A variable that already
        holds a value is REPORTED and left alone unless the operator confirms; a
        vault path that does not exist is refused rather than stored, because a
        stored path to nothing produces a daemon that starts at login, finds
        nothing and exits invisibly.

    .OUTPUTS
        A PSCustomObject with Action and Message.
          set          the variable is unset (or confirmed) and the path is valid
          keep         a value is already there and no confirmation was given
          replace      a value is already there and the operator confirmed
          no-vault     nothing to store
          missing-path the path does not exist, so it is refused
          same         the stored value already equals the requested one
    #>
    param(
        [AllowEmptyString()][string]$Vault = "",
        [AllowEmptyString()][string]$CurrentUserScope = "",
        [bool]$PathExists = $false,
        [switch]$Confirmed
    )

    if ([string]::IsNullOrWhiteSpace($Vault)) {
        return [pscustomobject]@{
            Action  = "no-vault"
            Message = "no Obsidian vault configured, nothing to store"
        }
    }

    # Validate BEFORE comparing or storing. A path that does not exist is a refusal,
    # not a value: the failure it produces surfaces at login, far from this run.
    if (-not $PathExists) {
        return [pscustomobject]@{
            Action  = "missing-path"
            Message = "refused: '$Vault' is not an existing directory"
        }
    }

    $current = if ($null -eq $CurrentUserScope) { "" } else { $CurrentUserScope }

    if ([string]::IsNullOrWhiteSpace($current)) {
        return [pscustomobject]@{
            Action  = "set"
            Message = "OBSIDIAN_VAULT is unset at USER scope, would set it to '$Vault'"
        }
    }

    if ($current -eq $Vault) {
        return [pscustomobject]@{
            Action  = "same"
            Message = "OBSIDIAN_VAULT already holds '$Vault' at USER scope"
        }
    }

    if ($Confirmed) {
        return [pscustomobject]@{
            Action  = "replace"
            Message = "confirmed: replacing '$current' with '$Vault' at USER scope"
        }
    }

    return [pscustomobject]@{
        Action  = "keep"
        Message = "OBSIDIAN_VAULT already holds '$current' at USER scope - left alone. Pass -Force to repoint it to '$Vault'"
    }
}

function Set-RtVaultEnvironment {
    <#
    .SYNOPSIS
        Apply the decision above. The ONE function here that touches the environment.

    .DESCRIPTION
        Writes at USER scope and nowhere else: the Startup shortcut passes no -Vault,
        so a login-started daemon reads the user environment block, and a value
        exported in a shell is invisible to it.

        Returns the same object it was given, so a caller can branch on Action. The
        offline check drives Resolve-RtVaultEnvironmentAction directly and never
        calls this function, which is why the two are separate.
    #>
    param(
        [Parameter(Mandatory = $true)]$Decision,
        [Parameter(Mandatory = $true)][AllowEmptyString()][string]$Vault,
        [switch]$Preview
    )

    switch ($Decision.Action) {
        "set"     { }
        "replace" { }
        default   {
            Write-Host "  [ok]  $($Decision.Message)" -ForegroundColor DarkGray
            return $Decision
        }
    }

    if ($Preview) {
        Write-Host "  [--]  Would set OBSIDIAN_VAULT='$Vault' at USER scope"
        return $Decision
    }

    [Environment]::SetEnvironmentVariable("OBSIDIAN_VAULT", $Vault, "User")

    # R9: read the state back rather than trusting the call to have taken.
    $readBack = [Environment]::GetEnvironmentVariable("OBSIDIAN_VAULT", "User")
    if ($readBack -eq $Vault) {
        Write-Host "  [OK]  OBSIDIAN_VAULT set to '$Vault' at USER scope" -ForegroundColor Green
        Write-Host "        An already-open terminal keeps its old environment block, and"
        Write-Host "        VS Code has to be restarted before a session sees the new one."
    } else {
        Write-Host "  [ERR] OBSIDIAN_VAULT did not take: read back '$readBack'" -ForegroundColor Red
    }
    return $Decision
}
