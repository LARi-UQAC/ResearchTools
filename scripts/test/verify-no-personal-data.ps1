#Requires -Version 5.1
<#
.SYNOPSIS
    Asserts that no file this repository would publish carries the machine's
    own account name, and proves the assertion can fail.

.DESCRIPTION
    The defect this answers, measured 2026-08-29: two scripts disagreed about
    whether the generated CLAUDE.md and .claude\settings.json were repository
    content or machine-local, so twelve absolute paths through one user profile
    sat in a tracked file for months and no check said a word. A grep nobody
    re-reads would not have helped either, which is why this one carries a
    NEGATIVE CONTROL: it plants an account-name-shaped string in a scratch tree
    and fails if the finder does not report it.

    SCOPE, stated rather than assumed:

      IN   - the account name of whoever runs it ($env:USERNAME, or -UserName).
             That is the string that turns a shared file into one machine's
             file, and it is the one no reviewer can spot by reading.
      OUT  - the repository owner's PERSON name. It is authorship in LICENSE,
             FUNDING.yml and the README badge; it is frozen oracle input in
             .claude\skills\loop-engineer\qualification\tasks.json and in the
             scopus name-parsing fixtures, where the SHAPE carries the defect
             the test documents; and it is the documented default vault path
             (OBSIDIAN_VAULT) in four modules and their fixtures. A check that
             flagged all of those would be turned off within a week.
      OUT  - anything .gitignore excludes, which is how the two generated files
             are meant to be handled from now on. The ignore rules are read
             from .gitignore itself rather than restated here: a second copy
             of that list would drift, and drift is the whole subject.

.PARAMETER UserName
    Account name to look for. Defaults to $env:USERNAME. Injected by the
    negative control so the proof does not depend on who is logged in.

.PARAMETER Root
    Repository root. Defaults to two levels above this script.

.EXAMPLE
    .\scripts\test\verify-no-personal-data.ps1
#>

[CmdletBinding()]
param(
    [string]$UserName = $env:USERNAME,
    [string]$Root
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Write-Header([string]$text) { Write-Host ""; Write-Host "=== $text ===" -ForegroundColor Cyan }
function Write-Pass([string]$text)   { Write-Host "  PASS  $text" -ForegroundColor Green }
function Write-Fail([string]$text)   { Write-Host "  FAIL  $text" -ForegroundColor Red }
function Write-Info([string]$text)   { Write-Host "  [--]  $text" -ForegroundColor DarkGray }

$script:Failures = 0
function Assert-True([bool]$condition, [string]$label) {
    if ($condition) { Write-Pass $label } else { Write-Fail $label; $script:Failures++ }
}

# --- .gitignore, read rather than restated ----------------------------------

function Get-RtIgnoreRules([string]$gitignorePath) {
    <#
        Each rule becomes { Glob; DirOnly; Anchored }. Only the pattern forms
        this repository actually uses are supported; a negation (!) is REFUSED
        out loud rather than ignored, because silently mis-reading an un-ignore
        rule would hide exactly the kind of file this check exists to find.
    #>
    $rules = @()
    if (-not (Test-Path $gitignorePath)) { return $rules }
    foreach ($raw in (Get-Content -Path $gitignorePath -Encoding UTF8)) {
        $line = $raw.Trim()
        if (-not $line -or $line.StartsWith("#")) { continue }
        if ($line.StartsWith("!")) {
            throw "verify-no-personal-data.ps1 cannot read a negation rule ('$line') in $gitignorePath. Teach it that form before adding one."
        }
        $dirOnly = $line.EndsWith("/")
        $glob = $line.TrimEnd("/")
        # A pattern with a slash anywhere is relative to the .gitignore, exactly
        # as git reads it; one without is matched against every path segment.
        $anchored = $glob.Contains("/")
        $rules += [PSCustomObject]@{
            Glob     = $glob.TrimStart("/")
            DirOnly  = $dirOnly
            Anchored = $anchored
        }
    }
    return $rules
}

function Test-RtIgnored([string]$relativePath, [object[]]$rules) {
    $segments = $relativePath -split "/"
    foreach ($rule in $rules) {
        if ($rule.Anchored) {
            if ($relativePath -like $rule.Glob) { return $true }
            if ($relativePath -like ($rule.Glob + "/*")) { return $true }
            continue
        }
        # Unanchored: every segment is a candidate. A directory-only rule may
        # match any segment except the last, which is the file itself.
        $limit = if ($rule.DirOnly) { $segments.Count - 1 } else { $segments.Count }
        for ($i = 0; $i -lt $limit; $i++) {
            if ($segments[$i] -like $rule.Glob) { return $true }
        }
    }
    return $false
}

# --- the finder -------------------------------------------------------------

function Test-RtBinary([string]$path) {
    <# A NUL in the first kilobyte means bytes, not text. #>
    $stream = [System.IO.File]::OpenRead($path)
    try {
        $buffer = New-Object byte[] 1024
        $read = $stream.Read($buffer, 0, $buffer.Length)
        for ($i = 0; $i -lt $read; $i++) { if ($buffer[$i] -eq 0) { return $true } }
    } finally {
        $stream.Dispose()
    }
    return $false
}

function Find-RtPersonalData([string]$root, [string]$userName) {
    <#
        Every text file the repository would publish, scanned for $userName,
        case-insensitively because a Windows path is written both ways.
        Returns one object per hit: RelativePath, LineNumber, Text.
    #>
    if ([string]::IsNullOrWhiteSpace($userName)) {
        throw "no account name to look for: pass -UserName."
    }
    if ($userName.Trim().Length -lt 3) {
        throw "account name '$userName' is too short to search for without flooding the report with false positives. Run this check under a longer account name, or pass -UserName explicitly."
    }

    $rules = Get-RtIgnoreRules (Join-Path $root ".gitignore")
    $rootFull = (Resolve-Path $root).Path.TrimEnd("\")
    $hits = @()

    foreach ($file in (Get-ChildItem -Path $rootFull -Recurse -File -Force)) {
        $relative = $file.FullName.Substring($rootFull.Length + 1).Replace("\", "/")
        # .git is never tracked and is not named in .gitignore.
        if ($relative -eq ".git" -or $relative.StartsWith(".git/")) { continue }
        if (Test-RtIgnored $relative $rules) { continue }
        if (Test-RtBinary $file.FullName) { continue }

        $lineNumber = 0
        foreach ($line in (Get-Content -Path $file.FullName -Encoding UTF8)) {
            $lineNumber++
            if ($line -and $line.IndexOf($userName, [System.StringComparison]::OrdinalIgnoreCase) -ge 0) {
                $text = $line.Trim()
                if ($text.Length -gt 120) { $text = $text.Substring(0, 120) + " (truncated)" }
                $hits += [PSCustomObject]@{
                    RelativePath = $relative
                    LineNumber   = $lineNumber
                    Text         = $text
                }
            }
        }
    }
    return $hits
}

# --- run it against this repository -----------------------------------------

if (-not $Root) { $Root = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent }

Write-Header "No account name in publishable files"
Write-Host "  repo : $Root"
Write-Host "  name : $UserName"

$found = @(Find-RtPersonalData -root $Root -userName $UserName)
if ($found.Count -gt 0) {
    foreach ($hit in $found) {
        Write-Fail "$($hit.RelativePath):$($hit.LineNumber)  $($hit.Text)"
    }
    $script:Failures++
} else {
    Write-Pass "no tracked file carries '$UserName'"
}

# --- negative control: prove the finder can fail -----------------------------
# A check that cannot fail is not a check. The scratch tree lives under TEMP and
# is removed afterwards; nothing here reads or writes the real repository, the
# live ~/.claude, the Startup folder or any environment variable.

Write-Header "Negative control (scratch tree under TEMP)"

$scratch = Join-Path $env:TEMP ("rt-personal-data-" + [System.Guid]::NewGuid().ToString("N").Substring(0, 8))
$utf8NoBom = New-Object System.Text.UTF8Encoding $false
try {
    New-Item -ItemType Directory -Path $scratch -Force | Out-Null
    New-Item -ItemType Directory -Path (Join-Path $scratch "generated") -Force | Out-Null
    New-Item -ItemType Directory -Path (Join-Path $scratch "docs") -Force | Out-Null

    [System.IO.File]::WriteAllText((Join-Path $scratch ".gitignore"),
        "# scratch`r`ngenerated/`r`n/IGNORED.md`r`n", $utf8NoBom)
    # 1. a plain file that MUST be reported
    [System.IO.File]::WriteAllText((Join-Path $scratch "docs\notes.md"),
        "a path through C:\Users\PLANTEDNAME\.claude\hooks`r`n", $utf8NoBom)
    # 2. an ignored directory that must NOT be reported
    [System.IO.File]::WriteAllText((Join-Path $scratch "generated\settings.json"),
        "{ `"path`": `"C:/Users/PLANTEDNAME/bin`" }`r`n", $utf8NoBom)
    # 3. a root-anchored ignored file that must NOT be reported
    [System.IO.File]::WriteAllText((Join-Path $scratch "IGNORED.md"),
        "PLANTEDNAME again`r`n", $utf8NoBom)
    # 4. a clean file
    [System.IO.File]::WriteAllText((Join-Path $scratch "README.md"),
        "nothing personal here`r`n", $utf8NoBom)

    $control = @(Find-RtPersonalData -root $scratch -userName "PLANTEDNAME")
    $paths = @($control | ForEach-Object { $_.RelativePath })

    Assert-True ($control.Count -eq 1) "the planted name is reported (found $($control.Count), expected 1)"
    Assert-True ($paths -contains "docs/notes.md") "reported from the file that carries it"
    Assert-True (-not ($paths -contains "generated/settings.json")) "an ignored directory is not reported"
    Assert-True (-not ($paths -contains "IGNORED.md")) "a root-anchored ignored file is not reported"
    Assert-True (-not ($paths -contains "README.md")) "a clean file is not reported"

    # A name too short to search for is a refusal, not a flood of noise.
    $refused = $false
    try { $null = Find-RtPersonalData -root $scratch -userName "ab" } catch { $refused = $true }
    Assert-True $refused "a two-character account name is refused rather than searched"

    # And the unsupported-pattern refusal, since a negation read as a normal
    # rule would silently un-ignore nothing and hide a real hit.
    [System.IO.File]::WriteAllText((Join-Path $scratch ".gitignore"),
        "generated/`r`n!generated/keep.md`r`n", $utf8NoBom)
    $refusedNegation = $false
    try { $null = Find-RtPersonalData -root $scratch -userName "PLANTEDNAME" } catch { $refusedNegation = $true }
    Assert-True $refusedNegation "a .gitignore negation is refused rather than misread"
} finally {
    if (Test-Path $scratch) { Remove-Item -Path $scratch -Recurse -Force }
}

Write-Header "Summary"
if ($script:Failures -eq 0) {
    Write-Host "  All checks passed." -ForegroundColor Green
    exit 0
}
Write-Host "  $script:Failures check(s) failed." -ForegroundColor Red
exit 1
