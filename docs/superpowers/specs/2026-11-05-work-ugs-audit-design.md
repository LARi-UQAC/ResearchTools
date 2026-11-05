# work-ugs-audit - local undergraduate report grading, and one language skill

Date: 2026-11-05. Issue: #104. Branch: `feat/work-ugs-audit`.
Status: draft for the owner's approval. Calls made by the session, not the owner, are marked
**[session call]**; everything else was stated by the owner on 2026-11-05.

## 1. Intent

The professor grades undergraduate lab and project reports that students submit on Moodle as PDF files
(4 to 88 pages, many technical figures and tables, always with a text layer: measured 2026-11-05 on 14
real reports from two courses). Grading is slow, and the toolkit has nothing for coursework: every
auditor targets research writing, Scopus references and LaTeX sources.

The new agent `work-ugs-audit` produces a **draft** that the professor then reviews line by line. Each
student PDF comes back annotated in place, with the completed rubric appended at the end, a score per
rubric item and a total computed by a script. A batch analysis compares the class with the expected grade
distribution and proposes options. The professor uploads the final PDFs to Moodle himself.

**Everything that reads a report runs on this computer.** The grading reproduces the mechanics of the
`aider-setup` pipeline (one model produces, a second model audits and never edits, state kept in
`progress.md`, the specification in `spec.md`), but inside a subagent wrapper like `local-coder`, so that
no report, no extract of it and no model output about it ever leaves the machine.

The same effort gathers language correction, today duplicated across five agents, into one skill.

## 2. Goals

1. Normalize the professor's rubric into `spec.md` (human-readable) plus `rubric.json` (machine
   form). `spec.md` is the grading equivalent of the aider specification. The professor confirms it once
   before any report is graded.
2. Grade each report locally with **one** grader model; a second local model **audits** each grade and
   never edits it (aider-setup's writer/reviewer split). For every rubric item: a score, a status, a
   short comment and the evidence (page, quoted passage).
3. Judge every figure separately (section 7.4).
4. Annotate the student PDF natively (highlight plus pop-up note anchored on the quoted passage, or on a
   figure's rectangle) for technical, figure, language and reference remarks.
5. Append the completed rubric to the PDF as extra pages.
6. Compute every total, percentage and statistic in Python, never in a model.
7. Analyse the batch against the calibration band and propose options to the professor at the end.
8. When the batch leaves the band, re-grade **all** reports with a recalibrated scale. At most two loops,
   counted by a script; then ask the professor whether a third is wanted.
9. Validate references at the undergraduate level: ISO/CSA/IEC standards, datasheets and web pages are
   acceptable, still checked.
10. One language skill (language only), used by this agent and by the five research agents, which are
    migrated to it in this effort.
11. Ready-to-use templates in the skills' `assets/`: rubric, `spec.md`, `progress.md`, grade sheet,
    figure analysis JSON, completed-rubric annex, language correction table, batch report, calibration
    targets.

## 3. Non-goals

- Uploading to or downloading from Moodle.
- Converting the PDF to Markdown (pdf2md is not used: annotations land on the original PDF).
- Plagiarism or AI-generated-text detection.
- Grading exams or source code. The exam figures the owner gave (77 percent, sd 7) only document the
  contrast with lab reports **[session call]**.
- Rubric input other than `.md` and `.txt`, the two forms the owner supplied **[session call]**.
- Grading with a cloud model. It is not an option, not a fallback (R8).

## 4. Anti-goals

- **Student text leaving the computer**: in a cloud prompt, a wrapper's context, a log, a commit, a test,
  an Issue or a plan. This includes quotes and model comments about a report, not only names.
- **A grader that is too severe**: lab reports target 88 percent with sd 4 (owner).
- **Research standards applied to undergraduates.**
- **A total computed by a model, or a missing item silently counted as zero.**
- **A truncated prompt**: Ollama silently truncates a prompt over its window (R8, rule R26 notes); a
  report that does not fit is split, never cut.
- **Annotations that move**, or that hide the student's text.
- **A grade with no evidence** the professor can trace to a page and a passage.

## 5. Constraints

- **Local only (owner).** Answers the Quebec Act A-2.1 (Law 25) art. 65.1 concern found in the vault
  (`30_Ressources/Methode/quebec-student-data-protection-a21.md`): the reports never leave the machine.
- **The wrapper is blind to content [session call, follows from the owner's rule].** Like `local-coder`,
  the agent is a cheap cloud wrapper. It runs scripts and reads only `progress.md` and the scripts' JSON
  status lines, which carry an anonymous report id, statuses, counts, scores and file paths, never a
  quote, a comment, a name or a file name. A Python driver reads the reports, builds every prompt and
  calls `ollama_bridge.py`. A test asserts that no driver output read by the wrapper carries text from a
  fixture report.
- **Pseudonymous ids.** Each report gets an id (`R01`, `R02`, ...). The id-to-file map stays in the
  output folder beside the reports, never in the repository.
- **No model tag in code (R2).** Grader, auditor and vision models are resolver roles, adopted with
  `model_resolver.py --adopt-role` like the `session` role. The owner named Gemma4 and Qwen3.8; which one
  grades and which audits is adopted, not written in code. *Guess: Gemma4 grades, Qwen3.8 audits.*
- **Vision is measured, not assumed.** A figure is handed only to a role whose vision capability has been
  checked on this machine; otherwise the figure step reports `NOT RUN`, never a score (vault lesson
  `quality-gates-three-outcomes`).
- **Window fit.** Every prompt is measured with `context_budget.py --role` before it is sent. A report
  larger than the role's window is graded item by item on the sections that item needs, located by
  heading. The 6GEN135 reports reach about 200 000 characters, roughly 50 000 tokens.
- **Calibration (owner).** Lab and project reports: target mean 88 percent, target sd 4. Tolerance: the
  mean within 88 ± 5 points (83 to 93) and the sd within 4 ± 2 (2 to 6). Leaving either band triggers a
  re-grade. *Read as percentage points, not 5 percent of 88* **[session call]**. Stored in
  `calibration_targets.json` with provenance (R0, R4); a missing value is a refusal (R3).
- **Loop bound (owner).** Two full re-grading loops, then ask.
- **Privacy (R34).** Outputs stay beside the reports. Fixtures are generated fictitious PDFs. Report file
  names carry student names, so a file name is never copied anywhere either.
- **French text.** The reports seen are in French. Comments follow the report's language, and every
  text check is tested on accented input (vault: `compteur-de-mots-aveugle-au-francais`).
- **Repository rules**: R18, R22, R23, R31, R26/R29/R38 (plans with a header, no code in plans), R35
  (bounded review before the PR), R36 (outside skills are inspiration only).

## 6. Prior art (inspiration only, nothing installed, R36 part 4)

| Source | Idea taken | Idea left |
|---|---|---|
| Report Evaluation skill (Become-A-DevOps-PM/IPL25-Hugo-Site, licence not stated) | assignment folder, resumable state file, outputs kept out of git | three graders and a vote |
| Curriculum Grade Assist (catalog listing, no licence, no script) | anchored levels per criterion with justification, batch consistency and outlier flags | its level names |
| K-Dense scholar-evaluation v2.4 (MIT) | `rated / missing / not_applicable`, so a missing item is never a silent zero; human review before release | research process-audit dimensions |
| ResearchTools `aider-setup` | `spec.md` / `progress.md` / audit split, a producer and an auditor that never edits, three ledger marks | aider itself: it edits code by diff and cannot read or annotate a PDF |
| ResearchTools `local-coder` | blind cheap wrapper, bridge with resolver roles, `PLAN:`-style dispatch | its plan contract, which is for code |

## 7. Components

### 7.1 Language skill `language-review` (new) **[session call on the name]**

- Scope: language only, as the owner asked (structure, spelling, grammar, style, register). The content
  codes of `reviewer-response` (SC, M, R, D, FT, EQ, REF, Q, MAJ) classify reviewer comments and stay
  there.
- `assets/language_categories.json`: the single table. G and S from `reviewer-response`, split into
  finer codes (spelling, agreement, punctuation, sentence structure, register, terminology, typography),
  plus the composition tags the research auditors use (`SENTENCE TOO LONG`, `SEMICOLON IN PROSE`,
  `INFORMAL LANGUAGE`, `ACTIVE VOICE UNJUSTIFIED`, `LIST IN PROSE SECTION` and the rest), each keeping
  its R1.x rule. Per entry: code, FR and EN labels, severity, scope (research, undergraduate, both), R1.x
  rule if any, LaTeX action, PDF action (colour, note prefix).
- `assets/correction_table.csv` and `.md`: ready-to-fill table (location, code, original, proposed,
  reason).
- `references/`: rules per code with a French and an English example; composition rules pointed to.
- The five research agents replace their local table and tags by a reference to this skill;
  `docs/manual/04-commands.md` points to it. Research agents keep using it from the cloud as today.
- Acceptance: every language tag and rule each agent used before is still reachable with the same flag
  text, R1.x number and LaTeX action, proven by a documentation test like `test_deliberation_contract.py`.

### 7.2 Grading skill and agent `work-ugs-audit` (new)

Working folder per batch, beside the reports **[session call on the layout]**:

```text
<reports folder>/_correction/
  ids.json                 report id -> file name (never leaves this folder)
  spec.md, rubric.json     normalized rubric, confirmed by the professor
  progress.md              one "## R01" section per report, aider marks [ ] [x] [!]
  loop-1/ loop-2/          one folder per grading loop
    R01/ grade.json  audit.md  figures/  figures.json  language.csv  annotated.pdf
    grades.csv  batch_report.md
```

`progress.md` lines name a step and its status only (rubric item 3 graded, figure 4 judged, audit
clean), so the wrapper can read it.

Driver mechanics (aider-setup reproduced in Python):

1. **Prepare**: assign ids, convert each report to Markdown **page by page** with `pymupdf4llm` (already
   pinned 1.27.2.3 in `extract-statistic`; headings and tables kept, page number kept for anchoring, no
   model, seconds per report), locate and extract figures as PNG (7.4), write the per-report ledger in
   `progress.md`. `pdf2md` is not used (owner, 2026-11-05): it drops page numbers, its vision model
   rewrites text so a quote may no longer match the PDF, it takes hours per long report, and it competes
   for the 6 GB card with the grading models; every report seen has a clean text layer anyway.
2. **Grade**: for each report and each rubric item, a fresh bridge call with the grader role: the item
   from `spec.md`, the anchored levels of the undergraduate framework, the relevant sections. Output: one
   item record in `grade.json` (score, status, comment, evidence).
3. **Language**: per section, the grader role applies `language-review`'s undergraduate scope; output in
   `language.csv`.
4. **Audit**: the auditor role reads each item record with its evidence and returns agree or disagree
   with a reason in `audit.md`. It never edits `grade.json`. A disagreement is re-graded once by the
   grader with the auditor's reason; if it persists, the item is marked `[!]` for the professor. *Bound
   of one retry* **[session call]**.
5. **Assemble**: `grade_total.py`, `pdf_annotate.py`, `pdf_annex.py` produce `annotated.pdf`.
6. **Batch**: `batch_stats.py` writes `grades.csv` and the numeric part of `batch_report.md`, and prints
   the in-band or out-of-band verdict.

Every step is resumable from `progress.md`; a step whose model is unavailable is `NOT RUN`.

Assets (templates): `rubric.schema.json`, `rubric.template.json`, `spec.template.md`,
`progress.template.md`, `grade.template.json`, `figure_analysis.template.json`,
`grade_sheet.template.csv`, `annex.template.html`, `batch_report.template.md`,
`calibration_targets.json`, `undergrad_references.json`.

Scripts (offline tests on fictitious PDFs, each suite asserting a failure path, R20):

| Script | Job |
|---|---|
| `ugs_driver.py` | the driver above: prepare, grade, language, audit, assemble, batch; `--resume`, `--dry-run` (R16), JSON status lines (R17) |
| `rubric_check.py` | validate `rubric.json`; sum of points (decimals: one rubric totals 28.5, another 100); refuse an empty or duplicate item |
| `grade_total.py` | totals and percentages; `missing` and `not_applicable` explicit, never zero |
| `batch_stats.py` | mean, sd, band verdict, outliers, loop counter (refuses a third loop without an explicit flag) |
| `figure_extract.py` | position, count and extraction of figures (7.4) |
| `pdf_annotate.py` | highlight-plus-note annotations from JSON; a passage not found is reported, never placed elsewhere |
| `pdf_annex.py` | render the completed rubric and append it to a copy; the original is never modified |
| `ref_check.py` | standard ids checked for form (`form-ok`, `malformed`: no free ISO/CSA registry); URLs fetched with a timeout (`reachable`, `unreachable`, `blocked`); every reference checked for a citation in the text. No status costs points by itself; only a rubric item on references does **[session call]** |

PDF library **[session call]**: PyMuPDF (pinned 1.27.2.3 in four skills already) because it locates a
quoted passage (`search_for`) and extracts images with their position; pypdf cannot. AGPL-3.0, local
use only.

Agent pipeline (contractual, final checklist like the other pipeline agents):

1. Run the driver's prepare step; show the professor `spec.md` and the figure count per report;
   **PIPELINE-PAUSED** for confirmation of the rubric.
2. Run grade, language, audit, assemble. Long: the batch can run overnight; the wrapper only polls
   `progress.md`.
3. Run batch; present the band verdict and the options built from numbers only (re-grade, accept, adjust
   one item's anchors); the professor reads `batch_report.md` himself.
4. Out of band: re-grade every report into the next loop folder, with the batch statistics as
   calibration input. After loop 2, ask.
5. Final checklist; outputs listed by relative path inside `_correction/`.

### 7.3 `scholar-evaluation`: undergraduate framework

`references/undergraduate_framework.md`: anchored levels for technical reports where "complete and
correct" maps to about 88 percent of an item and points are lost for a missing element or a technical
error, not for style or research-level depth; reuses `rated / missing / not_applicable`. Written so a
local model can apply it from the prompt alone. The research framework is unchanged.

### 7.4 Figures

1. `figure_extract.py` counts the figures per page, records their position, and extracts each as an
   image file in `R01/figures/`. It also computes the share of the figure area occupied by the drawing
   (non-background pixels' bounding box over the image area), a deterministic measure for the 70 percent
   criterion.
2. Each figure is judged in **its own fresh bridge call** (owner: "a new session per image"), with the
   vision role, its caption and the paragraph that cites it. `progress.md` holds the state per figure.
3. The result goes into `figures.json`, built from `figure_analysis.template.json`. The criteria live in
   `figure_criteria.json` (a correction template: id, FR and EN label, judged by script or model, the
   figure kinds it applies to, a ready-to-use FR and EN comment for a failure). 21 criteria, all kept by
   the owner on 2026-11-05 (S = script, M = vision model):
   - owner's six: cited in the text with meaningful content (M), curves visible (M), more than 70 percent
     of the space used by the drawing (S), relevant axis titles (M), adequate units (M), a legend when
     several curves (M);
   - readability: effective resolution of a raster image (S), text inside the figure large enough
     against the body text (S for vector, M for raster), curves distinguished by more than colour and
     readable in grey (M), legend not covering data (M);
   - link with the text: numbered in sequence (S), called in the text before it appears (S), caption
     understandable on its own (M), source cited for a borrowed figure (S then M);
   - technical content: SI units consistent with the text, ISO 80000 (M), error bars or uncertainty for
     a measurement (M), honest axis scale (M), values consistent with the text (M, low reliability on a
     local model);
   - block diagrams and flowcharts: inputs and outputs identified, arrows oriented and labelled (M),
     standard flowchart symbols, ISO 5807 (M), no screenshot of code in place of a flowchart or text (M).
   The two standards are named by the session and checked before they are quoted to students.
4. Each criterion is `pass`, `fail`, `not_applicable` (a block diagram has no axes) or `not_run`, with a
   one-line reason. The figure remarks are annotated on the figure's rectangle in the PDF. Points move
   only through the rubric item that covers figures, as for references.

### 7.5 Skill `figure-review` (owner, 2026-11-05)

The figure work of 7.4 lives in its own skill, called by `work-ugs-audit` and by the research auditors
(`paper-auditor`, `thesis-auditor`, `thesis-proposal-auditor`, `scopus-auditor`) and `/tikz`, which are
migrated to it in this effort with no behaviour change. It holds `figure_criteria.json` (the 21 criteria
plus research-scope entries such as the nine TikZ rules, each with `scope`, `severity`, a threshold when
measured, and FR/EN failure comments), `figure_extract.py` (PDF), `figure_tex.py` (LaTeX), `figure_checks.py`
(script verdicts) and `prompts/figure.md`. It is the lower layer: it reads nothing from `work-ugs-audit`.
The caller's model judges the `model` criteria (local for undergraduate grading, cloud for the auditors).

Vector and bitmap figures (owner, 2026-11-05). A thesis, an article or any other work may hold both kinds,
so every figure is handled on its own. Vector sources (TikZ, draw.io, SVG, EPS, PDF) keep their source
checks. As an option, off by default, a figure in a format the model cannot see natively is rendered to
PNG by `figure_render.py` (TikZ through `pdflatex` with the document's preamble, draw.io through
`paper2talk`'s `fig_export.py`, SVG and PDF through PyMuPDF, EPS through `epstopdf`, GIF, BMP, TIFF and
WebP converted). PNG and JPEG go to the model as they are. A missing tool makes that figure `not_run`.
`find-skills` found no equivalent on 2026-11-05; `how-to-review-figure` (quantumbfs/sci-brain, 18-rule
scorecard with severity-ranked findings) and `figure-results-review` (claim against displayed evidence)
were read for ideas only, nothing installed.

## 8. Decided by the owner (2026-11-05)

- Draft only; the professor reviews and uploads to Moodle.
- Comments in the original PDF; completed rubric appended; totals by a script.
- Local grading only; aider-setup mechanics inside a wrapper subagent; `progress.md`; `spec.md` is the
  rubric.
- Two local models, grader and auditor (Gemma4 and Qwen3.8 today).
- Calibration: 88 percent, sd 4; tolerance 5 on the mean, 2 on the sd. Two loops, then ask.
- One grader per report; consistency checked at batch level by script.
- Figures extracted and judged one per session, results in a JSON template, criteria listed in 7.4.
- Language skill created; the five research agents migrated in this effort.
- Undergraduate references accepted (standards, web), still validated.
- Templates in the skills' assets. Skills authored with `superpowers:writing-skills` and `skill-creator`.

## 9. Left to the builder

- JSON field names, annex layout, annotation colours.
- Matching a quoted passage split across lines (normalize whitespace and hyphenation first).
- Command name (proposal: `/gradeugs`).
- How a report too large for the window is split, as long as nothing is truncated.

## 10. Tests and evidence

Offline suites on generated fictitious PDFs and rubrics; the two real rubric shapes are reproduced as
fictitious fixtures (a points table totalling 100, a checklist rubric with fractional points totalling
28.5). The bridge is faked in tests (R21). One test plants a marker sentence in a fixture report and
asserts it never appears in anything the wrapper reads. The professor runs the live batch on his machine.

## 11. Measured before the plan is executed

- Vision capability of each adopted role on this machine (a figure is not judged without it).
- Window and decode speed of the grader and auditor roles (`opt-local-vram-llm` or the thread sweep), to
  estimate a batch's duration.
