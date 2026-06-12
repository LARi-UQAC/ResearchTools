# Claude Code — Manual

Reference for all skills (slash commands) and agents installed in this workspace.
For a full map of agents, skills, and commands and how they relate to each other,
see [Architecture.md](Architecture.md).

---

## Installation

Follow these steps on any machine after cloning the repository.

### Prerequisites

| Tool | Required for |
|---|---|
| [Claude Code](https://docs.anthropic.com/claude-code) | Running agents and slash commands |
| [Git for Windows](https://git-scm.com/download/win) (includes Git Bash) | Hooks that use `bash` shell |
| [Node.js](https://nodejs.org/) | Caveman-mode hooks (`caveman-activate.js`, etc.) |
| Python 3.x | Security hooks (`betterleaks`, `pip-audit`, `prompt-injection-defender`) |
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

Verify that no `{{placeholder}}` remains after the script completes — it will
report any unreplaced values in the validation step.

### Step 3 — Make agents available globally (optional, recommended)

This step creates directory junctions from `~/.claude/agents/`, `~/.claude/skills/`,
`~/.claude/rules/`, and `~/.claude/commands/` into this repository, so that Claude Code
loads these agents and skills in **every** workspace, not only when you open this folder.

> **Requires Administrator privileges.**

```powershell
# Review what will be created without making changes
.\install-junctions.ps1 -WhatIf

# Apply
.\install-junctions.ps1
```

Because the links point directly into this repository, a `git pull` is all that is
needed to propagate improvements contributed by any collaborator.

### Contributing improvements

Fork the repository, improve an agent or skill on a feature branch, and open a
pull request against `main`. The repository owner reviews and merges; a `git pull`
on their machine immediately updates the linked entries via the junctions.

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

## Skills (Slash Commands)

Skills are invoked with `/skill-name [arguments]` in any Claude Code session.

### `/code-review` — Multi-project code reviewer

Checks bugs, security, style, naming, docstrings, and test coverage against project rules.
Applies `.claude/rules/` automatically based on detected project type (Blazor, Flask, Python ML, React, LaTeX).

| Command | What it reviews |
|---------|----------------|
| `/code-review` | All uncommitted changes (staged + unstaged) |
| `/code-review staged` | Staged changes only |
| `/code-review committed` | Commits not yet on main/master |
| `/code-review main` | Diff vs `main` branch |
| `/code-review <branch>` | Diff vs any branch (e.g. `/code-review origin/dev`) |

Findings are grouped as 🔴 Critical / 🟡 Warning / 🔵 Info with `file:line` references.
Add "fix all issues" to trigger an autonomous fix-then-re-review loop.

**File:** `.claude/commands/code-review.md`

---

### `/frontend-design` — Distinctive frontend UI builder

Creates production-grade web interfaces with strong aesthetic direction.
Avoids generic AI aesthetics (Inter font, purple gradients, centered layouts).

| Command | What it does |
|---------|-------------|
| `/frontend-design` | Build a UI component, page, or app with a bold design direction |

Applies to: HTML/CSS/JS, React, Vue, artifacts, dashboards, landing pages.

**File:** `.claude/skills/frontend-design/SKILL.md`

---

### `/web-artifacts-builder` — Multi-component HTML artifact builder

Builds complex React + shadcn/ui artifacts bundled into a single self-contained HTML file.
Use for artifacts that need state management, routing, or 40+ shadcn/ui components.

| Command | What it does |
|---------|-------------|
| `/web-artifacts-builder` | Initialize, develop, and bundle a React artifact |

**Workflow:** `init-artifact.sh <name>` → develop → `bundle-artifact.sh` → share `bundle.html`

**Stack:** React 18 + TypeScript + Vite + Parcel + Tailwind CSS 3.4.1 + shadcn/ui

> **Prerequisite:** Place `shadcn-components.tar.gz` in `scripts/` before running the init script.
> Download from: https://github.com/anthropics/skills/releases

**Files:**
- `.claude/skills/web-artifacts-builder/SKILL.md`
- `.claude/skills/web-artifacts-builder/scripts/init-artifact.sh`
- `.claude/skills/web-artifacts-builder/scripts/bundle-artifact.sh`

---

### `/pptx` — PowerPoint skill

Handles any `.pptx` file operation: reading, editing, creating from scratch, combining decks, extracting content.

| Command | What it does |
|---------|-------------|
| `/pptx` | Auto-selects workflow based on context |

| Task | Method |
|------|--------|
| Read / extract text | `python -m markitdown presentation.pptx` |
| Edit existing deck | Unpack XML → edit → clean → pack (see `editing.md`) |
| Create from scratch | PptxGenJS (Node.js) — see `pptxgenjs.md` |
| Visual QA | `soffice` → `pdftoppm` → subagent image inspection |

**Triggers on:** "deck", "slides", "presentation", any `.pptx` filename.

> **Prerequisites:** `pip install "markitdown[pptx]" Pillow defusedxml` · `npm install -g pptxgenjs react react-dom react-icons sharp` · LibreOffice · Poppler

**Files:**
- `.claude/skills/pptx/SKILL.md`
- `.claude/skills/pptx/editing.md`
- `.claude/skills/pptx/pptxgenjs.md`
- `.claude/skills/pptx/scripts/` (6 Python scripts)

---

### `/scopus` — Scopus academic search

Searches the Scopus database via the Elsevier REST API. Requires `SCOPUS_API_KEY` env var and an active institutional network connection (campus or VPN).

| Command | What it does |
|---------|-------------|
| `/scopus <topic>` | Search top papers on a topic |
| `/scopus review <topic>` | Structured literature review with inline citations |
| `/scopus validate <DOI or title>` | Confirm a reference exists and return full metadata |
| `/scopus cite <DOI>` | Citation count + full metadata for one paper |
| `/scopus author <name>` | Author h-index and top publications |
| `/scopus journal <name or ISSN>` | Journal SJR quartile, CiteScore, subject areas |

**Prerequisite:** `pip install requests google-genai openai` · Campus network or VPN

**Environment variables (Windows User scope):**

| Variable | Required for | Source |
|---|---|---|
| `SCOPUS_API_KEY` | All `/scopus` and `/auditreview` commands | Elsevier Developer Portal |
| `GEMINI_API_KEY` | Cross-review via Gemini 2.0 Flash (optional) | Google AI Studio |
| `GITHUB_TOKEN` | Cross-review via GitHub Copilot / GPT-4o (optional) | GitHub → Settings → Developer settings → PAT |

**Files:**
- `.claude/skills/scopus/SKILL.md`
- `.claude/skills/scopus/scripts/scopus_api.py`

---

## Workspace Commands

Session-behaviour commands scoped to this workspace. Invoked with `/command-name [arguments]` in the chat.
Files located in `C:\Martin Otis\OutilsLogiciels\.claude\commands\`.

| Command | What it does | Arguments |
|---|---|---|
| `/concis` | Activates concise mode for the rest of the session | No |
| `/focus <topic>` | Scopes the session to one topic only | Yes — topic to focus on |
| `/ctx` | Audits context window pressure (turns, topics, recommendation) | No |
| `/tikz [code]` | Validates TiKZ code against 6 rules (anchoring, arrows, overlaps…) | Optional — code or file |
| `/test [module]` | Runs project tests following `.claude/rules/testing.md` | Optional — specific module/file |
| `/doc <target>` | Generates or updates documentation for a file or function | Yes — file/function to document |
| `/latex [args]` | Diagnoses and fixes LaTeX errors from the `.log` or open file | Optional — specific error |
| `/ref <citation>` | Formats and validates an academic reference (UQAC/LAR.i style) | Yes — reference to format |
| `/litreview <topic>` | Full autonomous literature review: search → validate → synthesize → comparison table → hypotheses + contributions → objectives → context → 15-item novelty checklist | Yes — research topic |
| `/auditreview [file or text]` | Audit an existing review: validate references, flag errors, run 15-item novelty checklist (Section F), produce an executable improvement plan | Optional — file path, pasted text, or leave empty for IDE file |
| `/auditpaper [file or text]` | Audit a complete scientific paper: references, methodology, results, discussion, future works — Scopus validation + cross-review (Gemini + Copilot) + executable improvement plan | Optional — file path, pasted text, or leave empty for IDE file |
| `/bibclean [file.bib]` | Clean and validate a BibTeX file: required fields, author normalization, duplicate detection, DOI enrichment via Scopus, SJR quartile annotation, publisher approval check | Optional — `.bib` file path or IDE file |
| `/submitcheck <file.tex> <journal>` | Check paper submission readiness for a target journal: page count, required sections, reference style, abstract length, keywords, anonymization | Yes — source `.tex` file and journal name |
| `/auditthesis [main.tex or dir]` | Full UQAC thesis audit: front matter, jury, hypothesis flow (H_N across all chapters), chapter structure (sujet amené/posé/divisé), references, figures, equations, acronyms, LLM-style, bilingual résumé/abstract, UQAC formatting — produces executable plan with maturity verdict | Optional — path to `main.tex`, directory, or IDE file |
| `/replyreviewer` | Generate point-by-point LaTeX response letters to peer reviewer comments and apply track-change markup directly in the paper using the `changes` package. The reviewer ID (`id=RN`) in each `\added`, `\replaced`, or `\deleted` command is the permanent link between the paper markup and the response letter. One `.tex` letter per reviewer file. | Yes — see usage below |

---

### `/concis` — Concise mode

Activates for the rest of the session:

- Max 5 sentences for short answers; structured bullets for long answers
- No preamble ("I will…", "Sure…", "Here is…")
- No trailing summary after completing a task
- Code written directly; comments explain WHY only

Responds in French unless the active file is in English.

**File:** `.claude/commands/concis.md`

---

### `/focus <topic>` — Session scope

Restricts the session to a single topic. Everything outside that topic is ignored.

| Command | Effect |
|---|---|
| `/focus authentication flow` | Ignore all files and context unrelated to authentication |
| `/focus step2 perimeter validation` | Scope to Step 2 of Blazer only |

Responds in French unless the active file is in English.

**File:** `.claude/commands/focus.md`

---

### `/ctx` — Context window audit

Reports in under 10 lines:

1. Estimated number of exchange turns in the active window
2. Top 3 topics/files consuming the most context
3. Pressure level: **low / moderate / high**
4. If moderate or high: recommends running `/compact` before the next heavy task

Does not read any additional files — uses only what is already in context. Responds in French.

**File:** `.claude/commands/ctx.md`

---

### `/tikz` — TiKZ validation

Validates TiKZ code (from `$ARGUMENTS` or the file open in the IDE) against 6 rules:

| Rule | What is checked |
|---|---|
| Line breaks in nodes | `align=center` only — never `text centered` |
| backgrounds + scaling | No `\begin{scope}[on background layer]` inside `\resizebox`/`\scalebox` |
| Arrow angles | Arrows must connect perpendicularly to node borders (.north/.south/.east/.west) |
| Overlaps | Min 3-character gap between rectangles; arrow labels must not overlap geometry |
| Anchoring | `positioning` library + `node distance` only — no absolute coordinates |
| TiKZiT compatibility | Named styles in `.tikzstyles`; no exotic libraries |

For each violation: cites the line, explains the cause, provides corrected code directly.

**File:** `.claude/commands/tikz.md`

---

### `/test [module]` — Run project tests

Reads `.claude/rules/testing.md`, selects the correct venv, and runs the tests.

| Command | What it runs |
|---|---|
| `/test` | All tests for the active project |
| `/test test_excel_generator` | Single API test module |
| `/test Test/test_scale_calibrator.py` | Single engine test file |

Reports: **passed / total** — failures listed with short error message and likely cause.

**File:** `.claude/commands/test.md`

---

### `/doc <target>` — Documentation generator

Generates or updates documentation following project conventions from `.claude/rules/code-style.md`.

| Language | What is generated |
|---|---|
| Python | Module docstring (Stage N format) + Purpose/Inputs/Outputs function docstrings |
| C# / Blazor | `/// <summary>` for non-trivial public members + doc file cross-reference |
| LaTeX / Markdown | Equations in `$...$` / `$$...$$`; no redundant headings |

Never documents WHAT — only WHY (hidden constraints, invariants, workarounds).
Responds in French unless the active file is in English.

**File:** `.claude/commands/doc.md`

---

### `/latex` — LaTeX diagnosis and fix

Diagnoses and fixes LaTeX compilation errors from the `.log` file or active IDE file.

Procedure:

1. Reads `out/*.log` first for exact error line numbers
2. Cites the line, explains the cause, applies the fix directly
3. Priority checks: `\resizebox` wrapping a `backgrounds`-library tikzpicture, `\\` in `text centered` node, `\addcontentsline` order
4. States whether a two-pass recompilation is needed

Fixes directly — never asks "would you like me to…". Responds in French.

**File:** `.claude/commands/latex.md`

---

### `/ref <citation>` — Academic reference formatter

Formats and validates academic references per UQAC / LAR.i requirements.

**Accepted publishers:** IEEE, Springer, Elsevier, Taylor & Francis, Cambridge, Wiley, IET, IOP, ACME, MDPI.
Any other publisher requires professor approval before inclusion.

For each reference provides:

1. Full LaTeX reference (BibTeX or natbib)
2. Clickable DOI via `\href{http://doi.org/...}{DOI}`
3. Confidence level (0–100 %) with one-sentence justification
4. Introductory sentence to use in the text

Will not fabricate a reference or invent a DOI.

**File:** `.claude/commands/ref.md`

---

### `/replyreviewer` — Peer reviewer response generator

Generates a formal LaTeX response letter for each reviewer comment file and applies track-change
markup directly in the paper using the `changes` package. The reviewer ID (`id=RN`) in each
`\added`, `\replaced`, or `\deleted` command is the permanent, visible link between the paper
modification and the corresponding item in the response letter. No separate annotation markers
needed. Delegates to the `reviewer-response` agent.

**Full command syntax:**

```
/replyreviewer --paper <paper.tex> --reviewers <r1.txt> [r2.txt ...] [--title "Title"] [--editor "Name"]
```

Exemple:
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

1. **One LaTeX response letter per reviewer** — `<basename>_response_R<N>.tex` alongside the paper. Each letter contains:
   - Formal opening addressed to the editor with the standard thank-you paragraph
   - Section 1.1 General Comments — one paragraph per general remark
   - Section 1.2 Specific Comments — numbered point-by-point: verbatim reviewer comment, then `=>Answer from authors:` response paragraph
   - Section 2 References Added — IEEE-style references with clickable DOI hyperlinks, validated via Scopus

2. **Annotated original paper** — the `.tex` source is updated with:
   - `\added[id=RN]{new text}` for added passages
   - `\replaced[id=RN]{new text}{old text}` for rewritten passages
   - `\deleted[id=RN]{old text}` for removed passages
   - Grammar-only fixes applied directly without markup
   - `\usepackage{changes}` with `\definechangesauthor` for each reviewer (R1 blue, R2 red, R3 orange, R4+ purple) added to the preamble automatically if not already present
   - The colored reviewer-attributed markup in the paper is the direct, visible link to the corresponding item in the response letter

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

**Typical workflow:**

```text
1. Receive reviewer comment files from the journal (save as r1.txt, r2.txt, ...)
2. Run: /replyreviewer --paper mypaper.tex --reviewers r1.txt r2.txt --editor "Prof. Smith"
3. Review the generated _response_R1.tex and _response_R2.tex — edit answers as needed
4. Open the annotated mypaper.tex — each colored `\added`/`\replaced`/`\deleted` shows which reviewer triggered the change
5. Once satisfied, remove `\added{}`/`\deleted{}`/`\replaced{}` markup before final submission
   (use /auditpaper to verify the cleaned paper before submitting)
```

**Prerequisites:** `SCOPUS_API_KEY` env var set; campus network or VPN active.

**Related commands:** `/auditpaper` (full paper audit before/after revision), `/bibclean` (clean the `.bib` file after adding new references), `/ref` (format individual references in IEEE style).

**File:** `.claude/commands/replyreviewer.md`

---

## Agents

Agents are specialists that Claude delegates to automatically based on context, or explicitly on request ("use the blazor-dev agent to…").

### Blazer agents

| Agent | Triggers on | Path |
|-------|-------------|------|
| `blazor-dev` | `.razor` files, JS interop, `LocalizationService`, `ValidationCard`, `ce-*` CSS | `.claude/agents/blazor-dev/AGENT.md` |
| `flask-api` | Flask routes, session management, Excel export, audit logging, API contract | `.claude/agents/flask-api/AGENT.md` |
| `analysis-engine` | Python ML/CV pipeline — EasyOCR, YOLO12, SAM, PyMuPDF, OpenCV | `.claude/agents/analysis-engine/AGENT.md` |


#### `blazor-dev` key rules
- `@rendermode="InteractiveServer"` always; never WASM
- After editing `geometry-interop.js` → increment `?v=N` in `App.razor`
- Element identity via `data-ce-vid`, never the ElementReference object
- All strings via `@L["key"]`; CSS via `ce-*` classes only

#### `flask-api` key rules
- Session IDs: uuid4 only, never user-supplied
- Route entry: validate all required fields → 400 immediately if missing
- File uploads: `secure_filename()` + extension + `%PDF` magic-byte check
- After new route: update `.claude/CLAUDE.md` + `docs/reference/api-endpoints.md`

---

### React-based agents

| Agent | Triggers on | Path |
|-------|-------------|------|
| `react-dev` | React components, Leaflet maps, COLREGS routing, vessel data | `.claude/agents/react-dev/AGENT.md` |

#### `react-dev` key rules
- TypeScript strict mode; no `any`
- TailwindCSS 4 utilities only; Lucide icons
- COLREGS collision avoidance logic in `collisionAvoidance.ts`

---

### Workspace-root agents (all projects)

| Agent | Triggers on | Path |
|-------|-------------|------|
| `latex-writer` | `.tex`, `.tikz`, `.bib`, Beamer slides, academic papers, UQAC thesis | `.claude/agents/latex-writer/AGENT.md` |
| `security-auditor` | New API endpoints, file upload handlers, input validation logic | `.claude/agents/security-auditor/AGENT.md` |
| `scopus-researcher` | Literature review requests, `/litreview` command, Scopus search tasks | `.claude/agents/scopus-researcher/AGENT.md` |
| `scopus-auditor` | Existing review auditing, `/auditreview` command, reference validation + improvement plan | `.claude/agents/scopus-auditor/AGENT.md` |
| `paper-auditor` | Full scientific paper auditing, `/auditpaper` command — methodology, results, discussion, future works + Scopus validation + cross-review | `.claude/agents/paper-auditor/AGENT.md` |
| `reviewer-response` | Peer review response workflow, `/replyreviewer` command — comment classification, point-by-point LaTeX letters, paper corrections with `\added[id=RN]{}`/`\deleted[id=RN]{}`/`\replaced[id=RN]{}{}` (changes package), Scopus reference validation | `.claude/agents/reviewer-response/AGENT.md` |
| `bib-cleaner` | BibTeX file cleaning, `/bibclean` command — required fields, author normalization, duplicates, DOI enrichment, SJR quartile annotation | `.claude/agents/bib-cleaner/AGENT.md` |
| `submit-checker` | Journal submission readiness, `/submitcheck` command — page count, sections, reference style, abstract, keywords, anonymization | `.claude/agents/submit-checker/AGENT.md` |
| `thesis-auditor` | UQAC thesis auditing, `/auditthesis` command — front matter, hypothesis flow, chapter structure, references, figures, LLM-style, bilingual consistency, UQAC compliance, maturity verdict | `.claude/agents/thesis-auditor/AGENT.md` |

#### `latex-writer` key rules
- TiKZ: relative positioning only; arrows perpendicular; no overlaps
- References: IEEE, Springer, Elsevier, Taylor & Francis, Cambridge, Wiley, IET, IOP, MDPI only; DOI via hyperref
- French default for UQAC thesis
- Avoid AI-detectable patterns: zero-width spaces, smart quotes, em dashes, perfect parallel lists

#### `reviewer-response` key rules

- Reviewer files assigned sequentially: first file = R1, second = R2, etc.
- Grammar-only fixes (G category): applied directly — no changes markup
- Additions: `\added[id=RN]{text}`, deletions: `\deleted[id=RN]{text}`, rewrites: `\replaced[id=RN]{new}{old}` (changes package required)
- Reviewer colors (changes package): R1 blue, R2 red, R3 orange, R4+ purple (`\definechangesauthor`)
- Every reference proposed for any comment is validated via Scopus (including DOI): found with DOI = auto-approved, no user confirmation; found without DOI = auto-approved, `[NO DOI]` flagged in summary; not found = removed, alternative searched
- References without a DOI are flagged `[NO DOI]` in the summary report so the user can verify manually
- Response letter language follows the paper's primary language (English for IEEE/Elsevier)

#### `security-auditor` key rules
- Read-only agent; reports findings as `[CRITICAL / HIGH / MEDIUM / LOW] file:line → Fix:`
- Checks: session ID source, `secure_filename`, magic-byte validation, field validation, `_FILE_LOCK` usage, no `shell=True`

---

### Calling an agent explicitly

Agents are normally triggered automatically by context. To invoke one directly, address it by name in your message. The examples below use `scopus-auditor` and `reviewer-response`, but the same pattern works for any agent.

#### `scopus-auditor` — explicit call examples

```
Use the scopus-auditor agent to audit the review in paper_review/literature_review.tex
```

```
Ask the scopus-auditor to validate all references in sn-article.tex and produce an improvement plan.
```

```
scopus-auditor: check the .bib file at paper_review/refs.bib — flag any DOI mismatches and low-confidence citations.
```

What the agent receives as `$ARGUMENTS`: the path(s) or text you provide after the agent name. It reads the file, runs Scopus validation on every reference, assigns confidence levels (`[HIGH/MEDIUM/LOW CONFIDENCE]`) with a one-sentence justification written as a LaTeX comment after each `.bib` entry, flags `[REFERENCE NOT INTRODUCED]` for bare citations, and saves an improvement plan as `<basename>_improvement_plan.md`.

#### `reviewer-response` — explicit call examples

```
Use the reviewer-response agent with --paper paper_review/sn-article.tex --reviewers paper_review/r1.txt paper_review/r2.txt --editor "Prof. Smith"
```

```
reviewer-response agent: --paper sn-article.tex --reviewers r1.txt --title "Framework for Behavior-Based Robot Teleoperation" --editor "Prof. Yin"
```

What the agent receives as `$ARGUMENTS`: the named flags above. It parses the reviewer files, drafts point-by-point responses, applies `\added[id=RN]{}` / `\replaced[id=RN]{}{}` / `\deleted[id=RN]{}` corrections directly in the paper, validates every proposed reference via Scopus (confidence comment added after each `\bibitem`), and writes one `<basename>_response_R<N>.tex` letter per reviewer.

**Tip:** the slash commands `/auditreview` and `/replyreviewer` are thin wrappers that call these agents with the same argument syntax — use the commands for convenience and the explicit agent names when you need finer control over the arguments or want to chain agents in one message.

---

## File Locations Summary

All agents, commands, and skills are consolidated in one location.

```
C:\Martin Otis\OutilsLogiciels\
└── .claude\
    ├── agents\                           (14 agents total)
    │   ├── latex-writer\AGENT.md
    │   ├── security-auditor\AGENT.md
    │   ├── scopus-researcher\AGENT.md    ← /litreview
    │   ├── scopus-auditor\AGENT.md       ← /auditreview
    │   ├── paper-auditor\AGENT.md        ← /auditpaper
    │   ├── reviewer-response\AGENT.md    ← /replyreviewer
    │   ├── bib-cleaner\AGENT.md          ← /bibclean
    │   ├── submit-checker\AGENT.md       ← /submitcheck
    │   ├── thesis-auditor\AGENT.md       ← /auditthesis
    │   ├── blazor-dev\AGENT.md           ← Blazer frontend
    │   ├── flask-api\AGENT.md            ← Flask API
    │   ├── analysis-engine\AGENT.md      ← ML pipeline
    │   ├── cost-tester\AGENT.md          ← tests
    │   └── react-dev\AGENT.md            ← React frontend
    ├── commands\                          (17 commands total)
    │   ├── concis.md
    │   ├── focus.md
    │   ├── ctx.md
    │   ├── tikz.md
    │   ├── test.md
    │   ├── doc.md
    │   ├── latex.md
    │   ├── ref.md
    │   ├── code-review.md
    │   ├── slim.md
    │   ├── litreview.md
    │   ├── auditreview.md
    │   ├── auditpaper.md
    │   ├── bibclean.md
    │   ├── submitcheck.md
    │   ├── auditthesis.md
    │   └── replyreviewer.md
    └── skills\
        ├── frontend-design\SKILL.md
        ├── web-artifacts-builder\
        │   ├── SKILL.md
        │   └── scripts\  (init-artifact.sh, bundle-artifact.sh)
        ├── pptx\
        │   ├── SKILL.md
        │   ├── editing.md
        │   ├── pptxgenjs.md
        │   └── scripts\  (add_slide.py, clean.py, thumbnail.py, office/)
        └── scopus\
            ├── SKILL.md
            └── scripts\
                ├── scopus_api.py        ← Scopus REST API client
                ├── gemini_reviewer.py   ← Gemini 2.0 Flash cross-reviewer
                └── github_reviewer.py   ← GPT-4o via GitHub Models cross-reviewer
```
