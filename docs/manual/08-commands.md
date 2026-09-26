# Commands (Slash Commands)

Chapter 08 of the ResearchTools manual. Back to [table of contents](../../README.md).

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
| `/litupdate <review.tex>` | Incrementally update an existing review with new papers: windowed search → delta dedup → validate/grade → preemption check (deliberation + scholar-evaluation) → dated `\added{}` copy `_up_YYYYMMDD.tex` + CHANGELOG. Schedulable (draft + REVIEW REQUIRED when unattended) | Yes — existing review `.tex` |
| `/auditreview [file or text]` | Audit an existing review: validate references, flag errors, novelty checklist, executable improvement plan | Optional — file/text/IDE file |
| `/auditpaper [file or text]` | Audit a complete paper: references, methodology, results, discussion, future works — Scopus validation + cross-review + improvement plan | Optional — file/text/IDE file |
| `/auditthesis [main.tex or dir]` | Full UQAC thesis audit: front matter, jury, hypothesis flow, chapter structure, references, figures, equations, acronyms, LLM-style, bilingual résumé/abstract, UQAC formatting | Optional — path/dir/IDE file |
| `/bibclean [file.bib]` | Clean and validate a BibTeX file: required fields, author normalization, duplicates, DOI enrichment, SJR quartile, publisher approval check | Optional — `.bib` file/IDE file |
| `/submitcheck <file.tex> <journal>` | Check submission readiness for a target journal: page count, sections, reference style, abstract length, keywords, anonymization | Yes — `.tex` file + journal |
| `/replyreviewer` | Point-by-point LaTeX response letters + track-change markup in the paper via the `changes` package (one letter per reviewer file) | Yes — see below |
| `/talk <paper>` | Accepted paper → conference talk: six opening questions (audience, duration, target, aspect, PDF format, ending), build contract, one deck model rendered to PowerPoint / Beamer / self-contained web, timed speaker notes at 130 wpm, visual QA loop | Yes — paper path + optional flags |
| `/word2latex` | Convert a Word `.docx` template to a faithful LaTeX source (pandoc + standard patch sequence) | Yes — `.docx` path |
| `/fetchform <https-url> [dest]` | Fetch one official PDF form (any institution), validated, and report its SHA-256. Refuses anything that is not a PDF served over https, and writes nothing when it refuses | Yes |
| `/geolocalisation` | Map a review corpus's study locations from its `.bib`: draft study-location table (confidence + per-paper provenance), human review, then CSV/KML/GeoJSON/PNG/HTML + per-country count. Optional `--full-text` PDF scan. | Optional — `.bib` file/dir/IDE file |
| `/recommendation-letter` | Generate a support / recommendation / appreciation / acceptance / dispense letter in LaTeX → PDF from a candidate's files (two tracks; candidate status + funding provider; paired invitation). | Optional — folder / paths / IDE file |
| `/cv` | Draft, refresh, or tailor the narrative CV-FRQ / tri-agency CV to one grant competition via the `narrative-cv-writer` agent: durable master contributions inventory, ranked by keyword overlap against the competition's own objectives, drafted through `scientific-writing`, rendered to LaTeX/PDF + plain text. `--refresh-only` updates the inventory with no draft produced. | Yes — competition + objectives text/path + language + portal variant |
| `/rt-dashboard` | Start the rt-observe dashboard on loopback and open it: mirror matrix, fan-out canvas, plan progression, services and sessions. Wraps `rt-dashboard.ps1` / `.sh` / `.bat`, which need no Claude Code. `--dry-run` names the interpreter, the bind address and every TTL and starts nothing | Optional — `--dry-run`, `--open`, `--port <n>`, `--json` |
| `/abstract [paper.tex]` | Extract a paper's own content and draft (or refresh) its abstract, grounded in its own contribution/method/results/limitations rather than a paraphrase; for a UQAC thesis, drafts the Résumé (French) + Abstract (English) pair from the same extraction. Confirms before overwriting existing content | Optional — `.tex` path/IDE file |

Full detail for `/rt-dashboard`: see [07-rt-observe-dashboard.md](07-rt-observe-dashboard.md).

## `/concis` — Concise mode

Activates for the rest of the session: max 5 sentences for short answers, structured
bullets for long answers, no preamble, no trailing summary, code written directly with
WHY-only comments. Responds in French unless the active file is in English.

**File:** `.claude/commands/concis.md`

## `/focus <topic>` — Session scope

Restricts the session to a single topic; everything outside it is ignored. Responds in
French unless the active file is in English.

**File:** `.claude/commands/focus.md`

## `/ctx` — Context window audit

Reports, in under 10 lines: estimated exchange turns, top 3 context-consuming topics/files,
a low/moderate/high pressure level, and a `/compact` recommendation when needed. Reads no
additional files. Responds in French.

**File:** `.claude/commands/ctx.md`

## `/tikz` — TiKZ validation

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

## `/test [module]` — Run project tests

Reads `.claude/rules/testing.md`, selects the correct venv, runs the tests, and reports
**passed / total** with short error messages and likely causes.

**File:** `.claude/commands/test.md`

## `/doc <target>` — Documentation generator

Generates documentation following `.claude/rules/code-style.md` (Python Stage-N module +
Purpose/Inputs/Outputs docstrings; C# `/// <summary>`; LaTeX/Markdown equation formatting).
Documents WHY, not WHAT. Responds in French unless the active file is in English.

**File:** `.claude/commands/doc.md`

## `/latex` — LaTeX diagnosis and fix

Reads `out/*.log` first for exact error lines, cites the line, explains the cause, and
applies the fix directly. Priority checks: `\resizebox` wrapping a `backgrounds`-library
tikzpicture, `\\` in a `text centered` node, `\addcontentsline` order. States whether a
two-pass recompilation is needed. Responds in French.

**File:** `.claude/commands/latex.md`

## `/ref <citation>` — Academic reference formatter

Formats and validates references per UQAC / LAR.i rules.

**Accepted publishers:** IEEE, Springer, Elsevier, Taylor & Francis, Cambridge, Wiley, IET,
IOP, ACM, MDPI, ASME, ACME, BioMed Central (BMC). Any other publisher requires professor approval. Provides: full LaTeX
reference, clickable DOI via `\href`, a 0–100 % confidence level with justification, and an
introductory sentence. Never fabricates a reference or DOI.

**File:** `.claude/commands/ref.md`

## `/replyreviewer` — Peer reviewer response generator

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
