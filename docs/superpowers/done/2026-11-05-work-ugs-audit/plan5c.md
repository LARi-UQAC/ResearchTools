---
executor: local-coder
tier: standard
bounds:
  max_rounds: 3
  max_tokens: 1500000
  plateau: 2
---

# Plan 5c - Figure extraction with the drawing-area ratio

> **For agentic workers:** run by the local coder model through the driver (rule R39). Return every
> file you create in full. The test file runs as a script (`unittest.main()` at its end) and puts the
> parent folder of its own folder, and the folder holding the fixture helper, at the start of
> `sys.path`.

**Goal:** every figure of a PDF is located, counted, cut out as a PNG file and measured, whether it is a
raster image or a chart drawn with vector paths.

**Spec:** `spec.md` D6, D14, "Data shapes" (the figures record).

## Global Constraints

Library: PyMuPDF only. The two thresholds are parameters (no configuration file here): the caller reads
their values from the figure criteria data and passes them. Every output path is resolved inside the
output folder (R24). Nothing printed carries text from the report. Every function carries the Purpose,
Inputs and Outputs header, and Raises when it raises on purpose.

## Review Focus

- A vector chart (drawn paths, no embedded image) is still found, through clusters of drawings.
- A tiny logo under `min_area_pt2` is not a figure.
- A chart filling a small part of a large frame has a ratio below 0.7, a full chart above it.
- A figure without a caption has a null caption; a French caption beginning `Figure` is found.

---

### Task 1: the module and its tests

**Files:**
- Create: `.claude/skills/figure-review/scripts/figure_extract.py`
- Test: `.claude/skills/figure-review/scripts/Test/test_figure_extract.py`

**Reads, do not modify:** `.claude/skills/figure-review/scripts/Test/_pdf_fixtures.py` (its
`make_report(path, pages)` builds a fictitious PDF; a page dict may hold `text`, `image`,
`vector_chart`, `logo`, `caption`, `font_size`).

**Interfaces:**
- `extract(pdf: Path, out_dir: Path, min_area_pt2: float, background_threshold: int) -> list[dict]`: one
  record per figure, in page order, with `figure_id` (`F01`, `F02`...), `page` (1-based), `rect` (four
  numbers in points), `file` (the PNG path relative to `out_dir`, written inside `out_dir`), `source`
  (`raster` or `vector`), `pixel_size` (width and height in pixels, raster only, else absent),
  `drawing_area_ratio` (0 to 1, three decimals), `text_sizes` (vector figures only: the size in points
  of every text span whose box lies inside the rectangle, an empty list when there is none) and
  `caption` (the nearest text block below, else above, that starts with `Figure`, `Fig.` or `Fig `,
  else null). A raster figure is an embedded image whose
  displayed rectangle is at least `min_area_pt2`. A vector figure is a cluster of drawings, merged
  when their rectangles touch or overlap, whose union is at least `min_area_pt2`, with no embedded image
  inside it. The figure is rendered to PNG from the page at 150 dots per inch, clipped to its rectangle.
- `drawing_area_ratio(samples: bytes, width: int, height: int, n: int, threshold: int) -> float`: the
  area of the bounding box of the pixels darker than `threshold` in any channel, over the image area.
  An image with no such pixel gives 0.0.
- `main(argv)`: `--pdf FILE --out DIR [--min-area N --threshold N] [--json]`; it prints counts per page
  and the figure ids, never a caption. Exit 0, 2 on a refusal (missing file, output outside the output
  folder), 1 on a failure.

**Tests to write first, each failing before the code exists:**
`test_counts_and_pages_of_raster_and_vector_figures`; `test_logo_under_min_area_is_ignored`;
`test_png_files_are_written_inside_out_dir`; `test_ratio_of_a_full_chart_is_above_0_7`;
`test_ratio_of_a_small_chart_in_a_large_frame_is_below_0_7`; `test_caption_found_below_and_in_french`;
`test_figure_without_caption_has_null_caption`;
`test_raster_record_carries_pixel_size_and_vector_record_does_not`;
`test_vector_record_carries_the_sizes_of_its_labels_and_raster_does_not`;
`test_blank_image_has_ratio_zero`; `test_stdout_never_carries_a_caption`;
`test_missing_pdf_is_a_refusal`.

- Test: `.claude/skills/figure-review/scripts/Test/test_figure_extract.py`

- [ ] Step 1: write the tests, run the file, they fail (module absent).
- [ ] Step 2: write the module, run the file, every test passes.
