# Installation

Chapter 01 of the <a href="https://lari-uqac.github.io/ResearchTools/">ResearchTools</a> manual. Back to [table of contents](../../README.md).

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
| Output | Nothing inside the repository. Additively: `~/.claude/CLAUDE.md` (whole file only when absent), `~/.claude/settings.json` (only the hook entries the template declares and the live file lacks), `OBSIDIAN_VAULT` at USER scope (only when unset), and `.venv-skills/`, `.venv-docs/` and `.venv-pdf2md/` in the main clone with `-InstallPython` | Links in `C:\Users\<you>\.claude\` | Generated files committed in the repo (`.github\`, `.opencode\`, `.continue\`, `CONVENTIONS.md`, `AGENTS.md`) + optional user copies |
| When to run | Once after clone (or when machine paths change) | Once after clone; re-run when an agent or skill is ADDED (or a hardlink detached after a pull) | After every agent/command/rule EDIT, then commit the output |
| Privilege | none | symlinks want Developer Mode (automatic hardlink fallback) | none |
| Interactive | yes (asks vault path, confirms) - `-NonInteractive` refuses with exit 2 instead of assuming a default, and `-Preview` writes nothing at all | no | no |
| Via `setup.ps1` | - | `-InstallJunctions` | `-InstallTools` |
| Other switches | `-InstallDaemon` (vault daemon at login), `-InstallPython` (the three Python environments, see Step 5), `-UpdateHooks` (replace a changed hook entry of `~/.claude/settings.json`), `-KeepHooks <names>` (leave a local hook variant as it is), `-Update` (the whole update in one command, see [Update an existing installation](#update-an-existing-installation)) | `-Sync` (copy the files a green offline-suite run has proven into `~/.claude`), `-WhatIf` | - |

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
| Python libraries (`pip`) | Every library each skill imports, with its pin, the requirements file that declares it and the environment `setup.ps1 -InstallPython` puts it in: [chapter 02, Python environments](02-profiles.md#python-environments-every-library) |
| `pandoc` | `word2latex` skill (Word → LaTeX) |
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

Every target and the limits that stub or trim a mirror are in [chapter 09](09-harnesses.md). The agent side is in [Using the agents outside Claude Code](05-agents.md#using-the-agents-outside-claude-code).

## Step 5 — Python environments (optional)

`scripts/test/run-offline-tests.ps1`, the dashboard launchers, the vault drill and the other
launchers all take their Python from `.venv-skills` of the clone, then of the **main clone**
when you work in a linked worktree (they ask git for its common directory, so no link is
needed). If that environment is absent or empty they **refuse** and print every path they
looked at together with the rebuild command. They no longer fall back to the first `python`
on `PATH`: on one machine that was another account's Python, and a lost environment went
unnoticed for a week. To accept `PATH` knowingly, pass `-AllowPathFallback` (or
`--allow-path-fallback` for `rt-dashboard.sh`, in any position); to name an interpreter,
pass `-Python <path>`. The interpreter in use is always printed.

Without the environment several suites cannot import what they need and are reported
**NOT RUN** — which is honest, and means the suite is not actually proving what it looks like
it is proving.

One command builds the three environments of the repository, in the order of the data file
`scripts/lib/rt-python-requirements.json`:

| Environment | For | Holds |
|---|---|---|
| `.venv-skills` | the skills, the hooks' tests, the offline suite and the launchers | fourteen skill requirements files (every one except `pdf2md`'s) plus `pip-audit` |
| `.venv-docs` | building this site with MkDocs | `requirements-docs.txt` |
| `.venv-pdf2md` | the `pdf2md` conversion (`mineru`) | the `pdf2md` requirements file, kept apart because `mineru` needs an older `pillow` |

```powershell
.\setup.ps1 -InstallPython            # creates or extends the three environments, then pip-audits every file
.\setup.ps1 -InstallPython -Preview   # choose the interpreter, say what it would install, write nothing
.\setup.ps1 -InstallPython -Python "C:\Users\<you>\AppData\Local\Programs\Python\Python311\python.exe"
```

The environments are always built in the main clone, even when you run the command from a
worktree. An environment that already exists is reused and its requirements are installed into
it. The base interpreter is chosen only when one of them has to be created, and it is chosen, not
assumed: the switch tries `-Python`, then the `python` entries on `PATH` and the py launcher,
and keeps the first one that belongs to your own profile and can really create a virtual
environment (it builds a scratch one to check). If none qualifies it stops and names each
candidate with the reason, for example "belongs to another account" or "python -m venv failed".
A requirements file named in the data file that does not exist stops the run before anything is
installed. After the install, `pip-audit` (installed in `.venv-skills`) audits every
requirements file it applied.

`docling`, part of `extract-statistic`, is installed too and pulls `torch` (a dry run of
2026-10-22 counted 105 packages, about 339 MB). The three NVIDIA CUDA packages of `rt-observe` carry a
platform marker, so a macOS install skips them. The Chromium binary for Playwright stays a
separate `playwright install chromium`. The complete list of libraries, per environment, is in
[chapter 02](02-profiles.md#python-environments-every-library).

By hand, as an alternative to the switch, for one environment and one requirements file:

```powershell
python -m venv .venv-docs
.\.venv-docs\Scripts\python.exe -m pip install -r requirements-docs.txt
.\.venv-skills\Scripts\python.exe -m pip_audit --strict -r requirements-docs.txt
```

The directory names matter: name an environment anything else and the launchers will not look
there.

**Never link `.venv-skills` into a worktree** (junction or symbolic link). Removing the worktree
with `git worktree remove` (no `--force` needed when git ignores the link, as it does `.venv*/`) follows the link and deletes the real environment
([R37](../../.claude/rules/workflows.md)). A worktree needs no link.

## Step 6 — Privacy guard for every git repository (recommended)

A global pre-commit hook refuses a commit that adds a secret or personal data (account paths,
Quebec student codes, `@etu.uqac.ca` addresses, FRQ identifiers, your own account name), in
every repository on the machine. The repository's own hooks keep running.

```powershell
winget install Betterleaks.Betterleaks                  # the scanner the hook calls
.\.claude\hooks\git\install-git-hooks.ps1 -DryRun       # say what it would do
.\.claude\hooks\git\install-git-hooks.ps1               # copy to ~/.config/git/hooks, set core.hooksPath
```

A deliberate exception: `betterleaks:allow` on the line. A private repository can opt out
with `git config privacyguard.enabled false`. If another tool already owns the global
`core.hooksPath`, the installer refuses rather than overwrite it. The `privacy-scan` CI
workflow applies the same rules to every push and pull request.

**Real names have no shape, so no rule can recognise them.** Give the hooks a list of your own
students' names that never leaves your machine:

```powershell
.\.claude\hooks\git\install-git-hooks.ps1 -TermsFrom "<folder of student projects>" -TermsDepth 2
```

The folder names found two levels down are split at capitals into `private-terms.txt` beside the
installed hooks, and the hooks then refuse any of them in an added line, a path, a commit message
or a commit author. Only counts are printed. **Run the same command for every new student:** it
only appends the names the file lacks, so earlier names (even a student whose folder is gone) and
lines you typed stay. Add names by hand in `private-terms.extra.txt`. The installer **refuses to write the list in a synchronized or shared
folder** (OneDrive, Dropbox, Google Drive, a network share): the list holds real names and must not
be copied off the machine. If it refuses, run `-Uninstall`, then install again with
`-Target <a local folder>`. Never paste a name into an issue, a pull request or a commit message:
no hook sees GitHub comments.

## Update an existing installation

Run these from the root of your clone, the folder that holds `setup.ps1` (the `ResearchTools`
folder `git clone` created), in PowerShell. The first two lines are prerequisites. The next two are
the update itself (a preview, then the real one). The last line is an optional proof:

```powershell
git pull --ff-only origin main        # get the new version
.\setup.ps1 -InstallPython            # only if .venv-skills is missing, or you want to run the offline suite
.\setup.ps1 -Update -Preview          # shows every step and writes nothing to ~/.claude
.\setup.ps1 -Update                   # does the update, and asks the three questions below first
.\scripts\test\run-all-checks.ps1     # optional proof: the offline suite and the verify-*.ps1 of scripts/test (about 15 minutes)
```

**What `-Update` asks, once, before it changes anything.** The domain profile (the names found in
`profiles/`, and Enter keeps the profile recorded today; an unknown name is refused). Whether to
also install GitHub Copilot at user level (default no). Whether to run the offline test suite first
(about 15 minutes, default no), which is what lets the sync copy changed hooks, see below. The
vault stored in the `OBSIDIAN_VAULT` user variable is reused without a question, and there is no
second "Proceed?".

**What it then runs, in this order:**

| # | Step | Command it stands for |
|---|---|---|
| 1 | Global configuration (hook entries are added; changed hook commands are replaced after step 5) | `.\setup.ps1 -UpdateHooks` |
| 2 | Claude Code links | `.\setup.ps1 -InstallJunctions` |
| 3 | Mirrors for the other tools | `.\install.ps1 -Profile <profile>` and `-Personal` when you said yes to Copilot |
| 4 | Offline test suite, only when you asked | `.\scripts\test\run-offline-tests.ps1` |
| 5 | Copy the proven files into `~/.claude` | `.\install-junctions.ps1 -Sync` |
| 6 | Deployment check, read-only | `.\scripts\audit\check-deployment.ps1` |

In `-Preview` the links and the sync run as `-WhatIf`, step 3 is skipped (`install.ps1` has no
preview mode) and step 4 is left out, while the read-only check still runs. The check lists what the
real update would fix, so in a preview it does not turn the exit code into a failure. A step that
fails does not stop the later ones, and the exit code is the worst one. Step 2 is advisory: a
conflict it reports is a warning, because step 5 refreshes stale copies and the check at the end
judges the state the update leaves. Scripted runs need
`-NonInteractive -Profile <name>`, and add `-Personal` and `-RunSuite` for the two yes answers.

**Changed hook entries (`-UpdateHooks`).** `setup.ps1` used to add a hook entry only when it was
absent from `~/.claude/settings.json`, so a changed command never arrived (the memory reminder was
the first case). With `-UpdateHooks`, an entry the template declares and the live file already has
is recognised by its own script name or bracket tag, and its `command` and `statusMessage` are
replaced when they differ. The file is edited as text, so nothing else in it moves. A backup
`settings.json.bak-<date>-<time>` is made first, the result is parsed before it is written and read
back after, and the backup is restored when the read-back fails. An entry it cannot match with
certainty (the same tag twice in one event, or an old value that does not occur exactly once) is
reported and left alone. **A hand edit of a recognised entry is overwritten**, and the backup keeps
it. Under `-Update` the replacement is made after the sync (step 5), once the scripts are in place,
because a new command that calls an old script can exit non-zero and refuse every tool of its
matcher. An entry whose script the sync held (no green suite) is skipped by name and listed, and the
update tells you to run the suite, `-Sync`, then `-UpdateHooks`. It also skips the whole hook update
when Git Bash or Node.js was not found, rather than write a path that does not exist. A `matcher`
or `timeout` that differs from the template is reported, not edited, since only `command` and
`statusMessage` are replaced. Without the switch, `setup.ps1` only reports how many entries differ. Preview it first with
`.\setup.ps1 -UpdateHooks -Preview`.

**Keeping a local variant (`-KeepHooks`).** A hook entry you changed on purpose on this machine is
not an old version, and `-UpdateHooks` cannot tell the two apart. Name it and it is left exactly as
it is, with no backup and no edit: `.\setup.ps1 -Update -KeepHooks 'AUTO-SYNC CHECK'`. The names are
the ones the output prints (a script name such as `review-loop-guard.py`, or the bracket tag of an
inline hook), written with or without the brackets and in any case. Several names are separated by
commas. The lab owner's machine needs it for the git-sync entry, whose folder-name guard differs
from the template on purpose.

**Why the sync may hold files.** `install-junctions.ps1 -Sync` copies a hook or an agent into
`~/.claude` only when a green offline-suite run has proven that exact file. With no green stamp it
copies prose such as agents and holds the code, and says which. If it held files, run
`.\setup.ps1 -Update -RunSuite` (or the suite and then `.\install-junctions.ps1 -Sync`), or fix the
failing suite first.

**Checking the result (`run-all-checks.ps1`).** `run-offline-tests.ps1` runs only the Python suites,
so a green suite does not cover the PowerShell verifiers (`verify-setup-writes.ps1`,
`verify-sync-writes.ps1` and the others). `.\scripts\test\run-all-checks.ps1` runs the suite and then
every `verify-*.ps1` of `scripts/test`, each in its own process, runs all of them even when one
fails, prints which failed and exits 1 if any did. Five verifiers live elsewhere and are not run by
it: `scripts/local/Test/verify-claude-switch.ps1`, the three `verify-*.ps1` of
`.claude/skills/aider-setup/scripts/Test`, and `.claude/skills/aider-setup/scripts/build/verify-kit-install.ps1`. It leaves out `verify-graph-health.ps1`, which only the
`local-writer` agent may run. `-DryRun` lists the checks and runs none, `-SkipSuite` skips the
15-minute suite, `-Only verify-setup-writes,verify-sync-writes` runs just those, and
`-ReportPath result.json` also writes a JSON report. If `.venv-skills` is missing the suite stops
and names the command that rebuilds it: `.\setup.ps1 -InstallPython`. A green run also writes
`.rt-green.json`, which is what lets the sync copy changed hooks (run `.\install-junctions.ps1 -Sync`
afterwards, or `.\setup.ps1 -Update` again).

**What is still yours:**

- Close and reopen VS Code and Claude Code. Hooks and rules are read when a session starts, and
  the `[HOOKS ACTIVE]` line at the start of the session must say `0 missing`.
- `install.ps1 -Profile` records the profile in `.claude\CLAUDE.md`, a tracked file, so `git status`
  will show it. Keep the change or restore the file with git.
- A `[CONFLICT]` line from the links step means a real file in `~/.claude\agents` that differs from
  the repository shadows it. A real file that is byte-for-byte the repository version (the copy the
  sync makes when Windows refuses a link) is reported as already there and is not a conflict. A
  differing one is a warning during `-Update`, since the sync that follows refreshes it, and the
  check at the end says whether anything still shadows the repository. Run alone, the links step
  still exits with code 1 on a differing file and does not remove it for you.
- `git pull` and the Python environment are not part of `-Update`. Run them first, as above.

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
