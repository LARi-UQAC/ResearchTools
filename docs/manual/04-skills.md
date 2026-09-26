# Skills

Chapter 04 of the ResearchTools manual. Back to [table of contents](../../README.md).

Skills bundle scripts and references the agents reuse. Fifteen ship in this repo, and every one
of them is written here.

**This repository vendors no skill it did not write.** Two were vendored on 2026-08-30 and both
were removed the same day, because each already had its own delivery path and the copy only
created a second one that would drift:

- `tech-debt` is delivered by the `engineering@knowledge-work-plugins` plugin, which both
  `.claude/settings.template.json` and `.claude/settings.json` declare in `enabledPlugins`. The
  vendored file was byte-identical to the plugin's own, which Claude Code serves from
  `~/.claude/plugins/cache/`. A plugin declaration is the delivery mechanism; a copy is not.
- `graphify` ships with the graphify tool, installed on the machine with
  `uv tool install graphifyy`. The skill is a property of that installation, not of this
  repository.

The consequence is stated rather than hidden: a clone whose machine has neither the plugin
enabled nor the graphify tool installed gets `local-writer` referring to a code graph it cannot
reach. That is a machine-setup gap, answered by the Prerequisites table in
[01-installation.md](01-installation.md), and not something
a copied `SKILL.md` fixes - a vendored copy of a CLI's skill without the CLI is instructions for a
tool that is still absent. `test_settings_template_distribution.py` asserts that neither name
reappears under `.claude/skills/`.

| Skill | Purpose | Entry point |
|---|---|---|
| `scopus` | Search Scopus (citation-ordered, title/abstract/keyword scoped), validate references (ambiguity-flagged), fetch PDFs via the Elsevier REST API (with a Semantic Scholar fallback). | `/scopus`, `.claude/skills/scopus/SKILL.md` |
| `scientific-writing` | Core writing skill: scientific manuscripts in flowing IMRAD prose with verified citations (IEEE/APA/AMA/Vancouver) and reporting guidelines (CONSORT/STROBE/PRISMA). | `.claude/skills/scientific-writing/SKILL.md` |
| `scholar-evaluation` | ScholarEval framework — scores research work across problem formulation, literature review, methodology, data, analysis, results, writing, citations. | `.claude/skills/scholar-evaluation/SKILL.md` |
| `deliberation` | Two-round Gemini ↔ GitHub Copilot debate over a near-final draft; Claude arbitrates and validates any new references against Scopus. Used inside the auditor/researcher agents. | `.claude/skills/deliberation/SKILL.md` |
| `extract-statistic` | Statistical analysis. Mode `audit`: review a manuscript's own statistics (test selection, assumptions, effect size, presentation, cross-validation). Mode `mine`: extract the reported statistics of a corpus's full-text PDFs and synthesize a corpus statistics table plus an improvement-opportunity list. Engineering-default domain profiles. Used inside `paper-auditor` / `thesis-auditor` (audit) and `scopus-researcher` (mine). Also carries `parse_cache.py` (content-addressed PDF-parse cache, additive to every consumer) and the opt-in `corpus_index.py` (deterministic chunker, injected embedder, pgvector store for ad-hoc cross-corpus retrieval; every hit is provenance, never a citation). | `.claude/skills/extract-statistic/SKILL.md` |
| `extract-futureworks` | Future-works analysis (reuses `extract_text.py --section-scan`). Mode `audit`: review a work's own future works (presence, testability, link-to-limitation, novelty) and validate its hypotheses against the cited-corpus future works, proposing stronger ones. Mode `mine`: extract every corpus paper's stated future works, build a review-fit table, Pareto 80/20-rank it (low effort, high impact first), and emit a research-opportunity list. Used inside the four auditors (audit) and `scopus-researcher` (mine), where it is a hard gate: no hypothesis/project without it. | `.claude/skills/extract-futureworks/SKILL.md` |
| `extract-contributions` | What a cited paper says it CONTRIBUTES, out of its full text (reuses `extract_text.py`; ships no reader). Mode `validate`: pair every `\cite{}` of a manuscript with the paper's own contribution sentences and flag the citations the paper does not support. Mode `mine`: tabulate a `refs/` corpus by kind. Surfaces evidence verbatim and decides nothing; `ok` / `no-contribution` / `empty` / `unreadable` are kept apart so a retrieval failure is never read as a property of the paper. Markers are data in `contribution_markers.json`. | `.claude/skills/extract-contributions/SKILL.md` |
| `extract-paper-idea` | Extract a paper's OWN content into one JSON, the basis for drafting or refreshing its abstract (or, for a UQAC thesis, its Résumé + Abstract pair). Ships no reader of its own: reuses `paper2talk`'s `\input`/`\include` flattening and section map, `extract-statistic`'s future-works-cue section scan, and `extract-contributions`' marker scan (pointed at the paper's own text instead of a cited one). Detects document type (`uqac.cls` on the flattened text) and the document's own language; never a forced bilingual pair for a paper, always both languages for a thesis. Delegates the drafting to the `abstract-writer` agent. | `/abstract`, `.claude/skills/extract-paper-idea/SKILL.md` |
| `paper2talk` | Accepted paper -> conference talk. Asks six questions before reading the paper (audience, duration, output target, aspect ratio, PDF format, deck ending), echoes a build contract, then builds ONE `talk_model.json` and renders it to PowerPoint (pptxgenjs), LaTeX Beamer on the lab gabarit, or a self-contained web page. Speaker notes budgeted at 130 wpm aiming under the slot, figures re-exported through the draw.io CLI at scale 3, and a visual QA loop (PowerPoint COM -> `pdftoppm`) with a legibility gate and a no-text-only-slide rule. Delegates the loop to the `talk-builder` agent. | `/talk`, `.claude/skills/paper2talk/SKILL.md` |
| `word2latex` | Convert a Word `.docx` template (Mitacs, CRSNG, FRQNT, UQAC, partner forms) into a faithful LaTeX source. Delegates the patch work to the `word-to-latex` agent. | `/word2latex`, `.claude/skills/word2latex/SKILL.md` |
| `drawio2tikz` | Convert one `.drawio` sheet into a coordinate-exact TikZ fragment (absolute coordinates, edge anchoring, braces, rotation, FR→EN `--translate`). The sanctioned absolute-coordinate exception to the hand-authored TiKZ rules. | `/drawio2tikz`, `.claude/skills/drawio2tikz/SKILL.md` |
| `geolocalisation` | Map a review corpus in space from its `.bib`: resolve each paper's study/case-study site (per-DOI Scopus abstract + title + keywords, optional `--full-text` PDF scan via `download_pdf.py`, matched against an offline Natural Earth gazetteer), write a reviewable draft table with a confidence column and a per-paper provenance note, then render CSV, KML (Google My Maps), GeoJSON (QGIS/Leaflet), a world-map PNG, an interactive HTML map, and a per-country count table. Human-reviewed; an override CSV always wins. | `/geolocalisation`, `.claude/skills/geolocalisation/SKILL.md` |
| `loop-engineer` | Budget-bounded develop-and-improve loop (Agent SDK driver): design → plan → code → comment → test → review → score → correct, looping until a composite gate (tests green, no CRITICAL/HIGH, score `>=` min) or a hard budget/max-iters/no-progress stop. Fable 5 orchestrates; Opus/Sonnet act; `local-coder`/`local-writer` do local generation. `loop_audit.py` aggregates the installed reviewers into a 0-100 score with a security hard floor; merge to a protected branch is human-gated. | `/loopdev`, `.claude/skills/loop-engineer/SKILL.md` |
| `recommendation-letter` | Generate support, recommendation, appreciation, acceptance, and dispense (short-stay invitation) letters in LaTeX → PDF from a candidate's files. Two tracks: Claude authors the four persuasive types (fr/en); a stdlib-only Python script fills the fixed French acceptance/dispense forms (candidate status, funding provider, 120-day work-permit exemption, paired output). Sample data is synthetic. | `/recommendation-letter`, `.claude/skills/recommendation-letter/SKILL.md` |
| `narrative-cv` | Draft, refresh, or tailor the narrative "CV descriptif" (FRQ CV-FRQ, structurally identical to the tri-agency CIHR/NSERC/SSHRC CV commun des trois organismes) to one grant competition: three sections, up to 10 items in section 2, 6-page FR / 5-page EN cap. Built around a durable master contributions inventory in the researcher's own external project folder, refreshed via Scopus (AU-ID two-step) + `extract-contributions` and re-ranked per competition by keyword overlap against that program's own objectives/evaluation criteria rather than rebuilt from scratch each time. Renders LaTeX/PDF and a plain-text companion for the new-FRQnet-portal paste-in channel from one JSON model (`paper2talk`'s one-model-many-renderers pattern). | `/cv`, `.claude/skills/narrative-cv/SKILL.md` |
| `obsidian-cli` | Read and search the Obsidian vault through the allowed command surface only (`read`, `search`, `list`, `property:get`/`property:set`, `tasks`, `links`, `tags`, `move`, `rename`); a captured learning is deposited to the outbox, the single write path, instead of calling a write command directly. The direct CLI write commands (`create`, `append`, `prepend`, plus `eval`, `dev:*`, `plugin:install`, `theme:install`, `sync*`) are forbidden for measured reasons: the failure sits in the whole JSON header, not the content (a 3850-byte header passes, 4343 does not, and 4096, a Windows named-pipe buffer, falls between); the CLI exits 0 on that failure too; and `create` on an existing file writes a numbered duplicate instead of failing. | `.claude/skills/obsidian-cli/SKILL.md` |
| `latex-hygiene` | Measure LaTeX manuscript hygiene mechanically: forbidden characters, an AI-usage risk score, prose and track-changed word counts, abstract length, brace/`\begin`-`\end` balance, `changes`-macro paragraph-crossing corruption, and label/citation coverage (`citecov` against a `.bib`, `refcov` for uncited labels, dangling refs, and duplicate labels). Backs the `aiscan`/`wc` checks that `paper-auditor` and `submit-checker` already describe in prose, so the same signal table and score formula are computed the same way every time. The write side applies a machine-readable audit plan (`patch`), scans for post-write corruption (`scan`), and resolves and builds the tracked or accepted PDF (`accept`, `build`). | `/texcheck`, `.claude/skills/latex-hygiene/SKILL.md` |
| `form-service` (was `uqac-forms`, renamed 2026-09-25) | Stateless mechanics for official PDF forms from any institution. RT-1 ships the validated ingest contract: https only re-checked on every redirect hop, at most 5 redirects followed manually, a 25 MiB cap enforced during the stream, `%PDF` magic bytes, a 30 s timeout, and an atomic write. The form catalogue, field maps and profile live in ThesisTracker, not here. Filling (RT-3), PAdES signing (RT-4) and signature validation follow. RT-5 exposes all of it as a stateless HTTP API in `deploy/form-service/` (`/pdf/widgets`, `/pdf/fill`, `/pdf/sign`, `/pdf/validate`), shared-secret gated, no CORS, nothing persisted. See chapter [09](09-thesistracker-integration.md) for the boundary with ThesisTracker. | Yes |
| `graphify` *(external: `uv tool install graphifyy`, not shipped here)* | The code-graph memory: turn a folder of files into a queryable knowledge graph, then ask it what calls what, how one node reaches another, and what a symbol is. `query`, `path` and `explain` are deterministic traversals of `graphify-out/graph.json` and cost no model at all, which is why one graph query beats grepping file by file. Reached only through `local-writer`, like the vault. The CLI itself is a separate install (`uv tool install graphifyy`); this directory is the SKILL, kept here so a clone is never told to consult a graph it has no way to reach. `.graphify_version` records the version it was generated from - refresh the copy after upgrading the CLI. | `/graphify`, `.claude/skills/graphify/SKILL.md` |
| `opt-local-vram-llm` | Tune a local Ollama model for this GPU: retain the largest `num_ctx` that keeps the model 100 percent resident in VRAM, among configurations whose decode throughput clears a floor (default 0.90 of the best admissible run). Reads the manifest and daemon facts read-only, renders a tuned Modelfile, sweeps `num_ctx` against `OLLAMA_KV_CACHE_TYPE` (restarting the daemon per value and proving the restart took effect from `server.log`, restoring the original value on failure), then declares the tuned tag as a role candidate in `local-models.json`. Stops before qualification, which stays with `model_resolver.py --qualify`. | `/opt-local-vram-llm`, `.claude/skills/opt-local-vram-llm/SKILL.md` |
| `aider-setup` | Set up, tune and run the aider nightly local-coding pipeline — a second, independent local-coding harness that needs no Claude Code: two local Ollama models (a writer that codes and tests, a reviewer that never edits, gated by measured token budgets) run one aider process per plan overnight, driven by `aider-plan.ps1`/`aider-night.ps1`. Owns the packaging pipeline (`scripts/build/`) that assembles the student-facing `aider-kit.zip` from this skill's own canonical sources, with a leak scan and an install-and-dry-run gate. `config/rules.md` is generated at build time from this repository's own `.claude/rules/` (R26 fixes the plan-file shape every harness reads; R27 the function-header convention). See chapter [06](06-aider-pipeline.md) for the full picture. | `.claude/skills/aider-setup/SKILL.md` |

### `/scopus` — Scopus academic search

Searches the Scopus database via the Elsevier REST API. Requires `SCOPUS_API_KEY`
(see the API-keys table in [02-profiles.md](02-profiles.md)) and an active institutional network connection
(campus or VPN), or an `--insttoken`.

| Command | What it does |
|---------|-------------|
| `/scopus <topic>` | Search top papers on a topic — **ordered by citation count**, and bare keywords are scoped to title/abstract/keywords. Add `--sort recent` when you want the newest papers instead |
| `/scopus review <topic>` | Structured literature review with inline citations |
| `/scopus validate <DOI or title>` | Confirm a reference exists. Flags `ambiguous` when several records share the title, so `results[0]` is never taken on faith |
| `/scopus cite <DOI>` | Citation count + full metadata for one paper |
| `/scopus author AU-ID(<digits>)` | Author profile: document count, affiliation, computed h-index, top papers. Works on a Search-only key |
| `/scopus author <name>` | Same, when the key is entitled for the Author Search API; otherwise degrades to Semantic Scholar candidates and says so (no Scopus AU-ID can be resolved from a name without that entitlement) |
| `/scopus journal <name or ISSN>` | Journal SJR quartile, CiteScore, subject areas |

**Files:**
- `.claude/skills/scopus/SKILL.md`
- `.claude/skills/scopus/scripts/scopus_api.py` — Scopus REST client. `search` orders by `-citedby-count` (`--sort recent` for date order; the alias is required because argparse refuses a value starting with a dash) and wraps a query naming no Scopus field in `TITLE-ABS-KEY()`; without both, a search answered only this year's least-cited papers, and citation ordering on an unqualified query answered the most-cited papers of all science. `validate` queries the title as a quoted phrase and publishes `title_similarity` plus an `ambiguous` flag. `journal --issn` is the reliable venue lookup: it resolves print and electronic ISSNs in turn and returns the best CiteScore subject percentile with the quartile derived from it (a lookup by title, or an ISSN lookup combined with `field=`, answers a stub). `publications` returns one author's document list, most recent first, each carrying its own DOI and an `approved_publisher` flag against the CLAUDE.md list (flagged, never dropped); `deploy/form-service/`'s `GET /publications` wraps it in a disk cache and a rate limiter so the Scopus key, the throttling, and the publisher policy never cross the service boundary to ThesisTracker
- `.claude/skills/scopus/scripts/doi_publisher.py` — DOI prefix → publisher. `search`, `validate` and `cite` all carry `doi_prefix` and `publisher_by_prefix`; the prefix is assigned by the registration agency, whereas Scopus `prism:publisher` was measured naming a learned society for a Springer DOI and an imprint for an Elsevier one
- `.claude/skills/scopus/scripts/bib_batch.py` — **candidates → `.bib`**: strict `TITLE()` title-to-DOI resolution, cite enrichment, venue grading, BibTeX generation
- `.claude/skills/scopus/scripts/bib_audit.py` — **`.bib` → audit**, the opposite direction: required fields, duplicates, DOI validation against Scopus, venue metrics by ISSN, publisher approval, then an annotated pass-through copy (`<base>_clean.bib`) and a measured report (`<base>_bib_report.md`). Drives the `bib-cleaner` agent; `--no-network` replays from its cache
- `.claude/skills/scopus/scripts/semantic_scholar_api.py` — Semantic Scholar fallback
- `.claude/skills/scopus/scripts/download_pdf.py` — any-format full-text retrieval (PDF, else HTML/Markdown via Unpaywall, arXiv, PMC, validated DOI landing), plus an opt-in `--browser` tier
- `.claude/skills/scopus/scripts/browser_fetch.py` — tier 8: a real Playwright Chromium for challenge-gated publishers (Akamai/Cloudflare), with a per-paper `refs/_sources.json` override URL (e.g. ResearchGate) for papers with no institutional access; optional (needs `playwright` + `playwright install chromium`)
- `.claude/skills/scopus/scripts/litreview_update.py` — incremental-update bookkeeping for `/litupdate` (baseline fingerprint, delta dedup via `bib_batch.title_match`, dated output paths, CHANGELOG scaffold)
- `.claude/skills/scopus/scripts/gemini_reviewer.py` · `github_reviewer.py` · `gemini_table.py` — cross-review cores

### `geolocalisation` — corpus study-location mapping

Turns a corpus `.bib` into a spatial map of where each paper's empirical study was conducted.
A case-study site is not a bibliographic field (no API returns it — it lives in the text), so
the skill is deliberately human-in-the-loop: it emits a **draft** with a `confidence` column and
a per-paper provenance note, a human reviews it, and a manual **override CSV always wins** before
rendering. Requires `SCOPUS_API_KEY` (campus network or VPN), or run `--no-scopus` for a
manual-entry template.

| Stage | Command | Output |
|---|---|---|
| 1 — extract | `extract_locations.py --bib <corpus.bib> --out <dir> [--full-text] [--override <curated.csv>]` | `study_locations.csv` (with `confidence`, `evidence_field`, `evidence`, `provenance`) + `provenance/<citekey>.md` audit notes |
| 2 — review | *(human)* | curate / confirm; correct every `low`/`none` row via the override CSV |
| 3 — render | `generate_geomap.py --csv <dir>/study_locations.csv --out <dir> [--formats …] [--min-confidence …]` | CSV, KML (Google My Maps), GeoJSON (QGIS/Leaflet), world-map PNG, interactive HTML, `country_counts.csv` |

- **Extraction:** per-DOI Scopus abstract + title + keywords; place names matched against an
  offline Natural Earth gazetteer, with capitalization + a population floor + a common-word
  stoplist for precision (separates the city `Mobile` from the word `mobile`).
- **`--full-text`:** for `none`/`low` results, downloads the PDF via the scopus skill's
  `download_pdf.py`, reads it with PyMuPDF, and scans **only study-cue sentences with
  affiliation lines rejected** — an unfiltered full-text scan maps author affiliations, not
  study sites. Adopted only when it beats the abstract; PDFs cached in `refs/`.
- **Auditability:** every mapped point carries `evidence_field` + the verbatim `evidence`
  sentence in the CSV, a `provenance/<citekey>.md` note, and the same surfaced in the HTML
  popup, GeoJSON properties, and KML description.
- No geopandas/GDAL — the basemap is drawn from raw GeoJSON. Deps: `matplotlib` (PNG),
  optional `folium` (HTML) and `PyMuPDF` (`--full-text`).

**Files:**
- `.claude/skills/geolocalisation/SKILL.md`
- `.claude/skills/geolocalisation/scripts/extract_locations.py` — bib + Scopus/full-text → draft CSV + provenance notes
- `.claude/skills/geolocalisation/scripts/generate_geomap.py` — reviewed CSV → CSV/KML/GeoJSON/PNG/HTML + per-country table (no geopandas)
- `.claude/skills/geolocalisation/references/geocoding-protocol.md` — extraction method, confidence rubric, override format, full-text pipeline
- `.claude/skills/geolocalisation/scripts/Test/test_extract_locations.py` — offline unit tests (bib parse, matcher, evidence, full-text)

### recommendation-letter — support / recommendation / acceptance / dispense letters

Generates supervisor letters in LaTeX → PDF from a candidate's own files, signed by the
active profile's author (`profiles/<active>.yaml`, `author.letter`; a profile with no such
block is a stated refusal, never a letter signed with someone else's name). Two
tracks: Claude authors the four persuasive types (scholarship, academic_position,
industry_position, appreciation; French or English), while a Python
script fills the fixed French **acceptance** and **dispense** forms. `candidate_status`
(applicant / current_student / graduated) sets how the candidate is named; `funding_provider`
(supervisor / candidate / combination) branches the funding paragraph; the dispense letter
carries the < 120-day work-permit exemption paragraph and warns when a stay exceeds it;
`invitation_pair=both` emits the acceptance and dispense letters together. A style-hygiene
linter enforces the AI-usage rules. All shipped sample data is synthetic.

**Files:**
- `.claude/skills/recommendation-letter/SKILL.md`
- `.claude/skills/recommendation-letter/scripts/generate_letter.py` — two-track assembler, validator, `pdflatex` compile
- `.claude/skills/recommendation-letter/scripts/letter_templates.py` — preamble, letterhead/signature, acceptance/dispense French templates
- `.claude/skills/recommendation-letter/scripts/Test/test_generate_letter.py` — offline unit tests (53 cases)
- `.claude/skills/recommendation-letter/references/quality-patterns.md` — authored-track quality patterns
- `.claude/skills/recommendation-letter/evals/` — synthetic sample configs

### `narrative-cv` — FRQ / tri-agency narrative CV

FRQ's CV-FRQ and the tri-agency (CIHR/NSERC/SSHRC) "CV commun des trois organismes" are the same
format (verified against both official pages 2026-09-25): three sections (career/skills, up to
ten contributions and experiences, supervision and mentoring), 6 pages French or 5 English. Built
around a durable master inventory rather than a stateless per-run extraction, so a grant CV is a
re-selection over a growing corpus instead of a from-scratch rebuild each time.

| Stage | Script | Job |
|---|---|---|
| 1 — inventory | `cv_inventory.py` | CRUD over the master inventory YAML (`init`/`add`/`list`/`stats`/`mark-used`), validated and deduplicated by id/DOI. Never calls Scopus itself. |
| 2 — select | `cv_select.py` | Deterministic keyword-overlap ranking against a competition's own objectives/evaluation criteria — a signal for the drafting agent's judgment, not a verdict. |
| 3 — build | `cv_build.py` | Renders ONE `cv_model.json` to LaTeX and a plain-text companion, builds the mandatory old-portal filename (`NOM_XXXXX1234_Titre.pdf`, normes_presentation.pdf), and checks the compiled page count against the 6/5-page cap. |

The candidate's identity (CV header/footer, filename surname) and the external project folder
the inventory and drafts live in (`cv.project_dir`) both come from the active profile
(`profiles/<active>.yaml`), never from a hardcoded path — a profile carrying neither block is a
stop, not a guess. Drives the `narrative-cv-writer` agent, reached via `/cv`.

**Files:**
- `.claude/skills/narrative-cv/SKILL.md`
- `.claude/skills/narrative-cv/scripts/cv_common.py` — shared helpers: contribution-types loader, active-profile identity/project-dir resolution (no fallback), FRQ filename builder
- `.claude/skills/narrative-cv/scripts/cv_inventory.py` — the master inventory CRUD
- `.claude/skills/narrative-cv/scripts/cv_select.py` — keyword-overlap ranking
- `.claude/skills/narrative-cv/scripts/cv_build.py` — LaTeX/text rendering, filename, page-budget check
- `.claude/skills/narrative-cv/scripts/contribution_types.json` — section titles, clientele/category vocabularies, page budget, portal/font variants (data, not code)
- `.claude/skills/narrative-cv/scripts/Test/test_cv_common.py`, `test_cv_inventory.py`, `test_cv_select.py`, `test_cv_build.py` — offline unit tests (61 cases; no network, no LaTeX install, no machine-local profile dependency)

### `paper2talk` — accepted paper to conference talk

Starts where `submit-checker` and `cover-paper` stop: the paper is accepted, the talk is the
next deliverable. The skill asks **six questions before reading the paper** — audience,
duration and conference, output target, aspect ratio, PDF format, and how the deck ends —
because every one of them is an input to a number the build cannot invent, then echoes a build
contract (`n_content`, word budget, font floor, preferred form, deliverables) before a single
slide is authored.

| Stage | Command | Output |
|---|---|---|
| 0 — preflight | `talk_doctor.py --target pptx` | per-dependency state, which targets are buildable here, what degrades without each missing tool |
| 0b — read | `paper_extract.py main.tex --out inventory.json` | `\input`-flattened sections, floats with labels/captions/assets, equations, citation keys, and the number inventory the deck is checked against |
| 1 — brand | `talk_template.py <gabarit.pptx> --out brand.json --extract-media assets/` | canvas, layouts, master background, every object in inches with `srcRect` as a keep-fraction |
| 2 — figures | `fig_export.py <fig.svg> --out <fig.png> --scale 3 [--fix-text map.json]` | projector-grade PNG + implied-DPI report (warns below 150) |
| 3 — model | `talk_model.py <talk_model.json>` | block-vocabulary check, no-text-only-slide rule, exhibit coverage, budget aggregation |
| 4 — render | `talk_pptx.py --template <gabarit.pptx>` · `talk_model.py --render …tex.j2` (Beamer) · `…html.j2` (web) | `.pptx` built on the gabarit's own layouts, `.tex`, or one self-contained `.html`, all from the same model |
| 5 — gates | `talk_validate.py` · `talk_notes.py` · `talk_render.py [--paper a4]` | package + legibility checks, spoken budget and cadence, PDF + page images, A4/Letter reflow |

- **Cadence.** One slide per minute counts **content** slides only:
  `n_content = floor(minutes - 0.5*(title+thanks) - 0.33*dividers)`. A 13-minute talk is 12
  content slides and 15 in all, or 10 and 18 with five dividers.
- **Rate.** 130 words per minute for a technical talk (not the 150 wpm of conversational
  speech), aimed at `(minutes - 1.5) x 130` so the talk lands under the slot.
- **Audience-parameterised typography.** 16 pt body floor in the field (14 pt for captions and
  references), 20 pt for a general-public talk; no bullet cap for a scientific audience, since a
  slide may legitimately carry seven or eight equations. The cap is replaced by a mechanical
  legibility gate.
- **Content hierarchy.** figure > table > equation > prose. Prose, bullets included, is the last
  resort; a content slide with no exhibit is a defect, and every exhibit must be discussed in
  its own speaker notes (matched on subject keywords, never filenames).
- **Gabarits.** `../gabarit_these_maitrise_DSA_UQAC/src/slides/`: `Gabarit169.pptx` (16:9, 18
  named layouts), `Gabarit43.pptx` (4:3, preferred when an A4 handout is the deliverable),
  `main.tex` for Beamer. The deck is built **on** the gabarit with python-pptx rather than
  imitated, so the lab branding, layouts and placeholders are used as designed.
- **Nothing invented.** `talk_model.py --check-numbers inventory.json` compares every number
  on every slide against the numbers the paper states, on normalised values (a French decimal
  comma and an English point are one number), so a figure that entered the deck from nowhere is
  caught before the room catches it.
- **Windows render path.** PowerPoint COM `SaveAs(..., 32)` then `pdftoppm`; the
  `document-skills` `soffice.py` wrapper fails here with `AF_UNIX`. `soffice` is used when it is
  on `PATH`. A legacy `.ppt` gabarit is converted with `talk_template.py --convert`
  (`SaveAs(..., 24)`), leaving the original untouched.

**Files:**
- `.claude/skills/paper2talk/SKILL.md`
- `.claude/skills/paper2talk/scripts/talk_rules.py` — audience profiles, tier costs, cadence, budget, build contract
- `.claude/skills/paper2talk/scripts/talk_model.py` — deck-as-data validation + Jinja render of the Beamer/web targets
- `.claude/skills/paper2talk/scripts/talk_doctor.py` — preflight: buildable targets, per-tool degradation
- `.claude/skills/paper2talk/scripts/paper_extract.py` — paper → inventory (`\input` flattening, floats, equations, numbers)
- `.claude/skills/paper2talk/scripts/talk_pptx.py` — PowerPoint renderer: opens the lab gabarit, drops its sample slides, builds on its own layouts and placeholders
- `.claude/skills/paper2talk/scripts/talk_template.py` · `fig_export.py` · `talk_render.py` · `talk_notes.py` · `to_a4.py` · `talk_validate.py`
- `.claude/skills/paper2talk/assets/deck_skeleton.js` (no-gabarit fallback) · `beamer_skeleton.tex.j2` · `web_skeleton.html.j2`
- `.claude/skills/paper2talk/references/renderer-contracts.md` · `qa-loop.md`
- `.claude/skills/paper2talk/scripts/Test/` — thirteen offline suites, 182 tests (fixtures built in the test; no Office, no network)
- Harvest and licence findings: `docs/superpowers/notes/2026-08-11-reference-skill-harvest.md`

### The two memories - the vault and the code graph

Two memories back this toolkit, and they do not overlap. The Obsidian vault holds what was
LEARNED, across every project: a failure and its root cause, a decision and why, a tool that
misbehaves. The graphify knowledge graph in `graphify-out/` holds what this repository's code
IS right now: which function calls which, how one module reaches another, where a symbol
lives. The vault is permanent and hand-curated; the graph is derived from the files and
therefore rebuildable and disposable.

The routing rule follows from that. A question about **this code** goes to the graph first,
and `query`, `path` and `explain` are deterministic traversals that cost no model at all, so
one graph query beats grepping file by file. A question about a failure mode, a misbehaving
tool or a past decision goes to the **vault** first. Many tasks want both, in that order.

Both are reached the same way and only that way: **dispatch the `local-writer` agent**. It is
the single reader and the single writer of both memories. Consulting or refreshing the graph
by hand is the same breach as reading the vault by hand, and since 2026-08-30 the
`vault-access-guard.py` hook enforces BOTH at the tool boundary rather than only the vault. For the
vault it matches by PATH rather than by command; for the graph it matches the `graphify-out/` path,
the `graphify` CLI, and the two graph audit scripts by name, because running a read-only health
check to learn the graph's state is a consultation in which the graph's path never appears.
The graph is refreshed by writing a file and then pointing `graphify update <path>` at it,
never by editing `graph.json`.

**What the graph does not answer.** Measured 2026-08-30 through a `local-writer` consultation:
every node carries `_origin: ast`, so the graph holds the code and the *structure* of each `.md`
file - headings, names, where things live - and no layer that read what those files say. Asked
"why is the Obsidian CLI write path forbidden", it returned 109 nodes of file names, command
names and test-class names, and none of the three measured reasons (the header-size threshold,
the CLI exiting 0 on a failed write, `create` making a numbered duplicate). Those reasons live in
`.claude/CLAUDE.md` and in the vault. So the graph is asked *what calls what*, and the vault is asked *why*.
Asking the graph for intent is the failure that hurts, because it returns names that read like an
answer. Adding the missing layer is possible and needs no API key - the graphify skill's own flow
has the host agent read the documents - but it is a deliberate, token-costing run, so
`check-graph-health.ps1` reports the state as a note and does not fail on it.

The graph's own state is the one thing a session may read directly, because it is metadata
rather than content: `scripts/audit/check-graph-health.ps1` is read-only and reports what is
in the graph, which files it claims to cover and never produced a node for, and whether any
covered file is newer than the graph itself. It exits 0 where there is no `graphify-out/` at
all, so it is harmless in a project that has no graph.

### `obsidian-cli` - Obsidian vault operations

Gives Claude the vault's allowed read/search command surface (`read`, `search`, `list`,
`property:get`/`property:set`, `tasks`, `links`, `tags`, `move`, `rename`) and the single
sanctioned write path: a captured learning is drafted, dropped in
`~/.claude/obsidian-outbox/` with a `create|append path="..."` directive on its first line,
and the `obsidian-outbox-flush.py` hook (SessionStart/SessionEnd) writes it into the vault
through the filesystem, verifying the effect by file size before and after rather than
trusting the CLI's return code.

`create`, `append`, and `prepend` (plus `eval`, `dev:*`, `plugin:install`, `theme:install`,
and every `sync*` except read-only `sync:history`) are forbidden commands. The measured
reasons: the write fails on the whole JSON header size (content, path, `tty`/`cwd`), not
the content alone - a 3850-byte header passes, a 4343-byte header does not, and 4096 bytes,
a Windows named-pipe buffer, falls in between; the CLI exits 0 even when the write failed,
so a script checking the return code archives notes that were never written; and `create`
on an existing file silently writes a numbered duplicate (`Decisions 1.md`) instead of
failing.

**Files:**
- `.claude/skills/obsidian-cli/SKILL.md`
- `.claude/skills/obsidian-cli/references/command-reference.md` - full command syntax
- `.claude/skills/obsidian-cli/scripts/vault_consolidate.py` - deterministic half of
  consolidation: measures shared tags/`domaine`/term overlap and proposes links, decides
  nothing; `--mode links` reports dead wiki-links read-only, and `--apply <map.json> --yes`
  is the one guarded, map-validated, single-pass rewrite of existing links exempted from the
  outbox-only write rule
- `.claude/skills/obsidian-cli/scripts/vault_daemon.py` - the unattended path. A raw drop
  (unrouted text in `~/.claude/obsidian-outbox/raw/`, three frontmatter keys, no directive)
  is classified, drafted, filed, journalled and queued for consolidation without a session:
  the cloud wrapper pushes, the local model decides. `--once` handles what is pending,
  `--drain` runs the deferred work by hand, `--dry-run` lists and touches nothing. Anything
  it is not confident about is parked in `needs-review/` with its reason, for `local-writer`
  to file with the whole reusable layer in context
- `.claude/skills/obsidian-cli/scripts/daemon_outbox.py` - the outbox layout that IS the
  queue (`raw`, `working`, `raw/sent`, `needs-review`, `state`, `queue`), plus the write
  lock, the one-daemon-per-machine singleton lock, the atomic claim by rename, and the sweep
  that recovers a drop stranded by a crash
- `.claude/skills/obsidian-cli/scripts/daemon_states.py` - the per-state handlers; both
  model calls are constrained by a JSON schema, and every refusal parks the event
- `.claude/skills/obsidian-cli/scripts/daemon_drains.py` - the deferred half: candidate
  pairs judged one per call on the strict mechanism test, accepted edges appended
  reciprocally with their sentence and journalled. Phantom repair stays human-gated
- `.claude/skills/obsidian-cli/scripts/local_capability_probe.py` - the gate that measured,
  before any of this was written, that the daemon honours a JSON schema and re-uses a
  prompt prefix
- `.claude/skills/obsidian-cli/scripts/vault_lock.py`, `vault_journal.py`, `outbox_io.py` -
  the shared write path: one lock across sessions and processes, an append-only record of
  every vault write with an `--undo`, and the single implementation the flush hook and the
  daemon both call
- `.claude/skills/obsidian-cli/daemon-config.json` - every timeout, ceiling and threshold,
  with its provenance; no such value is written in the code that uses it

### `latex-hygiene` - mechanical LaTeX manuscript hygiene

Turns the hygiene checks `paper-auditor`, `submit-checker`, and `thesis-auditor` already describe
in prose into one script with subcommands, so the AI-usage score, the word count, and the brace
balance are computed the same way every session instead of by hand. One script, `tex_check.py`;
every subcommand takes paths or globs, never a hardcoded manuscript path, and accepts `--json`.

| Subcommand | Input | Output |
|---|---|---|
| `chars` | `.tex` files/globs | per-file forbidden-character hits (line + name) and a total count |
| `aiscan` | `.tex` files/globs | `risk_score`, weighted count per signal, lowest-deviation sentence window, a 15-word excerpt per hit |
| `wc` | `.tex` files/globs | prose word count per file (floats and comments excluded), float count, total, page estimate |
| `wc --accepted` | `.tex` files/globs, optional `--before <dir>` | word count of the accepted text (`changes` macros resolved); with `--before`, a before/after/delta/percent table |
| `abstract` | main `.tex` | abstract word count, keyword count |
| `braces` | `.tex` files/globs | final brace depth per file, the line of the first negative dip, and `\begin`/`\end` environment balance |
| `par` | `.tex` files/globs | occurrences of `\added`/`\deleted`/`\replaced` whose argument crosses a blank line (the macros are not `\long`, so this breaks a build) |
| `citecov` | `--tex <globs> --bib <file>` | cited keys absent from the `.bib` (dangling), and `.bib` entries never cited |
| `refcov` | `.tex` files/globs | uncited labels, dangling `\ref`/`\eqref`/`\cref` targets, and duplicate labels |
| `patch` | `--plan <audit_plan.md> --target <file.tex>`, optional `--author <id>`, `--dry-run`, `--init` | applies an audit plan by exact-match substitution, one occurrence required per edit; a `FAILS:` list and non-zero exit on any 0-match or 2+-match edit |
| `scan` | `.tex` files/globs, optional `--bib <file>`, `--fail-on-markers` | post-write guard for control characters, damaged control-sequence residue, `changes` macros crossing a table/float boundary, a `%` comment that swallowed a row-terminating `\\`, a stale `\cite` inside a deleted span, and live `\hl{}`/`\todo{}` markers |
| `accept` | `--target <file.tex>`, optional `--out <path>`, `--resolve` | the accepted source, `[final]{changes}`/`[disable]{todonotes}`, generated from the tracked source |
| `build` | `--target <file>`, optional `--outdir out`, `--both` | pdflatex/bibtex/pdflatex/pdflatex with mandatory `BIBINPUTS=".."`, refusing a `.bib` inside the output directory |
| `all` | files/globs | the aggregate of the read-side subcommands above |

`aiscan` reproduces the High/Medium signal weights and the `risk_score` formula stated in
`paper-auditor.md` Step 7.5 (a High signal counts 2, a Medium signal counts 1, toward `raw_count`).
The script is pure Python standard library, so it needs no `requirements.txt` and adds no
`pip-audit` surface.

**Files:**
- `.claude/skills/latex-hygiene/SKILL.md`
- `.claude/skills/latex-hygiene/scripts/tex_check.py` - thin CLI dispatching to the subcommand modules
- `.claude/skills/latex-hygiene/scripts/tex_common.py`, `tex_chars.py`, `tex_braces.py`, `tex_par.py`,
  `tex_citecov.py`, `tex_abstract.py`, `tex_wc.py`, `tex_aiscan.py`, `tex_aiscan_text.py`
- `.claude/skills/latex-hygiene/scripts/tex_patch.py`, `tex_scan.py`, `tex_build.py` - the four
  write-side subcommands (`patch`, `scan`, `accept`, `build`)
- `.claude/skills/latex-hygiene/scripts/Test/test_tex_check.py` - offline synthetic-string tests
- `.claude/skills/latex-hygiene/scripts/Test/test_tex_patch.py`, `test_tex_build.py` - offline
  tests for the write side (10 + 7 tests); `test_tex_build.py` patches `subprocess` and
  `shutil.which`, no LaTeX installation needed

### `opt-local-vram-llm` - measured VRAM tuning for the local agents

Replaces six manual steps with one command when a newer model arrives for `local-writer` or
`local-coder`: read the manifest, write a Modelfile, create the tag, sweep, declare the
candidate, qualify. Every number it writes is measured on this card, none copied from a model
card or inferred from a parameter count. The objective, in order: admissible (`size_vram / size
>= 0.999` from `/api/ps`, 300 MiB free, the rung not clamped by the model's own context
maximum), fast enough (decode throughput at or above `--throughput-floor`, default 0.90, of the
best admissible throughput), then largest window wins, ties broken on throughput. `num_ctx`
climbs the existing ladder; `kv_cache_type` (`f16`, `q8_0`, `q4_0`) is a daemon-wide variable
read only at start, so each value costs a restart through `restart-ollama.ps1`, verified against
`server.log` before anything is measured. `num_gpu` is pinned at 99, not swept. The rung
measurement itself is `optimize_ollama.evaluate_rung`, imported from `loop-engineer` rather than
duplicated. It stops at declaration: it writes `local-model-config.json`, declares the tag as a
role candidate in `local-models.json`, and prints the `model_resolver.py --qualify` command
without running it.

**Files:**
- `.claude/skills/opt-local-vram-llm/SKILL.md`
- `.claude/skills/opt-local-vram-llm/scripts/vram_probe.py` - read-only manifest and daemon facts
- `.claude/skills/opt-local-vram-llm/scripts/vram_modelfile.py` - pure Modelfile render
- `.claude/skills/opt-local-vram-llm/scripts/vram_daemon.py` - KV cache axis: write, restart,
  verify, restore
- `.claude/skills/opt-local-vram-llm/scripts/vram_optimizer.py` - the driver: search, objective
  function, report, declaration
- `.claude/skills/opt-local-vram-llm/scripts/Test/test_vram_probe.py`,
  `test_vram_modelfile.py`, `test_vram_daemon.py`, `test_vram_optimizer.py` - four offline
  suites (11 + 9 + 5 + 13 tests), no network, no GPU, no Ollama daemon

`aider-setup` and `rt-observe` are big enough to get their own chapters rather than a
subsection here: [06-aider-pipeline.md](06-aider-pipeline.md) and
[07-rt-observe-dashboard.md](07-rt-observe-dashboard.md).
