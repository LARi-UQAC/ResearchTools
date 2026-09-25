<#
.SYNOPSIS
  Prove the audit prompts the driver BUILDS still carry every instruction.

.DESCRIPTION
  Written after the worst self-inflicted defect of 2026-09-06. A clause added to
  the per-plan audit prompt read:

      "If a "## $planName" heading is already in audit.md from an earlier " +

  That is VALID PowerShell: a string, then `##`, which begins a COMMENT. The rest
  of the clause, the instruction to write the report in English, and the whole
  rule that audit.md must be written before the ledger line were all dropped from
  the message. The prompt went out at 991 bytes ending mid-word.

  Nothing caught it. The parser was happy, because the file IS valid. The 33
  driver checks were happy, because none of them reads an assembled prompt. The
  only symptom was a report coming back in French, three hours later, in a run
  that had to be thrown away.

  A first version of this check read the SOURCE with a regex and recovered the
  text PowerShell would have discarded, so it passed on the planted bug - a
  check that cannot fail. This one asks PowerShell itself: it locates each
  prompt assignment through the language parser, evaluates that expression with
  the surrounding variables stubbed, and asserts on the STRING THAT RESULTS.

.PARAMETER Driver
  aider-plan.ps1. Defaults to the installed one beside this script's parent.
#>
[CmdletBinding()]
param(
    [string]$Driver = ""
)

$ErrorActionPreference = "Stop"

if ($Driver -eq "") {
    $Driver = Join-Path (Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)) "aider-plan.ps1"
}
if (-not (Test-Path -LiteralPath $Driver)) {
    Write-Host "REFUSED: no driver at $Driver" -ForegroundColor Red
    exit 2
}

# What each prompt must still say. Every entry is the TAIL of a clause, so a
# truncation anywhere before it removes the phrase with it.
$required = @{
    "msg" = @(
        "which is a failed review",
        "Write the report and stop",
        "your findings worst first",
        "Writing nothing is never the right answer",
        "APPEND under it anyway",
        "Write the report in English",
        "is a FAILED review"
    )
    "auditMessage" = @(
        "Every source file is read-only",
        "worst first",
        "Write the report in English",
        "Write the report and stop"
    )
}

$errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile($Driver, [ref]$null, [ref]$errors)
if ($errors.Count -ne 0) {
    Write-Host ("REFUSED: {0} does not parse: {1}" -f $Driver, $errors[0].Message) -ForegroundColor Red
    exit 2
}

# Variables the prompt expressions interpolate. Stubbed, because the check is
# about which CLAUSES survive, not about their substituted values.
$planName  = "planN.md"
$fatNote   = ""
$of        = ""
$auditPath = "audit.md"

$failures = 0
foreach ($name in $required.Keys) {
    $assignments = $ast.FindAll({
        param($node)
        $node -is [System.Management.Automation.Language.AssignmentStatementAst] -and
        $node.Left.Extent.Text -eq ('$' + $name) -and
        # '=' only. A '+=' later in the file appends optional material and
        # references variables this check has no business stubbing; taking it
        # as THE prompt made the evaluation fail for a reason unrelated to
        # truncation, which is the failure this exists to see.
        $node.Operator -eq [System.Management.Automation.Language.TokenKind]::Equals
    }, $true)

    if ($assignments.Count -eq 0) {
        Write-Host ("  FAIL  no assignment to `$$name found in the driver") -ForegroundColor Red
        $failures++
        continue
    }

    # The LAST assignment is the prompt; earlier ones may be scaffolding.
    $expression = $assignments[-1].Right.Extent.Text
    try {
        $built = Invoke-Expression $expression
    } catch {
        Write-Host ("  FAIL  `$$name does not evaluate: {0}" -f $_.Exception.Message) -ForegroundColor Red
        $failures++
        continue
    }

    $missing = @($required[$name] | Where-Object { $built -notlike ("*" + $_ + "*") })
    if ($missing.Count -eq 0) {
        Write-Host ("  ok    `$$name builds {0} characters, all {1} clause(s) present" -f $built.Length, $required[$name].Count) -ForegroundColor Green
    } else {
        Write-Host ("  FAIL  `$$name is missing {0} clause(s) - the prompt is TRUNCATED:" -f $missing.Count) -ForegroundColor Red
        foreach ($m in $missing) { Write-Host ("          $m") -ForegroundColor Red }
        $failures++
    }
}

Write-Host ""
if ($failures -eq 0) {
    Write-Host "PASSED: every audit prompt carries every clause it is supposed to." -ForegroundColor Green
    exit 0
}
Write-Host ("FAILED: {0} prompt(s) truncated." -f $failures) -ForegroundColor Red
exit 1
