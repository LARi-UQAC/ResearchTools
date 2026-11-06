---
executor: local-coder
tier: standard
bounds:
  max_rounds: 3
  max_tokens: 1500000
  plateau: 2
---

# Plan 5a - Fictitious PDF fixtures

> **For agentic workers:** run by the local coder model through the driver (rule R39). Return every
> file you create in full. The test file runs as a script (`unittest.main()` at its end) and puts the
> parent folder of its own folder at the start of `sys.path`, then imports the helper from the same
> folder as itself.

**Goal:** one helper builds fictitious student-report PDFs on the fly, so every later suite of the
PDF scripts has realistic input and no real report ever enters the repository (R34).

**Spec:** `spec.md` D6, D7, "Constraints". Library: PyMuPDF only (already installed).

## Global Constraints

All names, titles and sentences in the fixtures are invented. Accented French text must survive.
The helper writes only the path it is given. Every function carries the Purpose, Inputs and Outputs
header.

## Review Focus

- A page asked to hold an image, a vector chart, a logo and a caption holds all four, and a reader can
  tell them apart.
- Accented text extracted from the fixture equals what was written.

---

### Task 1: the helper and its test

**Files:**
- Create: `.claude/skills/figure-review/scripts/Test/_pdf_fixtures.py`
- Test: `.claude/skills/figure-review/scripts/Test/test_pdf_fixtures.py`

**Interfaces:**
- `make_report(path: Path, pages: list[dict]) -> Path`: writes a PDF with one page per dict and returns
  `path`. A page dict may hold these optional keys: `text` (a string, accented French allowed, drawn as
  body text near the top), `image` (draw a raster chart of at least 600 by 400 pixels with an x axis
  title, a y axis title with a unit, and a legend, inserted as an embedded image), `vector_chart`
  (a chart made only of drawn lines and rectangles, no embedded image, with a few text labels),
  `logo` (an embedded image of about 40 by 40 pixels), `caption` (a line of text placed just below the
  last figure of the page, for example `Figure 1 - Courbe de réponse`), `font_size` (body size in points,
  default 11). The page size is A4 portrait. The raster chart is built with PyMuPDF only (a pixmap
  drawn pixel row by pixel row, or a small drawing rendered to a pixmap), never with another library.
- `image_info(path: Path) -> list[dict]`: for tests, one dict per embedded image with `page`, `width`,
  `height`.

**Tests to write first, each failing before the code exists:**
`test_page_count_matches_the_page_list`; `test_accented_text_is_extracted_unchanged`;
`test_image_page_holds_one_embedded_image_of_the_requested_size`;
`test_vector_chart_page_holds_drawings_and_no_embedded_image`; `test_logo_is_a_small_embedded_image`;
`test_caption_is_found_below_the_figure` (the caption's top is lower on the page than the figure's
bottom); `test_font_size_is_applied`; `test_make_report_writes_only_the_given_path` (the folder holds
exactly that file afterwards).

- Test: `.claude/skills/figure-review/scripts/Test/test_pdf_fixtures.py`

- [ ] Step 1: write the tests, run the file, they fail (helper absent).
- [ ] Step 2: write the helper, run the file, every test passes.
