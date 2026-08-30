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
  The working pattern: a `model: haiku` cloud **wrapper** that drives a local model through
  `.claude/skills/loop-engineer/scripts/ollama_bridge.py`. Cloud stays on subscription auth;
  only the small wrapper spends cloud tokens; the bulk generation is local and free.
- The bridge speaks Ollama's HTTP API (`POST /api/generate`), NOT `ollama run`. Measured
  2026-08-14 on Ollama 0.32.9: the CLI cannot fix a seed (the same requested seed gave
  different text), and it writes 68 to 71 ANSI cursor-control sequences into stdout, which a
  naive strip corrupts because the model writes, moves the cursor back and rewrites. The API
  fixes the seed byte-for-byte and carries zero escapes.
- **The vault lookup lives in the bridge, and is not optional.** `--vault-context <terms>`
  makes it search `30_Ressources` and prepend the matching notes; omitting it AND
  `--no-vault-context` is exit 2. The rule used to live only in the agent definition and was
  skipped by the first caller in a hurry: with no context the local model answered a
  documented LaTeX question with the non-existent command `\endminitoc`, passing every other
  gate, because the other gates are structural and none looks at truth.
- No model tag appears in an agent or a script. `model_resolver.py` is the only thing that
  names one, `.claude/local-model-state.json` is the only file recording it, and there is no
  fallback: an unqualified or uninstalled model is an explicit stop, never a quieter
  substitute. The retired `qwen2.5-coder:7b` fallback is exactly what this removes.
- The measured window is `num_ctx` 16384 (2026-08-14, RTX A1000 6 GB, `q8_0` KV cache, 100
  percent GPU, 625 MiB free), recorded in the machine-local `.claude/local-model-config.json`
  and frozen in `~/.litellm/Modelfile.ornith-9b-gpu`. `context_budget.py` reads that file and
  errors rather than assuming a default. Ollama silently truncates a prompt longer than
  `num_ctx` to `num_ctx // 2 + 2` tokens and reports success, which is why the budget gate
  exists at all.
- An optional LiteLLM config (`~/.litellm/ollama.yaml`) proxies only Ollama (keep-alive /
  context tuning); it is not required, and the bridge inherits NOTHING from it.
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

The vault path is authoritative from the `OBSIDIAN_VAULT` environment variable; the documented
default is `C:\Martin Otis\Vault`. The vault (PARA layout `10_Projets` / `20_Domaines` /
`30_Ressources` / `90_Archives`) is the broad, cross-project memory Claude Code lacks natively:
its auto-memory is siloed per working directory (`~/.claude/projects/<slug>/memory/`), so no
single Claude memory spans grants, students, papers, and software. The vault fills that role. The
`loop-engineer` and `authoring-loop` flows read and write it so a lesson learned in one iteration
(or project) is not re-learned later.

**Roles (single serialized writer, read-many).**

- `local-writer` is the only agent that writes to the vault: it drafts the note body locally and
  deposits it in `~/.claude/obsidian-outbox/` with a first-line directive
  (`<!-- obsidian: create|append path="..." -->`); the `obsidian-outbox-flush.py` hook writes it
  into the vault through the filesystem and verifies the effect by comparing the target file's
  size before and after. The outbox is the only write path for CREATING or APPENDING note
  CONTENT, not a fallback used only when Obsidian happens to be closed - see the rationale under
  Transport below. The one sanctioned exception is `vault_consolidate.py --apply --yes` (see
  Consolidation below): an in-place MAINTENANCE edit of links in notes that already exist,
  performed by this same single serialized writer, through the filesystem, verified by re-reading
  the file, never through the Obsidian CLI. Writes stay serialized - never two agents at once, and
  never an external concurrent tool (Claudian, a second IDE agent) on the same vault. That is what
  the root `CLAUDE.md` "single writer" rule protects.
- `local-coder` reads only; if it finds a code learning it hands the text to `local-writer`.
- Plan-time cloud reads (superpowers `brainstorming` on Fable 5, `writing-plans` on Opus) are
  orchestrator-mediated: the planner reads the vault and bakes the learnings into the plan.
  `executing-plans` and the Sonnet review panel do not read.

**Consolidation: a deterministic script, a judgment agent.** After every write, `local-writer` runs
`.claude/skills/obsidian-cli/scripts/vault_consolidate.py`, which measures two distinct graph
defects and decides neither:

| Defect | Deterministic half measures | Judgment half decides |
| --- | --- | --- |
| Missing edge (`--mode candidates`, the default) | shared tags, shared `domaine`, Jaccard overlap on rare terms between unlinked notes | whether the pair shares a real mechanism; add a reciprocal edge with one sentence, or reject |
| Dead edge (`--mode links`) | every wiki-link that resolves to no note, with up to three suggested targets scored `basename` / `alias` / `fuzzy` | which suggestion, if any, is the real target; author the fix as a literal bracketed map |

`--mode links` is read-only, so `local-coder` and the orchestrator may run it like any other vault
read; only `local-writer` may run the rewrite. That rewrite (`--apply <map.json>`) is dry-run by
default - it reports the intended change and writes nothing until `--yes` is also passed - and it
refuses any path that resolves outside the vault rather than writing through it, the same discipline
the outbox hook applies below.

**Where things go (PARA).**

- Project-chronological logs -> `10_Projets/<nature>/<projet>/` (the four natures: `Articles`,
  `Subventions`, `Livres`, `Logiciels`): `Decisions.md` (ADR), `CodeReview.md` (findings),
  `Revisions.md` (article/content corrections). Append.
- Reusable cross-project knowledge -> `30_Ressources/<Technology>/` (current folders: `LaTEX`,
  `Python`, `PowerShell`, `Obsidian`, `ResearchTools`, `Publication`): one atomic note per
  learning, with frontmatter (`type`, `projet: "[[...]]"`, `domaine`, `date`, `tags`) and a
  back-link. The folder axis is the technology, not the nature of the learning: the nature
  already lives in the `type:` property, so a folder per nature would duplicate that property
  and foreclose this second axis. Retrieve all of a project's notes in one call with
  `obsidian search query="[[<projet>]]"`.
- There is no note keyed by a single day. The date lives as a `date:` frontmatter property on
  the note itself and, inside a project log, as a `## YYYY-MM-DD` section heading. The
  cross-project view is `10_Projets/Tableau de bord.base`, which indexes whole files only, never
  titles or internal lines, so it cannot rebuild an entry-by-entry chronology across projects;
  finding everything logged on one date means searching across every `Decisions.md`.

**Triggers.** Error root-cause, loop iteration checkpoint, review finding (code-review /
tech-debt / ai-firstify), gate reached, article/content correction, new method type.

**Transport and reliability.**

- Bare `obsidian` under Git Bash resolves to the GUI `Obsidian.exe` and hangs. Use a
  `~/bin/obsidian` wrapper that execs `Obsidian.com`, with `export PATH="$HOME/bin:$PATH"`.
  Requires Obsidian open + CLI enabled (`Settings > General > Advanced > Command line
  interface = ON`).
- Every note deposited by `local-writer` goes to `~/.claude/obsidian-outbox/<slug>.md` (first
  line `<!-- obsidian: create|append path="..." -->`, the rest is the content), unconditionally,
  regardless of whether Obsidian happens to be reachable. The `obsidian-outbox-flush.py` hook
  (SessionStart + SessionEnd, wired in `.claude/settings.template.json`, script under
  `.claude/hooks/`) writes the target file directly on the filesystem and confirms the write by
  comparing the file's size before and after, never by trusting a return code.
- For the capture-to-read loop to close within one session, Obsidian must be open during the run
  so its file watcher can pick up the change. Otherwise the note waits in the outbox until the
  next flush; `local-coder` also scans the outbox (`cat ~/.claude/obsidian-outbox/*.md`) to pick
  up not-yet-flushed learnings intra-session.

**Why the filesystem writes the note, not the CLI.**

Three measured defects retired the CLI write path (`create`, `append`, `prepend`):

- Past a threshold, the CLI hands its command to Obsidian's main process as JSON over a socket,
  and the header arrives truncated: `JSON.parse` throws inside the main process, an unhandled
  "A JavaScript error occurred in the main process" dialog pops up, and the write never happens.
  The threshold sits on the whole JSON header (note content plus path plus `tty`/`cwd` metadata),
  not on the content alone: a 3850-byte header is accepted, a 4343-byte header is refused, and
  4096 bytes, a Windows named-pipe buffer, falls in between. Measured on Obsidian 1.13.4 (crash
  site `main.js:80:136`) and reproduced on 1.13.7 with the same failure shape at a different
  location (`main.js:64:136`) - a contributor on a newer Obsidian should not assume this was
  fixed upstream. The full trace is in the hook's module docstring, not repeated here.
- The CLI still exits 0 when the write above fails, so a script that only checks the return code
  archives notes that were never written.
- `create` onto an existing file does not fail and does not append - it silently writes a
  numbered duplicate (`Decisions 1.md`), which is how the vault accumulated exact duplicate
  notes.

Two candidate causes were ruled out by measurement, not assumed away: the server code inside the
`.asar` does reassemble the socket's chunks and does frame the JSON on a newline, so the defect
is not there, and a UTF-8 sequence split across a chunk boundary was ruled out because the
failing note's only non-ASCII bytes sit far from the boundary. What remains, unproven, is a
client that exits without waiting for the socket's `drain` event and so loses the tail of the
message; verifying that would mean reproducing the crash, and the threshold alone is enough to
decide. Consequently `obsidian create`, `append`, and `prepend` are forbidden for writing
(decision D3), ranked with `eval`, `dev:*`, `plugin:install`, `theme:install`, and `sync*` (except
the read-only `sync:history`). The filesystem write has been checked in practice on notes of
5443 and 7266 bytes, with no truncation.

**CLI traps that remain (also measured on 2026-08-03; the read-only surface is still in use).**

- `create --help` does not print help - it creates a file named `Untitled.md`. Use
  `obsidian help <command>` for documentation instead, and note that CLI parameters take no
  dashes (`path=`, `to=`, `content=`).
- `obsidian move` into a folder that does not exist exits 0 but fails with `ENOENT` without
  creating the missing folder. Create the destination folder first.

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

**Drift check.** The five corrections above (this file, the ResearchTools `.claude/CLAUDE.md`,
`local-writer.md`, `local-coder.md`, and `CLAUDE.template.md`) are prose: nothing compiles them, so
nothing notices them drifting apart again. `scripts/audit/check-claude-template.ps1` is that
control. It regenerates `CLAUDE.template.md` with today's substitutions into a file under
`$env:TEMP` (never by calling `setup.ps1`, and never by writing to the live global file), diffs
the result against this machine's own `~/.claude/CLAUDE.md`, and asserts four invariants: no
`daily:append` in the template, no removed `30_Ressources` folder (`Apprentissages/`, `Methodes/`,
`GardeFous/`) used as a live location in a definition file (`.claude/agents`, `.claude/commands`,
`.claude/skills`, plus the two per-agent mirror trees `.github/agents/*.agent.md` and
`.opencode/agent/*.md`; `.continue/rules/researchtools.md` is a single combined rules file, not a
per-agent mirror, and carries none of these three folder names today, so it is left out), the
shipped hook verifies a write through `st_size` rather than a return code, and the shipped hook
never calls the Obsidian CLI binary. A line naming a removed folder is exempt only when its
trimmed content is byte-identical to one of two hardcoded, exact-quoted lines from
`local-writer.md`'s own historical sentence about the 2026-08-03 rename - fix round 1 replaced an
earlier "sanctioning phrase somewhere in a nearby window" check after a scratch fixture showed it
could be defeated by pasting unrelated boilerplate containing the same words next to a genuine
live-location instruction. Template and live also diverge on three content lines by design right now (Task 5
advanced the template with a fix the live file cannot receive without running `setup.ps1` by
hand): the script names each of the three, by literal content, as a pending propagation with that
remedy, and fails on any other, unclassified difference. What it does not cover: it compares the
template against ONE machine's global file, so a second contributor's own drifted copy is
invisible to it; a clean exit here is not a claim that every contributor's `~/.claude/CLAUDE.md`
is in sync.

### The vault event daemon (unattended filing)

Everything above describes the ATTENDED path: a session runs, `local-writer` judges, the note
is filed. The daemon is the unattended one, added 2026-08-28 on branch
`feat/vault-event-daemon`. Its point is that the cloud wrapper should not be the thing that
decides where a learning goes. Haiku pushes a raw drop; the LOCAL model classifies it, drafts
it, and the vault organises itself, at no cloud generation cost.

**The event contract.** A raw drop is unrouted text in `~/.claude/obsidian-outbox/raw/`, with
three frontmatter keys (`source`, `subject`, optional `project`) and no directive line, because
deciding the destination IS the daemon's job. Pre-routed notes carrying a directive keep
working exactly as before; only the unrouted form is new.

**The path.** `CLASSIFY` and `DRAFT` call the local model. `ROUTE`, `WRITE` and `ENQUEUE` are
Python. Two model calls, roughly 1.2 minutes. Whatever `ROUTE` refuses lands in
`needs-review/` with the reason on its first line, and a session picks it up by dispatching
`local-writer`, which classifies with the whole reusable layer in context. The daemon never
retries a parked event: re-running a judgment the model already failed produces the same
answer more slowly.

**The filesystem is the queue**, so `obsidian-cli` still ships no `requirements.txt` and adds
no `pip-audit` surface: `raw/` inbound, `working/` claimed, `raw/sent/` delivered,
`needs-review/` parked, `state/` in flight, `queue/*` deferred. Three distinct mechanisms hold
it together, and confusing them is the mistake to avoid. The WRITE lock serializes writers so
a file is never corrupted. The SINGLETON lock admits one daemon per machine: without it two
daemons classify and draft every drop twice, paying two model calls for one result, which
serializing the writes does not prevent. The CLAIM is a rename out of `raw/`, atomic, so the
winner owns the drop and the loser gets `FileNotFoundError`. Producers are unlimited and
parallel; the consumer is one, deliberately, because the card holds one resident model and two
consumers would only thrash VRAM.

**Two signals designed to mean something.** A `state/` file exists only while an event is in
flight, so one that survives IS the crash signal, and the startup sweep names them: that is the
list of notes to check against the journal. A deferred queue is cleared only on the branch that
actually did the work, so a skipped drain never silently discards what it did not process.

**Deferred drains.** Consolidation and graphify are off the event path on purpose: at the
measured 36.991 s median call, judging fifteen candidate pairs inline would pin the GPU for
about ten minutes per drop. The drain asks `vault_consolidate.py` for the candidates, judges
one pair per model call on the strict mechanism test, and appends accepted edges reciprocally
with the sentence saying what they share. Phantom-link repair is deliberately NOT here: adding
an edge appends a sentence and is reversible from the journal, while rewriting `[[Old]]` to
`[[New]]` substitutes text across many notes at once, is not reversible from an append-only
record, and rests on a truth judgment the writer-role evidence does not support.

**What the gates cannot do.** They are structural, and none of them looks at whether an answer
is true - the 2026-08-14 `\endminitoc` incident is the standing reminder. The confidence
threshold (`daemon.classify_confidence_min`, 0.7 to start) is a dial, not a measurement: a
model's self-reported confidence is not a probability, so the daemon logs its own accept and
park counts per event and the value is meant to be revised from that log. The journal makes a
wrong filing recoverable and the report makes it visible; neither makes it correct.

**Measured before it was built** (`.claude/local-capability-probe.json`, 2026-08-28, Ollama
0.33.0): a JSON schema sent in the request's `format` field is honoured, enum included, so the
two judgment calls are constrained at the sampler rather than validated hopefully. And a shared
prompt prefix is re-used - but the verdict cannot be taken on token count, since the daemon
bills the full `prompt_eval_count` either way (2186 on both calls); prefill duration is the
only exposed signal, and it needs a CONTROL call on a prefix never seen to separate it from
machine load. Measured ratio 0.23, 635 ms against 2741 ms.

## 6. Keeping this file alive

When you (or an assistant) learn a durable, non-obvious project fact - a convention, an
environment constraint, a gotcha - record it **here**, in the repo, not only in a personal
Claude Code memory. Personal memories still help within a single contributor's sessions, but
this file is what the whole team and every assistant (Copilot, OpenCode, Continue, Aider)
can read. Prefer genericized paths (`~/...`) over machine-specific absolute paths.

Martin Otis
