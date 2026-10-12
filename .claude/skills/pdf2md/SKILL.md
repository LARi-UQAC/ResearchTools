---
name: pdf2md
description: "Convert a PDF (typically a thesis or paper received with no LaTeX source, where LaTeX export and Marker both failed) into clean, chapter-split markdown laid out as a project's own src/ directory (-o points AT that src/ itself, never a parent of it): src/main.md linking everything, src/content/ holding frontmatter.md, Introduction.md, chapitreN.md, Conclusion.md, and src/assets/ holding bibliography.md and ref.md (acronyms and, if ever extracted, figures under assets/figures/ are reserved slots, not implemented). Accurate enough to feed thesis-auditor's content-level checks, though never auto-discovered by thesis-auditor's own directory resolution, which needs a real src/main.tex and reads LaTeX \\input{}/\\include{} macros only. Drives mineru end to end via its installed mineru-kit CLI: installs/downloads what's missing, starts the VLM server with a real accuracy fix (--image-min-tokens) that mineru's own CLI wrapper cannot apply on Windows, runs the conversion at maximum accuracy, then cleans up the running-header splice defect mineru's own title_leveling step leaves behind when it fails under CPU contention. Trigger on: convert this PDF to markdown, pdf2md, mineru conversion, thesis has no LaTeX source, PDF to UQAC chapters, max accuracy PDF conversion, /pdf2md."
allowed-tools: [Read, Write, Edit, Bash, PowerShell]
permissions: [read, write]
---

# pdf2md - PDF to UQAC-shaped markdown, maximum accuracy

Converts a PDF with no LaTeX source into markdown good enough for
`thesis-auditor`'s **content** checks (hypothesis flow, references,
equations/figures, LLM-style detection, bilingual consistency) -- never the
mechanical `uqac.cls` checks, since mineru has no LaTeX output format at all
(`--format` only accepts `markdown`/`middle_json`/`zip`, confirmed in its
source).

Everything this skill does was measured hands-on against mineru-kit 4.0.11
on Windows, not guessed (R14). Where mineru's behavior changes in a later
version, re-verify before trusting the script's own assumptions -- `pdf2md
version` is the first thing to check if something that used to work stops
working.

## Why this is more than "run mineru-kit parse"

Three real defects, found by actually running the tool, not reading its
docs:

1. **mineru-kit's own `vlm-server` wrapper is broken on Windows.** It
   builds its argv as a Python list and launches via `os.execv`, which does
   not quote its own injected default `--grammar "root ::= .*"` (contains a
   space) across the POSIX-argv-to-Windows-command-line boundary.
   llama-server receives it split into separate tokens and dies with
   `error: invalid argument: ::=` -- even with zero flags supplied, so it is
   not a usage mistake. `pdf2md_server.py` sidesteps this entirely by
   launching `llama-server.exe` directly via `subprocess.Popen` with a
   proper argument LIST (Python quotes this correctly on Windows on its
   own); never reconstruct this via a manually pre-quoted PowerShell string
   or a `.ps1` file, which reintroduces the exact same bug class (PowerShell
   5.1's `Start-Process -ArgumentList <array>` has an identical quoting
   gap).

2. **`~/.mineru/config.yaml`'s `vlm:` key must nest under `model:`.** A
   top-level `vlm:` key is silently accepted and ignored by pydantic -- no
   error, ever. This is why a hand-written `image_min_tokens: 1024` entry
   under a top-level `vlm:` (not even a real recognized key anywhere in
   mineru's source, separately confirmed) never did anything, and why a
   later `server_url` edit under the same wrong nesting also silently had
   no effect. `pdf2md_config.py` diagnoses and fixes this.

3. **`llm_aided.max_concurrency` defaults to 16.** mineru's optional
   `title_leveling`/`cross_page_table_cell_merge` LLM cleanup step fires up
   to 16 concurrent calls to a local Ollama model for cleanup JSON. If that
   model is not fully GPU-resident (`ollama ps`'s CPU/GPU split tells you),
   16-way contention pushes every call past the OpenAI SDK's hardcoded
   600s x 3-retry ceiling (`mineru/backend/postprocess/llm_client.py`'s
   `_MAX_LLM_RETRIES = 3`, no override exposed). mineru degrades gracefully
   on this failure rather than crashing -- it just leaves the page's running
   header as a spurious markdown heading sitting mid-paragraph, sometimes
   with a page number fused into it. The sentence is NOT lost, just split.
   Stage 5's `pdf2md_postprocess.py` is the dedicated fix for this, on top
   of `pdf2md_config.py` lowering the concurrency so it happens less.

## The pipeline

Run the whole thing with `pdf2md.py run <pdf> -o <dir> [--tier advanced]
[--yes]`, or each stage separately for more control. Every stage emits a
JSON report on request (`--json`) and follows the exit-code convention: 0
done, 2 refusal by design (e.g. dry-run found issues but `--yes` was not
passed), 1 failure.

| Stage | Script | What it does |
|---|---|---|
| 1. Bootstrap | `pdf2md_bootstrap.py` | Checks `mineru`/`mineru-llama-cpp` installed (the pip DISTRIBUTION is `mineru`, confirmed via `pip show mineru`, 2026-10-10 -- `mineru-kit` is only the CLI entry point it installs, never a separate pip package; `pip show mineru-kit` reports "Package(s) not found"), the VLM model downloaded (`mineru-kit models show`), and fixes `config.yaml`'s two defects above. Dry-run by default, `--yes` to apply. Idempotent -- safe to rerun. |
| 2. Version check | `pdf2md_version.py` | Installed vs latest on PyPI (`mineru`, not `mineru-kit`), report-only. `--yes` upgrades + runs `pip-audit` (security.md). Never auto-upgrades silently -- this skill's correctness depends on version-4.0.11-specific behavior measured above; an upgrade could change any of it without warning. |
| 3. Start VLM server | `pdf2md_server.py` | Resolves the model's real paths through mineru's OWN registry module (`mineru.model.registry.vlm_model_repo`, never reimplemented file-naming guesses), builds the exact llama-server argv mineru's wrapper would (plus `--image-min-tokens 1024`, a real grounding-accuracy fix, confirmed present in the bundled binary's own `--help`), launches it, and verifies via the server's OWN log -- both that it is listening AND that the grounding warning is actually gone (R9: never trust a launcher's exit code alone). |
| 4. Convert | `pdf2md_convert.py` | `mineru-kit parse --tier advanced --format markdown --pages all -v`, detached (can run for hours). `--ocr-mode` stays at mineru's own default (`auto`) -- forcing `ocr` is LESS accurate than an existing native text layer. Never `--disable-image-analysis`. Poll `convert status --log <path>` for progress; its report says whether the run is actually routed through the VLM server (`get http-client predictor cost` in the log) or silently fell back to the slow/warning-prone in-process engine (`Using llama-cpp-engine`) -- the latter means stage 1/3's config wiring regressed. |
| 5. Post-process | `pdf2md_postprocess.py` | Detects and strips the running-header splice defect (a heading whose digit-stripped text fuzzy-matches an EARLIER heading WITH THE SAME CHAPTER NUMBER is a repeat -- two different chapters never merge just because their stripped titles collide; a heading that is not of the "CHAPITRE N" form is spurious only when the SAME text, digits included, repeats inside the same chapter -- measured 2026-10-11, the earlier rule compared a missing chapter number with itself and deleted 28 real headings such as "3.2 Conclusion" and "Avant-propos"), rejoining the surrounding prose into one sentence where safe (never merging across a `$$` math fence, a list, or another heading). A numbered-reference line only opens the bibliography when a DENSE run of further numbered references follows it (`_BIBLIOGRAPHY_DENSITY_MIN_MATCHES` of the next `_BIBLIOGRAPHY_DENSITY_WINDOW` lines, both read from `pdf2md-postprocess.json` beside the module, never a code literal) -- a lone in-text citation like "[40] presented a method" no longer swallows every chapter after it into a bogus bibliography. `-o <dir>` IS the project's own `src/`, never nested under an extra "src" segment of its own: writes `<dir>/main.md` directly, `<dir>/content/frontmatter.md` (everything before the first real `CHAPITRE N`) plus one file per chapter via `chapter_filenames()` (first chapter -> `Introduction.md`, last -> `Conclusion.md`, every chapter in between -> `chapitreN.md`), and `<dir>/assets/bibliography.md` when found. `main.md` links all of them in reading order; it does NOT make thesis-auditor's own directory resolution (`thesis-auditor.md:98`, which looks for `src/main.tex` and reads only `\input{}`/`\include{}` LaTeX macros) auto-discover this output -- that mechanism has no markdown support at all, so this layout is a human/manual-feed convenience, not a claim of interoperability. |
| 6. References | `pdf2md_refs.py` | Restructures mineru's flat numbered bibliography (`[171] Lin Xiao and Stephen Boyd. Fast linear iterations...`) into `<dir>/assets/ref.md`, one block per entry with labelled Authors/Title/Venue fields and a `firstauthor+year+keyword` key (this repo's own citation-label convention, code-style.md) -- the key uses the first author's SURNAME (last whitespace-separated name token, e.g. "Javier Alonso-Mora" -> `alonso-mora`), never their given name, since mineru renders "Firstname Lastname" with no comma between them. BibTeX-LIKE, not literal `.bib` syntax, per the confirmed output-shape decision for this skill. Heuristic text split, not a full citation parser; documented limitation in the module docstring. |
| 7. Validate | `pdf2md_validate.py` | A structural sanity pass: compares word/section/subsection/table/figure/citation-marker counts chapter by chapter between pdf2md's output and an INDEPENDENT second reader of the PDF (extract-statistic's `extract_text.read_pdf`, reused by direct import, R18, never mineru's own VLM again). Chapter boundaries on the PDF side are matched on the literal uppercase word "CHAPITRE" per LINE, and the last chapter is cut at the first bibliography heading found after its own start (both measured live, see the module docstring). Heading counting keys on the N.M / N.M.K numbering, never on heading depth. The equation count is an explicitly labelled ROUGH heuristic. Words EXCLUDE formulas on both sides (the output's `$...$` spans and base64 images are removed, and a token counts only when it holds a run of `word_min_letters` letters, which drops the PDF reader's one-letter italic fragments): measured 2026-10-11, counting formulas as words made two chapters read +6171 and +8449 words longer in the output. Every threshold lives in `pdf2md-validate.json` (R0). The report is ONE table, a row per measure and a column per converted file (each cell reads PDF / output), a last column with each measure's global error in percent and a last row with each file's error in percent; the percentages are defined under the table and returned structured under `table` in `--json`. **The counts are still not conversion errors on a math-heavy chapter**: the citation-marker gap was matrix indices such as `[11]` read as citations by the PDF reader, not lost references. The next three rows are what finds real conversion errors. |
| 7b. Fidelity | `pdf2md_fidelity.py` (`pdf2md_validate.py --fidelity [--strict]`) | A CONTENT check, chapter by chapter, that reports what a person would call a conversion error: `missing_heading` (a numbered heading the PDF has and the output lacks, with whether its title survives as a plain line), `out_of_order_heading` / `out_of_order_paragraph`, `missing_paragraph`, `extra_paragraph`, `duplicate_paragraph`, `embedded_image` (a base64 data-URI left in the markdown), `html_residue` (page-footnote `<span>` markup), `figure_caption_missing` / `table_caption_missing` / `figure_without_image` / `table_without_content`, `image_analysis_block` (an invented `<details>` block), `equation_number_gap` / `equation_number_unformatted` / `equation_number_duplicate` (the equation numbering is a PDF-independent check: a hole means a lost equation) and `citation_missing` / `citation_undercounted` (both errors: a lost citation leaves a claim without its source). Citations are counted only in prose, so matrix indices (`[0]`, `[11]`) and footnote calls are not citations. Formulas are excluded on both sides. Matching is by letters-only, accent-folded character n-grams over prose words, because this PDF's font garbles accented characters in the reader and a word comparison would report every accented word; a PDF paragraph is matched against the whole output chapter, because the reader splits a paragraph at every page break and interleaves running headers. Deterministic (ties go to the earliest paragraph, R19, proven across hash seeds). Thresholds in `pdf2md-fidelity.json`. `--strict` exits 1 on any error-severity issue. |
| 7c. Formula check | `pdf2md_vlmcheck.py` (`pdf2md_validate.py --vlm-check --vlm-check-model TAG`) | A LOCAL vision model, named by the operator (R2), reads the pages richest in math symbols and verifies their formulas against the markdown located for each page, one narrow question: for each formula on the page, is it in the markdown and does the LaTeX say the same thing. The answer is forced into a JSON schema and VALIDATED: a reply that does not fit is an error row, never a pass, and an empty formula list on a page chosen for its formulas is its own status (`no_formula_reported`). Reasoning is turned off (`think: false`) and the context bounded (`num_ctx`), since the model reasons by default at level medium and carries a 262144-token context: measured 2026-10-11 with `ollama show`, a likely cause of the earlier 130 s per page and of an empty `{}` answer the first version accepted as success. A spot check of `pages_per_chapter` pages per chapter, not full coverage. Settings in `pdf2md-vlmcheck.json`. |
| 7d. Repair | `pdf2md_repair.py` (`pdf2md.py repair <pdf> -o <dir> [--yes]`) | Fixes mechanically what 7b finds: base64 images decoded to `assets/figures/chapterN_figureK.ext` and replaced by a relative link, page-footnote HTML unwrapped to its text, lost numbered headings restored (inserted before the output paragraph that follows them in the PDF, or promoted from a plain line holding the title), far-displaced paragraphs moved back (a shift under the fidelity key `out_of_order_min_displacement` is left alone and reported; figure and table captions are never moved, they stay with their float), mineru's `<details>` "image analysis" blocks removed (they carry invented approximate values such as a chart turned into a table of "~2.0"; every removed block is kept with its chapter and line in `assets/image_analysis_removed.md`), equation numbers written as text ("(3. 2 5)") turned into `\tag {3.25}`, and a citation mineru read as mathematics ("holds [14]:" came out as a `${ \sqrt { I } }...$` span) put back when exactly one short, non-formula math span follows the same five words as in the PDF. The PDF reader guides headings and order only: paragraph text is never copied from it. A dry run by default (R16); `--yes` writes, after copying the original of every rewritten file into `<dir>/pdf2md-backup/`, and the run refuses to start over an existing backup so a second run cannot overwrite the first run's originals. The effect is MEASURED (R9): the fidelity check is run before and after and the report states both counts. Exit 0 done, 2 refused, 1 failure; `--json` report (R17). Settings in `pdf2md-repair.json`. |

| 7e. Correction loop | `pdf2md_vlmfix.py` (`pdf2md.py fix <pdf> -o <dir> --model TAG [--pages all] [--yes] [--strict]`) | A bounded loop with a LOCAL vision model named by the operator (slow, meant for the night). Each round: (1) an equation number missing from the numbering (`equation_number_gap`) is transcribed from the PDF page and inserted with an HTML comment naming the page, (2) the formula check runs, (3) a correction is applied only when its `markdown_latex` quote is unique verbatim in the chapter, the corrected LaTeX is syntactically sane and not wildly longer, (4) the model is asked again about the corrected formula and the change is REVERTED if it still disagrees. The loop stops on `target reached`, `no change`, `no progress` or the round limit (`max_rounds`). Every edit is listed in `assets/vlm_changes.json`; originals are copied to `pdf2md-backup-vlm/`. Anything it cannot settle is left as `needs_review`, never guessed. When mineru kept the number as a lone line `(4.5)` and lost the equation, the transcription replaces that line, so no placement is guessed. `--equations-only` recovers lost numbered equations and stops after one round: no formula is checked or rewritten, which is the safe setting because measured 2026-10-11 the model changed the meaning of a formula the conversion had right (a definition of h(lambda) rewritten as a modulus chain) and its first transcription of (4.5) kept only the last term of a three-part equality. Dry run unless `--yes`. Settings in `pdf2md-vlmfix.json`. |

## Known limits -- state them, don't claim past them

- **No real `.tex` output, ever.** mineru has no LaTeX format. A thesis
  converted this way can feed `thesis-auditor`'s content checks but never
  its `uqac.cls` mechanical checks (front-matter macros, label/citation
  conventions) -- there is no `.tex` to check those against.
- **Mixed French/English inside one chapter is normal**, not a defect: a
  UQAC thèse-par-articles wraps a published English article (with its own
  "Avant-propos"/"Résumé français" block) inside the French thesis
  narrative. Don't flag it.
- **The splice-defect detector is a fuzzy text-repeat heuristic.** It can
  theoretically misfire on a thesis with two genuinely distinct sections
  sharing near-identical titles. Not observed in practice; stated here the
  same way `extract-contributions` states its own known misses.
- **The reference splitter is a heuristic sentence-boundary split**, not a
  citation parser. An entry with an unusual shape still gets a partial
  record (number + raw text) rather than being silently dropped, but its
  authors/title/venue split may be wrong.
- **`--tier advanced` is a compute-effort setting, not a bigger model.**
  mineru's own `tier.py` maps flash/basic/standard/advanced to
  flash/medium/high/xhigh "effort" on the SAME downloaded model;
  `mineru-kit models download --tier` only accepts `basic`/`standard`.
  There is no separate "advanced" model to download.
- **Not auto-discovered by `thesis-auditor`.** Its own directory resolution
  (`thesis-auditor.md:98`) looks for `<dir>/src/main.tex` and reads
  `\input{}`/`\include{}` LaTeX macros only -- it has no markdown-chapter-
  following behaviour at all. Pointing it at a pdf2md output directory will
  not make it find or merge the chapters; the operator feeds it the content
  manually (or a future real `.tex` conversion). The `src/content/` +
  `src/assets/` layout mirrors a real UQAC thesis's file-per-chapter
  organization for a human reader, not this specific automatic step.
- **Figures are written to `assets/figures/` only by the `repair` stage, and
  acronyms are not extracted at all.** mineru embeds every figure as a base64
  data-URI in the markdown (measured 2026-10-11: 22 images across one thesis,
  although an earlier version of this file said its image extraction stays
  off), so before `repair` runs the markdown carries them inline. A figure
  whose media type is not in `pdf2md-repair.json` or whose data does not
  decode is left in place and keeps being reported. A tiny image (at most
  `glyph_image_max_bytes`, 4096, measured 2026-10-11: the four end-of-proof
  squares of a thesis weigh 968 to 1164 bytes, the smallest real figure
  29593) is a symbol, not a figure: `repair` writes the end-of-proof symbol
  instead, counts it as `glyph_images_replaced` and gives it no figure number.
  Acronym detection has no code path at all.
- **Stage 7's equation measure is the numbering, not a detection.**
  The expected count is the highest equation number in the output and the
  found count the distinct numbers present, so a hole is a real lost
  equation but an unnumbered equation is invisible to it. Docling, the only
  PDF backend with a formula-enrichment model, is not installed.
- **The word count cannot be tighter than about 1 percent on a math-heavy
  chapter, and that is the two readers, not lost text.** Measured 2026-10-11
  on chapters 3 and 4 of a real thesis (-0.6 and -2.0 percent raw): apostrophes
  and hyphenated words are identical on both sides (83/83 and 87/87
  apostrophe tokens), so neither elisions nor compounds are the cause. The PDF
  reader prints math variables as italic text that counts as words
  (`_tau_ij_`, `max`, `deg(`: 175 and 249 fragments against 12 and 6 in the
  output), glues words to italic markers (`_where`), and leaves the running
  header "Article soumis" in (14 to 16 times per chapter, 13 letters, under
  `running_header_min_letters`). The output side counts a few HTML table tags.
  After normalising those, the output has 0.6 percent MORE words than the PDF
  reading, because the reader swallows ordinary words ("the", "for", "and")
  into italic runs next to formulas. The errors cancel; the paragraph-level
  fidelity check, not this count, is the evidence that no text is missing.
- **Equations are the one thing stage 7e writes from a model.** A transcribed
  equation carries an HTML comment naming the PDF page and must be checked
  against the page, and a transcription can be PARTIAL (measured 2026-10-11:
  the last term of a three-part equality only); the loop reverts a correction the model itself rejects on
  a second look, but a model can be wrong twice.
- **A misread citation is repaired only where the place is unambiguous.**
  Zero or several candidate spans leave the text unchanged and the citation
  is reported under `citations_unplaced`.
- **Stage 7c is a spot check, and its answers are the model's.** It checks
  `pages_per_chapter` pages per chapter, chosen for their math content, so a
  chapter with no reported issue is not a chapter proven correct. The model can
  be wrong in both directions (a formula it reports as missing may be outside
  the markdown excerpt, which is widened by `excerpt_margin_lines`; a formula it
  reads as identical may differ), so each reported issue is a lead to check
  against the page, not a verdict. Latency is set by the card: the 27B model
  measured 86% CPU / 14% GPU on a 6 GiB GPU, so it is minutes per page.
- **Stage 7d cannot repair what crosses a chapter boundary.** A block that
  mineru read into the wrong chapter (measured: a chapter 3 concluding
  paragraph written at the top of chapter 4, and the chapter-introduction
  blocks of both chapters reordered or partly missing) is reported by 7b as
  missing or extra paragraphs and is left for a human, since the repair works
  one chapter at a time and never copies text from the PDF reader.
- **Stage 7's PDF-side chapter extraction depends on mineru's own
  "CHAPITRE" capitalization convention.** The splitter matches the literal
  uppercase word, since this thesis's own body prose cross-references
  other chapters in ordinary title case ("Chapitre 2 a montre que...") and
  a case-insensitive match mistook that sentence for a heading. A thesis
  whose chapter headings are NOT rendered in full caps by mineru would
  need this re-verified, not assumed to transfer.

## When something doesn't match this document

Re-verify against the installed version rather than trusting this file
blindly (R14) -- `pdf2md version` is the first check. If mineru's own CLI
surface or config schema has changed, the fix belongs in this skill's
scripts (R18: a script lives beside its only caller), with a new offline
test pinning the new behavior, following the "Improving ResearchTools from
another folder" protocol in the repo-root `.claude/CLAUDE.md`.
