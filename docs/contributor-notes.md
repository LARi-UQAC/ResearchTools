# Contributor notes (shared project knowledge)

Durable, non-obvious conventions for working on ResearchTools. These were previously held
only in individual Claude Code **personal** memories (`~/.claude/projects/<slug>/memory/`),
which are machine-local and invisible to other contributors. This file is the
**version-controlled, shared** home for that knowledge: read it before contributing, and add
to it when you learn a durable project fact.

For the mechanics of creating/editing an agent, skill, or command and regenerating the
per-tool mirrors, see [authoring-and-mirrors.md](authoring-and-mirrors.md); this file covers
the conventions and environment facts around that process.

## 1. Definition files are English-only

Every file under `.claude/agents/`, `.claude/skills/`, and `.claude/commands/` (and across
the whole `OutilsLogiciels` workspace) is written in **English only**. A single file never
mixes languages.

- Applies to guardrails, sections, checklists, and sentinel strings you add - write them in
  English even when the request arrives in French. Shared sentinels stay English:
  `PIPELINE-PAUSED @ <step>`, `PIPELINE INCOMPLETE - DO NOT USE`.
- French is allowed only in (a) deliverable output strings an agent emits (e.g. a LaTeX
  title `\subsection*{Carte des lacunes}`) and (b) files that are already French (the
  repo-root `CLAUDE.md`, generated from `CLAUDE.template.md`).

## 2. Agents are files, skills are folders (no symmetry)

- Agents: flat `.claude/agents/<name>.md`, line 1 `---`, frontmatter keys `name:` +
  `description:` (quoted). Claude Code subagent discovery scans **only flat `*.md`** here; a
  folder or a frontmatter-less file is undiscoverable. Copilot/OpenCode use the same
  flat+frontmatter convention.
- Skills: folder-based `.claude/skills/<name>/SKILL.md` (+ `scripts/`, `references/`).
- Never reintroduce the old `<name>/AGENT.md` folder layout for agents (it silently breaks
  discovery). Some parent-repo dev agents outside ResearchTools may still carry that broken
  layout - migrate them to the flat layout when asked.
- After editing an agent, run `install.ps1` to regenerate the mirrors and, for global Claude
  Code loading, `install-junctions.ps1` (see [authoring-and-mirrors.md](authoring-and-mirrors.md)).
  On Windows without Developer Mode, `install-junctions.ps1` falls back to **hardlinks** that
  detach when `git pull` rewrites a file - re-run it after such a pull, or enable Developer
  Mode for true symlinks.

## 3. Local-model routing (`local-writer` / `local-coder`)

These agents push token-heavy generation to a local Ollama model to save cloud tokens.

- The intended auth is **claude.ai subscription** (no pay-as-you-go `ANTHROPIC_API_KEY`).
  Do **not** set a whole-session `ANTHROPIC_BASE_URL` pointing at a local gateway - it
  disables the cloud models (a gateway without an Anthropic key cannot serve them).
- Per-subagent `model: ollama/...` frontmatter is not natively supported by Claude Code.
  The working pattern: a `model: haiku` cloud **wrapper** that shells `ollama run <model>`
  over the Bash bridge. Cloud stays on subscription auth; only the small wrapper spends
  cloud tokens; the bulk generation is local and free.
- An optional LiteLLM config (`~/.litellm/ollama.yaml`) proxies only Ollama (keep-alive /
  context tuning); it is not required.
- Target local models: writer `ornith:9b`, coder `qwen3.5:9b` (manual GGUF imports). Until
  both are imported, the bridge falls back to `qwen2.5-coder:7b`.
- The `loop-engineer` skill (`/loopdev`) builds on these agents; its Agent SDK loop also
  runs on subscription auth, with local steps through the same bridge.

## 4. Git and GitHub workflow

- Remote: `LARi-UQAC/ResearchTools`. Contributors fork, branch, and open a PR against
  `main`; the maintainer reviews and merges. A maintainer `git pull` immediately refreshes
  the junction-linked entries in `~/.claude`.
- Commit hygiene: never commit directly to `main` for feature work - branch first. A commit
  message containing `Closes #N` auto-closes that issue on push. To close a PR **without**
  merging, delete its head branch.
- API write access via a plain `GITHUB_TOKEN` may be restricted (read-only on this repo for
  non-admins); rely on `git push` (credential-manager auth) for write operations rather than
  API calls to comment on or patch issues/PRs.

## 5. Obsidian knowledge-capture loop

The Obsidian vault (`~/...Vault`, PARA layout `10_Projets` / `20_Domaines` / `30_Ressources` /
`90_Archives`) is the broad, cross-project memory Claude Code lacks natively: its auto-memory is
siloed per working directory (`~/.claude/projects/<slug>/memory/`), so no single Claude memory
spans grants, students, papers, and software. The vault fills that role. The `loop-engineer` and
`authoring-loop` flows read and write it so a lesson learned in one iteration (or project) is not
re-learned later.

**Roles (single serialized writer, read-many).**

- `local-writer` is the only agent that writes to the vault: it drafts the note body locally and
  runs `obsidian create` / `append` itself. Writes are serialized - never two agents at once, and
  never an external concurrent tool (Claudian, a second IDE agent) on the same vault. That is what
  the root `CLAUDE.md` "single writer" rule protects.
- `local-coder` reads only; if it finds a code learning it hands the text to `local-writer`.
- Plan-time cloud reads (superpowers `brainstorming` on Fable 5, `writing-plans` on Opus) are
  orchestrator-mediated: the planner reads the vault and bakes the learnings into the plan.
  `executing-plans` and the Sonnet review panel do not read.

**Where things go (PARA).**

- Project-chronological logs -> `10_Projets/<domaine>/<projet>/`: `Decisions.md` (ADR),
  `CodeReview.md` (findings), `Revisions.md` (article/content corrections). Append.
- Reusable cross-project knowledge -> `30_Ressources/<cat>/` (`Apprentissages/`, `Methodes/`,
  `GardeFous/`): one atomic note per learning, with frontmatter (`type`, `projet: "[[...]]"`,
  `domaine`, `date`, `tags`) and a back-link. Retrieve all of a project's notes in one call with
  `obsidian search query="[[<projet>]]"`.
- The daily note gets a pointer only, never the full note.

**Triggers.** Error root-cause, loop iteration checkpoint, review finding (code-review /
tech-debt / ai-firstify), gate reached, article/content correction, new method type.

**Transport and reliability.**

- Bare `obsidian` under Git Bash resolves to the GUI `Obsidian.exe` and hangs. Use a
  `~/bin/obsidian` wrapper that execs `Obsidian.com`, with `export PATH="$HOME/bin:$PATH"`.
  Requires Obsidian open + CLI enabled (`Settings > General > Advanced > Command line
  interface = ON`).
- If Obsidian is unreachable, `local-writer` drops the note into
  `~/.claude/obsidian-outbox/<slug>.md` (first line `<!-- obsidian: create|append path="..." -->`,
  the rest is the content). The `obsidian-outbox-flush.py` hook (SessionStart + SessionEnd, wired
  in `.claude/settings.template.json`, script under `.claude/hooks/`) delivers it later.
- For the capture-to-read loop to close within one session, Obsidian must be open during the run.
  Otherwise the note waits in the outbox until the session boundary; `local-coder` also scans the
  outbox (`cat ~/.claude/obsidian-outbox/*.md`) to pick up not-yet-flushed learnings intra-session.

**Setup (per machine).**

```bash
mkdir -p ~/bin
printf '#!/bin/bash\nexec "/c/Users/<you>/AppData/Local/Programs/Obsidian/Obsidian.com" "$@"\n' > ~/bin/obsidian
chmod +x ~/bin/obsidian
grep -q 'HOME/bin' ~/.bashrc || printf '\nexport PATH="$HOME/bin:$PATH"\n' >> ~/.bashrc
cp .claude/hooks/obsidian-outbox-flush.py ~/.claude/hooks/   # if not junction-linked
```

Keep the `settings.template.json` SessionStart / SessionEnd entries that call the flush hook.

**Plugin decision.** Do not install Claudian / obsidian-claude-code-plugin (they embed a second
agent = a concurrent writer, breaking the single-writer rule) nor the Claude Code IDE / IDE Pro
MCP-over-WebSocket plugins (this integration is deliberately the local CLI, not MCP). Stay
CLI-only.

## 6. Keeping this file alive

When you (or an assistant) learn a durable, non-obvious project fact - a convention, an
environment constraint, a gotcha - record it **here**, in the repo, not only in a personal
Claude Code memory. Personal memories still help within a single contributor's sessions, but
this file is what the whole team and every assistant (Copilot, OpenCode, Continue, Aider)
can read. Prefer genericized paths (`~/...`) over machine-specific absolute paths.

Martin Otis
