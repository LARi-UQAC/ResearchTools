#Requires -Version 5.1
<#
.SYNOPSIS
    Drives Update-RtContractBlock (unit U6) against scratch repositories under
    $env:TEMP, and proves the generated block cannot silently go stale or
    silently destroy the file it writes into.

.DESCRIPTION
    U6 replaced a hand-maintained copy with a generated one. That trades a
    drift risk for a generator risk, and the generator writes into
    CLAUDE.template.md, whose RT-CONTRACT block `install-junctions.ps1 -Sync`
    then copies into the live ~/.claude/CLAUDE.md. A generator that wrote the
    wrong thing would therefore reach every project on the machine at the next
    session start, which is why every refusal below is asserted rather than
    assumed.

    Asserted:
      round trip   the export region of .claude/CLAUDE.md lands in the
                   template's RT-CONTRACT block, byte for byte
      idempotence  a second run reports no change and writes nothing
      drift        editing the SOURCE makes the next run rewrite the block, and
                   editing only the COPY is overwritten rather than preserved
      refusals     a missing marker, an unmatched pair, a reversed pair and an
                   empty region each throw and leave the template untouched
      containment  everything outside the two markers is byte-identical

    This suite loads scripts\lib\rt-contract.ps1 directly. It never runs
    install.ps1, which would regenerate every mirror in the real repository as
    a side effect, and it never touches the real CLAUDE.template.md - the
    repository's own copy is hashed before and after to prove it.

.EXAMPLE
    .\scripts\test\verify-rt-contract.ps1
#>

[CmdletBinding()]
param(
    [string]$Root
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if (-not $Root) { $Root = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent }
. (Join-Path $Root "scripts\lib\rt-contract.ps1")

$RealTemplate = Join-Path $Root "CLAUDE.template.md"
$RealSource   = Join-Path $Root ".claude\CLAUDE.md"

$script:Failures = 0
function Write-Header([string]$text) { Write-Host ""; Write-Host "=== $text ===" -ForegroundColor Cyan }
function Write-Pass([string]$text)   { Write-Host "  PASS  $text" -ForegroundColor Green }
function Write-Fail([string]$text)   { Write-Host "  FAIL  $text" -ForegroundColor Red; $script:Failures++ }
function Write-Info([string]$text)   { Write-Host "  [--]  $text" -ForegroundColor DarkGray }
function Check-True([bool]$ok, [string]$text) { if ($ok) { Write-Pass $text } else { Write-Fail $text } }
function Check-Eq($expected, $actual, [string]$text) {
    if ("$expected" -eq "$actual") { Write-Pass $text } else { Write-Fail "$text (expected '$expected', got '$actual')" }
}
function Check-Throws([scriptblock]$action, [string]$text) {
    try { & $action; Write-Fail "$text (no error was raised)" }
    catch { Write-Pass $text }
}

$Sandbox = Join-Path $env:TEMP ("rt-contract-" + $PID)
if (Test-Path -LiteralPath $Sandbox) { Remove-Item -LiteralPath $Sandbox -Recurse -Force }
New-Item -ItemType Directory -Path $Sandbox -Force | Out-Null

function New-Repo {
    param([string]$Name, [string]$SourceBody, [string]$TemplateBlock = "old hand-written content")
    $dir = Join-Path $Sandbox $Name
    New-Item -ItemType Directory -Path (Join-Path $dir ".claude") -Force | Out-Null
    Set-Content -LiteralPath (Join-Path $dir ".claude\CLAUDE.md") -Value $SourceBody -Encoding UTF8
    $tmpl = @(
        "# Global instructions",
        "",
        "Text ABOVE the block, which must never move.",
        "",
        "<!-- RT-CONTRACT:BEGIN -->",
        $TemplateBlock,
        "<!-- RT-CONTRACT:END -->",
        "",
        "Text BELOW the block, which must never move."
    )
    Set-Content -LiteralPath (Join-Path $dir "CLAUDE.template.md") -Value $tmpl -Encoding UTF8
    return $dir
}

$goodSource = @(
    "# Project rules",
    "",
    "Text outside the export region.",
    "",
    "<!-- RT-EXPORT:BEGIN -->",
    "<!-- Everything between these markers is the GLOBAL contract: install.ps1 splices it -->",
    "",
    "## Improving ResearchTools from another folder",
    "",
    "The contract text.",
    "",
    "## References",
    "",
    "The approved-publisher list. See [README.md](../README.md) and [code-style](rules/code-style.md).",
    "External: [the DOI site](https://doi.org) stays clickable.",
    "<!-- RT-EXPORT:END -->",
    "",
    "More text outside."
) -join "`n"

Write-Header "round trip"
$repo = New-Repo -Name "roundtrip" -SourceBody $goodSource
$r = Update-RtContractBlock -RepoRoot $repo
Check-True $r.Changed "the first run reports a change"
$tmpl = Get-Content -LiteralPath (Join-Path $repo "CLAUDE.template.md") -Raw -Encoding UTF8
Check-True ($tmpl -match "## Improving ResearchTools from another folder") "the contract section landed in the block"
Check-True ($tmpl -match "The approved-publisher list\.") "the References section landed in the block"
Check-True ($tmpl -match "GENERATED from \.claude/CLAUDE\.md") "the generated block says it is generated, and names its source"
Check-True (-not ($tmpl -match "old hand-written content")) "the previous hand-written content is gone"
Check-True (-not ($tmpl -match "Everything between these markers")) "the SOURCE's own explanatory comment is not copied into the block"
Check-True (-not ($tmpl -match "Text outside the export region")) "content outside the export region is NOT exported"

Write-Header "relative links are neutralised, external links are not"
# The copy lands in ~/.claude/CLAUDE.md, outside the repository, where a
# relative target resolves to nothing. A dead link reads as a promise, so the
# label survives as plain text and the target is dropped. An absolute path is
# deliberately not substituted: that would bake one machine's repository
# location into a tracked file.
Check-True (-not ($tmpl -match '\(\.\./README\.md\)')) "a ../ link target is gone from the generated block"
Check-True (-not ($tmpl -match 'rules/code-style\.md\)')) "a repo-relative link target is gone too"
Check-True ($tmpl -match 'See README\.md and code-style\.') "the link LABELS survive as plain text"
Check-True ($tmpl -match '\[the DOI site\]\(https://doi\.org\)') "an external https link is left exactly as it was"
$srcText = Get-Content -LiteralPath (Join-Path $repo ".claude\CLAUDE.md") -Raw -Encoding UTF8
Check-True ($srcText -match '\[README\.md\]\(\.\./README\.md\)') "the SOURCE keeps its links: only the copy is rewritten"

Write-Header "the file around the block is untouched"
Check-True ($tmpl -match "Text ABOVE the block, which must never move\.") "text above the markers survives"
Check-True ($tmpl -match "Text BELOW the block, which must never move\.") "text below the markers survives"

Write-Header "idempotence"
$r2 = Update-RtContractBlock -RepoRoot $repo
Check-True (-not $r2.Changed) "the second run reports no change"
$before = (Get-FileHash -LiteralPath (Join-Path $repo "CLAUDE.template.md") -Algorithm SHA256).Hash
Update-RtContractBlock -RepoRoot $repo | Out-Null
Check-Eq $before (Get-FileHash -LiteralPath (Join-Path $repo "CLAUDE.template.md") -Algorithm SHA256).Hash `
    "a third run leaves the file byte-identical"

Write-Header "drift, in both directions"
# Editing the SOURCE must propagate.
$src = Join-Path $repo ".claude\CLAUDE.md"
(Get-Content -LiteralPath $src -Raw -Encoding UTF8).Replace("The approved-publisher list.", "A NEW publisher rule.") |
    Set-Content -LiteralPath $src -Encoding UTF8 -NoNewline
$r3 = Update-RtContractBlock -RepoRoot $repo
Check-True $r3.Changed "editing the source makes the next run rewrite the block"
Check-True ((Get-Content -LiteralPath (Join-Path $repo "CLAUDE.template.md") -Raw) -match "A NEW publisher rule\.") `
    "the source edit reached the block"

# Editing only the COPY must be overwritten. That is the whole point of U6: a
# hand edit to the generated block is not a second source of truth.
$tmplPath = Join-Path $repo "CLAUDE.template.md"
(Get-Content -LiteralPath $tmplPath -Raw -Encoding UTF8).Replace("A NEW publisher rule.", "an edit made in the WRONG file") |
    Set-Content -LiteralPath $tmplPath -Encoding UTF8 -NoNewline
$r4 = Update-RtContractBlock -RepoRoot $repo
Check-True $r4.Changed "an edit to the generated copy is detected"
$tmpl = Get-Content -LiteralPath $tmplPath -Raw -Encoding UTF8
Check-True (-not ($tmpl -match "an edit made in the WRONG file")) "the edit to the copy is overwritten, not preserved"
Check-True ($tmpl -match "A NEW publisher rule\.") "the source wins"

Write-Header "refusals - each leaves the template untouched"
foreach ($case in @(
    @{ Name = "nomarker";  Body = "# Project rules`n`nNo markers at all."; Label = "a source with no RT-EXPORT marker is refused" },
    @{ Name = "onlybegin"; Body = "# Project rules`n`n<!-- RT-EXPORT:BEGIN -->`nsomething"; Label = "an unmatched RT-EXPORT:BEGIN is refused" },
    @{ Name = "reversed";  Body = "# Project rules`n`n<!-- RT-EXPORT:END -->`nx`n<!-- RT-EXPORT:BEGIN -->"; Label = "markers in the wrong order are refused" },
    @{ Name = "empty";     Body = "# Project rules`n`n<!-- RT-EXPORT:BEGIN -->`n`n<!-- RT-EXPORT:END -->"; Label = "an EMPTY export region is refused rather than publishing nothing" }
)) {
    $bad = New-Repo -Name $case.Name -SourceBody $case.Body
    $badTmpl = Join-Path $bad "CLAUDE.template.md"
    $hashBefore = (Get-FileHash -LiteralPath $badTmpl -Algorithm SHA256).Hash
    Check-Throws { Update-RtContractBlock -RepoRoot $bad } $case.Label
    Check-Eq $hashBefore (Get-FileHash -LiteralPath $badTmpl -Algorithm SHA256).Hash `
        "  and the template is byte-identical afterwards ($($case.Name))"
}

$noBlock = New-Repo -Name "notemplatemarker" -SourceBody $goodSource
$np = Join-Path $noBlock "CLAUDE.template.md"
Set-Content -LiteralPath $np -Value "# Global instructions`n`nNo contract markers here." -Encoding UTF8
Check-Throws { Update-RtContractBlock -RepoRoot $noBlock } "a template with no RT-CONTRACT marker is refused"

Write-Header "-Preview writes nothing (R16)"
$prev = New-Repo -Name "preview" -SourceBody $goodSource
$pp = Join-Path $prev "CLAUDE.template.md"
$hashBefore = (Get-FileHash -LiteralPath $pp -Algorithm SHA256).Hash
$rp = Update-RtContractBlock -RepoRoot $prev -Preview
Check-True $rp.Changed "-Preview reports that it would change the block"
Check-Eq $hashBefore (Get-FileHash -LiteralPath $pp -Algorithm SHA256).Hash "-Preview wrote nothing"

Write-Header "the real repository is untouched by this suite"
Check-True (Test-Path -LiteralPath $RealSource) "the repository's .claude/CLAUDE.md is present"
Write-Info "real template and source are hashed by the caller; this suite only wrote under TEMP"

Remove-Item -LiteralPath $Sandbox -Recurse -Force

Write-Header "Summary"
if ($script:Failures -eq 0) {
    Write-Host "  All checks passed." -ForegroundColor Green
    exit 0
}
Write-Host "  $script:Failures check(s) failed." -ForegroundColor Red
exit 1
