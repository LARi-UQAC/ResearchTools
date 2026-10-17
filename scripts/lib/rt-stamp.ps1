<#
.SYNOPSIS
    Which files the green stamp vouches for, and which hook files -Sync copies: ONE definition.

.DESCRIPTION
    Measured 2026-10-16. install-junctions.ps1 -Sync copies a hook's .py AND its .json
    configuration into ~/.claude (widened 2026-08-30, because a .py that arrives without its
    .json finds no config and, per R11, disables itself in silence). But the green stamp
    written by scripts\test\run-offline-tests.ps1 hashed only *.py. A .json therefore had no
    entry in the stamp, read as "changed since the last green run", and was HELD on every
    -Sync, however green the suite. Three hook configs sat held that way
    (askuserquestion-clarity, rt-inbox-deliver, worktree-link-guard) until they were
    copied by hand. The selection of what is copied and the selection of what is proven had
    drifted apart because each lived in its own file.

    Both now call these two functions, and verify-sync-writes.ps1 asserts that every file
    -Sync would copy is also a file the stamp hashes.

    Dot-source it; it defines functions and runs nothing.
#>

Set-StrictMode -Version Latest

function Get-RtHookFiles {
    <#
    .SYNOPSIS
        The files -Sync copies from a hooks folder: the top-level .py scripts and .json
        configuration files. Test fixtures under Test\ and git\ are not hooks.

    .OUTPUTS
        System.IO.FileInfo[]
    #>
    param([Parameter(Mandatory = $true)][string]$HooksDir)

    if (-not (Test-Path -LiteralPath $HooksDir -PathType Container)) { return @() }
    return @(Get-ChildItem -LiteralPath $HooksDir -File |
             Where-Object { $_.Extension -eq ".py" -or $_.Extension -eq ".json" })
}

function Get-RtCodeFiles {
    <#
    .SYNOPSIS
        Every file the green stamp vouches for: all .py under .claude, plus the hook
        .json configurations that -Sync copies.

    .OUTPUTS
        System.IO.FileInfo[], without duplicates.
    #>
    param([Parameter(Mandatory = $true)][string]$RepoRoot)

    $claude = Join-Path $RepoRoot ".claude"
    $files = @(Get-ChildItem -Path $claude -Recurse -File -Include *.py -ErrorAction SilentlyContinue |
               Where-Object { $_.FullName -notmatch '\\__pycache__\\' })
    $configs = @(Get-RtHookFiles -HooksDir (Join-Path $claude "hooks") |
                 Where-Object { $_.Extension -eq ".json" })
    return @($files + $configs | Sort-Object FullName -Unique)
}
