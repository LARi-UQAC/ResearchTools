# Authoring and mirroring: agents, skills, commands

This is the single, turnkey reference for adding or editing an **agent**, **skill**,
or **command** in ResearchTools and propagating it to every assistant (Claude Code,
GitHub Copilot, OpenCode, Continue, Aider) plus any tool that reads the `AGENTS.md`
convention (OpenHuman, Hermes Agent, Codex, and others). Follow the matching section;
you should not need to re-investigate the mirror machinery.

Related: [README.md](../README.md) and [Architecture.md](../Architecture.md) are the
authoritative inventories; [.claude/CLAUDE.md](../.claude/CLAUDE.md) holds the routing
table; [.claude/rules/workflows.md](../.claude/rules/workflows.md) lists task flows.

## 1. The model: one source, generated mirrors

`.claude/` is the **single source of truth**. Every other tool reads either the repo
directly or a file **generated** from `.claude/`. Never hand-edit a generated mirror; edit
the canonical source and regenerate.

| Canonical source (`.claude/`) | Shape | Count today |
|---|---|---|
| `agents/<name>.md` | flat file, YAML frontmatter (`name:`, `description:`) | 15 |
| `skills/<name>/SKILL.md` | folder with `SKILL.md` (+ optional `scripts/`, `references/`) | 10 |
| `commands/<name>.md` | thin wrapper, ends with `$ARGUMENTS` | 19 |
| `rules/<name>.md` | plain markdown | 5 |
| `CLAUDE.md` | mission, the "Tooling" **routing table**, the `active_profile` selector | 1 |

The first row (bold) and first column of any table you add follow the repo table rules in
[.claude/CLAUDE.md](../.claude/CLAUDE.md).

## 2. The mirror map (what each tool consumes)

`install.ps1` regenerates all of these idempotently from the canonical sources:

| Tool | Consumes | Generated from | Notes |
|---|---|---|---|
| Claude Code | `.claude/` directly | - | canonical; nothing to generate |
| GitHub Copilot | `.github/agents/<name>.agent.md` | each agent | full body inlined; a **stub** pointing at `.claude/agents/<name>.md` when the body exceeds ~28k chars (Copilot's 30k prompt cap) |
| GitHub Copilot | `.github/prompts/<name>.prompt.md` | each command | **except** the session-mode commands `concis`, `slim`, `focus`, `ctx` (no Copilot meaning); `$ARGUMENTS` is rewritten to a chat phrase |
| GitHub Copilot | `.github/instructions/<name>.instructions.md` | each rule | wrapped with `applyTo: "**"` |
| GitHub Copilot | `.github/copilot-instructions.md` | agents + skills pointer | master file: mission, agent routing, skills pointer |
| OpenCode | `.opencode/agent/<name>.md` | each agent | full body, no size limit |
| Continue | `.continue/rules/researchtools.md` | agent list | one rule file that points at the `.claude/CLAUDE.md` routing table |
| Aider | `CONVENTIONS.md` | static pointer | generated **only if absent**; never overwritten (see section 4) |
| AGENTS.md readers | `AGENTS.md` | agent list | static master, regenerated on every run; serves any harness reading the `AGENTS.md` convention |
| Codex | `.agents/skills/<name>/SKILL.md` | each skill | **pointer** mirror: frontmatter only, description trimmed to whole sentences to fit Codex's skill-list budget, body points at the canonical skill |
| Codex | `.claude/skills/AGENTS.md` | static | nested `AGENTS.md`, appended to the root one when the working directory is inside the skills tree |

### Why `AGENTS.md` covers more than one harness

Two actively maintained agent harnesses converge on the same file, which is why
`AGENTS.md` is one new mirror target, not several. **OpenHuman**
(`tinyhumansai/openhuman`, GPL-3.0) loads a project-level `AGENTS.md`:
`src/openhuman/agent/prompts/agents_md.rs` line 26 sets
`pub const AGENTS_MD_FILENAME: &str = "AGENTS.md";`, and `load_agents_md` (line 69)
reads `dir.join(AGENTS_MD_FILENAME)`. **Hermes Agent** (`nousresearch/hermes-agent`,
MIT) reads, per directory from the git root down to the working directory, the first
of `AGENTS.override.md`, `AGENTS.md`, or `agents.md` (`agent/prompt_builder.py` line
2281). Codex and any other tool that follows the same `AGENTS.md` convention are
covered by the same file at no extra cost. Neither harness supports per-agent
definition files, so `AGENTS.md` is a distilled master, the same class as
`.continue/rules/researchtools.md` and `CONVENTIONS.md`, not a per-agent mirror.

`AGENTS.md` at the repo root is a **shared namespace**: any tool that reads it now
receives this content, which is the point, but it is also a fact a contributor must
know before editing it - a change here reaches every harness that follows the
convention, not just one.

Hermes Agent additionally reads `CLAUDE.md` from the current working directory
(`agent/prompt_builder.py` line 2323). This repo has none at its root, so
`AGENTS.md` is the operative file for Hermes here, not an optional parity extra.

**One file under `.github/instructions/` is NOT generated.**
`.github/instructions/mermaid.instructions.md` is hand-maintained and has no source rule.
It documents the Mermaid Chart VS Code extension (its LM tools, its command IDs, its
`@mermaid-chart` slash commands), which is Copilot-and-VS-Code-specific: promoting it to
`.claude/rules/mermaid.md` would push those command IDs into the OpenCode, Continue and
Aider mirrors, where nothing can act on them. `install.ps1` writes one instructions file
per rule and never deletes an extra one, so the file survives every regeneration untouched
and must be edited in place. It carries a header saying so; do not "restore" it by running
the installer, and do not read its presence as drift.

**Skills have no per-tool mirror, except for Codex.** They are plain repo folders every
tool can read. A skill becomes discoverable in Copilot/OpenCode/Continue **only** through
(a) an agent that calls it, or (b) the routing table in `.claude/CLAUDE.md`. A user-invoked
skill with no calling agent (e.g. `geolocalisation`) is invisible to those tools unless it
is in the routing table (and, ideally, has a command wrapper -> Copilot prompt).

Codex is the exception, because it is the one harness with a **native skill convention**:
it scans `.agents/skills` in every directory from the working directory up to the
repository root, reads each `SKILL.md` (that exact casing) for `name:` and `description:`,
and offers the skill by name. So `install.ps1` generates `.agents/skills/<name>/SKILL.md`
for all 15 skills, and a user-invoked skill needs neither an agent nor the routing table to
be reachable there.

Three properties of that mirror are deliberate:

- **It is a pointer, never a copy.** Only the frontmatter is reproduced; the body says to
  read `.claude/skills/<name>/SKILL.md` first. Duplicating skill bodies would create the
  second truth the whole generated-mirror model exists to prevent.
- **Descriptions are trimmed to whole sentences.** Codex caps the skill list at 2% of the
  model's context window, or 8000 characters when the window is unknown, then shortens
  descriptions and finally omits skills with a warning. Measured 2026-08-28, the untrimmed
  list for this repo is 9417 characters, already over. The trim keeps the first sentence
  unconditionally because it carries the trigger, and `test_codex_mirror.py` proves the
  result fits. The choice is only whether the shortening is ours or Codex's.
- **The description is emitted as a single-quoted YAML scalar.** Eleven of the canonical
  descriptions are double-quoted at the source, and the first generated set carried those
  quotes through and then trimmed mid-scalar, shipping eleven mirrors whose frontmatter did
  not parse while the installer printed a green `[OK]` for each. One skill also opens its
  description with a `>` block indicator, which is syntax and not text. Both are parsed out
  now, and both have a test.

`AGENTS.md` nesting is the same story from the other side: Codex concatenates one file per
directory from the git root down to the working directory, later files overriding earlier
ones, and stops once the combined size reaches `project_doc_max_bytes` (32 KiB default).
`.claude/skills/AGENTS.md` therefore reaches a session whose cwd is inside the skills tree,
carrying the script-surface rule that is easiest to break from exactly there. Note that
Codex checks `AGENTS.override.md` **before** `AGENTS.md` in each directory - the same
precedence Hermes Agent uses - so a hand-written override silently replaces the generated
file for both harnesses.

## 3. The two install scripts (different jobs)

| Script | Job | When to run |
|---|---|---|
| `install.ps1` | **Generate the mirrors** (section 2) and record the active profile in `.claude/CLAUDE.md` | After adding/editing any agent, command, or rule. Then commit the regenerated mirrors. |
| `install-junctions.ps1` | Link `~/.claude` <-> this repo so Claude Code loads these agents/skills/rules/commands in **any** workspace | Once per machine; re-run after a `git pull` that rewrote agent files (hardlink fallback detaches) |

```powershell
.\install.ps1 -Profile engineering      # regenerate all mirrors, keep engineering profile
.\install.ps1 -Personal                 # also copy Copilot agents to ~/.copilot/agents + VS Code user prompts
.\install-junctions.ps1                  # (separate) global Claude Code loading; -WhatIf to preview
```

`install.ps1` is idempotent and safe to run repeatedly. Copilot needs no install step
beyond committing the files: `.github/agents/*.agent.md` on the default branch are
auto-discovered.

## 4. What `CONVENTIONS.md` is (and is not)

`CONVENTIONS.md` at the repo root is the **Aider** conventions pointer. `install.ps1`
writes it **only if it does not already exist**, so once present it is effectively static
and hand-maintainable. Its sole job is to tell Aider (and any generic tool) that agent
definitions live in `.claude/agents/` and to follow the routing table in
`.claude/CLAUDE.md`.

It is **not** a start/stop registry for skills, commands, or agents, and editing it does
not register anything. Registration happens in the routing table (`.claude/CLAUDE.md`) and
the generated mirrors.

## 5. Choose the right kind

- **Agent** - an autonomous, multi-step pipeline with a contractual process and an exit
  checklist (e.g. an auditor, a researcher). Mirrored to Copilot + OpenCode + Continue.
- **Skill** - a reusable capability, usually script-backed, invoked by agents or the user
  (e.g. `scopus`, `extract-statistic`). No mirror; lives as a repo folder.
- **Command** - a thin `/slash` wrapper that points at an agent or a skill workflow.
  Mirrored to a Copilot prompt.

A skill and its command wrapper commonly coexist (`/geolocalisation` -> the
`geolocalisation` skill). A command may instead drive an agent (`/bibclean` -> the
`bib-cleaner` agent).

## 6. Add a new AGENT

1. Create `.claude/agents/<name>.md` (flat file). Minimum frontmatter is `name` and
   `description` (only these two are read by `install.ps1`; a `tools:` line is optional):

   ```markdown
   ---
   name: <name>
   description: "Use when <trigger>. Produces <deliverable>."
   ---

   ## Pipeline integrity - NON-NEGOTIABLE
   <state the contractual pipeline: the ordered steps, the mandatory skill
   invocations, the manual-checkpoint rule, and the final ✓/✗ exit checklist -
   see "Agent pipeline integrity" in .claude/CLAUDE.md and model on
   .claude/agents/bib-cleaner.md>
   ```

2. Update the inventories and routing:
   - `.claude/CLAUDE.md` "Tooling" table: add a routing row (canonical registration).
   - [README.md](../README.md): bump the agent count where stated; add the agents-table row.
   - [Architecture.md](../Architecture.md): add the agent node/edge in the mermaid graph and
     any inventory count.
   - [.claude/rules/workflows.md](../.claude/rules/workflows.md): add a flow row if it maps a
     user goal to this agent.
3. Regenerate + commit (section 9). `install.ps1` emits the Copilot, OpenCode, and Continue
   mirrors automatically.

Agent bodies over ~28k chars become a Copilot **stub** that points back at the canonical
file - keep hard constraints early in the body so the stub carries them. A stub does not
carry the rest of the body, so a cross-cutting rule added to agent bodies (not just this
one) must ALSO be distilled into the three master files (`.github/copilot-instructions.md`,
`.continue/rules/researchtools.md`, `CONVENTIONS.md`), the way the Obsidian outbox and
`ollama_bridge.py` rules already are.

## 7. Add a new SKILL

1. Create `.claude/skills/<name>/SKILL.md`. Frontmatter carries `name`, a trigger-rich
   `description`, and (optionally) `allowed-tools` / `permissions`:

   ```markdown
   ---
   name: <name>
   description: "<what it does>. Use when <triggers, including slash and natural-language phrases>."
   allowed-tools: [Read, Write, Edit, Bash]
   ---

   # <name> - <one-line purpose>
   <the workflow: numbered steps; scripts under scripts/; prerequisites; outputs>
   ```

   Put runnable code in `.claude/skills/<name>/scripts/` and offline tests in
   `.../scripts/Test/`. Pin dependencies in the skill's `requirements.txt`, run
   `pip-audit`, and add a security-floor comment for any transitive CVE.

   A script produced while operating on an EXTERNAL project — a manuscript, thesis, or
   grant tree outside this repo — is authored in ResearchTools, under the owning skill's
   `scripts/` directory, and is called from there by path; it is never left behind in
   that project's own directory.
2. **Register it (critical - a skill has no mirror outside Codex):**
   - `.claude/CLAUDE.md` "Tooling" table: add a routing row. This is the ONLY thing that
     makes a user-invoked skill discoverable in Copilot/OpenCode/Continue. Codex gets a
     generated `.agents/skills/<name>/SKILL.md` pointer instead, so keep the canonical
     `description` trigger-rich AND reasonably short: it is the whole trigger surface there,
     and every skill added tightens the shared list budget the others must fit in.
   - [README.md](../README.md): bump the skill count in the three places it appears
     (header "N skills", the "N ship" sentence, the File-Locations "(N skills)"); add the
     skills-table row, a `### <name>` subsection, a Prerequisites row for new deps, and the
     File-Locations tree entry (fix the `└──`/`├──` on the previous last skill).
   - [Architecture.md](../Architecture.md): update the skill inventory/count.
   - `install.ps1` skills-pointer sentence in `.github/copilot-instructions.md` names a few
     helper skills; add yours there only if it should be called out (edit the generator's
     master text, not the mirror).
3. Add a command wrapper if the skill is user-invokable (section 8) - this makes `/<name>`
   first-class and emits a Copilot prompt. Optional: a skill may advertise `/<name>` and let
   the Skill tool handle the trigger with no command file (precedent: `drawio2tikz`).
4. Regenerate + commit (section 9).

## 8. Add a new COMMAND

1. Create `.claude/commands/<name>.md`. Frontmatter is optional (Claude Code allows a
   frontmatter-less command whose H1 becomes the description). Model on
   `.claude/commands/word2latex.md`: a short procedure that points at the agent/skill,
   ending with the argument placeholder and the language line:

   ```markdown
   # <Title -> becomes the description>

   <short procedure; reference the agent or skill workflow to run>

   $ARGUMENTS
   ```

   End user-facing command bodies with: "Respond in French unless the active file is in
   English." `install.ps1` rewrites `$ARGUMENTS` for the Copilot prompt automatically.
2. Update the inventories:
   - [README.md](../README.md): bump the command count (header "N commands", File-Locations
     "(N commands)"), add the Commands-table row and the File-Locations commands-tree entry
     (fix the `└──` on the previous last command).
   - [Architecture.md](../Architecture.md): add the command node + edge (command -> agent, or
     command -> skill directly when the skill has no agent).
   - [.claude/rules/workflows.md](../.claude/rules/workflows.md): add the flow row.
3. Regenerate + commit (section 9). A Copilot prompt `.github/prompts/<name>.prompt.md` is
   emitted (unless `<name>` is a session-mode command: `concis`, `slim`, `focus`, `ctx`).

## 9. Regenerate, verify, commit

```powershell
.\install.ps1 -Profile engineering
```

Then verify the new entity is wired everywhere, and commit **the canonical change and the
regenerated mirrors together**:

```bash
rtk grep -n "<name>" .claude/CLAUDE.md README.md Architecture.md \
  .github/copilot-instructions.md .github/prompts/ .github/agents/ \
  .opencode/agent/ .continue/rules/researchtools.md
rtk git add .claude .github .opencode .continue CONVENTIONS.md README.md Architecture.md
rtk git commit -m "feat: add <name> <agent|skill|command> and regenerate mirrors"
```

Editing a **rule** (`.claude/rules/<name>.md`) also requires a regenerate, since its Copilot
mirror `.github/instructions/<name>.instructions.md` is generated from it. A change to a
skill's scripts or to `README.md`/`Architecture.md` alone needs no regenerate (skills and
those docs are not mirrored).

## 10. Quick checklist by type

| Step | Agent | Skill | Command |
|---|---|---|---|
| Create canonical file | `agents/<name>.md` | `skills/<name>/SKILL.md` (+`scripts/`) | `commands/<name>.md` |
| `.claude/CLAUDE.md` routing row | yes | **yes (only discoverability path)** | via its agent/skill |
| README count + table + tree | agent count | skill count (3 spots) + subsection | command count |
| Architecture.md graph/inventory | node/edge | inventory count | node/edge |
| workflows.md flow row | if user-facing | if user-facing | yes |
| Dependencies + `pip-audit` | if scripted | if scripted | n/a |
| Run `install.ps1` + commit mirrors | yes | yes (for routing/master) | yes (emits prompt) |

## 11. See also

- [contributor-notes.md](contributor-notes.md) - shared project conventions and environment
  facts (English-only definition files, agent/skill layout, local-model routing, git/GitHub
  workflow), distilled from per-contributor Claude Code memories into version control.

- The project memory `adding-a-skill-checklist` records the skill + command mirror flow;
  this document supersedes and generalizes it to agents as well. Keep both pointing at the
  same routing table. It lives in the Claude Code project memory directory
  (`~/.claude/projects/<project-slug>/memory/`, where `<project-slug>` is the working
  directory with path separators replaced by `-`); on this machine that is
  `C:\Users\m3otis\.claude\projects\c--Martin-Otis-OutilsLogiciels-ResearchTools\memory\adding-a-skill-checklist.md`
  (indexed in that directory's `MEMORY.md`).
- `install.ps1` header comment is the authoritative description of each generated file.

Martin Otis