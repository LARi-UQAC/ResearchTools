#Requires -Version 5.1
<#
.SYNOPSIS
    Drift check between CLAUDE.template.md and this machine's live global
    ~/.claude/CLAUDE.md, plus two invariants on the shipped Obsidian outbox hook.

.DESCRIPTION
    Five prose and code corrections (Tasks 1 to 5 of the write-path hardening
    plan) fixed the template, the ResearchTools .claude/CLAUDE.md, the two
    local agents, docs/contributor-notes.md, and CLAUDE.template.md itself.
    Nothing compiles the template, so nothing notices it drifting from the
    live global file again. This script is that control.

    It performs its own copy of the substitution that setup.ps1 does
    (Invoke-TemplateSubstitution, {{KEY}} -> value), into a file under
    $env:TEMP, then:

    1. Diffs the generated copy against the live global CLAUDE.md and
       classifies every differing line against a documented, content-exact
       allowed-divergence list (see ALLOWED DIVERGENCES below).
    2. Asserts four explicit invariants (see INVARIANTS below).

    Exit code is 1 if any invariant fails, or if any template/live difference
    is NOT on the allowed-divergence list. Exit code is 0 only when every
    invariant holds and every difference found is a known, named, pending
    propagation (the remedy for those is always: run setup.ps1 once, by hand).

.SAFETY
    This script NEVER invokes setup.ps1 and NEVER writes to the live global
    CLAUDE.md. Running setup.ps1 would regenerate that file from the template
    and would discard any correction made directly on the live copy - that
    silent-overwrite risk is the defect this whole check exists to catch, so
    the check itself must not be a second way to trigger it. The generated
    comparison copy lives under $env:TEMP and is never copied over the live
    file by this script.

.INVARIANTS
    1. The template has no `daily:append` (there were 6 before Task 1).
    2. No definition file (.claude/agents, .claude/commands, .claude/skills,
       plus the two per-agent mirror trees .github/agents/*.agent.md and
       .opencode/agent/*.md) uses a removed 30_Ressources folder
       (Apprentissages/, Methodes/, GardeFous/) as a LIVE location. A match
       is exempt ONLY when its trimmed line content is byte-identical to one
       of the two hardcoded $sanctionedLines entries quoted from
       .claude/agents/local-writer.md's own sentence that Methodes/ and
       Apprentissages/ were renamed away on 2026-08-03 (that sentence is
       required by an earlier task and must not fail this check). This is a
       content-exact allow-list, not a nearby-words pattern: fix round 1
       replaced an earlier "does a sanctioning phrase appear somewhere in a
       3-line window" test after a scratch fixture proved it defeatable by
       pasting unrelated boilerplate containing the same words near a live
       path. See the $sanctionedLines comment in the script body for the
       exact fixture. .continue/rules/researchtools.md is a single combined
       rules file, not a per-agent mirror, and carries none of these three
       folder names today (verified at fix time) - it is intentionally not
       scanned; see WHAT THIS CHECK DOES NOT COVER.
    3. The shipped hook (.claude/hooks/obsidian-outbox-flush.py) contains
       `st_size` (it verifies a write by comparing file size, not a return
       code).
    4. The shipped hook does NOT contain `OBSIDIAN_COM` (writes go through
       the filesystem, never through the Obsidian CLI binary).

.ALLOWED DIVERGENCES (today, content-exact, not a pattern)
    Task 5 advanced CLAUDE.template.md with a correction the live global file
    cannot yet receive, because this script (and every other script in this
    repository) is forbidden from running setup.ps1. Exactly three content
    lines diverge as a result, each matched below by a literal, ASCII-only
    substring taken from the real line (never a character-class regex), so a
    future and DIFFERENT edit to these same lines is reported as a failure,
    not silently accepted:
      a. the D3 forbidden-command table row for `obsidian create` / `append`
         / `prepend`, present in the template, absent from the live file;
      b. the D3 allowed-commands line: the live file still lists `obsidian
         create`, `append`, `prepend` as allowed; the template removed them;
      c. the "NE JAMAIS ecrire une note par obsidian create ou append"
         paragraph: the template names two Obsidian versions (1.13.4 and
         1.13.7); the live file still names only 1.13.4.
    Each is printed as "pending propagation" with the remedy: run setup.ps1
    once, by hand, which now regenerates the live file correctly.

.ENCODING NOTE (R15 - BOM insensitivity)
    PowerShell 5.1's `Set-Content -Encoding UTF8` always writes a UTF-8 byte
    order mark; the live global CLAUDE.md on disk does not carry one. The
    comparison below reads both files with Get-Content, which decodes and
    discards a leading BOM on read, so a BOM-only difference never appears
    among $diffEntries - a byte-exact comparison would instead fail forever
    on that artefact alone. This script does not repeat that mistake, but the
    fact is called out here because a future edit that switches to a raw byte
    or hash comparison would reintroduce it.

.WHAT THIS CHECK DOES NOT COVER
    It compares the template against ONE machine's live global file: the one
    at $env:USERPROFILE\.claude\CLAUDE.md on the machine running this script.
    A second contributor's own ~/.claude/CLAUDE.md, on their own machine, is
    invisible to it - this script cannot see it, was not run against it, and
    a clean exit here says nothing about whether that contributor's copy has
    drifted the same way. The allowed-divergence list above is equally
    single-machine and single-moment: it names exactly today's known gap, not
    a general "template ahead of live is fine" rule. Invariant 2's mirror
    coverage is partial by choice, not by oversight: the two per-agent mirror
    trees (.github/agents, .opencode/agent) are scanned, but
    .continue/rules/researchtools.md is not, because it is one combined rules
    file rather than a per-agent mirror and the exact-match allow-list this
    invariant now uses was built to describe individual sanctioned LINES, not
    a differently-shaped digest file; a future edit that copies the removed-
    folder text into that file would be invisible to this check. A check
    believed to cover everything is more dangerous than no check; this one
    covers one machine, one file, two mirror trees, and four invariants, and
    says so.

.EXAMPLE
    .\scripts\audit\check-claude-template.ps1
#>

[CmdletBinding()]
param(
    [string]$GlobalClaudeMd = (Join-Path $env:USERPROFILE ".claude\CLAUDE.md"),
    [string]$ObsidianVault = $(if ($env:OBSIDIAN_VAULT) { $env:OBSIDIAN_VAULT } else { "C:\Martin Otis\Vault" }),
    # The three below default to the real repo locations and exist only so this
    # script can be exercised against a scratch copy while proving an
    # invariant fails, without ever touching a tracked repo file. Normal usage
    # (no arguments) is unaffected.
    [string]$TemplatePath,
    [string]$HookPath,
    [string[]]$DefinitionPaths
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Write-Header([string]$text) { Write-Host ""; Write-Host "=== $text ===" -ForegroundColor Cyan }
function Write-Ok([string]$text)     { Write-Host "  [OK]   $text" -ForegroundColor Green }
function Write-Warn([string]$text)   { Write-Host "  [INFO] $text" -ForegroundColor Yellow }
function Write-Fail([string]$text)   { Write-Host "  [FAIL] $text" -ForegroundColor Red }

$exitCode = 0

# --- Locate repo-relative inputs -------------------------------------------
# scripts\audit\check-claude-template.ps1 -> repo root is two levels up.
$RepoRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$templateSrc = if ($TemplatePath) { $TemplatePath } else { Join-Path $RepoRoot "CLAUDE.template.md" }
$hook = if ($HookPath) { $HookPath } else { Join-Path $RepoRoot ".claude\hooks\obsidian-outbox-flush.py" }
# Where the write actually happens since the Stage 0 extraction. The hook keeps
# the vault default, the outbox location and the promise never to block a
# session; the byte-size verification lives here, shared with the daemon.
$writeModule = Join-Path $RepoRoot ".claude\skills\obsidian-cli\scripts\outbox_io.py"

if (-not (Test-Path $templateSrc)) {
    Write-Fail "Template not found: $templateSrc"
    exit 1
}
if (-not (Test-Path $hook)) {
    Write-Fail "Hook not found: $hook"
    exit 1
}

# --- Step 1: generate the template with today's substitutions --------------
# Duplicates only Invoke-TemplateSubstitution's $claudeVars map from
# setup.ps1 (lines ~194-233 there); never dot-sources or invokes setup.ps1
# itself. Output goes under $env:TEMP, never over the live file (see SAFETY).
Write-Header "Generating template (never via setup.ps1)"

$obsidianExeCandidates = @(
    (Join-Path $env:LOCALAPPDATA "Programs\Obsidian\Obsidian.exe"),
    "C:\Program Files\Obsidian\Obsidian.exe"
)
$obsidianExe = $obsidianExeCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $obsidianExe) { $obsidianExe = "NOT_CONFIGURED" }

$claudeVars = @{
    OBSIDIAN_VAULT = $ObsidianVault
    OBSIDIAN_EXE   = $obsidianExe
    WORKSPACE_ROOT = $RepoRoot
    USERPROFILE    = $env:USERPROFILE
}

$templateContent = Get-Content -Path $templateSrc -Raw -Encoding UTF8
foreach ($key in $claudeVars.Keys) {
    $templateContent = $templateContent -replace [regex]::Escape("{{$key}}"), $claudeVars[$key]
}

$generated = Join-Path $env:TEMP "check-claude-template-generated.md"
Set-Content -Path $generated -Value $templateContent -Encoding UTF8 -NoNewline
Write-Ok "Generated: $generated"
Write-Host "  OBSIDIAN_VAULT = $ObsidianVault"
Write-Host "  OBSIDIAN_EXE   = $obsidianExe"

# --- Step 2: diff the generated copy against the live global file ----------
Write-Header "Template vs live global CLAUDE.md ($GlobalClaudeMd)"

$diffEntries = @()
if (-not (Test-Path $GlobalClaudeMd)) {
    Write-Warn "Live global file not found: $GlobalClaudeMd (nothing to compare)"
} else {
    # Get-Content decodes and strips a leading UTF-8 BOM on read, so this
    # line-array comparison is BOM-insensitive by construction. See the
    # ENCODING NOTE in the header comment (R15).
    $genLines = Get-Content -Path $generated -Encoding UTF8
    $liveLines = Get-Content -Path $GlobalClaudeMd -Encoding UTF8
    $diffEntries = @(Compare-Object -ReferenceObject $liveLines -DifferenceObject $genLines)
    Write-Host "  Differing line(s): $($diffEntries.Count)"
}

# Content-exact allowed-divergence anchors (R17). Each Anchor is a literal,
# ASCII-only substring of the real line, not a character class, so a future
# and different edit to the same line is not silently accepted. ASCII-only
# is deliberate: a PowerShell 5.1 script file without a byte order mark is
# read back in the system code page, not UTF-8, so an accented literal here
# would risk a silent mismatch (verified while building this check).
$allowedDivergences = @(
    @{ Name = "D3 forbidden-table row for obsidian create/append/prepend (added in template)"
       Anchor = 'obsidian create` / `append` / `prepend' },
    @{ Name = "D3 allowed-commands line (create/append/prepend removed in template)"
       Anchor = 'obsidian move`, `obsidian rename' },
    @{ Name = "paragraph carrying the two Obsidian versions (1.13.4 and 1.13.7)"
       Anchor = 'obsidian create` ou `obsidian append' },
    # Added 2026-08-28 with the graphify sections. restart-ollama.ps1 moved out
    # of scripts\dev\ to sit beside its only caller (R18), so the template
    # carries the new path and the live file still carries the old one. The
    # anchor is the part BOTH lines share, since this check tests each differing
    # line on its own and the pair must classify together.
    @{ Name = "restart-ollama.ps1 path (moved beside its only caller in the template)"
       Anchor = 'restart-ollama.ps1`, jamais par `Stop-Process -Name "ollama*"' }
)

$unclassified = @()
$pending = @()
foreach ($entry in $diffEntries) {
    $line = [string]$entry.InputObject
    # .Contains(), not -like: the -like wildcard engine treats a backtick as
    # ITS OWN escape character inside the pattern (unrelated to PowerShell
    # string escaping), so an anchor containing a raw backtick - every anchor
    # here does, since they quote inline code from the source Markdown -
    # would silently fail to match under -like. Verified while building this
    # check.
    $match = $allowedDivergences | Where-Object { $line.Contains($_.Anchor) } | Select-Object -First 1
    if ($match) {
        $pending += [PSCustomObject]@{
            Side = $entry.SideIndicator
            Name = $match.Name
            Text = $line
        }
    } else {
        $unclassified += [PSCustomObject]@{
            Side = $entry.SideIndicator
            Text = $line
        }
    }
}

if ($pending.Count -gt 0) {
    Write-Warn "Pending propagation (on the allowed-divergence list; remedy: run setup.ps1 once, by hand):"
    foreach ($p in ($pending | Sort-Object Name -Unique)) {
        Write-Host "    - $($p.Name)"
    }
}

if ($unclassified.Count -gt 0) {
    Write-Fail "Unclassified difference(s) between template and live global file:"
    foreach ($u in $unclassified) {
        $preview = $u.Text
        if ($preview.Length -gt 160) { $preview = $preview.Substring(0, 160) + " (truncated)" }
        Write-Host "    $($u.Side) $preview"
    }
    $exitCode = 1
} else {
    Write-Ok "No unclassified difference: every line that differs is on the allowed-divergence list."
}

# --- Step 3: the four invariants --------------------------------------------
Write-Header "Invariants"

# Content-exact allow-list for invariant 2 (fix round 1, replacing a bag-of-
# words context check). MEASURED DEFEAT: a pattern test of the form
# "does a nearby line contain no longer exist|renamed away" is a bag-of-words
# test, not a check that the sanctioning clause is ABOUT the folder mention on
# that line. A scratch fixture proved it:
#
#   Store your reusable learning notes under `30_Ressources/Methodes/` going
#   forward, because that folder was renamed away in some other unrelated
#   context, not here.
#
# That is a genuine instruction to use the removed folder as a live location,
# and the old context-window check passed it, because "renamed away" appears
# somewhere in the same three-line window regardless of what it is actually
# talking about. A content-exact allow-list cannot be defeated this way: a
# new violating line is simply not byte-for-byte one of the two sanctioned
# lines below, so it fails, no matter what boilerplate surrounds it. Do not
# "simplify" this back into a regex; the fixture above is the reason not to.
#
# Both lines are quoted verbatim (trimmed of leading/trailing whitespace) from
# .claude/agents/local-writer.md, where the sentence legitimately states that
# Methodes/ and Apprentissages/ were renamed away on 2026-08-03. The mirrors
# .github/agents/local-writer.agent.md and .opencode/agent/local-writer.md
# carry byte-identical copies of the same two lines (verified), so the same
# two entries cover all three scanned copies without growing the list; see
# the header's INVARIANTS section 2 for which trees are scanned and why
# .continue/rules is not among them.
$sanctionedLines = @(
    '`PowerShell/`, `Publication/`, and one folder per technology followed). `30_Ressources/Methodes/`',
    'and `Apprentissages/` no longer exist - they were renamed away on 2026-08-03.',
    # Added 2026-08-28. local-writer.md was rewritten around the live folder
    # counts, and this line names both retired folders for the one reason the
    # invariant exists to protect: to say they are retired. Naming a folder to
    # forbid it is the opposite of using it as a live location, and an exact
    # line is the only safe way to say so - a nearby-words exemption is what
    # this allow-list was built to replace.
    'technology - not the retired plural `Methodes/`. `Apprentissages/` is gone.'
)

function Test-NoLiveRemovedFolder {
    <#
    --------------------------------------------------------------------------
    Purpose:
        Invariant 2, with the R18 exception applied: a line naming a removed
        30_Ressources folder (Apprentissages/, Methodes/, GardeFous/) fails
        UNLESS its trimmed content exactly equals one of $sanctionedLines.
        Exact-match, not a nearby-words check - see the block comment above
        this function for the measured defeat that forced this design.

    Inputs:
        Paths (string[]): definition files to scan (agents, commands, skills,
            and the two per-agent mirror trees; see caller)

    Outputs:
        offenses ([PSCustomObject[]]): one entry per unsanctioned match, with
            File, Line, and Text
    --------------------------------------------------------------------------
    #>
    param([string[]]$Paths)
    $offenses = @()
    if (-not $Paths -or $Paths.Count -eq 0) { return $offenses }
    $hits = Select-String -Path $Paths -Pattern 'Apprentissages/|Methodes/|GardeFous/'
    foreach ($hit in $hits) {
        $trimmed = $hit.Line.Trim()
        # -cnotcontains, not -notcontains: PowerShell's default -contains /
        # -notcontains comparison is CASE-INSENSITIVE, so an ALL-CAPS
        # permutation of a sanctioned line would have matched and been
        # wrongly exempted, defeating the "byte-identical" claim this
        # invariant makes above. -cnotcontains is case-sensitive, which is
        # what an exact-match allow-list actually requires.
        if ($sanctionedLines -cnotcontains $trimmed) {
            $offenses += [PSCustomObject]@{
                File = $hit.Path
                Line = $hit.LineNumber
                Text = $trimmed
            }
        }
    }
    return $offenses
}

if ($DefinitionPaths) {
    $defPaths = $DefinitionPaths
} else {
    # Fix round 1 (Minor 2): widened from .claude only to also scan the two
    # per-agent mirror trees, so a mirror-only regression (someone hand-edits
    # a .github/.opencode copy without regenerating it) is no longer
    # invisible. .continue/rules is NOT scanned: it is one combined rules
    # file, not a per-agent mirror, and a repo-wide check at fix time found no
    # occurrence of Apprentissages/, Methodes/, or GardeFous/ in it - adding
    # it would add scanning cost for a file shape this exact-match list was
    # never built to describe. See the header's "WHAT THIS CHECK DOES NOT
    # COVER" section for this same statement.
    $defPaths = @()
    $defPaths += (Get-ChildItem -Path (Join-Path $RepoRoot ".claude\agents") -Filter "*.md" -File -ErrorAction SilentlyContinue).FullName
    $defPaths += (Get-ChildItem -Path (Join-Path $RepoRoot ".claude\commands") -Filter "*.md" -File -ErrorAction SilentlyContinue).FullName
    $defPaths += (Get-ChildItem -Path (Join-Path $RepoRoot ".claude\skills") -Filter "*.md" -Recurse -File -ErrorAction SilentlyContinue).FullName
    $defPaths += (Get-ChildItem -Path (Join-Path $RepoRoot ".github\agents") -Filter "*.agent.md" -File -ErrorAction SilentlyContinue).FullName
    $defPaths += (Get-ChildItem -Path (Join-Path $RepoRoot ".opencode\agent") -Filter "*.md" -File -ErrorAction SilentlyContinue).FullName
}

# Normalizes a Select-String MatchInfo (.Path, .LineNumber, .Line-as-text) into
# the same File/Line/Text shape Test-NoLiveRemovedFolder already returns, so the
# printing loop below never has to guess which shape it received. Select-String
# itself exposes a .Line property that holds the matched TEXT, not a number -
# reusing that name for a line NUMBER in a hand-built object would collide.
function ConvertTo-Offense {
    param([Parameter(ValueFromPipeline = $true)]$MatchInfo)
    process {
        [PSCustomObject]@{ File = $MatchInfo.Path; Line = $MatchInfo.LineNumber; Text = $MatchInfo.Line.Trim() }
    }
}

$invariants = @(
    @{
        Name = "template has no daily:append"
        Test = { @(Select-String -Path $templateSrc -Pattern 'daily:append' -AllMatches).Count -eq 0 }
        Offenses = { @(Select-String -Path $templateSrc -Pattern 'daily:append' -AllMatches) | ConvertTo-Offense }
    },
    @{
        Name = "no removed 30_Ressources folder used as a live location (content-exact allow-list)"
        Test = { @(Test-NoLiveRemovedFolder -Paths $defPaths).Count -eq 0 }
        Offenses = { @(Test-NoLiveRemovedFolder -Paths $defPaths) }
    },
    @{
        # The property is "the write is verified by reading the size back",
        # never "this file contains the string st_size". Stage 0 of the vault
        # daemon moved the write into outbox_io.py so the hook and the daemon
        # share ONE implementation, and this check went red on 2026-08-28 while
        # the property it guards held perfectly. Both halves are asserted: the
        # module still verifies, and the hook still routes through it.
        Name = "the shipped write path verifies by st_size, and the hook uses it"
        Test = {
            (Test-Path $writeModule) -and
            (Select-String -Path $writeModule -Pattern 'st_size' -Quiet) -and
            (Select-String -Path $hook -Pattern 'outbox_io' -Quiet)
        }
        Offenses = { @() }  # absence failure; nothing to enumerate by line
    },
    @{
        Name = "shipped hook has no OBSIDIAN_COM"
        Test = { -not (Select-String -Path $hook -Pattern 'OBSIDIAN_COM' -Quiet) }
        Offenses = { @(Select-String -Path $hook -Pattern 'OBSIDIAN_COM' -AllMatches) | ConvertTo-Offense }
    }
)

foreach ($inv in $invariants) {
    $passed = & $inv.Test
    if ($passed) {
        Write-Ok $inv.Name
    } else {
        Write-Fail $inv.Name
        $offenses = @(& $inv.Offenses)
        if ($offenses.Count -gt 0) {
            foreach ($o in $offenses) {
                Write-Host "    $($o.File):$($o.Line)"
            }
        } else {
            Write-Host "    $hook (pattern absent)"
        }
        $exitCode = 1
    }
}

# --- Summary -----------------------------------------------------------------
Write-Header "Summary"
if ($exitCode -eq 0) {
    Write-Ok "All invariants hold; every template/live difference is on the allowed-divergence list."
} else {
    Write-Fail "Drift detected. Fix the file(s) named above before continuing."
}

exit $exitCode
