---
name: figure-review
description: "Review the figures of a report, paper or thesis (figure review, graphiques, axes, unités, légende, résolution, TikZ, draw.io, SVG, bitmap, PDF and LaTeX): measure what a script can measure, then give a model the figure to judge. Three entry points: the figures of a compiled PDF, the figures of a LaTeX source (vector and bitmap), and a single image. A vector figure a model cannot see (TikZ, draw.io, SVG, EPS, PDF) is rendered to PNG only when the caller asks with --render. Trigger on: figure review, review the figures, check the figures, revue des figures, axes and units, caption, resolution, TikZ validation."
allowed-tools: [Read, Bash]
---

# Figure review

One place that knows how to look at a figure. It serves the student-report audit (criteria scope
`undergraduate`) and the research auditors (scope `research`). It reads nothing from `work-ugs-audit`:
the callers hand it a PDF, a `.tex` file or an image.

Python is `.venv-skills`. PyMuPDF is pinned in `scripts/requirements.txt`. Every limit and threshold is in
`assets/figure_criteria.json`, each with its provenance, and a missing key is a named error.

## Who judges

Each criterion of `assets/figure_criteria.json` says `judged_by` and `needs`.

- `script`: measured by the code (drawing area, effective resolution, text size, numbering, call before the
  figure, source in the caption, label form). The model never overturns a measured verdict.
- `model`: judged by the calling harness's own model, on what `needs` names: `source` (the TikZ or LaTeX
  text), `image` (the pixels) or `either`.

## Entry point 1: the figures of a compiled PDF

1. `figure_extract.py --pdf REPORT.pdf --out DIR --min-area N --threshold N --json` finds each figure, crops it
   to a PNG and reads its caption and text sizes. The two numbers are `extraction.min_area_pt2` and
   `extraction.background_threshold`.
2. `figure_checks.py --figures FIGURES.json --pdf REPORT.pdf --criteria assets/figure_criteria.json --out
   CHECKS.json` runs the script criteria.
3. The model judges the rest with `prompts/figure.md` (`## single` for one figure, `## set` for the style
   across figures), one image at a time, kept under `max_long_edge` by `figure_image.py`.

## Entry point 2: the figures of a LaTeX source

`figure_render.py --tex MAIN.tex --out DIR [--render] [--json]` lists each `figure` environment and every
source it draws (inline or `\input` TikZ, draw.io beside its export, SVG, EPS, PDF, PNG, JPEG, GIF, BMP, TIFF,
WebP), subfigures included.

- Without `--render`: the list only. No tool is called and nothing is written. Vector figures then get source
  checks only (`figure_tex.text_checks(tex_text, criteria_doc)` for the label form, the call before the figure
  and a hard-coded number out of order, and the model for the `source` criteria).
- With `--render`: each source a model cannot read is turned into a PNG in `DIR`. PNG and JPEG are native:
  they are always shown, never re-encoded, and cut only when over `max_long_edge`. A document with only
  bitmaps costs no tool call.

| Source | Rendered with | When the tool is absent |
|---|---|---|
| TikZ | `pdflatex` on a `standalone` document carrying the paper's own preamble, then PyMuPDF | `not_run`, tool `pdflatex`, with the first LaTeX error (a missing macro is never judged as the student's fault) |
| draw.io | `paper2talk/scripts/fig_export.py` (imported, not copied) | `not_run`, tool `draw.io`; the page count of the file is reported |
| SVG, PDF | PyMuPDF | `not_run` with the reason |
| EPS | `epstopdf`, then PyMuPDF | `not_run`, tool `epstopdf` |
| GIF, BMP, TIFF, WebP | PyMuPDF | `not_run` with the reason |

A figure that cannot be rendered is `not_run` with the tool and the reason, and the rest of the run goes on.
No tool is substituted for a missing one. A source path that leaves the document's folder is refused.

## Entry point 3: a single image

`figure_image.py --src IMAGE --dst DIR --max-long-edge N --photo-colors N --jpeg-quality N --json` fits one
image for a model (PNG for line art, JPEG for a photo) and reports its estimated token cost. Then judge it
with `prompts/figure.md`, `## single`.

## Elements of a report (preparation)

The work-ugs-audit preparation calls `figure_extract.extract_elements` (added 2026-11-17, Issue 122), which returns
one record per element with a type. A table is found with PyMuPDF's table finder (`page.find_tables()`) and is never
judged as a figure; its cells come back as Markdown. Figure regions closer than `extraction.fragment_gap_pt` form one
figure, unless a title lies between them. A region that overlaps a table box by `extraction.table_overlap_ratio` is
dropped. A small image that recurs in the header or footer band on `extraction.repeat_min_pages` pages or more is a
`logo`. Each title (found by `element_labels.py` from the marker words of `assets/element_markers.json`) is attached to
at most one element. Every threshold is in `assets/figure_criteria.json` with its provenance, and the thresholds are
proposals to tune on the counts of the real reports. The vocabulary (title, legend, notes) is defined in the
work-ugs-audit skill.

## Limits

- Rendering needs `pdflatex`, `epstopdf` or draw.io on the machine. None is installed by this skill.
- **Rendering TikZ compiles the document's own LaTeX, which is untrusted.** Before any compile, a source or
  preamble using a file, shell or token primitive (`\input`, `\include`, `\openin`, `\write`, `\immediate`,
  `\csname`, `\catcode`, `\scantokens`, `\directlua`, and the packages `catchfile`, `filecontents`,
  `readarray`, `datatool`, `minted`, `shellesc`, `luacode`) is refused as `not_run`, so a paper whose
  preamble `\input`s a macro file is not rendered. The scan reads the text as written (a commented primitive
  is refused too), also refuses `^^` escapes, the kernel aliases `\@...`, `\RequirePackage`,
  `\IfFileExists`, `\includegraphics` and `\pgfimage` (a local file would be drawn into the image sent to a
  model), and ignores case. The compile runs with `-disable-write18`, in a throwaway folder, under a timeout,
  with `openin_any=p` and `openout_any=p`. Measured 2026-11-14: MiKTeX 26.2 ignores those two variables (a
  file outside the working folder was still read), so on MiKTeX the refusal list is the only guard. A list is
  not a sandbox and a determined author can bypass it: a file-reading package such as `pgfplotstable`,
  `csvsimple` or `pdfpages` is not on it. The boundary that makes rendering untrusted LaTeX safe is the final
  system of Issue 107 (a source scanner, an allowlist and a confined execution). Until it exists, do not use
  `--render` on a document you do not trust.
- A TikZ picture is compiled with the paper's preamble written in the `.tex` file. A macro defined in a file
  the preamble `\input`s is not carried and gives `not_run` naming the missing macro.
- draw.io exports one image per file. Whether it is the first page is not verified (R15); the report gives
  the page count.
- `text_checks` covers three criteria. The other research criteria are judged by the model or by the calling
  auditor's own steps.
