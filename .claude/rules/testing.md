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
- Every suite asserts at least one failure path, not only the happy path (`R20`). The defects
  that mattered here were all caught by a negative case: a swept rung clamped above the native
  window, a tag that spills out of VRAM, a truncated JSON header, a `create` on an existing
  file writing a numbered duplicate.
- No test reads machine-local measured configuration (`R21`).
  `.claude/local-model-config.json` is gitignored and describes one GPU, so a test that reads
  it passes only on this machine. Inject the number the test needs as a fixture.

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
- `latex-hygiene` skill: `tex_check.py` (thin CLI dispatching to sibling modules `tex_common.py`,
  `tex_chars.py`, `tex_braces.py`, `tex_par.py`, `tex_citecov.py`, `tex_abstract.py`, `tex_wc.py`,
  `tex_aiscan.py`, `tex_aiscan_text.py`; `chars` answers which forbidden characters and where,
  `aiscan` answers the AI-usage risk score reproducing `paper-auditor.md` Step 7.5's signal
  weights and formula, `wc`/`wc --accepted` answer prose and accepted-text word counts with an
  optional before/after table, `abstract` answers abstract word and keyword counts, `braces`
  answers brace depth and `\begin`/`\end` balance, `par` answers whether a `changes` macro
  argument crosses a blank line, `citecov` answers cite-key coverage against a `.bib`, `refcov`
  answers uncited labels, dangling refs, and duplicate labels, and `all` aggregates every
  subcommand). Pure Python standard library, so it adds no `requirements.txt` and no
  `pip-audit` surface. The write side adds `tex_patch.py` (applies an audit plan's
  `\added`/`\deleted`/`\replaced` edits by exact-match substitution, one occurrence required, a
  `FAILS:` list on any 0- or 2+-match), `tex_scan.py` (post-write guard: control characters,
  damaged control-sequence residue, a `changes` macro crossing a table or float boundary, a `%`
  comment that swallowed a row-terminating `\\`, a retracted `\cite` still resolved inside a
  deleted span, and live `\hl{}`/`\todo{}` markers), and `tex_build.py` (`accept` resolves
  `changes` markup to `[final]{changes}`/`[disable]{todonotes}`; `build` runs
  pdflatex/bibtex/pdflatex/pdflatex with mandatory `BIBINPUTS=".."`, refusing a `.bib` inside the
  output directory).
- **Self-improvement loop** (repo-wide, owned by no single skill): `scripts/test/run-offline-tests.ps1`
  is the single runner behind "every previous test still passes". It DISCOVERS every
  `.claude/**/Test/test_*.py` rather than reading a list, so a suite added later is picked up with
  nothing to update; it resolves and reports one interpreter (`.venv-skills` first), because a suite
  silently run under the wrong Python is worse than one not run at all; and it grades each suite into
  THREE outcomes, not two - PASSED, FAILED, and NOT RUN. NOT RUN covers a suite that cannot import a
  third-party package, decided by looking for the missing module INSIDE the repository rather than
  against a hardcoded package list that would rot; a missing module that does resolve in-repo is
  first-party, so it is a real defect and counts as FAILED. Without that third outcome one uninstalled
  package (`pypdf`, today) would block every future self-improvement permanently. Green means every
  suite that COULD run passed, and writes `.rt-green.json` carrying a hash PER CODE FILE; any FAILED
  deletes it. `install-junctions.ps1 -Sync` reads those per-file hashes to decide, file by file,
  whether what is on disk is what the suite actually passed - per file rather than one repo-wide hash,
  which would freeze all propagation whenever any edit was in progress. `scripts/lib/rt-sync.ps1`
  holds the -Sync engine in its own file for one reason: `scripts/test/verify-sync-writes.ps1` must be
  able to load it WITHOUT executing the installer's legacy junction flow, which would write to the
  real `~/.claude` just by being tested.
- `opt-local-vram-llm` skill: `vram_probe.py` (read-only manifest and daemon facts: projector
  layer present or baked in, native context maximum from `ollama show`, current KV cache type
  and other settings from the last `server config` line of `server.log`), `vram_modelfile.py`
  (pure render of the tuned Modelfile: `num_gpu` pinned at 99, `num_ctx` from the swept rung, no
  repetition penalty, TEMPLATE and per-role SYSTEM carried through, measurement provenance in
  comments), `vram_daemon.py` (the KV cache axis: writes `OLLAMA_KV_CACHE_TYPE`, restarts through
  `restart-ollama.ps1` (beside it in the same skill), verifies the value took effect in
`server.log`, restores the
  original value on failure), and `vram_optimizer.py` (the driver: sweeps `num_ctx` against the
  KV cache axis, applies the admissible/fast-enough/largest-window objective by calling
  `optimize_ollama.evaluate_rung` from `loop-engineer` rather than re-measuring a rung itself,
  writes the report, and declares the tuned tag as a role candidate in `local-models.json`
  without qualifying it).

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
python .claude/skills/latex-hygiene/scripts/Test/test_tex_check.py        # chars/aiscan/wc/abstract/braces/par/citecov/refcov: forbidden chars, AI-usage score, accepted-text word count, brace/begin-end balance, changes-macro corruption, cite<->bib and label<->ref coverage
python .claude/skills/latex-hygiene/scripts/Test/test_tex_patch.py        # 10 tests: exact-match plan application, occurrence-count gate, FAILS: list, --author override, --init preamble emission, colour-only deleted markup
python .claude/skills/latex-hygiene/scripts/Test/test_tex_build.py        # 7 tests: accept resolution, pdflatex/bibtex/pdflatex/pdflatex sequence, BIBINPUTS, output-dir .bib refusal

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
heavy Docling/MarkItDown imports never load. `test_tex_build.py` patches `subprocess` and
`shutil.which`, so no LaTeX installation is needed.

```powershell
python .claude/hooks/Test/test_vault_access_guard.py      # 15 tests: every path form of the vault refused (Windows, drive-relative, Git Bash, the $OBSIDIAN_VAULT token), local-writer exempt and every other agent not, the PowerShell tool guarded as its own tool name, file CONTENT carrying the vault path NOT treated as an access, malformed payload never blocking
python .claude/hooks/Test/test_obsidian_outbox_flush.py   # 8 tests: vault write path (threshold, replay, escape, missing vault), the setUp precondition that PROVES the vault redirection took effect before a byte is written, and the unresolved-link warning
python .claude/skills/obsidian-cli/scripts/Test/test_vault_consolidate.py   # 35 tests: phantom detection, alias, fence, archives, why labels, dry-run, junction escape, LF endings, non-regression, map-entry validation, no-cascade, code-span/archive exclusion, cross-drive refusal, CLI dry-run gate, path-suffix resolution, aliased/heading link repair, phantom provenance
.\scripts\audit\check-claude-template.ps1                 # template vs live global, plus the write-path invariants
.\scripts\test\run-offline-tests.ps1                       # runs EVERY Python suite above; writes .rt-green.json on a full pass, deletes it on any failure
.\scripts\test\verify-sync-writes.ps1                      # 13 checks on the two irreversible -Sync writes, driven against temp copies, proving the live ~/.claude is never opened for writing
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
python .claude/skills/loop-engineer/scripts/Test/test_ollama_bridge.py    # 31 tests: transport, budget probe, truncation signature, reasoning stripper, hygiene, seed, no fallback, empty body, mandatory vault consultation, --role forwarded to the resolver, think=false so a reasoning model does not eat the reply reserve, and a response that IS one fenced code block unwrapped so a model presenting its module for display is not failed on punctuation (measured 2026-08-28: a candidate scored 0/3 because every attempt was written verbatim to a .py and died with SyntaxError on line 1 before a single case ran, while prose around a fence, two blocks, and an unterminated fence are all left alone), the context window read PER RESOLVED TAG rather than from an import-time constant (a tag with no swept measurement fails the run and names itself instead of borrowing another model's window)
python .claude/skills/loop-engineer/scripts/Test/test_model_resolver.py   # 39 tests: eligibility, per-role win rule, qualification, LARI_LOCAL_MODEL override, no-fallback states, per-role current tag (resolve/qualify/adopt/refuse-to-seed), language-gate thresholds injected from one constant, coder target named .py so importlib can load it, plus the seven measured-budget tie-break cases: an exact tie in every role now goes to local-model-config.json, where the challenger wins if the incumbent has NO admissible measured configuration on this card or if the challenger retains a strictly larger window without losing decode throughput, while a regression is never rescued and a strict gain never reaches the tie-break; the per-role adoption path honours policy.win_rule, which it silently ignored before 2026-08-28
python .claude/skills/loop-engineer/scripts/Test/test_qualification_tasks.py  # 9 tests: grades the GRADER - a reference implementation of every coder contract, written from the task's own prompt rather than copied from the function it mirrors, must pass every case through the REAL oracle, so a wrong expected value fails here instead of silently mis-scoring every candidate forever; plus a negative control proving the check can fail, the ten-per-role floor, unique ids, and writer-side consistency (every required heading and frontmatter key actually named in its prompt, length window able to hold the sections)
python .claude/skills/loop-engineer/scripts/Test/test_matrix_command.py       # 8 tests: --matrix scores EVERY declared and installed candidate on EVERY task, including roles it is not declared for (a candidate graded only on its own role is not comparable - an 18/20 tag held the coder role while a 20/20 tag sat unscored on coder tasks), a tag with no measured context window is reported NOT RUNNABLE and is never even asked to run a task rather than printing 0/20, the summary ranks by total and carries num_ctx and decode rate, --json emits the whole structure, and no installed candidate is an explicit refusal
python .claude/skills/loop-engineer/scripts/Test/test_score_command.py        # 6 tests: --score reports per task and leaves the state document byte-identical, a role naming no task is refused, and --record refreshes ONLY an incumbent's stale number - a tag that is not current for that role is refused and nothing is written, so --record can never be a back door to adoption
python .claude/skills/loop-engineer/scripts/Test/test_context_budget.py   # 13 tests: task gate, descending scan, missing config is an explicit error
python .claude/skills/loop-engineer/scripts/Test/test_optimize_ollama.py  # 8 tests: a sweep rung ABOVE the model's own native context maximum is rejected instead of retained - Ollama clamps options.num_ctx silently rather than erroring, so the rung costs the memory of the smaller window and passes every threshold on numbers describing a window the daemon never granted; the honest rung still passes, one deviating run out of three is enough to reject, and the 300 MiB free-VRAM floor still rejects on its own; plus api_ps_row's residency_ratio from /api/ps size/size_vram (full, partial-offload, absent-tag), and the rung record carrying residency_ratio (worst run) and decode_tps (median run) alongside the existing acceptance predicate
python .claude/skills/opt-local-vram-llm/scripts/Test/test_vram_probe.py      # 11 tests: projector present vs baked into a single layer, registry-nested and locally-created manifest layouts, bare name resolves to :latest, unknown tag raises rather than returning empty, native context maximum from `ollama show`, LAST 'server config' line wins so a restart is not read as stale
python .claude/skills/opt-local-vram-llm/scripts/Test/test_vram_modelfile.py  # 9 tests: num_gpu/num_ctx always emitted, no repetition penalty ever emitted or copied, TEMPLATE inherited from a tag FROM but restated from a blob FROM, a multi-line template triple-quoted rather than flattened, triple-quoted directive parsed whole, per-role SYSTEM, measurement provenance in the comments
python .claude/skills/opt-local-vram-llm/scripts/Test/test_vram_daemon.py     # 5 tests: the variable written BEFORE the restart (after is a no-op the daemon never reads), a daemon that came back on another value stops the run, missing restart script named, the axis restored when the search aborts, no redundant restart when the search ends on the original value
python .claude/skills/opt-local-vram-llm/scripts/Test/test_vram_optimizer.py  # 24 tests: objective function (context wins when throughput is flat, floor rejects a slow large window, residency outranks speed, the floor references the best ADMISSIBLE throughput so a spilled rung cannot veto a usable one, free-VRAM floor, clamped rung, nothing admissible, tie-break, empty input raises), dry run touches nothing, unknown KV type refused, role required, plus the four cases where a tag whose MANIFEST layer exceeds the card is decided by loading it at a 512-token window instead of by the file size - the disk figure and the resident figure disagreed by 6106 MiB on one tag and 1041 MiB on another, so refusing on disk size turned away models that fit; a tag that spills at that window, one fully resident but under the free-VRAM floor, and one the daemon never reports resident are all still refused
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
