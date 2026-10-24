#Requires -Version 5.1
<#
.SYNOPSIS
    Offline check that every third-party import of the repository is declared, through
    scripts\docs\python_libs.py --check.

.DESCRIPTION
    A thin wrapper so run-all-checks.ps1 finds the generator by name. Three things are
    asserted:
      1. python_libs.py --check on the real repository exits 0: every import is declared,
         every requirements file is registered, one pin per library per environment, and
         the three tables of manual chapter 02 are up to date.
      2. The failure path (R20): a fictitious root under TEMP holding one undeclared import
         makes the same command exit 1 and name the import. Its control: the same root with
         the import declared, after --write, exits 0.
      3. The real chapter 02 is byte-identical before and after (--check writes nothing).

    The interpreter comes from scripts\lib\rt-venv.ps1 (the main clone's .venv-skills from a
    worktree, R37). With none, the check refuses and names the rebuild command (R8).

.SAFETY
    The fixture lives under $env:TEMP with fictitious names (R34) and is deleted afterwards.
    Nothing in the repository is written.

.EXAMPLE
    .\scripts\test\verify-python-libs.ps1
#>
param([string]$Python = "")

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$Script   = Join-Path $RepoRoot "scripts\docs\python_libs.py"
$Doc      = Join-Path $RepoRoot "docs\manual\02-profiles.md"
$Tmp      = Join-Path $env:TEMP "rt-python-libs-$PID"
$failures = 0
. (Join-Path $RepoRoot "scripts\lib\rt-venv.ps1")

function Check([string]$name, [bool]$ok) {
    if ($ok) { Write-Host "  PASS  $name" -ForegroundColor DarkGray }
    else     { Write-Host "  FAIL  $name" -ForegroundColor Red; $script:failures++ }
}

function Write-Text([string]$Path, [string]$Text) {
    $dir = Split-Path $Path -Parent
    if (-not (Test-Path -LiteralPath $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
    [System.IO.File]::WriteAllText($Path, $Text, (New-Object System.Text.UTF8Encoding($false)))
}

function Invoke-Libs([string[]]$LibsArgs) {
    $ErrorActionPreference = "Continue"   # the exit code is what is checked
    $out = & $script:Py $Script @LibsArgs *>&1 | Out-String
    return [PSCustomObject]@{ Code = $LASTEXITCODE; Text = $out }
}

Write-Host ""
Write-Host "=== python_libs.py: every import declared ===" -ForegroundColor Cyan

$resolved = Resolve-RtVenvPython -RepoRoot $RepoRoot -Python $Python
$Py = $resolved.Python
if ($null -eq $Py) {
    Write-Host "  FAIL  no interpreter to run python_libs.py" -ForegroundColor Red
    Write-Host $resolved.Message
    Write-Host "  Rebuild: $($resolved.Rebuild)"
    exit 1
}
Write-Host "  interpreter: $Py ($($resolved.Source))" -ForegroundColor DarkGray

# --- 1. the real repository -----------------------------------------------------------
$before = (Get-FileHash -LiteralPath $Doc -Algorithm SHA256).Hash
$res = Invoke-Libs @("--check")
Check "the real repository is clean (python_libs.py --check exits 0)" ($res.Code -eq 0)
if ($res.Code -ne 0) { Write-Host $res.Text }
$after = (Get-FileHash -LiteralPath $Doc -Algorithm SHA256).Hash
Check "the real chapter 02 is unchanged by --check" ($before -eq $after)

# --- 2. a fixture with one undeclared import ------------------------------------------
try {
    $root  = Join-Path $Tmp "repo"
    $data  = Join-Path $root "scripts\lib\rt-python-requirements.json"
    $notes = Join-Path $root "scripts\docs\python-libs-notes.json"
    $fdoc  = Join-Path $root "docs\manual\02-profiles.md"
    $req   = Join-Path $root ".claude\skills\zeta\scripts\requirements.txt"
    Write-Text (Join-Path $root ".claude\skills\zeta\scripts\tool.py") "import json`nimport acmelib`n"
    Write-Text $req "PyYAML==6.0.3`n"
    Write-Text $data (@{
        _comment = "fixture"; settings = @{}
        environments = @(@{ name = ".venv-skills"; why = "fixture"; tools = @()
            requirements = @(@{ path = ".claude/skills/zeta/scripts/requirements.txt"; why = "zeta"; exclude = @() }) })
    } | ConvertTo-Json -Depth 6)
    Write-Text $notes (@{
        skip_dirs = @("__pycache__"); files_cap = 3; unused_check_environments = @()
        docs_direct = @(); role_table_environments = @(); pip_list_timeout_s = 30
        distributions = @{ "acme-lib" = @{ imports = @("acmelib"); optional = $false; runtime_only = $false; note = "" } }
    } | ConvertTo-Json -Depth 6)
    Write-Text $fdoc "# Fixture`n`n<!-- python-libs:begin .venv-skills -->`nold`n<!-- python-libs:end .venv-skills -->`n"
    $common = @("--root", $root, "--data", $data, "--notes", $notes, "--doc", $fdoc)

    $res = Invoke-Libs ($common + @("--check"))
    Check "an undeclared import makes --check exit 1" ($res.Code -eq 1)
    Check "the finding names the import and its kind" ($res.Text -match "undeclared" -and $res.Text -match "acmelib")

    Write-Text $req "PyYAML==6.0.3`nacme-lib==1.0.0`n"
    $w = Invoke-Libs ($common + @("--write"))
    $res = Invoke-Libs ($common + @("--check"))
    Check "(control) declared and written, the same root exits 0" ($w.Code -eq 0 -and $res.Code -eq 0)
} finally {
    Remove-Item -LiteralPath $Tmp -Recurse -Force -ErrorAction SilentlyContinue
}
Check "the fixture folder is gone" (-not (Test-Path -LiteralPath $Tmp))

Write-Host ""
if ($failures -eq 0) { Write-Host "  All checks passed." -ForegroundColor Green; Write-Host ""; exit 0 }
Write-Host "  $failures check(s) failed." -ForegroundColor Red
Write-Host ""
exit 1
