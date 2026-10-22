# rt-finish.ps1 - the decisions of scripts\test\finish-branch.ps1, with no side effect.
#
# Dot-sourced by finish-branch.ps1 and by scripts\test\verify-branch-tools.ps1. The script
# spawns git and gh, which cannot be tested offline, so what it decides lives here as pure
# functions (the same split as rt-sync.ps1 and rt-update.ps1). Nothing here runs a process.

function Get-RtFinishRefusals {
    <#
        --------------------------------------------------------------------------
        Purpose:
            List every reason cleaning a merged branch must NOT start. An empty
            list means it may. All reasons are returned at once, so one run tells
            the operator everything to fix.

        Inputs:
            Branch (string): the branch to clean, for example feat/x
            PrMerged (bool): a merged pull request has this branch as its head
            PrReason (string): why PrMerged is false, may be empty
            PrHeadOid (string): the commit the merged pull request ended on
            LocalOid (string): the commit the local branch is on, empty when none
            RemoteOid (string): the commit origin's branch is on, empty when it is gone
            WorktreePath (string): the worktree holding the branch, empty when none
            DirtyFiles (string[]): output of git status --porcelain in that worktree
            Links (string[]): junctions and symbolic links found in that worktree
            IgnoredFiles (string[]): git-ignored entries in that worktree (git status
                --porcelain --ignored lines starting with "!!"); git worktree remove
                deletes them without a word
            DiscardIgnored (bool): the operator accepted losing those ignored entries
            MainDirty (string[]): modified tracked files in the main clone; the pull
                would rewrite files another session may be editing (R32)
            MainHead (string): the branch checked out in the main clone
            MainBranch (string): the branch that must be checked out there
            RunFromWorktree (bool): this script was started from inside the worktree

        Outputs:
            reasons (string[]): one sentence per refusal, with the remedy
        --------------------------------------------------------------------------
    #>
    param(
        [Parameter(Mandatory = $true)][string]$Branch,
        [Parameter(Mandatory = $true)][bool]$PrMerged,
        [string]$PrReason = "",
        [string]$PrHeadOid = "",
        [string]$LocalOid = "",
        [string]$RemoteOid = "",
        [string]$WorktreePath = "",
        [string[]]$DirtyFiles = @(),
        [string[]]$Links = @(),
        [string[]]$IgnoredFiles = @(),
        [bool]$DiscardIgnored = $false,
        [string[]]$MainDirty = @(),
        [Parameter(Mandatory = $true)][string]$MainHead,
        [Parameter(Mandatory = $true)][string]$MainBranch,
        [bool]$RunFromWorktree = $false
    )
    $reasons = @()
    if (-not $PrMerged) {
        $why = if ($PrReason) { $PrReason } else { "no merged pull request has $Branch as its head" }
        $reasons += "the branch is not merged: $why. Merge the pull request on GitHub first."
    }
    if ($PrMerged -and $LocalOid -and $PrHeadOid -and ($LocalOid -ne $PrHeadOid)) {
        $reasons += "the local branch is on $($LocalOid.Substring(0, [Math]::Min(7, $LocalOid.Length))) but the merged pull request ended on $($PrHeadOid.Substring(0, [Math]::Min(7, $PrHeadOid.Length))): the branch holds commits that were never pushed. Push or save them, then run again."
    }
    if ($PrMerged -and $RemoteOid -and $PrHeadOid -and ($RemoteOid -ne $PrHeadOid)) {
        $reasons += "origin/$Branch is on $($RemoteOid.Substring(0, [Math]::Min(7, $RemoteOid.Length))) but the merged pull request ended on $($PrHeadOid.Substring(0, [Math]::Min(7, $PrHeadOid.Length))): a commit was pushed after the merge, and deleting the branch would lose it. Look at it first."
    }
    if (@($MainDirty).Count -gt 0) {
        $reasons += "the main clone has $(@($MainDirty).Count) modified tracked file(s) ($((@($MainDirty) | Select-Object -First 3) -join '; ')): another session may be editing there, and the pull would rewrite files under it (R32). Commit or restore them, then run again."
    }
    if ($MainHead -ne $MainBranch) {
        $reasons += "the main clone has $MainHead checked out, not $MainBranch. This script never switches the checked-out branch (R32): switch it yourself after checking no other session is working there."
    }
    if ($WorktreePath) {
        if ($RunFromWorktree) {
            $reasons += "this script was started from inside the worktree it must remove. Run the copy in the main clone instead."
        }
        if (@($DirtyFiles).Count -gt 0) {
            $reasons += "the worktree has $(@($DirtyFiles).Count) uncommitted or untracked file(s): commit or discard them first."
        }
        if (@($IgnoredFiles).Count -gt 0 -and -not $DiscardIgnored) {
            $reasons += "the worktree holds $(@($IgnoredFiles).Count) git-ignored entr(y/ies) ($((@($IgnoredFiles) | Select-Object -First 5) -join '; ')) that git worktree remove deletes without warning. Keep what you need, then run again with -DiscardIgnored."
        }
        if (@($Links).Count -gt 0) {
            $reasons += "the worktree holds a junction or symbolic link ($((@($Links)) -join ', ')); removing the worktree would follow it and delete its target (R37). Remove each link with: cmd /c rmdir <link>"
        }
    }
    return $reasons
}

function Resolve-RtFinishSteps {
    <#
        --------------------------------------------------------------------------
        Purpose:
            Give the ordered steps that clean a merged branch, as data. The caller
            runs each Argv with git and stops at the first failure.

        Inputs:
            Branch (string): the branch to clean
            MainBranch (string): the branch to bring up to date first
            WorktreePath (string): the worktree to remove, empty when there is none
            LocalExists (bool): the local branch exists
            RemoteExists (bool): origin still has the branch
            PlansFolder (string): a name under docs/superpowers/todo to move to done,
                empty to skip
            PlansPresent (bool): that folder exists

        Outputs:
            steps (object[]): Id, Label, Kind ("git" or "move"), Argv (git arguments,
                run in the main clone) or From / To for a move
        --------------------------------------------------------------------------
    #>
    param(
        [Parameter(Mandatory = $true)][string]$Branch,
        [Parameter(Mandatory = $true)][string]$MainBranch,
        [string]$WorktreePath = "",
        [bool]$LocalExists = $true,
        [bool]$RemoteExists = $true,
        [string]$PlansFolder = "",
        [bool]$PlansPresent = $false
    )
    $steps = @()
    $steps += [PSCustomObject]@{ Id = "pull"; Label = "bring $MainBranch up to date"; Kind = "git"; Argv = @("pull", "--ff-only", "origin", $MainBranch) }
    if ($WorktreePath) {
        # No --force: a worktree that needs it holds something the checks above should have named.
        $steps += [PSCustomObject]@{ Id = "worktree"; Label = "remove the worktree"; Kind = "git"; Argv = @("worktree", "remove", $WorktreePath) }
    }
    if ($LocalExists) {
        # -D, not -d: after a squash merge the branch tip is never an ancestor of main.
        # The caller has already proved the tip equals the merged pull request's last commit.
        $steps += [PSCustomObject]@{ Id = "branch"; Label = "delete the local branch"; Kind = "git"; Argv = @("branch", "-D", $Branch) }
    }
    if ($RemoteExists) {
        $steps += [PSCustomObject]@{ Id = "remote"; Label = "delete the branch on origin"; Kind = "git"; Argv = @("push", "origin", "--delete", $Branch) }
    }
    $steps += [PSCustomObject]@{ Id = "prune"; Label = "prune worktree records"; Kind = "git"; Argv = @("worktree", "prune") }
    $steps += [PSCustomObject]@{ Id = "fetch"; Label = "drop remote-tracking references that are gone"; Kind = "git"; Argv = @("fetch", "--prune") }
    if ($PlansFolder -and $PlansPresent) {
        $steps += [PSCustomObject]@{ Id = "plans"; Label = "move the plans from todo to done"; Kind = "move"; Argv = @(); From = "docs/superpowers/todo/$PlansFolder"; To = "docs/superpowers/done/$PlansFolder" }
    }
    return $steps
}

function Test-RtPlansFolderName {
    <#
        Purpose: accept only a bare folder name for -PlansFolder (R24), so it cannot
        walk out of docs/superpowers/todo.
        Inputs: Name (string)
        Outputs: valid (bool)
    #>
    param([string]$Name)
    if ([string]::IsNullOrWhiteSpace($Name)) { return $false }
    if ($Name -match '[\\/:]' -or $Name -eq '.' -or $Name -eq '..' -or $Name.Contains('..')) { return $false }
    return $true
}
