#Requires -Version 5.1
<#
.SYNOPSIS
    Drives scripts\audit\check-claude-template.ps1 against scratch template and
    "live global file" pairs under $env:TEMP, and proves the U5 title check
    keys on the thing it claims.

.DESCRIPTION
    U5 (2026-08-30) translated CLAUDE.template.md to English while the live
    ~/.claude/CLAUDE.md stays French until the operator installs the
    translation deliberately. Comparing the two line by line then reports the
    WHOLE file - 796 lines on the day of the change - which is noise, not
    drift, and it retired all twelve French allowed-divergence anchors at once.

    So the audit now compares the two files' top-level titles first. Different
    titles mean these are not the same document, classification is skipped with
    a stated reason, and the invariants still run. That is a new decision with
    real teeth - it can hide genuine drift if it fires when it should not - so
    it is asserted in BOTH directions here:

      skip fires      different H1 -> classification skipped, exit 0
      skip does NOT   same H1 -> classification runs, and an unclassified
                      difference still fails the run with exit 1

    The second half is the one that matters. Without it the title check would
    be indistinguishable from switching the audit off.

    Nothing here touches the live ~/.claude: every run is pointed at scratch
    files through -TemplatePath and -GlobalClaudeMd, and the real global file
    is hashed before and after to prove it.

.EXAMPLE
    .\scripts\test\verify-template-audit.ps1
#>

[CmdletBinding()]
param(
    [string]$Root
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if (-not $Root) { $Root = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent }
$Audit = Join-Path $Root "scripts\audit\check-claude-template.ps1"
$RealTemplate = Join-Path $Root "CLAUDE.template.md"

$script:Failures = 0
function Write-Header([string]$text) { Write-Host ""; Write-Host "=== $text ===" -ForegroundColor Cyan }
function Write-Pass([string]$text)   { Write-Host "  PASS  $text" -ForegroundColor Green }
function Write-Fail([string]$text)   { Write-Host "  FAIL  $text" -ForegroundColor Red; $script:Failures++ }
function Write-Info([string]$text)   { Write-Host "  [--]  $text" -ForegroundColor DarkGray }
function Check-True([bool]$ok, [string]$text) { if ($ok) { Write-Pass $text } else { Write-Fail $text } }
function Check-Eq($expected, $actual, [string]$text) {
    if ("$expected" -eq "$actual") { Write-Pass $text } else { Write-Fail "$text (expected '$expected', got '$actual')" }
}

$Sandbox = Join-Path $env:TEMP ("rt-template-audit-" + $PID)
if (Test-Path -LiteralPath $Sandbox) { Remove-Item -LiteralPath $Sandbox -Recurse -Force }
New-Item -ItemType Directory -Path $Sandbox -Force | Out-Null

# The audit substitutes {{OBSIDIAN_VAULT}} and {{OBSIDIAN_EXE}} itself, so a
# scratch template must carry no placeholder we do not want resolved. It must
# also satisfy the five invariants, which are not what this suite is testing.
function New-Pair {
    param([string]$Name, [string]$TemplateTitle, [string]$LiveTitle, [string]$ExtraLiveLine = "")
    $dir = Join-Path $Sandbox $Name
    New-Item -ItemType Directory -Path $dir -Force | Out-Null
    $body = @(
        "",
        "A scratch file. It exists to exercise the title check, nothing else.",
        "",
        "### Permanent permission for memory upkeep",
        "",
        "Dispatching local-writer for memory upkeep is always permitted, and stays narrow:",
        "one sequential agent, never a parallel fan-out of agents.",
        ""
    )
    $tmpl = @("# $TemplateTitle") + $body
    $live = @("# $LiveTitle") + $body
    if ($ExtraLiveLine) { $live += $ExtraLiveLine }
    $tmplPath = Join-Path $dir "template.md"
    $livePath = Join-Path $dir "live.md"
    Set-Content -LiteralPath $tmplPath -Value $tmpl -Encoding UTF8
    Set-Content -LiteralPath $livePath -Value $live -Encoding UTF8
    return [pscustomobject]@{ Template = $tmplPath; Live = $livePath }
}

function Invoke-Audit([string]$template, [string]$live) {
    # `*>&1`, not `2>&1`: the audit reports through Write-Host, which in
    # PowerShell 5.1 writes to the INFORMATION stream (6), not to stdout. A
    # capture of stdout plus stderr comes back empty and every text assertion
    # below fails while the audit is behaving perfectly - measured while
    # writing this suite, four false failures in a row.
    $out = & $Audit -TemplatePath $template -GlobalClaudeMd $live *>&1 | Out-String
    return [pscustomobject]@{ exit = $LASTEXITCODE; text = $out }
}

Write-Header "check-claude-template.ps1 title check"
Write-Info "sandbox : $Sandbox"

# ---------------------------------------------------------------------------
# 1. Different titles: the U5 state. Skip, with the reason stated.
# ---------------------------------------------------------------------------
Write-Header "different titles - the U5 state"
$p = New-Pair -Name "u5" -TemplateTitle "Global instructions - Obsidian integration" `
              -LiveTitle "Instructions globales - Integration Obsidian"
$r = Invoke-Audit $p.Template $p.Live
Check-Eq 0 $r.exit "exit 0"
Check-True ($r.text -match "DIFFERENT top-level titles") "the mismatch is REPORTED, not silently tolerated"
Check-True ($r.text -match "Classification skipped") "classification is skipped"
Check-True ($r.text -match "Invariants") "the invariants still run"

# ---------------------------------------------------------------------------
# 2. Same titles, identical bodies: classification runs and finds nothing.
# ---------------------------------------------------------------------------
Write-Header "same titles, no difference"
$p = New-Pair -Name "same" -TemplateTitle "Global instructions" -LiveTitle "Global instructions"
$r = Invoke-Audit $p.Template $p.Live
Check-Eq 0 $r.exit "exit 0"
Check-True (-not ($r.text -match "Classification skipped")) "classification is NOT skipped when the titles agree"

# ---------------------------------------------------------------------------
# 3. NEGATIVE CONTROL, the one that matters. Same titles, one unexplained
#    extra line: the audit must still fail. Without this the title check would
#    be indistinguishable from switching the audit off.
# ---------------------------------------------------------------------------
Write-Header "same titles, an unclassified difference"
$p = New-Pair -Name "drift" -TemplateTitle "Global instructions" -LiveTitle "Global instructions" `
              -ExtraLiveLine "A line nobody classified, which is exactly what drift looks like."
$r = Invoke-Audit $p.Template $p.Live
Check-Eq 1 $r.exit "exit 1 - drift still fails the run"
Check-True ($r.text -match "Unclassified difference") "the drifting line is named"

# ---------------------------------------------------------------------------
# 4. The live global file is untouched by all of the above.
# ---------------------------------------------------------------------------
Write-Header "the real global file is never touched"
$liveGlobal = Join-Path $env:USERPROFILE ".claude\CLAUDE.md"
if (Test-Path -LiteralPath $liveGlobal) {
    $before = (Get-FileHash -LiteralPath $liveGlobal -Algorithm SHA256).Hash
    Invoke-Audit $p.Template $p.Live | Out-Null
    Check-Eq $before (Get-FileHash -LiteralPath $liveGlobal -Algorithm SHA256).Hash `
        "live ~/.claude/CLAUDE.md is byte-identical afterwards"
} else {
    Write-Info "no live global CLAUDE.md on this machine; check not applicable"
}
$tmplBefore = (Get-FileHash -LiteralPath $RealTemplate -Algorithm SHA256).Hash
Invoke-Audit $p.Template $p.Live | Out-Null
Check-Eq $tmplBefore (Get-FileHash -LiteralPath $RealTemplate -Algorithm SHA256).Hash `
    "the repository's CLAUDE.template.md is byte-identical afterwards"

Remove-Item -LiteralPath $Sandbox -Recurse -Force

Write-Header "Summary"
if ($script:Failures -eq 0) {
    Write-Host "  All checks passed." -ForegroundColor Green
    exit 0
}
Write-Host "  $script:Failures check(s) failed." -ForegroundColor Red
exit 1
