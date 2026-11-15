---
executor: local-coder
tier: standard
bounds:
  max_rounds: 3
  max_tokens: 1500000
  plateau: 2
---

# Plan 8h - Judging the figures of a report

> **For agentic workers:** run by the local coder model through the driver (rule R39). Return every
> file you create in full. The test file runs as a script (`unittest.main()` at its end) and puts the
> parent folder of its own folder, and the folder holding the fixture helper, at the start of
> `sys.path`.

**Goal:** the figures of a report are extracted and measured by script, each is judged by the vision
model in its own fresh call on a fitted image, one contact sheet is judged for style consistency, and a
record per figure is returned with a ready failure comment for each failed criterion.

**Spec:** `spec.md` D6, D12, D14, "Data shapes" (the figures record), "Driver contracts".

## Global Constraints

Local models only (D2). The `call` is injected (R21). Every threshold comes from the criteria data
(R0). A model answer naming an id that was not sent is refused. Without a validated vision model the
script verdicts are still recorded and the model criteria are `not_run`. Every function carries the
Purpose, Inputs and Outputs header, and Raises when it raises on purpose.

## Review Focus

- A criterion that does not apply to the figure kind the model named becomes `not_applicable`, whatever
  the model said about it.
- A sent criterion missing from the answer becomes `not_run` with reason `no_answer`.
- The style criterion is judged once per report, written to `report_criteria`, never to a figure.
- No image reaches the model with a long edge above the configured maximum.

---

### Task 1: the module and its tests

**Files:**
- Create: `.claude/skills/work-ugs-audit/scripts/ugs_figures.py`
- Test: `.claude/skills/work-ugs-audit/scripts/Test/test_ugs_figures.py`

**Reads, do not modify:** `.claude/skills/figure-review/scripts/figure_extract.py`
(`extract(pdf, out_dir, min_area_pt2, background_threshold)` returns figure records),
`.claude/skills/figure-review/scripts/figure_checks.py` (`load_criteria`, `check(figures, pages,
body_font_size, criteria_doc)`, `body_font_size(pdf)`, `failure_comment(criterion_id, criteria,
language)`), `.claude/skills/figure-review/scripts/figure_image.py` (`fit_for_model(src, dst_dir,
max_long_edge, photo_colors, jpeg_quality)` and `contact_sheet(files, dst, max_long_edge)` return dicts
with a `file` relative to the folder), `.claude/skills/figure-review/assets/figure_criteria.json` (a
`criteria` list and an `extraction` object whose entries have a `value`; each criterion has `id`, `level`
`figure` or `report`, `judged_by` `script` or `model`, `applies_to`, `label_fr`, `label_en`,
`model_when_script_not_run`), `.claude/skills/figure-review/prompts/figure.md` (sections `## single` with
the slots `CAPTION`, `CITING_TEXT`, `SCRIPT_VERDICTS`, `CRITERIA`, and `## set` with `FIGURE_COUNT` and
`CRITERION`), `.claude/skills/figure-review/scripts/Test/_pdf_fixtures.py`,
`.claude/skills/work-ugs-audit/scripts/ugs_text.py` (`StepContext`, `fill`, `prompt_section`),
`.claude/skills/work-ugs-audit/scripts/ugs_bridge.py` (`NotRun`). The figure prompt is
`ctx.prompts["figure"]`; schemas are `ctx.schemas["figure"]` and `ctx.schemas["figure_set"]`. The module
adds the figure-review scripts folder to `sys.path` from its own location.

**Interfaces:**
- `citing_text(pages: list[str], number: int) -> str`: the first blank-line paragraph that mentions
  `Figure N` or `Fig. N` and does not start with it; empty when none.
- `figures_report(pdf: Path, report_dir: Path, report_id: str, pages: list[str], call, ctx,
  criteria_doc: dict, language: str, vision_ok: bool, existing: dict | None = None, on_figure=None) ->
  dict`: extracts into `report_dir/figures`, runs the script checks, and builds one record per figure
  with `figure_id`, `page`, `rect`, `file`, `kind`, `drawing_area_ratio`, `effective_dpi` (raster pixel
  width over the displayed width in inches, one decimal; else None), `caption`, `cited_in_text` and
  `criteria`. With `vision_ok` each figure not already in `existing` gets ONE call: its image fitted into
  `report_dir/model_images` with the `extraction` values, the prompt's `single` section filled with the
  caption, the citing text, the script verdicts as lines `id: verdict (reason)` and the criteria to judge
  (those with `judged_by` `model`, plus those with `model_when_script_not_run` whose script verdict is
  `not_run`) as lines `id | label | applies to: kinds`. The answer's `kind` is stored; each answered
  criterion is kept, except that one whose `applies_to` does not hold the named kind (and is not `all`)
  becomes `not_applicable`; an id that was not sent makes the answer invalid and the call is repeated up
  to `ctx.grade_retries` times, then every model criterion of that figure is `not_run` with reason
  `invalid_answer`. A failed criterion gets a `comment`: the ready failure comment in the report language,
  a space, and the reason. With two or more figures and `vision_ok`, ONE more call on a contact sheet
  fills `report_criteria["style_consistency"]` as `{verdict, reason}`. Without `vision_ok`, kind is
  `other`, model criteria are `not_run` with reason `vision_not_validated`, and no model call is made.
  Returns `{report_id, figures, report_criteria}`; calls `on_figure(figure_id, record)` after each figure.
  Unretryable `NotRun` kinds propagate.

**Tests to write first, each failing before the code exists** (fixture PDF from the helper, a fake
`call` recording prompts and image sizes):
`test_script_verdicts_are_recorded_without_any_model_call_when_vision_is_not_ok`;
`test_one_fresh_call_per_figure`; `test_only_model_criteria_are_sent_and_the_script_ones_are_explained`;
`test_a_criterion_not_applicable_to_the_named_kind_is_forced_not_applicable`;
`test_an_id_that_was_not_sent_is_refused_and_repeated`; `test_a_missing_answer_is_not_run_no_answer`;
`test_a_failed_criterion_carries_the_ready_comment_and_the_reason`;
`test_every_image_sent_is_within_max_long_edge`;
`test_style_consistency_is_one_call_per_report_and_never_in_a_figure`;
`test_one_figure_makes_no_style_call`; `test_citing_text_finds_the_paragraph_and_ignores_the_caption`;
`test_existing_figures_are_not_judged_again`; `test_on_figure_is_called_per_figure`;
`test_unreachable_propagates`.

- Test: `.claude/skills/work-ugs-audit/scripts/Test/test_ugs_figures.py`

- [ ] Step 1: write the tests, run the file, they fail (module absent).
- [ ] Step 2: write the module, run the file, every test passes.
