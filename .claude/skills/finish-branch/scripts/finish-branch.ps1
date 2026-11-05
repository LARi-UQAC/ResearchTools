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
        .\.claude\skills\finish-branch\scripts\finish-branch.ps1 -Branch feat/my-branch          # dry run
        .\.claude\skills\finish-branch\scripts\finish-branch.ps1 -Branch feat/my-branch -Yes

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

.PARAMETER Refresh
    After the clean-up (or when there is nothing to clean), refresh this machine from the
    updated main: setup.ps1 -Update -Profile <active> -RunSuite -NonInteractive -Force, with
    -Personal when the merged pull request changed an agent, a command or a rule (or its file list could not be read whole). The profile is read
    from the active_profile line of the main clone's .claude/CLAUDE.md; a missing line is a
    refusal (R8). A dry run prints the command and runs nothing. A reminder to publish the
    site (mkdocs gh-deploy) is printed when the merged pull request changed docs/.

.PARAMETER KeepHooks
    With -Refresh: hook entry names setup.ps1 must leave as they are on this machine.

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
    [switch]$Refresh,
    [string[]]$KeepHooks = @(),
    [switch]$Yes
)

Set-StrictMode -Version Latest
# Native commands write progress to stderr; that is not an error here, the exit code is checked.
$ErrorActionPreference = "Continue"

. (Join-Path $PSScriptRoot "rt-finish.ps1")
# Get-RtActiveProfile has one definition, in scripts\lib\rt-update.ps1 (review round 1, #5). A copy
# outside the repository has no such file; it is refused below as outside git.
$updateLib = Join-Path $PSScriptRoot "..\..\..\..\scripts\lib\rt-update.ps1"
if (Test-Path -LiteralPath $updateLib -PathType Leaf) { . $updateLib }

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

# The script sits in <repo>\.claude\skills\finish-branch\scripts, four levels below the root.
$scriptRepo = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\..\..\.."))
# Started through a junction (~/.claude/skills/finish-branch is one), "four levels up" is not the
# repository but whatever folder holds the junction, possibly another git repository. Refuse
# rather than act there (review round 2).
$walk = [System.IO.Path]::GetFullPath($PSScriptRoot)
while ($walk -and ($walk.TrimEnd('\') -ne $scriptRepo.TrimEnd('\'))) {
    $item = Get-Item -LiteralPath $walk -Force -ErrorAction SilentlyContinue
    if ($null -ne $item -and ($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint)) {
        Write-Refused @("this script was started through a junction or symbolic link ($walk). Run the copy inside the ResearchTools clone (.claude\skills\finish-branch\scripts\finish-branch.ps1 in the main clone).")
        exit 2
    }
    $walk = Split-Path $walk -Parent
}
$common = Get-Git $scriptRepo @("rev-parse", "--path-format=absolute", "--git-common-dir")
if (-not $common) {
    Write-Refused @("$scriptRepo is not inside a git repository. Run the script that sits in the ResearchTools clone (.claude\skills\finish-branch\scripts\finish-branch.ps1 in the main clone), not a copy or a path through a ~/.claude junction.")
    exit 2
}
$mainRoot = [System.IO.Path]::GetFullPath((Split-Path ($common -replace '/', '\') -Parent))
# No Set-Location: this script runs in the caller's shell, which must stay where it was.

# -Refresh needs the active profile and setup.ps1; refuse before anything else is looked at.
$profileName = ""; $setupScript = Join-Path $mainRoot "setup.ps1"
if ($Refresh) {
    if (-not (Get-Command Get-RtActiveProfile -ErrorAction SilentlyContinue)) {
        Write-Refused @("-Refresh needs scripts\lib\rt-update.ps1 beside this repository's scripts, and it was not found."); exit 2
    }
    $profileName = Get-RtActiveProfile -ClaudeMdPath (Join-Path $mainRoot ".claude\CLAUDE.md")
    $why = @()
    if (-not $profileName) { $why += "-Refresh needs the 'active_profile: <name>' line in $mainRoot\.claude\CLAUDE.md, and none was found; no profile is guessed." }
    if (-not (Test-Path -LiteralPath $setupScript -PathType Leaf)) { $why += "-Refresh needs $setupScript, which does not exist." }
    if ($why.Count -gt 0) { Write-Refused $why; exit 2 }
}

# `gh pr view --json files` lists at most 100 files (gh queries one GraphQL page of 100; raised
# by review round 1, #4, not measured here); a list that long is treated as incomplete.
$GhFilesCap = 100

function Get-PrFiles([string]$Number) {
    <#
        Purpose: paths changed by merged PR $Number, via gh.
        Outputs: PSCustomObject Files (string[]) and Unknown (bool, true when there is no PR
        number, gh failed, or the list reached the gh cap). The callers then assume the
        conservative case (-Personal, gh-deploy reminder) rather than a silently partial list.
    #>
    if (-not $Number) {
        Write-Host "  [WARN] no merged pull request number is known; the refresh assumes agents, commands, rules and docs changed." -ForegroundColor Yellow
        return [PSCustomObject]@{ Files = @(); Unknown = $true }
    }
    $errFile = [System.IO.Path]::GetTempFileName()
    Push-Location -LiteralPath $mainRoot
    try { $raw = & gh pr view $Number --json files 2>$errFile; $code = $LASTEXITCODE }
    finally { Pop-Location; Remove-Item -LiteralPath $errFile -Force -ErrorAction SilentlyContinue }
    $paths = @()
    if ($code -eq 0) {
        try {
            $parsed = ConvertFrom-Json -InputObject ($raw | Out-String)
            if ($null -ne $parsed -and $null -ne $parsed.PSObject.Properties["files"]) {
                foreach ($f in $parsed.files) { if ($f.path) { $paths += [string]$f.path } }
            }
        } catch { $code = 1 }
    }
    $unknown = ($code -ne 0 -or $paths.Count -ge $GhFilesCap)
    if ($code -ne 0) { Write-Host "  [WARN] the files of pull request #$Number could not be read; the refresh assumes the worst case." -ForegroundColor Yellow }
    elseif ($unknown) { Write-Host "  [WARN] pull request #$Number lists $($paths.Count) files, the gh cap; the refresh assumes the worst case." -ForegroundColor Yellow }
    return [PSCustomObject]@{ Files = $paths; Unknown = $unknown }
}

$script:refreshRecord = $null
function Invoke-Refresh($Info) {
    <# Purpose: print, or with -Yes run, setup.ps1 with the refresh arguments; record the outcome for the report. Outputs: exit code (0 in a dry run). #>
    $argv = @(Get-RtRefreshArgs -ProfileName $profileName -ChangedFiles $Info.Files -KeepHooks $KeepHooks -FilesUnknown:([bool]$Info.Unknown))
    $shown = "setup.ps1 " + ($argv -join " ")
    if (-not $Yes) {
        Write-Host "  refresh (dry run, not run): $shown"
        $script:refreshRecord = [PSCustomObject]@{ ran = $false; code = 0; command = $shown }
        return 0
    }
    Write-Host ""
    Write-Host "=== machine refresh: $shown ===" -ForegroundColor Cyan
    & powershell -NoProfile -ExecutionPolicy Bypass -File $setupScript @argv | Out-Host
    $code = $LASTEXITCODE
    if ($code -ne 0) { Write-Host "  [FAIL] machine refresh: setup.ps1 exited $code" -ForegroundColor Red }
    else { Write-Host "  [OK]   machine refresh" -ForegroundColor Green }
    $script:refreshRecord = [PSCustomObject]@{ ran = $true; code = $code; command = $shown }
    return $code
}

function Write-Reminders($Info) {
    <# Purpose: print the owner's remaining steps (gh-deploy) for the merged PR's files. #>
    foreach ($r in @(Get-RtFinishReminders -ChangedFiles $Info.Files -FilesUnknown:([bool]$Info.Unknown))) { Write-Host "  [TODO] $r" -ForegroundColor Yellow }
}

function Write-Report([bool]$Ok, $Steps) {
    <# Purpose: write the -ReportPath JSON (R17), the refresh outcome included (review round 1, #6). Outputs: none. #>
    if (-not $ReportPath) { return }
    $rep = [PSCustomObject]@{ branch = $Branch; ok = $Ok; steps = @($Steps); refresh = $script:refreshRecord }
    [System.IO.File]::WriteAllText($ReportPath, ($rep | ConvertTo-Json -Depth 5), (New-Object System.Text.UTF8Encoding($false)))
}

# gh: is there a merged pull request with this branch as its head, and where did it end?
$prMerged = $false; $prReason = ""; $prHead = ""; $prNumber = ""
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
        if ($prs.Count -gt 0) {
            $prMerged = $true; $prHead = [string]$prs[0].headRefOid
            if ($null -ne $prs[0].PSObject.Properties["number"]) { $prNumber = [string]$prs[0].number }
        }
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

$mainHead = Get-Git $mainRoot @("symbolic-ref", "--short", "HEAD")
$mainDirty = @((& git -C $mainRoot status --porcelain --untracked-files=no 2>$null) | Where-Object { $_ })

if (-not $worktree -and -not $localOid -and -not $remoteExists -and -not $plansPresent -and -not $remoteError) {
    Write-Host "Nothing to clean: no worktree, no local branch and no branch on origin for $Branch." -ForegroundColor Green
    if ($Refresh) {
        # The refresh rewrites mirrors and syncs ~/.claude from the main clone: it needs the same
        # main-clone guarantees as the clean-up (R32), and an up-to-date main (review round 1, #1, #2).
        $why = @()
        if (-not $prMerged) {
            $detail = if ($prReason) { " ($prReason)" } else { "" }
            $why += "no merged pull request has '$Branch' as its head$detail; the refresh runs only after a merge. Check the branch name (review round 2)."
        }
        if ($mainHead -ne $MainBranch) { $why += "the main clone is on '$mainHead', not '$MainBranch'; the refresh never switches the checked-out branch (R32)." }
        if ($mainDirty.Count -gt 0) { $why += "the main clone has modified tracked files ($(($mainDirty | Select-Object -First 3) -join '; ')); the refresh would rewrite files under another session (R32)." }
        if ($why.Count -gt 0) { Write-Refused $why; exit 2 }
        if (-not $Yes) {
            Write-Host "  pull (dry run, not run): git pull --ff-only origin $MainBranch"
        } else {
            $out = & git -C $mainRoot pull --ff-only origin $MainBranch 2>&1
            if ($LASTEXITCODE -ne 0) {
                Write-Host "  [FAIL] git pull --ff-only origin ${MainBranch}: $((($out | Out-String).Trim() -split "`r?`n") | Select-Object -Last 1)" -ForegroundColor Red
                Write-Report $false @()
                exit 1
            }
            Write-Host "  [OK]   bring $MainBranch up to date" -ForegroundColor Green
        }
        $info = Get-PrFiles $prNumber
        $rc = Invoke-Refresh $info
        Write-Reminders $info
        Write-Report ($rc -eq 0) @()
        if ($rc -ne 0) { exit 1 }
    } else {
        Write-Report $true @()
    }
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
    if ($Refresh) { $info = Get-PrFiles $prNumber; [void](Invoke-Refresh $info); Write-Reminders $info }
    Write-Report $true @()   # a dry run reports too, like the nothing-to-clean path (review round 2)
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

Write-Host ""
if ($ok) {
    Write-Host "Done. $Branch is cleaned up." -ForegroundColor Green
    if ($Refresh) {
        $info = Get-PrFiles $prNumber
        $rc = Invoke-Refresh $info
        Write-Reminders $info
        Write-Report ($rc -eq 0) $done
        if ($rc -ne 0) { exit 1 }
        exit 0
    }
    Write-Report $true $done
    exit 0
}
Write-Report $false $done
Write-Host "Stopped at the failed step above. The later steps were not run." -ForegroundColor Red
exit 1
