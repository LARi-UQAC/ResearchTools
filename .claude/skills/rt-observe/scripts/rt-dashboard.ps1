<#
.SYNOPSIS
    rt-dashboard - start the rt-observe loopback dashboard (canonical launcher).

.DESCRIPTION
    This script does ONE thing that Python cannot do for itself: find an
    interpreter. Everything else - the port probe, the two refusals about a port
    already in use, the session token, the bind - lives in rt_state.py, where an
    offline suite can reach it. That split is the same one run-drill.ps1 and
    tune-new-model.ps1 already use in this repository: PowerShell that spawns
    processes cannot be tested offline, so it holds as little decision as
    possible.

    Its own refusal is the one it cannot delegate: with no interpreter found,
    every candidate that was tried is NAMED and the exit code is 2, a refusal by
    design (R12). It never guesses at a path and never falls back to a different
    tool.

    The POSIX twin is rt-dashboard.sh, beside this file. Both are reached from
    the repository root through thin wrappers, and neither is required: a user
    with no PowerShell runs `python rt_state.py --serve` directly.

.PARAMETER Open
    Hand the loopback URL to the default browser once the server is up.

.PARAMETER DryRun
    Print the interpreter, the bind address, every TTL and what would happen,
    and start nothing (R16). It returns the code the real run would return, so
    it works as a preflight.

.PARAMETER Port
    Override the port declared in observe-config.json for this run.

.PARAMETER Python
    An explicit interpreter. It must exist; a path that does not is a refusal.

.PARAMETER AllowPathFallback
    Accept the first python on PATH when .venv-skills is absent or empty. Without
    it the launcher refuses (exit 2) and names the rebuild command, because a silent
    PATH fallback is how an emptied environment went unnoticed for a week
    (measured 2026-10-16).

.EXAMPLE
    .\rt-dashboard.ps1 -DryRun

.EXAMPLE
    .\rt-dashboard.ps1 -Open
#>
[CmdletBinding()]
param(
    [switch]$Open,
    [switch]$DryRun,
    [int]$Port = 0,
    [string]$Python = '',
    [switch]$AllowPathFallback,
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$Rest
)

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = (Resolve-Path (Join-Path $scriptDir '..\..\..\..')).Path
$module = Join-Path $scriptDir 'rt_state.py'

if (-not (Test-Path $module)) {
    [Console]::Error.WriteLine("rt-dashboard: rt_state.py is not beside this launcher ($module).")
    exit 2
}

# The interpreter decision is scripts\lib\rt-venv.ps1's, shared by every launcher
# (R18): .venv-skills of this clone, then of the MAIN clone when this is a linked
# worktree (no link needed), and PATH only when -AllowPathFallback is given.
. (Join-Path $repoRoot 'scripts\lib\rt-venv.ps1')
$resolved = Resolve-RtVenvPython -RepoRoot $repoRoot -Python $Python -AllowPathFallback:$AllowPathFallback
$exe = $resolved.Python

if (-not $exe) {
    [Console]::Error.WriteLine("rt-dashboard: no Python interpreter found.")
    [Console]::Error.WriteLine($resolved.Message)
    exit 2
}
if ($resolved.Source -eq 'path-fallback') {
    [Console]::Error.WriteLine($resolved.Message)
}

$argv = @()
$argv += $module
$argv += '--serve'
if ($DryRun) { $argv += '--dry-run' }
if ($Open) { $argv += '--open' }
if ($Port -gt 0) { $argv += @('--port', "$Port") }
if ($Rest) { $argv += $Rest }

& $exe @argv
exit $LASTEXITCODE
