---
name: word2latex
description: "Convert a Word .docx template (Mitacs, CRSNG, FRQNT, UQAC, partner forms) into a faithful LaTeX source. Use when the user asks to translate a Word gabarit to LaTeX, when a generated .tex must match a .docx visually, or for /word2latex. Drives pandoc + applies the standard patch sequence (Arial, full-grid tables, centered sections, landscape geometry, first-page banner). Delegates the actual patch work to the word-to-latex agent."
allowed-tools: [Read, Write, Edit, Bash]
permissions: [read, write]
---

# word2latex Skill

## Prerequisites

Before running, verify:

1. `pandoc` installed: `pandoc --version`
2. `python-docx` available (used by `docx_inspect.py`): `python -c "import docx; print('OK')"` — if missing, `pip install python-docx`
3. `pdflatex` and `pdftoppm` reachable from the shell (any TeX distribution + poppler)
4. **LaTeX compiler.** Two cases, decided by how close to Word the output must be:

   | Output required | Compiler | Fonts | Declared in the `.tex` |
   |---|---|---|---|
   | Readable LaTeX version of the form (default) | `pdflatex` | `helvet` stands in for Arial | nothing |
   | Visually identical to the Word file | `xelatex` (with `fontspec`, MiKTeX or TeX Live) | the real Windows fonts installed on the machine: Arial, Calibri, Segoe UI Symbol, MS Gothic, Cambria Math | `% !TEX program = xelatex` on line 1 |

   With `latexmk` (and VS Code LaTeX Workshop, which calls it), the choice is made per file
   by `scripts/latexmk_engine.pl` through a one-line project `latexmkrc` (see Step 5), so a
   folder can mix both. Check before building: `xelatex --version` and
   `fc-list | findstr /i "Arial Calibri"` (or the Fonts control panel).
4. The `.docx` file is closed in Word (otherwise the `~$` lock file blocks reads)

## Mode dispatch

`$ARGUMENTS` is the path to the `.docx` file (or a directory containing exactly one `.docx`).

```
/word2latex <path-to-docx>
```

Optional flags appended after the path:

| Flag | Effect |
|---|---|
| `--engine=pdflatex` (default) | Use `helvet` to approximate Arial |
| `--engine=xelatex` | Use `fontspec` with native Arial |
| `--no-banner` | Skip the first-page TikZ banner block (use for plain documents without a colored header strip) |
| `--legal-landscape` | Enable the Legal-landscape macros (14×8.5 in) — needed only if the docx has `<w:pgSz w:w="20160" w:h="12240">` |
| `--bibliography` | Manuscript mode: extract the numbered bibliography to a first-pass `.bib`, rewrite inline citations to `\cite`, then validate via `/bibclean` + `/scopus`. Opt-in; off for form gabarits. |

## Workflow

### Step 1 — Inspect the .docx

Run the inspector to extract every value the LaTeX preamble needs:

```powershell
cd "<docx directory>"
python "<workspace>/.claude/skills/word2latex/scripts/docx_inspect.py" <file.docx>
```

The script prints a structured report with:

- Default font + size
- Line spacing
- Each `<w:sectPr>` (orientation, page size, margins, header/footer references)
- Heading1 / Heading2 / Title styles (font, size, color, alignment)
- Table border defaults
- Image catalog (path, dimensions, dominant color, transparency stats)
- Header and footer text per section

Save the report — every preamble decision below traces back to it.

### Step 2 — Run pandoc

```powershell
pandoc "<file.docx>" -o "<file>.tex" --extract-media="img_<file>"
```

This produces a `.tex` with longtables, hyperlinks, and image references in place but **without** the visual fidelity adjustments. Do not edit the pandoc output until step 3.

### Step 3 — Delegate to the `word-to-latex` agent

Hand off to the agent with the inspector report as context:

```
Use the word-to-latex agent to patch <file>.tex against the inspector report above.
Apply the full standard patch sequence in order. The banner uses image<N>.png
(white wordmark) on the left; pages <M>–<P> are landscape <orientation>.
```

The agent applies the 10-step patch sequence documented in
`.claude/skills/word2latex/references/preamble_patches.md`.

### Step 3b — Manuscript bibliography (optional, `--bibliography` only)

Skip this step for form gabarits. Run it only when the `.docx` is a manuscript
(numbered references + inline citations) and `--bibliography` was passed.

1. Second pandoc pass to markdown (keeps explicit `1.` numbering):
   ```powershell
   pandoc "<file.docx>" -t gfm -o "<file>.md"
   ```
2. Extract the bibliography and rewrite citations:
   ```powershell
   python "<workspace>/.claude/skills/word2latex/scripts/manuscript_bib.py" `
       "<file>.tex" --bib-source "<file>.md"
   ```
   Produces `<file>.cited.tex` (citations as `\cite{...}`) and
   `<file>.first-pass.bib`.
3. Validate and enrich the bibliography (respects the project reference rules —
   approved publishers, clickable DOI):
   ```
   /bibclean <file>.first-pass.bib
   /scopus validate <file>.first-pass.bib
   ```
4. The agent (Step 3) then injects the `biblatex` preamble and replaces the
   pandoc-rendered reference list with `\printbibliography`.

Full details: `.claude/skills/word2latex/references/manuscript_bibliography.md`.

### Step 4 — Compile and render

```powershell
pdflatex -interaction=nonstopmode -output-directory=out "<file>.tex"
pdflatex -interaction=nonstopmode -output-directory=out "<file>.tex"
Remove-Item out\page-*.png -ErrorAction SilentlyContinue
pdftoppm -png -r 120 out\<file>.pdf out\page
```

Two `pdflatex` passes are required for `\pageref{LastPage}` and longtable column widths.

For a `.tex` marked `% !TEX program = xelatex`, replace `pdflatex` by `xelatex` in both
passes, or let `latexmk` choose:
`latexmk -pdf -outdir=out -auxdir=out "<file>"` (the project `latexmkrc` loads
`latexmk_engine.pl`). Two passes are also needed when headers or footers are placed with
TikZ `remember picture`.

### Step 5 — Visual verification

Read at minimum:

- Page 1 — banner, white wordmark on left, title centered, icon on right, no duplicate header
- Each landscape page — text + table on the same page, full grid visible
- The last page — footer reads correctly, no orphan content from a previous section

If any page does not match, return to the agent with the specific page index and the discrepancy.

**Measured comparison (when the output must look identical to Word).** Export the `.docx`
to PDF with Word itself (Word COM `SaveAs(..., 17)`), then compare it line by line:

```powershell
python .claude/skills/word2latex/scripts/pdf_line_compare.py "<file>_word.pdf" out\<file>.pdf
```

Each line of the Word PDF is paired with the same line of the LaTeX PDF; a pair is flagged
(`!!`) when the page, the baseline, the left edge or the right edge of the last visible
glyph differs by more than `tolerance_cm` (`pdf-line-compare.json`, 0.02 cm). `MISSING` and
`EXTRA` lines usually mean a different line break. `--json` gives the full report. Exit 0
identical, 1 differences, 2 refusal. Lessons measured on the Mitacs v2 form (2026-10-30),
each a cause of flagged lines before it was fixed:

- Word sizes and spacings are in PostScript points: write them in `bp`, not `pt`
  (TeX's `pt` is 0.4 % smaller).
- pdflatex kerns Helvetica and Word does not kern Arial: lines came out 0.6 % narrower and
  line breaks moved. Identical output needs XeLaTeX with the real fonts and
  `Kerning=Off, Ligatures=NoCommon` (Word applies no ligature either).
- Word's line box is `size x 1.149 x spacing` with the baseline 0.905 x size below its top
  (Arial), and the gap between paragraphs is `max(space after, space before)`, not the sum.

**Running XeLaTeX from latexmk without changing other files.** A project folder holds a
one-line `latexmkrc`:

```perl
do "$ENV{USERPROFILE}/.claude/skills/word2latex/scripts/latexmk_engine.pl";
```

Then a `.tex` whose first lines contain `% !TEX program = xelatex` is built with xelatex,
and every other `.tex` of the folder keeps pdflatex. `~/.latexmkrc` (out/, bibtex) is not
touched, and only the engine token of its `$pdflatex` is replaced, so its options
(`-synctex`, `-shell-escape`) apply to both engines.

**VS Code: disable LaTeX Workshop's magic comments in that workspace.** LaTeX Workshop
10.x reads `% !TEX program` itself and, by default, bypasses its latexmk recipe: it runs
the named engine once, with no bibtex and no `-outdir`, so every citation is undefined
and the outputs land beside the `.tex`. Measured 2026-10-30 on LaTeX Workshop 10.20.0:
100 undefined citations, 18 pages instead of 22. Its changelog (#4792) replaced
`latex.build.forceRecipeUsage` by `latex.build.enableMagicComments` (default `true`);
`package.json` still lists the old key, which the code no longer reads. Put in the
workspace `.vscode/settings.json`:

```json
"latex-workshop.latex.build.enableMagicComments": false
```

Then the save runs the latexmk recipe, which loads the folder `latexmkrc`, which runs
xelatex with bibtex into `out/`. Set it per workspace, not in the user settings: another
project may rely on its magic comments and have no `latexmkrc`.

## Output formatting

Final response to the user lists:

1. The `.tex` file path
2. The page count of the resulting PDF
3. For each landscape page: dimensions in inches
4. Any unresolved overfull `\hbox` ≥ 5 pt (smaller are absorbed by `\hfuzz=3pt`)
5. The verification rendering folder (`out/page-*.png`)

## Tracked changes in a Word file that stays in Word

Some manuscripts cannot move to LaTeX (a revision of a paper submitted in Word, for example).
`docx_track.py` is the Word counterpart of `latex-hygiene`'s `tex_patch.py`: it applies an edit
list to an existing `.docx` as real Word revisions (`<w:ins>` / `<w:del>`), under one author.

```powershell
python .claude/skills/word2latex/scripts/docx_track.py paragraphs "<file>.docx"          # visible text, for anchors
python .claude/skills/word2latex/scripts/docx_track.py apply "<file>.docx" edits.json -o "<file>_rev.docx" --author "<name>" --date 2026-10-30T00:00:00Z [--dry-run] [--json]
```

`edits.json` holds `{"edits": [...]}`. Operations: `replace` (`find`, `with`), `delete` (`find`),
`insert_after` / `insert_before` (`anchor`, `text`), `insert_paragraphs_after` (`anchor`,
`paragraphs`); optional `occurrence` (1-based) and `highlight` (a Word colour name, e.g. `cyan`
for placeholders the author must fill). Text is matched across Word's fragmented runs, never
across two paragraphs. Refusals, each listed as a `FAILS:` line: text not found, text found
several times without `occurrence`, a match inside a field (an EndNote citation, a
cross-reference, or a field spanning several paragraphs such as the EndNote bibliography,
which Word rewrites on update), a boundary inside a run holding a tab, a break or a drawing,
a deletion covering such a run or stepping over a footnote reference, image or symbol,
new paragraphs that would land inside a field, and an edit of the wrong shape. A tab is
read as `\t` and a line break as `\n`, so a find string must name them to match across
them. One failure writes nothing (exit 1). Before the output is put in place, the written
archive is read back: rejecting every revision, in the output and in the input, must give
the same text (R9), so a file that already carries a co-author's tracked changes verifies
too, and a mismatch also writes nothing (exit 1). Exit 0 applied, 1 an edit or the
read-back failed, 2 refusal (output equal to input, unreadable edit file, input that is
not a readable .docx). New citations are inserted
as EndNote temporary citations `{Author, Year}`: import the references into the EndNote
library, then *Update Citations and Bibliography* turns them into live fields.

Validate the result with the docx skill's `validate.py --original <file>.docx --author
<name>`. Under Windows run it with `PYTHONUTF8=1`: it opens XML files without an encoding
and otherwise reads them in cp1252, which reports a false "new error" on any curly quote.

## Error handling

| Error | Action |
|---|---|
| `pandoc: command not found` | Ask user to install pandoc or add it to `PATH` |
| `python-docx` missing | `pip install python-docx` then retry |
| `~$<file>.docx` lock present | Ask user to close the document in Word |
| `! Misplaced \noalign` | A `\toprule`/`\midrule` was missed by the rule-replacement pass — re-run `replace booktabs rules with \hline` |
| `Command \endLegalLand already defined` | Macro name collides with `\begin{LegalLand}` / `\end{LegalLand}` semantics — rename to `\Open...`/`\Close...` |
| `paperwidth not available in \newgeometry` | Geometry forbids paper-size keys mid-document — set `\pdfpagewidth` and `\paperwidth` *before* the `\newgeometry` call |
| Calendar table spills to a second page | Apply row-compaction: replace minipage+enumerate cells with `\textbf{N) text}`, set `\renewcommand{\arraystretch}{0.95}`, use `\footnotesize` |
| Right header text missing | Header logo image has no width constraint and pushes the right slot off-page — set `width=3.5cm,keepaspectratio` on the `\includegraphics` in `\fancyhead[L]` |
| `Entries : 0` from `manuscript_bib.py` | The bibliography is not numbered as `1.`/`2.` in the source — run the `-t gfm` markdown pass and pass it via `--bib-source` |
| Unresolved cites > 0 after validation | A `\cite{refN}` survived — the source citation number has no matching numbered reference; fix the source numbering or the reference list |

## See also

- Agent: `.claude/agents/word-to-latex.md`
- Patch reference: `.claude/skills/word2latex/references/preamble_patches.md`
- Manuscript bibliography reference: `.claude/skills/word2latex/references/manuscript_bibliography.md`
- Inspector script: `.claude/skills/word2latex/scripts/docx_inspect.py`
- Bibliography module: `.claude/skills/word2latex/scripts/manuscript_bib.py`
- Line comparison against the Word PDF: `.claude/skills/word2latex/scripts/pdf_line_compare.py` (settings in `pdf-line-compare.json`)
- latexmk engine choice (xelatex by magic comment, pdflatex otherwise): `.claude/skills/word2latex/scripts/latexmk_engine.pl`
- Tracked changes in an existing .docx: `.claude/skills/word2latex/scripts/docx_track.py`
