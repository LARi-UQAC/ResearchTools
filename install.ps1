#Requires -Version 5.1
<#
.SYNOPSIS
    Generates per-tool agent mirrors from the canonical .claude/agents/*.md files
    so the same agents work in GitHub Copilot, OpenCode, Continue, and Aider.

.DESCRIPTION
    Canonical source of truth: .claude/agents/<name>.md (flat file, YAML frontmatter
    with name: and description:). This script regenerates, idempotently:

      .github/agents/<name>.agent.md   GitHub Copilot custom agents (repo level).
                                       Copilot enforces a 30,000-character prompt
                                       limit; bodies above the threshold become a
                                       stub profile that instructs the agent to
                                       read the canonical file first.
      .github/prompts/<name>.prompt.md GitHub Copilot prompt files, one per task
                                       command in .claude/commands/ (the Claude
                                       session-mode commands concis/slim/focus/ctx
                                       are skipped - they have no Copilot meaning).
                                       Invoke in Copilot Chat as /<name>.
      .github/instructions/<name>.instructions.md
                                       GitHub Copilot instructions, one per rule in
                                       .claude/rules/ (applyTo: "**").
      .github/copilot-instructions.md  Master Copilot instructions: mission, agent
                                       routing, skills pointer.
      .opencode/agent/<name>.md        OpenCode agents (full body, description key).
      .continue/rules/researchtools.md Continue rule pointing at the routing table.
      CONVENTIONS.md                   Aider pointer (created only if absent).
      .agents/skills/<name>/SKILL.md   Codex skill pointers: frontmatter only, with
                                       the description trimmed to whole sentences so
                                       the list stays under Codex's budget, and a
                                       body that points at the canonical skill.
      .claude/skills/AGENTS.md         Nested AGENTS.md appended to the root one when
                                       Codex runs with a cwd inside that tree.

    GENERATOR INTENT LIVES IN DATA, not here: mirror-policy.json at the repository
    root carries the Copilot stub threshold, Copilot's hard limit, both Codex
    ceilings, the session-mode skip list, the declared orphan mirrors, and the list
    of target dialects. This script reads it and so does the rt-observe collector,
    which is what lets a reader tell a deliberately empty mirror cell from a lost
    one without being able to run PowerShell.

    Skills have no Copilot equivalent: they are repo folders the agents read
    directly (.claude/skills/<name>/SKILL.md), so they work from any tool that
    can read the repository. Codex is the exception - it has a native skill
    convention, so it gets the pointer mirrors above and can invoke a skill by
    name instead of needing an agent or the routing table to mention it.

    Run after adding or editing an agent, then commit the regenerated mirrors.
    Copilot needs no install step: files on the default branch under
    .github/agents/ are auto-discovered (GitHub.com agents panel, coding agent,
    VS Code, Copilot CLI /agent or --agent <name>).

    The script also records the active domain profile (profiles/<name>.yaml) in
    .claude/CLAUDE.md: pass -Profile <name>, or answer the interactive prompt
    (non-interactive runs keep the default, engineering).

.EXAMPLE
    .\install.ps1
    .\install.ps1 -Personal   # also copy Copilot agents to ~/.copilot/agents
                                     # (available in every project via Copilot CLI)
    .\install.ps1 -Profile cosmetic   # select the active domain profile
    .\install.ps1 -Manifest           # also write .rt-mirrors.json (verdicts + policy hash)
#>
param(
    # The three generator-intent values below - the Copilot stub threshold, both
    # Codex ceilings, and the session-mode skip list further down - are NOT
    # declared here any more. They live in mirror-policy.json at the repository
    # root, because install.ps1 was the only thing that knew them and PowerShell
    # is not readable to most of the people who clone this repo. The collector
    # behind the rt-observe dashboard reads the same file, which is what lets it
    # tell an empty cell that is BY DESIGN from one that is a LOSS.
    #
    # Passing one of these explicitly still overrides the policy, for a one-off
    # experiment. Omitting it - the normal case - takes the policy value.
    [int]$CopilotStubThreshold,
    [int]$CodexSkillListBudget,
    [int]$CodexDocMaxBytes,
    [switch]$Personal,
    # Write .rt-mirrors.json: the verdict this run computed for every target,
    # plus the policy hash it used. Gitignored and machine-local, exactly like
    # .rt-green.json. The dashboard treats it as an enrichment, never a
    # prerequisite: with no manifest the matrix is still complete, it simply
    # cannot report drift SINCE an install nobody ran.
    [switch]$Manifest,
    # -Profile also works ($PROFILE is a PowerShell automatic variable, hence the alias)
    [Alias('Profile')][string]$DomainProfile
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$utf8NoBom  = New-Object System.Text.UTF8Encoding($false)
$repoRoot   = $PSScriptRoot
$agentsDir  = Join-Path $repoRoot ".claude\agents"

# --- Generator intent, read from data rather than declared here -------------
# A missing or unparsable policy is an explicit stop naming the file (R3). It is
# never defaulted: a silent fallback here would regenerate every mirror against
# invented thresholds and report [OK] for all of them, which is precisely the
# green-looking failure this repository keeps legislating against.

$policyPath = Join-Path $repoRoot "mirror-policy.json"
if (-not (Test-Path $policyPath)) {
    throw "mirror-policy.json not found at $policyPath. It carries the Copilot stub threshold, both Codex ceilings and the session-mode skip list; install.ps1 no longer declares any of them."
}
$policyRaw = [System.IO.File]::ReadAllText($policyPath, [System.Text.Encoding]::UTF8)
try {
    $policy = $policyRaw | ConvertFrom-Json
} catch {
    throw "mirror-policy.json does not parse: $($_.Exception.Message)"
}
$policyHash = (Get-FileHash -Path $policyPath -Algorithm SHA256).Hash

function Get-PolicyInt([string]$key) {
    if (-not $policy.thresholds.PSObject.Properties.Name.Contains($key)) {
        throw "mirror-policy.json declares no thresholds.$key"
    }
    $node = $policy.thresholds.$key
    if ($null -eq $node.value) { throw "mirror-policy.json: thresholds.$key has no 'value'" }
    return [int]$node.value
}

# An explicitly passed parameter still wins, for a one-off experiment; anything
# omitted takes the policy value. $PSBoundParameters is the exact test, since an
# unbound [int] is indistinguishable from a deliberate 0 by its value alone.
if (-not $PSBoundParameters.ContainsKey('CopilotStubThreshold')) { $CopilotStubThreshold = Get-PolicyInt 'copilot_stub_threshold' }
if (-not $PSBoundParameters.ContainsKey('CodexSkillListBudget'))  { $CodexSkillListBudget  = Get-PolicyInt 'codex_skill_list_budget' }
if (-not $PSBoundParameters.ContainsKey('CodexDocMaxBytes'))      { $CodexDocMaxBytes      = Get-PolicyInt 'codex_doc_max_bytes' }
$CopilotHardLimit = Get-PolicyInt 'copilot_hard_limit'

# --- Verdict recorder: what this run actually did, for -Manifest ------------
# install.ps1 already decides every verdict; it simply threw them away after
# printing. Collecting them costs nothing and gives the dashboard a second,
# independent source: the policy says what was INTENDED, the filesystem says what
# IS, and this says what the last generation DID.

$script:MirrorVerdicts = New-Object System.Collections.ArrayList
function Add-MirrorVerdict([string]$Target, [string]$Name, [string]$State, [hashtable]$Detail) {
    $record = [ordered]@{ target = $Target; name = $Name; state = $State }
    if ($Detail) { foreach ($k in $Detail.Keys) { $record[$k] = $Detail[$k] } }
    [void]$script:MirrorVerdicts.Add([pscustomobject]$record)
}

function Write-Ok([string]$text)   { Write-Host "  [OK]  $text" -ForegroundColor Green }
function Write-Skip([string]$text) { Write-Host "  [--]  $text" -ForegroundColor DarkGray }

function Read-AgentFile([string]$path) {
    $raw = [System.IO.File]::ReadAllText($path, [System.Text.Encoding]::UTF8)
    if ($raw -notmatch '(?s)^---\r?\n(.*?)\r?\n---\r?\n\s*(.*)$') {
        throw "No YAML frontmatter in $path"
    }
    $fm   = $Matches[1]
    $body = $Matches[2]
    $name = $null; $descLine = $null
    foreach ($line in ($fm -split "\r?\n")) {
        if ($line -match '^name:\s*(.+)$')  { $name = $Matches[1].Trim() }
        if ($line -match '^description:')   { $descLine = $line }
    }
    if (-not $name -or -not $descLine) { throw "Missing name/description in $path" }
    [pscustomobject]@{ Name = $name; DescriptionLine = $descLine; Body = $body }
}

$agents = Get-ChildItem $agentsDir -File -Filter *.md | ForEach-Object { Read-AgentFile $_.FullName }
Write-Host "Canonical agents found: $($agents.Count)"

# --- Active domain profile: select and record in .claude/CLAUDE.md ----------

$profilesDir  = Join-Path $repoRoot "profiles"
$profileNames = @()
foreach ($pf in (Get-ChildItem $profilesDir -File -Filter *.yaml | Where-Object { $_.Name -ne "_template.yaml" })) {
    foreach ($line in (Get-Content $pf.FullName)) {
        if ($line -match '^name:\s*(\S+)') { $profileNames += $Matches[1]; break }
    }
}
if ($profileNames.Count -eq 0) { throw "No profiles found under profiles/ (expected profiles/<name>.yaml with a name: key)" }

$activeProfile = $DomainProfile
if (-not $activeProfile) {
    # Read-Host throws under -NonInteractive; fall back to the default silently.
    $answer = $null
    try { $answer = Read-Host "Active domain profile [engineering] (available: $($profileNames -join ', '))" } catch { $answer = $null }
    if ($answer) { $activeProfile = $answer.Trim() } else { $activeProfile = "engineering" }
}
if ($profileNames -notcontains $activeProfile) {
    throw "Unknown profile '$activeProfile'. Valid profiles: $($profileNames -join ', ')"
}

$claudeMdPath = Join-Path $repoRoot ".claude\CLAUDE.md"
$claudeMd     = [System.IO.File]::ReadAllText($claudeMdPath, [System.Text.Encoding]::UTF8)
$claudeMd     = $claudeMd -replace '(?m)^active_profile:\s*\S+', "active_profile: $activeProfile"
$claudeMd     = $claudeMd -replace '(?m)^Profil actif : \S+', "Profil actif : $activeProfile"
[System.IO.File]::WriteAllText($claudeMdPath, $claudeMd, $utf8NoBom)
Write-Ok "active profile: $activeProfile (recorded in .claude/CLAUDE.md)"

# --- U6: regenerate the RT-CONTRACT block from .claude/CLAUDE.md -------------
# It must run BEFORE the mirrors below, because the mirrors are generated from
# the same source and a stale contract block would be published alongside a
# fresh mirror. The engine lives in scripts/lib/rt-contract.ps1 so its test can
# load it without running this installer.
. (Join-Path $repoRoot "scripts\lib\rt-contract.ps1")
try {
    $rtContract = Update-RtContractBlock -RepoRoot $repoRoot
    if ($rtContract.Changed) { Write-Ok "RT-CONTRACT block regenerated ($($rtContract.Lines) lines) from .claude/CLAUDE.md" }
    else                     { Write-Ok "RT-CONTRACT block already in step with .claude/CLAUDE.md" }
} catch {
    # A refusal here is deliberate and must stop the run: publishing mirrors
    # from a source whose export region is broken would spread the damage.
    Write-Host "  [ERR] RT-CONTRACT generation refused: $($_.Exception.Message)" -ForegroundColor Red
    exit 2
}

# --- GitHub Copilot: .github/agents/<name>.agent.md -------------------------

$ghDir = Join-Path $repoRoot ".github\agents"
New-Item -ItemType Directory -Path $ghDir -Force | Out-Null
foreach ($a in $agents) {
    if ($a.Body.Length -le $CopilotStubThreshold) {
        $body = $a.Body
        $mode = "full"
    } else {
        $body = @"
This is a compact profile. The complete, authoritative instructions live in
``.claude/agents/$($a.Name).md`` at the repository root; this stub exists because
GitHub Copilot limits agent prompts to 30,000 characters.

MANDATORY FIRST STEP: read ``.claude/agents/$($a.Name).md`` in this repository in
full before doing anything else, then follow it exactly. Do not act from this
stub alone.

Hard constraints carried over from the full definition:

- Validate every reference against Scopus; never fabricate references or DOIs.
- Approved publishers only (IEEE, Springer, Elsevier, Taylor & Francis, Cambridge,
  Wiley, IET, IOP, ACM, MDPI, ASME, ACME, BMC); ask before citing outside the list.
- LaTeX output goes to the ``out/`` sub-directory; follow the writing rules in
  ``.claude/CLAUDE.md`` (labels, figures, tables, equations, style hygiene).
"@
        $mode = "stub"
    }
    $out = "---`nname: $($a.Name)`n$($a.DescriptionLine)`n---`n`n$body`n"
    if ($out.Length -gt $CopilotHardLimit) { throw "$($a.Name): generated Copilot profile exceeds $CopilotHardLimit characters (mirror-policy.json thresholds.copilot_hard_limit)" }
    [System.IO.File]::WriteAllText((Join-Path $ghDir "$($a.Name).agent.md"), $out, $utf8NoBom)
    if ($mode -eq "stub") {
        # A stub carries none of the agent's instructions, only a pointer to the
        # canonical file. Seven long-form agents are stubs by design; anything
        # else here is an instruction set that just stopped reaching Copilot, so
        # it must not be printed as a green [OK].
        Write-Host ("  [STUB] .github/agents/{0}.agent.md  (body {1} > {2}; Copilot gets a pointer, not the instructions)" -f `
            $a.Name, $a.Body.Length, $CopilotStubThreshold) -ForegroundColor Yellow
        Add-MirrorVerdict 'copilot-agents' $a.Name 'stubbed' @{ body_chars = $a.Body.Length; threshold = $CopilotStubThreshold; written_chars = $out.Length }
    } else {
        Write-Ok (".github/agents/{0}.agent.md  ({1}, {2} chars)" -f $a.Name, $mode, $out.Length)
        Add-MirrorVerdict 'copilot-agents' $a.Name 'ok' @{ body_chars = $a.Body.Length; written_chars = $out.Length }
    }
}

# --- GitHub Copilot personal level: ~/.copilot/agents (optional) ------------

if ($Personal) {
    $personalDir = Join-Path $env:USERPROFILE ".copilot\agents"
    New-Item -ItemType Directory -Path $personalDir -Force | Out-Null
    Get-ChildItem $ghDir -File -Filter *.agent.md | ForEach-Object {
        Copy-Item $_.FullName (Join-Path $personalDir $_.Name) -Force
        Write-Ok ("~/.copilot/agents/{0}" -f $_.Name)
        Add-MirrorVerdict 'copilot-cli-agents' ($_.Name -replace '\.agent\.md$', '') 'ok' $null
    }
}

# VS Code user profile: prompt + instruction files usable in ANY workspace
# (%APPDATA%\Code\User\prompts holds both *.prompt.md and *.instructions.md).
# Copied AFTER generation below via Install-VSCodeUserFiles.
function Install-VSCodeUserFiles([string]$promptsDir, [string]$instructionsDir) {
    $vsUserPrompts = Join-Path $env:APPDATA "Code\User\prompts"
    New-Item -ItemType Directory -Path $vsUserPrompts -Force | Out-Null
    Get-ChildItem $promptsDir -File -Filter *.prompt.md | ForEach-Object {
        Copy-Item $_.FullName (Join-Path $vsUserPrompts $_.Name) -Force
        Write-Ok ("VSCode user prompts/{0}" -f $_.Name)
    }
    Get-ChildItem $instructionsDir -File -Filter *.instructions.md | ForEach-Object {
        Copy-Item $_.FullName (Join-Path $vsUserPrompts $_.Name) -Force
        Write-Ok ("VSCode user prompts/{0}" -f $_.Name)
    }
}

# --- GitHub Copilot: .github/prompts/<name>.prompt.md (from commands) -------

# The skip list is generator INTENT, so it lives in mirror-policy.json with the
# thresholds. An absent prompt mirror for one of these names is BY DESIGN; the
# collector needs that distinction to avoid reporting four deliberate skips as
# four losses, which is the defect the mirror matrix exists to prevent.
if (-not $policy.skips.PSObject.Properties.Name.Contains('session_mode_commands')) {
    throw "mirror-policy.json declares no skips.session_mode_commands"
}
$SessionModeCommands = @($policy.skips.session_mode_commands.values)
$cmdDir = Join-Path $repoRoot ".claude\commands"
$prDir  = Join-Path $repoRoot ".github\prompts"
New-Item -ItemType Directory -Path $prDir -Force | Out-Null
foreach ($cmd in (Get-ChildItem $cmdDir -File -Filter *.md)) {
    $cmdName = [System.IO.Path]::GetFileNameWithoutExtension($cmd.Name)
    if ($SessionModeCommands -contains $cmdName) {
        Write-Skip "prompt: $cmdName (Claude session mode)"
        Add-MirrorVerdict 'copilot-prompts' $cmdName 'by-design' @{ reason = 'session_mode_commands' }
        continue
    }
    $raw = [System.IO.File]::ReadAllText($cmd.FullName, [System.Text.Encoding]::UTF8)
    if ($raw -match '(?s)^---') {
        $c = Read-AgentFile $cmd.FullName
    } else {
        # Frontmatter-less command (Claude Code allows it): H1 becomes description
        $descText = $cmdName
        if ($raw -match '(?m)^#\s+(.+)$') { $descText = $Matches[1].Trim() }
        $body = ([regex]'(?m)^#\s+.+\r?\n').Replace($raw, '', 1).TrimStart()
        $c = [pscustomobject]@{
            Name            = $cmdName
            DescriptionLine = "description: `"$($descText.Replace('\','\\').Replace('"','\"'))`""
            Body            = $body
        }
    }
    # Copilot prompt files have no $ARGUMENTS placeholder; text typed after the
    # slash command in chat is part of the request.
    $body = $c.Body -replace '\$ARGUMENTS', 'the file(s) or topic given after the command in the chat message (if none was given, use the file currently open in the editor)'
    $out = "---`n$($c.DescriptionLine)`n---`n`n$body`n"
    [System.IO.File]::WriteAllText((Join-Path $prDir "$cmdName.prompt.md"), $out, $utf8NoBom)
    Write-Ok ".github/prompts/$cmdName.prompt.md"
    Add-MirrorVerdict 'copilot-prompts' $cmdName 'ok' $null
}

# --- GitHub Copilot: .github/instructions/<name>.instructions.md (from rules)

$rulesDir = Join-Path $repoRoot ".claude\rules"
$insDir   = Join-Path $repoRoot ".github\instructions"
New-Item -ItemType Directory -Path $insDir -Force | Out-Null
foreach ($rule in (Get-ChildItem $rulesDir -File -Filter *.md)) {
    $ruleName = [System.IO.Path]::GetFileNameWithoutExtension($rule.Name)
    $ruleBody = [System.IO.File]::ReadAllText($rule.FullName, [System.Text.Encoding]::UTF8)
    $out = "---`napplyTo: `"**`"`n---`n`n$ruleBody"
    [System.IO.File]::WriteAllText((Join-Path $insDir "$ruleName.instructions.md"), $out, $utf8NoBom)
    Write-Ok ".github/instructions/$ruleName.instructions.md"
    Add-MirrorVerdict 'copilot-instructions' $ruleName 'ok' $null
}

# --- GitHub Copilot: master .github/copilot-instructions.md ------------------

$agentRouting = ($agents | ForEach-Object { "- ``$($_.Name)``: see ``.github/agents/$($_.Name).agent.md`` (full definition in ``.claude/agents/$($_.Name).md``)" }) -join "`n"
$masterOut = @"
# ResearchTools - Copilot instructions

Academic toolkit: LaTeX writing, Scopus reference validation, paper/thesis
auditing, grant-template conversion. Authoritative academic standards (writing
rules, reference policy, approved publishers, figure/table/equation rules) live
in ``.claude/CLAUDE.md`` - read it before producing academic content.

Specialized custom agents (invoke from the agents panel, ``/agent`` in Copilot
CLI, or ``copilot --agent <name>``):

$agentRouting

Task prompt files are available as slash commands in Copilot Chat (see
``.github/prompts/``). Helper skills (Scopus API scripts, statistics extraction,
scientific-writing rules, corpus study-location mapping, recommendation/support/
acceptance letters, Obsidian vault operations) are plain repo folders under
``.claude/skills/`` - read the relevant ``SKILL.md`` when a task calls for it (e.g.
``geolocalisation`` to map where a corpus's studies were conducted,
``recommendation-letter`` to draft a support/recommendation/acceptance letter from
a candidate's files, ``latex-hygiene`` to score a manuscript's mechanical hygiene
(forbidden characters, AI-usage risk, word counts, brace and citation balance)
before applying an audit plan and building it, or ``obsidian-cli`` to read or
search the Obsidian vault through its allowed command surface, since skills have
no mirror of their own).

Hard rules: validate every reference against Scopus (scripts in
``.claude/skills/scopus/scripts/``); never fabricate references or DOIs; LaTeX
output goes to ``out/``.

Obsidian vault writes go through the outbox only: deposit the note in
``~/.claude/obsidian-outbox/`` with a first-line directive and let the
``obsidian-outbox-flush.py`` hook write it through the filesystem. The Obsidian CLI
commands ``create``, ``append`` and ``prepend`` are forbidden, together with
``eval``, ``dev:*``, ``plugin:install``, ``theme:install`` and every ``sync*``
except read-only ``sync:history``. The one exception is
``vault_consolidate.py --apply --yes``, an in-place link repair in notes that already
exist, dry-run until ``--yes`` is passed.

Local generation goes through ``.claude/skills/loop-engineer/scripts/ollama_bridge.py``,
never ``ollama run``. The bridge resolves the model itself through ``model_resolver.py``
and refuses rather than substituting a weaker one, so no agent or script names a model
tag. ``--role writer`` or ``--role coder`` says WHICH work is being done, and the resolver
returns the tag qualified for that role; without it both roles share one tag.
``--vault-context <terms>`` is MANDATORY: the bridge searches the vault itself and
exits 2 when neither it nor ``--no-vault-context`` is given, because a local model asked a
documented question with no context answers with a fluent invention that passes every
structural gate.

Any Python script an auditing or authoring agent needs is created inside
ResearchTools, under ``.claude/skills/<skill>/scripts/``, with an offline test
beside it in ``Test/`` - never in the session scratchpad and never in the
manuscript, thesis, or grant directory being worked on. Search the
"ResearchTools script surface" inventory in ``.claude/rules/testing.md`` first,
and extend an existing script with a flag or a subcommand rather than forking
one; the manuscript directory may hold a thin wrapper that calls the
ResearchTools script by path, never logic of its own. Several of the largest
agents (``paper-auditor``, ``scopus-auditor``, ``scopus-researcher``,
``thesis-auditor``, ``thesis-proposal-auditor``, ``reviewer-response``,
``cover-paper``) are the very agents that write such scripts, and are delivered
above as stubs pointing back at ``.claude/agents/<name>.md`` - read the
canonical file when the stub is what you were given, since this rule lives in
the full body, not the stub.

This file is generated by ``install.ps1`` - edit the canonical sources,
not this mirror.
"@
[System.IO.File]::WriteAllText((Join-Path $repoRoot ".github\copilot-instructions.md"), "$masterOut`n", $utf8NoBom)
Write-Ok ".github/copilot-instructions.md"
Add-MirrorVerdict 'copilot-master' 'copilot-instructions.md' 'ok' $null

if ($Personal) { Install-VSCodeUserFiles $prDir $insDir }

# --- OpenCode: .opencode/agent/<name>.md (full body, no size limit) ---------

$ocDir = Join-Path $repoRoot ".opencode\agent"
New-Item -ItemType Directory -Path $ocDir -Force | Out-Null
foreach ($a in $agents) {
    $out = "---`n$($a.DescriptionLine)`n---`n`n$($a.Body)`n"
    [System.IO.File]::WriteAllText((Join-Path $ocDir "$($a.Name).md"), $out, $utf8NoBom)
    Write-Ok (".opencode/agent/{0}.md" -f $a.Name)
}

# --- Continue: one rule file pointing at the canonical set ------------------

$ctDir = Join-Path $repoRoot ".continue\rules"
New-Item -ItemType Directory -Path $ctDir -Force | Out-Null
$agentList = ($agents | ForEach-Object { "- ``$($_.Name)`` - see ``.claude/agents/$($_.Name).md``" }) -join "`n"
$ctOut = @"
---
name: ResearchTools agents
description: Routing to the canonical ResearchTools agent definitions
---

This repository defines specialized academic agents as flat markdown files under
``.claude/agents/`` (canonical source of truth). When a task matches one of them,
read the corresponding file in full and follow it exactly:

$agentList

The task-to-agent routing table lives in ``.claude/CLAUDE.md`` (section "Tooling").

Obsidian vault writes go through the outbox only: deposit the note in
``~/.claude/obsidian-outbox/`` with a first-line directive and let the
``obsidian-outbox-flush.py`` hook write it through the filesystem. The Obsidian CLI
commands ``create``, ``append`` and ``prepend`` are forbidden, together with
``eval``, ``dev:*``, ``plugin:install``, ``theme:install`` and every ``sync*``
except read-only ``sync:history``. The one exception is
``vault_consolidate.py --apply --yes``, an in-place link repair in notes that already
exist, dry-run until ``--yes`` is passed.

Local generation goes through ``.claude/skills/loop-engineer/scripts/ollama_bridge.py``,
never ``ollama run``. The bridge resolves the model itself through ``model_resolver.py``
and refuses rather than substituting a weaker one, so no agent or script names a model
tag. ``--role writer`` or ``--role coder`` says WHICH work is being done, and the resolver
returns the tag qualified for that role; without it both roles share one tag.
``--vault-context <terms>`` is MANDATORY: the bridge searches the vault itself and
exits 2 when neither it nor ``--no-vault-context`` is given, because a local model asked a
documented question with no context answers with a fluent invention that passes every
structural gate.

Any Python script an auditing or authoring agent needs is created inside
ResearchTools, under ``.claude/skills/<skill>/scripts/``, with an offline test
beside it in ``Test/`` - never in the session scratchpad and never in the
manuscript, thesis, or grant directory being worked on. Search the
"ResearchTools script surface" inventory in ``.claude/rules/testing.md`` first,
and extend an existing script with a flag or a subcommand rather than forking
one. The manuscript directory may hold a thin wrapper that calls the
ResearchTools script by path; it holds no logic of its own.
"@
[System.IO.File]::WriteAllText((Join-Path $ctDir "researchtools.md"), "$ctOut`n", $utf8NoBom)
Write-Ok ".continue/rules/researchtools.md"
Add-MirrorVerdict 'continue-rules' 'researchtools.md' 'ok' $null

# --- Aider: CONVENTIONS.md mirror -------------------------------------------
# Regenerated like the other three mirrors, so an agent change reaches Aider too.
# Guarded by the marker on the first line: a CONVENTIONS.md without it was written
# by a human, and a human file is never overwritten by an installer.

$convPath   = Join-Path $repoRoot "CONVENTIONS.md"
$convMarker = "<!-- generated by install.ps1 - edit .claude/agents/ instead -->"
$convGenerated = $true
if (Test-Path $convPath) {
    $convFirst = (Get-Content $convPath -TotalCount 1)
    if ($convFirst -ne $convMarker) { $convGenerated = $false }
}
if ($convGenerated) {
    $convOut = @"
$convMarker
# Conventions

Specialized agent definitions for this repository live in ``.claude/agents/`` (one
flat markdown file per agent, YAML frontmatter). When performing a task covered by
one of them, read the matching ``.claude/agents/<name>.md`` in full and follow it:

$agentList

The task-to-agent routing table lives in ``.claude/CLAUDE.md`` (section "Tooling").
Skills are repository folders the agents read directly
(``.claude/skills/<name>/SKILL.md``), so they need no mirror.

Academic writing rules: validate references against Scopus, never fabricate DOIs,
LaTeX output in ``out/``.

Obsidian vault writes go through the outbox only. Deposit the note in
``~/.claude/obsidian-outbox/`` with a first-line directive and let the
``obsidian-outbox-flush.py`` hook write it through the filesystem. The Obsidian CLI
commands ``create``, ``append`` and ``prepend`` are forbidden, together with
``eval``, ``dev:*``, ``plugin:install``, ``theme:install`` and every ``sync*``
except read-only ``sync:history``. The one exception is
``vault_consolidate.py --apply --yes``, an in-place link repair in notes that already
exist, dry-run until ``--yes`` is passed.

Local generation goes through ``.claude/skills/loop-engineer/scripts/ollama_bridge.py``,
never ``ollama run``. The bridge resolves the model itself through ``model_resolver.py``
and refuses rather than substituting a weaker one, so no agent or script names a model
tag. ``--role writer`` or ``--role coder`` says WHICH work is being done, and the resolver
returns the tag qualified for that role; without it both roles share one tag.
``--vault-context <terms>`` is MANDATORY: the bridge searches the vault itself and
exits 2 when neither it nor ``--no-vault-context`` is given, because a local model asked a
documented question with no context answers with a fluent invention that passes every
structural gate.

Any Python script an auditing or authoring agent needs is created inside
ResearchTools, under ``.claude/skills/<skill>/scripts/``, with an offline test
beside it in ``Test/`` - never in the session scratchpad and never in the
manuscript, thesis, or grant directory being worked on. Search the
"ResearchTools script surface" inventory in ``.claude/rules/testing.md`` first,
and extend an existing script with a flag or a subcommand rather than forking
one. The manuscript directory may hold a thin wrapper that calls the
ResearchTools script by path; it holds no logic of its own.
"@
    [System.IO.File]::WriteAllText($convPath, "$convOut`n", $utf8NoBom)
    Write-Ok "CONVENTIONS.md"
    Add-MirrorVerdict 'aider-conventions' 'CONVENTIONS.md' 'ok' $null
} else {
    Write-Skip "CONVENTIONS.md hand-written (no generated marker) - not touched"
}

# --- AGENTS.md: shared master for any tool reading the AGENTS.md convention -
# Overwritten on every run, unlike CONVENTIONS.md above: Hermes Agent reads
# AGENTS.override.md in preference to this file, so a hand-written local
# variant has a first-class place and nothing is lost by regenerating.

$agentsMdPath = Join-Path $repoRoot "AGENTS.md"
$agentsMdOut = @"
<!-- generated by install.ps1 - edit .claude/agents/ instead -->
# ResearchTools

ResearchTools is an academic toolkit for LaTeX writing, Scopus reference
validation, paper and thesis auditing, and grant-template conversion. This
file is regenerated on every ``install.ps1`` run; local edits belong in
``AGENTS.override.md`` instead, which Hermes Agent reads in preference to
this file.

Specialized agents (flat markdown files under ``.claude/agents/``):

$agentList

The task-to-agent routing table lives in ``.claude/CLAUDE.md`` (section "Tooling").

Skills have no mirror of their own and are read directly at
``.claude/skills/<name>/SKILL.md`` - for example ``geolocalisation`` to map
where a corpus's studies were conducted, ``recommendation-letter`` to draft a
support/recommendation/acceptance letter from a candidate's files,
``latex-hygiene`` (``/texcheck``) to score a manuscript's mechanical hygiene
before applying an audit plan, or ``obsidian-cli`` to read or search the
Obsidian vault through its allowed command surface.

Obsidian vault writes go through the outbox only: deposit the note in
``~/.claude/obsidian-outbox/`` with a first-line directive and let the
``obsidian-outbox-flush.py`` hook write it through the filesystem. The Obsidian CLI
commands ``create``, ``append`` and ``prepend`` are forbidden, together with
``eval``, ``dev:*``, ``plugin:install``, ``theme:install`` and every ``sync*``
except read-only ``sync:history``. The one exception is
``vault_consolidate.py --apply --yes``, an in-place link repair in notes that already
exist, dry-run until ``--yes`` is passed.

Local generation goes through ``.claude/skills/loop-engineer/scripts/ollama_bridge.py``,
never ``ollama run``. The bridge resolves the model itself through ``model_resolver.py``
and refuses rather than substituting a weaker one, so no agent or script names a model
tag. ``--role writer`` or ``--role coder`` says WHICH work is being done, and the resolver
returns the tag qualified for that role; without it both roles share one tag.
``--vault-context <terms>`` is MANDATORY: the bridge searches the vault itself and
exits 2 when neither it nor ``--no-vault-context`` is given, because a local model asked a
documented question with no context answers with a fluent invention that passes every
structural gate.

Any Python script an auditing or authoring agent needs is created inside
ResearchTools, under ``.claude/skills/<skill>/scripts/``, with an offline test
beside it in ``Test/`` - never in the session scratchpad and never in the
manuscript, thesis, or grant directory being worked on. Search the
"ResearchTools script surface" inventory in ``.claude/rules/testing.md`` first,
and extend an existing script with a flag or a subcommand rather than forking
one. The manuscript directory may hold a thin wrapper that calls the
ResearchTools script by path; it holds no logic of its own.

Academic writing rules: validate references against Scopus, never fabricate DOIs,
LaTeX output in ``out/``.
"@
[System.IO.File]::WriteAllText($agentsMdPath, "$agentsMdOut`n", $utf8NoBom)
Write-Ok "AGENTS.md"
Add-MirrorVerdict 'agents-md' 'AGENTS.md' 'ok' $null

# --- Codex: .agents/skills/<name>/SKILL.md pointer mirrors ------------------
# Codex discovers skills by scanning .agents/skills in every directory from the
# working directory up to the repository root, and requires the entry file to be
# named exactly SKILL.md (that casing) carrying name: and description:.
#
# The mirror is a POINTER, never a copy. Duplicating 15 skill bodies would create
# a second truth that drifts from .claude/skills/, which is the defect the whole
# generated-mirror model exists to avoid. Only the frontmatter is reproduced,
# because the description is the entire trigger surface: it decides whether Codex
# reaches for the skill at all, and the body it then reads is the canonical one.
#
# Descriptions are trimmed to WHOLE SENTENCES under a computed per-skill cap so
# the list stays inside CodexSkillListBudget. This is not cosmetic. Over budget,
# Codex shortens descriptions itself and then omits skills with a warning, so a
# skill can stop being reachable without anything here failing - the same silent
# class as the Copilot stub. Measured 2026-08-28 on this repo: the untrimmed list
# is 9417 chars against a 8000 budget. The only choice is whether the trimming is
# ours and deliberate or Codex's and arbitrary.

function Read-SkillFrontmatter([string]$path) {
    $raw = [System.IO.File]::ReadAllText($path, [System.Text.Encoding]::UTF8)
    if ($raw -notmatch '(?s)^---\r?\n(.*?)\r?\n---\r?\n') { throw "No YAML frontmatter in $path" }
    $lines = $Matches[1] -split "\r?\n"
    $name = $null; $desc = $null
    for ($i = 0; $i -lt $lines.Count; $i++) {
        if ($lines[$i] -match '^name:\s*(.+)$') { $name = $Matches[1].Trim(); continue }
        if ($lines[$i] -match '^description:\s*(.*)$') {
            # A YAML folded description continues on the following indented lines
            # (recommendation-letter uses 10 of them), so a line-only read would
            # mirror a truncated trigger and quietly change when Codex fires.
            # "description: >" (or |, >-, |-) is a BLOCK SCALAR INDICATOR, not
            # text. recommendation-letter uses one; carrying it through mirrors a
            # description that literally begins "> Generate support...".
            $head = $Matches[1].Trim()
            if ($head -match '^[>|][-+]?\d*$') { $head = '' }
            $parts = @($head)
            for ($j = $i + 1; $j -lt $lines.Count; $j++) {
                if ($lines[$j] -match '^\s+\S') { $parts += $lines[$j].Trim() } else { break }
            }
            $desc = (($parts | Where-Object { $_ }) -join ' ').Trim()
            # Carry the VALUE, not its quoting. Eleven of these descriptions are
            # double-quoted at the source; trimming a quoted scalar mid-string
            # leaves an unterminated quote, the whole frontmatter stops parsing,
            # and the skill silently disappears from Codex. Measured 2026-08-28 on
            # the first generated set, which shipped 11 broken mirrors.
            if ($desc.Length -ge 2 -and
                (($desc[0] -eq '"' -and $desc[-1] -eq '"') -or
                 ($desc[0] -eq "'" -and $desc[-1] -eq "'"))) {
                $desc = $desc.Substring(1, $desc.Length - 2)
            }
        }
    }
    if (-not $name -or -not $desc) { throw "Missing name/description in $path" }
    [pscustomobject]@{ Name = $name; Description = $desc }
}

function Limit-Description([string]$text, [int]$cap) {
    if ($text.Length -le $cap) { return $text }
    $sentences = [regex]::Split($text, '(?<=[.!?])\s+')
    # The first sentence is kept even when it alone exceeds the cap: a mirror with
    # an empty description is a skill Codex can never trigger, which is worse than
    # one slightly over budget.
    $kept = $sentences[0]
    if ($sentences.Count -gt 1) {
        foreach ($s in $sentences[1..($sentences.Count - 1)]) {
            if (($kept.Length + 1 + $s.Length) -gt $cap) { break }
            $kept = "$kept $s"
        }
    }
    return $kept
}

$skillsDir      = Join-Path $repoRoot ".claude\skills"
$codexSkillsDir = Join-Path $repoRoot ".agents\skills"
$skills = @(Get-ChildItem $skillsDir -Directory | ForEach-Object {
    $skillFile = Join-Path $_.FullName "SKILL.md"
    if (Test-Path $skillFile) { Read-SkillFrontmatter $skillFile }
})
if ($skills.Count -eq 0) { throw "No skills found under .claude/skills/<name>/SKILL.md" }

$nameOverhead = 0
foreach ($s in $skills) { $nameOverhead += $s.Name.Length }
$perSkillCap = [math]::Floor(($CodexSkillListBudget - $nameOverhead) / $skills.Count)

New-Item -ItemType Directory -Path $codexSkillsDir -Force | Out-Null
$listChars = 0
foreach ($s in $skills) {
    $desc = Limit-Description $s.Description $perSkillCap
    $listChars += $s.Name.Length + $desc.Length
    # Emit as a single-quoted YAML scalar: descriptions contain ": " (every
    # "Trigger on:" clause does), which a plain scalar cannot hold, and single
    # quoting needs only the doubling below rather than backslash escaping.
    $descYaml = "'" + ($desc -replace "'", "''") + "'"
    $skillOut = Join-Path $codexSkillsDir $s.Name
    New-Item -ItemType Directory -Path $skillOut -Force | Out-Null
    $out = @"
---
name: $($s.Name)
description: $descYaml
---

Pointer mirror generated by ``install.ps1``. The authoritative skill, with every
instruction, script and reference it ships, lives at
``.claude/skills/$($s.Name)/SKILL.md`` in this repository.

MANDATORY FIRST STEP: read ``.claude/skills/$($s.Name)/SKILL.md`` in full and follow
it exactly. Do not act from this pointer alone - it carries the trigger description
and nothing else.
"@
    [System.IO.File]::WriteAllText((Join-Path $skillOut "SKILL.md"), "$out`n", $utf8NoBom)
    if ($desc.Length -lt $s.Description.Length) {
        Write-Host ("  [TRIM] .agents/skills/{0}/SKILL.md  (description {1} -> {2} chars to fit the Codex list budget)" -f `
            $s.Name, $s.Description.Length, $desc.Length) -ForegroundColor Yellow
        Add-MirrorVerdict 'codex-skills' $s.Name 'trimmed' @{ description_chars = $s.Description.Length; written_chars = $desc.Length }
    } else {
        Write-Ok (".agents/skills/{0}/SKILL.md" -f $s.Name)
        Add-MirrorVerdict 'codex-skills' $s.Name 'ok' @{ description_chars = $s.Description.Length }
    }
}
if ($listChars -gt $CodexSkillListBudget) {
    Write-Host ("  [WARN] Codex skill list is {0} chars over the {1} budget; Codex will shorten or omit entries" -f `
        ($listChars - $CodexSkillListBudget), $CodexSkillListBudget) -ForegroundColor Yellow
} else {
    Write-Ok ("Codex skill list: {0} skills, {1}/{2} chars" -f $skills.Count, $listChars, $CodexSkillListBudget)
}
Add-MirrorVerdict 'codex-skills' '(list budget)' $(if ($listChars -gt $CodexSkillListBudget) { 'over-budget' } else { 'ok' }) @{ skills = $skills.Count; list_chars = $listChars; budget = $CodexSkillListBudget }

# --- Codex: nested .claude/skills/AGENTS.md --------------------------------
# Codex concatenates one AGENTS.md per directory from the git root down to the
# working directory, later files overriding earlier ones. A session whose cwd is
# inside .claude/skills/ therefore gets this file appended to the root AGENTS.md.
# It carries the one rule most easily broken from inside that tree: extend the
# existing script surface rather than forking it.

$skillsAgentsMdPath = Join-Path $skillsDir "AGENTS.md"
$skillsAgentsMdOut = @"
<!-- generated by install.ps1 - edit .claude/rules/workflows.md instead -->
# Skill scripts

This file adds to the repository-root ``AGENTS.md``; it does not replace it.

Runnable code lives in ``.claude/skills/<skill>/scripts/`` with an offline test
beside it in ``Test/`` - no network, no API key, no model load. A script lives
beside its only caller (rule R18): one caller means the owning skill's
``scripts/`` directory, several callers mean a repository-wide home
(``.claude/hooks/``, ``profiles/``, ``install.ps1``).

Before writing anything new, search the "ResearchTools script surface" inventory
in ``.claude/rules/testing.md``. It is one line per script and is the fastest way
to find what already exists. Extend a script with a flag or a subcommand rather
than forking it, and add the new test to that file's offline-test block in the
same commit.

Constraints that bite hardest inside this tree:

- No hardcoded numeric value, path, or external identifier (R0, R1, R2). Model
  tags come from ``model_resolver.py`` alone, which refuses rather than
  substituting a weaker model.
- No silent fallback (R8). A missing dependency, key, or measurement stops the
  run and names what is missing.
- Verify the effect, not the return code, wherever the tool is known to lie (R9).
- Every suite asserts at least one failure path (R20).
"@
[System.IO.File]::WriteAllText($skillsAgentsMdPath, "$skillsAgentsMdOut`n", $utf8NoBom)

$chainBytes = (Get-Item $agentsMdPath).Length + (Get-Item $skillsAgentsMdPath).Length
if ($chainBytes -gt $CodexDocMaxBytes) {
    Write-Host ("  [WARN] AGENTS.md chain is {0} bytes, over Codex's {1}-byte project_doc_max_bytes; the tail is dropped" -f `
        $chainBytes, $CodexDocMaxBytes) -ForegroundColor Yellow
} else {
    Write-Ok (".claude/skills/AGENTS.md  (chain {0}/{1} bytes)" -f $chainBytes, $CodexDocMaxBytes)
}
Add-MirrorVerdict 'codex-nested-agents-md' 'AGENTS.md' $(if ($chainBytes -gt $CodexDocMaxBytes) { 'over-budget' } else { 'ok' }) @{ chain_bytes = $chainBytes; budget = $CodexDocMaxBytes }

# --- -Manifest: write down the verdicts this run computed -------------------
# Same contract as .rt-green.json: machine-local, gitignored, and an ENRICHMENT
# for the reader rather than a prerequisite. It records the policy hash so a
# consumer can tell a manifest written under a different policy from a current
# one, and it records whether -Personal ran, because the ~/.copilot/agents column
# is empty for two completely different reasons - never generated, or generated
# and since drifted - and only this file distinguishes them.

if ($Manifest) {
    $manifestPath = Join-Path $repoRoot ".rt-mirrors.json"
    # NOTE: not $manifest. PowerShell variable names are CASE INSENSITIVE, so
    # $manifest IS the [switch]$Manifest parameter, and assigning a dictionary to
    # it fails with a type error 700 lines from the parameter that caused it.
    # Same defect class as the $h / $H collision recorded in check-deployment.ps1.
    $manifestDoc = [ordered]@{
        generated    = (Get-Date -Format "yyyy-MM-ddTHH:mm:ss")
        policy_hash  = $policyHash
        policy_file  = "mirror-policy.json"
        personal_run = [bool]$Personal
        profile      = $activeProfile
        counts       = [ordered]@{
            agents   = $agents.Count
            skills   = $skills.Count
            commands = (Get-ChildItem $cmdDir -File -Filter *.md).Count
            rules    = (Get-ChildItem $rulesDir -File -Filter *.md).Count
        }
        verdicts     = @($script:MirrorVerdicts)
    }
    $json = $manifestDoc | ConvertTo-Json -Depth 6
    [System.IO.File]::WriteAllText($manifestPath, $json, $utf8NoBom)
    # R9: verify the effect, not the return code. ConvertTo-Json on an empty
    # verdict list would write a structurally valid file describing nothing.
    $written = ([System.IO.File]::ReadAllText($manifestPath, [System.Text.Encoding]::UTF8) | ConvertFrom-Json)
    if ($written.verdicts.Count -lt 1) {
        throw ".rt-mirrors.json was written but carries no verdicts; the recorder did not run."
    }
    Write-Ok (".rt-mirrors.json  ({0} verdicts, policy {1})" -f $written.verdicts.Count, $policyHash.Substring(0, 12))
}

Write-Host ""
Write-Host "Done. Commit the regenerated mirrors." -ForegroundColor Green
