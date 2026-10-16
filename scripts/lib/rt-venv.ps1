<#
.SYNOPSIS
    One place that decides which Python interpreter the ResearchTools scripts use.

.DESCRIPTION
    Measured 2026-10-16, after .venv-skills was emptied on 2026-10-06 and nobody
    noticed for a week. Two defects made that loss invisible, and both live in how an
    interpreter was found:

      1. Five launchers (run-offline-tests, rt-dashboard, run-drill,
         vault-daemon-autostart, tune-new-model) each carried their own copy of
         "look for .venv-skills, otherwise take whatever python is on PATH". A
         worktree has no .venv-skills of its own, so the only way to reach the main
         clone's environment was a junction, and a junction is what let
         `git worktree remove` delete the real environment.
      2. With the environment gone, every copy fell through to PATH without a word.
         On this machine the first python on PATH belonged to another account, so the
         suite ran under an interpreter that could not even be read from the sandbox.

    This file replaces the copies. It finds the MAIN clone through git's own common
    directory, so a worktree reaches the main environment by an absolute path and
    needs no link. When nothing is found it REFUSES, names every path it looked at
    and the command that rebuilds the environment. PATH is used only when the caller
    asks for it with -AllowPathFallback, and the result then says so (R8).

    Dot-source it; it defines functions and runs nothing.

.NOTES
    Same shape as rt-sync.ps1 and rt-python-env.ps1: logic in scripts\lib\ so a
    verify script can load it without running a launcher. R18: this is the single
    owner of interpreter resolution FOR POWERSHELL, and scripts\test\verify-venv-resolution.ps1
    fails if a launcher grows its own copy again. Two ports exist because they cannot
    dot-source it: rt-dashboard.sh (POSIX, asks git the same question) and collect_repo.py
    (the dashboard's Repository panel, which reads the same .git and commondir files
    without running git). They agree on the layout and on the broken-environment rule, and
    test_launcher.py and test_rt_collectors.py pin them; a change to the layout is made in
    all three.
#>

Set-StrictMode -Version Latest

$script:RtVenvDirName = ".venv-skills"

function Test-RtStampAllowed {
    <#
    .SYNOPSIS
        Whether a test run may write the green stamp, given where its interpreter came from.

    .DESCRIPTION
        A python taken from PATH (-AllowPathFallback) or named by hand (-Python) may lack the
        repository's packages, and a suite that cannot import one is graded NOT RUN, which
        does not fail the run. Such a run proves less than it looks like it proves, and the
        stamp gates what install-junctions.ps1 -Sync copies into ~/.claude. So the stamp is
        written under an interpreter that is not the repository's own environment only when
        nothing was NOT RUN.

    .OUTPUTS
        bool
    #>
    param(
        [Parameter(Mandatory = $true)][string]$InterpreterSource,
        [Parameter(Mandatory = $true)][int]$NotRunCount
    )
    $inRepository = $InterpreterSource -in @("venv", "main-repo-venv")
    return $inRepository -or ($NotRunCount -eq 0)
}

function Find-RtPathPython {
    <#
    .SYNOPSIS
        The first `python` on PATH, or an empty string. A separate function so a
        test can shadow it and stay independent of the machine's PATH (R21).
    #>
    foreach ($name in @("python", "python3")) {
        $found = Get-Command $name -ErrorAction SilentlyContinue
        if ($null -ne $found) { return [string]$found.Source }
    }
    return ""
}

function Get-RtMainRepoRoot {
    <#
    .SYNOPSIS
        The root of the MAIN clone that owns RepoRoot.

    .DESCRIPTION
        Inside a linked worktree `git rev-parse --git-common-dir` points at the main
        clone's .git directory, whose parent is the main clone. In the main clone, or
        in a folder that is not a repository at all, RepoRoot itself is returned: the
        caller then looks for the environment next to where it already is, and the
        refusal names that path.

    .OUTPUTS
        string - an absolute path. Never throws.
    #>
    param([Parameter(Mandatory = $true)][string]$RepoRoot)

    if ($null -eq (Get-Command git -ErrorAction SilentlyContinue)) { return $RepoRoot }

    $saved = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    # claude-switch.ps1 is dot-sourced into the operator's interactive shell and calls this
    # on every use, so the caller's $LASTEXITCODE is put back afterwards rather than left
    # holding git's (code-review finding).
    $callerExit = Get-Variable -Name LASTEXITCODE -Scope Global -ErrorAction SilentlyContinue
    try {
        # No stderr merge: Windows PowerShell 5.1 wraps merged native stderr in
        # ErrorRecords and flips $? even on exit 0.
        $common = & git -C $RepoRoot rev-parse --git-common-dir 2>$null
        $code = $global:LASTEXITCODE
    } catch {
        return $RepoRoot
    } finally {
        $ErrorActionPreference = $saved
        if ($null -ne $callerExit) { $global:LASTEXITCODE = $callerExit.Value }
        else { Remove-Variable -Name LASTEXITCODE -Scope Global -ErrorAction SilentlyContinue }
    }
    if ($code -ne 0 -or [string]::IsNullOrWhiteSpace(($common | Out-String))) { return $RepoRoot }

    $common = ($common | Select-Object -First 1).ToString().Trim()
    if (-not [System.IO.Path]::IsPathRooted($common)) { $common = Join-Path $RepoRoot $common }
    $common = [System.IO.Path]::GetFullPath($common)

    # A bare repository has no working tree to hold an environment.
    if ((Split-Path $common -Leaf) -ne ".git") { return $RepoRoot }
    return (Split-Path $common -Parent)
}

function Get-RtVenvMissingBase {
    <#
    .SYNOPSIS
        The base interpreter folder a virtual environment points at when that folder is
        gone, or an empty string when it exists or cannot be read.

    .DESCRIPTION
        pyvenv.cfg holds a `home = <folder>` line. A missing or unreadable file proves
        nothing, so it is NOT reported as broken (the caller still gets the interpreter).
    #>
    param([Parameter(Mandatory = $true)][string]$Venv)

    $cfg = Join-Path $Venv "pyvenv.cfg"
    if (-not (Test-Path -LiteralPath $cfg -PathType Leaf)) { return "" }
    try { $text = Get-Content -LiteralPath $cfg -Raw -Encoding UTF8 } catch { return "" }
    $m = [regex]::Match($text, '(?m)^\s*home\s*=\s*(.+?)\s*$')
    if (-not $m.Success) { return "" }
    $home_ = $m.Groups[1].Value
    if (Test-Path -LiteralPath $home_ -PathType Container) { return "" }
    return $home_
}

function Get-RtVenvCandidates {
    <#
    .SYNOPSIS
        The environment locations to try, in order, each with what was found there.

    .OUTPUTS
        PSCustomObject[] with Source, Venv, Python, State. State is one of
        present, empty (the folder exists but holds no interpreter), absent.
    #>
    param(
        [Parameter(Mandatory = $true)][string]$RepoRoot,
        # Already known by the caller, so git is asked once per resolution, not twice.
        [AllowEmptyString()][string]$MainRoot = ""
    )

    $main  = if ([string]::IsNullOrWhiteSpace($MainRoot)) { Get-RtMainRepoRoot -RepoRoot $RepoRoot } else { $MainRoot }
    $roots = @(@{ Source = "venv"; Root = $RepoRoot })
    $same  = ([System.IO.Path]::GetFullPath($main).TrimEnd('\', '/') -ieq
              [System.IO.Path]::GetFullPath($RepoRoot).TrimEnd('\', '/'))
    if (-not $same) { $roots += @{ Source = "main-repo-venv"; Root = $main } }

    foreach ($r in $roots) {
        $venv   = Join-Path $r.Root $script:RtVenvDirName
        $python = Join-Path $venv "Scripts\python.exe"
        $posix  = Join-Path $venv "bin/python"
        $state  = "absent"
        if (Test-Path -LiteralPath $python -PathType Leaf) { $state = "present" }
        elseif (Test-Path -LiteralPath $posix -PathType Leaf) { $state = "present"; $python = $posix }
        elseif (Test-Path -LiteralPath $venv -PathType Container) { $state = "empty" }
        # A launcher stub that outlived its base interpreter still passes Test-Path and then
        # dies with "No Python at ..." in every caller (code-review finding). pyvenv.cfg names
        # the base folder, and reading it needs no process.
        $missingBase = ""
        if ($state -eq "present") {
            $missingBase = Get-RtVenvMissingBase -Venv $venv
            if ($missingBase) { $state = "broken" }
        }
        [pscustomobject]@{ Source = $r.Source; Venv = $venv; Python = $python; State = $state; MissingBase = $missingBase }
    }
}

function Resolve-RtVenvPython {
    <#
    .SYNOPSIS
        Decide which interpreter to run, or refuse and say why.

    .DESCRIPTION
        Order: an explicit -Python, then .venv-skills of RepoRoot, then .venv-skills
        of the main clone when RepoRoot is a linked worktree. PATH is consulted only
        with -AllowPathFallback. No link into the worktree is ever created or needed.

    .PARAMETER RepoRoot
        The clone (or worktree) the calling script belongs to.

    .PARAMETER Python
        An interpreter path given on the command line. It must exist; a path that
        does not is a refusal, never a quiet move to the next candidate.

    .PARAMETER AllowPathFallback
        Accept the first python on PATH when no environment exists.

    .OUTPUTS
        PSCustomObject: Python (path, or $null on refusal), Source (explicit, venv,
        main-repo-venv, path-fallback, none), Message (what to print: a refusal
        explanation, a fallback warning, or empty), Candidates (what was tried),
        Rebuild (the command that recreates the environment).
    #>
    param(
        [Parameter(Mandatory = $true)][string]$RepoRoot,
        [AllowEmptyString()][string]$Python = "",
        [switch]$AllowPathFallback
    )

    $main    = Get-RtMainRepoRoot -RepoRoot $RepoRoot
    $rebuild = "& '" + (Join-Path $main "setup.ps1") + "' -InstallPython"
    $cands   = @(Get-RtVenvCandidates -RepoRoot $RepoRoot -MainRoot $main)

    function New-Result($path, $source, $message) {
        [pscustomobject]@{
            Python = $path; Source = $source; Message = $message
            Candidates = $cands; Rebuild = $rebuild
        }
    }

    if (-not [string]::IsNullOrWhiteSpace($Python)) {
        if (Test-Path -LiteralPath $Python -PathType Leaf) {
            return (New-Result $Python "explicit" "")
        }
        return (New-Result $null "none" ("the interpreter given with -Python does not exist: $Python"))
    }

    foreach ($c in $cands) {
        if ($c.State -eq "present") { return (New-Result $c.Python $c.Source "") }
    }

    $lines = @("no suite interpreter: .venv-skills holds no Scripts\python.exe. Looked at:")
    foreach ($c in $cands) {
        $why = if ($c.State -eq "empty") { "folder exists but is EMPTY or damaged (a recursive delete leaves exactly this)" }
               elseif ($c.State -eq "broken") { "BROKEN: its base interpreter folder is gone ($($c.MissingBase))" }
               else { "absent" }
        $lines += "  $($c.Python)  [$why]"
    }

    if ($AllowPathFallback) {
        $onPath = Find-RtPathPython
        if (-not [string]::IsNullOrWhiteSpace($onPath)) {
            $warn = ($lines -join "`n") + "`n" +
                    "  -AllowPathFallback was given, so the first python on PATH is used instead: $onPath`n" +
                    "  It may not carry this repository's packages, and it may belong to another account."
            return (New-Result $onPath "path-fallback" $warn)
        }
        $lines += "  -AllowPathFallback was given but there is no python on PATH either."
    }

    $lines += "Only .venv-skills is looked for. A root .venv is not used (dropped on purpose 2026-10-16: a missing environment must be said, not replaced)."
    $lines += "Rebuild the environment with:"
    $lines += "  $rebuild"
    $lines += "Or pass -Python <path to an interpreter>, or -AllowPathFallback to accept PATH knowingly."
    return (New-Result $null "none" ($lines -join "`n"))
}
