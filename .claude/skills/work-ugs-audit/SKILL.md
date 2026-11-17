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
`excluded` folder and they are never graded. (5) Elements are extracted with a type (`figure`, `table`, `logo`): a
table is never judged as a figure, its Markdown is added to the page text the models read, a diagram made of separate
regions is one figure, and a logo is not judged. (6) Each table is added to its page text.

Vocabulary, the same in the code and the annex. A **title** names the whole figure or the whole table and starts with
a marker word (Figure, Fig., Tableau, Table): a figure title is usually below the figure, a table title above it. A
**legend** is the text inside a figure that explains its series or symbols; a table has no legend. **Notes** are the
lines under a table (Note, Source, an asterisk). The element type is `figure`, `table` or `logo`; only a `figure` is
judged.

Grades. Each item of `grade.json` keeps every field the model gave, above all the score. The `validation` field holds
`ok` or the code of the refusal (`quote_not_found`, `evidence_missing`, `score_above_max`, `unknown_status`, and the
others of `GRADE_CODES` in `ugs_grade.py`). A refused proof keeps its score and counts in the totals, with its label in
the annex. A score that cannot be used gives status `not_run`, a null score, and the raw value in `model_score`. The
ledger line carries the code as its note, and `attempts` counts the tries. The audit prompt never receives these
fields.

The annex is written in the document language (labels in `assets/annex_labels.json`) and its table fits the page. Its
last section holds five checks computed by `crossref_checks.py` on the report's own text and elements: every figure
cited, every table cited, figure numbers increasing, table numbers increasing, equation numbers increasing. Each check
gives `ok`, `not_ok` or `not_applicable` with the numbers concerned only. A gap in the numbers lists at most
`checks.max_gap_numbers` numbers, and a number above `checks.max_number` is refused.

Local actions. While it runs, each local role emits action records built by `ugs_events.py` from identifiers only:
the report id, the item id, a page range, the base name of an output file, a mark. No prompt, reply, quote or report
text is recorded. `rt-observe` shows them as the steps of the role's lane.

## Driver

`scripts/ugs_driver.py`, all subcommands take `--dry-run` and `--json` and print one JSON object per line.

| Subcommand | Does |
|---|---|
| `prepare --reports DIR --rubric FILE --type T` | ids and pages of every PDF, takes the rubric as written (JSON is validated, a Markdown or text grid with numbered sections is split by the code and every section keeps its exact text, an unnumbered or PDF rubric is restructured by the model, which may not remove a line), writes the rubric, its Markdown and the ledger. There is no confirmation step |
| `run --work DIR --reports DIR [--loop N] [--resume] [--only R01]` | runs the steps of every report in id order, resumable |
| `batch --work DIR --loop N [--allow-third]` | spread of the totals against the calibration targets, opens the next loop when out of band |
| `status --work DIR` | ledger counts and the first open step |

Exit codes: 0 done, 1 a model step could not run (stop, resume later), 2 refusal, 3 batch out of band. A third
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
`other` (tables such as a budget or a timesheet, a Kanban board, a screenshot). The kind decides which criteria are
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
`pdf_annex.py`, `vision_probe.py`. Each has an offline test in `scripts/Test/`.

## Limits

- Local models only, so the quality of a grade is that of the adopted models. The audit and the batch
  calibration exist to expose a spread, not to remove it; the professor decides.
- The marker sentence test proves a sentence of a report never reaches an output or the ledger; it does not
  prove the models grade correctly.
- Reports are read from PDF text. `prepare` lists the pages that have no text layer (a scan) as empty pages;
  it does not read them from their pixels.
