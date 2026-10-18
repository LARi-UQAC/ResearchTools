#Requires -Version 5.1
<#
.SYNOPSIS
    Offline check of scripts\test\run-all-checks.ps1 and scripts\test\finish-branch.ps1.

.DESCRIPTION
    Both scripts spawn processes (git, gh, powershell), so what they decide lives in
    scripts\lib\rt-checks.ps1 and scripts\lib\rt-finish.ps1 and is checked here as pure
    functions. Then each script is RUN for real, in a child process, against a throwaway
    world under $env:TEMP: a bare origin, a main clone, real worktrees with real junctions
    (R37), and a stub gh.cmd placed first on PATH. There is no bypass flag in either script
    for the tests to use, so what is proven here is what a user gets.

    Every case that refuses is paired with a case that proceeds (R20), and the refusal cases
    assert that nothing was removed.

.SAFETY
    Everything is created under $env:TEMP with fictitious names (R34). GIT_CONFIG_GLOBAL and
    GIT_CONFIG_NOSYSTEM point git at a scratch config, so the operator's global hooks and
    identity are never used. The live repository and ~/.claude are never touched.

.EXAMPLE
    .\scripts\test\verify-branch-tools.ps1
#>

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$Tmp      = Join-Path $env:TEMP "rt-branch-tools-$PID"
$failures = 0
. (Join-Path $RepoRoot "scripts\lib\rt-checks.ps1")
. (Join-Path $RepoRoot "scripts\lib\rt-finish.ps1")

function Check([string]$name, [bool]$ok) {
    if ($ok) { Write-Host "  PASS  $name" -ForegroundColor DarkGray }
    else     { Write-Host "  FAIL  $name" -ForegroundColor Red; $script:failures++ }
}

function Write-Text([string]$Path, [string]$Text) {
    $dir = Split-Path $Path -Parent
    if (-not (Test-Path -LiteralPath $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
    [System.IO.File]::WriteAllText($Path, $Text, (New-Object System.Text.UTF8Encoding($false)))
}

function Invoke-Child([string]$Script, [string[]]$ScriptArgs = @(), [string]$Cwd = $Tmp, [string]$PathPrefix = "") {
    $ErrorActionPreference = "Continue"   # a child's stderr is output here, its exit code is what is checked
    $oldPath = $env:PATH
    if ($PathPrefix) { $env:PATH = "$PathPrefix;$oldPath" }
    Push-Location $Cwd
    try {
        $out = & powershell -NoProfile -ExecutionPolicy Bypass -File $Script @ScriptArgs *>&1 | Out-String
        return [PSCustomObject]@{ Code = $LASTEXITCODE; Text = $out }
    } finally { Pop-Location; $env:PATH = $oldPath }
}

Write-Host ""
Write-Host "=== branch tools: run-all-checks and finish-branch ===" -ForegroundColor Cyan
New-Item -ItemType Directory -Path $Tmp -Force | Out-Null

# --- the decisions, as pure functions ------------------------------------------------
Write-Host ""
Write-Host "  -- decisions --" -ForegroundColor DarkCyan

$ok = @(Get-RtFinishRefusals -Branch "feat/x" -PrMerged $true -PrHeadOid "aaaaaaa1" -LocalOid "aaaaaaa1" `
        -WorktreePath "W" -MainHead "main" -MainBranch "main")
Check "a merged, clean, pushed branch has no refusal" (@($ok).Count -eq 0)
$r = @(Get-RtFinishRefusals -Branch "feat/x" -PrMerged $false -PrReason "gh not found" -MainHead "main" -MainBranch "main")
Check "an unmerged branch is refused, with the reason" (@($r).Count -eq 1 -and $r[0] -like "*gh not found*")
$r = @(Get-RtFinishRefusals -Branch "feat/x" -PrMerged $true -PrHeadOid "aaaaaaa1" -LocalOid "bbbbbbb2" -MainHead "main" -MainBranch "main")
Check "a local tip that differs from the merged one is refused (unpushed commits)" (@($r).Count -eq 1 -and $r[0] -like "*never pushed*")
$r = @(Get-RtFinishRefusals -Branch "feat/x" -PrMerged $true -MainHead "other" -MainBranch "main")
Check "a main clone on another branch is refused, never switched (R32)" (@($r).Count -eq 1 -and $r[0] -like "*never switches*")
$r = @(Get-RtFinishRefusals -Branch "feat/x" -PrMerged $true -WorktreePath "W" -DirtyFiles @("?? a") -Links @("W\lnk") `
        -MainHead "main" -MainBranch "main" -RunFromWorktree $true)
Check "every reason is returned at once" (@($r).Count -eq 3)
Check "a link names the remedy that deletes the link and not its target" (($r -join " ") -like "*cmd /c rmdir*")
$r = @(Get-RtFinishRefusals -Branch "feat/x" -PrMerged $true -DirtyFiles @("?? a") -Links @("W\lnk") -MainHead "main" -MainBranch "main")
Check "(control) dirty files and links are ignored when there is no worktree" (@($r).Count -eq 0)

$s = Resolve-RtFinishSteps -Branch "feat/x" -MainBranch "main" -WorktreePath "W" -PlansFolder "p1" -PlansPresent $true
Check "the steps run in the safe order" ((($s | ForEach-Object { $_.Id }) -join ",") -eq "pull,worktree,branch,remote,prune,fetch,plans")
Check "the worktree is removed without --force" (-not (($s | Where-Object Id -eq "worktree").Argv -contains "--force"))
Check "the local branch uses -D, since a squash merge is never an ancestor" ((($s | Where-Object Id -eq "branch").Argv) -contains "-D")
$s = Resolve-RtFinishSteps -Branch "feat/x" -MainBranch "main" -LocalExists $false -RemoteExists $false
Check "(control) nothing is deleted that is not there" ((($s | ForEach-Object { $_.Id }) -join ",") -eq "pull,prune,fetch")
$np = Resolve-RtFinishSteps -Branch "b" -MainBranch "main" -PlansFolder "p1" -PlansPresent $false
Check "a plans folder that is not there is not moved" (-not (@($np | Where-Object Id -eq "plans").Count))

Check "a plain folder name is accepted" (Test-RtPlansFolderName "2026-10-17-update")
Check "a name with a separator or .. is refused (R24)" (-not (Test-RtPlansFolderName "..\x") -and -not (Test-RtPlansFolderName "a/b") -and -not (Test-RtPlansFolderName "..") -and -not (Test-RtPlansFolderName "C:x"))
Check "an empty name is refused" (-not (Test-RtPlansFolderName ""))

# --- the check list -------------------------------------------------------------------
Write-Host ""
Write-Host "  -- the check list --" -ForegroundColor DarkCyan
$Fx = Join-Path $Tmp "checks"
foreach ($n in @("run-offline-tests", "verify-b", "verify-a", "verify-graph-health")) {
    $code = if ($n -eq "verify-b") { 3 } else { 0 }
    Write-Text (Join-Path $Fx "$n.ps1") "Set-Content -LiteralPath (Join-Path `$PSScriptRoot '$n.ran') -Value 'x'`r`nexit $code`r`n"
}
$list = @(Get-RtCheckList -TestDir $Fx -Exclude @("verify-graph-health.ps1"))
Check "the suite comes first, then the verifiers in name order" ((($list | ForEach-Object { $_.Name }) -join ",") -eq "run-offline-tests.ps1,verify-a.ps1,verify-b.ps1")
Check "the excluded verifier is left out" (-not (@($list | Where-Object Name -eq "verify-graph-health.ps1").Count))
Check "(control) it is listed when nothing is excluded" (@(Get-RtCheckList -TestDir $Fx | Where-Object Name -eq "verify-graph-health.ps1").Count -eq 1)
Check "-SkipSuite drops the suite" ((@(Get-RtCheckList -TestDir $Fx -SkipSuite -Exclude @("verify-graph-health.ps1") | ForEach-Object { $_.Name }) -join ",") -eq "verify-a.ps1,verify-b.ps1")
Check "-Only keeps the run order whatever the order given" ((@(Get-RtCheckList -TestDir $Fx -Only @("verify-b", "verify-a.ps1") | ForEach-Object { $_.Name }) -join ",") -eq "verify-a.ps1,verify-b.ps1")
$threw = $false; try { Get-RtCheckList -TestDir $Fx -Only @("nosuch") | Out-Null } catch { $threw = $_.Exception.Message -like "*nosuch*verify-a.ps1*" }
Check "an unknown -Only name is refused and the known ones are named" $threw
$real = @(Get-RtCheckList -TestDir (Join-Path $RepoRoot "scripts\test") -Exclude @("verify-graph-health.ps1") | ForEach-Object { $_.Name })
Check "on the real folder: the suite, setup-writes and sync-writes are in" (($real -contains "run-offline-tests.ps1") -and ($real -contains "verify-setup-writes.ps1") -and ($real -contains "verify-sync-writes.ps1"))
Check "on the real folder: the graph verifier is out (local-writer only)" (-not ($real -contains "verify-graph-health.ps1"))
Check "on the real folder: this verifier is in" ($real -contains "verify-branch-tools.ps1")

# --- run-all-checks.ps1, run for real -------------------------------------------------
Write-Host ""
Write-Host "  -- run-all-checks.ps1 --" -ForegroundColor DarkCyan
$runAll = Join-Path $RepoRoot "scripts\test\run-all-checks.ps1"
$report = Join-Path $Tmp "report.json"
$res = Invoke-Child $runAll @("-TestDir", $Fx, "-ReportPath", $report)
Check "run-all-checks.ps1 exists" (Test-Path -LiteralPath $runAll)
Check "one failing check makes the exit code 1" ($res.Code -eq 1)
Check "every check ran even though one failed" ((Test-Path (Join-Path $Fx "run-offline-tests.ran")) -and (Test-Path (Join-Path $Fx "verify-a.ran")) -and (Test-Path (Join-Path $Fx "verify-b.ran")))
Check "the graph verifier did not run" (-not (Test-Path (Join-Path $Fx "verify-graph-health.ran")))
$rep = $null; try { $rep = Get-Content -LiteralPath $report -Raw | ConvertFrom-Json } catch { $rep = $null }
Check "the JSON report names each check with its exit code" ($null -ne $rep -and @($rep.checks).Count -eq 3 -and (@($rep.checks | Where-Object { $_.name -eq "verify-b.ps1" })[0].exit_code -eq 3))
Check "the JSON report counts passed and failed" ($null -ne $rep -and $rep.failed -eq 1 -and $rep.passed -eq 2)
Check "the summary names the failing check" ($res.Text -match "FAIL.*verify-b\.ps1")

Get-ChildItem -LiteralPath $Fx -Filter "*.ran" | Remove-Item -Force
$res = Invoke-Child $runAll @("-TestDir", $Fx, "-Only", "verify-a")
Check "(control) only the named check runs, and all-green exits 0" ($res.Code -eq 0 -and (Test-Path (Join-Path $Fx "verify-a.ran")) -and -not (Test-Path (Join-Path $Fx "verify-b.ran")) -and -not (Test-Path (Join-Path $Fx "run-offline-tests.ran")))
Get-ChildItem -LiteralPath $Fx -Filter "*.ran" | Remove-Item -Force
$res = Invoke-Child $runAll @("-TestDir", $Fx, "-SkipSuite", "-Only", "verify-a,verify-b")
Check "-SkipSuite with -Only runs the verifiers and not the suite" ($res.Code -eq 1 -and (Test-Path (Join-Path $Fx "verify-b.ran")) -and -not (Test-Path (Join-Path $Fx "run-offline-tests.ran")))
Get-ChildItem -LiteralPath $Fx -Filter "*.ran" | Remove-Item -Force
$res = Invoke-Child $runAll @("-TestDir", $Fx, "-DryRun")
Check "-DryRun lists the checks and runs none of them (R16)" ($res.Code -eq 0 -and $res.Text -match "verify-a\.ps1" -and @(Get-ChildItem -LiteralPath $Fx -Filter "*.ran").Count -eq 0)
$res = Invoke-Child $runAll @("-TestDir", $Fx, "-Only", "nosuch")
Check "an unknown -Only name is a refusal, exit 2" ($res.Code -eq 2 -and $res.Text -match "nosuch")

# --- finish-branch.ps1, run for real --------------------------------------------------
Write-Host ""
Write-Host "  -- finish-branch.ps1 --" -ForegroundColor DarkCyan

$gitCfg = Join-Path $Tmp "gitconfig"
Write-Text $gitCfg "[user]`n`tname = Test Person`n`temail = test@example.org`n[init]`n`tdefaultBranch = main`n[core]`n`thooksPath = $($Tmp.Replace('\','/'))/nohooks`n[protocol `"file`"]`n`tallow = always`n"
New-Item -ItemType Directory -Path (Join-Path $Tmp "nohooks") -Force | Out-Null
$saved = @{ GC = $env:GIT_CONFIG_GLOBAL; NS = $env:GIT_CONFIG_NOSYSTEM; GS = $env:GH_STUB_FILE }
$env:GIT_CONFIG_GLOBAL = $gitCfg; $env:GIT_CONFIG_NOSYSTEM = "1"

try {
    function Invoke-Git([string]$Dir, [string[]]$GitArgs) {
        $ErrorActionPreference = "Continue"
        $out = & git -C $Dir @GitArgs 2>&1
        if ($LASTEXITCODE -ne 0) { throw "git $($GitArgs -join ' ') failed in ${Dir}: $out" }
        return ($out | Out-String).Trim()
    }

    $ErrorActionPreference = "Continue"   # git writes progress and warnings to stderr
    $origin = Join-Path $Tmp "origin.git"
    $main   = Join-Path $Tmp "main"
    & git init --bare -q $origin 2>&1 | Out-Null
    & git clone -q $origin $main 2>&1 | Out-Null
    Write-Text (Join-Path $main "README.md") "fixture`n"
    $finishSrc = Join-Path $RepoRoot "scripts\test\finish-branch.ps1"
    New-Item -ItemType Directory -Path (Join-Path $main "scripts\test"), (Join-Path $main "scripts\lib") -Force | Out-Null
    if (Test-Path -LiteralPath $finishSrc) { Copy-Item $finishSrc (Join-Path $main "scripts\test\finish-branch.ps1") -Force }
    Copy-Item (Join-Path $RepoRoot "scripts\lib\rt-finish.ps1") (Join-Path $main "scripts\lib\rt-finish.ps1") -Force
    Invoke-Git $main @("add", "-A") | Out-Null
    Invoke-Git $main @("commit", "-q", "-m", "fixture") | Out-Null
    Invoke-Git $main @("push", "-q", "origin", "main") | Out-Null

    $bin = Join-Path $Tmp "bin"
    Write-Text (Join-Path $bin "gh.cmd") "@echo off`r`ntype `"%GH_STUB_FILE%`"`r`n"
    $ghFile = Join-Path $Tmp "gh.json"
    $env:GH_STUB_FILE = $ghFile

    function New-Case([string]$Name) {
        $branch = "feat/$Name"
        $wt = Join-Path $main ".worktrees\$Name"
        Invoke-Git $main @("worktree", "add", "-q", "-b", $branch, $wt, "main") | Out-Null
        Write-Text (Join-Path $wt "$Name.txt") "work`n"
        Invoke-Git $wt @("add", "$Name.txt") | Out-Null
        Invoke-Git $wt @("commit", "-q", "-m", "work $Name") | Out-Null
        Invoke-Git $wt @("push", "-q", "origin", $branch) | Out-Null
        return [PSCustomObject]@{ Branch = $branch; Worktree = $wt; Oid = (Invoke-Git $wt @("rev-parse", "HEAD")) }
    }
    function Set-Merged($Case, [bool]$Merged = $true, [string]$Oid = "") {
        $o = if ($Oid) { $Oid } else { $Case.Oid }
        $json = if ($Merged) { "[{`"number`":88,`"headRefOid`":`"$o`"}]" } else { "[]" }
        Write-Text $ghFile $json
    }
    function Invoke-Finish($Case, [string[]]$More = @(), [string]$Script = "") {
        $s = if ($Script) { $Script } else { Join-Path $main "scripts\test\finish-branch.ps1" }
        return (Invoke-Child $s (@("-Branch", $Case.Branch) + $More) $main $bin)
    }
    function Alive($Case) {
        return ((Test-Path -LiteralPath $Case.Worktree) -and
                [bool](Invoke-Git $main @("branch", "--list", $Case.Branch)) -and
                [bool](Invoke-Git $main @("ls-remote", "--heads", "origin", $Case.Branch)))
    }

    Check "finish-branch.ps1 exists" (Test-Path -LiteralPath $finishSrc)

    $c1 = New-Case "c1"; Set-Merged $c1
    $res = Invoke-Finish $c1
    Check "no -Yes: a dry run, exit 0, and it says so" ($res.Code -eq 0 -and $res.Text -match "dry run")
    Check "no -Yes: the worktree, the branch and the remote branch are all still there (R16)" (Alive $c1)

    Set-Merged $c1 $false
    $res = Invoke-Finish $c1 @("-Yes")
    Check "(refusal) a branch with no merged pull request exits 2 and names it" ($res.Code -eq 2 -and $res.Text -match "not merged")
    Check "(refusal) nothing was removed" (Alive $c1)

    Set-Merged $c1
    Write-Text (Join-Path $c1.Worktree "stray.txt") "x`n"
    $res = Invoke-Finish $c1 @("-Yes")
    Check "(refusal) an untracked file in the worktree exits 2" ($res.Code -eq 2 -and $res.Text -match "uncommitted")
    Check "(refusal) nothing was removed" (Alive $c1)
    Remove-Item (Join-Path $c1.Worktree "stray.txt") -Force

    $target = Join-Path $Tmp "link-target"
    Write-Text (Join-Path $target "keep.txt") "precious`n"
    $link = Join-Path $c1.Worktree "lnk"
    & cmd /c mklink /J "$link" "$target" | Out-Null
    $res = Invoke-Finish $c1 @("-Yes")
    Check "(refusal) a junction in the worktree exits 2 and names it (R37)" ($res.Code -eq 2 -and $res.Text -match "junction")
    Check "(refusal) the junction target is intact and the worktree still there" ((Test-Path (Join-Path $target "keep.txt")) -and (Alive $c1))
    & cmd /c rmdir "$link" | Out-Null
    Check "the remedy it names removes the link and not its target" ((Test-Path (Join-Path $target "keep.txt")) -and -not (Test-Path $link))

    Set-Merged $c1 $true "0000000000000000000000000000000000000000"
    $res = Invoke-Finish $c1 @("-Yes")
    Check "(refusal) a local tip that is not the merged tip exits 2" ($res.Code -eq 2 -and $res.Text -match "never pushed")
    Check "(refusal) nothing was removed" (Alive $c1)

    Set-Merged $c1
    Invoke-Git $main @("checkout", "-q", "-b", "other") | Out-Null
    $res = Invoke-Finish $c1 @("-Yes")
    Check "(refusal) a main clone on another branch exits 2 and is not switched" ($res.Code -eq 2 -and $res.Text -match "never switches" -and (Invoke-Git $main @("symbolic-ref", "--short", "HEAD")) -eq "other")
    Invoke-Git $main @("checkout", "-q", "main") | Out-Null
    Invoke-Git $main @("branch", "-q", "-D", "other") | Out-Null

    $res = Invoke-Finish $c1 @("-Yes") (Join-Path $c1.Worktree "scripts\test\finish-branch.ps1")
    Check "(refusal) started from inside the worktree it would remove, exit 2" ($res.Code -eq 2 -and $res.Text -match "inside the worktree")
    Check "(refusal) nothing was removed" (Alive $c1)

    $res = Invoke-Finish $c1 @("-Yes", "-PlansFolder", "..\x")
    Check "(refusal) a -PlansFolder that walks out is refused (R24)" ($res.Code -eq 2 -and $res.Text -match "PlansFolder")

    # the proceeding case
    $c2 = New-Case "c2"; Set-Merged $c2
    $plans = Join-Path $main "docs\superpowers\todo\plan-c2"
    Write-Text (Join-Path $plans "spec.md") "spec`n"
    $rp = Join-Path $Tmp "finish-report.json"
    $res = Invoke-Finish $c2 @("-Yes", "-PlansFolder", "plan-c2", "-ReportPath", $rp)
    Check "-Yes on a merged, clean, pushed branch exits 0" ($res.Code -eq 0)
    Check "the worktree is gone" (-not (Test-Path -LiteralPath $c2.Worktree))
    Check "the local branch is gone" (-not [bool](Invoke-Git $main @("branch", "--list", $c2.Branch)))
    Check "the branch on origin is gone" (-not [bool](Invoke-Git $main @("ls-remote", "--heads", "origin", $c2.Branch)))
    Check "the plans moved from todo to done" ((-not (Test-Path $plans)) -and (Test-Path (Join-Path $main "docs\superpowers\done\plan-c2\spec.md")))
    Check "the other case is untouched by this one" (Alive $c1)
    $frep = $null; try { $frep = Get-Content -LiteralPath $rp -Raw | ConvertFrom-Json } catch { $frep = $null }
    Check "the JSON report lists the steps with their outcome" ($null -ne $frep -and @($frep.steps).Count -ge 5 -and $frep.ok -eq $true)
    $res = Invoke-Finish $c2 @("-Yes")
    Check "(idempotent) a second run finds nothing to clean and exits 0" ($res.Code -eq 0 -and $res.Text -match "nothing to clean")
    $script:finishSectionCompleted = $true
}
finally {
    $env:GIT_CONFIG_GLOBAL = $saved.GC; $env:GIT_CONFIG_NOSYSTEM = $saved.NS; $env:GH_STUB_FILE = $saved.GS
    if (-not $saved.GC) { Remove-Item Env:GIT_CONFIG_GLOBAL -ErrorAction SilentlyContinue }
    if (-not $saved.NS) { Remove-Item Env:GIT_CONFIG_NOSYSTEM -ErrorAction SilentlyContinue }
    if (-not $saved.GS) { Remove-Item Env:GH_STUB_FILE -ErrorAction SilentlyContinue }
    # Junctions were removed with rmdir above; list again before any recursive delete (R37).
    $left = @(Get-ChildItem -LiteralPath $Tmp -Force -Recurse -Attributes ReparsePoint -ErrorAction SilentlyContinue)
    foreach ($l in $left) { & cmd /c rmdir "$($l.FullName)" | Out-Null }
    Get-ChildItem -LiteralPath $Tmp -Force -Recurse -File -ErrorAction SilentlyContinue | ForEach-Object { $_.Attributes = 'Normal' }
    Remove-Item -LiteralPath $Tmp -Recurse -Force -ErrorAction SilentlyContinue
}

Check "the finish-branch section ran to its end (an abort is a failure, not a pass)" ((Get-Variable finishSectionCompleted -Scope Script -ValueOnly -ErrorAction SilentlyContinue) -eq $true)
Write-Host ""
if ($failures -eq 0) { Write-Host "  All checks passed." -ForegroundColor Green; Write-Host ""; exit 0 }
Write-Host "  $failures check(s) failed." -ForegroundColor Red
Write-Host ""
exit 1
