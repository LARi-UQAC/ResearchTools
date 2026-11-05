---
executor: local-coder
tier: standard
bounds:
  max_rounds: 3
  max_tokens: 1500000
  plateau: 2
---

# Plan 5 - Reading reports: pseudonymous ids, Markdown per page, figures

> **For agentic workers:** dispatched to `local-coder` with a `PLAN:` line naming this file. Tests are
> the oracle; tick `progress.md`. No audit inside the wrapper (R38).

**Goal:** Every report in a folder gets a stable id, a Markdown file per page and its figures extracted
as PNG with position and drawing-area ratio, all from fictitious-PDF tests.

**Architecture:** `report_prepare.py` assigns ids and converts each page with `pymupdf4llm`.
`figure_extract.py` uses PyMuPDF image and drawing rectangles, renders each figure to PNG, and measures
the share of the figure occupied by non-background pixels from the pixmap samples. A test helper builds
fictitious PDFs on the fly.

**Tech Stack:** PyMuPDF 1.27.2.3, pymupdf4llm 1.27.2.3 (both already pinned in `.venv-skills` through
`extract-statistic`), `unittest`.

**Spec:** `spec.md` D2, D6, D7, "Data shapes" (`figures.json`, working folder).

## Global Constraints

`spec.md` "Constraints". The same pins as the other skills (one pin per library per environment,
`verify-python-libs.ps1`). Every output path resolved inside the working folder (R24). File names of
reports appear only in `ids.json`; nothing printed carries one. Accented text survives.

## Review Focus

- A report folder holding a `.zip` or a non-PDF file: skipped and counted, never an id.
- Re-running prepare after one report was added: existing ids unchanged, the new one gets the next id.
- A page with no text (scanned figure page): Markdown file written empty and flagged, not an error.
- A vector chart (drawn paths, no embedded image): still found as a figure through drawing clusters.
- A tiny logo under `figure.min_area_pt2`: not a figure.

---

### Task 1: fixtures and `report_prepare.py`

**Files:**
- Create: `.claude/skills/figure-review/scripts/Test/_pdf_fixtures.py`
- Create: `.claude/skills/work-ugs-audit/scripts/report_prepare.py`
- Test: `.claude/skills/work-ugs-audit/scripts/Test/test_report_prepare.py`
- Create: `.claude/skills/work-ugs-audit/scripts/requirements.txt`
- Create: `.claude/skills/figure-review/scripts/requirements.txt`
- Modify: `scripts/lib/rt-python-requirements.json`
- Modify: `docs/manual/02-profiles.md`

**Interfaces:**
- Produces:
  - `_pdf_fixtures.make_report(path: Path, pages: list[dict]) -> Path`: each page dict may hold `text`
    (accented French allowed), `image` (draw a raster chart with axis titles and a legend), `vector_chart`
    (drawn lines), `logo` (tiny image), `caption`. Names in fixtures are fictitious (R34).
  - `report_prepare.prepare(reports_dir: Path, work_dir: Path) -> list[dict]`: one dict per report,
    `report_id`, `pages`, `empty_pages` (list of numbers); writes `ids.json` (`{id: file name}`,
    existing ids kept) and `R01/pages/p001.md` and so on. Ids follow sorted file names. Raises
    `PrepareError` when `work_dir` resolves outside `reports_dir`.
  - `main(argv)`: `--reports DIR --work DIR [--dry-run] [--json]`; the JSON line carries ids and counts
    only. Exit 0, 2 refusal, 1 failure.
  - `requirements.txt` pins `PyMuPDF==1.27.2.3` and `pymupdf4llm==1.27.2.3` with the AGPL note; the
    `figure-review` copy pins `PyMuPDF==1.27.2.3` only. The fixture helper lives in `figure-review`
    (the lower layer) and `work-ugs-audit` tests import it from there, never the reverse.

- [ ] **Step 1: Write the failing tests:** `test_ids_follow_sorted_names_and_are_stable_on_rerun`;
  `test_non_pdf_files_are_skipped_and_counted`; `test_one_markdown_file_per_page_with_accents_kept`;
  `test_an_empty_page_is_flagged`; `test_work_dir_outside_reports_is_refused`;
  `test_stdout_never_carries_a_file_name` (fixture file named with a fictitious student name);
  `test_dry_run_writes_nothing`.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement** the fixture helper and `report_prepare.py`; write `requirements.txt`; add the
  file to the `.venv-skills` entry of `rt-python-requirements.json` with its `why`; run
  `scripts/docs/python_libs.py --write` to refresh the chapter 02 tables, then `--check`. Expected: exit 0.
- [ ] **Step 4: Run** the suite. Expected: all OK. Run `pip-audit -r` on the new file; record the result
  in `progress.md`.
- [ ] **Step 5: Commit:** `feat(work-ugs-audit): pseudonymous ids and Markdown per page (#104)`.

### Task 2: `figure_extract.py`

**Files:**
- Create: `.claude/skills/figure-review/scripts/figure_extract.py`
- Test: `.claude/skills/figure-review/scripts/Test/test_figure_extract.py`
- Modify: `.claude/rules/testing.md`

**Interfaces:**
- Consumes: the fixtures above. No configuration file: the two thresholds are parameters, whose values
  live in `figure-review/assets/figure_criteria.json` (`extraction` block, plan 6) and are passed by the
  caller; tests pass their own.
- Produces:
  - `extract(pdf: Path, out_dir: Path, min_area_pt2: float, background_threshold: int) -> list[dict]`:
    one record per figure with `figure_id`,
    `page`, `rect`, `file` (relative PNG path), `source` (`raster` or `vector`), `pixel_size` (width,
    height, raster only), `drawing_area_ratio` (0 to 1, 3 decimals), `caption` (text block starting with
    Figure, Fig. or Figure in French, nearest below or above, or null). Plan 6 adds the other measured
    criteria from these fields.
  - `drawing_area_ratio(samples, width, height, n, threshold: int) -> float`: bounding box of pixels
    darker than `threshold` in any channel, over the image area.
  - `fit_for_model(src: Path, dst_dir: Path, max_long_edge: int, photo_colors: int, jpeg_quality: int)
    -> dict`: the image the model receives, to limit tokens (Anthropic Vision doc, read 2026-11-05: cost is
    `ceil(w/28) * ceil(h/28)` visual tokens, the format does not change it). Cropped to the figure already,
    downscaled so the long edge is at most `max_long_edge` (never upscaled), written as PNG for line art
    and as JPEG when the image holds more than `photo_colors` distinct colours (a photo). Returns `file`,
    `format`, `width`, `height`, `estimated_tokens` (the formula above, for the cloud).
  - `contact_sheet(files: list[Path], dst: Path, max_long_edge: int) -> dict`: all the figures of one
    report tiled into ONE image within `max_long_edge`, for the per-report style criterion (one image
    instead of N). Returns `file`, `tiles`, `estimated_tokens`.
  - `main(argv)`: `--pdf FILE --out DIR [--json]`, prints counts per page and ids.

- [ ] **Step 1: Write the failing tests:** `test_counts_and_pages_of_raster_and_vector_figures`;
  `test_logo_under_min_area_is_ignored`; `test_png_files_written_inside_out_dir`;
  `test_ratio_of_a_full_chart_is_above_0_7` and `test_ratio_of_a_small_chart_in_a_large_frame_is_below_0_7`;
  `test_caption_found_below_and_in_french`; `test_figure_without_caption_has_null_caption`;
  `test_raster_record_carries_pixel_size_and_vector_record_does_not`;
  `test_fit_downscales_to_the_long_edge_and_never_upscales`; `test_line_art_is_png_and_photo_is_jpeg`;
  `test_estimated_tokens_follow_the_28_pixel_patch_formula` (1092x819 gives 39 x 30 = 1170);
  `test_contact_sheet_is_one_image_within_the_long_edge`.
- [ ] **Step 2: Run.** Expected: FAIL. **Step 3:** implement. **Step 4: Run.** Expected: all OK.
- [ ] **Step 5: Add** both script lines to `.claude/rules/testing.md`, tick `progress.md`.
- [ ] **Step 6: Commit:** `feat(work-ugs-audit): figure extraction with drawing-area ratio (#104)`.
