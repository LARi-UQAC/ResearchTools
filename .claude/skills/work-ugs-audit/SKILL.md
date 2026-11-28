---
name: work-ugs-audit
description: "Grade undergraduate (premier cycle) student reports in PDF against the professor's rubric or grille de correction, with local models only, then annotate each PDF and append a correction annex: grading, correction, rubric, language, figures and references, with a batch calibration across reports. The reports are confidential, so no cloud model reads them. Trigger on: grade the reports, correct the student reports, grille de correction, corriger les rapports, rapport de laboratoire, premier cycle, /work-ugs-audit."
allowed-tools: [Read, Bash]
---

# work-ugs-audit

Grading of a folder of undergraduate reports (PDF), one report at a time, by the local models of this machine.
Python is `.venv-skills`. Every threshold, role name and count is in `assets/ugs_config.json`, each value with its
provenance, and a missing key is a named error. The `work-ugs-audit` agent drives this skill and stays blind to
the reports; a professor can also run the driver by hand.

## What it does

For every report: cut the PDF into pages and figures, grade each rubric item with evidence quoted from the
report, review the language with the `language-review` table, review each figure with the `figure-review`
skill (scope `undergraduate`), check the cited references, audit the grades with a second model, then write an
annotated PDF and a correction annex. Across the batch it measures the spread of the totals and, when they fall
out of band, offers a calibrated second loop.

## Preparation, in order

`prepare` runs these steps for each report before any model is called. (1) The language is detected once from the
text layer and stored in `report_meta.json`. (2) The OCR preflight (`text_quality.ocr_preflight`) runs a real OCR
probe for each language and refuses before any write when Tesseract does not answer (`TESSDATA_PREFIX`, the `fra`
and `eng` data). (3) Pages holding replacement characters are repaired by OCR in the detected language; a page with
sound text keeps its text, and an OCR that returns nothing keeps the original text and flags the page. (4) Excluded
pages (cover, signature table, version table, `page_roles.py`) are replaced by a one-line marker; their text goes to an
`excluded` folder and they are never graded. (5) `front_pages.py` finds the front-matter roles from the page texts
(cover, version and signature page, executive summary, table of contents, list of figures, list of tables) and the
first body page, written as `front_roles` in `report_meta.json`. Every front page but the summary is skipped by the
element extraction, and each role has a language mode (`none` for the cover and the version page, `spelling_only` for
the contents and the lists, `full` otherwise). (6) `front_matter.py` reads the declared counts and printed numbers of
figures and tables from the lists, or from the contents pages that hold them (`declared_figures`, `declared_tables`;
a list that cannot be found is `None`, never 0). (7) Elements are extracted with a type (`figure`, `table`,
`table_image`, `logo`) through the count loop of `count_loop.py`: an attempt is accepted when the titled numbers
match the declared ones, otherwise the extraction runs again with the next settings, up to
`extraction.count_max_iterations`, every attempt kept in `figure_attempts`, and a rejected attempt leaves no file.
(8) A table drawn as an image (a table title over a picture, or an untitled region whose OCR gives a grid) is read by
OCR at `text.ocr_dpi` in the report language and rebuilt as a Markdown table by `table_image.py`; when no usable row
comes back it is `table_image_unreadable` with a `status_reason` of counts only. (9) Each table and each rebuilt
table image is added to its page text under the heading of `assets/table_text.json`, in the report language.
(10) `count_check.py` compares declared and titled numbers per type and writes `figure_count_status` and
`table_count_status` (`ok`, `mismatch`, `not_found`) with the missing and extra numbers. An element without a title
never counts and never stands in for a number: it is listed in `untitled_figures` or `untitled_tables`, its file goes
to `figures/untitled/`, and it is still judged (a missing title is a fault).

Files of a report: `figures/F<X>.png` for each titled figure and `figures/T<Y>.png` for each table drawn as an image,
X and Y being the numbers printed in the titles ("Figure 2.3" gives `F2.3.png`). Ruled tables and logos write no file.
The figures folder therefore holds exactly one file per declared figure and per image table.

Vocabulary, the same in the code and the annex. A **title** names the whole figure or the whole table and starts with
a marker word (Figure, Fig., Tableau, Table): a figure title is usually below the figure, a table title above it. A
**legend** is the text inside a figure that explains its series or symbols; a table has no legend. **Notes** are the
lines under a table (Note, Source, an asterisk). The element type is `figure`, `table`, `table_image` (a table drawn as
an image, rebuilt by OCR) or `logo`; only a `figure` is judged as a figure.

Titles in the image and placement (Issue #126 plans 24 and 25). A title drawn inside a raster figure is read in the
top or bottom band of `extraction.in_image_title_band_ratio` of its height (`element_labels.find_in_image_title`), with
its position `in_image_top` or `in_image_bottom`; the element then takes its printed number as its id and file name,
as a text title does. A title is placed by the house rule: a figure title centred below the figure (or centred on the
text column), a table title left-aligned above the table; a title drawn in the image is always a finding. The annex
row `title_placement` lists the ids of the findings, and its annotations carry the comments of `title_placement_comments`.
Alignment is measured on the title's own lines against the element edges (plan 28, owner 2026-11-27): the last line centred
means `center`, the first line at the left edge means `left`; the tolerance is `centre_tolerance_ratio` of the element
width. Each finding is a note on the stored title rectangle (`title.rect`), so a quote no page holds still gets its note.
Appendix pages after the references are body pages; `assets/section_terms.json` adds the words of a section (a
timesheet analysis, for instance) to the page search.

Language step. A word written correctly is never a spelling finding: a finding is refused when its proposal equals its
quote, or only swaps spellings listed in `assets/accepted_spellings.json` (both spellings of the 1990 French reform);
the count is `rejected_correct`. Findings dropped by a `spelling_only` page are counted in `dropped_scope`.

A comment written in another language than the report's is replaced by its label in the report language, counted as
`comment_language_replaced` (`ugs_language.py`, Issue #126 plan 22).

Grades. Each item of `grade.json` keeps every field the model gave, above all the score. The `validation` field holds
`ok` or the code of the refusal (`quote_not_found`, `evidence_missing`, `score_above_max`, `unknown_status`, and the
others of `GRADE_CODES` in `ugs_grade.py`). A refused proof keeps its score and counts in the totals, with its label in
the annex. A score that cannot be used (absent, not finite, above the maximum) gives status `not_run`, a null score,
and the raw value in `model_score`. A score above the maximum is asked again once, and `not_applicable` is accepted only
for an optional item (Issue #126 plan 22). A score that is not finite gives `model_score` null and its text in
`model_score_raw`, so `grade.json` is always strict JSON. Each record also carries `missing`: the element that is
absent or wrong in the report and cost the points, in the report language, empty at the maximum score, cut at
`grade.missing_max_chars` characters. It is model text saved in
`grade.json` only; it never reaches the ledger, a log or the dashboard. The ledger line carries the code as its note,
and `attempts` counts the tries. The auditor receives `missing` and `comment`, never the validation fields.

Elements and levels (Issue #126 plan 25, review round 1). The model lists the elements a rubric item asks for and gives each
a verdict: `present`, `partial` or `absent`; a present or partial element carries its page and a quote, checked on the page
by `quote_match.py` (review round 2). A quote matches in three tiers: a key tier (NFKC, case, invisible characters,
Markdown, table bars and every non-alphanumeric character removed on both sides), an elision tier (fragments around `...`
found in order) and a fuzzy tier (accent-folded words in order, share `grade.quote_min_word_share`). Every tier needs
`grade.quote_min_chars` and `grade.quote_min_words`; the page searched is the named page within `grade.quote_page_window`;
a quote over `grade.quote_max_words` skips the fuzzy tier; at most `grade.max_elements` elements are verified. An unverified
present element counts as `grade.unverified_present_counts_as`, an unverified partial one counts as absent, so a quote that
cannot be found costs that element and never refuses the item. The code computes the level from the verdicts (`assets/grade_levels.json`):
all present gives `complete_correct`, none present or partial gives `absent`, otherwise the share of present elements (a
partial one counts `partial_weight`) selects a band. `exemplary` comes only from an explicit `exceptional` claim, and only when
every element is present and every quote is verified; a refused proof never keeps it. The points come from the elements, not
from the level (owner, 2026-11-27): the maximum times the sum of the element credits (present 1, partial `partial_weight`,
absent 0) over the number of elements, rounded to `grade.score_step` (0.001 point). The elements are the rubric's own
(`rubric.element_regexes`: the checklist lines, else the numbered points), each answered by its id (`elements_mismatch`
when the ids differ, asked again once). Each lost element is named in the item comment with its lost points, and a
comment that opens on the whole report (`grade.comment_forbidden_openings`) is asked again once, then its sentence is
dropped (`comment_code`). The level stays in `grade.json` for traceability and decides no points. An item with no rubric
element must name at least `grade.min_model_elements` (3): fewer is asked again once, then the item is rated with the code
`elements_few`, and the annex marks it for the professor's check. The item keeps its points and its record is not flagged
(`flag` false), so the ledger step is not blocked by it. The 3-element minimum is a speed bump, not a guard: the real
protection is a checklist in the rubric, which fixes the elements; a model naming three trivial verified elements still
earns the section. A rated item with no verified quote is refused
(`evidence_missing`, asked again once, the answer with the most verified elements kept), except an item whose every element is
absent with a `missing` text, which is level `absent`, score 0. An empty element list is `elements_missing` and fewer elements
than the rubric checklist is `elements_too_few` (asked again once). `model_score` holds the element
summary ("present N, partial N, absent N"). A not_applicable answer carries no score and no evidence (`not_applicable_with_score`).

A report whose language cannot be decided (no text layer and no metadata) is refused in preparation with a named
reason, and the other reports continue. A page with no text layer is sent to OCR and, when still empty, listed in
`unreadable_pages` of `report_meta.json`.

The annex is written in the document language (labels in `assets/annex_labels.json`) and its table fits the page. Its
last section holds five checks computed by `crossref_checks.py` on the report's own text and elements: every figure
cited, every table cited, figure numbers increasing, table numbers increasing, equation numbers increasing. Each check
gives `ok`, `not_ok` or `not_applicable` with the numbers concerned only. A gap in the numbers lists at most
`checks.max_gap_numbers` numbers, and a number above `checks.max_number` is refused. Five more rows follow:
`citation_placement` (see below), `figure_counts` and `table_counts` (declared against titled numbers, from
`report_meta.json`), `untitled_elements` (figures and tables without a title), `title_kind` (an element whose printed title says Figure but is a table, or the reverse: the ids, from the script's ruled-table signal or the vision kind; each one gets a PDF annotation on its caption), `appendices` (every appendix listed in the contents is found after the references, and every
appendix found there is listed; markers in `front_matter.json`). `citation_placement` finds a numeric citation after
the sentence's period, ". [5]", on body pages; an abbreviation of `assets/citation_rules.json` such as "et al." before
the bracket is not a finding; each finding is also annotated in the PDF.

Local actions. While it runs, each local role emits action records built by `ugs_events.py` from identifiers only:
the report id, the item id, a page range, the base name of an output file, a mark. No prompt, reply, quote or report
text is recorded. `rt-observe` shows them as the steps of the role's lane.

## Driver

`scripts/ugs_driver.py`, all subcommands take `--dry-run` and `--json` and print one JSON object per line.

| Subcommand | Does |
|---|---|
| `prepare --reports DIR --rubric FILE --type T` | ids and pages of every PDF, takes the rubric as written (JSON is validated, a Markdown or text grid with numbered sections is split by the code and every section keeps its exact text, an unnumbered or PDF rubric is restructured by the model, which may not remove a line), writes the rubric, its Markdown and the ledger. There is no confirmation step |
| `run --work DIR --reports DIR [--loop N] [--resume] [--only R01] [--steps a,b]` | runs the steps of every report in id order, resumable; `--steps` runs only the named steps (an unknown or empty list is refused before any write) |
| `run --work DIR --continue` | after a crash or a reboot: restarts the stopped run at its most recent state, with the arguments saved in `run_state.json` (plan 30). Refused with `--loop`, `--only`, `--steps` or `--reports`, and without that file; the audit resumes at the first item not audited, and an unreachable model is retried by the driver itself (`driver.unreachable_retries`, `driver.unreachable_pause_s`) |
| `batch --work DIR --loop N [--allow-third]` | spread of the totals against the calibration targets, opens the next loop when out of band |
| `status --work DIR` | ledger counts and the first open step |
| `auto --reports DIR [--work DIR] [--type T] [--rubric FILE] [--ignore-gpu]` | the whole folder in one command (owner, 2026-11-28): checks the graphics card (another program than the model server is a refusal unless `--ignore-gpu`), prepares a new work folder (`--type` required then; the rubric defaults to `auto.rubric_name` in the reports folder), runs every report of the current loop, runs `batch`, then prints one `summary` line per report (total, maximum, percent, items not run). The same command resumes after a crash or a reboot. A batch out of band opens the next loop and stops; run the command again for that loop |

From `cmd`, the launcher `scripts/report-ugs-correction.bat` holds no logic: it finds the interpreter (this clone's `.venv-skills`, else the main clone's, never PATH) and calls `auto`:

```bat
report-ugs-correction "C:\path\to\reports" --work "C:\path\to\reports\_correction3"
```

Exit codes: 0 done, 1 a model step could not run (stop, resume later), 2 refusal, 3 batch out of band. Each `run` also writes `run_done.json` in the work folder when it ends (keys: `loop`, `exit_code`, `reports`, `open_steps`, `blocked_steps`, `stopped_at`), so a stopped session reads the outcome once. A third
loop needs `--allow-third` after the professor's answer.

## Files

The work folder is `_correction/`, inside the reports folder. It holds `ids.json`, `rubric.json`, `rubric.md`,
`ledger.md`, `loop_state.json`, `vision_probe.json`, one folder per report with its pages, figures and model
images, and one folder per loop with the grades, language and figure results, annotations, totals, the
annotated PDF and the batch report. Every output path is resolved inside the work folder (R24).

## Models

Three roles, `ugs-grader`, `ugs-auditor` and `ugs-vision`, resolved by `model_resolver.py`; no tag is written
here. The owner adopts each once:
`model_resolver.py --adopt-role ugs-grader <tag> --reason "<measurement>"`, the same for the other two. A role
not adopted stops the step and names it. There is no fallback and no cloud grading. `vision_probe.py` measures
what the vision role reads on a figure of any kind (a chart, a Gantt chart, a CAD or PCB view, a photo) before
figures are graded, and always writes a reason; a failed probe leaves the model-judged figure criteria `not_run`,
it does not stop the run. Any figure of a report is classified into one schema kind: `chart` (curves, bars, budget
charts, S-curves), `gantt`, `diagram` (UML, SysML, architectures, block diagrams, breakdown structures),
`flowchart` (flowcharts, logigrams, activity diagrams), `technical_drawing` (CAD, PCB, schematics), `photo`, or
`table` (a grid of rows and columns, such as a budget or a timesheet), `other` (a Kanban board, a screenshot). The kind decides which criteria are
judged: axes and legend only for a chart, arrows and signals for a diagram or a flowchart, the general criteria
(caption, resolution, text size, citation) for every kind. The words a professor writes as the expected kind
(`UML`, `Kanban`, `S-curve`, ...) are mapped to these kinds by `vision.kind_aliases` of the configuration.

The token count that checks a prompt against the window waits `driver.count_timeout_s` seconds (measured
2026-11-15: prefill runs near 130 tokens per second on a CPU-heavy split, so a prompt above about 1000 tokens
needs more than a few seconds). Every model call also writes a `start` record, an attempt record with its token
counts and, on a failure, a `failed` record to the bridge log, from `ugs_bridge.py` in the schema that
`collect_local.py` of `rt-observe` reads (the same log `ollama_bridge.py` writes), so the dashboard shows the
role, its window and its tokens, and Rex wakes while a role generates. The log never holds a prompt, a reply
or an error text.

## Scripts

`ugs_driver.py` (command line), `ugs_run.py` (the steps of one report), `ugs_ledger.py` (the step ledger),
`ugs_grade.py`, `ugs_audit.py`, `ugs_language.py`, `ugs_figures.py`, `ugs_assemble.py` (one module per step),
`ugs_bridge.py` (the model call, reusing the bridge helpers of `loop-engineer`), `ugs_text.py`, `ugs_config.py`,
`report_prepare.py`, `rubric_check.py`, `grade_total.py`, `batch_stats.py`, `ref_check.py`, `pdf_annotate.py`,
`pdf_annex.py`, `vision_probe.py`, `crossref_checks.py`, `front_pages.py`, `front_matter.py`, `count_check.py`,
`count_loop.py`, `table_image.py`. Each has an offline test in `scripts/Test/`.

## Recomputing a score (plan 29)

Anyone can recompute every section score and the final score from a JSON file of element verdicts, with the same
functions the grade step uses, and the run stops before writing the annotated PDF when a stored score is not
reproduced (`score_not_reproduced`). The input is `grade.json` itself or a hand-written file of the same shape:

```bash
python .claude/skills/work-ugs-audit/scripts/grade_total.py rubric.json my_grade.json --recompute --json
python .claude/skills/work-ugs-audit/scripts/grade_total.py rubric.json my_grade.json --recompute --write out.json --yes
```

```json
{"report_id": "R01", "items": [{"item_id": "I01", "status": "rated",
  "elements": [{"id": "E1", "verdict": "present"}, {"id": "E2", "verdict": "present"},
               {"id": "E3", "verdict": "present"}, {"id": "E4", "verdict": "partial"}]}]}
```

Exit 0 when every stored score matches (or none is stored), 1 on a mismatch, 2 on a refusal (an unknown verdict, an element
count or id set that differs from the rubric's elements of the item). An item with no elements keeps its stored score and is
reported `not_recomputed`; elements with no stored score are reported `no_stored_score`. `--write` names a new file and
writes only with `--yes`.

The recomputation trusts the stored `effective` and `verified` fields of each element: a hand edit of both passes the
check. It guards against a stored score that disagrees with its elements, not against edited elements; the rubric's
checklist is the protection against an element the model invents. A mismatch stops the run with `score_not_reproduced`,
whose message names the remedy: rerun the section scores with `grade_total.py RUBRIC GRADE --recompute --write OUT --yes`,
then rerun assemble on OUT.

## Limits

- Measured 2026-11-25 on two real reports: the titled figure and table numbers matched their lists, but a scanned
  page and a Simulink diagram, both without a title, were taken for untitled tables by the grid rule. They count
  nowhere and are listed as untitled; read them in `figures/untitled/`.
- The front pages are found from their headings; a list of figures whose heading sits mid-page is read from the
  contents pages that hold it. A front page the code does not know is passed through until the first body page.
- Local models only, so the quality of a grade is that of the adopted models. The audit and the batch
  calibration exist to expose a spread, not to remove it; the professor decides.
- The marker sentence test proves a sentence of a report never reaches an output or the ledger; it does not
  prove the models grade correctly.
- Reports are read from PDF text. `prepare` lists the pages that have no text layer (a scan) as empty pages;
  it does not read them from their pixels.
