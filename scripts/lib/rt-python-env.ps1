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

    Scope is deliberately the OFFLINE SUITE and nothing else. The heavier optional
    skills (requests / google-genai for scopus, docling which pulls torch,
    matplotlib, pymupdf) stay a manual step documented in README.md: a switch that
    downloaded gigabytes for a skill the operator may never run would be refused on
    the first slow machine, and one CVE in a skill nobody uses would block the
    switch the test suite needs.

    The decisions are separated from the work so the offline check can drive them
    with injected values: nothing in Resolve-RtPythonEnvAction touches the disk,
    and nothing in Get-RtSuiteRequirements runs a process.

.NOTES
    Same shape, and the same reason, as scripts\lib\rt-daemon-install.ps1 and
    scripts\lib\rt-sync.ps1: dot-sourcing setup.ps1 to test it would run its whole
    interactive flow just by being loaded.
#>

Set-StrictMode -Version Latest

function Get-RtSuiteRequirements {
    <#
    .SYNOPSIS
        The requirements files the OFFLINE SUITE needs, in install order.

    .DESCRIPTION
        Data, not logic (R6). Each entry names the suite that would otherwise be
        reported NOT RUN, so a reader can tell why the file is on the list and
        delete it from here the day that suite stops importing the package.

        A path that does not exist is returned all the same, with Exists false:
        the caller reports the absence by name rather than installing a shorter
        list than it announced (R3).
    #>
    param([Parameter(Mandatory = $true)][string]$RepoRoot)

    $entries = @(
        @{ Path = ".claude\skills\paper2talk\scripts\requirements.txt"
           Why  = "paper2talk: test_to_a4 (pypdf), the Jinja render path (jinja2), test_talk_pptx (python-pptx), OOXML reads (defusedxml)" },
        @{ Path = ".claude\skills\recommendation-letter\scripts\requirements.txt"
           Why  = "recommendation-letter: test_letter_identity (PyYAML, safe_load over profiles/<active>.yaml)" }
    )

    foreach ($e in $entries) {
        $full = Join-Path $RepoRoot $e.Path
        [pscustomobject]@{
            Path   = $e.Path
            Full   = $full
            Why    = $e.Why
            Exists = (Test-Path -LiteralPath $full -PathType Leaf)
        }
    }
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
            Message = "no Python interpreter on PATH - install Python 3.x first, then re-run"
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
        Create .venv-skills if absent and install what the offline suite imports.

    .DESCRIPTION
        Returns an exit code: 0 for done, previewed or deliberately skipped, 1 for
        a real failure. A failure here must not take the rest of setup down with
        it - junctions and mirrors are useful on a machine with no Python at all -
        so the caller records the code and carries on.

        pip-audit runs afterwards on every file installed, per security.md. Its
        finding is REPORTED and does not fail the step: the pins are the
        repository's to change, and a setup that refused to finish because a
        transitive package published a CVE overnight would be unusable.
    #>
    param(
        [Parameter(Mandatory = $true)][string]$RepoRoot,
        [switch]$Preview
    )

    $venv       = Join-Path $RepoRoot ".venv-skills"
    $venvPython = Join-Path $venv "Scripts\python.exe"

    $base = ""
    $cmd  = Get-Command python -ErrorAction SilentlyContinue
    if ($null -ne $cmd) { $base = $cmd.Source }

    $decision = Resolve-RtPythonEnvAction `
        -VenvPath $venv `
        -VenvExists (Test-Path -LiteralPath $venvPython -PathType Leaf) `
        -BasePython $base

    if ($decision.Action -eq "no-python") {
        Write-Host "  [!!]  Python environment skipped: $($decision.Message)" -ForegroundColor Yellow
        return 0
    }

    $reqs = @(Get-RtSuiteRequirements -RepoRoot $RepoRoot)
    $missing = @($reqs | Where-Object { -not $_.Exists })
    if ($missing.Count -gt 0) {
        foreach ($m in $missing) {
            Write-Host "  [ERR] requirements file not found: $($m.Path)" -ForegroundColor Red
        }
        return 1
    }

    if ($Preview) {
        Write-Host "  [--]  $($decision.Message)"
        foreach ($r in $reqs) {
            Write-Host "  [--]  Would install -r $($r.Path)"
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

    foreach ($r in $reqs) {
        Write-Host "  pip install -r $($r.Path)"
        & $venvPython -m pip install --quiet --disable-pip-version-check -r $r.Full
        if ($LASTEXITCODE -ne 0) {
            Write-Host "  [ERR] install failed for $($r.Path) (exit $LASTEXITCODE)" -ForegroundColor Red
            return 1
        }
    }

    # security.md: pip-audit runs on any requirements file this repository installs.
    # Reported, never fatal - see the header.
    foreach ($r in $reqs) {
        & $venvPython -m pip_audit --strict -r $r.Full 2>&1 | Out-Null
        if ($LASTEXITCODE -eq 0) {
            Write-Host "  [OK]  pip-audit clean: $($r.Path)" -ForegroundColor Green
        } else {
            Write-Host "  [!!]  pip-audit reported findings for $($r.Path) - run it yourself:" -ForegroundColor Yellow
            Write-Host "          $venvPython -m pip_audit --strict -r $($r.Full)"
        }
    }

    Write-Host "  [OK]  Offline suite environment ready: $venvPython" -ForegroundColor Green
    return 0
}
