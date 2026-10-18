# rt-update.ps1 - the pure half of `setup.ps1 -Update`.
#
# Dot-sourced by setup.ps1 and by scripts\test\verify-setup-writes.ps1. It holds the decisions
# (which profiles exist, which one an answer chooses, which steps run in which order and with
# which flags) and executes nothing, for the reason rt-global-config.ps1 and rt-sync.ps1 are
# separate files: a test can prove the order and the flags without running an installer, and
# without writing to the real ~/.claude.

function Get-RtProfileNames {
    <#
        --------------------------------------------------------------------------
        Purpose:
            List the domain profiles a clone offers: one per profiles\<name>.yaml.

        Inputs:
            ProfilesDir (string): the profiles folder of the repository

        Outputs:
            names (string[]): the file names without extension, sorted; empty when
            the folder is absent
        --------------------------------------------------------------------------
    #>
    param([Parameter(Mandatory = $true)][string]$ProfilesDir)
    if (-not (Test-Path -LiteralPath $ProfilesDir -PathType Container)) { return ,@() }
    $names = @(Get-ChildItem -LiteralPath $ProfilesDir -Filter "*.yaml" -File |
        ForEach-Object { $_.BaseName } | Sort-Object)
    return ,$names
}

function Get-RtActiveProfile {
    <#
        --------------------------------------------------------------------------
        Purpose:
            Read the active domain profile that install.ps1 recorded in
            .claude\CLAUDE.md (the machine-readable `active_profile:` line).

        Inputs:
            ClaudeMdPath (string): path of .claude\CLAUDE.md

        Outputs:
            name (string): the profile name, or an empty string when the file or the
            line is absent
        --------------------------------------------------------------------------
    #>
    param([Parameter(Mandatory = $true)][string]$ClaudeMdPath)
    if (-not (Test-Path -LiteralPath $ClaudeMdPath -PathType Leaf)) { return "" }
    $text = [System.IO.File]::ReadAllText($ClaudeMdPath)
    $found = [regex]::Match($text, '(?m)^active_profile:\s*(\S+)')
    if ($found.Success) { return $found.Groups[1].Value }
    return ""
}

function Resolve-RtUpdateProfile {
    <#
        --------------------------------------------------------------------------
        Purpose:
            Turn the student's answer to "which profile" into a profile name, never
            guessing: an unknown name, or a path, is refused.

        Inputs:
            Answer (string): what was typed; empty means "keep the current one"
            Available (string[]): the profile names of this clone
            Current (string): the profile recorded today

        Outputs:
            name (string): the canonical name from Available, or $null when the
            answer names no profile, or is empty and the current one is not usable
        --------------------------------------------------------------------------
    #>
    param(
        [AllowEmptyString()][string]$Answer,
        [Parameter(Mandatory = $true)][AllowEmptyCollection()][string[]]$Available,
        [AllowEmptyString()][string]$Current
    )
    $wanted = $Answer.Trim()
    if ($wanted -eq "") { $wanted = $Current.Trim() }
    if ($wanted -eq "") { return $null }
    foreach ($name in $Available) {
        if ($name -ieq $wanted) { return $name }
    }
    return $null
}

function Resolve-RtUpdatePlan {
    <#
        --------------------------------------------------------------------------
        Purpose:
            Decide the steps of `setup.ps1 -Update`, in order, with their flags. It
            runs nothing: setup.ps1 executes the records one by one.

        Details:
            Order: config (with the hook update), the Claude Code links, the mirrors
            for other tools, the offline suite when asked, the sync into ~/.claude,
            the read-only deployment check. The suite sits just before the sync
            because the sync only copies files a green run has proven. In preview the
            links and the sync run as WhatIf, the mirrors step is skipped (install.ps1
            has no preview mode), the suite is left out and the read-only check stays.

        Inputs:
            Profile (string): the chosen domain profile
            Personal (bool): also install GitHub Copilot at user level
            RunSuite (bool): run the offline suite first
            Preview (bool): write nothing

        Outputs:
            steps (object[]): records with Id, Label, WhatIf, Skipped, Reason, and
            for config UpdateHooks, for tools Profile and Personal
        --------------------------------------------------------------------------
    #>
    param(
        [Parameter(Mandatory = $true)][string]$Profile,
        [Parameter(Mandatory = $true)][bool]$Personal,
        [Parameter(Mandatory = $true)][bool]$RunSuite,
        [Parameter(Mandatory = $true)][bool]$Preview
    )
    $steps = @()
    $steps += [PSCustomObject]@{
        Id = "config"; Label = "Global configuration, with the hook update (setup.ps1)"
        WhatIf = $Preview; Skipped = $false; Reason = ""; UpdateHooks = $true
    }
    $steps += [PSCustomObject]@{
        Id = "junctions"; Label = "Claude Code links (setup.ps1 -InstallJunctions)"
        WhatIf = $Preview; Skipped = $false; Reason = ""
    }
    $steps += [PSCustomObject]@{
        Id = "tools"; Label = "Mirrors for the other tools (install.ps1 -Profile $Profile$(if ($Personal) { ' -Personal' }))"
        WhatIf = $false; Skipped = $Preview
        Reason = $(if ($Preview) { "install.ps1 has no preview mode, skipped in preview" } else { "" })
        Profile = $Profile; Personal = $Personal
    }
    if ($RunSuite -and -not $Preview) {
        $steps += [PSCustomObject]@{
            Id = "suite"; Label = "Offline test suite (so the sync can copy changed files)"
            WhatIf = $false; Skipped = $false; Reason = ""
        }
    }
    $steps += [PSCustomObject]@{
        Id = "sync"; Label = "Copy changed files into ~/.claude (install-junctions.ps1 -Sync)"
        WhatIf = $Preview; Skipped = $false; Reason = ""
    }
    $steps += [PSCustomObject]@{
        Id = "check"; Label = "Deployment check, read-only (scripts\audit\check-deployment.ps1)"
        WhatIf = $false; Skipped = $false; Reason = ""
    }
    return ,$steps
}
