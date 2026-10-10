---
name: pdf2md
description: "Convert a PDF (typically a thesis or paper received with no LaTeX source, where LaTeX export and Marker both failed) into clean, chapter-split markdown mirroring thesis-auditor's own <project-dir>/src/ directory convention (src/frontmatter.md, src/Introduction.md, src/chapitreN.md, src/Conclusion.md, src/bibliography.md, src/main.md linking all of them, src/ref.md), accurate enough to feed thesis-auditor's content-level checks. Drives mineru-kit end to end: installs/downloads what's missing, starts the VLM server with a real accuracy fix (--image-min-tokens) that mineru's own CLI wrapper cannot apply on Windows, runs the conversion at maximum accuracy, then cleans up the running-header splice defect mineru's own title_leveling step leaves behind when it fails under CPU contention. Trigger on: convert this PDF to markdown, pdf2md, mineru conversion, thesis has no LaTeX source, PDF to UQAC chapters, max accuracy PDF conversion, /pdf2md."
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
| 1. Bootstrap | `pdf2md_bootstrap.py` | Checks `mineru-kit`/`mineru-llama-cpp` installed, the VLM model downloaded (`mineru-kit models show`), and fixes `config.yaml`'s two defects above. Dry-run by default, `--yes` to apply. Idempotent -- safe to rerun. |
| 2. Version check | `pdf2md_version.py` | Installed vs latest on PyPI, report-only. `--yes` upgrades + runs `pip-audit` (security.md). Never auto-upgrades silently -- this skill's correctness depends on version-4.0.11-specific behavior measured above; an upgrade could change any of it without warning. |
| 3. Start VLM server | `pdf2md_server.py` | Resolves the model's real paths through mineru's OWN registry module (`mineru.model.registry.vlm_model_repo`, never reimplemented file-naming guesses), builds the exact llama-server argv mineru's wrapper would (plus `--image-min-tokens 1024`, a real grounding-accuracy fix, confirmed present in the bundled binary's own `--help`), launches it, and verifies via the server's OWN log -- both that it is listening AND that the grounding warning is actually gone (R9: never trust a launcher's exit code alone). |
| 4. Convert | `pdf2md_convert.py` | `mineru-kit parse --tier advanced --format markdown --pages all -v`, detached (can run for hours). `--ocr-mode` stays at mineru's own default (`auto`) -- forcing `ocr` is LESS accurate than an existing native text layer. Never `--disable-image-analysis`. Poll `convert status --log <path>` for progress; its report says whether the run is actually routed through the VLM server (`get http-client predictor cost` in the log) or silently fell back to the slow/warning-prone in-process engine (`Using llama-cpp-engine`) -- the latter means stage 1/3's config wiring regressed. |
| 5. Post-process | `pdf2md_postprocess.py` | Detects and strips the running-header splice defect (a heading whose digit-stripped text fuzzy-matches an EARLIER heading WITH THE SAME CHAPTER NUMBER is a repeat -- two different chapters never merge just because their stripped titles collide), rejoining the surrounding prose into one sentence where safe (never merging across a `$$` math fence, a list, or another heading). A numbered-reference line only opens the bibliography when a DENSE run of further numbered references follows it (`_BIBLIOGRAPHY_DENSITY_MIN_MATCHES` of the next `_BIBLIOGRAPHY_DENSITY_WINDOW` lines) -- a lone in-text citation like "[40] presented a method" no longer swallows every chapter after it into a bogus bibliography. Writes everything under `<output-dir>/src/`, mirroring thesis-auditor's own `<project-dir>/src/main.tex` convention (`thesis-auditor.md:98`): `frontmatter.md` (everything before the first real `CHAPITRE N`), one file per chapter via `chapter_filenames()` (first chapter -> `Introduction.md`, last -> `Conclusion.md`, every chapter in between -> `chapitreN.md`), `bibliography.md` when found, and `main.md` linking all of them in order. |
| 6. References | `pdf2md_refs.py` | Restructures mineru's flat numbered bibliography (`[171] Lin Xiao and Stephen Boyd. Fast linear iterations...`) into `ref.md`, one block per entry with labelled Authors/Title/Venue fields and a `firstauthor+year+keyword` key (this repo's own citation-label convention, code-style.md) -- BibTeX-LIKE, not literal `.bib` syntax, per the confirmed output-shape decision for this skill. Heuristic text split, not a full citation parser; documented limitation in the module docstring. |

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

## When something doesn't match this document

Re-verify against the installed version rather than trusting this file
blindly (R14) -- `pdf2md version` is the first check. If mineru's own CLI
surface or config schema has changed, the fix belongs in this skill's
scripts (R18: a script lives beside its only caller), with a new offline
test pinning the new behavior, following the "Improving ResearchTools from
another folder" protocol in the repo-root `.claude/CLAUDE.md`.
