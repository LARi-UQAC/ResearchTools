#Requires -Version 5.1
<#
.SYNOPSIS
    Clean up after a pull request is merged: remove its worktree, delete its branch locally
    and on origin, and move its plans from todo to done.

.DESCRIPTION
    The last step after "pull request, owner merges". It does nothing until -Yes is given: a
    plain run only prints the steps it would take (R16).

    It refuses, and names every reason at once, when:
      - no merged pull request has the branch as its head (asked of gh),
      - the local branch is on a different commit than the one the pull request ended on, which
        means it holds commits that were never pushed,
      - the main clone does not have the main branch checked out (it never switches the
        checked-out branch: R32),
      - origin's branch is on a commit other than the merged pull request's last one (someone
        pushed after the merge, and deleting it would lose that commit),
      - the main clone has modified tracked files (the pull would rewrite files under another
        session, R32),
      - the worktree has uncommitted or untracked files,
      - the worktree holds git-ignored files, which `git worktree remove` deletes without a word
        (pass -DiscardIgnored once you have kept what you need),
      - the worktree holds a junction or a symbolic link, because removing the worktree would
        follow it and delete its target (R37),
      - it was started from inside the worktree it would remove.

    It never uses --force. It deletes the local branch with -D, which is safe here only because
    the check above proved the branch ends on the merged pull request's last commit (after a
    squash merge the branch is never an ancestor of main, so -d would always refuse).

    Run the copy that sits in the MAIN clone (after the merge it is there):
        cd <main clone>
        .\scripts\test\finish-branch.ps1 -Branch feat/my-branch          # dry run
        .\scripts\test\finish-branch.ps1 -Branch feat/my-branch -Yes

.PARAMETER Branch
    The branch of the merged pull request, for example feat/setup-update-hooks.

.PARAMETER MainBranch
    The branch that must be checked out in the main clone and brought up to date. Default: main.

.PARAMETER PlansFolder
    Optional. A folder NAME under docs/superpowers/todo to move to docs/superpowers/done. These
    folders are ignored by git, so a missing one is skipped, not an error.

.PARAMETER ReportPath
    Optional. Write a JSON report: the branch, ok, and each step with its outcome.

.PARAMETER DiscardIgnored
    Accept that git-ignored files in the worktree (logs, caches, local state) are deleted with it.

.PARAMETER Yes
    Actually do it. Without it, nothing is changed.

.NOTES
    Exit codes: 0 done, dry run, or nothing to clean; 1 a step failed (the later ones are not
    run); 2 refused, nothing was changed. Needs git and gh on PATH.
#>
param(
    [Parameter(Mandatory = $true)][string]$Branch,
    [string]$MainBranch = "main",
    [string]$PlansFolder = "",
    [string]$ReportPath = "",
    [switch]$DiscardIgnored,
    [switch]$Yes
)

Set-StrictMode -Version Latest
# Native commands write progress to stderr; that is not an error here, the exit code is checked.
$ErrorActionPreference = "Continue"

. (Join-Path $PSScriptRoot "..\lib\rt-finish.ps1")

function Write-Refused([string[]]$Reasons) {
    Write-Host ""
    foreach ($r in $Reasons) { Write-Host "[REFUSED] $r" -ForegroundColor Red }
    Write-Host ""
    Write-Host "Nothing was changed." -ForegroundColor Red
}

function Get-Git([string]$Dir, [string[]]$GitArgs) {
    <# Purpose: run git in a folder and return its trimmed stdout, or "" on failure. #>
    $out = & git -C $Dir @GitArgs 2>$null
    if ($LASTEXITCODE -ne 0) { return "" }
    return (($out | Out-String).Trim())
}

# --- facts -------------------------------------------------------------------------------
if (-not (Test-RtBranchName $Branch) -or $Branch -eq $MainBranch) {
    Write-Refused @("'$Branch' is not a branch this script will clean (it must start with a letter or digit, hold letters, digits, . _ / - only, and not be $MainBranch).")
    exit 2
}
if ($PlansFolder -and -not (Test-RtPlansFolderName $PlansFolder)) {
    Write-Refused @("-PlansFolder must be a bare folder name under docs/superpowers/todo, got '$PlansFolder'.")
    exit 2
}
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Write-Refused @("git was not found on PATH.")
    exit 2
}

$scriptRepo = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\.."))
$common = Get-Git $scriptRepo @("rev-parse", "--path-format=absolute", "--git-common-dir")
if (-not $common) {
    Write-Refused @("$scriptRepo is not inside a git repository.")
    exit 2
}
$mainRoot = [System.IO.Path]::GetFullPath((Split-Path ($common -replace '/', '\') -Parent))
# No Set-Location: this script runs in the caller's shell, which must stay where it was.

# gh: is there a merged pull request with this branch as its head, and where did it end?
$prMerged = $false; $prReason = ""; $prHead = ""
if (-not (Get-Command gh -ErrorAction SilentlyContinue)) {
    $prReason = "gh was not found on PATH, so the pull request cannot be checked"
} else {
    # stdout is the JSON; stderr (an update notice, an auth warning) goes to a file so it can never
    # end up inside the text that is parsed. gh needs the main clone as its folder to find the repo.
    $ghErrFile = [System.IO.Path]::GetTempFileName()
    Push-Location -LiteralPath $mainRoot
    try { $raw = & gh pr list --head $Branch --state merged --json "number,headRefOid" 2>$ghErrFile; $ghCode = $LASTEXITCODE }
    finally { Pop-Location }
    $ghErr = [string](Get-Content -LiteralPath $ghErrFile -Raw -ErrorAction SilentlyContinue)
    Remove-Item -LiteralPath $ghErrFile -Force -ErrorAction SilentlyContinue
    if ($ghCode -ne 0) {
        $prReason = "gh failed: $($ghErr.Trim())"
    } else {
        $prs = @()
        # Windows PowerShell 5.1 hands a JSON array through the pipeline as ONE object, so "[]"
        # becomes a single empty array and "no merged pull request" would read as "one merged".
        # Iterating with foreach flattens it; only entries that carry a head commit count.
        try {
            $parsed = ConvertFrom-Json -InputObject ($raw | Out-String)
            foreach ($p in $parsed) {
                if ($null -ne $p -and $null -ne $p.PSObject.Properties["headRefOid"]) { $prs += $p }
            }
        } catch { $prReason = "gh answered something that is not JSON" }
        if ($prs.Count -gt 0) { $prMerged = $true; $prHead = [string]$prs[0].headRefOid }
    }
}

# worktree holding the branch
$worktree = ""
$current = ""
foreach ($line in ((& git -C $mainRoot worktree list --porcelain 2>$null) -split "`r?`n")) {
    if ($line -like "worktree *") { $current = $line.Substring(9) }
    elseif ($line -eq "branch refs/heads/$Branch") { $worktree = [System.IO.Path]::GetFullPath(($current -replace '/', '\')); break }
}

$localOid = Get-Git $mainRoot @("rev-parse", "--verify", "--quiet", "refs/heads/$Branch")
# The exact ref, and the exit code: ls-remote with a bare name matches every branch that ENDS
# with it, and a failed call returns nothing, which is not the same as "the branch is gone".
$remoteExists = $false; $remoteOid = ""; $remoteError = ""
$lsOut = & git -C $mainRoot ls-remote --heads origin "refs/heads/$Branch" 2>&1
if ($LASTEXITCODE -ne 0) {
    $remoteError = ((($lsOut | Out-String).Trim() -split "`r?`n") | Select-Object -Last 1)
    if (-not $remoteError) { $remoteError = "git ls-remote exited with code $LASTEXITCODE" }
} else {
    foreach ($line in (($lsOut | Out-String) -split "`r?`n")) {
        $parts = $line.Trim() -split "\s+"
        if ($parts.Count -ge 2 -and $parts[1] -eq "refs/heads/$Branch") { $remoteExists = $true; $remoteOid = $parts[0] }
    }
}
$plansPresent = $false
if ($PlansFolder) { $plansPresent = Test-Path -LiteralPath (Join-Path $mainRoot "docs\superpowers\todo\$PlansFolder") }

if (-not $worktree -and -not $localOid -and -not $remoteExists -and -not $plansPresent -and -not $remoteError) {
    Write-Host "Nothing to clean: no worktree, no local branch and no branch on origin for $Branch." -ForegroundColor Green
    exit 0
}

$dirty = @(); $links = @(); $ignored = @()
if ($worktree -and (Test-Path -LiteralPath $worktree)) {
    $status = @((& git -C $worktree status --porcelain --ignored 2>$null) | Where-Object { $_ })
    $dirty = @($status | Where-Object { $_ -notlike '!! *' })
    $ignored = @($status | Where-Object { $_ -like '!! *' })
    $links = @(Find-RtReparsePoints -Root $worktree)
}
$runFromWorktree = [bool]($worktree -and ($scriptRepo.TrimEnd('\') -ieq $worktree.TrimEnd('\')))
$mainHead = Get-Git $mainRoot @("symbolic-ref", "--short", "HEAD")
$mainDirty = @((& git -C $mainRoot status --porcelain --untracked-files=no 2>$null) | Where-Object { $_ })

$reasons = @(Get-RtFinishRefusals -Branch $Branch -PrMerged $prMerged -PrReason $prReason -PrHeadOid $prHead `
    -LocalOid $localOid -RemoteOid $remoteOid -RemoteError $remoteError -WorktreePath $worktree -DirtyFiles $dirty -Links $links `
    -IgnoredFiles $ignored -DiscardIgnored $DiscardIgnored.IsPresent -MainDirty $mainDirty `
    -MainHead $mainHead -MainBranch $MainBranch -RunFromWorktree $runFromWorktree)
if (@($reasons).Count -gt 0) {
    Write-Refused $reasons
    exit 2
}

$steps = @(Resolve-RtFinishSteps -Branch $Branch -MainBranch $MainBranch -WorktreePath $(if ($worktree -and (Test-Path -LiteralPath $worktree)) { $worktree } else { "" }) `
    -LocalExists ([bool]$localOid) -RemoteExists $remoteExists -PlansFolder $PlansFolder -PlansPresent $plansPresent)

Write-Host ""
Write-Host "=== finish-branch: $Branch (merged on GitHub) ===" -ForegroundColor Cyan
Write-Host "  main clone : $mainRoot"
if ($worktree) { Write-Host "  worktree   : $worktree" }
$n = 0
foreach ($s in $steps) {
    $n++
    $what = if ($s.Kind -eq "git") { "git " + ($s.Argv -join " ") } else { "move $($s.From) -> $($s.To)" }
    Write-Host ("  {0}. {1}   [{2}]" -f $n, $s.Label, $what)
}

if (-not $Yes) {
    Write-Host ""
    Write-Host "Dry run: nothing was changed. Run again with -Yes to do it." -ForegroundColor DarkGray
    exit 0
}

# --- do it -------------------------------------------------------------------------------
$done = @(); $ok = $true
foreach ($s in $steps) {
    $detail = ""
    if ($s.Kind -eq "git") {
        $out = & git -C $mainRoot @($s.Argv) 2>&1
        $good = ($LASTEXITCODE -eq 0)
        $detail = (($out | Out-String).Trim() -split "`r?`n" | Select-Object -Last 1)
    } else {
        $from = Join-Path $mainRoot ($s.From -replace '/', '\')
        $to = Join-Path $mainRoot ($s.To -replace '/', '\')
        $good = $false
        if (Test-Path -LiteralPath $to) { $detail = "destination already exists: $($s.To)" }
        else {
            try {
                New-Item -ItemType Directory -Path (Split-Path $to -Parent) -Force | Out-Null
                Move-Item -LiteralPath $from -Destination $to -ErrorAction Stop
                $good = $true
            } catch { $detail = $_.Exception.Message }
        }
    }
    $done += [PSCustomObject]@{ id = $s.Id; label = $s.Label; ok = $good; detail = $detail }
    if ($good) { Write-Host "  [OK]   $($s.Label)" -ForegroundColor Green }
    else {
        Write-Host "  [FAIL] $($s.Label): $detail" -ForegroundColor Red
        $ok = $false
        break
    }
}

if ($ReportPath) {
    $rep = [PSCustomObject]@{ branch = $Branch; ok = $ok; steps = $done }
    [System.IO.File]::WriteAllText($ReportPath, ($rep | ConvertTo-Json -Depth 5), (New-Object System.Text.UTF8Encoding($false)))
}

Write-Host ""
if ($ok) { Write-Host "Done. $Branch is cleaned up." -ForegroundColor Green; exit 0 }
Write-Host "Stopped at the failed step above. The later steps were not run." -ForegroundColor Red
exit 1
