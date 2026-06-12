# Manuscript bibliography & citations (optional, `--bibliography`)

Companion to `preamble_patches.md`. The patch reference covers *form/template*
visual fidelity; this file covers the *manuscript* gap: turning a numbered Word
bibliography into BibTeX and rewriting inline citations to `\cite{...}`.

This volet is **opt-in**. It runs only when `/word2latex` is invoked with
`--bibliography`. The default form pipeline (Mitacs, CRSNG, FRQNT, UQAC) is
untouched, so no regression on gabarits.

## Where it sits in the pipeline

```
docx_inspect.py ──► pandoc (.tex) ──► [--bibliography] manuscript_bib.py
                                            │
                                            ├─► <file>.cited.tex   (citations -> \cite)
                                            └─► <file>.first-pass.bib
                                                   │
                                                   ├─► /bibclean   (normalise, dedupe,
                                                   │                enrich DOI, SJR quartile,
                                                   │                flag non-approved publisher)
                                                   └─► /scopus      (validate each reference exists)
                                            ▼
                                   word-to-latex agent  (inject biblatex,
                                   replace pandoc ref list with \printbibliography)
                                            ▼
                                   pdflatex ×2 + biber ──► verify (unresolved cites = 0)
```

The script is a **deterministic first-pass extractor only**. It never invents a
reference and never validates one — that is `/bibclean` + `/scopus`. The emitted
`.bib` header states this explicitly.

## Running the script

```powershell
python "<workspace>/.claude/skills/word2latex/scripts/manuscript_bib.py" `
    "<file>.tex" --bib-source "<file>.md"
```

- `source` (positional): the pandoc `.tex` — scanned for inline citations.
- `--bib-source`: a gfm markdown produced by a second pandoc pass
  (`pandoc <file>.docx -t gfm -o <file>.md`). Markdown keeps explicit `1.`
  numbering, which `parse_bib_entries` needs; pandoc's auto `\begin{enumerate}`
  in the `.tex` drops the visible numbers. If the `.tex` itself keeps explicit
  `1.`/`2.` numbers, omit `--bib-source`.
- `--out`: rewritten `.tex` (default `<stem>.cited.tex`, never overwrites input).
- `--bib`: BibTeX output (default `<stem>.first-pass.bib`).
- `--no-brackets`: disable `[n]` bracket conversion (keep superscripts only).

## Citation forms recognised

| Source (pandoc / Word) | Rewritten |
|---|---|
| `\textsuperscript{1}` / `\textsuperscript{1-3}` / `\textsuperscript{1,2,5}` | `\cite{...}` |
| Unicode superscript `¹` / `¹⁻³` / `¹,²,⁵` | `\cite{...}` |
| `[1]` / `[1,2]` / `[1-3]` (IEEE inline) | `\cite{...}` — only when every number resolves |

Bracket conversion is conservative: `\item[1]`, `array[1]`, `fig[1]`, display
math `\[` are excluded by a lookbehind, and an unresolved number leaves the
bracket untouched. Superscript forms always convert; an unresolved number
becomes `\cite{refN}` so the QC pass can grep for it.

## BibTeX key rule

`{first-author-lastname-lowercase}{year}`. The first occurrence stays bare; a
colliding later entry is suffixed `a`, `b`, … (ported from `docx2latex.py`).
Example: `smith2020`, then `smith2020a`. `/bibclean` normalises keys afterward.

## Preamble the agent injects (manuscript mode)

```latex
\usepackage[style=numeric,sorting=none,backend=biber]{biblatex}
\addbibresource{<file>.bib}
% ... body ...
\printbibliography
```

The agent replaces the pandoc-rendered reference list block with
`\printbibliography` and confirms every `\cite{...}` resolves after `biber`.

## Project reference rules (enforced downstream, not by the script)

Per `.claude/CLAUDE.md`: references limited to approved publishers (IEEE,
Springer, Elsevier, Taylor & Francis, Cambridge, Wiley, IET, IOP, MDPI, ACM);
DOI written as a clickable `https://doi.org/...` via hyperref; each reference
validated and presented by at least one sentence in the manuscript. The
first-pass `.bib` does not satisfy these on its own — `/bibclean` flags
non-approved publishers and missing DOIs, `/scopus` confirms existence, and the
human integration adds the per-reference sentence and confidence comment.

## Quality control

`manuscript_bib.py` prints: entries parsed, citation keys, bracket conversions,
and unresolved cites (`\cite{refN}`). Target after `/bibclean` + `/scopus`:
unresolved = 0 and zero non-approved publishers.
