# Spec - work-ugs-audit (Issue #104)

Condensed from `docs/superpowers/specs/2026-11-05-work-ugs-audit-design.md` (approved by the owner
2026-11-05), which holds the reasons. This file holds what every plan needs. Branch
`feat/work-ugs-audit`, worktree `.worktrees/work-ugs-audit`.

## What is built

1. Skill `language-review`: one language-only category table (FR/EN labels, severity, scope, R1.x rule,
   LaTeX action, PDF action), a ready-to-fill correction table, and the five research agents
   (`paper-auditor`, `thesis-auditor`, `thesis-proposal-auditor`, `scopus-auditor`,
   `reviewer-response`) migrated to it with no behaviour change.
2. Skill and agent `work-ugs-audit`, command `/gradeugs`: grades undergraduate lab and project reports
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
  figure in `progress.md`; result in `figures.json` from a template. 21 criteria held as data in
  `figure_criteria.json` (owner kept all on 2026-11-05; design 7.4 lists them). Script-measured: drawing
  over 70 percent of the image, effective DPI, text size (vector), numbering in sequence, called before it
  appears, source marker in the caption. The rest are judged by the vision model. Each criterion carries a
  ready-to-use FR and EN failure comment. Figures cost points only through the rubric item covering them.
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
  `cited_in_text`, `criteria{}` keyed by the ids of `figure_criteria.json`, each
  `{verdict: pass|fail|not_applicable|not_run, reason}`.
- Working folder beside the reports: `_correction/` with `ids.json`, `spec.md`, `rubric.json`,
  `progress.md`, `loop_state.json`, `loop-<n>/R01/...`, `loop-<n>/grades.csv`,
  `loop-<n>/batch_report.md`.

## Model roles

Resolver roles `ugs-grader`, `ugs-auditor`, `ugs-vision`, adopted by the owner with
`model_resolver.py --adopt-role` (today Gemma4 grades, Qwen3.8 audits). No tag in code (R2). A figure
step whose role has not passed `vision_probe.py` is `not_run`.

## Constraints

R34 (no student name, file name or report text in the repository, a test, a log line read by the wrapper,
an Issue or a plan; fixtures are generated fictitious PDFs), R0/R3/R4 (every threshold in a JSON with
provenance, a missing key named), R8 (no cloud fallback, no truncated prompt: a prompt over the role
window is split by section or refused), R16/R17 (`--dry-run`, JSON report), R18, R20, R21 (bridge
injected in tests), R22, R23, R24 (every output path resolved inside the working folder), R27, R29, R31,
R35, R36. French text: every text check is tested on accented input.

## Acceptance

Every new script has an offline suite with a failure path. A fixture report carrying a marker sentence
proves the marker never reaches a wrapper-visible output. The five research agents keep every language
flag text, R1.x number and LaTeX action. `run-all-checks.ps1` exits 0 once, at the end (plan 12).
