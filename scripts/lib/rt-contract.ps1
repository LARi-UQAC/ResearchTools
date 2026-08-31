#Requires -Version 5.1
<#
.SYNOPSIS
    Generates CLAUDE.template.md's RT-CONTRACT block from the marked export
    region of .claude/CLAUDE.md. Unit U6.

.DESCRIPTION
    There is one contract and there were two copies of it. The project file
    `.claude/CLAUDE.md` holds the academic rules; `CLAUDE.template.md` held a
    hand-maintained block that `install-junctions.ps1 -Sync` copies into the
    live `~/.claude/CLAUDE.md`, so that a session working in a THESIS folder
    still knows them. Two hand-maintained copies of one text drift, and
    `preferences.md` already forbids duplicating cross-layer context. This
    makes the second copy generated.

    Direction of travel, and it only goes one way:

        .claude/CLAUDE.md   (RT-EXPORT region, the SOURCE, edit here)
              |  Update-RtContractBlock, run by install.ps1
              v
        CLAUDE.template.md  (RT-CONTRACT block, generated)
              |  install-junctions.ps1 -Sync, marker to marker
              v
        ~/.claude/CLAUDE.md (loads in every project on the machine)

    Scope decided by the operator on 2026-08-30: the region carries the
    "Improving ResearchTools from another folder" contract plus the five
    academic sections (Role and mission, Writing standard, References,
    Language/figures/tables/equations, and the Tooling routing table), 182
    lines of the five, so that the approved-publisher list and the tool routing
    follow him into a paper folder instead of staying behind in this repository.

    This file is a library, dot-sourced by install.ps1 and by its test. It
    lives beside rt-sync.ps1 and rt-global-config.ps1 for the same reason those
    do: dot-sourcing install.ps1 to test one function would run the whole
    installer, regenerating every mirror as a side effect.

.NOTES
    Refuses rather than guessing (R8, R12): a missing marker, an unmatched
    marker, or an empty region is an explicit error naming the file, and
    nothing is written. Exit 2 from the CLI entry point is that refusal by
    design; 1 is a failure.

    Verifies the effect rather than the return code (R9): the result is parsed
    back out of the file it just wrote, and the function fails if what landed
    is not what was meant to land.
#>

Set-StrictMode -Version Latest

$script:RtExportBegin   = "<!-- RT-EXPORT:BEGIN -->"
$script:RtExportEnd     = "<!-- RT-EXPORT:END -->"
$script:RtContractBegin = "<!-- RT-CONTRACT:BEGIN -->"
$script:RtContractEnd   = "<!-- RT-CONTRACT:END -->"

# Written into the generated block so nobody edits the copy. The source file is
# named in it, because a reader who lands on the generated text needs to know
# where to go, and "see the repository" is not an address.
$script:RtGeneratedNote = @(
    "<!-- GENERATED from .claude/CLAUDE.md between its RT-EXPORT markers, by",
    "     scripts/lib/rt-contract.ps1 (run by install.ps1). Do not edit this copy:",
    "     the next install overwrites it. Edit .claude/CLAUDE.md instead. -->"
) -join "`n"

function Get-RtSectionBetween {
    <#
    .SYNOPSIS
        Returns the text strictly between two markers, or throws naming the file.
    #>
    param(
        [Parameter(Mandatory)][string]$Text,
        [Parameter(Mandatory)][string]$Begin,
        [Parameter(Mandatory)][string]$End,
        [Parameter(Mandatory)][string]$Label
    )
    $b = $Text.IndexOf($Begin)
    $e = $Text.IndexOf($End)
    if ($b -lt 0) { throw "$Label carries no $Begin marker" }
    if ($e -lt 0) { throw "$Label carries no $End marker" }
    if ($e -lt $b) { throw "$Label has its markers in the wrong order" }
    if ($Text.IndexOf($Begin, $b + $Begin.Length) -ge 0) { throw "$Label carries more than one $Begin marker" }
    $inner = $Text.Substring($b + $Begin.Length, $e - $b - $Begin.Length)
    if (-not $inner.Trim()) { throw "$Label has an EMPTY region between $Begin and $End" }
    return $inner
}

function Update-RtContractBlock {
    <#
    .SYNOPSIS
        Splices the export region of .claude/CLAUDE.md into the RT-CONTRACT
        block of CLAUDE.template.md. Idempotent.
    .OUTPUTS
        A PSCustomObject: Changed (bool), Lines (int), Message (string).
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$RepoRoot,
        [switch]$Preview
    )

    $sourcePath   = Join-Path $RepoRoot ".claude\CLAUDE.md"
    $templatePath = Join-Path $RepoRoot "CLAUDE.template.md"
    if (-not (Test-Path -LiteralPath $sourcePath))   { throw "source not found: $sourcePath" }
    if (-not (Test-Path -LiteralPath $templatePath)) { throw "template not found: $templatePath" }

    $source   = Get-Content -LiteralPath $sourcePath   -Raw -Encoding UTF8
    $template = Get-Content -LiteralPath $templatePath -Raw -Encoding UTF8

    $region = Get-RtSectionBetween -Text $source -Begin $script:RtExportBegin -End $script:RtExportEnd -Label ".claude/CLAUDE.md"
    # The region carries its own explanatory comment for a reader of the SOURCE.
    # That comment describes the source, not the copy, so it is dropped and the
    # generated note put in its place.
    $region = ($region -replace '(?s)<!--\s*Everything between these markers.*?-->', '').Trim("`r", "`n")

    # Relative links are written for a reader of .claude/CLAUDE.md, which sits
    # inside the repository. The generated copy ends up in ~/.claude/CLAUDE.md,
    # where `../README.md` and `rules/code-style.md` resolve to nothing at all.
    # A dead link is worse than no link, because it reads as a promise, so the
    # label is kept as plain text and the target dropped. An absolute path is
    # NOT used instead: it would bake one machine's repository location into a
    # tracked file. External links (http, https) are left exactly as they are,
    # since they resolve from anywhere.
    $region = [regex]::Replace($region, '\[([^\]\r\n]+)\]\((?!https?://)[^)\r\n]+\)', '$1')

    $current = Get-RtSectionBetween -Text $template -Begin $script:RtContractBegin -End $script:RtContractEnd -Label "CLAUDE.template.md"
    $wanted  = "`n" + $script:RtGeneratedNote + "`n`n" + $region + "`n"

    $lines = ($wanted -split "`n").Count
    if ($current -eq $wanted) {
        return [pscustomobject]@{ Changed = $false; Lines = $lines; Message = "RT-CONTRACT block already matches the export region" }
    }
    if ($Preview) {
        return [pscustomobject]@{ Changed = $true; Lines = $lines; Message = "would rewrite the RT-CONTRACT block from the export region ($lines lines)" }
    }

    $b = $template.IndexOf($script:RtContractBegin) + $script:RtContractBegin.Length
    $e = $template.IndexOf($script:RtContractEnd)
    $updated = $template.Substring(0, $b) + $wanted + $template.Substring($e)

    # No BOM: ConvertFrom-Json chokes on one elsewhere in this repo, and the
    # template is read back by check-claude-template.ps1 and by setup.ps1.
    [System.IO.File]::WriteAllText($templatePath, $updated, (New-Object System.Text.UTF8Encoding($false)))

    # R9: verify the effect, not the return code.
    $readBack = Get-Content -LiteralPath $templatePath -Raw -Encoding UTF8
    $landed = Get-RtSectionBetween -Text $readBack -Begin $script:RtContractBegin -End $script:RtContractEnd -Label "CLAUDE.template.md (after write)"
    if ($landed -ne $wanted) { throw "the RT-CONTRACT block was written but does not read back as intended" }

    return [pscustomobject]@{ Changed = $true; Lines = $lines; Message = "RT-CONTRACT block regenerated from the export region ($lines lines)" }
}
