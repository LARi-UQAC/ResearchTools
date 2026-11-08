# Spec - work-ugs-audit (Issue #104)

Condensed from `docs/superpowers/specs/2026-11-05-work-ugs-audit-design.md` (approved by the owner
2026-11-05), which holds the reasons. This file holds what every plan needs. Branch
`feat/work-ugs-audit`, worktree `.worktrees/work-ugs-audit`.

## What is built

1. Skill `language-review`: one language-only category table (FR/EN labels, severity, scope, R1.x rule,
   LaTeX action, PDF action), a ready-to-fill correction table, and the five research agents
   (`paper-auditor`, `thesis-auditor`, `thesis-proposal-auditor`, `scopus-auditor`,
   `reviewer-response`) migrated to it with no behaviour change.
2. Skill and agent `work-ugs-audit`, command `/work-ugs-audit`: grades undergraduate lab and project reports
   (PDF from Moodle) against the professor's rubric, **entirely on local models**, writes annotations
   into a copy of each PDF, appends the completed rubric, computes totals by script, analyses the batch
   against a calibration band, re-grades the whole batch when out of band (two loops, then ask).
3. `scholar-evaluation/references/undergraduate_framework.md`: anchored levels for technical reports.
4. Skill `figure-review`: the figure criteria (21 undergraduate and research criteria, plus the research
   TikZ rules), the figure extraction and script checks for PDF and LaTeX, the figure prompt and the
   template. Called by `work-ugs-audit` and by `paper-auditor`, `thesis-auditor`,
   `thesis-proposal-auditor`, `scopus-auditor` and `/tikz`, which are migrated to it (D12).

## Decisions (owner, 2026-11-05)

- D1 Draft only. The professor reviews everything and uploads to Moodle; the agent never does.
- D2 Local only. No report text, quote or model comment about a report reaches a cloud model. The agent
  is a cheap cloud wrapper that runs scripts and reads only `progress.md` and JSON status lines carrying
  a report id (`R01`), step, status, counts and scores.
- D3 aider-setup mechanics in Python: `spec.md` is the normalized rubric, `progress.md` the ledger with
  marks `[ ]`, `[x]`, `[!]`; one grader role produces, one auditor role checks and never edits.
- D4 One grader per report. Consistency is checked at batch level by script.
- D5 Calibration for lab and project reports: target mean 88 percent, sd 4. Re-grade when the mean leaves
  83 to 93 or the sd leaves 2 to 6 (read as percentage points). Two loops, then ask.
- D6 Figures: count, position and extract each as PNG; judge each in its own fresh model call; state per
  figure in `progress.md`; result in `figures.json` from a template. 22 criteria held as data in
  `figure_criteria.json` (owner kept all on 2026-11-05; design 7.4 lists them). Script-measured: drawing
  over 70 percent of the image, effective DPI (150 minimum), text size (vector, ratio 0.7 minimum),
  numbering in sequence, called before it appears, source marker in the caption. The rest are judged by
  the vision model. The 22nd, `style_consistency`, is judged once per report on one contact-sheet image
  and is comment only. Each criterion carries a ready-to-use FR and EN failure comment. Figures cost
  points only through the rubric item covering them. Outlier threshold |z| > 2 (owner).
- D14 Image size (owner, 2026-11-05). Token cost is `ceil(w/28) * ceil(h/28)` and does not depend on the
  format (Anthropic Vision doc, read 2026-11-05), so every image sent to a model is cropped, downscaled
  to a long edge of at most 1568 px, and written as PNG for line art or JPEG for a photo. A local model's
  own image cost is measured by `vision_probe.py`.
- D15 (owner, 2026-11-05) Anchored levels per item: absent 0, attempted 0.5, partial 0.75, complete and
  correct 0.88, exemplary 1.0. Qwen3.8 grades, Gemma4 audits (resolver roles). Annotations carry the
  professor's name read from the active profile's `author.name`, never written in code. Command
  `/work-ugs-audit`, output folder `_correction/` beside the reports.
- D7 Reports read with `pymupdf4llm` page by page (page number kept for anchoring); `pdf2md` not used.
- D8 References: ISO/CSA/IEC standards and web pages acceptable; standards checked for form, URLs for
  reachability with a timeout, every reference for a citation in the text. No reference status costs
  points except through a rubric item on references.
- D9 Language skill covers language only; the content codes (SC, M, R, D, FT, EQ, REF, Q, MAJ) stay in
  `reviewer-response`.
- D10 Templates in the skills' `assets/`.
- D11 Build executor: judgment plans in the session (`superpowers:executing-plans`), script plans by
  `local-coder` (one dispatch per plan). Review bounds: 3 rounds, 1500000 tokens, plateau 2.
- D12 Figure checks gathered in `figure-review` and the four auditors migrated in this effort.
  `find-skills` (2026-11-05) found no equivalent; two skills read for ideas only. `figure-review` is the
  lower layer: it reads no `work-ugs-audit` file, and its thresholds live in `figure_criteria.json`.
- D13 The auditors handle vector figures (TikZ, draw.io, SVG, EPS, PDF) and bitmaps (PNG, JPG, GIF, BMP,
  TIFF, WebP), figure by figure, since one document may hold both. As an option (off by default), a
  figure in a format the model cannot see is rendered to PNG; PNG and JPEG go to the model as they are.
  Vector sources keep their source checks (TikZ rules) whether or not they are rendered.

## Data shapes (fixed here, used across plans)

- `rubric.json`: `assessment_type` (`lab_report` or `project_report`), `total_points` (number),
  `items[]` with `id` (`I01`...), `title`, `max_points` (number, decimals allowed), `criteria[]`,
  `checklist[]`.
- `grade.json`: `report_id`, `loop`, `items[]` with `item_id`, `status`, `score` (number or null),
  `comment`, `evidence[]` (`page`, `quote`), `audit` (`agree`, `disagree`, `not_run`), `flag` (bool).
  Status: `rated` (score given, 0 allowed for an absent element), `not_applicable` (excluded from the
  maximum), `not_run` (model unavailable or failed: never a zero, the total is refused).
- `annotations.json`: list of `page`, `kind` (`technical`, `figure`, `language`, `reference`), `code`,
  `quote` (or null), `rect` (or null), `comment`.
- `figures.json`: `report_id`, `figures[]` with `figure_id` (`F01`...), `page`, `rect`, `file`, `kind`
  (`chart`, `diagram`, `flowchart`, `photo`, `other`), `drawing_area_ratio`, `effective_dpi`, `caption`,
  `cited_in_text`, `criteria{}` keyed by the `level: figure` ids of `figure_criteria.json`, each
  `{verdict: pass|fail|not_applicable|not_run, reason}`; plus `report_criteria{style_consistency}`.
- Working folder beside the reports: `_correction/` with `ids.json`, `spec.md`, `rubric.json`,
  `progress.md`, `loop_state.json`, `loop-<n>/R01/...`, `loop-<n>/grades.csv`,
  `loop-<n>/batch_report.md`.

## Model roles

Resolver roles `ugs-grader`, `ugs-auditor`, `ugs-vision`, adopted by the owner with
`model_resolver.py --adopt-role` (owner 2026-11-05: Qwen3.8 grades, Gemma4 audits). No tag in code (R2). A figure
step whose role has not passed `vision_probe.py` is `not_run`.

## Constraints

R34 (no student name, file name or report text in the repository, a test, a log line read by the wrapper,
an Issue or a plan; fixtures are generated fictitious PDFs), R0/R3/R4 (every threshold in a JSON with
provenance, a missing key named), R8 (no cloud fallback, no truncated prompt: a prompt over the role
window is split by section or refused), R16/R17 (`--dry-run`, JSON report), R18, R20, R21 (bridge
injected in tests), R22, R23, R24 (every output path resolved inside the working folder), R27, R29, R31,
R35, R36. French text: every text check is tested on accented input.

## Driver contracts (plans 8a to 8l)

Scripts live in `.claude/skills/work-ugs-audit/scripts` (`bridge_images` in loop-engineer). A test puts the
parent of its own folder first on `sys.path`. A module needing loop-engineer or figure-review scripts adds
their folder to `sys.path` from its own file location.

- `call(kind, prompt, schema, images=None) -> dict`: kind is `grader`, `auditor` or `vision`. The driver
  builds the real one from `ugs_bridge.call` and the role names of the configuration; tests pass a fake.
  It raises `ugs_bridge.NotRun` with `.kind` (`unadopted`, `over_budget`, `unreachable`, `unparsable`,
  `invalid`, `image`) and `.retryable` (true for `unparsable` and `invalid`).
- `ugs_text.StepContext`: `prompts` (name to text), `schemas`, `levels`, `window_tokens`, `reserve_tokens`,
  `count` (text to tokens), `grade_retries`, `audit_retries`, `min_word_len`.
- Answers (keys of the schemas file): grade_item `{status, score, comment, evidence[{page, quote}]}`;
  audit_item `{verdict agree|disagree, reason}`; language `{findings[{page, code, quote, proposed, reason}]}`;
  figure `{kind, criteria[{id, verdict, reason}]}`; figure_set `{verdict, reason, figures_involved[]}`;
  rubric = the rubric shape; vision_probe `{x_title, y_title, unit, curve_count}`.
- Work folder files: ids.json, rubric.json, spec.md, progress.md, loop_state.json, vision_probe.json,
  `R01/pages/p001.md`, `R01/figures/`, `R01/model_images/`; per loop `loop-N/R01/` holds grade.json,
  language.json, figures.json, annotations.json, totals.json, annotated.pdf; `loop-N/` holds grades.csv,
  batch_report.md, batch.json.
- Ledger lines of a `## R01` section: `prepare`, `grade I01`..., `language`, `figures`, `figure F01`...,
  `audit`, `assemble`. Marks `[ ]`, `[x]`, `[!]`; an optional note after ` - ` is a short code, never
  report text.
- Exit codes: 0 done, 1 a model step could not run (stop, resume later), 2 refusal, 3 batch out of band.

## Acceptance

Every new script has an offline suite with a failure path. A fixture report carrying a marker sentence
proves the marker never reaches a wrapper-visible output. The five research agents keep every language
flag text, R1.x number and LaTeX action. `run-all-checks.ps1` exits 0 once, at the end (plan 12).

## Language and conventions

- **Language and version:** Python 3.11 or later. Standard library only, except PyMuPDF (`fitz`) where a plan names it,
  declared in `.claude/skills/figure-review/scripts/requirements.txt`.
- **Case of names:** functions are `verb_complement` in lower snake case (`compute_total`), private helpers start with
  an underscore, classes are `PascalCase`, constants are `UPPER_SNAKE_CASE`, variables are lower snake case with the
  scope prefixes of the coding rules.
- **Documentation comment:** a docstring with Purpose, Inputs, Outputs and, when the function raises on purpose, Raises.
- **Types:** a type annotation on every parameter and every return value.
- **Tests:** `unittest`, in a folder named `Test` beside the source, one file `test_<module>.py` per module. Each test
  file ends with `unittest.main()` and puts the parent folder of its own folder at the start of `sys.path` before it
  imports the module under test.
- **Format and lint:** none required.
