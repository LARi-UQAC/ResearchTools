---
executor: cloud
tier: standard
bounds:
  max_rounds: 3
  max_tokens: 1500000
  plateau: 2
---

# Plan 9 - `figure-review` for LaTeX: vector and bitmap figures, optional rendering

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans (session). The SKILL.md is
> authored with superpowers:writing-skills and skill-creator:skill-creator. `progress.md` is the ledger.

**Goal:** A `.tex` document mixing TikZ, draw.io, SVG, EPS, PDF and bitmap figures is read figure by
figure; vector sources get their source checks, bitmaps their visual review, and any figure in a format a
model cannot see is rendered to PNG **when the caller asks for it**.

**Architecture:** `figure_tex.py` finds each figure and classifies its source. `figure_render.py` turns
one figure into a model-native PNG through the tool that fits its format, and reports `not_run` with the
reason when that tool is absent. Rendering is an option (`--render`): without it, vector figures get
source checks only and bitmaps go to the model as they are. `figure-review` reads nothing from
`work-ugs-audit`.

**Tech Stack:** Python standard library, PyMuPDF 1.27.2.3 (pinned in plan 5), `pdflatex` and `epstopdf`
from the TeX installation, the draw.io export of `paper2talk/scripts/fig_export.py` (imported, not
copied, R18), `unittest` with every subprocess and `shutil.which` patched.

**Spec:** `spec.md` item 4, D6, D12, D13; design sections 7.4 and 7.5.

## Global Constraints

`spec.md` "Constraints". Model-native formats: PNG and JPEG (both accepted by the Claude API and by an
Ollama vision model). Token cost depends on pixel size, not format (Anthropic Vision doc, 2026-11-05),
so every image a model receives, native or rendered, goes through `fit_for_model` (plan 5): long edge
at most `max_long_edge` 1568 (owner), PNG for line art, JPEG for a photo. A missing tool is a stated `not_run`,
never a silent skip and never a substitute tool (R8). Every rendered file goes into an output folder the
caller gives, resolved and confined (R24); the source figure is never modified.

## Review Focus

- A TikZ figure using a library or a macro defined in the preamble: rendered with the document's own
  preamble, or `not_run` naming the missing macro, never a broken image judged as the student's fault.
- A `.drawio` file with several pages: each page rendered, or the first with the count reported.
- An SVG with embedded fonts or external links: rendered, or `not_run` with the reason.
- A document with only bitmaps: `--render` changes nothing and costs no tool call.
- `pdflatex` or draw.io absent: the figure is `not_run` with the tool named, the rest of the run goes on.

---

### Task 1: research criteria, LaTeX reader, renderer, SKILL.md

**Files:**
- Create: `.claude/skills/figure-review/SKILL.md`
- Modify: `.claude/skills/figure-review/assets/figure_criteria.json`
- Create: `.claude/skills/figure-review/scripts/figure_tex.py`
- Test: `.claude/skills/figure-review/scripts/Test/test_figure_tex.py`
- Create: `.claude/skills/figure-review/scripts/figure_render.py`
- Test: `.claude/skills/figure-review/scripts/Test/test_figure_render.py`

**Interfaces:**
- Consumes: `figure_checks.check`, `load_criteria` (plan 6); `fig_export.export(src, out, scale)` and
  `fig_export.find_drawio()` from `paper2talk`.
- Produces:
  - `figure_criteria.json` gains `scope: research` entries: the nine TikZ rules of `.claude/CLAUDE.md`
    "Figures" (judged on the TikZ source, `applies_to: [tikz]`) plus every research figure check of the
    four auditors not already among the 22 (inventory in plan 10, step 1, is done first here by reading
    the agents). Each entry may carry `flag`, the auditor's exact bracket text. A new key per criterion,
    `needs` (`source`, `image`, `either`), says whether it is judged on code or on pixels.
  - `figure_tex.figures(tex_text: str, base_dir: Path | None) -> list[dict]`: each `figure` environment
    with `label`, `caption`, `position`, and `sources[]`, each `{kind, path_or_code}` where `kind` is
    `tikz` (inline or `\input` of a `.tikz`/`.tex`), `drawio`, `svg`, `eps`, `pdf`, `png`, `jpg`, `gif`,
    `bmp`, `tiff`, `webp`, or `unknown`. A figure may hold several sources (subfigures).
  - `figure_tex.references(tex_text: str) -> dict` (`\ref`, `\autoref`, `\cref` offsets per label) and
    `figure_tex.text_checks(tex_text, criteria_doc) -> list[dict]` (numbering, called before appearing,
    label form), same record shape as `figure_checks.check`.
  - `figure_render.native(kind: str) -> bool` (true for `png`, `jpg`).
  - `figure_render.render(source: dict, out_dir: Path, preamble: str | None, *, which=shutil.which,
    run=subprocess.run, timeout: float, max_long_edge: int) -> dict` with `status` (`rendered`,
    `native`, `not_run`), `file` (path or null), `format`, `estimated_tokens`, `reason`, `tool`. TikZ: a
    `standalone` document with the given preamble through `pdflatex`, then page 1 rasterised with
    PyMuPDF. draw.io: `fig_export.export`. SVG and PDF: PyMuPDF. EPS: `epstopdf` then PyMuPDF. GIF, BMP,
    TIFF, WebP: PyMuPDF pixmap. A native PNG or JPEG is not re-encoded but is still downscaled when over
    `max_long_edge`. Every result then goes through `figure_extract.fit_for_model`.
  - `figure_render.main(argv)`: `--tex FILE --out DIR [--render] [--json]`; without `--render` it lists
    sources and kinds only. Timeout and DPI of the rendering in `figure_criteria.json`'s `extraction`
    block (`render_dpi`, `render_timeout_s`, each `{value, provenance}`).

- [ ] **Step 1: Write the failing tests.** `test_figure_tex.py`: `test_mixed_document_lists_each_source_kind`
  (inline TikZ, `\input{fig.tikz}`, `.drawio` via `\includegraphics` of its export name, `.svg` through
  `\includesvg`, `.pdf`, `.png`, `.jpg`); `test_subfigures_give_several_sources`; `test_input_files_are_followed`;
  `test_ref_autoref_cref_all_count`; `test_figure_cited_after_it_appears_fails`;
  `test_label_not_three_words_fails`. `test_figure_render.py`: `test_png_and_jpg_are_native_and_not_rendered`;
  `test_tikz_is_compiled_with_the_document_preamble` (asserts the `pdflatex` argv and the standalone
  text); `test_drawio_goes_through_fig_export`; `test_missing_tool_is_not_run_naming_it`;
  `test_timeout_is_not_run_with_reason`; `test_bmp_is_converted_to_png` (real PyMuPDF on a generated
  bitmap); `test_without_render_flag_no_subprocess_is_called`; `test_output_outside_out_dir_is_refused`;
  `test_a_large_native_png_is_downscaled_to_max_long_edge`; `test_rendered_tikz_is_png_and_a_photo_is_jpeg`;
  `test_criteria_file_has_research_entries_and_needs_key`.
- [ ] **Step 2: Run** both with `.venv-skills\Scripts\python.exe`. Expected: FAIL.
- [ ] **Step 3: Implement** both modules and extend `figure_criteria.json`.
- [ ] **Step 4: Run** both. Expected: OK. One manual check, recorded in `progress.md`: render a fictitious
  TikZ figure and a fictitious `.drawio` file on this machine with `--render`.
- [ ] **Step 5: Write `SKILL.md`**: first sentence carries figure review, graphiques, axes, unités,
  légende, résolution, TikZ, draw.io, SVG, bitmap, PDF and LaTeX; it states the option, the native
  formats, the three entry points (PDF figures, LaTeX figures, a single image) and who judges.
- [ ] **Step 6: Commit:** `feat(figure-review): LaTeX figures, vector and bitmap, optional rendering (#104)`.
