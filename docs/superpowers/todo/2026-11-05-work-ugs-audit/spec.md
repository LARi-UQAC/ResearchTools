# Spec - grading of undergraduate reports and review of research documents

This file holds what every plan needs: what is built, the choices that bind the code, the shapes of the data and the contracts between the scripts.

## What is built

1. Skill `language-review`: one language-only category table (FR/EN labels, severity, scope, writing-rule number,
   LaTeX action, PDF action), a ready-to-fill correction table, and the five research agents
   (`paper-auditor`, `thesis-auditor`, `thesis-proposal-auditor`, `scopus-auditor`,
   `reviewer-response`) migrated to it with no behaviour change.
2. Skill and agent `work-ugs-audit`, command `/work-ugs-audit`: grades undergraduate lab and project reports
   (PDF files) against the professor's rubric, **entirely on local models**, writes annotations
   into a copy of each PDF, appends the completed rubric, computes totals by script, analyses the batch
   against a calibration band, re-grades the whole batch when out of band (two loops, then ask).
3. `scholar-evaluation/references/undergraduate_framework.md`: anchored levels for technical reports.
4. Skill `figure-review`: the figure criteria (21 undergraduate and research criteria, plus the research
   TikZ rules), the figure extraction and script checks for PDF and LaTeX, the figure prompt and the
   template. Called by `work-ugs-audit` and by `paper-auditor`, `thesis-auditor`,
   `thesis-proposal-auditor`, `scopus-auditor` and `/tikz`, which are migrated to it.

## Design choices

- **Draft only.** The professor reviews everything and uploads the result; the program never does.
- **Local only.** No report text, quote or comment about a report leaves the machine. The wrapper that drives
  the scripts reads only `progress.md` and JSON status lines carrying a report id (`R01`), a step, a status,
  counts and scores.
- **Mechanics.** `spec.md` is the normalized rubric, `progress.md` the ledger with marks `[ ]`, `[x]`, `[!]`.
  One grader role produces, one auditor role checks and never edits.
- **One grader per report.** Consistency is checked at batch level by script.
- **Calibration for lab and project reports:** target mean 88 percent, sd 4. Re-grade when the mean leaves
  83 to 93 or the sd leaves 2 to 6 (read as percentage points). Two loops, then ask.
- **Figures:** count, position and extract each as PNG; judge each in its own fresh model call; state per
  figure in `progress.md`; result in `figures.json` from a template. 22 criteria held as data in
  `figure_criteria.json`. Script-measured: drawing over 70 percent of the image, effective DPI (150
  minimum), text size (vector, ratio 0.7 minimum), numbering in sequence, called before it appears,
  source marker in the caption. The rest are judged by the vision model. The 22nd, `style_consistency`,
  is judged once per report on one contact-sheet image and is comment only. Each criterion carries a
  ready-to-use FR and EN failure comment. Figures cost points only through the rubric item covering them.
  Outlier threshold |z| > 2.
- **Image size.** Every image sent to a model is cropped, downscaled to a long edge of at most 1568 px, and
  written as PNG for line art or JPEG for a photo. A model reads an image as tiles about 28 px wide and
  high, so the cost grows with the area; a local model's own image cost is measured by `vision_probe.py`.
- **Anchored levels per item:** absent 0, attempted 0.5, partial 0.75, complete and correct 0.88,
  exemplary 1.0. Annotations carry the professor's name, read from the `author.name` key of the active
  profile file, never written in code. Command `/work-ugs-audit`, output folder `_correction/` beside the
  reports.
- **Reading:** reports are read with `pymupdf4llm` page by page (page number kept for anchoring).
- **References:** ISO/CSA/IEC standards and web pages are acceptable; standards are checked for form, URLs
  for reachability with a timeout, every reference for a citation in the text. No reference status costs
  points except through a rubric item on references.
- **Language skill covers language only.** The content codes (SC, M, R, D, FT, EQ, REF, Q, MAJ) stay in
  `reviewer-response`.
- **Templates** live in the skills' `assets/`.
- **Layers.** Figure checks are gathered in `figure-review`, the lower layer: it reads no `work-ugs-audit`
  file, and its thresholds live in `figure_criteria.json`.
- **Figure formats.** The auditors handle vector figures (TikZ, draw.io, SVG, EPS, PDF) and bitmaps (PNG,
  JPG, GIF, BMP, TIFF, WebP), figure by figure, since one document may hold both. As an option (off by
  default), a figure in a format the model cannot see is rendered to PNG; PNG and JPEG go to the model as
  they are. Vector sources keep their source checks (TikZ rules) whether or not they are rendered.

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

The roles are names read from the configuration: `ugs-grader`, `ugs-auditor`, `ugs-vision`. No model tag
appears in code. A figure step whose role has not passed `vision_probe.py` is `not_run`.

## Constraints

- No student name, file name or report text in the code, a test, a log line read by the wrapper, or a
  plan. Test fixtures are generated fictitious PDFs.
- No numeric threshold in the code: every one is read from a JSON file that states where the value comes
  from, and a missing key raises an error that names it.
- No cloud fallback and no truncated prompt: a prompt over the role window is split by section or refused.
- Every script that changes state offers `--dry-run` and prints a JSON report beside its text.
- A script lives beside the one skill that calls it.
- Every test file has at least one failure-path test, and the model bridge is injected in tests (a test
  never reads configuration measured on one machine).
- Every output path is resolved inside the working folder before anything is written.
- Every function has a header: Purpose, Inputs, Outputs and, when it raises on purpose, Raises.
- French text: every text check is tested on accented input.

## Driver contracts

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
flag text, writing-rule number and LaTeX action.

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
