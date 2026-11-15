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

## Driver

`scripts/ugs_driver.py`, all subcommands take `--dry-run` and `--json` and print one JSON object per line.

| Subcommand | Does |
|---|---|
| `prepare --reports DIR --rubric FILE --type T` | ids and pages of every PDF, validates or normalises the rubric (JSON, Markdown, text, PDF text), writes the rubric, its Markdown and the ledger |
| `run --work DIR [--loop N] [--resume] [--only R01]` | runs the steps of every report in id order, resumable |
| `batch --work DIR --loop N [--allow-third]` | spread of the totals against the calibration targets, opens the next loop when out of band |
| `status --work DIR` | ledger counts and the first open step |

Exit codes: 0 done, 1 a model step could not run (stop, resume later), 2 refusal, 3 batch out of band. A third
loop needs `--allow-third` after the professor's answer.

## Files

The work folder is `_correction/` inside the reports folder. It holds `ids.json`, `rubric.json`, `rubric.md`,
`ledger.md`, `loop_state.json`, `vision_probe.json`, one folder per report with its pages, figures and model
images, and one folder per loop with the grades, language and figure results, annotations, totals, the
annotated PDF and the batch report. Every output path is resolved inside the work folder (R24).

## Models

Three roles, `ugs-grader`, `ugs-auditor` and `ugs-vision`, resolved by `model_resolver.py`; no tag is written
here. The owner adopts each once:
`model_resolver.py --adopt-role ugs-grader <tag> --reason "<measurement>"`, the same for the other two. A role
not adopted stops the step and names it. There is no fallback and no cloud grading. `vision_probe.py` measures
what the vision role reads on a chart before figures are graded.

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
