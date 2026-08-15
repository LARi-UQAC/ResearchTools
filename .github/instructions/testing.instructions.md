---
applyTo: "**"
---

# Testing

General testing guidance for any project in this workspace. When a project ships its own
test suite, run it from the correct environment before pushing; there is no CI/CD pipeline,
so tests are run manually.

## Principle

- Test the behavior that matters: a script's contract (inputs, outputs, error paths), not
  its internals.
- Prefer fast, deterministic tests. Patch slow or network-bound dependencies (model loads,
  remote APIs) with fixtures so the suite runs offline where possible.
- Use tolerance-based comparison for floats (e.g. `assertAlmostEqual`, `places=2`).
- Document an expected timeout in a comment for any long-running test.

## Environments

- Use the project's own virtual environment for the layer you are working in (a repo may
  have more than one `.venv`). Activate it before running scripts or tests.
- Never mix dependencies across environments.

## ResearchTools script surface

The runnable code in this repo is the skill scripts under `.claude/skills/*/scripts/`. To
exercise them, set the required environment variables, then dry-run the entry points:

- `scopus` skill: `scopus_api.py` (Scopus REST client; `search` orders by `-citedby-count` by
  default and wraps bare keywords in `TITLE-ABS-KEY()` — the Scopus default is descending date,
  which never surfaces a founding work, and an unqualified query under citation ordering answers
  the most-cited papers of all science; pass `--sort recent` for a delta or a "most recent
  publications" list, using the dash-free alias because argparse refuses `--sort -coverDate`;
  `validate` queries the title as a quoted phrase, publishes `title_similarity`, and sets
  `ambiguous` when `total_found > 1` — its schema has NO `found` and NO `record` key;
  `search`/`validate`/`cite` all carry `doi_prefix` and `publisher_by_prefix`, which decide the
  publisher where `prism:publisher` misleads; `author` mode accepts BOTH
  "Lastname, Firstname" and "Firstname Lastname" and echoes the resolved `scopus_query` — for a
  publication list always resolve the AU-ID first, then query `AU-ID(...)`, never the bare name and
  never ORCID, which returns only the author-claimed subset; `journal --issn` is the reliable
  venue lookup and returns the CiteScore percentile plus its quartile — a lookup by title, or
  an ISSN lookup combined with `field=`, answers a stub), `doi_publisher.py` (the DOI-prefix to
  publisher table; `10.1186` BioMed Central diverges from the book repo's copy on purpose),
  `bib_batch.py` (batch
  title-to-DOI resolution, enrichment, grading, BibTeX generation), `bib_audit.py` (the
  opposite direction: audit an EXISTING `.bib` — required fields, duplicates, DOI validation,
  venue metrics by ISSN, publisher approval, annotated pass-through copy plus report;
  `--no-network` replays from its cache), `litreview_update.py`
  (incremental `/litupdate` bookkeeping: baseline fingerprint, delta dedup, dated paths,
  CHANGELOG scaffold; offline), `semantic_scholar_api.py`
  (fallback + `external_ids_for_doi`), `download_pdf.py` (any-format full-text retrieval:
  Elsevier/S2 PDF, then Unpaywall/arXiv/PMC/landing HTML, then an opt-in browser tier),
  `browser_fetch.py` (tier 8: a real Playwright Chromium for challenge-gated publishers,
  with a per-paper `refs/_sources.json` override URL), and the cross-review cores
  (`gemini_reviewer.py`, `github_reviewer.py`, `gemini_table.py`).
- `paper2talk` skill: `talk_rules.py` (import-only: audience profiles, three-tier cadence, the
  130 wpm budget), `talk_model.py` (deck-as-data validation, budget aggregation, Jinja render
  of the Beamer and web targets), `talk_pptx.py` (PowerPoint renderer built ON the lab gabarit
  via python-pptx: drops its sample slides, adds each slide on one of its own layouts),
  `talk_template.py` (brand contract out of any `.pptx`; detects a legacy `.ppt` and converts
  it with `--convert`), `paper_extract.py` (LaTeX `\input` flattening, sections, floats,
  equations, citations, number inventory; refuses an encrypted or scanned PDF),
  `talk_doctor.py` (preflight: buildable targets and per-tool degradation),
  `fig_export.py` (draw.io re-export at scale 3), `talk_render.py` (PDF via `soffice` else
  PowerPoint COM, then `pdftoppm`; `--paper` reflow), `talk_notes.py` (spoken budget, cadence,
  exhibit coverage), `to_a4.py` (A4/Letter reflow, `--handout`), `talk_validate.py` (package
  checks, legibility gate, text-only-slide check, web self-containment).
- `extract-statistic` skill: `extract_text.py` (`--stats-scan` and `--section-scan`; pluggable
  Markdown backend Docling -> pymupdf4llm/MarkItDown -> tag-strip). The `extract-futureworks`
  skill ships no script of its own and reuses `extract_text.py --section-scan`.
- `deliberation` skill: `deliberate.py` (two-round Gemini/Copilot debate). Neither leg names a
  model: `--gemini-model auto` and `--copilot-model auto` (both default) resolve the newest
  entry of the provider's live catalog, ranked generation-first then release date then stable
  over preview, and the envelope records the concrete ids under `models`. The GitHub leg walks
  the provider chain in `../scopus/scripts/copilot_providers.py` (Copilot on `COPILOT_TOKEN` or
  a token minted from `GH_OAUTH_TOKEN`, then the two legacy GitHub Models hosts on
  `GITHUB_TOKEN`), failing over on an HTTP status as well as a network error. GitHub Models was
  retired 2026-07-30 and answers 410, so with only `GITHUB_TOKEN` that leg is correctly
  unavailable; Copilot refuses a PAT by design. A response that cannot be parsed is logged with
  `_error` and truncated `_raw` rather than dropped, since a silently missing critique reads as
  agreement in the merge.
- `word2latex` skill: `docx_inspect.py`, `manuscript_bib.py`.

Offline unit tests (no network, no API key, no model load; run with the project Python):

```powershell
python .claude/skills/scopus/scripts/Test/test_download_pdf.py            # any-format tiers (incl. publisher/curl), tier-8 wiring, _sources.json, HTML validation
python .claude/skills/scopus/scripts/Test/test_browser_fetch.py           # tier 8: real-PDF capture / no-print / paywall / override with Playwright mocked
python .claude/skills/scopus/scripts/Test/test_bib_batch.py               # title match, venue grading, BibTeX invariants
python .claude/skills/scopus/scripts/Test/test_bib_audit.py               # parse, duplicates, dataset DOI vs invalid DOI, quartile boundaries, no '@' injected, idempotence
python .claude/skills/deliberation/Test/test_deliberate.py                # 31 tests: merge/ranking/degradation/CLI, plus strict-JSON and coded-key tolerance, the unparsable response kept as _raw while the other leg continues, expansion opt-out so gemini_table's free-key cells are not renamed, endpoint failover (first host 404 -> second, identical result; every host failing -> empty critique + _error, never an exception), and latest-model resolution (generation beats a fresher date on an older family, stable only breaks a tie at equal version, tokenless provider skipped, fallback flagged by an empty provider)
python .claude/skills/scopus/scripts/Test/test_litreview_update.py        # baseline parse, delta dedup (DOI + title Jaccard), changelog scaffold
python .claude/skills/scopus/scripts/Test/test_author_name_split.py       # author-name parsing: "Lastname, Firstname" and "Firstname Lastname" must resolve to the same query
python .claude/skills/scopus/scripts/Test/test_search_sort_and_publisher.py  # search sort default + aliases, TITLE-ABS-KEY scoping vs field pass-through, DOI-prefix publisher, validate ambiguity guard
python .claude/skills/extract-statistic/scripts/Test/test_section_scan.py # scan_sections / section-scan

python .claude/skills/paper2talk/scripts/Test/test_talk_template.py      # EMU->inch, srcRect keep-fraction, object extraction
python .claude/skills/paper2talk/scripts/Test/test_talk_notes.py         # slide-number strip, rels-based notes mapping, tolerance exit
python .claude/skills/paper2talk/scripts/Test/test_fig_export.py         # --fix-text into a copy, CLI discovery, raster refused
python .claude/skills/paper2talk/scripts/Test/test_talk_render.py        # backend order, page-count gate, --paper delegation
python .claude/skills/paper2talk/scripts/Test/test_to_a4.py              # A4/Letter maths, mediabox, margin guard, handout grid
python .claude/skills/paper2talk/scripts/Test/test_talk_validate.py      # plugin locator, dangling r:embed, chart axes, web URLs
python .claude/skills/paper2talk/scripts/Test/test_talk_model.py         # block kinds, renderer gap raises, budget agreement
python .claude/skills/paper2talk/scripts/Test/test_audience_rules.py     # font floors, equation policy, legibility gate
python .claude/skills/paper2talk/scripts/Test/test_cadence.py            # three-tier formula, 130 wpm, backup outside the slot
python .claude/skills/paper2talk/scripts/Test/test_content_hierarchy.py  # text-only slides, exhibit coverage by keyword
python .claude/skills/paper2talk/scripts/Test/test_talk_pptx.py          # gabarit layout choice, sample slides dropped, all block kinds, notes pane
python .claude/skills/paper2talk/scripts/Test/test_paper_extract.py      # include flattening, missing/circular include, number normalisation, PDF guards
python .claude/skills/paper2talk/scripts/Test/test_talk_doctor.py        # per-target buildability, absent vs not-probed, degradation text
```

The thirteen `paper2talk` suites build their `.pptx` fixtures in the test (`Test/_fixtures.py`,
and python-pptx's packaged default template standing in for the lab gabarit), so
no PowerPoint, LibreOffice, draw.io, Poppler or LaTeX is needed; `shutil.which`,
`platform.system` and `subprocess` are patched for the render and figure tiers. `test_to_a4.py`
needs `pypdf` (6.15.0, no known CVE per `pip-audit`) and the Jinja render path needs `jinja2`;
both are pinned in `.claude/skills/paper2talk/scripts/requirements.txt` with `python-pptx` and
`defusedxml`.
Rendering a real deck (PowerPoint COM or `soffice`, `pdftoppm`, `pptxgenjs` over `NODE_PATH`,
`pdflatex`) is exercised manually, not by this block.

The `test_download_pdf.py` suite patches `requests.get`, so the Unpaywall/arXiv/PMC tiers and the
HTML fetch are exercised with no network. `test_browser_fetch.py` replaces the Playwright sync API
with fakes and forces `_PW_OK`, so the browser tier's four branches run without installing Chromium.
The section-scan suite works on plain strings, so the
heavy Docling/MarkItDown imports never load.

```powershell
python .claude/hooks/Test/test_obsidian_outbox_flush.py   # 8 tests: vault write path (threshold, replay, escape, missing vault), the setUp precondition that PROVES the vault redirection took effect before a byte is written, and the unresolved-link warning
python .claude/skills/obsidian-cli/scripts/Test/test_vault_consolidate.py   # 35 tests: phantom detection, alias, fence, archives, why labels, dry-run, junction escape, LF endings, non-regression, map-entry validation, no-cascade, code-span/archive exclusion, cross-drive refusal, CLI dry-run gate, path-suffix resolution, aliased/heading link repair, phantom provenance
.\scripts\audit\check-claude-template.ps1                 # template vs live global, plus the write-path invariants
```

The first offline-tests the `obsidian-outbox-flush.py` hook itself (no Obsidian process, no
network): the byte-size verification the hook substitutes for the CLI's unreliable return
code, replay idempotence, the outside-vault path refusal, and the no-vault no-op.
`check-claude-template.ps1` is not a unit test but a drift check: it regenerates
`CLAUDE.template.md` with today's substitutions into a file under `$env:TEMP`, diffs it
against this machine's own
`~/.claude/CLAUDE.md`, and asserts four invariants (no `daily:append` in the template, no
removed `30_Ressources` folder used as a live location in a definition file, the shipped hook
verifies writes through `st_size`, the shipped hook never calls the Obsidian CLI). It never
runs `setup.ps1` and never writes to the live global file; see the script's own header for
what it does not cover (one machine's global file, not every contributor's).

### Required / optional environment variables

| Variable | Status | Used for |
|---|---|---|
| `SCOPUS_API_KEY` (or `.claude/skills/scopus/.scopus_key`) | Required | All Scopus search, validation, and PDF retrieval |
| `UNPAYWALL_EMAIL` (or `--email`) | Optional | Unpaywall open-access tier in `download_pdf.py` (HTML/PDF fallback) |
| `GEMINI_API_KEY` | Optional | Gemini cross-review and table enrichment |
| `GITHUB_TOKEN` | Optional | GPT cross-review via GitHub Models |
| `S2_API_KEY` (or `SEMANTIC_SCHOLAR_API_KEY`) | Optional | Semantic Scholar backfill (else throttled public pool) |

Scopus access needs a campus network or active VPN unless an `--insttoken` is supplied.

```powershell
python .claude/skills/loop-engineer/scripts/Test/test_ollama_bridge.py    # 22 tests: transport, budget probe, truncation signature, reasoning stripper, hygiene, seed, no fallback, empty body, mandatory vault consultation, --role forwarded to the resolver, think=false so a reasoning model does not eat the reply reserve
python .claude/skills/loop-engineer/scripts/Test/test_model_resolver.py   # 32 tests: eligibility, per-role win rule, qualification, LARI_LOCAL_MODEL override, no-fallback states, per-role current tag (resolve/qualify/adopt/refuse-to-seed), language-gate thresholds injected from one constant, coder target named .py so importlib can load it
python .claude/skills/loop-engineer/scripts/Test/test_context_budget.py   # 13 tests: task gate, descending scan, missing config is an explicit error
```

The bridge suite's mandatory-vault cases are the ones to keep an eye on: the bridge REFUSES
to call the local model unless the caller passes `--vault-context <terms>` or says
`--no-vault-context` out loud. Omitting both is exit 2. That guard exists because the rule
lived only in an agent definition and was skipped by the first caller in a hurry, on
2026-08-14, and the model answered a documented LaTeX question with a command that does not
exist. Structural gates do not catch an untrue answer; the vault does.

## Documentation of test results

When adding or modifying tests:
1. Update docstrings to reference any related documentation (formulas, validation rules).
2. If a test validates a published equation, link to its canonical reference in a comment.
3. State the expected timeout for long-running tests in a comment.

## No CI/CD

There is no automated pipeline. Run the relevant tests manually before pushing.
