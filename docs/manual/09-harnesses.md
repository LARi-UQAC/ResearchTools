# Harnesses and mirrors

Chapter 09 of the ResearchTools manual. Back to [table of contents](../../README.md).

A harness is the tool a person types into: Claude Code, GitHub Copilot, OpenCode, Continue, Aider,
Codex. ResearchTools is written once, for Claude Code, in `.claude/`. Every other harness reads a
**mirror**, a file `install.ps1` generates from the canonical definitions. The canonical files are the
single source of truth. Never edit a mirror by hand, since the next run overwrites it.

## What each harness receives

| Harness | Generated target | Scope | From | Notes |
|---|---|---|---|---|
| Claude Code | `.claude/` itself, linked into `~/.claude/` | user | none | Native. Agents, skills, commands, rules and hooks, see [chapter 01](01-installation.md) |
| GitHub Copilot, agents | `.github/agents/<name>.agent.md` | repo | `.claude/agents/` | Copilot caps an agent prompt at 30,000 characters. A larger agent is replaced by a short stub that reads the canonical file first, and the state is reported `stubbed`, never `ok` |
| GitHub Copilot, prompts | `.github/prompts/<name>.prompt.md` | repo | `.claude/commands/` | One prompt per task command, invoked as `/<name>` in Copilot Chat. The four session modes (`concis`, `slim`, `focus`, `ctx`) have no meaning outside Claude Code and are skipped on purpose |
| GitHub Copilot, rules | `.github/instructions/<name>.instructions.md` | repo | `.claude/rules/` | One per rules file, applied to all files. `mermaid.instructions.md` is hand-kept and has no canonical source, by design |
| GitHub Copilot, master | `.github/copilot-instructions.md` | repo | the repository | Mission, agent routing and a pointer to the skills |
| GitHub Copilot CLI | `~/.copilot/agents/<name>.agent.md` | user | `.claude/agents/` | Written only with `install.ps1 -Personal`. Agents added since the last such run are invisible to the CLI |
| VS Code user profile | `%APPDATA%/Code/User/prompts/` | user | prompts and rules | Written only with `-Personal`. Copies the generated prompts and instructions so they work in any workspace |
| OpenCode | `.opencode/agent/<name>.md` | repo | `.claude/agents/` | Full body, no size ceiling, so it never degrades to a stub |
| Continue | `.continue/rules/researchtools.md` | repo | `.claude/rules/` | One rule that points at the canonical files and the routing table |
| Aider | `CONVENTIONS.md` | repo | the repository | A pointer paragraph. Created once and never overwritten, so your edits survive |
| Aider, nightly pipeline | `.claude/skills/aider-setup/config/rules.md` | repo | `.claude/rules/` | Not made by `install.ps1`: the kit build regenerates it from the rules, see [chapter 11](11-aider-pipeline.md) |
| Any `AGENTS.md` reader | `AGENTS.md` | repo | the repository | The distilled master: agent list, routing pointer, skills examples, cross-cutting rules. Readers include Hermes Agent, OpenHuman and Codex |
| Codex, skills | `.agents/skills/<name>/SKILL.md` | repo | `.claude/skills/` | Codex is the only harness with a native skill convention. Each mirror holds the frontmatter only, since the description is the whole trigger surface. Descriptions are trimmed to whole sentences to fit Codex's skill-list budget, and the state is reported `trimmed` |
| Codex, nested instructions | `.claude/skills/AGENTS.md` | repo | the repository | Adds the script-surface rule for work inside the skills tree. Codex drops the deepest file when the chain exceeds its size cap |

OpenHands was considered and is **not** built: it has no mirror entry, because a target written for a
guessed convention would be an invented one.

## Generating the mirrors

```powershell
.\install.ps1                     # repo-level mirrors only, commit the output
.\install.ps1 -Personal           # also ~/.copilot/agents and the VS Code user profile
.\install.ps1 -Profile cosmetic   # also switch the active domain profile
```

Run it after every edit to an agent, a command or a rule, and commit the regenerated files with the
change. Run it with `-Personal` whenever an agent or command was added, since the ordinary run never
touches the two user-level targets. Through the setup entry point: `.\setup.ps1 -InstallTools -Personal`.

## The intent file: `mirror-policy.json`

`mirror-policy.json`, at the repository root, holds what the generator is meant to do as data: each
target above with its path, scope and flag, the size thresholds (the Copilot stub limit, the Codex
skill-list budget), and the empty cells that are deliberate. Both `install.ps1` and the dashboard
collector read it, so an empty cell is judged against intent: a by-design skip is never reported as a
loss, and a lost cell is never softened into by-design. The matrix has eight states: `ok`, `stubbed`,
`trimmed`, `lost`, `by-design`, `orphan`, `stale` and `unknown`. The page that shows it is in
[chapter 12](12-rt-observe-dashboard.md).

## Session adapters

Separate from the mirrors, the dashboard reads live sessions through adapters declared in
`.claude/skills/rt-observe/harnesses.json`: `claude_code` (the JSONL transcripts, plus the hooks
inventory), `copilot_chat` (a read-only copy of the VS Code extension's session store) and `aider`
(the run records the nightly driver writes). Adding a harness is one module plus one line in that
file, with no change to the core. A harness with no adapter simply shows no session lane.

## Rule for a new harness

A mirror is added in `mirror-policy.json` and in `install.ps1` together, with a test, following
`docs/authoring-and-mirrors.md`. The routing table in `.claude/CLAUDE.md`, `README.md` and
`Architecture.md` stay the discovery path for every harness that has no native skill convention.

---
[← 08 Rules and conventions](08-rules.md) | [Table of contents](../../README.md) | [10 Local coding and the cloud →](10-local-coding.md)
