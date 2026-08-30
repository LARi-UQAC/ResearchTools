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
- `obsidian-cli` skill: `vault_consolidate.py` (the deterministic half of consolidation: `--mode candidates` finds missing edges, `--mode links` finds phantom ones, `--apply <map>` rewrites link text and is dry-run until `--yes`). Since 2026-08-28 that name is the CLI and the re-export surface only, the module having reached 8768 tokens, more than twice the source ceiling; it was split along the seam it already had, into `vault_corpus.py` (read the vault and measure it - corpus loader, name and alias index, edge graph, term extraction, scored suggestions, the phantom report; read-only, so nothing here can damage a note), `vault_links.py` (the string surgery on ONE note: bare, aliased and heading link forms, and the code-region walk that leaves an example link inside backticks or a fence byte-identical), and `vault_apply.py` (the only module that writes to a note - `apply_map` and its refusals: a replacement that is not a bracketed wiki-link, a path leaving the vault, a junction escape, a cross-drive target, and dry-run until `--yes`; a reviewer looking for this skill's blast radius reads that one file). Every name the three export is re-exported by `vault_consolidate`, so the 35-test suite and `daemon_phantoms` are unaffected - the split is a size boundary, not a change of interface. Plus the vault write path shared by the flush hook and the vault event daemon - `outbox_io.py` (resolve the vault, parse the directive, refuse a path leaving the vault, write and VERIFY by `st_size`, `stage()` a note atomically through a `.tmp` and `os.replace`), `vault_lock.py` (the single-writer lock beside the outbox; the outbox is machine-global and a daemon is a separate OS process that `vault-access-guard.py` never sees, so this lock is the only mechanism spanning both, and `held_by_live_holder()` exposes the same reclamation rules read-only so a caller can ask whether a daemon still holds its singleton lock without reclaiming what it inspects), and `vault_journal.py` (append-only JSONL record of every vault write plus the `--undo` it enables, since the vault is not under version control; `--count` prints the undoable-record baseline a caller takes BEFORE a run, and `--undo-since <index>` is the teardown that walks back to it NEWEST FIRST - an append is undone by truncating to a journalled size, so undoing an older record before a newer one leaves the file shorter than the newer record's baseline and that newer undo is then refused, which is why the order is the mechanism and not a preference). `run-drill.ps1` (with `run-drill.bat` beside it as the double-click entry) is the harness around the end-to-end drill: it refuses up front rather than half way (no vault configured, a vault that does not exist, a red offline suite, a daemon already holding the singleton lock), takes the journal baseline before the daemon can write anything, spawns the daemon in a second window and waits for it to TAKE ITS LOCK rather than sleeping a guessed interval, runs the drill in the first, and undoes everything filed after the baseline in a `finally` block so the teardown happens even when the drill fails - previewing first and prompting unless `-Yes` (R16). The teardown logic itself deliberately lives in `vault_journal.py` where the offline suite can reach it, since a walk backwards through the journal is the one step here that can damage the vault and PowerShell that spawns processes cannot be tested offline. `vault-daemon-autostart.ps1` (with `vault-daemon-autostart.bat` as the Startup-folder target) answers the other half of the raw-drop gap - the flush hook reports drops waiting with no daemon, and this is what makes one already be running: `-Install` and `-Uninstall` manage a single shortcut in the current user's Startup folder and touch nothing else, `-Status` is read-only and prints whether the lock is held, the log's tail and whether the shortcut exists, and a plain run starts the daemon hidden with its output appended to `~/.claude/vault-daemon.log`, rotated once at `daemon.log_max_bytes` because a hidden daemon whose death nobody notices is worse than one not running. It refuses rather than guessing on an unset `OBSIDIAN_VAULT` (R1) and is a no-op when a live daemon already holds the singleton, asked of `vault_lock` rather than inferred from the lock file existing. Its one caller is `setup.ps1 -InstallDaemon` (also run by `-All`, but only when a vault is configured), whose decision and delegation live in `scripts/lib/rt-daemon-install.ps1` for the same reason `rt-sync.ps1` exists - dot-sourcing `setup.ps1` to test it would run its whole interactive flow. `setup.ps1` is the home rather than `install.ps1`, which regenerates mirrors many times a day and runs at every SessionStart through `-Sync`: a Startup-folder write there would be re-created after the user deliberately removed it. Expect bridge errors in the log's first lines after a login: Ollama is usually not up yet, the poll loop says so and keeps watching, and the first drop after it comes up is filed normally. Timeouts and the staleness ceiling live in `daemon-config.json`, never in the code (R0). `local_capability_probe.py` is the Stage 1 gate: it measures on the installed daemon whether structured output is honoured and whether a fixed prompt prefix is re-used, resolving the tag through the resolver and writing its verdicts to the gitignored `.claude/local-capability-probe.json`, kept apart from `local-model-config.json` because `optimize_ollama.py --sweep` rewrites that file whole. The daemon itself is five modules: `vault_daemon.py` (the poll loop, one event's traversal, `--once` / `--drain` / `--dry-run`), `daemon_outbox.py` (the outbox layout that IS the queue - raw, working, sent, needs-review, state, queue - plus the write lock, the one-daemon-per-machine singleton lock, the claim by rename and the crash-recovery sweep), `daemon_states.py` (READ, CLASSIFY, ROUTE, DRAFT: the two model calls are schema-constrained and every refusal parks the event with a stated reason), `daemon_taxonomy.py` (where a note may GO: the folder enum built from the vault at run time, plus the one-line description of each folder read from `technology-folders.json` beside `daemon-config.json` - data, not code (R6), because shown bare folder NAMES the model matched on surface association and filed an outbox-lock note under `Docker`; an unglossed folder is still offered by name, so the file's absence degrades a hint and never the enum), and `daemon_drains.py` (the deferred half: candidate pairs from `vault_consolidate.py` judged one per call on the strict mechanism test, accepted edges appended reciprocally with their sentence and journalled), and `daemon_phantoms.py` (the dead-link drain: the local model answers REPOINT, DROP or LEAVE per phantom, constrained to the deterministic report's OWN suggestions so it cannot name a note nobody proposed; a repoint goes through `apply_map`'s tested guardrails, a drop backticks the link so the words stay and the link dies, and NOTHING is written without a `vault_journal.snapshot` of the note's previous text first - a mid-file substitution cannot be undone from a size the way an append can, which is exactly why this drain was once ruled out and what makes it admissible now). `vault_daemon_e2e.py` is the end-to-end drill, the one script here a session must NOT run: it mutates the real vault against the real daemon and the real model, so it refuses without `--yes` and prints the steps it would run instead. Eight `--only` step names cover nine numbered checks - filing and its timing budget are one step, then an ambiguous drop parked, containment, a name collision, the deferred drain, the journal undo, lock contention, and GPU residency, the last opt-in with `--with-eviction` because it loads the coder-role model and leaves the card holding a different one than it found. Step 4 answers `pass: null` unless step 1 ran first, since a collision needs a note to collide with. It emits one JSON object per step on stderr and a JSON report on stdout whose `failed` count is the exit code, and it names no vault path and no model tag: the vault comes from `OBSIDIAN_VAULT` and the tag from the resolver.
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
  without qualifying it; since 2026-08-29 it also OWNS the tuned tag's name, `tuned_tag_for`,
  so the harness that scores what it built spells the suffix nowhere of its own (R2)),
  `tune_preflight.py` (the refusals and the comparison for the five-step runbook from a
  downloaded model to a served one - tune, score, compare, adopt, confirm: it answers whether
  a run may start at all (a tag that is not installed, a tag that is ALREADY tuned, an
  unreachable daemon, and between the sweep and the scoring, a tuned tag with no measured
  window, which is exactly the state the resolver reports as NOT RUNNABLE and would otherwise
  print as a row of zeros that read as the model's failure rather than the sweep's), ranks the
  `--matrix` rows by the role's own score before the overall one, and says where the candidate
  landed against the incumbent, or that no tag is adopted for that role rather than inventing
  one; exit 2 is a refusal by design and 1 a failure (R12)), and `tune-new-model.ps1` (the
  runbook harness: steps 1 to 3 plus the comparison, STOPPING before adoption, because
  `--qualify` changes which model every local agent executes and a harness that adopted on its
  own would make measuring and taking effect the same event. It dry-runs before it acts,
  confirms before a sweep that restarts the daemon, writes `score.json` and `matrix.json` for
  the record (R17), creates that directory only after the preflight passes so a refusal leaves
  nothing behind, and treats an unadopted role as the ordinary state of a fresh machine rather
  than an error. Its own logic is in `tune_preflight.py` for the same reason `run-drill.ps1`
  keeps its teardown in `vault_journal.py`: PowerShell that spawns processes cannot be tested
  offline).

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
python .claude/hooks/Test/test_session_hooks_inventory.py # 26 tests: the SessionStart inventory carrying a PER-HOOK status (ok / MISSING / inline / template, with the matcher for a tool-gated event) and a [HOOKS DISPLAY] directive asking for the block to be relayed to the user - without it the inventory reaches the model's context and never the person's pane, which is why the Session: status line has its own hook; the inventory printed on STDOUT (stderr never reaches the session context, so a hook that writes there is invisible, not broken), and a declared hook whose script is absent NAMED in a [HOOKS ALERT] line - the 2026-08-27 vault-access-guard failure that refused nine tools for four turns with nothing said at startup; plus the three ways a hook is labelled (script basename, printed bracket tag, statusMessage), canonical event order rather than declaration order, an unknown future event reported not dropped, and the negative cases the fixtures alone missed until the hook was run against the real settings.json: prose AFTER a statement break naming Decisions.md and model_resolver.py must not become the label nor a false missing-file alert, a quoted ';' sitting after the .ps1 must still yield the script, a bare relative name is inline because its existence is unknowable, an unsubstituted {{USERPROFILE}} placeholder is never reported missing, and a missing or unparsable settings.json is silent with exit 0 (R11)
python .claude/hooks/Test/test_agent_mirror_ceiling.py    # 4 tests: no agent silently loses its GitHub Copilot mirror. Above `$CopilotStubThreshold` install.ps1 replaces an agent's mirror with a ~1700-char pointer stub, prints the word `stub` and exits 0, so nothing fails - measured 2026-08-28, local-writer.md crossed at 28822 body chars and mirrored as a stub for three regenerations. The threshold is PARSED from install.ps1 so the test cannot keep passing after someone changes it, seven long-form agents are a known-stub baseline (both directions asserted: a new name means a mirror was just lost, a missing name means an agent was trimmed and the list must be pruned), and the installer's own 30000-char hard limit on the GENERATED file is checked separately since the body threshold is only a proxy for it. This is also what holds Task A's rule in place: `local-writer.md` sits at 27544 body chars of 28000 since the verify-before-reporting rule landed on 2026-08-28, a margin of 456, so the next addition to it has to trim something first
python .claude/hooks/Test/test_codex_mirror.py            # 10 tests: no skill silently stops being reachable from Codex, the one harness with a NATIVE skill convention (it scans `.agents/skills` from the cwd up to the repo root and reads each SKILL.md, that exact casing, for name/description). Both Codex ceilings are PARSED from install.ps1 so the test cannot keep passing after someone changes them. The skill list is capped at 2% of the context window, or 8000 chars when unknown, after which Codex shortens descriptions itself and then omits skills with a warning - measured 2026-08-28, the untrimmed list for this repo is 9417 chars, already over, so install.ps1 trims to WHOLE sentences under a computed per-skill cap and the test proves the result fits, that the trim is a prefix of the original rather than a rewrite, and that the first sentence (which carries the trigger) always survives. Then the defect the suite was written for: the first generated set carried the source's own double quotes into the mirror and trimmed mid-scalar, shipping 11 of 15 mirrors whose frontmatter did not parse while the installer printed a green [OK] for every one, so the emitted description is now a single-quoted YAML scalar read back STRICTLY here (an unterminated quote raises rather than being tolerated) and compared against the trimmed canonical value; a folded description is joined rather than read as its first line, and a `>` block indicator is parsed as syntax rather than mirrored as the literal text it isn't. Plus the negative control (ten 4000-char descriptions must still exceed the budget after trimming, or the trim is silently rewriting) and the second ceiling, project_doc_max_bytes over the concatenated root + `.claude/skills/AGENTS.md` chain, where an overrun drops the DEEPEST file, the one closest to the work
python .claude/hooks/Test/test_vault_access_guard.py      # 15 tests: every path form of the vault refused (Windows, drive-relative, Git Bash, the $OBSIDIAN_VAULT token), local-writer exempt and every other agent not, the PowerShell tool guarded as its own tool name, file CONTENT carrying the vault path NOT treated as an access, malformed payload never blocking
python .claude/hooks/Test/test_obsidian_outbox_flush.py   # 20 tests: vault write path (threshold, replay, escape, missing vault), the setUp precondition that PROVES the vault redirection took effect before a byte is written, and the unresolved-link warning, plus the Stage 0 additions: a raw drop in outbox/raw/ left alone, staging atomic for a *.md glob, the PENDING/WRITE journal pair whose before size chains one write to the next, a held lock keeping the notes and still exiting 0, and a missing skill making the hook a SILENT no-op (R11); plus the raw-drop report, which says at SessionStart that drops are waiting in raw/ with no daemon to consume them - liveness asked of `vault_lock.held_by_live_holder` rather than of the lock file existing, since a daemon killed mid-run leaves its singleton lock behind and reading that as "running" reports exactly backwards, with the live-lock, dead-holder, empty-folder and unusable-config cases all asserted and the report proven never to reclaim the lock it inspects
python .claude/skills/obsidian-cli/scripts/Test/test_vault_consolidate.py   # 35 tests: phantom detection, alias, fence, archives, why labels, dry-run, junction escape, LF endings, non-regression, map-entry validation, no-cascade, code-span/archive exclusion, cross-drive refusal, CLI dry-run gate, path-suffix resolution, aliased/heading link repair, phantom provenance
python .claude/skills/obsidian-cli/scripts/Test/test_vault_lock.py         # 12 tests: the single-writer lock over the machine-global outbox - a LIVE holder on this host refuses rather than being taken over, a dead holder and an over-age lock are reclaimed with a reason, another host is judged by age only since a foreign pid means nothing here, a malformed lock file is reclaimed, release happens on an exception, and release never deletes a lock someone else now holds; plus the read-only `held_by_live_holder` the flush hook asks about the daemon's singleton lock - a running holder, no lock at all, and both reclamation rules in the negative, with the file proven untouched, since a reader that reclaimed what it inspects would evict the very daemon it found
python .claude/skills/obsidian-cli/scripts/Test/test_vault_journal.py      # 16 tests: the append-only write record and its undo - record shape, a PENDING record carrying a null after, a corrupt line not hiding the history, undo of an append restoring the byte size, undo of a create removing the file, and the three refusals (a path outside the vault, a file already smaller than the journalled size, the CLI dry-run gate); plus `--undo-since`, the teardown the e2e drill never had - only what came after the baseline is undone so a note that existed before is returned to its earlier size rather than deleted, the walk is asserted to go NEWEST FIRST by index because an older undo first would make every newer one refuse, a baseline at the end is a clean no-op so a drill that filed nothing tears nothing down, the preview writes nothing, and `--count` prints the bare baseline a shell captures before the run
python .claude/skills/obsidian-cli/scripts/Test/test_local_capability_probe.py  # 14 tests: the Stage 1 capability probe with the bridge's network boundary patched - a schema-constrained reply honoured, and the three ways it is not (prose, JSON that is not the requested object, a value outside the enum); the prefix-cache verdict taken on prefill DURATION against a CONTROL call on a prefix never seen, since Ollama 0.33.0 bills the full prompt_eval_count even on a hit, with the machine-got-faster case (control collapsed too) correctly NOT read as reuse; and the two stops that write nothing, a resolver naming no model and a missing measured window
python .claude/skills/obsidian-cli/scripts/Test/test_vault_daemon.py           # 14 tests: the WRITE path, everything after the decision - a reusable drop filed under its technology and a project drop appended to its decision log, a drop with no subject, a hygiene violation retried then parked rather than patched, a prompt over the window parked rather than truncated, a name collision producing a dated atomic note instead of appending into an unrelated one, a replay writing nothing twice, both deferred queues filled on the event path, the in-flight state file present during the write and gone after, a crash before the write leaving the drop for the next poll, and lock contention DEFERRING the drop - claimed first, the way `run_once` does, because passing the raw/ path straight to `handle()` is what hid the defect the live drill found on 2026-08-28: the deferred drop was left in `working/`, where only a daemon restart looks, and it sat there for over an hour while the daemon polled an empty `raw/` beside it
python .claude/skills/obsidian-cli/scripts/Test/test_daemon_classify.py        # 14 tests: what the daemon ASKS the model and what it refuses to do with the answer - confidence under the threshold parked, an off-enum technology refused although the schema already constrained it, the retired catch-all folder never offered, a classification that is not JSON, and the four cases the first live drill produced on 2026-08-28, where the confidence dial caught nothing because both wrong answers came back ABOVE it: the SOURCE's frontmatter alone decides which project a write lands in, so a declared project outranks a model answer that merged the project with the subject; a project scope on a drop declaring none is refused outright rather than left to a directory lookup to catch by luck; a drop that names its project and is filed as REUSABLE is legitimate - the documented raw drop does exactly that - so it files normally and the report carries `scope_divergence` instead, one greppable field rather than a silent misfiling; and the classify prompt states the project rule in BOTH directions, in its FIXED prefix so it stays inside the measured prefix cache, after a one-sided version filed a genuine project entry as a resource note. Plus the folder menu from `daemon_taxonomy`: a folder offered with what it HOLDS and not only its name, an unglossed folder still offered, a missing data file degrading to bare names, and the shipped file's own content checked. Both suites share `Test/_daemon_fixtures.py`, which is imported and never discovered as a suite
python .claude/skills/obsidian-cli/scripts/Test/test_daemon_queue.py           # 8 tests: the filesystem queue - a second daemon refused by the singleton lock, the claim moving a drop out of raw/ so the loser of a race gets nothing, the sweep recovering a drop stranded by a crash mid-event, and both deferred queues filled on the event path but drained only off it
python .claude/skills/obsidian-cli/scripts/Test/test_daemon_drains.py          # 13 tests: the consolidation drain - a shared mechanism linking both notes reciprocally with its sentence, a topic-only pair REJECTED with its reason, an acceptance carrying no sentence rejected, both edges journalled, a second drain not doubling an edge, an unparsable verdict logged as an error rather than read as agreement, the pair count bounded, and graphify skipped with a reason when there is no graph or nothing queued
python .claude/skills/obsidian-cli/scripts/Test/test_daemon_phantoms.py       # 17 tests: the dead-link drain - a repoint rewriting the link, a drop backticking it so the author's words survive, LEAVE touching nothing, every edit snapshotted BEFORE it happens and the snapshot undoing the rewrite exactly, no journal meaning no rewrite at all, the schema admitting only the report's own suggested targets and naming no target when there is no suggestion, a repoint with no target not applied, an unparsable verdict logged rather than acted on, the per-drain bound, and a failing link audit refused rather than guessed, and the four the first live drill forced on 2026-08-28: a DROP verdict must neutralise an ALIASED link and a link carrying a heading, because a phantom is named by its TARGET only and a literal replace of `[[target]]` never matches `[[target|label]]` - the link survived six consecutive drains fifteen minutes apart, each one paying a model call to reach the same verdict; neutralising twice changes nothing the second time, which is what makes the drain converge; and a drop that changed NO note is reported as an error (R9), since a report saying 'dropped' while the link is still live is exactly how that loop stayed invisible
python .claude/skills/obsidian-cli/scripts/Test/test_vault_daemon_e2e.py      # 9 tests: the end-to-end drill's own harness, which is all that CAN be tested offline since the steps themselves only run against the real vault, daemon and model - a run without `--yes` writes nothing and reports what it would do, no configured vault is a stop rather than a guess, an unknown step name is recorded without aborting the rest, a step that raises is recorded rather than crashing the drill, every drop it stages carries the identifying prefix so an interrupted run leaves something recognisable as the drill's rather than a real learning, `wait_for` gives up on its bound instead of hanging and returns the elapsed time on a hit, the collision step says so when there is nothing to collide with, and containment reports anything created beside the vault
.\scripts\audit\check-claude-template.ps1                 # template vs live global, plus the write-path invariants
.\scripts\test\run-offline-tests.ps1                       # runs EVERY Python suite above; writes .rt-green.json on a full pass, deletes it on any failure
.\scripts\test\verify-sync-writes.ps1                      # 13 checks on the two irreversible -Sync writes, driven against temp copies, proving the live ~/.claude is never opened for writing
.\scripts\test\verify-daemon-install.ps1                   # 22 checks on setup.ps1 -InstallDaemon: which vault a login-started daemon would actually see (user scope wins over the argument, since the Startup shortcut passes no -Vault and NOT_CONFIGURED is not a vault), the delegation reaching vault-daemon-autostart.ps1 -Install with that vault, a missing vault as a SKIP with exit 0 rather than a failure that would stop -All, -Preview invoking nothing (R16), a non-zero autostart code propagating instead of being swallowed, a missing autostart script named, the USER-scope warning when the vault exists only as an argument, the four setup.ps1 wiring points checked statically, and the professor's real Startup folder listed before and after to prove no shortcut was created by the test
.\scripts\audit\check-deployment.ps1                       # read-only: does live ~/.claude actually MATCH the repo (agents by hash, skill junctions, hooks, contract block, settings entry, green stamp)
```

`test_obsidian_outbox_flush.py` offline-tests the `obsidian-outbox-flush.py` hook itself (no
Obsidian process, no network): the byte-size verification the hook substitutes for the CLI's
unreliable return code, replay idempotence, the outside-vault path refusal, and the no-vault
no-op. The byte-size comparison now lives in `outbox_io.py`, which the hook delegates to
since the Stage 0 extraction, so a search for `st_size` inside the hook file finds nothing.
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
python .claude/skills/loop-engineer/scripts/Test/test_ollama_bridge.py    # 33 tests: transport, budget probe, truncation signature, reasoning stripper, hygiene, seed, no fallback, empty body, mandatory vault consultation, --role forwarded to the resolver, think=false so a reasoning model does not eat the reply reserve, and a response that IS one fenced code block unwrapped so a model presenting its module for display is not failed on punctuation (measured 2026-08-28: a candidate scored 0/3 because every attempt was written verbatim to a .py and died with SyntaxError on line 1 before a single case ran, while prose around a fence, two blocks, and an unterminated fence are all left alone), an optional `fmt` carrying an Ollama structured-output schema in the request's top-level `format` field, with the omitted case asserted byte-identical so a new parameter cannot silently change what every existing caller measures, and the context window read PER RESOLVED TAG rather than from an import-time constant (a tag with no swept measurement fails the run and names itself instead of borrowing another model's window)
python .claude/skills/loop-engineer/scripts/Test/test_model_resolver.py   # 39 tests: eligibility, per-role win rule, qualification, LARI_LOCAL_MODEL override, no-fallback states, per-role current tag (resolve/qualify/adopt/refuse-to-seed), language-gate thresholds injected from one constant, coder target named .py so importlib can load it, plus the seven measured-budget tie-break cases: an exact tie in every role now goes to local-model-config.json, where the challenger wins if the incumbent has NO admissible measured configuration on this card or if the challenger retains a strictly larger window without losing decode throughput, while a regression is never rescued and a strict gain never reaches the tie-break; the per-role adoption path honours policy.win_rule, which it silently ignored before 2026-08-28
python .claude/skills/loop-engineer/scripts/Test/test_qualification_tasks.py  # 9 tests: grades the GRADER - a reference implementation of every coder contract, written from the task's own prompt rather than copied from the function it mirrors, must pass every case through the REAL oracle, so a wrong expected value fails here instead of silently mis-scoring every candidate forever; plus a negative control proving the check can fail, the ten-per-role floor, unique ids, and writer-side consistency (every required heading and frontmatter key actually named in its prompt, length window able to hold the sections)
python .claude/skills/loop-engineer/scripts/Test/test_matrix_command.py       # 8 tests: --matrix scores EVERY declared and installed candidate on EVERY task, including roles it is not declared for (a candidate graded only on its own role is not comparable - an 18/20 tag held the coder role while a 20/20 tag sat unscored on coder tasks), a tag with no measured context window is reported NOT RUNNABLE and is never even asked to run a task rather than printing 0/20, the summary ranks by total and carries num_ctx and decode rate, --json emits the whole structure, and no installed candidate is an explicit refusal
python .claude/skills/loop-engineer/scripts/Test/test_score_command.py        # 6 tests: --score reports per task and leaves the state document byte-identical, a role naming no task is refused, and --record refreshes ONLY an incumbent's stale number - a tag that is not current for that role is refused and nothing is written, so --record can never be a back door to adoption
python .claude/skills/loop-engineer/scripts/Test/test_context_budget.py   # 13 tests: task gate, descending scan, missing config is an explicit error
python .claude/skills/loop-engineer/scripts/Test/test_optimize_ollama.py  # 8 tests: a sweep rung ABOVE the model's own native context maximum is rejected instead of retained - Ollama clamps options.num_ctx silently rather than erroring, so the rung costs the memory of the smaller window and passes every threshold on numbers describing a window the daemon never granted; the honest rung still passes, one deviating run out of three is enough to reject, and the 300 MiB free-VRAM floor still rejects on its own; plus api_ps_row's residency_ratio from /api/ps size/size_vram (full, partial-offload, absent-tag), and the rung record carrying residency_ratio (worst run) and decode_tps (median run) alongside the existing acceptance predicate
python .claude/skills/opt-local-vram-llm/scripts/Test/test_vram_probe.py      # 11 tests: projector present vs baked into a single layer, registry-nested and locally-created manifest layouts, bare name resolves to :latest, unknown tag raises rather than returning empty, native context maximum from `ollama show`, LAST 'server config' line wins so a restart is not read as stale
python .claude/skills/opt-local-vram-llm/scripts/Test/test_vram_modelfile.py  # 9 tests: num_gpu/num_ctx always emitted, no repetition penalty ever emitted or copied, TEMPLATE inherited from a tag FROM but restated from a blob FROM, a multi-line template triple-quoted rather than flattened, triple-quoted directive parsed whole, per-role SYSTEM, measurement provenance in the comments
python .claude/skills/opt-local-vram-llm/scripts/Test/test_vram_daemon.py     # 5 tests: the variable written BEFORE the restart (after is a no-op the daemon never reads), a daemon that came back on another value stops the run, missing restart script named, the axis restored when the search aborts, no redundant restart when the search ends on the original value
python .claude/skills/opt-local-vram-llm/scripts/Test/test_tune_preflight.py  # 30 tests: the runbook's refusals and its comparison, which is all that CAN be tested offline since tune-new-model.ps1 spawns processes - a tag not installed refused by name, an ALREADY tuned tag refused (tuning a tuned tag measures a model two removes from what was downloaded), an unreachable daemon reported as the only message rather than joined by guesses, an empty tag refused WITHOUT consulting Ollama, and after the sweep a tuned tag that is absent or unmeasured refused instead of scored, since that is exactly the state the resolver reports as NOT RUNNABLE and scoring it prints zeros that read as the model's failure rather than the sweep's; plus the tuned-name suffix proven idempotent (both this module and the sweep name the same tag, and suffixing twice names nothing Ollama has), the ranking putting the role's own score above the overall one and NOT RUNNABLE rows last with their reason, a summary that says "behind" against an incumbent and says no tag is adopted rather than inventing one, exit 2 for a refusal by design and 1 for no verb at all (R12), and three static guards read off the .ps1 itself: it must never hand `--qualify` to the resolver, never shell out to `ollama run`, and never name a model tag - that last one carrying a negative control that plants a tag-shaped string, since a check that cannot fail is not a check
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
