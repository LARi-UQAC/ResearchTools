# rt-mirrors-fresh.ps1 - does install.ps1 still change something? (Issue #102)
#
# Dot-sourced by scripts\test\verify-mirrors-fresh.ps1, which run-all-checks.ps1 discovers.
# The mirrors (AGENTS.md, CONVENTIONS.md, .github\, .agents\skills\, ...) are generated from the
# canonical .claude\ definitions and committed. Editing a canonical file without re-running
# install.ps1 leaves them stale, and nothing failed until this check existed.

function Test-RtMirrorsFresh {
    <#
        --------------------------------------------------------------------------
        Purpose:
            Report every file install.ps1 would change or create in a repository,
            without writing to that repository.

        Details:
            The tracked and untracked-not-ignored files (`git ls-files -co
            --exclude-standard`, so an uncommitted canonical edit counts) are copied
            to a new TEMP folder, hashed, install.ps1 -Profile <name> is run THERE
            (never -Personal, so nothing user-scoped is written), and the copy is
            hashed again. The copy is removed in every case.

        Inputs:
            Root (string): the repository root holding install.ps1.
            ProfileName (string): the domain profile passed to install.ps1.

        Outputs:
            result (PSCustomObject): Ok (bool), Differs (string[] of repository-
            relative paths changed or created), Error ("" or why install could not
            be judged: the file list, the copy or install.ps1 failed).
        --------------------------------------------------------------------------
    #>
    param([Parameter(Mandatory = $true)][string]$Root, [Parameter(Mandatory = $true)][string]$ProfileName)
    $fail = { param($m) [PSCustomObject]@{ Ok = $false; Differs = @(); Error = $m } }
    if (-not (Test-Path -LiteralPath (Join-Path $Root "install.ps1") -PathType Leaf)) {
        return (& $fail "no install.ps1 in $Root")
    }
    $prev = $ErrorActionPreference; $ErrorActionPreference = "Continue"
    $list = @(& git -C $Root ls-files -co --exclude-standard 2>$null)
    $listCode = $LASTEXITCODE
    $ErrorActionPreference = $prev
    if ($listCode -ne 0 -or $list.Count -eq 0) { return (& $fail "git ls-files failed in $Root (exit $listCode)") }

    $copy = Join-Path $env:TEMP ("rt-mirror-copy-" + [guid]::NewGuid().ToString("N").Substring(0, 12))
    try {
        foreach ($rel in $list) {
            $src = Join-Path $Root $rel
            if (-not (Test-Path -LiteralPath $src -PathType Leaf)) { continue }   # a deleted tracked file
            $dst = Join-Path $copy $rel
            $dir = Split-Path $dst -Parent
            if (-not (Test-Path -LiteralPath $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
            Copy-Item -LiteralPath $src -Destination $dst -Force
        }
        $hashes = @{}
        foreach ($f in Get-ChildItem -LiteralPath $copy -Recurse -File -Force) {
            $hashes[$f.FullName.Substring($copy.Length + 1)] = (Get-FileHash -LiteralPath $f.FullName -Algorithm SHA256).Hash
        }
        $prev = $ErrorActionPreference; $ErrorActionPreference = "Continue"
        $out = & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $copy "install.ps1") -Profile $ProfileName *>&1 | Out-String
        $code = $LASTEXITCODE
        $ErrorActionPreference = $prev
        if ($code -ne 0) {
            $tail = (($out.Trim() -split "`r?`n") | Select-Object -Last 5) -join " | "
            return (& $fail "install.ps1 exited $code in the copy: $tail")
        }
        $differs = @()
        foreach ($f in Get-ChildItem -LiteralPath $copy -Recurse -File -Force) {
            $rel = $f.FullName.Substring($copy.Length + 1)
            $h = (Get-FileHash -LiteralPath $f.FullName -Algorithm SHA256).Hash
            if (-not $hashes.ContainsKey($rel) -or $hashes[$rel] -ne $h) { $differs += ($rel -replace '\\', '/') }
        }
        $differs = @($differs | Sort-Object)
        return [PSCustomObject]@{ Ok = ($differs.Count -eq 0); Differs = $differs; Error = "" }
    }
    catch {
        return (& $fail "the copy could not be built or read: $($_.Exception.Message)")
    }
    finally {
        Remove-Item -LiteralPath $copy -Recurse -Force -ErrorAction SilentlyContinue
    }
}
