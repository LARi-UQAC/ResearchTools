# Installation

Chapter 01 of the ResearchTools manual. Back to [table of contents](../../README.md).

Follow these steps on any machine after cloning the repository.

## Install scripts overview

Three scripts, three different jobs and lifecycles. `setup.ps1` is the single entry point:
it wraps the other two via `-InstallJunctions` / `-InstallTools`, and `-All` runs the full
sequence (config, then junctions, then tools) in one pass.

`setup.ps1 -InstallDaemon` is the fourth job, and it belongs here rather than in the two
installers: it delegates to
`.claude\skills\obsidian-cli\scripts\vault-daemon-autostart.ps1 -Install`, which puts one
shortcut in the Startup folder so the vault event daemon is running at login and raw drops
in `~/.claude/obsidian-outbox/raw` get filed instead of piling up. `-All` includes it only
when a vault is configured, and says so in one line when it skips: a login daemon with no
vault starts, finds nothing and exits invisibly. `install.ps1` runs many times a day and
`install-junctions.ps1 -Sync` runs at every session start, so a Startup write in either
would come back after the user deliberately removed it.

Nothing installs that shortcut on its own, and no tool here should: the Startup folder is the
operator's. **The daemon is therefore started by the operator**, either by running
`setup.ps1 -InstallDaemon` once so it comes up at every login, or by launching
`vault-daemon-autostart.bat` when it is wanted. Until one of those happens, raw drops simply
accumulate in `~/.claude/obsidian-outbox/raw/` and are filed the first time the daemon runs;
they are not lost. `vault-daemon-autostart.ps1 -Status` is read-only and answers the three
questions that matter - whether a daemon holds the lock right now, what the log's tail says,
and whether the login shortcut exists at all.

| | `setup.ps1` | `install-junctions.ps1` | `install.ps1` |
|---|---|---|---|
| Job | Detect this machine's paths (Git Bash, Node, Obsidian) and fill the gaps in the GLOBAL Claude Code configuration from the two templates | Link the repo into `~/.claude` so Claude Code loads agents/skills/rules/commands in every workspace | Generate mirrors for other coders: GitHub Copilot, OpenCode, Continue, Aider, `AGENTS.md` readers (`-Personal` adds the user-level Copilot install) |
| Output | Nothing inside the repository. Additively: `~/.claude/CLAUDE.md` (whole file only when absent), `~/.claude/settings.json` (only the hook entries the template declares and the live file lacks), `OBSIDIAN_VAULT` at USER scope (only when unset), and `.venv-skills/` in the clone with `-InstallPython` | Links in `C:\Users\<you>\.claude\` | Generated files committed in the repo (`.github\`, `.opencode\`, `.continue\`, `CONVENTIONS.md`, `AGENTS.md`) + optional user copies |
| When to run | Once after clone (or when machine paths change) | Once after clone; re-run when an agent or skill is ADDED (or a hardlink detached after a pull) | After every agent/command/rule EDIT, then commit the output |
| Privilege | none | symlinks want Developer Mode (automatic hardlink fallback) | none |
| Interactive | yes (asks vault path, confirms) - `-NonInteractive` refuses with exit 2 instead of assuming a default, and `-Preview` writes nothing at all | no | no |
| Via `setup.ps1` | - | `-InstallJunctions` | `-InstallTools` |
| Other switches | `-InstallDaemon` (vault daemon at login), `-InstallPython` (`.venv-skills` for the offline suite) | - | - |

```powershell
.\setup.ps1 -All -Personal   # new machine: config + Claude links + all tool mirrors
```

## The `CLAUDE*.md` family

Two files, both hand-written, both English, neither carrying a machine path or a person's
name. A file a script generates is never a tracked file, so anything derived from these
lands in `~/.claude/` or in the mirrors, which are regenerated wholesale and reviewed as
output.

| File | What it is | Written by | Where its content lands |
|---|---|---|---|
| `CLAUDE.template.md` | Source of the GLOBAL instructions: session rules, Obsidian vault integration, git-sync, plan-mode workflow, hooks. Carries the `{{OBSIDIAN_VAULT}}` / `{{OBSIDIAN_EXE}}` placeholders and the only copy of the `RT-CONTRACT` block | a human | `~/.claude/CLAUDE.md` — the whole substituted file when that file does not exist, the `RT-CONTRACT` block alone when it does (`install-junctions.ps1 -Sync`, `Update-RtClaudeMd`) |
| `.claude/CLAUDE.md` | The repository's own authority: mission, writing standard, references, figures/tables/equations, the routing table, pipeline integrity, where code belongs | a human | loaded by Claude Code when working inside this repository |

Two files that used to sit beside them are gone: a root `CLAUDE.md`, which was a generated
copy of the template carrying this machine's vault and Obsidian paths, and `CLAUDE (up).md`,
a stale copy of the parent directory's file that nothing read. Only the root `CLAUDE.md` is
gitignored.

`.claude/settings.json` is a different case and **is committed**. It is the shared project
scope, and it has to reach GitHub: a routine running on the web clones this repository and has
no `~/.claude` of yours, so this committed file is the only way it learns which plugin
marketplaces to trust when it reviews a pull request. It holds marketplace and plugin
declarations only — no absolute path, no account name, no secret. It must never declare
`hooks`: the global file already does, a project copy makes every hook run twice, and their
commands are Windows paths that do not exist on a Linux runner. Anything machine-specific goes
in `settings.local.json`, which is gitignored. `.claude/settings.template.json` remains the
declaration of the GLOBAL `~/.claude/settings.json`, which is a separate file with a separate
job.

## Prerequisites

| Tool | Required for |
|---|---|
| [Claude Code](https://docs.anthropic.com/claude-code) | Running agents and slash commands |
| [Git for Windows](https://git-scm.com/download/win) (includes Git Bash) | Hooks that use `bash` shell |
| [Node.js](https://nodejs.org/) | Caveman-mode hooks (`caveman-activate.js`, etc.) |
| Python 3.x | Scopus skill scripts + security hooks (`betterleaks`, `pip-audit`, `prompt-injection-defender`) |
| `pip install requests google-genai openai` | Scopus skill + Gemini/Copilot cross-review |
| `pip install pymupdf4llm pymupdf` *(optional, AGPL-3.0)* | `extract-statistic` skill PDF parsing (`mine` mode), LLM-ready Markdown + table extraction; reuses `SCOPUS_API_KEY` via `download_pdf.py`, needs no key of its own |
| `pip install docling markitdown[pdf]` *(optional, MIT; Docling pulls torch)* | Pluggable Markdown backend for `extract_text.py` (`--stats-scan` / `--section-scan`) and HTML conversion in the any-format retrieval path. Docling is the default (best tables/layout), MarkItDown the light fallback; absent both, the parser uses pymupdf4llm + a tag-strip |
| `pip install "psycopg[binary]" pgvector` *(optional)* | `extract-statistic`'s opt-in `corpus_index.py` (RT-7): pgvector store for ad-hoc cross-corpus retrieval. Both degrade gracefully when absent - the parse cache (`parse_cache.py`) and the chunker work without them, and the index reports itself unavailable |
| `pip install matplotlib` *(+ optional `folium`)* | `geolocalisation` skill: world-map PNG figure (`matplotlib`) and interactive HTML map (`folium`). No geopandas/GDAL. The `--full-text` study-site scan additionally reuses `pymupdf` + `download_pdf.py` |
| `pandoc` | `word2latex` skill (Word → LaTeX) |
| `pip install pypdf python-pptx jinja2 defusedxml` | `paper2talk` skill: paper-size PDF reflow (`pypdf`), the gabarit-based PowerPoint renderer (`python-pptx`), the Beamer/web renderers (`jinja2`), OOXML reading (`defusedxml`). Pinned in `.claude/skills/paper2talk/scripts/requirements.txt` |
| `npm install pptxgenjs` *(optional)* | `paper2talk` fallback for a PowerPoint deck with no gabarit at all. Set `NODE_PATH` when building outside the tree that holds the install |
| PowerPoint (Office 16+) **or** LibreOffice, plus Poppler `pdftoppm` | `paper2talk` render loop: deck → PDF → page images. On Windows the working path is PowerPoint COM `SaveAs(..., 32)`; the `document-skills` `soffice.py` wrapper fails here with `AF_UNIX`. Poppler ships with MiKTeX |
| draw.io Desktop *(optional)* | `paper2talk` figure re-export at scale 3 (`fig_export.py`); locate it with `--drawio` or `DRAWIO_EXE` |
| `pdflatex` (TeX Live / MiKTeX) | `recommendation-letter` skill: compile letters to PDF (degrades to `.tex` only if absent) |
| Obsidian Desktop *(optional)* | Obsidian vault integration in `CLAUDE.md` |
| `uv tool install graphifyy` *(optional)* | The graphify CLI behind the code-graph memory. The SKILL is vendored here (`.claude/skills/graphify/`, from graphify 0.9.50) so a clone is never left with instructions to consult a graph and no way to reach one; the CLI itself is not, and without it `query`, `path`, `explain` and `update` are simply unavailable |
| Ollama *(optional)* | The local model behind `local-writer` and `local-coder` |
| Docker and Docker Compose *(optional)* | `deploy/form-service/`, the containerized HTTP transport over the `form-service` skill. Not needed to use the skill itself |

Two Ollama settings are the operator's own step, and the scope is not interchangeable. The
`GRAPHIFY_*` pair ships in `.claude/settings.template.json`, because graphify runs as a child of
Claude Code and sends its own `keep_alive` in every request body, which overrides the daemon
default. The `OLLAMA_*` values cannot ship there at all and belong in the Windows user registry
(`HKCU:\Environment`), because the Ollama daemon is started by its own tray application at login
and never sees Claude Code's environment. Setting only one of the two leaves the model being
unloaded on a timer that nothing in this repository controls:

```powershell
# operator step, once, then restart the daemon and confirm with `ollama ps`
[Environment]::SetEnvironmentVariable('OLLAMA_KEEP_ALIVE',        '-1', 'User')
[Environment]::SetEnvironmentVariable('OLLAMA_MAX_LOADED_MODELS', '1',  'User')
[Environment]::SetEnvironmentVariable('OLLAMA_NUM_PARALLEL',      '1',  'User')
[Environment]::SetEnvironmentVariable('OLLAMA_FLASH_ATTENTION',   '1',  'User')
```

`OBSIDIAN_VAULT` is the third value of this kind, and `setup.ps1` now offers to set it at
USER scope when you give it a vault path. It is add-only: a variable that already holds a
value is printed and left alone unless you pass `-Force`, and a path that does not exist is
refused rather than stored. USER scope rather than the current shell is deliberate — the
Startup shortcut passes no argument, so a login-started daemon reads the user environment
block and nothing a shell exported. An already-open terminal keeps its old block, and VS Code
has to be restarted before a session sees the new one.

`ollama ps` must then show `Forever` in the `UNTIL` column. Restart the daemon with
`.claude\skills\opt-local-vram-llm\scripts\restart-ollama.ps1`, never by killing `ollama*` by
name: the model runs in a child process called `llama-server.exe`, which that pattern does not
match, so it survives and keeps its slice of VRAM.

## Step 1 — Clone the repository

```powershell
git clone https://github.com/LARi-UQAC/ResearchTools.git
cd ResearchTools
```

## Step 2 — Detect this machine's paths

Run the setup script from the repository root. It auto-detects Git Bash and Node.js and
asks for your Obsidian vault path (optional).

```powershell
.\setup.ps1
```

It writes nothing into the repository. The two templates
(`.claude/settings.template.json`, `CLAUDE.template.md`) are the hand-written sources, and
the configuration they describe belongs in your global Claude Code folder, `~/.claude/`.

## Step 3 — Make agents available globally (optional, recommended)

This step links `~/.claude/agents/`, `~/.claude/skills/`, `~/.claude/rules/`, and
`~/.claude/commands/` into this repository, so that Claude Code loads these agents and
skills in **every** workspace, not only when you open this folder.

Only missing links are created; existing ones are never overwritten.

```powershell
# Preview what will be created without making changes
.\setup.ps1 -InstallJunctions -Preview

# Apply
.\setup.ps1 -InstallJunctions
```

> **Alternative (direct):** `.\install-junctions.ps1` (or `.\install-junctions.ps1 -WhatIf` to preview).

**How linking works by directory type** (skills are folder-based, agents are file-based —
see the Agents chapter):

| Directory | Link type | One link per… | New file/folder after `git pull` |
|---|---|---|---|
| `agents/` | SymbolicLink per FILE (HardLink fallback when Developer Mode is off) | Agent file (e.g. `scopus-researcher.md`) | Re-run `.\setup.ps1 -InstallJunctions` — existing agents show `[EXISTS]`, only the new one is created. With HardLinks, also re-run after a pull that EDITS an agent (git rewrites detach hardlinks) |
| `skills/` | Junction per sub-folder | Skill (e.g. `scopus/`) | Re-run — only the new skill is created |
| `rules/` | Junction on the whole directory | Entire `rules/` folder | Automatic — new `.md` files are visible immediately through the existing junction, no re-run needed |
| `commands/` | Junction on the whole directory | Entire `commands/` folder | Same as above |

Junctions need no Administrator privileges. Agent file links prefer SymbolicLinks (enable
Windows Developer Mode, or run elevated); without that privilege the script falls back to
HardLinks automatically.

**Fallback when `rules/` or `commands/` already exists as a real directory** (another
project previously created it): the script automatically switches to per-file symbolic
links for any missing files. If Administrator privileges are required for the symlinks,
the script re-launches itself elevated.

Because the links point directly into this repository, a `git pull` is all that is
needed to propagate rule and command improvements contributed by any collaborator.

## Step 4 — Install for other coding tools (optional)

`install.ps1` regenerates the GitHub Copilot, OpenCode, Continue, Aider, and `AGENTS.md`
mirrors from the canonical `.claude/` sources (agents, task commands, rules). With `-Personal` it also
installs the Copilot agents to `~/.copilot/agents/` and the prompt/instruction files to
the VS Code user profile, making them available in every workspace:

```powershell
.\install.ps1                     # repo-level mirrors only (commit the output)
.\install.ps1 -Personal           # + user-level Copilot install
.\install.ps1 -Profile cosmetic   # + select the active domain profile
.\setup.ps1 -InstallTools -Personal   # same, via the setup entry point
```

`install.ps1` also records the active domain profile (see [Profiles](02-profiles.md)): pass
`-Profile <name>` or answer the interactive prompt; non-interactive runs keep the
current default (`engineering`).

Details in [Using the agents outside Claude Code](10-agents.md#using-the-agents-outside-claude-code).

## Step 5 — Python environment for the offline test suite (optional)

`scripts/test/run-offline-tests.ps1` resolves `.venv-skills\Scripts\python.exe` first, then
`.venv`, then whatever `python` is on `PATH`. Without that environment several suites cannot
import what they need and are reported **NOT RUN** — which is honest, and means the suite is
not actually proving what it looks like it is proving.

```powershell
.\setup.ps1 -InstallPython            # creates .venv-skills, installs, then pip-audits
.\setup.ps1 -InstallPython -Preview   # say what it would install, install nothing
```

It installs only what the offline suite imports: `pypdf`, `python-pptx`, `jinja2` and
`defusedxml` for the thirteen `paper2talk` suites, and `PyYAML` for
`test_letter_identity.py`. Everything else in the Prerequisites table above stays a manual
step on purpose — `docling` alone pulls `torch`, and a CVE in a skill you never run should
not block the environment your tests need.

By hand, if you would rather not use the switch:

```powershell
python -m venv .venv-skills
.\.venv-skills\Scripts\python.exe -m pip install -r .claude\skills\paper2talk\scripts\requirements.txt
.\.venv-skills\Scripts\python.exe -m pip install -r .claude\skills\recommendation-letter\scripts\requirements.txt
.\.venv-skills\Scripts\python.exe -m pip_audit --strict -r .claude\skills\paper2talk\scripts\requirements.txt
```

The directory name matters: name it anything else and the runner will not look there.

## Contributing improvements

Fork the repository, improve an agent or skill on a feature branch, and open a
pull request against `main`. The repository owner reviews and merges; a `git pull`
on their machine immediately updates the linked entries via the junctions.

To **add or edit an agent, skill, or command** (and propagate it to Copilot,
OpenCode, Continue, Aider, and `AGENTS.md` readers), follow the turnkey guide
[docs/authoring-and-mirrors.md](../authoring-and-mirrors.md): canonical sources,
per-type checklist, and the `install.ps1` mirror regeneration. Shared project
conventions and environment facts (English-only definition files, agent/skill
layout, local-model routing, git/GitHub workflow) live in
[docs/contributor-notes.md](../contributor-notes.md).

---
[← 00 Purpose & overview](00-purpose.md) | [Table of contents](../../README.md) | [02 Profiles & environment →](02-profiles.md)
