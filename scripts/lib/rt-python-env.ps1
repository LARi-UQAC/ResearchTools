<#
.SYNOPSIS
    The Python-environment half of setup.ps1, in its own file so a test can load it.

.DESCRIPTION
    U9 of the CLAUDE*.md consolidation plan. Measured 2026-08-29: no installer in
    this repository created a virtual environment or installed a requirement, while
    scripts\test\run-offline-tests.ps1 resolves .venv-skills\Scripts\python.exe
    first and several suites import third-party packages. A new user therefore
    cloned, ran setup, ran the suite, and read NOT RUN across the paper2talk cases -
    which the runner reports honestly and nothing fixed.

    Reworked 2026-10-16, after .venv-skills was emptied on 2026-10-06 and could not
    be rebuilt reliably. Measured on this machine that day:
      - `Get-Command python` returned another account's Python 3.13, which this
        account cannot read from the sandbox, so the rebuilt environment would have
        been born from an interpreter that cannot run.
      - the only other interpreter under this account, Python 3.12, has no
        venvlauncher.exe, so `python -m venv` fails with it.
      - the list covered the offline suite alone, so scopus and extract-statistic
        (requests, playwright, pymupdf, pymupdf4llm) were never installed.
    The base interpreter is therefore CHOSEN, not taken: an explicit -Python, or a
    candidate from PATH and the py launcher that belongs to the current profile and
    can really create a virtual environment. A refusal names every candidate and why
    it was rejected. The package list moved to rt-python-requirements.json (R6) and
    now covers the skills whose scripts the repository runs, minus docling, whose
    torch dependency would turn a setup step into a multi-gigabyte download.

    The decisions are separated from the work so the offline check can drive them
    with injected values: nothing in Resolve-RtPythonEnvAction or Select-RtBasePython
    touches the disk, and nothing in Get-RtSuiteRequirements runs a process.

.NOTES
    Same shape, and the same reason, as scripts\lib\rt-daemon-install.ps1 and
    scripts\lib\rt-sync.ps1: dot-sourcing setup.ps1 to test it would run its whole
    interactive flow just by being loaded. Needs rt-venv.ps1 (Get-RtMainRepoRoot)
    to be dot-sourced first.
#>

Set-StrictMode -Version Latest

$script:RtRequirementsFile = Join-Path $PSScriptRoot "rt-python-requirements.json"

function Read-RtRequirementsData {
    <#
    .SYNOPSIS
        Load rt-python-requirements.json. A missing or unparsable file is an
        explicit error naming the file (R3), never an empty list.
    #>
    if (-not (Test-Path -LiteralPath $script:RtRequirementsFile -PathType Leaf)) {
        throw "package list not found: $script:RtRequirementsFile"
    }
    try {
        return (Get-Content -LiteralPath $script:RtRequirementsFile -Raw -Encoding UTF8 | ConvertFrom-Json)
    } catch {
        throw "package list does not parse: $script:RtRequirementsFile ($($_.Exception.Message))"
    }
}

function Get-RtSuiteRequirements {
    <#
    .SYNOPSIS
        The requirements files -InstallPython applies, in install order.

    .DESCRIPTION
        Data, not logic (R6): the list lives in rt-python-requirements.json. Each
        entry says why it is there, so a reader can delete it the day nothing
        imports the package any more.

        A path that does not exist is returned all the same, with Exists false:
        the caller reports the absence by name rather than installing a shorter
        list than it announced (R3).

    .OUTPUTS
        PSCustomObject[] with Path, Full, Why, Exists, Exclude.
    #>
    param([Parameter(Mandatory = $true)][string]$RepoRoot)

    $data = Read-RtRequirementsData
    foreach ($e in @($data.requirements)) {
        $full = Join-Path $RepoRoot ($e.path -replace '/', '\')
        [pscustomobject]@{
            Path    = $e.path
            Full    = $full
            Why     = [string]$e.why
            Exists  = (Test-Path -LiteralPath $full -PathType Leaf)
            Exclude = @($e.exclude)
        }
    }
}

function Get-RtToolRequirements {
    <#
    .SYNOPSIS
        Packages the installer itself relies on (pip-audit), as pip specs.
    #>
    $data = Read-RtRequirementsData
    foreach ($t in @($data.tools)) {
        [pscustomobject]@{ Spec = [string]$t.spec; Why = [string]$t.why }
    }
}

function Get-RtFilteredRequirementLines {
    <#
    .SYNOPSIS
        A requirements file's lines with the excluded packages removed.

    .DESCRIPTION
        Only a requirement line whose package NAME equals an excluded name is
        dropped (case-insensitive, extras and version pins ignored). Comments are
        kept even when they mention the package, and a longer name that merely
        starts the same way (docling-core against docling) stays.

    .OUTPUTS
        string[] - the lines to hand to pip.
    #>
    param(
        [Parameter(Mandatory = $true)][AllowEmptyCollection()][AllowEmptyString()][string[]]$Lines,
        [AllowEmptyCollection()][string[]]$Exclude = @()
    )

    $out = @()
    foreach ($line in $Lines) {
        $drop = $false
        if ($line -notmatch '^\s*(#|$)') {
            $m = [regex]::Match($line, '^\s*([A-Za-z0-9][A-Za-z0-9._-]*)')
            if ($m.Success) {
                foreach ($x in $Exclude) {
                    if ($m.Groups[1].Value -ieq $x) { $drop = $true }
                }
            }
        }
        if (-not $drop) { $out += $line }
    }
    return $out
}

function Test-RtInterpreterOwner {
    <#
    .SYNOPSIS
        Why an interpreter may not be used because it belongs to another account.

    .DESCRIPTION
        Measured 2026-10-16: the first python on PATH sat under another user's
        profile, which the sandbox refused to read (EPERM), so nothing built from it
        could run. A path under the profiles root but outside the CURRENT profile is
        refused. A machine-wide install (Program Files and the like) is not.

    .OUTPUTS
        string - the reason to refuse, or an empty string when the path is fine.
    #>
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$UserProfile
    )

    $full    = [System.IO.Path]::GetFullPath($Path)
    $ownProfile = [System.IO.Path]::GetFullPath($UserProfile).TrimEnd('\', '/')
    $parent  = Split-Path $ownProfile -Parent
    # A profile directly under a drive root (D:\alice) has no "profiles folder" above it:
    # its parent is the whole drive, and every machine-wide install on that drive would
    # read as another account's. Nothing can be said about ownership there, so accept.
    if ([string]::IsNullOrEmpty($parent) -or $parent.TrimEnd('\', '/').Length -le 2) { return "" }
    $roots   = [System.IO.Path]::GetFullPath($parent).TrimEnd('\', '/')

    $inProfile = $full.StartsWith($ownProfile + '\', [System.StringComparison]::OrdinalIgnoreCase)
    $inRoots   = $full.StartsWith($roots + '\',   [System.StringComparison]::OrdinalIgnoreCase)
    if ($inRoots -and -not $inProfile) {
        return "belongs to another account (outside $ownProfile)"
    }
    return ""
}

function Get-RtPyLauncherPaths {
    <#
    .SYNOPSIS
        Interpreter paths listed by `py -0p`, parsed from its text output.

    .DESCRIPTION
        Lines look like " -V:3.11 *        C:\Users\x\Python311\python.exe". Anything
        that is not a path ending in python.exe is ignored. Pure: it takes the
        text, so a test needs no launcher.
    #>
    param([AllowEmptyString()][string]$Text = "")

    $found = @()
    foreach ($line in ($Text -split "`r?`n")) {
        $m = [regex]::Match($line, '([A-Za-z]:\\.*?python[0-9.]*\.exe)\s*$')
        if ($m.Success) { $found += $m.Groups[1].Value.Trim() }
    }
    return $found
}

function Get-RtPythonCandidates {
    <#
    .SYNOPSIS
        Every interpreter that could be the base of the environment, in order: all
        `python` entries on PATH, then those the py launcher knows.
    #>
    $seen = @{}
    $list = @()
    foreach ($c in @(Get-Command python -All -ErrorAction SilentlyContinue)) {
        $p = [string]$c.Source
        if ($p -and -not $seen.ContainsKey($p.ToLowerInvariant())) { $seen[$p.ToLowerInvariant()] = 1; $list += $p }
    }
    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($null -ne $py) {
        $saved = $ErrorActionPreference; $ErrorActionPreference = "Continue"
        try { $text = (& $py.Source -0p 2>$null | Out-String) } catch { $text = "" }
        $ErrorActionPreference = $saved
        foreach ($p in (Get-RtPyLauncherPaths -Text $text)) {
            if (-not $seen.ContainsKey($p.ToLowerInvariant())) { $seen[$p.ToLowerInvariant()] = 1; $list += $p }
        }
    }
    return $list
}

function Test-RtVenvCreates {
    <#
    .SYNOPSIS
        Prove that `<python> -m venv` really works by building a scratch
        environment in TEMP and running its interpreter once.

    .DESCRIPTION
        Measured 2026-10-16: Python 3.12 on this machine lacks venvlauncher.exe,
        so `-m venv` fails while `--version` and `-m venv --help` both succeed. Only
        a real creation tells. The scratch folder is created and removed here, so
        it can never be the real environment.

    .OUTPUTS
        string - empty when it works, otherwise the reason.
    #>
    param(
        [Parameter(Mandatory = $true)][string]$Python,
        [Parameter(Mandatory = $true)][int]$TimeoutSeconds
    )

    $scratch = Join-Path ([System.IO.Path]::GetTempPath()) ("rt-venv-probe-" + [guid]::NewGuid().ToString("N"))
    try {
        $proc = Start-Process -FilePath $Python -ArgumentList @("-m", "venv", "`"$scratch`"") `
                              -NoNewWindow -PassThru -RedirectStandardError ($scratch + ".err") `
                              -RedirectStandardOutput ($scratch + ".out")
        # Touching Handle keeps the process object's handle open, which is what lets
        # ExitCode be read after the process ends (a known Start-Process -PassThru
        # defect on Windows PowerShell 5.1: without it ExitCode comes back empty).
        $null = $proc.Handle
        if (-not $proc.WaitForExit($TimeoutSeconds * 1000)) {
            try { $proc.Kill() } catch { }
            return "python -m venv did not finish within $TimeoutSeconds s"
        }
        # The timed WaitForExit(ms) overload leaves ExitCode unpopulated on Windows
        # PowerShell 5.1 (measured 2026-10-16: every working interpreter was
        # rejected with an empty exit code). The untimed call finalises it.
        $proc.WaitForExit()
        if ($proc.ExitCode -ne 0) {
            $err = ""
            if (Test-Path ($scratch + ".err")) { $err = (Get-Content ($scratch + ".err") -Raw -Encoding UTF8 -ErrorAction SilentlyContinue) }
            if ($null -eq $err) { $err = "" }
            return "python -m venv failed (exit $($proc.ExitCode)): $($err.Trim())"
        }
        $made = Join-Path $scratch "Scripts\python.exe"
        if (-not (Test-Path -LiteralPath $made -PathType Leaf)) {
            return "python -m venv exited 0 but left no Scripts\python.exe"
        }
        return ""
    } catch {
        return "could not run it: $($_.Exception.Message)"
    } finally {
        Remove-Item -LiteralPath $scratch -Recurse -Force -ErrorAction SilentlyContinue
        Remove-Item -LiteralPath ($scratch + ".err"), ($scratch + ".out") -Force -ErrorAction SilentlyContinue
    }
}

function Select-RtBasePython {
    <#
    .SYNOPSIS
        Choose the interpreter the environment is built from, or refuse and say why
        for every candidate.

    .DESCRIPTION
        Order of checks per candidate: the file exists, it belongs to the current
        profile, then (unless SkipProbe) it can really create a virtual environment.
        The first candidate to pass wins. Probe is a scriptblock taking the path and
        returning an empty string or a reason, injected so a test runs no process.
        An explicit interpreter is the only candidate when given: it is never
        quietly replaced by another one.

    .OUTPUTS
        PSCustomObject: Python (path or empty), Rejected (objects with Path and
        Reason), Message (the refusal text, empty when something was chosen).
    #>
    param(
        [AllowEmptyCollection()][string[]]$Candidates = @(),
        [AllowEmptyString()][string]$Explicit = "",
        [Parameter(Mandatory = $true)][string]$UserProfile,
        [scriptblock]$Probe = $null,
        [switch]$SkipProbe
    )

    $list = @($Candidates)
    if (-not [string]::IsNullOrWhiteSpace($Explicit)) { $list = @($Explicit) }

    $rejected = @()
    foreach ($c in $list) {
        if (-not (Test-Path -LiteralPath $c -PathType Leaf)) {
            $rejected += [pscustomobject]@{ Path = $c; Reason = "does not exist" }; continue
        }
        $why = Test-RtInterpreterOwner -Path $c -UserProfile $UserProfile
        if ($why) { $rejected += [pscustomobject]@{ Path = $c; Reason = $why }; continue }
        if (-not $SkipProbe -and $null -ne $Probe) {
            $why = [string](& $Probe $c)
            if ($why) { $rejected += [pscustomobject]@{ Path = $c; Reason = $why }; continue }
        }
        return [pscustomobject]@{ Python = $c; Rejected = $rejected; Message = "" }
    }

    $lines = @("no usable Python interpreter to build .venv-skills from.")
    if ($list.Count -eq 0) { $lines += "  none was found on PATH or through the py launcher." }
    foreach ($r in $rejected) { $lines += "  $($r.Path): $($r.Reason)" }
    $lines += "Install Python 3 under your own profile, or pass -Python <path to a working interpreter>."
    return [pscustomobject]@{ Python = ""; Rejected = $rejected; Message = ($lines -join "`n") }
}

function Resolve-RtPythonEnvAction {
    <#
    .SYNOPSIS
        Decide what -InstallPython would do. Writes nothing, runs nothing.

    .OUTPUTS
        A PSCustomObject with Action and Message.
          create    no virtual environment yet, one would be created
          reuse     .venv-skills is already there, only the installs would run
          no-python no interpreter to build it with, which is a refusal (R3)
    #>
    param(
        [Parameter(Mandatory = $true)][string]$VenvPath,
        [bool]$VenvExists = $false,
        [AllowEmptyString()][string]$BasePython = ""
    )

    if ([string]::IsNullOrWhiteSpace($BasePython)) {
        return [pscustomobject]@{
            Action  = "no-python"
            Message = "no usable Python interpreter - install Python 3 under your own profile first, then re-run"
        }
    }

    if ($VenvExists) {
        return [pscustomobject]@{
            Action  = "reuse"
            Message = "reusing the existing environment at $VenvPath"
        }
    }

    return [pscustomobject]@{
        Action  = "create"
        Message = "would create $VenvPath with $BasePython"
    }
}

function Install-RtPythonEnv {
    <#
    .SYNOPSIS
        Create .venv-skills if absent and install what the repository's skills import.

    .DESCRIPTION
        Returns an exit code: 0 for done, previewed or deliberately skipped, 1 for
        a real failure. A failure here must not take the rest of setup down with
        it - junctions and mirrors are useful on a machine with no Python at all -
        so the caller records the code and carries on.

        The environment always lives in the MAIN clone, never in a linked worktree
        (rt-venv.ps1's rule, 2026-10-16): a second environment per worktree is what
        led to linking one, and a link is what let a worktree removal delete the
        real one. Run from a worktree, this builds or extends the main clone's.

        -Preview creates nothing and starts no process that writes: the base
        interpreter is checked for existence and ownership only, and the scratch
        venv probe is announced rather than run (R16).

        pip-audit runs afterwards on every file installed, per security.md. Its
        finding is REPORTED and does not fail the step: the pins are the
        repository's to change, and a setup that refused to finish because a
        transitive package published a CVE overnight would be unusable.

    .PARAMETER Python
        An explicit base interpreter. Refused when it belongs to another account or
        cannot create a virtual environment; never silently replaced.

    .PARAMETER CandidatePaths
        Test seam: the candidate list, instead of discovering it.

    .PARAMETER UserProfile
        Test seam: the profile to judge ownership against. Defaults to USERPROFILE.
    #>
    param(
        [Parameter(Mandatory = $true)][string]$RepoRoot,
        [switch]$Preview,
        [string]$Python = "",
        [string[]]$CandidatePaths = $null,
        [string]$UserProfile = $env:USERPROFILE
    )

    $target     = Get-RtMainRepoRoot -RepoRoot $RepoRoot
    $venv       = Join-Path $target ".venv-skills"
    $venvPython = Join-Path $venv "Scripts\python.exe"

    $reqs = @(Get-RtSuiteRequirements -RepoRoot $RepoRoot)
    $missing = @($reqs | Where-Object { -not $_.Exists })
    if ($missing.Count -gt 0) {
        foreach ($m in $missing) {
            Write-Host "  [ERR] requirements file not found: $($m.Path)" -ForegroundColor Red
        }
        return 1
    }

    $candidates = $CandidatePaths
    if ($null -eq $candidates) { $candidates = @(Get-RtPythonCandidates) }
    $settings = (Read-RtRequirementsData).settings
    $timeout  = [int]$settings.venv_probe_timeout_s.value
    # A plain scriptblock, not a closure: it resolves Test-RtVenvCreates and $timeout
    # through the call stack, which a closure's private module scope would not see.
    $probe    = { param($p) Test-RtVenvCreates -Python $p -TimeoutSeconds $timeout }

    # An environment that already exists is reused: pip runs from ITS interpreter, so no
    # base interpreter is chosen and no scratch venv is built to prove one (code-review
    # finding: a healthy .venv-skills used to be refused, or delayed by a probe of up to
    # the configured timeout per candidate, just because PATH held no usable python).
    $venvExists = Test-Path -LiteralPath $venvPython -PathType Leaf
    if ($venvExists) {
        $pick = [pscustomobject]@{ Python = $venvPython; Rejected = @(); Message = "" }
    } else {
        $pick = Select-RtBasePython -Candidates $candidates -Explicit $Python `
                                    -UserProfile $UserProfile -Probe $probe -SkipProbe:$Preview
    }

    $decision = Resolve-RtPythonEnvAction `
        -VenvPath $venv `
        -VenvExists $venvExists `
        -BasePython $pick.Python

    if ($decision.Action -eq "no-python") {
        Write-Host "  [!!]  Python environment skipped:" -ForegroundColor Yellow
        foreach ($line in ($pick.Message -split "`n")) { Write-Host "        $line" -ForegroundColor Yellow }
        return 0
    }
    $base = $pick.Python

    $sameRoot = ([System.IO.Path]::GetFullPath($target).TrimEnd('\', '/') -ieq
                 [System.IO.Path]::GetFullPath($RepoRoot).TrimEnd('\', '/'))
    if (-not $sameRoot) {
        Write-Host "  [--]  this is a linked worktree: the environment belongs to the main clone ($target)"
    }

    if ($Preview) {
        Write-Host "  [--]  $($decision.Message)"
        if ($venvExists) {
            Write-Host "  [--]  no base interpreter needed: pip runs from the existing environment ($base)"
        } else {
            Write-Host "  [--]  base interpreter: $base (exists, current profile; the venv probe is NOT run in a preview)"
        }
        foreach ($t in (Get-RtToolRequirements)) {
            Write-Host "  [--]  Would install $($t.Spec)"
        }
        foreach ($r in $reqs) {
            Write-Host "  [--]  Would install -r $($r.Path)$(if ($r.Exclude.Count) { '  (without: ' + ($r.Exclude -join ', ') + ')' })"
            Write-Host "        $($r.Why)" -ForegroundColor DarkGray
        }
        Write-Host "  [--]  Would then run pip-audit on each file"
        return 0
    }

    if ($decision.Action -eq "create") {
        Write-Host "  Creating $venv ..."
        & $base -m venv $venv
        if ($LASTEXITCODE -ne 0) {
            Write-Host "  [ERR] python -m venv failed (exit $LASTEXITCODE)" -ForegroundColor Red
            return 1
        }
    } else {
        Write-Host "  $($decision.Message)"
    }

    # R9: the environment is only real if its interpreter is on disk afterwards.
    if (-not (Test-Path -LiteralPath $venvPython -PathType Leaf)) {
        Write-Host "  [ERR] no interpreter at $venvPython after creation" -ForegroundColor Red
        return 1
    }

    # Files handed to pip and to pip-audit: the original when nothing is excluded,
    # a filtered temp copy otherwise. Tracked so the finally block removes them.
    $temps = @()
    $applied = @()
    try {
        $tools = @(Get-RtToolRequirements)
        if ($tools.Count -gt 0) {
            $toolFile = Join-Path ([System.IO.Path]::GetTempPath()) ("rt-tools-" + [guid]::NewGuid().ToString("N") + ".txt")
            [System.IO.File]::WriteAllLines($toolFile, [string[]]@($tools | ForEach-Object { $_.Spec }), (New-Object System.Text.UTF8Encoding($false)))
            $temps += $toolFile
            Write-Host "  pip install $(($tools | ForEach-Object { $_.Spec }) -join ' ')"
            & $venvPython -m pip install --quiet --disable-pip-version-check -r $toolFile
            if ($LASTEXITCODE -ne 0) {
                Write-Host "  [ERR] install failed for the installer's own tools (exit $LASTEXITCODE)" -ForegroundColor Red
                return 1
            }
            $applied += [pscustomobject]@{ Label = "tools"; File = $toolFile }
        }

        foreach ($r in $reqs) {
            $file = $r.Full
            if ($r.Exclude.Count -gt 0) {
                $lines = @(Get-RtFilteredRequirementLines -Lines (Get-Content -LiteralPath $r.Full -Encoding UTF8) -Exclude $r.Exclude)
                $file = Join-Path ([System.IO.Path]::GetTempPath()) ("rt-req-" + [guid]::NewGuid().ToString("N") + ".txt")
                [System.IO.File]::WriteAllLines($file, [string[]]$lines, (New-Object System.Text.UTF8Encoding($false)))
                $temps += $file
            }
            Write-Host "  pip install -r $($r.Path)$(if ($r.Exclude.Count) { '  (without: ' + ($r.Exclude -join ', ') + ')' })"
            & $venvPython -m pip install --quiet --disable-pip-version-check -r $file
            if ($LASTEXITCODE -ne 0) {
                Write-Host "  [ERR] install failed for $($r.Path) (exit $LASTEXITCODE)" -ForegroundColor Red
                return 1
            }
            $applied += [pscustomobject]@{ Label = $r.Path; File = $file }
        }

        # security.md: pip-audit runs on any requirements file this repository installs.
        # Reported, never fatal - see the header.
        foreach ($a in $applied) {
            & $venvPython -m pip_audit --strict -r $a.File 2>&1 | Out-Null
            if ($LASTEXITCODE -eq 0) {
                Write-Host "  [OK]  pip-audit clean: $($a.Label)" -ForegroundColor Green
            } else {
                Write-Host "  [!!]  pip-audit reported findings for $($a.Label) - run it yourself on that file" -ForegroundColor Yellow
                Write-Host "          (minus any excluded package): $venvPython -m pip_audit --strict -r <file>"
            }
        }
    } finally {
        foreach ($t in $temps) { Remove-Item -LiteralPath $t -Force -ErrorAction SilentlyContinue }
    }

    Write-Host "  [OK]  Environment ready: $venvPython" -ForegroundColor Green
    return 0
}
