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
    touches the disk, and nothing in Get-RtEnvironments runs a process.

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

    .PARAMETER Path
        The data file to read. Defaults to the one beside this script; a test passes
        a temp copy.

    .OUTPUTS
        PSCustomObject - the parsed JSON.
    #>
    param([string]$Path = $script:RtRequirementsFile)

    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "package list not found: $Path"
    }
    try {
        return (Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json)
    } catch {
        throw "package list does not parse: $Path ($($_.Exception.Message))"
    }
}

function Get-RtDataValue {
    <#
    .SYNOPSIS
        One property of a parsed JSON object, or $null when it is absent. StrictMode
        throws on a missing property, and a missing key here has to become a named
        error instead.
    #>
    param($Object, [Parameter(Mandatory = $true)][string]$Name)
    if ($null -eq $Object) { return $null }
    $p = $Object.PSObject.Properties[$Name]
    if ($null -eq $p) { return $null }
    return $p.Value
}

function Get-RtEnvironments {
    <#
    .SYNOPSIS
        The Python environments -InstallPython builds, in file order, each with its
        requirements files and its tools.

    .DESCRIPTION
        Data, not logic (R6): the list lives in rt-python-requirements.json, key
        'environments'. Each entry says why it is there, so a reader can delete it
        the day nothing imports the package any more.

        Validated at load time, each refusal naming the file and the dotted key
        (R3): the array is present and not empty, every name is a non-empty string,
        names are unique (a duplicate would install the same folder twice), and every
        'requirements' is a non-empty array whose entries carry a 'path'.

        A requirements path that does not exist is returned all the same, with
        Exists false: the caller reports the absence by name rather than installing
        a shorter list than it announced (R3).

    .PARAMETER RepoRoot
        The root the requirements paths are relative to.

    .PARAMETER Path
        The data file, defaulting to the one beside this script.

    .OUTPUTS
        PSCustomObject[] with Name, Why, Requirements (Path, Full, Why, Exists,
        Exclude) and Tools (Spec, Why).
    #>
    param(
        [Parameter(Mandatory = $true)][string]$RepoRoot,
        [string]$Path = $script:RtRequirementsFile
    )

    $data = Read-RtRequirementsData -Path $Path
    $list = Get-RtDataValue $data "environments"
    if ($null -eq $list -or @($list).Count -eq 0) {
        throw "package list ${Path}: key 'environments' is missing or empty"
    }
    $seen = @{}
    $i = 0
    $result = @()
    foreach ($e in @($list)) {
        $key = "environments[$i]"
        $name = Get-RtDataValue $e "name"
        if (-not ($name -is [string]) -or [string]::IsNullOrWhiteSpace($name)) {
            throw "package list ${Path}: key '$key.name' is missing or not a non-empty string"
        }
        if ($seen.ContainsKey($name.ToLowerInvariant())) {
            throw "package list ${Path}: key '$key.name' repeats the environment name '$name'"
        }
        $seen[$name.ToLowerInvariant()] = 1
        $reqList = Get-RtDataValue $e "requirements"
        if ($null -eq $reqList -or @($reqList).Count -eq 0) {
            throw "package list ${Path}: key '$key.requirements' is missing or empty"
        }
        $reqs = @()
        $j = 0
        foreach ($r in @($reqList)) {
            $rel = Get-RtDataValue $r "path"
            if (-not ($rel -is [string]) -or [string]::IsNullOrWhiteSpace($rel)) {
                throw "package list ${Path}: key '$key.requirements[$j].path' is missing"
            }
            $full = Join-Path $RepoRoot ($rel -replace '/', '\')
            $reqs += [pscustomobject]@{
                Path    = $rel
                Full    = $full
                Why     = [string](Get-RtDataValue $r "why")
                Exists  = (Test-Path -LiteralPath $full -PathType Leaf)
                Exclude = @(Get-RtDataValue $r "exclude" | Where-Object { $null -ne $_ })
            }
            $j++
        }
        $tools = @()
        foreach ($t in @(Get-RtDataValue $e "tools" | Where-Object { $null -ne $_ })) {
            $tools += [pscustomobject]@{ Spec = [string](Get-RtDataValue $t "spec"); Why = [string](Get-RtDataValue $t "why") }
        }
        $result += [pscustomobject]@{
            Name         = $name
            Why          = [string](Get-RtDataValue $e "why")
            Requirements = $reqs
            Tools        = $tools
        }
        $i++
    }
    return $result
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
                # PEP 503: case and every run of - _ . name the same distribution, so
                # docling_core and docling-core are one package (a spelling difference must not
                # let an excluded, torch-sized dependency through).
                $name = ($m.Groups[1].Value.ToLowerInvariant() -replace '[-_.]+', '-')
                foreach ($x in $Exclude) {
                    if ($name -eq ($x.ToLowerInvariant() -replace '[-_.]+', '-')) { $drop = $true }
                }
            }
        }
        if (-not $drop) { $out += $line }
    }
    return $out
}

function Test-RtRequirementHasInclude {
    <#
    .SYNOPSIS
        True when a requirements file pulls in another file (-r / -c and their long
        forms), which a filtered copy written elsewhere could not resolve.
    #>
    param([Parameter(Mandatory = $true)][AllowEmptyCollection()][AllowEmptyString()][string[]]$Lines)

    foreach ($line in $Lines) {
        if ($line -match '^\s*-[rc]\b' -or $line -match '^\s*--(requirement|constraint)\b') { return $true }
    }
    return $false
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
        [Parameter(Mandatory = $true)][AllowEmptyString()][string]$UserProfile
    )

    # No profile known (a service account, a stripped scheduled-task environment): ownership
    # cannot be judged, and a thrown "path not of a legal form" would hide that. The venv
    # probe that follows still decides whether the interpreter is usable.
    if ([string]::IsNullOrWhiteSpace($UserProfile)) { return "" }
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
        # --without-pip: only the CREATION of a venv is being proven here (pip is installed
        # later, into the real environment), and skipping the ensurepip bootstrap turns a
        # probe of tens of seconds per candidate into about a second.
        $proc = Start-Process -FilePath $Python -ArgumentList @("-m", "venv", "--without-pip", "`"$scratch`"") `
                              -NoNewWindow -PassThru -RedirectStandardError ($scratch + ".err") `
                              -RedirectStandardOutput ($scratch + ".out")
        # Touching Handle keeps the process object's handle open, which is what lets
        # ExitCode be read after the process ends (a known Start-Process -PassThru
        # defect on Windows PowerShell 5.1: without it ExitCode comes back empty).
        $null = $proc.Handle
        if (-not $proc.WaitForExit($TimeoutSeconds * 1000)) {
            # taskkill /T ends the whole process tree: Kill() alone leaves children (a venv
            # launcher's pip bootstrap) holding files in the scratch folder.
            try { & taskkill.exe /PID $proc.Id /T /F 2>&1 | Out-Null } catch { }
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
        [Parameter(Mandatory = $true)][AllowEmptyString()][string]$UserProfile,
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

    $lines = @("no usable Python interpreter to build the Python environments from.")
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

function Invoke-RtProcess {
    <#
    .SYNOPSIS
        Start one process for the installer and return its exit code.

    .DESCRIPTION
        The single place the installer starts a process, so a test can carry every
        call through an injected runner (a scriptblock taking the executable and an
        argument array and returning an exit code) and run nothing. With no runner
        the process runs natively; its output goes to the host, never to the
        pipeline, so it cannot pollute the caller's return value.

        ErrorActionPreference is Continue for the call: under setup.ps1's Stop
        preference, Windows PowerShell 5.1 turns the first merged stderr line of a
        native command into a terminating error.

    .PARAMETER Quiet
        Discard the process's output (pip-audit's report: only its code matters here).

    .OUTPUTS
        int - the exit code.
    #>
    param(
        [scriptblock]$Runner = $null,
        [Parameter(Mandatory = $true)][string]$Exe,
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [switch]$Quiet
    )

    if ($null -ne $Runner) {
        $r = @(& $Runner $Exe $Arguments)
        if ($r.Count -eq 0) { return 1 }
        return [int]$r[-1]
    }
    $saved = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        if ($Quiet) { & $Exe @Arguments 2>&1 | Out-Null }
        else        { & $Exe @Arguments | Out-Host }
        return [int]$LASTEXITCODE
    } finally {
        $ErrorActionPreference = $saved
    }
}

function Install-RtEnvironment {
    <#
    .SYNOPSIS
        Create one environment when absent and install its tools and requirements
        files into it.

    .DESCRIPTION
        The per-environment worker of Install-RtPythonEnv. It never audits: the
        orchestrator audits every applied file at the end, from the interpreter of
        the environment that carries pip-audit, so the docs environment never gains
        pip-audit's dependencies.

        A requirements entry with an 'exclude' list is installed from a filtered
        copy in TEMP; the copies are returned in Temps and the CALLER removes them,
        after the audit that still needs them.

        -Preview prints what would be done and starts nothing (R16).

    .PARAMETER Environment
        One object of Get-RtEnvironments.

    .PARAMETER Target
        The main clone the environment folder is created in.

    .PARAMETER Base
        The base interpreter for a creation. Ignored when the environment exists.

    .PARAMETER ProcessRunner
        Test seam, see Invoke-RtProcess.

    .OUTPUTS
        PSCustomObject: Code (0 or 1), Python (the environment's interpreter path),
        Applied (objects Label, File for the audit), Temps (files to remove).
    #>
    param(
        [Parameter(Mandatory = $true)]$Environment,
        [Parameter(Mandatory = $true)][string]$Target,
        [AllowEmptyString()][string]$Base = "",
        [switch]$Preview,
        [scriptblock]$ProcessRunner = $null
    )

    $venv       = Join-Path $Target $Environment.Name
    $venvPython = Join-Path $venv "Scripts\python.exe"
    $exists     = Test-Path -LiteralPath $venvPython -PathType Leaf
    $result     = [pscustomobject]@{ Code = 0; Python = $venvPython; Applied = @(); Temps = @() }
    $reqs       = @($Environment.Requirements)
    $tools      = @($Environment.Tools)

    Write-Host "  -- $($Environment.Name): $($Environment.Why)"
    $decision = Resolve-RtPythonEnvAction -VenvPath $venv -VenvExists $exists -BasePython $(if ($exists) { $venvPython } else { $Base })

    if ($Preview) {
        Write-Host "  [--]  $($decision.Message)"
        if ($exists) {
            Write-Host "  [--]  no base interpreter needed: pip runs from the existing environment ($venvPython)"
        } else {
            Write-Host "  [--]  base interpreter: $Base (exists, current profile; the venv probe is NOT run in a preview)"
        }
        foreach ($t in $tools) { Write-Host "  [--]  Would install $($t.Spec)" }
        foreach ($r in $reqs) {
            Write-Host "  [--]  Would install -r $($r.Path)$(if ($r.Exclude.Count) { '  (without: ' + ($r.Exclude -join ', ') + ')' })"
            Write-Host "        $($r.Why)" -ForegroundColor DarkGray
        }
        return $result
    }

    if ($decision.Action -eq "create") {
        Write-Host "  Creating $venv ..."
        $code = Invoke-RtProcess -Runner $ProcessRunner -Exe $Base -Arguments @("-m", "venv", $venv)
        if ($code -ne 0) {
            Write-Host "  [ERR] python -m venv failed for $($Environment.Name) (exit $code)" -ForegroundColor Red
            $result.Code = 1; return $result
        }
    } else {
        Write-Host "  $($decision.Message)"
    }

    # R9: the environment is only real if its interpreter is on disk afterwards.
    if (-not (Test-Path -LiteralPath $venvPython -PathType Leaf)) {
        Write-Host "  [ERR] no interpreter at $venvPython after creation" -ForegroundColor Red
        $result.Code = 1; return $result
    }

    $utf8 = New-Object System.Text.UTF8Encoding($false)
    if ($tools.Count -gt 0) {
        $toolFile = Join-Path ([System.IO.Path]::GetTempPath()) ("rt-tools-" + [guid]::NewGuid().ToString("N") + ".txt")
        [System.IO.File]::WriteAllLines($toolFile, [string[]]@($tools | ForEach-Object { $_.Spec }), $utf8)
        $result.Temps += $toolFile
        Write-Host "  pip install $(($tools | ForEach-Object { $_.Spec }) -join ' ')"
        $code = Invoke-RtProcess -Runner $ProcessRunner -Exe $venvPython -Arguments @("-m", "pip", "install", "--quiet", "--disable-pip-version-check", "-r", $toolFile)
        if ($code -ne 0) {
            Write-Host "  [ERR] install failed for the installer's own tools in $($Environment.Name) (exit $code)" -ForegroundColor Red
            $result.Code = 1; return $result
        }
        $result.Applied += [pscustomobject]@{ Label = "$($Environment.Name) tools"; File = $toolFile }
    }

    foreach ($r in $reqs) {
        $file = $r.Full
        if ($r.Exclude.Count -gt 0) {
            $source = @(Get-Content -LiteralPath $r.Full -Encoding UTF8)
            # The filtered copy lives in TEMP, where pip would resolve a relative `-r` or
            # `-c` include against the wrong folder. No file does that today; if one ever
            # does, say so rather than let pip fail with "No such file" (R8).
            if (Test-RtRequirementHasInclude -Lines $source) {
                Write-Host "  [ERR] $($r.Path) uses an include (-r/-c) and also has packages to exclude; the filtered copy cannot resolve it" -ForegroundColor Red
                $result.Code = 1; return $result
            }
            $lines = @(Get-RtFilteredRequirementLines -Lines $source -Exclude $r.Exclude)
            $file = Join-Path ([System.IO.Path]::GetTempPath()) ("rt-req-" + [guid]::NewGuid().ToString("N") + ".txt")
            [System.IO.File]::WriteAllLines($file, [string[]]$lines, $utf8)
            $result.Temps += $file
        }
        Write-Host "  pip install -r $($r.Path)$(if ($r.Exclude.Count) { '  (without: ' + ($r.Exclude -join ', ') + ')' })"
        $code = Invoke-RtProcess -Runner $ProcessRunner -Exe $venvPython -Arguments @("-m", "pip", "install", "--quiet", "--disable-pip-version-check", "-r", $file)
        if ($code -ne 0) {
            Write-Host "  [ERR] install failed for $($r.Path) (exit $code)" -ForegroundColor Red
            $result.Code = 1; return $result
        }
        $result.Applied += [pscustomobject]@{ Label = $r.Path; File = $file }
    }

    Write-Host "  [OK]  Environment ready: $venvPython" -ForegroundColor Green
    return $result
}

function Invoke-RtRequirementsAudit {
    <#
    .SYNOPSIS
        Run pip-audit on every applied requirements file, from one interpreter.

    .DESCRIPTION
        security.md: pip-audit runs on any requirements file this repository
        installs. A finding is REPORTED and never fatal: the pins are the
        repository's to change, and a setup that refused to finish because a
        transitive package published a CVE overnight would be unusable.

    .PARAMETER AuditPython
        The interpreter that has pip-audit (the .venv-skills one).

    .PARAMETER Applied
        Objects Label, File, as Install-RtEnvironment returns them.

    .PARAMETER ProcessRunner
        Test seam, see Invoke-RtProcess.

    .OUTPUTS
        None. Prints one OK or warning line per file.
    #>
    param(
        [Parameter(Mandatory = $true)][string]$AuditPython,
        [AllowEmptyCollection()][object[]]$Applied = @(),
        [scriptblock]$ProcessRunner = $null
    )

    foreach ($a in $Applied) {
        $code = Invoke-RtProcess -Runner $ProcessRunner -Exe $AuditPython -Arguments @("-m", "pip_audit", "--strict", "-r", $a.File) -Quiet
        if ($code -eq 0) {
            Write-Host "  [OK]  pip-audit clean: $($a.Label)" -ForegroundColor Green
        } else {
            Write-Host "  [!!]  pip-audit reported findings for $($a.Label) - run it yourself on that file" -ForegroundColor Yellow
            Write-Host "          (minus any excluded package): $AuditPython -m pip_audit --strict -r <file>"
        }
    }
}

function Install-RtPythonEnv {
    <#
    .SYNOPSIS
        Create .venv-skills and .venv-docs if absent and install what the repository's
        skills and its documentation site import.

    .DESCRIPTION
        Returns an exit code: 0 for done, previewed or deliberately skipped, 1 for
        a real failure in any environment. A failure here must not take the rest of
        setup down with it - junctions and mirrors are useful on a machine with no
        Python at all - so the caller records the code and carries on. A failure in
        one environment does not skip the next (2026-10-22, D1).

        The environments are the entries of rt-python-requirements.json, built in
        file order. Every requirements file of every environment is checked for
        existence BEFORE any process starts, so a missing file is named and nothing
        is half-built (R3).

        The environments always live in the MAIN clone, never in a linked worktree
        (rt-venv.ps1's rule, 2026-10-16): a second environment per worktree is what
        led to linking one, and a link is what let a worktree removal delete the
        real one. Run from a worktree, this builds or extends the main clone's.

        One base interpreter is chosen once, and only when an environment has to be
        created. An existing environment is reused: pip runs from ITS interpreter.
        With no usable base interpreter, the environments that would need creating
        are skipped with the reason, and the existing ones are still extended.

        -Preview creates nothing and starts no process that writes: the base
        interpreter is checked for existence and ownership only, and the scratch
        venv probe is announced rather than run (R16).

        pip-audit runs afterwards on every file installed, from the interpreter of
        the environment that carries it as a tool.

    .PARAMETER Python
        An explicit base interpreter. Refused when it belongs to another account or
        cannot create a virtual environment; never silently replaced.

    .PARAMETER CandidatePaths
        Test seam: the candidate list, instead of discovering it.

    .PARAMETER UserProfile
        Test seam: the profile to judge ownership against. Defaults to USERPROFILE.

    .PARAMETER ProcessRunner
        Test seam: a scriptblock taking the executable and an argument array and
        returning an exit code. Every process the installer starts goes through it,
        the scratch venv probe included. $null (the default) runs them natively.
    #>
    param(
        [Parameter(Mandatory = $true)][string]$RepoRoot,
        [switch]$Preview,
        [string]$Python = "",
        [string[]]$CandidatePaths = $null,
        [string]$UserProfile = $env:USERPROFILE,
        [scriptblock]$ProcessRunner = $null
    )

    $target = Get-RtMainRepoRoot -RepoRoot $RepoRoot
    $envs   = @(Get-RtEnvironments -RepoRoot $RepoRoot)

    $missing = @($envs | ForEach-Object { $_.Requirements } | Where-Object { -not $_.Exists })
    if ($missing.Count -gt 0) {
        foreach ($m in $missing) {
            Write-Host "  [ERR] requirements file not found: $($m.Path)" -ForegroundColor Red
        }
        return 1
    }

    $sameRoot = ([System.IO.Path]::GetFullPath($target).TrimEnd('\', '/') -ieq
                 [System.IO.Path]::GetFullPath($RepoRoot).TrimEnd('\', '/'))
    if (-not $sameRoot) {
        Write-Host "  [--]  this is a linked worktree: the environments belong to the main clone ($target)"
    }

    $toCreate = @($envs | Where-Object { -not (Test-Path -LiteralPath (Join-Path $target "$($_.Name)\Scripts\python.exe") -PathType Leaf) })
    $base = ""
    $skipNames = @()
    if ($toCreate.Count -gt 0) {
        $candidates = $CandidatePaths
        if ($null -eq $candidates) { $candidates = @(Get-RtPythonCandidates) }
        $settings = (Read-RtRequirementsData).settings
        $timeout  = [int]$settings.venv_probe_timeout_s.value
        if ($null -ne $ProcessRunner) {
            # The probe goes through the runner too, so a test starts no process at all.
            $probe = {
                param($p)
                $scratch = Join-Path ([System.IO.Path]::GetTempPath()) ("rt-venv-probe-" + [guid]::NewGuid().ToString("N"))
                try {
                    $c = Invoke-RtProcess -Runner $ProcessRunner -Exe $p -Arguments @("-m", "venv", "--without-pip", $scratch)
                    if ($c -ne 0) { return "python -m venv failed (exit $c)" }
                    return ""
                } finally { Remove-Item -LiteralPath $scratch -Recurse -Force -ErrorAction SilentlyContinue }
            }
        } else {
            # A plain scriptblock, not a closure: it resolves Test-RtVenvCreates and $timeout
            # through the call stack, which a closure's private module scope would not see.
            $probe = { param($p) Test-RtVenvCreates -Python $p -TimeoutSeconds $timeout }
        }
        $pick = Select-RtBasePython -Candidates $candidates -Explicit $Python `
                                    -UserProfile $UserProfile -Probe $probe -SkipProbe:$Preview
        $base = $pick.Python
        if ([string]::IsNullOrWhiteSpace($base)) {
            $skipNames = @($toCreate | ForEach-Object { $_.Name })
            Write-Host "  [!!]  Python environment skipped: $($skipNames -join ', ')" -ForegroundColor Yellow
            foreach ($line in ($pick.Message -split "`n")) { Write-Host "        $line" -ForegroundColor Yellow }
        }
    } elseif (-not [string]::IsNullOrWhiteSpace($Python)) {
        # Said, not swallowed: -Python names the interpreter an environment is BUILT from,
        # and there is nothing to build here. Repairing a broken base means deleting the
        # environment first, which this installer never does on its own.
        Write-Host "  [!!]  -Python was ignored: every environment already exists and is reused as it is." -ForegroundColor Yellow
        Write-Host "        To rebuild one from $Python, remove its folder yourself first." -ForegroundColor Yellow
    }

    $worst = 0
    $applied = @()
    $temps = @()
    $auditPython = ""
    try {
        foreach ($e in $envs) {
            if ($skipNames -contains $e.Name) { continue }
            $r = Install-RtEnvironment -Environment $e -Target $target -Base $base -Preview:$Preview -ProcessRunner $ProcessRunner
            $temps   += @($r.Temps)
            $applied += @($r.Applied)
            if ($r.Code -gt $worst) { $worst = $r.Code }
            if (@($e.Tools | Where-Object { $_.Spec -match '^pip-audit' }).Count -gt 0 -and $r.Code -eq 0) { $auditPython = $r.Python }
        }

        if ($Preview) {
            if ($applied.Count -eq 0 -and $skipNames.Count -lt $envs.Count) {
                Write-Host "  [--]  Would then run pip-audit on each file, from the environment that carries it"
            }
            return 0
        }

        if ($applied.Count -gt 0) {
            if ([string]::IsNullOrWhiteSpace($auditPython)) {
                Write-Host "  [!!]  pip-audit not run: the environment that carries it was not installed" -ForegroundColor Yellow
            } else {
                Invoke-RtRequirementsAudit -AuditPython $auditPython -Applied $applied -ProcessRunner $ProcessRunner
            }
        }
    } finally {
        foreach ($t in $temps) { Remove-Item -LiteralPath $t -Force -ErrorAction SilentlyContinue }
    }
    return $worst
}
