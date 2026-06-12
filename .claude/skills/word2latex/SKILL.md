---
name: word2latex
description: "Convert a Word .docx template (Mitacs, CRSNG, FRQNT, UQAC, partner forms) into a faithful LaTeX source. Use when the user asks to translate a Word gabarit to LaTeX, when a generated .tex must match a .docx visually, or for /word2latex. Drives pandoc + applies the standard patch sequence (Arial, full-grid tables, centered sections, landscape geometry, first-page banner). Delegates the actual patch work to the word-to-latex agent."
---

# word2latex Skill

## Prerequisites

Before running, verify:

1. `pandoc` installed: `pandoc --version`
2. `python-docx` available (used by `docx_inspect.py`): `python -c "import docx; print('OK')"` — if missing, `pip install python-docx`
3. `pdflatex` and `pdftoppm` reachable from the shell (any TeX distribution + poppler)
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

### Step 5 — Visual verification

Read at minimum:

- Page 1 — banner, white wordmark on left, title centered, icon on right, no duplicate header
- Each landscape page — text + table on the same page, full grid visible
- The last page — footer reads correctly, no orphan content from a previous section

If any page does not match, return to the agent with the specific page index and the discrepancy.

## Output formatting

Final response to the user lists:

1. The `.tex` file path
2. The page count of the resulting PDF
3. For each landscape page: dimensions in inches
4. Any unresolved overfull `\hbox` ≥ 5 pt (smaller are absorbed by `\hfuzz=3pt`)
5. The verification rendering folder (`out/page-*.png`)

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

- Agent: `.claude/agents/word-to-latex/AGENT.md`
- Patch reference: `.claude/skills/word2latex/references/preamble_patches.md`
- Manuscript bibliography reference: `.claude/skills/word2latex/references/manuscript_bibliography.md`
- Inspector script: `.claude/skills/word2latex/scripts/docx_inspect.py`
- Bibliography module: `.claude/skills/word2latex/scripts/manuscript_bib.py`
