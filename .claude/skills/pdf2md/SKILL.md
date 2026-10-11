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
| 5. Post-process | `pdf2md_postprocess.py` | Detects and strips the running-header splice defect (a heading whose digit-stripped text fuzzy-matches an EARLIER heading WITH THE SAME CHAPTER NUMBER is a repeat -- two different chapters never merge just because their stripped titles collide), rejoining the surrounding prose into one sentence where safe (never merging across a `$$` math fence, a list, or another heading). A numbered-reference line only opens the bibliography when a DENSE run of further numbered references follows it (`_BIBLIOGRAPHY_DENSITY_MIN_MATCHES` of the next `_BIBLIOGRAPHY_DENSITY_WINDOW` lines, both read from `pdf2md-postprocess.json` beside the module, never a code literal) -- a lone in-text citation like "[40] presented a method" no longer swallows every chapter after it into a bogus bibliography. `-o <dir>` IS the project's own `src/`, never nested under an extra "src" segment of its own: writes `<dir>/main.md` directly, `<dir>/content/frontmatter.md` (everything before the first real `CHAPITRE N`) plus one file per chapter via `chapter_filenames()` (first chapter -> `Introduction.md`, last -> `Conclusion.md`, every chapter in between -> `chapitreN.md`), and `<dir>/assets/bibliography.md` when found. `main.md` links all of them in reading order; it does NOT make thesis-auditor's own directory resolution (`thesis-auditor.md:98`, which looks for `src/main.tex` and reads only `\input{}`/`\include{}` LaTeX macros) auto-discover this output -- that mechanism has no markdown support at all, so this layout is a human/manual-feed convenience, not a claim of interoperability. |
| 6. References | `pdf2md_refs.py` | Restructures mineru's flat numbered bibliography (`[171] Lin Xiao and Stephen Boyd. Fast linear iterations...`) into `<dir>/assets/ref.md`, one block per entry with labelled Authors/Title/Venue fields and a `firstauthor+year+keyword` key (this repo's own citation-label convention, code-style.md) -- the key uses the first author's SURNAME (last whitespace-separated name token, e.g. "Javier Alonso-Mora" -> `alonso-mora`), never their given name, since mineru renders "Firstname Lastname" with no comma between them. BibTeX-LIKE, not literal `.bib` syntax, per the confirmed output-shape decision for this skill. Heuristic text split, not a full citation parser; documented limitation in the module docstring. |
| 7. Validate | `pdf2md_validate.py` | A structural sanity pass: compares word/section/subsection/table/figure/citation-marker counts chapter-by-chapter between pdf2md's own output and an INDEPENDENT second reader of the PDF (extract-statistic's `extract_text.read_pdf`, reused by direct import, R18 -- never mineru's own VLM again, so a mineru-specific mistake has a chance of being caught rather than confirmed by asking the same tool twice). Chapter boundaries on the PDF side are matched on the literal uppercase word "CHAPITRE" (measured live: a lowercase/title-case "Chapitre" is how this thesis's own body prose cross-references another chapter mid-sentence, e.g. "Chapitre 2 a montre que...", and matching case-insensitively mistook that sentence for a chapter heading, truncating the real chapter early), with the last chapter additionally truncated at the first bibliography heading found (measured: "LISTE DES REFERENCES", which even `pdf2md_postprocess`'s own heading regex would miss, bled 190 references into the last chapter's word count before this fix). Section/subsection counting matches the heading's own `N.M`/`N.M.K` numbering, never heading depth, since pymupdf4llm flattens most heading levels to the same depth in the real thesis. Equation counting is an explicitly-labelled ROUGH heuristic (no formula-aware backend is installed; Docling, the only one with a formula model, is absent) -- every threshold lives in `pdf2md-validate.json`, never a code literal (R0). `--vlm-check --vlm-check-model TAG` asks a LOCAL, OPERATOR-NAMED vision-capable Ollama model for a second opinion on chapters flagged as mismatched (word count beyond the configured tolerance, or missing from either side entirely) -- the operator names their own tag explicitly (R2: this script never names a model, and no role exists in `model_resolver`'s writer/coder taxonomy for a reader/verifier use). UNVERIFIED LIVE as of this writing: every HTTP/render effect is behind an injected seam for offline testing, but no real call against a running model has succeeded yet. |

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
- **No figure or acronym extraction yet.** `src/assets/figures/` is a
  reserved path, not a feature: mineru's `include_images` defaults to
  `False` and this pipeline never turns it on, so no image file exists to
  copy there, and acronym detection has no code path at all. Stated here
  rather than silently producing an empty folder nobody asked for.
- **Stage 7's equation count is a rough heuristic, not a real detector.**
  Docling, the only PDF backend with a formula-enrichment model, is not
  installed; `pymupdf4llm`'s own `to_markdown()` has no LLM/model/formula
  parameter at all (confirmed by inspecting its real signature). The
  count is correlated, not exact, and every report it appears in labels it
  "(rough estimate)" for this reason.
- **Stage 7's `--vlm-check` second opinion is unverified live.** Every
  HTTP/render effect is behind an injected seam and offline-tested, but no
  real call against a running Ollama model has succeeded yet as of this
  writing -- re-verify the plumbing against a real page before trusting
  its counts.
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
