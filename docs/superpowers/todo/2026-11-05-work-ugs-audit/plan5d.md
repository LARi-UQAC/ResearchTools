---
executor: local-coder
tier: standard
bounds:
  max_rounds: 3
  max_tokens: 1500000
  plateau: 2
---

# Plan 5d - Fitting images for a model

> **For agentic workers:** run by the local coder model through the driver (rule R39). Return every
> file you create in full. The test file runs as a script (`unittest.main()` at its end) and puts the
> parent folder of its own folder at the start of `sys.path`.

**Goal:** every image sent to a model is cropped already, downscaled to a long edge of at most the
configured size, written as PNG for line art or JPEG for a photo, and its token cost is estimated; a
set of figures can be tiled into one contact sheet.

**Spec:** `spec.md` D6, D14. Token cost is the number of 28-pixel patches: the width over 28 rounded up
times the height over 28 rounded up (Anthropic Vision documentation, read 2026-11-05); the format does
not change it, and a local model's own cost is measured elsewhere by the vision probe.

## Global Constraints

Library: PyMuPDF only (pixmaps, no other imaging library). Parameters, not constants: the long edge,
the colour count above which an image is a photo, and the JPEG quality are passed by the caller, who
reads them from the figure criteria data. Never upscale. Every output path is resolved inside the
destination folder (R24). Every function carries the Purpose, Inputs and Outputs header, and Raises
when it raises on purpose.

## Review Focus

- An image smaller than the long edge is written at its own size.
- A flat chart with few colours stays PNG, a gradient photograph becomes JPEG.
- The estimate for a 1092 by 819 image is 39 times 30 patches, 1170.
- The contact sheet is one image whose long edge does not exceed the limit, whatever the figure count.

---

### Task 1: the module and its tests

**Files:**
- Create: `.claude/skills/figure-review/scripts/figure_image.py`
- Test: `.claude/skills/figure-review/scripts/Test/test_figure_image.py`

**Interfaces:**
- `estimated_tokens(width: int, height: int) -> int`: the patch formula above.
- `fit_for_model(src: Path, dst_dir: Path, max_long_edge: int, photo_colors: int, jpeg_quality: int) ->
  dict`: downscales so the long edge is at most `max_long_edge` and never upscales; the output is JPEG
  at `jpeg_quality` when the image holds more than `photo_colors` distinct colours, else PNG. Returns
  `file` (path relative to `dst_dir`), `format` (`png` or `jpeg`), `width`, `height`,
  `estimated_tokens`. Raises `ImageError` (a `ValueError`) for a missing or unreadable source.
- `contact_sheet(files: list[Path], dst: Path, max_long_edge: int) -> dict`: tiles all the images into
  one near-square grid, each tile scaled to fit its cell, the whole within `max_long_edge`; returns
  `file`, `tiles`, `width`, `height`, `estimated_tokens`. An empty list raises `ImageError`.
- `main(argv)`: `--src FILE --dst DIR --max-long-edge N --photo-colors N --jpeg-quality N [--json]`
  prints the dict of `fit_for_model`. Exit 0, 2 on a refusal, 1 on a failure.

**Tests to write first, each failing before the code exists:**
`test_fit_downscales_to_the_long_edge_and_never_upscales`; `test_line_art_is_png_and_photo_is_jpeg`;
`test_estimated_tokens_follow_the_28_pixel_patch_formula` (1092 by 819 gives 1170);
`test_contact_sheet_is_one_image_within_the_long_edge`; `test_contact_sheet_counts_its_tiles`;
`test_missing_source_raises_image_error`; `test_empty_contact_sheet_raises_image_error`;
`test_output_stays_inside_the_destination_folder`.
The test builds its small images itself with PyMuPDF pixmaps (a flat two-colour chart, a gradient).

- Test: `.claude/skills/figure-review/scripts/Test/test_figure_image.py`

- [ ] Step 1: write the tests, run the file, they fail (module absent).
- [ ] Step 2: write the module, run the file, every test passes.
