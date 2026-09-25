<#
.SYNOPSIS
  Install the branch-protection hooks into ONE repository.

.DESCRIPTION
  Writes pre-commit and pre-push into this repository's .git/hooks. They refuse
  a commit or a push on main and master, so aider's automatic commits can only
  land on a working branch.

  Per repository on purpose. A global core.hooksPath would apply to every
  repository on the machine, and git honours it when resolving --git-path,
  which makes a hook that delegates to a repository's own hook re-run itself
  until the commit is killed.

.EXAMPLE
  .\install-hooks.ps1 -Path C:\work\my-project
#>
[CmdletBinding()]
param(
    [string]$Path = ".",
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"
$kit  = Split-Path -Parent $MyInvocation.MyCommand.Path
$proj = (Resolve-Path -LiteralPath $Path).Path

Push-Location $proj
try {
    # The redirection happens INSIDE cmd, not in PowerShell. Measured
    # 2026-09-03: `2>$null` does not stop PowerShell 5.1 wrapping a native
    # command's stderr in an ErrorRecord, and with $ErrorActionPreference =
    # "Stop" that terminates the script - so pointing this at a directory which
    # is not a repository printed a NativeCommandError stack trace and the
    # refusal three lines below was never reached. It is the same defect the
    # manual records for the test command, one script further along.
    $gitDir = (& cmd /c "git rev-parse --git-dir 2>NUL")
    if ($LASTEXITCODE -ne 0) {
        Write-Host "REFUSED: $proj is not a git repository." -ForegroundColor Red
        exit 2
    }
} finally { Pop-Location }

$hooksDir = Join-Path $proj ($gitDir + "\hooks")
foreach ($name in @("pre-commit", "pre-push")) {
    $src = Join-Path $kit "git-hooks\$name"
    $dst = Join-Path $hooksDir $name
    if ($DryRun) { Write-Host "  would write: $dst"; continue }
    if (-not (Test-Path -LiteralPath $hooksDir)) { New-Item -ItemType Directory -Force -Path $hooksDir | Out-Null }
    Copy-Item -LiteralPath $src -Destination $dst -Force
    Write-Host "  installed: $dst"
}

if (-not $DryRun) {
    Write-Host ""
    Write-Host "Check them, in both directions:" -ForegroundColor Cyan
    Write-Host "  git switch main   ; git commit --allow-empty -m x   -> must be REFUSED"
    Write-Host "  git switch -c work; git commit --allow-empty -m x   -> must SUCCEED"
}
