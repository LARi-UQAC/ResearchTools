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

    Skills have no Copilot equivalent: they are repo folders the agents read
    directly (.claude/skills/<name>/SKILL.md), so they work from any tool that
    can read the repository.

    Run after adding or editing an agent, then commit the regenerated mirrors.
    Copilot needs no install step: files on the default branch under
    .github/agents/ are auto-discovered (GitHub.com agents panel, coding agent,
    VS Code, Copilot CLI /agent or --agent <name>).

.EXAMPLE
    .\install-agents.ps1
    .\install-agents.ps1 -Personal   # also copy Copilot agents to ~/.copilot/agents
                                     # (available in every project via Copilot CLI)
#>
param(
    [int]$CopilotStubThreshold = 28000,  # keep margin under the 30k hard limit
    [switch]$Personal
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$utf8NoBom  = New-Object System.Text.UTF8Encoding($false)
$repoRoot   = $PSScriptRoot
$agentsDir  = Join-Path $repoRoot ".claude\agents"

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
    if ($out.Length -gt 30000) { throw "$($a.Name): generated Copilot profile exceeds 30k" }
    [System.IO.File]::WriteAllText((Join-Path $ghDir "$($a.Name).agent.md"), $out, $utf8NoBom)
    Write-Ok (".github/agents/{0}.agent.md  ({1}, {2} chars)" -f $a.Name, $mode, $out.Length)
}

# --- GitHub Copilot personal level: ~/.copilot/agents (optional) ------------

if ($Personal) {
    $personalDir = Join-Path $env:USERPROFILE ".copilot\agents"
    New-Item -ItemType Directory -Path $personalDir -Force | Out-Null
    Get-ChildItem $ghDir -File -Filter *.agent.md | ForEach-Object {
        Copy-Item $_.FullName (Join-Path $personalDir $_.Name) -Force
        Write-Ok ("~/.copilot/agents/{0}" -f $_.Name)
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

$SessionModeCommands = @("concis", "slim", "focus", "ctx")   # Claude-only output modes
$cmdDir = Join-Path $repoRoot ".claude\commands"
$prDir  = Join-Path $repoRoot ".github\prompts"
New-Item -ItemType Directory -Path $prDir -Force | Out-Null
foreach ($cmd in (Get-ChildItem $cmdDir -File -Filter *.md)) {
    $cmdName = [System.IO.Path]::GetFileNameWithoutExtension($cmd.Name)
    if ($SessionModeCommands -contains $cmdName) { Write-Skip "prompt: $cmdName (Claude session mode)"; continue }
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
scientific-writing rules) are plain repo folders under ``.claude/skills/`` - read
the relevant ``SKILL.md`` when an agent or prompt refers to it.

Hard rules: validate every reference against Scopus (scripts in
``.claude/skills/scopus/scripts/``); never fabricate references or DOIs; LaTeX
output goes to ``out/``.

This file is generated by ``install-agents.ps1`` - edit the canonical sources,
not this mirror.
"@
[System.IO.File]::WriteAllText((Join-Path $repoRoot ".github\copilot-instructions.md"), "$masterOut`n", $utf8NoBom)
Write-Ok ".github/copilot-instructions.md"

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
"@
[System.IO.File]::WriteAllText((Join-Path $ctDir "researchtools.md"), "$ctOut`n", $utf8NoBom)
Write-Ok ".continue/rules/researchtools.md"

# --- Aider: CONVENTIONS.md pointer (never overwrite an existing file) --------

$convPath = Join-Path $repoRoot "CONVENTIONS.md"
if (-not (Test-Path $convPath)) {
    $convOut = @"
# Conventions

Specialized agent definitions for this repository live in ``.claude/agents/`` (one
flat markdown file per agent, YAML frontmatter). When performing a task covered by
one of them (literature review, paper/thesis audit, BibTeX cleaning, reviewer
response, submission check, LaTeX/TiKZ authoring, Word-to-LaTeX conversion), read
the matching ``.claude/agents/<name>.md`` in full and follow it. The routing table
is in ``.claude/CLAUDE.md``. Academic writing rules: validate references against
Scopus, never fabricate DOIs, LaTeX output in ``out/``.
"@
    [System.IO.File]::WriteAllText($convPath, "$convOut`n", $utf8NoBom)
    Write-Ok "CONVENTIONS.md (created)"
} else {
    Write-Skip "CONVENTIONS.md exists - not touched"
}

Write-Host ""
Write-Host "Done. Commit the regenerated mirrors." -ForegroundColor Green
