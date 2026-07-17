# ResearchTools — Manual

## Purpose

Ask for my book (French version): Vibe Design. 30$ contribution via:

[![ko-fi](https://ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/s/89b1e1cc6c)

[![PayPal](https://img.shields.io/badge/Donate-PayPal-green.svg)](https://www.paypal.me/MartinJDOtis)

ResearchTools is an AI-assisted toolbox for researcher-professors and graduate students
who want to find and fix the issues hiding in their academic writing before a reviewer,
a thesis committee, or a grant panel does. It contains two loop for authoring and coding. It covers the whole process: starting
a literature review, auditing an existing review, a complete paper, a UQAC
thesis or thesis proposal, cleaning/improving a BibTeX file, helping to respond to peer reviewers, checking submission readiness against a target journal, building the submission package, and converting Word to LaTeX with high accuracy.

Every check is grounded in the same working norms: no reference enters a document
without being validated against Scopus (no fabricated citations, no invented DOIs),
weaknesses are reported as actionable findings with an executable improvement plan
rather than vague encouragement, and drafts pass a multi-model deliberation (Gemini +
GitHub Copilot debate, arbitrated with Claude) before a plan or review is finalized. Each improvment is evaluated with a score and then you can see the quantitative improvments.

The toolbox is built as agents, skills, and commands for [Claude Code](https://docs.anthropic.com/claude-code),
with generated mirrors for GitHub Copilot, OpenCode, Continue, and Aider (see
[Installation](#installation)). Typical entry points: `/litreview` for a new topic,
`/auditpaper` before submitting, `/auditthesis` before a defense, `/bibclean` on any
`.bib` file, `/replyreviewer` when the reviews come back.

## About this manual

Reference for the skills, agents and commands shipped in this repository. Everything
documented here lives under `.claude/` in **this** repo (academic research tooling for
LaTeX writing, Scopus reference validation, paper/thesis auditing, and grant-template
conversion). For a map of how the pieces relate, see [Architecture.md](Architecture.md).

The repo ships **10 skills**, **15 agents**, and **19 commands**.

---

## Installation

Follow these steps on any machine after cloning the repository.

### Install scripts overview

Three scripts, three different jobs and lifecycles. `setup.ps1` is the single entry point:
it wraps the other two via `-InstallJunctions` / `-InstallTools`, and `-All` runs the full
sequence (config, then junctions, then tools) in one pass.

| | `setup.ps1` | `install-junctions.ps1` | `install.ps1` |
|---|---|---|---|
| Job | Generate machine-local config: `.claude\settings.json` + `CLAUDE.md` from templates (detects Git Bash, Node, Obsidian paths of THIS machine) | Link the repo into `~/.claude` so Claude Code loads agents/skills/rules/commands in every workspace | Generate mirrors for other coders: GitHub Copilot, OpenCode, Continue, Aider (`-Personal` adds the user-level Copilot install) |
| Output | 2 machine-specific files (paths differ per PC) | Links in `C:\Users\<you>\.claude\` | Generated files committed in the repo (`.github\`, `.opencode\`, `.continue\`, `CONVENTIONS.md`) + optional user copies |
| When to run | Once after clone (or when machine paths change) | Once after clone; re-run when an agent or skill is ADDED (or a hardlink detached after a pull) | After every agent/command/rule EDIT, then commit the output |
| Privilege | none | symlinks want Developer Mode (automatic hardlink fallback) | none |
| Interactive | yes (asks vault path, confirms) | no | no |
| Via `setup.ps1` | - | `-InstallJunctions` | `-InstallTools` |

```powershell
.\setup.ps1 -All -Personal   # new machine: config + Claude links + all tool mirrors
```

### Prerequisites

| Tool | Required for |
|---|---|
| [Claude Code](https://docs.anthropic.com/claude-code) | Running agents and slash commands |
| [Git for Windows](https://git-scm.com/download/win) (includes Git Bash) | Hooks that use `bash` shell |
| [Node.js](https://nodejs.org/) | Caveman-mode hooks (`caveman-activate.js`, etc.) |
| Python 3.x | Scopus skill scripts + security hooks (`betterleaks`, `pip-audit`, `prompt-injection-defender`) |
| `pip install requests google-genai openai` | Scopus skill + Gemini/Copilot cross-review |
| `pip install pymupdf4llm pymupdf` *(optional, AGPL-3.0)* | `extract-statistic` skill PDF parsing (`mine` mode), LLM-ready Markdown + table extraction; reuses `SCOPUS_API_KEY` via `download_pdf.py`, needs no key of its own |
| `pip install docling markitdown[pdf]` *(optional, MIT; Docling pulls torch)* | Pluggable Markdown backend for `extract_text.py` (`--stats-scan` / `--section-scan`) and HTML conversion in the any-format retrieval path. Docling is the default (best tables/layout), MarkItDown the light fallback; absent both, the parser uses pymupdf4llm + a tag-strip |
| `pip install matplotlib` *(+ optional `folium`)* | `geolocalisation` skill: world-map PNG figure (`matplotlib`) and interactive HTML map (`folium`). No geopandas/GDAL. The `--full-text` study-site scan additionally reuses `pymupdf` + `download_pdf.py` |
| `pandoc` | `word2latex` skill (Word → LaTeX) |
| Obsidian Desktop *(optional)* | Obsidian vault integration in `CLAUDE.md` |

### Step 1 — Clone the repository

```powershell
git clone https://github.com/LARi-UQAC/ResearchTools.git
cd ResearchTools
```

### Step 2 — Generate machine-local configuration

Run the setup script from the repository root. It auto-detects Git Bash and Node.js,
asks for your Obsidian vault path (optional), and generates two gitignored files:
`.claude/settings.json` and `CLAUDE.md`.

```powershell
.\setup.ps1
```

Verify that no `{{placeholder}}` remains after the script completes — it reports any
unreplaced values in the validation step.

### Step 3 — Make agents available globally (optional, recommended)

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
see the Agents section):

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

### Step 4 — Install for other coding tools (optional)

`install.ps1` regenerates the GitHub Copilot, OpenCode, Continue, and Aider mirrors from
the canonical `.claude/` sources (agents, task commands, rules). With `-Personal` it also
installs the Copilot agents to `~/.copilot/agents/` and the prompt/instruction files to
the VS Code user profile, making them available in every workspace:

```powershell
.\install.ps1                     # repo-level mirrors only (commit the output)
.\install.ps1 -Personal           # + user-level Copilot install
.\install.ps1 -Profile cosmetic   # + select the active domain profile
.\setup.ps1 -InstallTools -Personal   # same, via the setup entry point
```

`install.ps1` also records the active domain profile (see [Profiles](#profiles)): pass
`-Profile <name>` or answer the interactive prompt; non-interactive runs keep the
current default (`engineering`).

Details in [Using the agents outside Claude Code](#using-the-agents-outside-claude-code).

### Contributing improvements

Fork the repository, improve an agent or skill on a feature branch, and open a
pull request against `main`. The repository owner reviews and merges; a `git pull`
on their machine immediately updates the linked entries via the junctions.

---

## Profiles

A domain profile centralizes everything domain-specific (Scopus subject areas and
exclusions, topical-relevance signals, off-topic flag, stats profile, author, course
context, language) in one YAML file under `profiles/`, so the agents and skills stay
shared across users and labs: one maintained core, N profiles.

| Profile | Domain | Author | Default |
|---|---|---|---|
| `engineering.yaml` | Mechanical / electrical / ML / control / systems engineering | Martin Otis (UQAC) | yes |
| `cosmetic.yaml` | Cosmetic / formulation science (SPF, microbiome, dermatology, sensory) | Lionel Ripoll (UQAC) | no |
| `_template.yaml` | Copy it to `profiles/<domain>.yaml` to add a new domain | - | - |

The active profile is recorded in `.claude/CLAUDE.md` as the machine-readable line
`active_profile: <name>`. Select it at install time (`.\install.ps1 -Profile <name>`, or
the interactive prompt) or edit that line directly. Currently wired consumer:
`scopus-researcher` (search clauses, Step 3a relevance check, synthesis framework); the
remaining fields (`author`, `stats_profile`, `course_context`, `language`) are schema-ready
and will be wired incrementally. Field-by-field spec, fallback rules, and the add-a-profile
procedure: [profiles/README.md](profiles/README.md).

---

## Environment variables / API keys

Set these at the Windows **User** scope (PowerShell), then restart Claude Code:

```powershell
[System.Environment]::SetEnvironmentVariable('SCOPUS_API_KEY', 'your-key', 'User')
```

| Variable / source | Required for | Where to get it |
|---|---|---|
| `SCOPUS_API_KEY` | **Required** — all `/scopus`, `/auditreview`, `/auditpaper`, `/auditthesis`, `/litreview`, `/bibclean`, `/replyreviewer`, and PDF retrieval | [Elsevier Developer Portal](https://dev.elsevier.com/) |
| `.scopus_key` file | Fallback for `SCOPUS_API_KEY` — place the key in `.claude/skills/scopus/.scopus_key` (gitignored) | same key as above |
| `UNPAYWALL_EMAIL` | *Optional* — enables the Unpaywall open-access tier in `download_pdf.py` (HTML/PDF fallback when no publisher PDF); a plain contact email, or pass `--email` | any institutional email |
| `GEMINI_API_KEY` | *Optional* — Gemini 2.0 Flash cross-review and table enrichment (deliberation panel) | [Google AI Studio](https://aistudio.google.com/apikey) |
| `GITHUB_TOKEN` | *Optional* — GPT-4o cross-review via GitHub Models (deliberation panel) | GitHub → Settings → Developer settings → Personal access token |
| `S2_API_KEY` *(or `SEMANTIC_SCHOLAR_API_KEY`)* | *Optional* — Semantic Scholar author/PDF backfill; without it the throttled public pool is used | [Semantic Scholar API key request](https://www.semanticscholar.org/product/api) |
| `--insttoken` *(CLI flag, not an env var)* | *Optional* — off-campus Elsevier access when not on the UQAC network/VPN | UQAC library / Elsevier institutional token |

> An on-campus network connection or active UQAC VPN is required for Scopus access
> unless an `--insttoken` is supplied. Secrets are kept out of git: `.env`, `secrets/`,
> and `credentials/` are listed in `.gitignore`.

---

## Token Management

Use these tools together to keep sessions fast and cheap.

### Output modes

| Mode | Command | Max length | Formatting |
| --- | --- | --- | --- |
| Normal | *(none)* | Unlimited | Full — headers, tables, bullets |
| Concise | `/concis` | 5 sentences | Structured bullets allowed |
| Slim | `/slim` | 2 sentences | Code blocks only, no prose |

### Recommended workflow

1. **Start** every session with `/slim` (quick tasks) or `/concis` (exploratory work)
2. **Scope** context with `/focus <topic>` to avoid loading irrelevant files
3. **Monitor** with `/ctx` when responses feel slow — it reports context pressure in under 10 lines
4. **Compress** with `/compact` when `/ctx` reports moderate or high pressure

> `/compact` is destructive — conversation history is summarized and cannot be restored. Always run `/ctx` first to confirm it is needed.

### Quick reference

| Command | When to use |
| --- | --- |
| `/slim` | Fast edits, one-liners, quick questions |
| `/concis` | Code reviews, multi-step explanations |
| `/focus <topic>` | Long sessions touching many files |
| `/ctx` | When the session feels sluggish or heavy |
| `/compact` | After `/ctx` reports moderate/high pressure |

---

## Skills

Skills bundle scripts and references the agents reuse. Ten ship in this repo.

| Skill | Purpose | Entry point |
|---|---|---|
| `scopus` | Search Scopus, validate references, fetch PDFs via the Elsevier REST API (with a Semantic Scholar fallback). | `/scopus`, `.claude/skills/scopus/SKILL.md` |
| `scientific-writing` | Core writing skill: scientific manuscripts in flowing IMRAD prose with verified citations (IEEE/APA/AMA/Vancouver) and reporting guidelines (CONSORT/STROBE/PRISMA). | `.claude/skills/scientific-writing/SKILL.md` |
| `scholar-evaluation` | ScholarEval framework — scores research work across problem formulation, literature review, methodology, data, analysis, results, writing, citations. | `.claude/skills/scholar-evaluation/SKILL.md` |
| `deliberation` | Two-round Gemini ↔ GitHub Copilot debate over a near-final draft; Claude arbitrates and validates any new references against Scopus. Used inside the auditor/researcher agents. | `.claude/skills/deliberation/SKILL.md` |
| `extract-statistic` | Statistical analysis. Mode `audit`: review a manuscript's own statistics (test selection, assumptions, effect size, presentation, cross-validation). Mode `mine`: extract the reported statistics of a corpus's full-text PDFs and synthesize a corpus statistics table plus an improvement-opportunity list. Engineering-default domain profiles. Used inside `paper-auditor` / `thesis-auditor` (audit) and `scopus-researcher` (mine). | `.claude/skills/extract-statistic/SKILL.md` |
| `extract-futureworks` | Future-works analysis (reuses `extract_text.py --section-scan`). Mode `audit`: review a work's own future works (presence, testability, link-to-limitation, novelty) and validate its hypotheses against the cited-corpus future works, proposing stronger ones. Mode `mine`: extract every corpus paper's stated future works, build a review-fit table, Pareto 80/20-rank it (low effort, high impact first), and emit a research-opportunity list. Used inside the four auditors (audit) and `scopus-researcher` (mine), where it is a hard gate: no hypothesis/project without it. | `.claude/skills/extract-futureworks/SKILL.md` |
| `word2latex` | Convert a Word `.docx` template (Mitacs, CRSNG, FRQNT, UQAC, partner forms) into a faithful LaTeX source. Delegates the patch work to the `word-to-latex` agent. | `/word2latex`, `.claude/skills/word2latex/SKILL.md` |
| `drawio2tikz` | Convert one `.drawio` sheet into a coordinate-exact TikZ fragment (absolute coordinates, edge anchoring, braces, rotation, FR→EN `--translate`). The sanctioned absolute-coordinate exception to the hand-authored TiKZ rules. | `/drawio2tikz`, `.claude/skills/drawio2tikz/SKILL.md` |
| `geolocalisation` | Map a review corpus in space from its `.bib`: resolve each paper's study/case-study site (per-DOI Scopus abstract + title + keywords, optional `--full-text` PDF scan via `download_pdf.py`, matched against an offline Natural Earth gazetteer), write a reviewable draft table with a confidence column and a per-paper provenance note, then render CSV, KML (Google My Maps), GeoJSON (QGIS/Leaflet), a world-map PNG, an interactive HTML map, and a per-country count table. Human-reviewed; an override CSV always wins. | `/geolocalisation`, `.claude/skills/geolocalisation/SKILL.md` |
| `loop-engineer` | Budget-bounded develop-and-improve loop (Agent SDK driver): design → plan → code → comment → test → review → score → correct, looping until a composite gate (tests green, no CRITICAL/HIGH, score `>=` min) or a hard budget/max-iters/no-progress stop. Fable 5 orchestrates; Opus/Sonnet act; `local-coder`/`local-writer` do local generation. `loop_audit.py` aggregates the installed reviewers into a 0-100 score with a security hard floor; merge to a protected branch is human-gated. | `/loopdev`, `.claude/skills/loop-engineer/SKILL.md` |

### `/scopus` — Scopus academic search

Searches the Scopus database via the Elsevier REST API. Requires `SCOPUS_API_KEY`
(see the API-keys table above) and an active institutional network connection
(campus or VPN), or an `--insttoken`.

| Command | What it does |
|---------|-------------|
| `/scopus <topic>` | Search top papers on a topic |
| `/scopus review <topic>` | Structured literature review with inline citations |
| `/scopus validate <DOI or title>` | Confirm a reference exists and return full metadata |
| `/scopus cite <DOI>` | Citation count + full metadata for one paper |
| `/scopus author <name>` | Author h-index and top publications |
| `/scopus journal <name or ISSN>` | Journal SJR quartile, CiteScore, subject areas |

**Files:**
- `.claude/skills/scopus/SKILL.md`
- `.claude/skills/scopus/scripts/scopus_api.py` — Scopus REST client
- `.claude/skills/scopus/scripts/semantic_scholar_api.py` — Semantic Scholar fallback
- `.claude/skills/scopus/scripts/download_pdf.py` — any-format full-text retrieval (PDF, else HTML/Markdown via Unpaywall, arXiv, PMC, validated DOI landing)
- `.claude/skills/scopus/scripts/gemini_reviewer.py` · `github_reviewer.py` · `gemini_table.py` — cross-review cores

### `geolocalisation` — corpus study-location mapping

Turns a corpus `.bib` into a spatial map of where each paper's empirical study was conducted.
A case-study site is not a bibliographic field (no API returns it — it lives in the text), so
the skill is deliberately human-in-the-loop: it emits a **draft** with a `confidence` column and
a per-paper provenance note, a human reviews it, and a manual **override CSV always wins** before
rendering. Requires `SCOPUS_API_KEY` (campus network or VPN), or run `--no-scopus` for a
manual-entry template.

| Stage | Command | Output |
|---|---|---|
| 1 — extract | `extract_locations.py --bib <corpus.bib> --out <dir> [--full-text] [--override <curated.csv>]` | `study_locations.csv` (with `confidence`, `evidence_field`, `evidence`, `provenance`) + `provenance/<citekey>.md` audit notes |
| 2 — review | *(human)* | curate / confirm; correct every `low`/`none` row via the override CSV |
| 3 — render | `generate_geomap.py --csv <dir>/study_locations.csv --out <dir> [--formats …] [--min-confidence …]` | CSV, KML (Google My Maps), GeoJSON (QGIS/Leaflet), world-map PNG, interactive HTML, `country_counts.csv` |

- **Extraction:** per-DOI Scopus abstract + title + keywords; place names matched against an
  offline Natural Earth gazetteer, with capitalization + a population floor + a common-word
  stoplist for precision (separates the city `Mobile` from the word `mobile`).
- **`--full-text`:** for `none`/`low` results, downloads the PDF via the scopus skill's
  `download_pdf.py`, reads it with PyMuPDF, and scans **only study-cue sentences with
  affiliation lines rejected** — an unfiltered full-text scan maps author affiliations, not
  study sites. Adopted only when it beats the abstract; PDFs cached in `refs/`.
- **Auditability:** every mapped point carries `evidence_field` + the verbatim `evidence`
  sentence in the CSV, a `provenance/<citekey>.md` note, and the same surfaced in the HTML
  popup, GeoJSON properties, and KML description.
- No geopandas/GDAL — the basemap is drawn from raw GeoJSON. Deps: `matplotlib` (PNG),
  optional `folium` (HTML) and `PyMuPDF` (`--full-text`).

**Files:**
- `.claude/skills/geolocalisation/SKILL.md`
- `.claude/skills/geolocalisation/scripts/extract_locations.py` — bib + Scopus/full-text → draft CSV + provenance notes
- `.claude/skills/geolocalisation/scripts/generate_geomap.py` — reviewed CSV → CSV/KML/GeoJSON/PNG/HTML + per-country table (no geopandas)
- `.claude/skills/geolocalisation/references/geocoding-protocol.md` — extraction method, confidence rubric, override format, full-text pipeline
- `.claude/skills/geolocalisation/scripts/Test/test_extract_locations.py` — offline unit tests (bib parse, matcher, evidence, full-text)

---

## Security audit (SkillSpector)

All eight skills under `.claude/skills/` were scanned with **SkillSpector v2.2.3** in
static-only mode (`skillspector scan <skill> --no-llm`) on **2026-06-18**, every dependency
finding cross-checked against `pip-audit`.

**True positives — corrected**

- **LP3 (missing permission declaration):** added to the frontmatter of `scopus`, `deliberation`,
  `extract-statistic`, `scholar-evaluation`, `word2latex`, and `drawio2tikz` a per-skill
  `permissions:` list declaring exactly the capabilities each skill's scripts use (e.g. `scopus`
  → `[env, read, write, network]`), plus an `allowed-tools: [Read, Write, Edit, Bash]` runtime
  restriction. Re-scan confirms LP3 cleared with no LP1/LP4 regression.
- **SC1 (unpinned dependencies):** pinned `>=` to exact `==` versions in
  `scopus/scripts/requirements.txt` (requests, google-genai, openai) and
  `extract-statistic/scripts/requirements.txt` (pymupdf4llm, pymupdf, docling, markitdown),
  using versions confirmed clean by `pip-audit`.

**False positives — reviewed and ignored**

- **SC4 (vulnerable dependency):** flagged by package name only; `pip-audit` resolves every
  declared `>=` floor to a patched release (`No known vulnerabilities found`).
- **E1 / E2 (external transmission / env harvesting):** skills reading their own configured API
  keys and querying their own research APIs (Elsevier, Unpaywall, Semantic Scholar).
- **TT2 (taint flow):** the https-only, redirect-disabled PDF download in `download_pdf.py`.
- **PE3 / RA2 / EA1 / EA2 / P6:** keyword matches inside docstrings/markdown (e.g. `SNIPList`,
  the `GITHUB_TOKEN` doc line, a `**…tool:**` bullet, a DOI-workflow description, a returned
  local prompt string).
- **AST4 (subprocess):** the test harness invoking the skill script with a fixed argument list.

`scientific-writing` and `extract-futureworks` required no changes.

The `geolocalisation` skill was added after this scan (2026-07) and should be scanned on the
next pass. Its declared dependencies pin exact/floor versions verified with `pip-audit`:
`matplotlib==3.9.2`, `pillow>=12.3.0` (fixes PYSEC-2026-2253..2257), and the optional
`folium==0.17.0` / `PyMuPDF==1.27.2`. It declares `permissions: [read]` and
`allowed-tools: [Read, Write, Edit, Bash]`, reuses the scopus skill's network I/O through
`download_pdf.py` rather than opening its own, and fetches only public-domain Natural Earth
basemaps (TLS-verified, cached).

---

## Commands (Slash Commands)

Invoked with `/command-name [arguments]` in any Claude Code session. All files live in
`.claude/commands/`.

| Command | What it does | Arguments |
|---|---|---|
| `/concis` | Concise mode for the rest of the session | No |
| `/slim` | Slim mode — ultra-minimal output (2 sentences, code only) | No |
| `/focus <topic>` | Scopes the session to one topic only | Yes — topic |
| `/ctx` | Audits context-window pressure (turns, topics, recommendation) | No |
| `/tikz [code]` | Validates TiKZ code against 6 rules (anchoring, arrows, overlaps…) | Optional — code or file |
| `/test [module]` | Runs project tests following `.claude/rules/testing.md` | Optional — module/file |
| `/doc <target>` | Generates or updates documentation for a file or function | Yes — file/function |
| `/latex [args]` | Diagnoses and fixes LaTeX errors from the `.log` or open file | Optional — specific error |
| `/ref <citation>` | Formats and validates an academic reference (UQAC/LAR.i style) | Yes — reference |
| `/litreview <topic>` | Full autonomous literature review: search → validate → synthesize → comparison table → hypotheses + contributions → objectives → context → novelty checklist | Yes — research topic |
| `/auditreview [file or text]` | Audit an existing review: validate references, flag errors, novelty checklist, executable improvement plan | Optional — file/text/IDE file |
| `/auditpaper [file or text]` | Audit a complete paper: references, methodology, results, discussion, future works — Scopus validation + cross-review + improvement plan | Optional — file/text/IDE file |
| `/auditthesis [main.tex or dir]` | Full UQAC thesis audit: front matter, jury, hypothesis flow, chapter structure, references, figures, equations, acronyms, LLM-style, bilingual résumé/abstract, UQAC formatting | Optional — path/dir/IDE file |
| `/bibclean [file.bib]` | Clean and validate a BibTeX file: required fields, author normalization, duplicates, DOI enrichment, SJR quartile, publisher approval check | Optional — `.bib` file/IDE file |
| `/submitcheck <file.tex> <journal>` | Check submission readiness for a target journal: page count, sections, reference style, abstract length, keywords, anonymization | Yes — `.tex` file + journal |
| `/replyreviewer` | Point-by-point LaTeX response letters + track-change markup in the paper via the `changes` package (one letter per reviewer file) | Yes — see below |
| `/word2latex` | Convert a Word `.docx` template to a faithful LaTeX source (pandoc + standard patch sequence) | Yes — `.docx` path |
| `/geolocalisation` | Map a review corpus's study locations from its `.bib`: draft study-location table (confidence + per-paper provenance), human review, then CSV/KML/GeoJSON/PNG/HTML + per-country count. Optional `--full-text` PDF scan. | Optional — `.bib` file/dir/IDE file |

### `/concis` — Concise mode

Activates for the rest of the session: max 5 sentences for short answers, structured
bullets for long answers, no preamble, no trailing summary, code written directly with
WHY-only comments. Responds in French unless the active file is in English.

**File:** `.claude/commands/concis.md`

### `/focus <topic>` — Session scope

Restricts the session to a single topic; everything outside it is ignored. Responds in
French unless the active file is in English.

**File:** `.claude/commands/focus.md`

### `/ctx` — Context window audit

Reports, in under 10 lines: estimated exchange turns, top 3 context-consuming topics/files,
a low/moderate/high pressure level, and a `/compact` recommendation when needed. Reads no
additional files. Responds in French.

**File:** `.claude/commands/ctx.md`

### `/tikz` — TiKZ validation

Validates TiKZ code (from `$ARGUMENTS` or the IDE file) against 6 rules:

| Rule | What is checked |
|---|---|
| Line breaks in nodes | `align=center` only — never `text centered` |
| backgrounds + scaling | No `\begin{scope}[on background layer]` inside `\resizebox`/`\scalebox` |
| Arrow angles | Arrows connect perpendicularly to node borders (.north/.south/.east/.west) |
| Overlaps | Min 3-character gap between rectangles; arrow labels must not overlap geometry |
| Anchoring | `positioning` library + `node distance` only — no absolute coordinates |
| TiKZiT compatibility | Named styles in `.tikzstyles`; no exotic libraries |

For each violation: cites the line, explains the cause, provides corrected code directly.

A figure generated by the `drawio2tikz` skill is exempt from the Anchoring and TiKZiT-compatibility
rules (it uses absolute coordinates by design); arrow tips, spacing, and overlaps are still checked.

**File:** `.claude/commands/tikz.md`

### `/test [module]` — Run project tests

Reads `.claude/rules/testing.md`, selects the correct venv, runs the tests, and reports
**passed / total** with short error messages and likely causes.

**File:** `.claude/commands/test.md`

### `/doc <target>` — Documentation generator

Generates documentation following `.claude/rules/code-style.md` (Python Stage-N module +
Purpose/Inputs/Outputs docstrings; C# `/// <summary>`; LaTeX/Markdown equation formatting).
Documents WHY, not WHAT. Responds in French unless the active file is in English.

**File:** `.claude/commands/doc.md`

### `/latex` — LaTeX diagnosis and fix

Reads `out/*.log` first for exact error lines, cites the line, explains the cause, and
applies the fix directly. Priority checks: `\resizebox` wrapping a `backgrounds`-library
tikzpicture, `\\` in a `text centered` node, `\addcontentsline` order. States whether a
two-pass recompilation is needed. Responds in French.

**File:** `.claude/commands/latex.md`

### `/ref <citation>` — Academic reference formatter

Formats and validates references per UQAC / LAR.i rules.

**Accepted publishers:** IEEE, Springer, Elsevier, Taylor & Francis, Cambridge, Wiley, IET,
IOP, ACM, MDPI, ASME, ACME, BioMed Central (BMC). Any other publisher requires professor approval. Provides: full LaTeX
reference, clickable DOI via `\href`, a 0–100 % confidence level with justification, and an
introductory sentence. Never fabricates a reference or DOI.

**File:** `.claude/commands/ref.md`

### `/replyreviewer` — Peer reviewer response generator

Generates a formal LaTeX response letter per reviewer comment file and applies track-change
markup directly in the paper using the `changes` package. The reviewer ID (`id=RN`) in each
`\added`, `\replaced`, or `\deleted` command is the permanent, visible link between the paper
modification and the response letter. Delegates to the `reviewer-response` agent.

**Full command syntax:**

```
/replyreviewer --paper <paper.tex> --reviewers <r1.txt> [r2.txt ...] [--title "Title"] [--editor "Name"]
```

Example:
```
/replyreviewer --paper sn-article.tex --reviewers .\reviewers\R1.txt .\reviewers\R2.txt --editor "Zhouping Yin"
```

| Argument | Required | Description |
|---|---|---|
| `--paper <path.tex>` | Yes | Path to the original LaTeX paper |
| `--reviewers <files>` | Yes | One `.txt` file per reviewer; first = R1, second = R2, etc. |
| `--title "..."` | No | Paper title for the letter header; extracted from `\title{}` if omitted |
| `--editor "..."` | No | Editor name for the salutation; defaults to `[EDITOR NAME]` if omitted |

**What the agent produces:**

1. **One LaTeX response letter per reviewer** — `<basename>_response_R<N>.tex`, each with a
   formal opening, General Comments, point-by-point Specific Comments, and a Scopus-validated
   References Added section with clickable DOIs.
2. **Annotated original paper** — `\added[id=RN]{}` / `\replaced[id=RN]{}{}` / `\deleted[id=RN]{}`
   markup, grammar-only fixes applied directly, and `\usepackage{changes}` with one
   `\definechangesauthor` per reviewer (R1 blue, R2 red, R3 orange, R4+ purple) added to the
   preamble automatically.

**Comment categories processed:**

| Code | Category | Paper change |
|---|---|---|
| G | Grammar / spelling | Direct fix, no markup |
| S | Style / writing | `\replaced[id=RN]{new}{old}` |
| SC | Scientific issue | `\added[id=RN]{...}` |
| M | Methodology addition | `\added[id=RN]{...}` |
| R | Results addition | `\added[id=RN]{...}` |
| D | Discussion addition | `\added[id=RN]{...}` |
| FT | Figure / table issue | `\added[id=RN]{...}` new float |
| EQ | Equation issue | `\replaced[id=RN]{}{}` or `\deleted[id=RN]{}` |
| REF | Reference suggestion | Scopus-validated, `\added[id=RN]{\cite{}}` |
| Q | General quality | `\added[id=RN]{...}` |
| MAJ | Major revision | `\replaced[id=RN]{}{}` / `\deleted[id=RN]{}` |

**Prerequisites:** `SCOPUS_API_KEY` set; campus network or VPN active.

**Related commands:** `/auditpaper` (full audit before/after revision), `/bibclean`
(clean the `.bib` after adding references), `/ref` (format individual references).

**File:** `.claude/commands/replyreviewer.md`

---

## Agents

Agents are specialists Claude delegates to automatically based on context, or explicitly on
request ("use the `scopus-auditor` agent to…"). Fifteen ship in this repo; most back a slash
command. Two of them (`local-writer`, `local-coder`) are local-delegation agents: a cheap
cloud wrapper that drives a local Ollama model over a Bash bridge (see "Local delegation").
Two are loop orchestrators: `authoring-loop` (ScholarEval-gated writing loop) and the
code loop in the `loop-engineer` skill (see "Loop engineering").

Format (repo convention): one flat markdown file per agent at `.claude/agents/<name>.md`,
opening with YAML frontmatter (`name:`, `description:`). This is what Claude Code's subagent
discovery scans; a sub-folder layout is invisible to it. Note the asymmetry with skills,
which ARE folder-based (`skills/<name>/SKILL.md`). The canonical `.claude/agents/` files are
the single source of truth; per-tool mirrors are generated from them (see
"Using the agents outside Claude Code" below).

| Agent | Purpose | Command / trigger | Path |
| --- | --- | --- | --- |
| `scopus-researcher` | Autonomous literature review: search, validate, summarize, PRISMA + gap/coverage/Pareto matrices, hypotheses, LaTeX output | `/litreview` | `.claude/agents/scopus-researcher.md` |
| `scopus-auditor` | Audit an existing review; validate every reference; executable improvement plan | `/auditreview` | `.claude/agents/scopus-auditor.md` |
| `paper-auditor` | Full paper content audit (intro→future works) + Scopus validation + ScholarEval score + improvement plan | `/auditpaper` | `.claude/agents/paper-auditor.md` |
| `thesis-auditor` | Full UQAC thesis audit (front matter, hypothesis flow, chapter structure, bilingual consistency, UQAC compliance) + ScholarEval score | `/auditthesis` | `.claude/agents/thesis-auditor.md` |
| `thesis-proposal-auditor` | Audit a UQAC thesis **proposal** (≤35 pages body, testable hypotheses, suggested methodology, no full results) + ScholarEval score | thesis-proposal audit / by name | `.claude/agents/thesis-proposal-auditor.md` |
| `reviewer-response` | Point-by-point response letters + traceable `changes`-package markup in the paper | `/replyreviewer` | `.claude/agents/reviewer-response.md` |
| `bib-cleaner` | Validate, deduplicate, normalize and DOI-enrich a `.bib` file | `/bibclean` | `.claude/agents/bib-cleaner.md` |
| `submit-checker` | Pass/fail submission checklist against a target journal's requirements | `/submitcheck` | `.claude/agents/submit-checker.md` |
| `word-to-latex` | Faithful Word `.docx` → LaTeX conversion (pandoc + visual-fidelity patches) | `/word2latex` | `.claude/agents/word-to-latex.md` |
| `cover-paper` | Submission package: hidden Cover Letter in source, standalone Title Page PDF, Corresponding Author Profile PDF (recent papers from Scopus), Graphical Abstract via Canva MCP from the paper's figures (Elsevier/Springer spec + FigureLabs prompt) | by name (at submission) | `.claude/agents/cover-paper.md` |
| `thesis-to-paper` | Integrate a thesis + its conference papers into one submission-ready journal manuscript (invited extension); pandoc reference conversion, figure pipeline, content-delta matrix, then `/litreview` + `scientific-writing` + `/bibclean` + `/submitcheck` + `/auditpaper` inline, with a multi-session checkpoint protocol | by name / "extend this paper to a journal version" | `.claude/agents/thesis-to-paper.md` |
| `authoring-loop` | ScholarEval-gated authoring loop: define subject -> author (Fable 5) -> audit with `scholar-evaluation` (Sonnet/Haiku) -> loop to `min_score` or `max_budget` -> record learnings to memory via `local-writer`. Authoring counterpart of the `loop-engineer` code loop | by name / "improve this to a ScholarEval target under a budget" | `.claude/agents/authoring-loop.md` |
| `latex-writer` | Bilingual LaTeX authoring: papers (IEEE/Springer/Elsevier), Beamer slides, TiKZ diagrams, thesis | by context (writing) | `.claude/agents/latex-writer.md` |
| `local-writer` | High-token repetitive writing (docstrings, comments, Markdown docs, Obsidian summaries) via local `ornith:9b` over a Bash bridge; NOT LaTeX text authoring | by context / by name | `.claude/agents/local-writer.md` |
| `local-coder` | Local code generation against a spec/failing test, refactor snippets, scaffolds via local `qwen3.5:9b` over a Bash bridge; no state-changing git | by context / by name | `.claude/agents/local-coder.md` |

The four ScholarEval auditors (`scopus-auditor`, `paper-auditor`, `thesis-auditor`,
`thesis-proposal-auditor`) score the document before writing the plan; after the plan is
executed they re-run the scoring on the revised source and report a before/after ScholarEval
comparison (baseline vs post), hard-gated so execution only completes when the score improves.

### `latex-writer` key rules

- TiKZ: relative positioning only (drawio2tikz-converted figures are the sanctioned absolute-coordinate exception); arrows perpendicular; no overlaps
- References: peer-reviewed only (IEEE, Springer, Elsevier, Taylor & Francis, Cambridge, Wiley, IET, IOP, ACM, MDPI, ASME, ACME, BioMed Central (BMC)); DOI via hyperref; any other publisher needs user confirmation
- Tables: rows = parameters, cols = concepts; bold headers; 10 % grey row shading
- Language: French default for UQAC thesis, English for scientific papers
- Avoid AI-detectable patterns: zero-width spaces, smart quotes, em dashes, perfect parallel lists

### `reviewer-response` key rules

- Reviewer files assigned sequentially: first file = R1, second = R2, etc.
- Grammar-only fixes (G): applied directly, no markup
- Additions `\added[id=RN]{}`, deletions `\deleted[id=RN]{}`, rewrites `\replaced[id=RN]{}{}` (changes package)
- Reviewer colors: R1 blue, R2 red, R3 orange, R4+ purple (`\definechangesauthor`)
- Every proposed reference validated via Scopus; `[NO DOI]` flagged in the summary when applicable

### Local delegation (Ollama subagents)

`local-writer` and `local-coder` cut cloud cost by keeping the top model as orchestrator and
pushing token-heavy generation to local models on the GPU. Each agent runs on a cheap cloud
model (Haiku) that only frames the task and drives a local model over a Bash bridge
(`ollama run ornith:9b` for writing, `ollama run qwen3.5:9b` for code); the bulk text or code
is generated locally and free. No gateway is used and cloud stays on your normal
subscription auth, so only the small Haiku wrapper spends cloud tokens.

Requirements: Ollama running with the two models pulled (`ollama list`). Until the 9B models
are imported, the bridge falls back to `qwen2.5-coder:7b`. LiteLLM
(`~/.litellm/ollama.yaml`) is optional and only gives the bridge its keep-alive / context
tuning. `local-writer` never authors LaTeX prose (it may add `%` comments only); all
scientific and LaTeX redaction stays with `latex-writer` + `scientific-writing` on the
latest cloud Claude model.

### Loop engineering (local-model dev loop)

The `loop-engineer` skill runs a budget-bounded develop-and-improve loop: design → plan →
code → comment → test → review → score → correct, repeating until a composite quality gate
is met or a hard budget cap is hit. It keeps the best cloud model (Fable 5) as
orchestrator/judge, uses cheaper cloud tiers (Opus for plans, Sonnet for execution and
review) for the actions, and delegates code and comments to the local `local-coder` /
`local-writer` agents so the heavy generation is free.

Option contract: `--loop --budget <max_usd> --score <min_score> [--max-iters N]`. The default
stop gate is composite: tests green AND no CRITICAL/HIGH review findings AND aggregate score
`>=` min_score (default 90); a literal 100 is opt-in. The loop also stops on the hard budget
cap, the max-iterations cap, or a no-progress plateau. The score aggregates findings from the
installed reviewers (`/code-review`, `/security-guidance`, `pr-review-toolkit`,
`systematic-debugging`) plus the betterleaks / pip-audit hooks, with security as a hard floor
(any CRITICAL fails the gate regardless of the aggregate). The final merge to a protected
branch is human-gated: the loop stops at "ready to merge" and waits for your confirmation.
The loop diagram and the use-case diagram are in [Architecture.md](Architecture.md)
("Layer 5 — Loop engineering").

The same loop applies to writing through the `authoring-loop` agent (the ScholarEval-gated
variant): define a subject, author with an authoring agent (`/litreview`, `latex-writer`,
`/replyreviewer`, …) on Fable 5, audit with the `scholar-evaluation` skill on Sonnet or Haiku
to get a score, loop until the ScholarEval target or the budget is reached, then record the
learnings to memory via `local-writer`. The five steps are documented in the loop-engineer
[SKILL.md](.claude/skills/loop-engineer/SKILL.md).

### Calling an agent explicitly

Agents are normally triggered automatically by context. To invoke one directly, address it
by name in your message:

```
Use the scopus-auditor agent to audit the review in paper_review/literature_review.tex
```

```
reviewer-response agent: --paper sn-article.tex --reviewers r1.txt --editor "Prof. Yin"
```

The slash commands `/auditreview`, `/replyreviewer`, `/litreview`, etc. are thin wrappers that
call these agents with the same argument syntax — use the commands for convenience and the
explicit agent names when you need finer control or want to chain agents in one message.

### Using the agents outside Claude Code

`install.ps1` regenerates per-tool mirrors from the canonical `.claude/agents/*.md`
files. Run it after adding or editing an agent, then commit the regenerated output. Add
`-Personal` to also copy the Copilot agent profiles to `~/.copilot/agents/`, which makes
them available to Copilot CLI in every project (re-run after agent edits to refresh).

| Tool | Generated target | Notes |
| --- | --- | --- |
| GitHub Copilot (agents) | `.github/agents/<name>.agent.md` | Auto-discovered once on the default branch (GitHub.com agents panel, coding agent, VS Code, Copilot CLI `/agent` or `copilot --agent <name>`). Copilot caps agent prompts at 30,000 characters, so the five large agents ship as stubs that read the canonical file first. |
| GitHub Copilot (commands) | `.github/prompts/<name>.prompt.md` | One prompt file per task command (13); invoke as `/<name>` in Copilot Chat. The Claude session modes (`concis`, `slim`, `focus`, `ctx`) are skipped. |
| GitHub Copilot (rules) | `.github/instructions/<name>.instructions.md` | One per `.claude/rules/*.md`, applied to all files (`applyTo: "**"`), plus the master `.github/copilot-instructions.md` (mission, agent routing, skills pointer). |
| GitHub Copilot (skills) | none needed | Skills are plain repo folders (`.claude/skills/<name>/SKILL.md`); Copilot agents read them directly, and the master instructions point there. |
| OpenCode | `.opencode/agent/<name>.md` | Full body, `description` frontmatter. |
| Continue | `.continue/rules/researchtools.md` | One rule pointing at the canonical files and routing table. |
| Aider | `CONVENTIONS.md` | Pointer paragraph (created once, never overwritten). |

For global availability in Claude Code (any working directory), `install-junctions.ps1`
links each `.claude/agents/<name>.md` into `~/.claude/agents/` per file (symlink; hard-link
fallback when Developer Mode is off — re-run after a `git pull` that changes agents).
Skills keep their per-folder junctions.

---

## File Locations Summary

All agents, commands, and skills live under this repository's `.claude/` directory.

```
ResearchTools\
└── .claude\
    ├── agents\                              (15 agents)
    │   ├── scopus-researcher.md       ← /litreview
    │   ├── scopus-auditor.md          ← /auditreview
    │   ├── paper-auditor.md           ← /auditpaper
    │   ├── thesis-auditor.md          ← /auditthesis
    │   ├── thesis-proposal-auditor.md ← thesis-proposal audit
    │   ├── reviewer-response.md       ← /replyreviewer
    │   ├── bib-cleaner.md             ← /bibclean
    │   ├── submit-checker.md          ← /submitcheck
    │   ├── word-to-latex.md           ← /word2latex
    │   ├── cover-paper.md             ← submission package
    │   ├── thesis-to-paper.md         ← thesis + conf papers -> journal manuscript
    │   ├── authoring-loop.md          ← ScholarEval-gated authoring loop
    │   ├── latex-writer.md            ← LaTeX authoring
    │   ├── local-writer.md            ← local docs/comments (ornith:9b bridge)
    │   └── local-coder.md             ← local code gen (qwen3.5:9b bridge)
    ├── commands\                            (19 commands)
    │   ├── concis.md   ├── slim.md    ├── focus.md   ├── ctx.md
    │   ├── tikz.md     ├── test.md    ├── doc.md     ├── latex.md
    │   ├── ref.md      ├── litreview.md             ├── auditreview.md
    │   ├── auditpaper.md               ├── auditthesis.md
    │   ├── bibclean.md ├── submitcheck.md           ├── replyreviewer.md
    │   ├── word2latex.md               ├── geolocalisation.md
    │   └── loopdev.md
    ├── rules\                               (code-style, preferences, security, testing, workflows)
    └── skills\                              (10 skills)
        ├── scopus\
        │   ├── SKILL.md
        │   └── scripts\  (scopus_api.py, semantic_scholar_api.py, download_pdf.py,
        │                  gemini_reviewer.py, github_reviewer.py, gemini_table.py)
        ├── scientific-writing\SKILL.md
        ├── scholar-evaluation\SKILL.md      (+ scripts\calculate_scores.py)
        ├── deliberation\SKILL.md            (+ scripts\deliberate.py)
        ├── extract-statistic\SKILL.md       (+ scripts\extract_text.py [--stats-scan / --section-scan];
        │                  references\statistical-audit-protocol.md, domain-profiles.md)
        ├── extract-futureworks\SKILL.md     (no script; reuses extract_text.py --section-scan;
        │                  references\futureworks-protocol.md, section-cues.md)
        ├── word2latex\SKILL.md              (+ scripts\docx_inspect.py, manuscript_bib.py)
        ├── drawio2tikz\SKILL.md             (+ scripts\drawio2tikz.py;
        │                  references\conversion-rules.md)
        ├── geolocalisation\SKILL.md         (+ scripts\extract_locations.py, generate_geomap.py,
        │                  Test\test_extract_locations.py; references\geocoding-protocol.md;
        │                  data\ Natural Earth gazetteer cache)
        └── loop-engineer\SKILL.md           (+ scripts\loop_engineer.py [Agent SDK driver],
                           loop_audit.py [code-quality scorer], Test\test_loop_audit.py;
                           references\ LOOP/STATE/PROCESS/ledger templates; requirements.txt)
```
