<#
.SYNOPSIS
  One command to run a night of coding on a project, with the skills already wired.

.DESCRIPTION
  The student types a project path and nothing else. This script finds the
  configuration beside itself, creates a working branch, holds the machine awake,
  runs every plan through aider-plan.ps1 with -Skills, and stops.

  It never merges. Pushing and opening a pull request are offered, because both
  are reversible and neither publishes anything to a default branch; the merge is
  a decision taken awake, after reading audit.md.

.PARAMETER Project
  The project directory. It must be a git repository with docs\superpowers\plans.

.PARAMETER Branch
  The branch to work on. Created if it does not exist. Defaults to a dated name.

.PARAMETER NoSkills
  Run without the per-stage skills, which is what the pipeline did before they
  existed. Useful for comparing one night's output against another.

.PARAMETER Push
  Push the branch when every plan is done. Requires a remote.

.PARAMETER PullRequest
  Open a pull request after pushing. Requires gh on PATH and a token. Implies
  -Push. NEVER merges.

.PARAMETER DryRun
  Print what would happen, start no model, write nothing.

.EXAMPLE
  aider-night.ps1 C:\work\my-project
  aider-night.ps1 C:\work\my-project -Branch night-friday -PullRequest
#>
param(
    [Parameter(Mandatory = $true, Position = 0)][string]$Project,
    [string]$Branch = "",
    # The escape hatch when no configuration file exists. Pinning a tag by hand
    # is acceptable; letting aider guess one from an API key is not.
    [string]$Model = "",
    [switch]$NoSkills,
    # Run the plans and stop before the review pass. The reviewer is the slower
    # of the two models, so this is what makes a short run possible at all.
    [switch]$NoAudit,
    [switch]$Push,
    [switch]$PullRequest,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

function Say($text)  { Write-Host $text }
function Head($text) { Write-Host ""; Write-Host "== $text" -ForegroundColor Cyan }
function Stop-With($lines, $code) {
    foreach ($l in $lines) { Write-Host $l -ForegroundColor Red }
    exit $code
}

# --- Where the configuration lives -----------------------------------------
# Two layouts are supported and the script SAYS which one it found, because an
# unannounced fallback is how a run ends up reading someone else's settings:
#   the kit      bin\aider-night.ps1 with ..\config\ beside it
#   this machine ~/.local/bin with ~/.config/aider
$kitConfig = Join-Path (Split-Path -Parent $PSScriptRoot) "config"
$devConfig = Join-Path $HOME ".config\aider"
if (Test-Path -LiteralPath (Join-Path $kitConfig "context-budget.json")) {
    $configDir = $kitConfig
    $layout    = "kit"
} elseif (Test-Path -LiteralPath (Join-Path $devConfig "context-budget.json")) {
    $configDir = $devConfig
    $layout    = "user"
} else {
    Stop-With @("REFUSED: no configuration found. Looked in:",
                "  $kitConfig",
                "  $devConfig",
                "  Run setup.ps1 first.") 2
}

$driver     = Join-Path $PSScriptRoot "aider-plan.ps1"
$budgetFile = Join-Path $configDir "context-budget.json"
$skillsFile = Join-Path $configDir "skills.json"
$aiderConf  = Join-Path $configDir "aider.conf.yml"

# The kit ships its configuration as a TEMPLATE: setup.ps1 substitutes {{HOME}}
# for the student's own home when it installs. Running straight out of the
# extracted kit therefore hands aider a path that is not one, and aider answers
# with its full usage text - a wall of argument syntax that says nothing about
# what is actually wrong. Measured 2026-09-03, and it is a student's very first
# gesture, so it gets a sentence instead.
foreach ($template in @($budgetFile, $skillsFile, $aiderConf)) {
    if (-not (Test-Path -LiteralPath $template)) { continue }
    if ((Get-Content -LiteralPath $template -Raw -Encoding UTF8) -match '\{\{HOME\}\}') {
        # The placeholder is NAMED by assembling it, never written literally: this
        # file passes through setup.ps1's own substitution, so a literal one here
        # is replaced by the student's home and the message then reads
        # "still contains the C:/Users/... placeholder", which explains nothing.
        # Measured 2026-09-04 on a scratch install.
        $token = "{{" + "HOME" + "}}"
        Stop-With @("REFUSED: this kit has not been installed yet.",
                    "  $template still contains the $token placeholder.",
                    "",
                    "  Run the installer first, from the kit directory:",
                    "    .\setup.ps1",
                    "",
                    "  Then call aider-night from your own bin directory, not from here.") 2
    }
}

Head "Night run"
Say ("  configuration : {0}  ({1} layout)" -f $configDir, $layout)

foreach ($required in @($driver, $budgetFile)) {
    if (-not (Test-Path -LiteralPath $required)) {
        Stop-With @("REFUSED: a required file is missing:", "  $required") 2
    }
}
if (-not (Test-Path -LiteralPath $aiderConf)) {
    # The kit ships config/aider.conf.yml. A development machine keeps the same
    # file under build/ with a .saved suffix, and aider's own default lives in
    # the home directory. Try all three, in that order, and SAY which was used.
    $alternatives = @(
        (Join-Path $configDir "build\aider.conf.yml.saved"),
        (Join-Path $HOME ".aider.conf.yml")
    )
    $aiderConf = ""
    foreach ($candidate in $alternatives) {
        if (Test-Path -LiteralPath $candidate) { $aiderConf = $candidate; break }
    }
    if ($aiderConf -eq "" -and $Model -eq "") {
        # NOT a note, and not a fallback to "let the driver work it out".
        #
        # Measured 2026-09-03 on this machine, by this script, before this
        # refusal existed: with no config reachable aider resolved
        # gemini/gemini-2.5-pro-exp-03-25 - a PAID cloud model - because
        # GEMINI_API_KEY happened to be in the environment. The driver caught it
        # and refused, which is why that guard exists; but a launcher that
        # shrugs and hands the problem downstream is a launcher that will one
        # day meet a driver without the guard.
        Stop-With @("REFUSED: no aider configuration found. Looked for:",
                    "  $(Join-Path $configDir 'aider.conf.yml')",
                    "  $($alternatives -join "`n  ")",
                    "",
                    "  Without one, aider resolves a model from whatever API key is in the",
                    "  environment, and an unattended run can spend a cloud quota all night.",
                    "  Run setup.ps1, or pass -Model <local tag> to pin one.") 2
    }
}

$useSkills = -not $NoSkills
if ($useSkills -and -not (Test-Path -LiteralPath $skillsFile)) {
    Stop-With @("REFUSED: skills are on by default and $skillsFile is missing.",
                "  Pass -NoSkills to run the pipeline without them.") 2
}
Say ("  skills        : {0}" -f $(if ($useSkills) { $skillsFile } else { "off (-NoSkills)" }))

# --- The project ------------------------------------------------------------
if (-not (Test-Path -LiteralPath $Project)) {
    Stop-With @("REFUSED: project directory does not exist:", "  $Project") 2
}
$Project = (Resolve-Path -LiteralPath $Project).Path
Say ("  project       : {0}" -f $Project)

Push-Location $Project
try {
    $null = & git rev-parse --git-dir 2>&1
    if ($LASTEXITCODE -ne 0) {
        Stop-With @("REFUSED: $Project is not a git repository.",
                    "  The pipeline commits every accepted edit, so it needs one.") 2
    }

    # --- Refusals that must happen BEFORE a night of work, not during it ----
    $battery = Get-CimInstance Win32_Battery -ErrorAction SilentlyContinue
    if ($battery -and $battery.BatteryStatus -ne 2) {
        Stop-With @("REFUSED: the machine is on battery.",
                    "  A wake lock does not survive a battery sleep, so four hours in the",
                    "  plan is half done and the machine sleeps regardless. Plug it in.") 2
    }

    if ($PullRequest) {
        $gh = Get-Command gh -ErrorAction SilentlyContinue
        if (-not $gh) {
            Stop-With @("REFUSED: -PullRequest needs gh on PATH, and it is not there.",
                        "  Discovering this at 4 a.m. after a night of work is the reason",
                        "  it is checked here. Drop -PullRequest, or install gh.") 2
        }
        & gh auth status 2>&1 | Out-Null
        if ($LASTEXITCODE -ne 0) {
            Stop-With @("REFUSED: gh is installed but not authenticated.",
                        "  Run: gh auth login") 2
        }
        $Push = $true
    }
    if ($Push) {
        $remotes = @(& git remote)
        if ($remotes.Count -eq 0) {
            Stop-With @("REFUSED: -Push was asked for and this repository has no remote.") 2
        }
    }

    # --- The branch, which the driver refuses to create for itself ---------
    # A team of three to seven shares one repository with a protected main, so a
    # date alone is not a branch name: two students working the same night would
    # collide on it. The default carries WHO as well as WHEN, taken from git's
    # own identity so it matches the name their commits already carry.
    if ($Branch -eq "") {
        $who = (& cmd /c "git config user.name 2>NUL")
        if (-not $who) { $who = $env:USERNAME }
        $who = ($who -replace '[^A-Za-z0-9]+', '-').Trim('-').ToLowerInvariant()
        if ($who -eq "") { $who = "student" }
        $Branch = "$who/night-" + (Get-Date -Format "yyyy-MM-dd")
    }
    if ($Branch -in @("main", "master")) {
        Stop-With @("REFUSED: '$Branch' is a default branch.",
                    "  Every commit would be refused by the pre-commit hook, all night.") 2
    }
    # symbolic-ref, NOT rev-parse --abbrev-ref. On a repository whose HEAD is
    # UNBORN - which is every project new-project.ps1 has just created, since it
    # runs git init and makes no commit - rev-parse writes
    #   fatal: ambiguous argument 'HEAD': unknown revision...
    # to stderr, so the first dry run of every new project opened with a git
    # error that meant nothing was wrong. symbolic-ref answers the branch name
    # in that state. It is the reverse on a DETACHED head, where symbolic-ref
    # fails and rev-parse is right, so both are tried in that order. Redirection
    # inside cmd, as with the user.name read above, because PowerShell wraps a
    # native command's stderr in an ErrorRecord.
    $current = (& cmd /c "git symbolic-ref --short HEAD 2>NUL")
    if (-not $current) { $current = (& cmd /c "git rev-parse --abbrev-ref HEAD 2>NUL") }
    if (-not $current) {
        Stop-With @("REFUSED: cannot read the current branch in $Project.",
                    "  Neither git symbolic-ref nor git rev-parse answered, so this is not",
                    "  an unborn HEAD or a detached one - check that it is a git repository.") 1
    }
    $current = $current.Trim()
    if ($current -ne $Branch) {
        if ($DryRun) {
            Say "  would switch to branch $Branch (creating it if needed)"
        } else {
            $exists = @(& git branch --list $Branch)
            # Captured, not discarded. git explains itself - which untracked
            # file would be overwritten, or that the branch is checked out
            # elsewhere - and 'could not switch' without that sentence sends a
            # reader looking in the wrong place.
            if ($exists.Count -gt 0) { $switchOut = & cmd /c "git switch ""$Branch"" 2>&1" }
            else                     { $switchOut = & cmd /c "git switch -c ""$Branch"" 2>&1" }
            if ($LASTEXITCODE -ne 0) {
                $why = @($switchOut | Where-Object { $_ -ne '' })
                Stop-With (@(
                    "REFUSED: could not switch to branch $Branch.",
                    "  git said:") + ($why | ForEach-Object { "    $_" }) + @(
                    "  A night that has already run leaves its branch behind, and the",
                    "  plan files are untracked on the branch you are on now. Delete the",
                    "  old branch, or pass -Branch with a name nothing is using.")) 1
            }
        }
    }
    Say ("  branch        : {0}" -f $Branch)
    # Said, not left silent. A project new-project.ps1 has just made has no
    # commit at all, and until 2026-09-05 the only sign of that was a raw
    # "fatal: ambiguous argument 'HEAD'" leaking out of git with nothing saying
    # which command produced it or that nothing was wrong. Suppressing the
    # error was half the fix; the other half is reporting the state it was
    # reporting, in this script's own voice.
    $null = & cmd /c "git rev-parse --verify HEAD 2>NUL"
    if ($LASTEXITCODE -ne 0) {
        Say "  commits       : none yet, so the run makes the first one"
    }

    # --- Hold the machine awake --------------------------------------------
    # Decimal, never 0x80000000: PowerShell 5.1 parses that as Int32
    # -2147483648, so the -bor yields -2147483647 and the uint parameter throws
    # before the lock is taken. Measured 2026-09-03.
    Add-Type -Namespace AiderNight -Name Power -MemberDefinition @'
[DllImport("kernel32.dll", SetLastError = true)]
public static extern uint SetThreadExecutionState(uint esFlags);
'@ -ErrorAction SilentlyContinue
    $ES_CONTINUOUS      = [uint32]2147483648
    $ES_SYSTEM_REQUIRED = [uint32]1

    $rc = 0
    try {
        if (-not $DryRun) {
            $previous = [AiderNight.Power]::SetThreadExecutionState($ES_CONTINUOUS -bor $ES_SYSTEM_REQUIRED)
            if ($previous -eq 0) {
                # Verify the effect, not the call. A lock that was not taken must
                # be said out loud rather than assumed.
                Say "  WARNING: the wake lock was refused; the machine may throttle overnight"
            } else {
                Say "  wake lock     : held (previous state $previous)"
            }
        } else {
            Say "  would take a wake lock, and release it in a finally"
        }

        # --- The run --------------------------------------------------------
        # A HASHTABLE, not an array, and not $args.
        #
        # Two traps, both measured 2026-09-03 and both silent until they are not:
        #
        #   $args is an automatic variable holding this script's own unbound
        #   arguments. Assigning it and splatting @args sends the driver
        #   something other than what was built here.
        #
        #   Splatting an ARRAY passes its elements POSITIONALLY, so "-Path" is
        #   taken as the VALUE of the driver's first parameter and the project
        #   path lands on its second, -TokenCeiling, which is an [int]. The run
        #   died on a type conversion naming a parameter this script does not
        #   have. Only a hashtable splats by name.
        $driverArgs = @{ Path = $Project; BudgetFile = $budgetFile }
        if ($aiderConf -ne "") { $driverArgs.Config = $aiderConf }
        if ($Model -ne "")     { $driverArgs.Model  = $Model }
        if ($useSkills)        { $driverArgs.Skills = $true; $driverArgs.SkillsFile = $skillsFile }
        if ($DryRun)           { $driverArgs.DryRun = $true }
        if ($NoAudit)          { $driverArgs.NoAudit = $true }
        # The test command names the PROJECT'S OWN interpreter, and that default
        # is not a convenience.
        #
        # A bare `python` runs whatever PATH resolves, which on a shared machine
        # can be another account's installation entirely - measured 2026-09-03 on
        # the reference machine, where `python` resolved into a different user
        # profile. Tests that pass against the wrong interpreter, with the wrong
        # packages, are worse than tests that do not run: they report a green
        # suite for code nobody has actually exercised.
        #
        # So the environment is required, and its absence is a refusal (R8: no
        # silent fallback). AIDER_TEST_COMMAND overrides it for anyone who
        # manages their own, and then the interpreter is their responsibility.
        $testCmd = $env:AIDER_TEST_COMMAND
        if (-not $testCmd -or $testCmd -eq "") {
            $venvPython = Join-Path $Project ".venv\Scripts\python.exe"
            if (-not (Test-Path -LiteralPath $venvPython)) {
                Stop-With @(
                    "REFUSED: no virtual environment at $venvPython",
                    "  A project's tests run in the project's own environment, never in",
                    "  whatever interpreter PATH happens to resolve.",
                    "",
                    "  Create it:                   cd `"$Project`" ; uv venv .venv",
                    "  or let the scaffolder do it: new-project.ps1 -Name <name> -Root <dir>",
                    "  or name your own command:    `$env:AIDER_TEST_COMMAND = '<command>'"
                ) 2
            }
            $testCmd = '.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py"'
        }
        $driverArgs.TestCommand = $testCmd

        Head "Driver"
        & $driver @driverArgs
        # Captured on the line immediately after the call. A trailing command
        # overwrites it, and a failed run then reads as a success.
        $rc = $LASTEXITCODE
    }
    finally {
        if (-not $DryRun) { [void][AiderNight.Power]::SetThreadExecutionState($ES_CONTINUOUS) }
    }

    Head "Result"
    Say ("  driver exit   : {0}" -f $rc)

    # --- Publish, never merge ----------------------------------------------
    # A pull request is opened only when EVERY plan is done, which is the rule the
    # team works by: main is protected, each student has a branch, and the pull
    # request is the one way in. A half-finished branch may still be pushed -
    # pushing is a backup and costs a reviewer nothing - but it must not arrive as
    # a request to merge unfinished work.
    $plansLeft = @(Get-ChildItem -LiteralPath (Join-Path $Project "docs\superpowers\plans") `
                       -Filter "plan*.md" -File -ErrorAction SilentlyContinue).Count
    $cycleComplete = ($plansLeft -eq 0)
    Say ("  plans left    : {0}{1}" -f $plansLeft,
         $(if ($cycleComplete) { "  (the cycle is complete)" } else { "  (not finished)" }))

    # A non-zero driver exit no longer blocks the push, since 2026-09-04. It used
    # to, which contradicted the paragraph above in this same file: pushing is a
    # backup, and withholding it punished the student for a review finding the
    # driver could not close. Since the driver stopped abandoning later plans on
    # the first blocked one, exit 1 means "some plan carries a [!] that a person
    # must read", and that branch is exactly the one worth having off the machine.
    # The pull request is still gated on the cycle being complete, which is the
    # rule that actually protects main.
    if ($Push) {
        if ($rc -ne 0) {
            Say "  the driver exited $rc, so some plan carries a [!]. Pushing anyway: the"
            Say "  branch is a backup, and progress.md says what is left."
        }
        $prAllowed = ($PullRequest -and $cycleComplete -and $rc -eq 0)
        if ($DryRun) {
            Say "  would push $Branch"
            if ($prAllowed) { Say "  would open a pull request into main" }
            elseif ($PullRequest -and -not $cycleComplete) {
                Say "  would NOT open a pull request: $plansLeft plan(s) still to run"
            }
            elseif ($PullRequest) {
                Say "  would NOT open a pull request: the driver exited $rc"
            }
        } else {
            & git push -u origin $Branch
            if ($LASTEXITCODE -ne 0) {
                Say "  push failed; the work is committed locally on $Branch"
            } elseif ($PullRequest -and -not $cycleComplete) {
                Say "  branch pushed. NO pull request: $plansLeft plan(s) are still to run,"
                Say "  and a pull request is how this team says 'all the plans are done'."
            } elseif ($PullRequest -and $rc -ne 0) {
                Say "  branch pushed. NO pull request: the driver exited $rc, so a plan carries"
                Say "  a [!]. Read progress.md and audit.md, then open it yourself."
            } elseif ($PullRequest) {
                & gh pr create --base main --head $Branch --fill
                if ($LASTEXITCODE -ne 0) { Say "  the branch is pushed; opening the pull request is yours" }
            }
        }
    } else {
        Say "  the work is committed locally on $Branch. Read audit.md, then push if you want it."
    }
    Say "  NOTHING WAS MERGED. That decision is yours, awake, after reading audit.md."
}
finally {
    Pop-Location
}

exit $rc
