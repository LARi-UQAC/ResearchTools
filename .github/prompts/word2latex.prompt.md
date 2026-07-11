---
description: "Word → LaTeX template conversion"
---

Convert a Word `.docx` gabarit into a LaTeX source that renders identically: Arial font, full-grid tables, centered sections, landscape pages on Legal paper when needed, first-page banner, header/footer.

Procedure:

1. Resolve the `.docx` path from `the file(s) or topic given after the command in the chat message (if none was given, use the file currently open in the editor)` (a path, a directory containing one `.docx`, or the file open in the IDE).
2. Run the inspector to extract every value the LaTeX preamble needs:
   ```
   python ".claude/skills/word2latex/scripts/docx_inspect.py" <file.docx>
   ```
3. Run pandoc once:
   ```
   pandoc <file.docx> -o <file>.tex --extract-media="img_<file>"
   ```
4. Delegate to the `word-to-latex` agent with the inspector report so it applies the 10-step patch sequence (geometry, Arial via `helvet`, line spacing, section/subsection formatting, full-grid tables, first-page TikZ banner, fancyhdr header/footer with `\headrulewidth=0pt`, paired `\OpenLegalLand` / `\CloseLegalLand` macros for landscape sections).
4b. **Only if `--bibliography` is in `the file(s) or topic given after the command in the chat message (if none was given, use the file currently open in the editor)`** (manuscript mode; skip for form gabarits): run a second pandoc pass to markdown, extract the numbered bibliography, and rewrite inline citations.
   ```
   pandoc <file.docx> -t gfm -o <file>.md
   python ".claude/skills/word2latex/scripts/manuscript_bib.py" <file>.tex --bib-source <file>.md
   ```
   Then validate the first-pass bibliography through the existing skills (approved publishers, clickable DOI, SJR quartile):
   ```
   /bibclean <file>.first-pass.bib
   /scopus validate <file>.first-pass.bib
   ```
   The agent then injects the `biblatex` preamble and replaces the pandoc reference list with `\printbibliography`. See `.claude/skills/word2latex/references/manuscript_bibliography.md`.
5. Compile twice and render at 120 DPI:
   ```
   pdflatex -interaction=nonstopmode -output-directory=out <file>.tex
   pdflatex -interaction=nonstopmode -output-directory=out <file>.tex
   Remove-Item out\page-*.png -ErrorAction SilentlyContinue
   pdftoppm -png -r 120 out\<file>.pdf out\page
   ```
6. Inspect page 1 (banner), every landscape page (text + table on same page), and the last page (footer correctness). If a discrepancy remains, report the page index + symptom and patch again.

Report at the end:

- `.tex` file path
- PDF page count
- Landscape pages with their dimensions in inches
- Unresolved overfull `\hbox` ≥ 5 pt
- Folder containing the verification PNGs

Read only the files necessary for the diagnosis. Apply fixes directly — do not ask "would you like me to...". Respond in French unless the active file is in English.

the file(s) or topic given after the command in the chat message (if none was given, use the file currently open in the editor)

