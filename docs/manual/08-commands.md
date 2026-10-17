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
| `/texcheck [subcommand] [files]` | Measures LaTeX manuscript hygiene via `latex-hygiene`: forbidden characters, AI-usage risk score, prose/accepted word counts, abstract length, brace balance, `changes`-argument corruption, cite-key coverage. Also applies a machine-readable audit plan (`patch`), scans for post-write corruption (`scan`), and resolves/builds the tracked or accepted PDF (`accept`, `build`). Measures only — a found defect goes to `latex-writer`/`/auditpaper` to fix | Optional — one subcommand (`chars`/`aiscan`/`wc`/`abstract`/`braces`/`par`/`citecov`/`patch`/`scan`/`accept`/`build`) + files, or none for `all` |
| `/ref <citation>` | Formats and validates an academic reference (UQAC/LAR.i style) | Yes — reference |
| `/litreview <topic>` | Full autonomous literature review: search → validate → synthesize → comparison table → hypotheses + contributions → objectives → context → novelty checklist | Yes — research topic |
| `/litupdate <review.tex>` | Incrementally update an existing review with new papers: windowed search → delta dedup → validate/grade → preemption check (deliberation + scholar-evaluation) → dated `\added{}` copy `_up_YYYYMMDD.tex` + CHANGELOG. Schedulable (draft + REVIEW REQUIRED when unattended) | Yes — existing review `.tex` |
| `/auditreview [file or text]` | Audit an existing review: validate references, flag errors, novelty checklist, executable improvement plan | Optional — file/text/IDE file |
| `/auditpaper [file or text]` | Audit a complete paper: references, methodology, results, discussion, future works — Scopus validation + cross-review + improvement plan | Optional — file/text/IDE file |
| `/auditthesis [main.tex or dir]` | Full UQAC thesis audit: front matter, jury, hypothesis flow, chapter structure, references, figures, equations, acronyms, LLM-style, bilingual résumé/abstract, UQAC formatting | Optional — path/dir/IDE file |
| `/bibclean [file.bib]` | Clean and validate a BibTeX file: required fields, author normalization, duplicates, DOI enrichment, SJR quartile, publisher approval check | Optional — `.bib` file/IDE file |
| `/submitcheck <file.tex> <journal>` | Check submission readiness for a target journal: page count, sections, reference style, abstract length, keywords, anonymization | Yes — `.tex` file + journal |
| `/replyreviewer` | Point-by-point LaTeX response letters + track-change markup in the paper via the `changes` package (one letter per reviewer file) | Yes — see below |
| `/loopdev [--score N] [--no-merge-pr] "<feature request>"` | A procedure the session follows through the `loop-engineer` skill: ask the owner the review bounds, declare them with `loop_bounds.py init`, run design → plan → code → comment → test → review → score → correct, record each round with `tick`, and stop at the composite gate (tests green, no CRITICAL/HIGH, aggregate ≥ `--score`, default 90) or at the first bound reached. The driver flag `--loop` is not wired. On a gate pass, pushes the branch and opens a PR (unless `--no-merge-pr`) — the merge to a protected branch stays human-gated | Optional `--score`, `--no-merge-pr`; the bounds are asked, not passed |
| `/opt-local-vram-llm <base-tag> --role <writer\|coder>` | Tunes a local Ollama model for this GPU: sweeps `num_ctx` against the KV cache type, applies the admissible/fast-enough/largest-window objective, declares the tuned tag as a role candidate. Restarts the Ollama daemon once per KV cache type during the sweep. Stops before adoption — prints the `model_resolver.py --qualify` command and never runs it, since adopting changes what every local agent executes | Yes — base tag + `--role`; optional `--throughput-floor`, `--kv`, `--keep-vision`, `--dry-run` |
| `/talk <paper>` | Accepted paper → conference talk: six opening questions (audience, duration, target, aspect, PDF format, ending), build contract, one deck model rendered to PowerPoint / Beamer / self-contained web, timed speaker notes at 130 wpm, visual QA loop | Yes — paper path + optional flags |
| `/word2latex` | Convert a Word `.docx` template to a faithful LaTeX source (pandoc + standard patch sequence) | Yes — `.docx` path |
| `/pdf2md run <pdf> -o <dir>` | Convert a PDF with no LaTeX source into markdown for `thesis-auditor`'s content checks. `run` is a DRY RUN without `--yes` (reports the bootstrap plan, launches nothing; a failed bootstrap stops it). Two output layouts via `postprocess --layout thesis\|single`: `thesis` (default) makes `<dir>` play the role of a project's `src/` — `<dir>/main.md` linking everything, `<dir>/content/*.md` (`Introduction.md`/`chapitreN.md`/`Conclusion.md`), `<dir>/assets/*.md` (`bibliography.md`, `ref.md`) and `<dir>/assets/figures/`; `single` keeps an article or a talk source as ONE `main.md` plus `assets/bibliography.md` — `repair`, `fix`, and `validate --vlm-check` refuse a single layout (exit 2), `validate` and `--fidelity` accept it. Not auto-discovered by `thesis-auditor`'s own directory resolution, which needs a real `main.tex` and `\input{}`/`\include{}` macros. Bootstraps `mineru`/`mineru-llama-cpp` (pinned versions, settings in `pdf2md-pipeline.json`)/model/config, starts the VLM server directly (bypassing a Windows-broken `mineru-kit vlm-server`) with a real `--image-min-tokens` accuracy fix, runs the conversion, strips the running-header splice defect, restructures the bibliography BibTeX-like, then validates against an independent second PDF reader chapter by chapter (words/sections/tables/figures/citations/rough-equation-estimate), with `--fidelity` (content check: lost headings, missing or reordered paragraphs, embedded images) and `--vlm-check` (a local vision model, loopback-only `base_url`, verifies the formulas of math-heavy pages), then a `repair` stage (dry run unless `--yes`, originals backed up) for what can be fixed mechanically, and a `fix --model TAG` stage (bounded loop with a local vision model, `--yes` to write) that recovers only LOST numbered equations by default — `--rewrite-formulas` opts in to also rewrite a formula whose meaning may be wrong, since a measured run once changed the meaning of an already-correct one | Yes — PDF path + `-o <dir>`; optional `--tier`, `--port`, `--yes`, `--layout thesis\|single` |
| `/fetchform <https-url> [dest]` | Fetch one official PDF form (any institution), validated, and report its SHA-256. Refuses anything that is not a PDF served over https, and writes nothing when it refuses | Yes |
| `/geolocalisation` | Map a review corpus's study locations from its `.bib`: draft study-location table (confidence + per-paper provenance), human review, then CSV/KML/GeoJSON/PNG/HTML + per-country count. Optional `--full-text` PDF scan. | Optional — `.bib` file/dir/IDE file |
| `/recommendation-letter` | Generate a support / recommendation / appreciation / acceptance / dispense letter in LaTeX → PDF from a candidate's files (two tracks; candidate status + funding provider; paired invitation). | Optional — folder / paths / IDE file |
| `/cv` | Draft, refresh, or tailor the narrative CV-FRQ / tri-agency CV to one grant competition via the `narrative-cv-writer` agent: durable master contributions inventory, ranked by keyword overlap against the competition's own objectives, drafted through `scientific-writing`, rendered to LaTeX/PDF + plain text. `--refresh-only` updates the inventory with no draft produced. | Yes — competition + objectives text/path + language + portal variant |
| `/rt-dashboard` | Start the rt-observe dashboard on loopback and open it: mirror matrix, fan-out canvas, plan progression, services and sessions. Wraps `rt-dashboard.ps1` / `.sh` / `.bat`, which need no Claude Code. `--dry-run` names the interpreter, the bind address and every TTL and starts nothing | Optional — `--dry-run`, `--open`, `--port <n>`, `--json` |
| `/opt-local-stt-vram` | Score speech-to-text models for this GPU beside the resident local LLM and print one selection table: word error against your own reference words, live-caption speed, dedicated VRAM, and how much of the LLM each pushes out of VRAM (a gate). Downloads the models, one fresh process each; `--dry-run` writes nothing, `--rescore` recomputes a saved run. Never edits the voice panel's config | Yes — `--reference <folder>/reference.txt --out <dir>`; optional `--model NAME:COMPUTE ...`, `--language`, `--dry-run`, `--rescore`, `--json` |
| `/abstract [paper.tex]` | Extract a paper's own content and draft (or refresh) its abstract, grounded in its own contribution/method/results/limitations rather than a paraphrase; for a UQAC thesis, drafts the Résumé (French) + Abstract (English) pair from the same extraction. Confirms before overwriting existing content | Optional — `.tex` path/IDE file |
| `/expertfinder` | Find university professors closest to a set of expertise keywords in a user-supplied location via the `professor-expertise-finder` agent: reuses or builds a verified department/faculty-list table, ranks professors with a /5 rubric grounded in Scopus-verified recent articles (`scopus` + `extract-contributions`), and supports test mode, an exclusion list, an optional reviewers reference file, and a batch allocation mode (no-reuse, one-university-per-evaluator, conflict-of-interest) | Optional — location + keywords, or `--test`/`--exclude`/`--reference`/`--batch` flags |
| `/portfolio` | One-shot migration of a researcher's final CIHR / Canadian Common CV XML export into their WordPress portfolio via the `wp-portfolio-agent` agent: parse, discover WP pages (first run only), preview and pause for approval, dry-run the push, push for real only after explicit approval, verify the public pages. No student data is ever read from the XML | Yes — CV XML path + `--data-dir` (outside the repository) |

<!-- local-coding:begin -->
A review started by hand is guarded too: `review-loop-guard.py` refuses a review skill until `loop_bounds.py init` has declared the bounds (`--max-rounds 1` is the one-shot). The full process, the plan header and the choice of executor are in [chapter 12](12-local-coding.md).
<!-- local-coding:end -->

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

---
[← 07 rt-observe & dashboard](07-rt-observe-dashboard.md) | [Table of contents](../../README.md) | [09 ThesisTracker integration →](09-thesistracker-integration.md)
