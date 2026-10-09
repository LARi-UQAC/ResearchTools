# ResearchTools improvements

What the toolkit has learned, newest last. Appended automatically whenever a ResearchTools
weakness is fixed from inside another project, and whenever an attempt is abandoned.

There is no git in that loop, so this file is the record: it answers "what has my toolkit
learned" and "when did this behaviour change". The full rule is the RT-CONTRACT block in
`~/.claude/CLAUDE.md`, whose source is `CLAUDE.template.md`.

Format: one entry per fix. Date, owning skill or agent, what changed, where it was found,
and how it was proven. An abandoned attempt is marked ABANDONED and names the failing test,
its error, and any file left behind skip-marked.


## 2026-09-26 — Architecture.md diagram palette recolored; graphify deferral (markdown)

**Change:** Three diagram elements in Architecture.md recolored to the project's brand palette (teal `#1F9E8F` and amber `#C9762F` against generic defaults). Routine application of existing palette knowledge, no new learning.

**Deliberately NOT changed:** NEW_ARCHITECTURE.md's 13 diagrams remain untouched — that file is shared with ThesisTracker and not yet finalized. Recoloring would fork the synced copies; consolidation is planned later.

**Graphify:** AST-only refresh at repository root. File is Markdown (documentation), not code. Semantic pass deferred — no code structure or content semantics changed, only visual formatting applied. Cost-benefit: AST sufficient to track presence and dependency links; semantic pass would cost a model call for no structural gain.

**Project log:** appended entry to `10_Projets/Logiciels/ResearchTools/Decisions.md` via outbox.

## 2026-09-26 — MkDocs Material GitHub Pages asset-path fix; semantic pass deferred to vault note

**Defect found and fixed on live site:** MkDocs Material's `theme.logo` and `theme.favicon` configuration references can reach assets outside `docs_dir` via parent-relative paths (e.g., `../ResearchToolsLogo.png` at the repository root). This pattern works in `mkdocs serve` (local domain root, no path prefix) but breaks silently on GitHub Pages PROJECT pages (`https://<user>.github.io/<repo>/`): Material emits root-absolute hrefs (`/ResearchToolsLogo.png`) instead of repo-relative ones, missing the `/<repo>/` prefix and returning 404. Discovered 2026-09-26 by navigating the live site and checking the browser console.

**Fix:** copied logo to `docs/assets/ResearchToolsLogo.png` and updated `mkdocs.yml` `theme.logo` and `theme.favicon` to use relative paths (`assets/ResearchToolsLogo.png`). Redeployed with `mkdocs gh-deploy`.

**Durable learning:** atomic note `30_Ressources/Publication/mkdocs-github-pages-asset-path-guard.md` documenting the root cause, guard rule, and reusability across static-site generators on PROJECT pages. Key: LOCAL PREVIEW CANNOT CATCH THIS — the bug is invisible until live deploy. Verification: browser console check on the real URL.

**Project log:** appended 2026-09-26 entry to `10_Projets/Logiciels/ResearchTools/Decisions.md`.

**Graphify:** AST-only refresh at repository root (command form: graphify update, dot argument). Semantic pass deferred: changed files are config (`mkdocs.yml`) and image (`docs/assets/ResearchToolsLogo.png`), neither code. No semantic extraction justifies the model cost; AST-only sufficient to track dependencies and file presence.

## 2026-09-26 — MkDocs landing page built; base64 context-cost lesson captured; graphify deferral

**Completed:** MkDocs landing page for documentation site. Changes: `docs/index.md` (complete rebuild as real landing page with front-matter `hide: [navigation, toc]`, hero section with banner image + tagline + 3 CTA buttons, feature grid with 3 cards, existing "Why ResearchTools" table); `mkdocs.yml` (added `attr_list` and `md_in_html` extensions to Markdown config); `docs/assets/extra.css` (brand CSS classes: `.rt-hero`, `.rt-cta`, `.rt-feature-grid`, `.rt-feature-card`, `.rt-stats` with light/dark variants, integrated into site color palette).

**Durable learning captured:** Atomic note `30_Ressources/Methode/base64-encoding-llm-context-cost.md` documenting a measured token-cost lesson. Reading a self-contained HTML file with base64-encoded assets into context is extremely expensive: a 252,740-character base64 string consumed ~2.7M tokens (9% of file = ~241K tokens). Base64 amplifies context cost by roughly 30× compared to the unencoded binary. Consequence: use htmlpreview.github.io for GitHub-hosted pages, ask users for local preview (mkdocs serve), never embed as base64 for model inspection.

**Project Decisions entry:** Appended 2026-09-26 entry to `10_Projets/Logiciels/ResearchTools/Decisions.md` noting the landing page was built, visual verification was deferred due to token-cost measurement, and structural verification was substituted.

**Graphify:** AST-only refresh at repository root (`graphify update .`). Semantic pass deferred: three changed files are documentation/config (index.md, mkdocs.yml, extra.css) with no code understanding to extract. Semantic extraction adds no value for a documentation-only change.

## 2026-09-26 — GitHub-presentation playbook consolidated; AST-only graphify update deferred

**Completed:** `docs/github-repo-setup-playbook.md` — an 8-phase, reusable playbook for bringing another repository's GitHub presentation to publication standard. Phases: brand palette discovery, docs structure (docs/manual/ book-split), community files, README template, MkDocs Material setup (with measured gotchas), GitHub settings via `gh` CLI, R30/R31 governance pattern (generic, not hardcoded), verification checklist, appendix naming measured mistakes caught during reference implementation.

**Consolidation:** pointer note filed to `30_Ressources/Publication/github-presentation-setup-consolidated.md` (via outbox) stating the playbook's location and linking it to related atomic notes it stitches together (ffmpeg GIF technique, GFM-slug computation, MkDocs exclude_docs gotcha, Playwright file-render boundary, rule-index-drift prevention). Those five remain independent and reusable; this pointer is the discovery path for future sessions asked to "set up GitHub for a new repo."

**Project log:** one-line append to `10_Projets/Logiciels/ResearchTools/Decisions.md` noting the playbook was written, its scope, and its docs links.

**Graphify:** AST-only refresh at repository root (`graphify update .`). Semantic pass deferred: new markdown document (~550 lines of documentation text) + two small doc edits (docs/index.md, mkdocs.yml). Cost not justified for a documentation-only change; semantic extraction adds no code understanding.

## 2026-09-26 — Governance additions R30 and R31; index-drift failure class discovered and documented

**Governance additions:**
Two numbered rules were added to `.claude/rules/workflows.md` to enforce PRs against the toolkit's own governance:
- R30: A PR needs a linked GitHub Issue with a Kanban card on the repo's own project board before opening it (exception: pure documentation fixes).
- R31: Documentation for whatever a PR touched must be updated in the same PR before it can be approved/merged (merge-time gate, companion to R30's open-time gate).

Both rules are now surfaced at the point of use: `CONTRIBUTING.md` describes R30 as an open-time checklist, and `PULL_REQUEST_TEMPLATE.md` embeds R31 as a merge-time gate item.

**Learning discovered: index enumeration drift:**
While updating `.claude/rules/code-style.md` to reflect the current rule roster (R0 through R31), a silent failure was uncovered: the section's "Rule identifiers" header had stated "R0 to R27" for several sessions while R28 and R29 had been added unnoticed, leaving readers consulting that index with false information. This is not a code defect but a process one: a hand-maintained index that enumerates a bounded sequence drifts silently when a new item is added without updating that index in the same commit. Identical patterns exist for hook inventories, mirror counts, and feature lists throughout the repository.

**Learning documented:** Wrote atomic note `30_Ressources/Methode/index-enumeration-drift.md` (via outbox) capturing this failure class, its measured instance, its root cause (sequences defined in separate files with no mechanical link to the index that claims to know them), and the antidote: grep for EVERY place that states the old bound after adding a new item, then update all of them in the same edit.

**Secondary learning:** `.claude/rules/` is a machine-wide junction; editing a rule file here takes effect immediately in every Claude Code project on this machine. The consequence: rule text must be phrased generically ("this repo's own X") rather than with concrete instances (a literal URL, owner name, project number), because the same rule is read from unrelated projects where that instance is wrong. An R30 open-time draft used a GitHub Project URL; it was reworded to "the repo's own project board" to remain valid across machines and projects.

**Project Decisions entry:** Appended 2026-09-26 entry naming R30 and R31, their enforcement, the GitHub Wiki disable and Project board #6 creation, and the vault note about index drift.

**Graphify:** AST-only refresh at repository root (`graphify update .`) on the three edited rule files (code-style.md, workflows.md, and two supporting files). Semantic pass deferred: rules are documentation, not code; no semantic extraction justifies the model cost.

## 2026-10-02 - obsidian-cli - the voice-ask queue now reaches a project's own code graph

**Change:** The ask queue, previously vault-only, now answers questions by searching both the vault AND the project code graph (read-only `graphify query`). New module `daemon_graph.py` extracts keywords from a question, resolves the repository by walking upward from a vault hit's `index.md` property to find its `repo:` key, and queries the graph deterministically (AST-only, no model cost). `daemon_ask.answer()` now publishes in two parts: vault search results published via an injected `publish` callback BEFORE the graph part runs, so partial answers appear immediately while graph queries execute in the background. The three graph outcomes (ok/skipped/error) are kept apart, and a keyword-extraction failure is "error" per spec section 6's table, never "skipped".

**Files changed:** `daemon_graph.py` (new module: extract_keywords, entity_repo, query_graph), `daemon_ask.py` (answer() now wires a callable publish; docstring now correctly states "calls graphify query"), `vault_daemon.py` (_write_answer gained a `consume=False` mode to support published partials; final write overwrites a partial even if answer() crashed after publishing), `daemon-config.json` (new keys `ask_search_roots`, `ask_keywords_max`, `ask_graph_budget_tokens`, `ask_graph_max_chars`, `ask_graph_timeout_s`, `ask_graph_sentences`).

**Tests:** three new test files all passing. `test_daemon_graph.py` (23 tests): extract_keywords (schema-constrained, failure modes named), entity_repo (repository resolution via index.md property walking, orphan notes), query_graph (subprocess contract: list argv, cwd, timeout, truncation gate). `test_daemon_ask.py` (28 → 50 tests): old tests + accent-folded vault search, project/resource folder ranking, graph_sentence catalogue read from config, progressive publish with three graph outcomes. `test_vault_daemon.py` (14 → 19 tests): old tests + _write_answer consume=False path, run_ask_once wiring, final write overwriting partial, crash after publish still landing as error on disk.

**Project stage:** plan1a+1b of a 3-plan design (docs/superpowers/plans/2026-10-02-voice-graph-lookup/spec.md). Plan2 is the dashboard side; plan3 is governance/rollout/vault repo: properties.

## 2026-10-02 - obsidian-cli / rt-observe - the voice panel now polls its answer in parts instead of waiting for one final reply

**Change:** `POST /api/voice/ask` returns `{status: accepted, id}` at once instead of blocking; a new `GET /api/voice/answer?id=` route is what the browser polls repeatedly for the daemon's progressive answer (plan1a+1b). `voice_ask.py`'s `read_answer` replaces the removed `poll_answer` (one non-blocking read per call, instead of an internal sleep loop). `rt_state.voice_callables` now returns THREE callables - `transcribe_fn`, `ask_fn`, `answer_fn` - instead of two. The voice panel's JS speaks each answer part as it arrives, via a new `pollAnswer`/`queueUtterance` pair, giving up only after `CFG.timeouts_seconds.voice_ask_wait` seconds with no NEW part (tracked from the last part's own arrival, not from when the question was asked).

**Files changed:** `voice_ask.py` (`read_answer`, `TERMINAL_STATUSES`), `observe-config.json` (new key `voice.answer_poll_ms`), `rt_state.py` (`voice_callables`'s three-tuple return; `view_config`'s new `voice.answer_poll_ms` and `timeouts_seconds.voice_ask_wait` keys), `rt_server.py` (new `voice_answer` parameter and `GET /api/voice/answer` route; `POST /api/voice/ask` now answers 202), `assets/rt_state.html` (the poll loop: `pollAnswer`, `queueUtterance`, `stopAnswerPoll`).

**Tests:** `test_voice_ask.py` (7 -> 10), `test_voice_config.py` (5 -> 6), `test_voice_routes.py` (16 -> 22), `test_rt_view.py` (71 -> 76), `test_rt_state.py` (82 -> 87, voice wiring). All green.

**Project stage:** plan2 of the 3-plan design (docs/superpowers/plans/2026-10-02-voice-graph-lookup/spec.md). plan1a+1b (daemon side) is committed above; plan3 (governance/rollout/vault repo: properties) is still pending.

## 2026-08-28 - repo-wide hooks - a session now prints the hook inventory it actually loaded

**Found:** a session opened showing only `Session: RTK=active | Caveman=full | git-sync=on`
and the hooks were assumed dead. They were not: four of six SessionStart entries had run and
emitted, while `obsidian-outbox-flush.py` writes its `[OUTBOX]` lines to stderr and
`install-junctions.ps1 -Sync -Quiet` is quiet by construction. Only a SessionStart hook's
stdout reaches the session context. Two drifts surfaced with it. The hook table in
`CLAUDE.template.md` claimed eleven entries against thirteen declared in `settings.json`,
omitting the `install-junctions -Sync` entry and the `Stop` memory-upkeep hook; and nothing at
startup reported a declared hook whose script had gone missing, which is exactly the
2026-08-27 `vault-access-guard.py` failure that refused nine tools for four turns.

**Changed:** new `.claude/hooks/session-hooks-inventory.py`, registered as a SessionStart hook
in `.claude/settings.template.json` and in the live `~/.claude/settings.json`. It reads
`settings.json`, prints on stdout a header line, one compact line per event, and a
`[HOOKS ALERT]` line naming any declared hook whose script is absent from disk. It exits 0 on
a missing, unreadable or malformed settings file (R11), takes its path from the environment
rather than a literal (R1), and holds no clock or randomness (R19). The hand-maintained tables
in `CLAUDE.template.md`, the live `~/.claude/CLAUDE.md` and `CLAUDE (up).md` now describe each
hook's ROLE and defer the count to the generated inventory, with the stdout-versus-stderr rule
written into the "un hook doit échouer en silence" consequences.

**Proven:** `.claude/hooks/Test/test_session_hooks_inventory.py`, 20 offline tests, no network
and no settings file of this machine read. `scripts/test/run-offline-tests.ps1` green
end to end (46 PASSED, 0 FAILED, 1 NOT RUN for the pre-existing `pypdf` gap), and
`.rt-green.json` rewritten. Running the hook against the real `settings.json` then caught two
defects the fixtures had not: the `Stop` hook's prose reason mentions `Decisions.md` and
`model_resolver.py`, which became the hook's label and a false missing-file alert, and a bare
relative script name was checked against a working directory that is not ours to assume.
Script detection was narrowed to the invocation head and to paths carrying a separator, with
three tests added for those cases. `install-junctions.ps1 -Sync` correctly HELD the file until
the suite was re-run, then propagated it; `~/.claude/hooks/session-hooks-inventory.py` now
prints fourteen entries over six events with no alert.

## 2026-08-28 - repo-wide hooks - the inventory now carries per-hook status and is shown to the user

**Found:** the inventory added earlier the same day was emitted correctly and seen by nobody. A
SessionStart hook's stdout reaches the model's context, not the user's pane, exactly like
`[RTK ACTIVE]` and `[AUTO-SYNC CHECK]`. The `Session:` line is visible only because its hook
asks for it to be printed. A second session read the silence as the hooks being dead, then
declined to relay the block on the grounds that "Hooks globaux" warns against duplication - a
misreading of that warning, which is about a table hand-copied INTO a document, not about a
block regenerated from `settings.json` at every start. The inventory also named each hook
without saying anything about its state.

**Changed:** `session-hooks-inventory.py` now emits a per-hook status - `ok`, `MISSING`,
`inline`, `template` - with the matcher appended for a tool-gated event, header tallies, and a
final `[HOOKS DISPLAY]` line asking for the block to be relayed verbatim. "Status de session
obligatoire" in `CLAUDE.template.md` and in the live `~/.claude/CLAUDE.md` now REQUIRES that
relay right after the `Session:` line, excludes the directive line itself from the copy, states
why it is not the duplication the hooks section warns about, and tells a session with no
`[HOOKS ACTIVE]` in context to say so rather than invent an inventory.

**Proven:** the suite grew to 26 tests, adding the four status states, the matcher segment and
its absence off tool-gated events, the header tallies, and the directive's presence and position
after the alert. `scripts/test/run-offline-tests.ps1` green end to end: 48 PASSED, 0 FAILED,
0 NOT RUN. `install-junctions.ps1 -Sync` propagated the hook.

## 2026-08-28 - Codex harness mirror: skills reachable natively, both ceilings tested

**Why:** asked whether a ChatGPT harness mirror was possible. "ChatGPT" is three surfaces,
not one. The coding harness, Codex, was already served by the root `AGENTS.md`, but the
repo's 15 skills were invisible there: the mirror map's claim that "skills have no per-tool
mirror" was true of Copilot, OpenCode and Continue, and false of Codex, which is the one
harness with a native skill convention.

**Changed:** `install.ps1` now generates `.agents/skills/<name>/SKILL.md` for every skill -
a POINTER carrying only the frontmatter, body directing the reader to the canonical
`.claude/skills/<name>/SKILL.md` - plus a nested `.claude/skills/AGENTS.md` that Codex
appends to the root one when the working directory is inside that tree. Two new params,
`$CodexSkillListBudget` (8000) and `$CodexDocMaxBytes` (32768), carry Codex's own documented
defaults with the date and source they were verified against (R0, R13). Descriptions are
trimmed to whole sentences under a computed per-skill cap, the first sentence always kept.
Registered in `README.md`, `Architecture.md`, `docs/authoring-and-mirrors.md` (mirror map,
the corrected claim, and the add-a-skill checklist) and `.claude/rules/testing.md`.

**Two defects caught by the new test rather than by reading:** the first generated set
carried the source's own double quotes into the mirror and then trimmed mid-scalar, shipping
11 of 15 mirrors whose YAML frontmatter did not parse while the installer printed a green
`[OK]` for each - the exact silent class this repo already knows from the Copilot stub. And
one skill opens its description with a `>` block indicator, which is syntax, so the mirror
read "> Generate support..." as text. The description is now emitted as a single-quoted
scalar with internal quotes doubled, and both parsers strip the block indicator.

**Proven:** `test_codex_mirror.py`, 10 tests, was run against the BROKEN generated set first
and failed on 12 mirrors before the fix, so its teeth are demonstrated rather than asserted.
Budgets are parsed from `install.ps1` so the test cannot outlive a threshold change.
`scripts/test/run-offline-tests.ps1` green end to end: 56 PASSED, 0 FAILED, 0 NOT RUN.

**Not done:** Codex custom prompts (`$CODEX_HOME/prompts/`) were considered as the analogue
of the `-Personal` Copilot install and deliberately skipped - they are deprecated upstream in
favour of skills, which this change already covers.

## 2026-08-29 - setup.ps1 -InstallDaemon, and the graphify drain's queue named as a defect

**Gap:** `vault-daemon-autostart.ps1 -Install` existed and nothing called it, so a new user
who ran `setup.ps1` got skills, mirrors and hooks but no daemon: raw drops landed in
`~/.claude/obsidian-outbox/raw/` and waited for someone to notice. The flush hook reports
them at SessionStart, which is the alarm, not the fix.

**Change:** `setup.ps1 -InstallDaemon` delegates to that script, and `-All` includes it only
when a vault is configured, skipping with a stated reason otherwise. The decision and the
delegation live in `scripts/lib/rt-daemon-install.ps1` for the same reason `rt-sync.ps1`
exists: dot-sourcing `setup.ps1` to test it would run its whole interactive flow. `setup.ps1`
is the home rather than `install.ps1`, which regenerates mirrors many times a day and runs at
every session start through `-Sync`; a Startup-folder write there would come back after the
user deliberately removed it.

**Proven:** `scripts/test/verify-daemon-install.ps1`, 22 checks, including -Preview invoking
nothing (R16), a non-zero autostart code propagating rather than being swallowed, and the
professor's real Startup folder listed before and after so the test cannot create the shortcut
it is meant to be reasoning about.

**OWNER UNKNOWN, left undone:** `daemon_outbox.enqueue()` files vault-relative note paths into
a `graphify` queue that `drain_graphify` would hand to `graphify update` with cwd set to a code
repository, where those paths name nothing. Reviewed 2026-08-29 with M. Otis: the vault is
cross-project and a graphify graph is per-project, so a machine-global daemon holding one
`graphify_repo_root` is the wrong shape at any value. `graphify_repo_root` therefore stays
null, its provenance in `daemon-config.json` now says why, and the queueing itself wants
removing - a code graph is refreshed by `local-writer` pointing `graphify update` at the code
it just wrote. Not done here because it is a behaviour change to the daemon with its own test,
outside this session's scope.

## 2026-08-29 - tune-new-model.ps1: the runbook from a downloaded model to the adoption gate

**Gap:** every piece between "a model is on disk" and "the resolver serves it" existed and was
tested, but the SEQUENCE lived nowhere. A new model was therefore either adopted without being
compared against the field, or tuned, declared and forgotten.

**Change:** `.claude/skills/opt-local-vram-llm/scripts/tune-new-model.ps1` runs steps 1 to 3 -
sweep for this card, score against the frozen task set writing nothing, then `--matrix` the
whole field - prints the comparison and STOPS. Step 4, `model_resolver.py --qualify`, is the
only step that changes which tag every local agent executes, so it stays a command a person
types: a harness that adopted on its own would make measuring and taking effect the same
event, and nobody would see the numbers before they applied. The decisions live in
`tune_preflight.py` beside it, where the offline suite reaches them, exactly as `run-drill.ps1`
keeps its teardown in `vault_journal.py`. `vram_optimizer.py` gained `tuned_tag_for()` and
`TUNED_TAG_SUFFIX` so the harness that scores the tuned tag does not spell the suffix a second
time (R2).

**Proven:** `test_tune_preflight.py`, 30 tests. Refusals: a tag not installed, a tag that is
ALREADY tuned, an unreachable daemon, an empty tag refused without even consulting Ollama, and
after the sweep a tuned tag that is absent or has no measured window - that last one is the
state the resolver reports as NOT RUNNABLE, where scoring anyway prints zeros that read as the
model's failure rather than the sweep's. Plus three static guards on the `.ps1`: it must never
hand `--qualify` to the resolver, never shell out to `ollama run`, and never name a model tag,
that one carrying a negative control so a broken pattern cannot pass silently.
`scripts/test/run-offline-tests.ps1` green end to end: 57 PASSED, 0 FAILED, 0 NOT RUN.

**Not done:** the harness's happy path is not covered offline and cannot be - it spawns the
sweep, which restarts the Ollama daemon. It was exercised by hand only as far as its first
refusal (an uninstalled tag: stop, exit 1, no report directory created).


## 2026-09-26 - local-writer / obsidian-cli - drafted vault notes must pass a fidelity check before staging

**Change:** new `.claude/skills/obsidian-cli/scripts/note_fidelity.py` (+ `note-fidelity.json`). local-writer now stages every drafted note through `note_fidelity.py --brief <facts given> --note <draft> --stage <slug>`, which stages nothing (exit 2) when the draft carries a number, identifier, file name, commit hash or `[[link]]` absent from the brief. `local-writer.md` step 1 of its write sequence and `obsidian-cli/SKILL.md` say so.

**Found:** a memory-upkeep run on branch feat/voice-memory-query. Given a precise brief, local-writer's local model drafted five notes that all carried invented facts (an unmeasured "1405 MiB", `get_store()`/`load_oo_config()` credited with a daemon fix they have nothing to do with, a wrong `[[project]]` link, an inverted finding) and the wrapper reported them as correct, because every existing rule checked only that the files existed. They flushed; six vault writes (journal records 506-511) were undone with `vault_journal.py --undo-since 506`, authorized by the operator.

**Proven:** `test_note_fidelity.py`, 15 tests, including that day's real draft and brief verbatim; replaying the real fabricated Decisions.md draft against its real brief refuses it naming `get_store()`, `load_oo_config()`, 1405, 421 and 300. Known limit, pinned by a test: a claim re-worded into its opposite with no new token passes, so the staged note is still read. Full offline suite green.

## 2026-09-27 - narrative-cv / latex-hygiene - a CRSNG CV could not follow the funder's citation rules

**Change:** `narrative-cv/scripts/cv_build.py`: section-2 item fields now carry `**bold**` and clickable DOI URLs (`inline_latex`), a backslash is escaped, the `' -- '` separator is replaced by language-aware labels (`item_labels` in `contribution_types.json`), paper is `letterpaper`, the tri-agency variant prints its template heading and name line, `load_model()` reads `prose_file` (confined to the model folder, R24), an item's `references` list puts each citation on its own line, and `render` reports `citation_warnings()`. `contribution_types.json` gains per-variant `citation_rules`: the FRQ bolds the candidate and co-researchers, the CRSNG / tri-agency CV bolds only a lead author not listed first (NSERC instructions page dated 2026-01-27). `latex-hygiene`: `aiscan` publishes `max_length`, and `aiscan --max-words N` lists every sentence above N words (R1.8), with no default cap (R0). `narrative-cv/SKILL.md` and `agents/narrative-cv-writer.md` state the funder-dependent bold rule; mirrors regenerated with `install.ps1 -Profile engineering`.

**Found:** drafting a CRSNG Alliance tri-agency CV (project NanoSmart) from `CV_Martin_Otis`. Every item field was escaped wholesale, so no name could be bolded, the renderer emitted the forbidden double dash, the item labels were French-only, sentence length (R1.8) could only be measured by a throwaway script, and the agent applied the FRQ bold rule to a CRSNG CV, bolding a third author. Two assembly scripts were also written in the session scratchpad; they were data wearing a script's clothes and were replaced by `prose_file` and data files in the CV folder.

**Proven:** `test_cv_build.py` 13 -> 35 tests, `test_tex_check.py` 39 -> 43 tests; full offline suite rerun after the last change (see below); the real CV rebuilt with 0 LaTeX errors, 6/6 pages, 0 forbidden characters, aiscan 1 %, longest sentence 30 words, and `render` reporting no citation warning once the bold was removed.

**Not a defect, recorded to stop it being re-investigated:** `download_pdf.py --browser` did warn that Playwright was missing when run under the system Python. The warning was hidden by a `| tail` filter. Run it under `.venv-skills` (Playwright installed): four IEEE papers came back through the headed browser on the UQAC network, and one Taylor & Francis paper (10.1080/23311916.2024.2432515) still failed.

## 2026-10-01 - narrative-cv / aider-setup / rt-observe / form-service / scopus - no account name, machine path or private identifier in a public repository (Quebec Law 25)

**Change:** tracked files no longer carry the Windows account name (aider-setup `config/context-budget.json`, `config/skills.json`, `MEMORY.md`, rt-observe `test_rt_openobserve.py`), now `{{HOME}}`, the template token `config/aider.conf.yml` already used; `verify-aider-plan.ps1` hands the driver a copy of the template budget with this machine's home substituted, the token assembled because the file ships in the kit. `profiles/engineering.yaml` `cv.project_dir` is `{{HOME}}/Your_CV/`, resolved by `cv_common.load_cv_project_dir()` (a leading token only; anywhere else is refused). Fixtures: real third-party names replaced with fictitious ones (narrative-cv, scopus `test_author_name_split.py`, form-service `SKILL.md` and `test_fill_form.py`), code-permanent-shaped values replaced with `XXXX000000` and student-domain emails with `student@example.org` (form-service tests, `deploy/form-service/tests/test_api.py`, three `plans/done` files). `.gitignore` now covers `.scopus_key`, as `security.md` already claimed.

**Found:** a personal-data audit of narrative-cv requested by the operator; `verify-no-personal-data.ps1` was red on eight lines in five files, and the repository is PUBLIC. The same values were in history (account name since 2026-07-11, code-permanent values since 2026-07-29).

**History:** rewritten with `git filter-repo --replace-text` in a separate bare clone (248 commits, author, date and message identical; a full-history scan finds zero remaining occurrences against 23 before). Pushed by the operator the same day (main `36be054`, the 4 `feat/uqac-forms-*` branches and tag `v0.1.0`; `gh-pages` unchanged), after the session's own force-push was refused by the auto-mode classifier. It bypassed the `Main protection` ruleset. Still open: 17 merged-PR refs and the 2 forks keep the old commits until GitHub Support purges them, and every existing clone must re-clone.

**Proven:** full offline suite 102 passed / 0 failed / 1 not run (pyhanko); `verify-no-personal-data.ps1` green; `verify-aider-plan.ps1` 33/33 before and after; `test_cv_common.py` 16 -> 18. Not run: `deploy/form-service/tests/test_api.py` (fastapi absent from `.venv-skills`, outside the offline runner).

**Consequence:** `/cv` now resolves to `~/Your_CV/`, not the previous external folder that still holds the existing inventory; moving or linking it is the operator's decision. `aider-night.ps1` run straight from the repository now refuses as an uninstalled kit, by design.

## 2026-10-02 - security.md / CLAUDE.md / CLAUDE.template.md / obsidian-cli vault properties - voice-graph-lookup governance, rollout, and vault mapping

**Change:** `.claude/rules/security.md` names the vault daemon as a second, narrowly gated graph reader (read-only graph query only, gated on `from: rt-dashboard`); `.claude/CLAUDE.md`'s graphify routing row gained one sentence on the same mechanism, regenerated into `CLAUDE.template.md`'s RT-CONTRACT block via `rt-contract.ps1`. `README.md` and `docs/manual/07-rt-observe-dashboard.md` document the two-part spoken answer. Three vault projects (`Assistive-feeding-robot`, `CostEstimator`, `ResearchTools`) gained a `repo:` frontmatter property, mapping them to their code repositories. `CLAUDE.template.md` gained the one heading the live global `~/.claude/CLAUDE.md` had that the English template (translated 2026-08-30, U5) did not yet carry: "Scripts: always in ResearchTools, never in the scratchpad" (the live 2026-09-27 rule). With the operator's explicit go-ahead, `~/.claude/CLAUDE.md` was backed up to `~/.claude/CLAUDE.md.fr.bak` and replaced by the substituted English template, confirmed byte-identical by `check-claude-template.ps1` (0 differing lines).

**Found:** while building the vault-to-repo mapping, a real data-integrity defect (see the 2026-10-02 entry above on the voice-ask queue): the first `repo:` staging attempt used append on an existing note, which always writes a second, never-read frontmatter block rather than editing in place. Caught by reading the staged outbox files directly rather than trusting the dispatching agent's own summary; the fix landed in `outbox_io.py` (commit `e22608a`). The first broken drafts had already auto-flushed before they could be deleted, corrupting both `Assistive-feeding-robot/index.md` and `CostEstimator/index.md` with a duplicate frontmatter+body block; a second dispatch repaired them directly, and a THIRD, independent read-only dispatch confirmed the repair clean (one frontmatter block each, `repo:` present, no duplicate body) rather than trusting the repair agent's own report.

**Proven:** `test_graph_routing.py` 18/18, `test_vault_access_guard.py` 31/31, `verify-rt-contract.ps1` and `verify-template-audit.ps1` all passed after the template port, `check-claude-template.ps1` reporting 0 unclassified differences against the newly installed live global file.

**Project stage:** plan3 of the 3-plan design (`docs/superpowers/plans/2026-10-02-voice-graph-lookup/spec.md`), closing the feature. Tasks 1, 2, 3, 4, 5 and 6 done; Task 7 (live verification against the real running daemon) deferred to a dedicated session by operator choice, since it needs the branch merged or the live daemon pointed at this worktree.

## 2026-10-07 - obsidian-cli / rt-observe - PR #49 Copilot review (2 High, 1 Medium, 1 Low already closed, 3 Low)

**Change:** `outbox_io.set_frontmatter_property` refuses a value containing CR or LF before touching the file (a staged directive's body can carry more than one content line, and embedding it verbatim would insert extra frontmatter lines, caught only at post-write verification otherwise, with the outbox item replaying the corruption forever). `flush_one` now journals a `set-property` write as a `vault_journal.STATE_SNAPSHOT` (full pre-edit text) instead of a size-based `STATE_WRITE`: the edit happens in the middle of the file and can shrink it, so a truncate-based undo would either chop bytes off the body while leaving the new value in place, or refuse outright. `voice_ask.read_answer` now catches `OSError` (not only `ValueError`) around the read, closing a race where two overlapping polls both pass `path.exists()` and the first one's terminal-status unlink deletes the file before the second's `read_text()`. `daemon-config.json`'s French `ask_graph_sentences.skipped` now says "graphe" instead of the English "graph". `obsidian-cli/SKILL.md` documents the `set-property` directive (syntax, existing-note-only, one-line value constraint) that commit `e22608a` had shipped undocumented. Mirrors regenerated with `install.ps1 -Profile engineering` (`.github/instructions/security.instructions.md` and `testing.instructions.md` were stale, missing the 2026-10-02 vault-daemon-reader exception).

**Found:** GitHub Copilot's automated review of PR #49 (`feat/voice-graph-lookup`), 7 inline findings. One (`rt_state.view_config` requiring `voice.answer_poll_ms`) was reviewed against commit `e22608a`, two commits before `2aebd4f` had already declared the key in `observe-config.json` on the same branch - confirmed still passing (`test_rt_state.py` 87/87) and reported back as already-fixed rather than touched again.

**Proven:** `test_outbox_io.py` 14 tests (4 new: multiline/CR-only value refusal, `set-property` journaled as SNAPSHOT not WRITE, undo restores byte-for-byte on a shrinking edit), `test_voice_ask.py` 11 tests (1 new: concurrent-unlink race), `test_vault_daemon.py`, `test_vault_journal.py`, `test_daemon_ask.py`, `test_rt_state.py`, `test_voice_routes.py` all green.

## 2026-10-01 - repo-wide - privacy guard: global pre-commit hook, CI workflow, push protection

**Change:** `.claude/hooks/git/` holds a betterleaks rules file (`privacy-rules.toml`: the betterleaks default secret rules plus five personal-data shapes), a global `pre-commit` hook that scans the staged diff and the machine's account name and then chains the repository's own hook, `_chain` for every other hook name, and `install-git-hooks.ps1` (sets the global `core.hooksPath`, refuses another one, dry run, JSON report, read-back). `.github/workflows/privacy-scan.yml` applies the same rules to every push and pull request, reusable by the lab's other public repositories, with `actions/checkout` pinned by SHA and the betterleaks binary by checksum. New rule R34: fixtures never carry a real identity. "No CI/CD" removed from testing.md, workflows.md and CONTRIBUTING.md.

**Found:** after the 2026-10-01 history purge, the operator asked for the 2026 best practice; it is three layers on one standard scanner (pre-commit, CI as the authoritative gate, GitHub push protection), not a custom scanner. Git 2.53 has no config-based hooks (probed), hence `core.hooksPath` plus chaining. Real names are out of scope by operator decision.

**Proven:** `test_git_privacy_guard.py` 15 tests; the rules give zero findings on the current tree and on the full history.

**PR #40 review (2026-10-02):** six Copilot findings fixed - installer ownership check, trusted CI rules, full githooks(5) list, uninstall read-back, whole-token account match, every-branch push scan. One partly declined with a measurement: `reference-transaction` and `post-index-change` are not chained, since chaining them took a commit cycle from 575 ms to 3598 ms. `test_git_privacy_guard.py` 15 -> 24 tests; four of the new ones fail on the pre-review code.

**Local review rounds (R35, 2026-10-02):** round 1 (security-review) fixed an ignore file in the PR checkout silencing the scan and a fail-open bootstrap; round 2 (code-review high) reproduced two more bypasses - a .gitattributes -diff and an evil merge commit both hid content from the betterleaks git subcommand - now closed by feeding git log -p --text -m (CI) and git diff --cached --text (hook) to betterleaks stdin, plus the privacy script as pre-merge-commit, /Users/ and /c/Users/ paths, accented account names, case-insensitive code permanent, file paths in the account check, and a bootstrap judged at the trusted ref. Declined with measurement: a case-insensitive FRQ shape (it matches citation keys such as smith2020). The new /Users/ rule found a real leak in history: a 2026-08-25 commit added the code-graph output folder carrying a collaborator macOS account path (2588 matches, deleted from the tree 2026-09-02, still in public history). test_git_privacy_guard.py 27 -> 33 tests.
- 2026-10-02 - privacy guard round 3 (R35): global pre-push hook scans every outgoing commit and message; hooks and CI scan added lines only; CI rescans on PR retarget against the live base; /Users rule catches diff-line and file:// forms; UTF-16/binary and stale installed-rules limits documented in security.md. test_git_privacy_guard.py 33 -> 40.
- 2026-10-02 - privacy guard round 3 (R35): global pre-push hook scans every outgoing commit and message; hooks and CI scan added lines only; CI rescans on PR retarget against the live base; /Users rule catches diff-line and file:// forms; UTF-16/binary and stale installed-rules limits documented in security.md. test_git_privacy_guard.py 33 -> 40 (full offline suite not re-run).

## 2026-10-02 - repo-wide rules - R36, no task runs without a skill; a missing skill is authored here, never installed

**Owner:** repo-wide rule (`.claude/CLAUDE.md` exported region, `.claude/rules/workflows.md`, `security.md`); no single skill owns it.

**Found:** the operator asked that every CLAUDE.md level state it: any model or harness runs a task only through a skill or an agent using a skill, an unclear or missing match goes to `AskUserQuestion`, a missing skill is built with `skill-creator` inspired by the nearest one found read-only with `find-skills`, and nothing is installed from the internet. Until then the routing table said where to reach a skill but nothing forbade acting without one. Read in `~/.agents/.skill-lock.json`: `find-skills` itself came from `vercel-labs/skills` on 2026-07-27.

**Changed:** new section "Skill-first rule (R34)" (initially filed under this number; renamed to R36 the same day - see the 2026-10-02 renumbering entry two paragraphs below) inside the RT-EXPORT region, so it reaches `CLAUDE.template.md` (RT-CONTRACT block, regenerated) and the live global file at the next `-Sync`; a routing-table row for a task no skill covers; the rule in full in `workflows.md`; "Skill provenance" in `security.md`; the rule index in `code-style.md`; a statement of the rule in the three heredocs of `install.ps1` (Copilot master, `AGENTS.md`, `CONVENTIONS.md`) and so in their regenerated mirrors; `docs/manual/04-skills.md` and `docs/authoring-and-mirrors.md`.

**Proven:** `test_skill_first_rule.py`, 13 tests at this point (superseded; grew to 19 across the entries below), with negative controls for the region finder and the phrase finder. It proves the rule is written in each place, not that a model obeys it.

**Not done:** `local-writer.md` sits close to the Copilot mirror ceiling (`test_agent_mirror_ceiling.py`), so the rule was not added to any agent body; agents receive it through the CLAUDE.md files and the three master mirrors.

**2026-10-02 renumbering (069641f):** PR #40 (`feat/privacy-guard-v2`) forked `main` at the same R0-R32 ceiling and independently claimed R34 (fixtures never carry a real identity) and R35 (security gate before a PR); #40 merged first with CI green. This rule moves from R34 to R36 across every source file, the three `install.ps1` heredocs, the test, and the rule index, since #40 was further along and cheaper to leave untouched. No functional change.

**2026-10-06 correction plan review:** the plan flagged the R34 collision (fixed above by renumbering), the "ask vs author" order for a missing skill left undefined, "task" having no exemption list (`local-coder.md` carries the `Skill` tool but is not required to invoke it on a non-skill task), the plugin ban in `.claude/rules/security.md` conflicting with the `skill-creator@claude-plugins-official` plugin the template itself enables, the installer-heredoc mirror lacking the same carve-out and fallback as `.claude/CLAUDE.md`, the exported region's repo-relative doc links breaking outside ResearchTools, the PR body's stale test count, and 4 Copilot review threads answered in-thread but left unresolved on GitHub. Rebased onto `main` after #40 and #52 merged; `install.ps1 -Profile engineering` regenerates every mirror from the corrected sources rather than hand-editing generated files.

**2026-10-06 fixes applied:** `workflows.md` R36 part 1 now says explicitly that a sub-step performed inside an already-selected skill or agent (a file the skill itself reads or writes, a command it runs) does not each need its own skill lookup - the rule binds the top-level task selection, which is what settles `local-coder.md`'s `Skill` tool sitting unused on a given run. Part 3 now cross-references the "ask the user first" step of "Improving ResearchTools from another folder" for a repo-wide tooling gap with no clear owner, so authoring a brand-new skill is not a silent default. The three `install.ps1` heredocs carry the same plugin carve-out and portable-fallback language as `.claude/CLAUDE.md` and `workflows.md`, instead of the bare "never install" line. The two prose mentions of `docs/authoring-and-mirrors.md` and `.claude/rules/workflows.md` inside the RT-EXPORT region are now qualified "ResearchTools' own", since that region is read from `~/.claude/CLAUDE.md` in every project on the machine, not only this one. `install.ps1 -Profile engineering` re-run after each fix; full offline suite 104/104 (1 not-run, pyhanko, pre-existing).

**Doc scope (R33), corrected 2026-10-07:** the original wording of this line claimed the MkDocs manual needed no update, which was wrong even at the time it was written - `docs/manual/04-skills.md` is part of that manual and was touched in the same 2026-10-02 commit. The accurate scope: no new skill, agent, or command is exposed to the user, so `README.md`'s skill/agent/command inventory table needs no new row; the manual's existing skills chapter (`docs/manual/04-skills.md`) was updated instead, since the rule changes how every skill-dispatch decision is made. The convention itself is documented in `.claude/rules/workflows.md`, `.claude/CLAUDE.md`, and the three `install.ps1` mirrors, per R31's own table.

**2026-10-07 re-review fixes (B1-B3):** a second full re-review at head `57e6d15` verified the 2026-10-06 fixes against the diff itself and found three remaining mechanical gaps. **B1:** the three `install.ps1` heredocs and `docs/authoring-and-mirrors.md` carried the plugin carve-out and portable fallback but not the ask-first gate for an entirely new skill, so a Copilot/Aider/Codex session reading only the mirror would author one with no `AskUserQuestion`; fixed, and `MIRROR_PHRASES` now asserts the literal "ask first too" clause so a dropped gate fails the suite instead of passing silently. **B2:** the PR title still said "R34:"; fixed via `gh pr edit --title`. **B3:** the routing-table row in `.claude/CLAUDE.md` said "ask ... when it is ambiguous, otherwise author the missing skill", contradicting part 3's own "ask first" for a genuine no-owner gap; fixed, plus a new test (`test_no_file_lets_the_row_skip_the_ask_gate`, with its own negative control) asserting the exact contradicting phrase never reappears in any file the rule is stated in. The remaining unqualified repo-relative mentions B3 named (`docs/authoring-and-mirrors.md` section 7, `.claude/settings.template.json`, `.claude/rules/security.md`, the fallback's "repository's own") are now all qualified by project rather than assumed to be ResearchTools.

**2026-10-07 operator correction on Q1/Q2/Q3:** three follow-up `AskUserQuestion` rounds on the re-review's open questions were rejected as unclear (jargon "floor", a premise about aider-night that does not apply, restating R36's own intent back at the question). Plain-language result, confirmed in chat rather than via the tool: R36's real intent is self-improvement with no copy-paste - find something similar with `find-skills`, build a new skill from it, build the skill BEFORE doing the task; part 3 already said this and needed no change. R36 does not reach headless/unattended runs with no `AskUserQuestion` capability (aider-setup's nightly pipeline named explicitly as the example) - stated as an exemption rather than left to be inferred. "Task" is redefined as the piece of work the session is asked to do, not each individual file read/write/command inside it, closing the literal-reading gap where a bare `git status` looked like it needed its own skill lookup; `local-coder`'s reads and writes are explicitly named as part of doing its one task rather than separate tasks. Part 4's "never install ad hoc" stays prose-only, no new hook - confirmed rather than re-opened, since no violation has been reported. A new test (`test_task_is_the_unit_of_work_not_each_tool_call`) pins the aider exemption and the "no human in the loop" phrasing across all four files it is stated in, normalizing hard-wrapped line breaks before the substring check since the raw text split the phrase across a line twice while editing it. Full offline suite 104/104 after each round (1 not-run, pyhanko, pre-existing).

**2026-10-07 third re-review, N1-N4 fixed with the operator's own O1/O2 answers:** a third re-review at head `03e3b15` found the headless exemption (2026-10-07's own fix) contradicted part 2's "stop" clause (**N1**, High), left the Tooling-table reference unqualified for a non-ResearchTools reader (**N2**), the `testing.md` inventory line stale at "13 tests" against the real 16 (**N3**), and `docs/manual/04-skills.md` restating the rule without either the headless exemption or the ask-first gate (**N4**). The operator answered the review's two open questions directly in a PR comment rather than through `AskUserQuestion`: **O1**, a single-step request with no deliverable (reading one file, `git status`) never triggers the ask-first question - written as a "Floor:" sentence everywhere the rule is stated; **O2**, a subagent or scheduled run that cannot ask but is not fully headless logs `OWNER UNKNOWN` and continues, per "Improving ResearchTools from another folder" step 1, rather than stopping - this closes N1 by replacing part 2's "stop" clause with the same fallback part 3 already used. Also fixed from the review's adversarial pass: part 3's authoring step now says explicitly "inside ResearchTools, never inside the project the task is for", closing the implied loophole where a non-ResearchTools session's fallback search read as writing the `SKILL.md` into that project; part 4 and `security.md` are now stated to bind even a harness otherwise exempt; and `find-skills`'s `vercel-labs/skills` provenance (2026-07-27, via the skills CLI) moved from `workflows.md` part 4 to this log, since a machine-local `~/.agents/.skill-lock.json` path is not something another clone can verify. `docs/manual/04-skills.md` updated to state the floor, the headless exemption, and the ask-first gate in the same words as the rule's own text. `testing.md`'s inventory line rewritten to the current 16-test coverage.

**2026-10-07 fourth re-review, B1/B2 fixed and M1/L6 decided by the operator:** a fourth re-review at head `4616038` found two real blockers and six non-blocking findings. **B1** (Medium): the part-3 fallback for a harness without `skill-creator` said "do not stop" unconditionally, which collided with the 8-step protocol it cites in the same sentence - that protocol's own step 2 says a fresh clone with no `.rt-green.json` must be reported and must not be built on. Fixed: the green-stamp check now governs authoring regardless of tool availability, and "do not stop over the missing tool" applies only once that check has already passed. **B2** (Medium, R31/R33): `IMPROVEMENTS.md` itself contradicted the PR in three places - the 2026-10-02 entry's section title still said R34 (annotated with a forward pointer to the renumbering entry rather than rewritten, preserving what that entry's commit actually produced at the time), its test count was stale at 13 (annotated as superseded), and its R33 doc-scope line claimed the MkDocs manual needed no update when `docs/manual/04-skills.md` - part of that manual - was touched in the very same commit (corrected: only `README.md`'s inventory table needed no new row). The PR body's own definition of "task" was also out of step with the Floor sentence; updated.

The operator decided the two open questions directly in PR comments rather than through `AskUserQuestion`. **M1** (exemption wording): "Wording A" (`no AskUserQuestion capability at all`) everywhere, retiring "no human in the loop" - closes the risk that a tool-less-but-human-present harness (Aider chat) and a capability-less subagent were being judged by two drifting tests. **L6** (does part 4 forbid an explicit user-requested install): no - the ban is purpose-gated to covering a missing skill ad hoc; an explicit request is honored, but the skill is installed outside ResearchTools, never added to the repository, its mirrors, or its junctions.

Non-blocking findings also closed: **M2**, the Floor sentence's wording had drifted into two families ("never triggers steps 2 or 3" vs "no skill lookup") with an undefined "deliverable of its own" - unified to one phrase and one pair of examples everywhere. **M3**, the test suite could not see the floor/exemption/fallback in `CLAUDE.template.md`, the three generated mirrors, or `security.md`, and two negative controls asserted a bare Python `in` on a literal instead of exercising the real file-reading path - both fixed, plus a new `flat_section`/`flat_section_text` helper that narrows the check to the R36 section specifically in the two files that also carry the unrelated "Improving ResearchTools" protocol section (so deleting a phrase from the rule and leaving it in that other section now correctly fails). **L1-L5**: the remaining unqualified `security.md`/`workflows.md` mentions qualified "ResearchTools' own"; the mirrors' "Improving ResearchTools from another folder" reference now names the file it lives in; the mirrors now carry the "cloud model only, Claude Code" sentence `workflows.md` had kept to itself; `security.md`'s stray-bullet Markdown rendering fixed by moving the ordinary-dependency-install carve-out into its own sentence; `OWNER UNKNOWN` logging now says "ResearchTools' own `IMPROVEMENTS.md`" rather than a bare filename. Test count: 19 -> 26. Full offline suite 104/104 (1 not-run: pyhanko, pre-existing, unrelated).

**2026-10-07 fifth re-review, a mutation check and F1 decided by the operator:** a fifth re-review at head `5286bd0` ran the suite under `python -I`, confirmed every prior fix against the repository text, and then mutated 22 key phrases one at a time across the 17 non-test files (about 205 file/phrase pairs) to measure what the suite could actually detect - 72 mutations caught, 133 missed, several of which mattered. **F1** (Medium, owner decision): Wording A's "no `AskUserQuestion` capability at all" left open whether "capability" meant the literal tool or the ability to ask in chat; since `.claude/CLAUDE.md` and `workflows.md` list Codex and Copilot as bound harnesses while neither exposes an `AskUserQuestion` tool, a literal reading would have silently exempted them. The operator's answer: capability means any way to ask the user, in chat or through the tool, so a harness with no such tool but a human present is still bound. Written as a clarifying clause beside the exemption sentence in every copy, with a new test (`test_capability_means_chat_or_tool_not_the_tool_alone`) pinning both the clause and the phrase "are bound, not exempt".

The mutation check's other findings, all closed the same round: **F2** (subagent wording drift - the mirrors said "an interactive subagent" where the source files said "a subagent or a scheduled run"; unified). **F3** (the two "strengthened" negative controls from the fourth round still called `path.read_text()` directly rather than the suite's own `read()`; rewritten to redirect the module-level `REPO` constant at a scratch directory and call `read()` itself, so they exercise the identical file-reading path the production checks use). **F4** (the Floor sentence's own sub-phrases - "single-step request", "deliverable of its own" - and the authoring-location negative and "latest cloud model" were nowhere pinned, so any of them could be deleted or reworded without a failure; all four now asserted in every copy, including `CLAUDE.template.md` and the three mirrors, closing the one genuine gap the check found there - `docs/manual/04-skills.md`'s condensed authoring sentence never said "latest cloud" at all, which the new test caught immediately). **F5** (a loophole in the L6 exception: nothing said an "explicit user request" had to come from the user's own message rather than a tool result, a README, or a subagent's report parroting one - exactly the injection vector `security.md`'s own prompt-injection paragraph already names elsewhere in the same file; closed with one clause in every copy plus `security.md`, and a test). **F6** (nit, not a defect): `IMPROVEMENTS.md`'s "grew to 19" line was correct for the entry it sits in, part of a dated chain rather than a single current figure.

3 new tests. Test count: 26 -> 29. Full offline suite 104/104 (1 not-run: pyhanko, pre-existing, unrelated). All 4 Copilot review threads resolved.

## 2026-10-01 - obsidian-cli / loop-engineer - the vault daemon did not survive a reboot or a slow Ollama

**Change:** `vault_lock.py` records the holder's process start marker (`process_start_marker`) in the lock and reclaims a live pid whose marker differs (pid reused after a reboot); `ollama_bridge.resolve_model` wraps `ResolverError` into `BridgeError`, and `vault_daemon.context_window` wraps `ContextBudgetError` into `BridgeError`, so `run_forever` keeps polling when Ollama is not up yet.

**Found:** `~/.claude/vault-daemon.log` against the Windows boot log: on 2026-09-29 the login daemon refused to start behind its own stale singleton lock (no daemon all day, three voice questions expired after 22 h), and 11 earlier deaths were `ResolverError: 'ollama list' exited 1 ... connection refused`.

**Proven:** `test_vault_lock.py` 16 -> 23, `test_vault_daemon.py` 14 -> 18, `test_ollama_bridge.py` 33 -> 36, each regression watched failing first; full offline suite green. Known gap at this point: a pid reused by a process this user cannot query, or a lock written before this change, is still read as the holder - see the 2026-10-07 entries below for what of this was later closed.

## 2026-10-07 - obsidian-cli - PR #42 review round 1: a legacy lock was not reboot-safe

**Change:** one High fixed - "a lock written before this change is still read as the holder" (2026-10-01, above) reproduced #41 on the first full restart after that fix shipped, since a legacy lock has no `started` marker to compare. `vault_lock._boot_time_utc()` (GetTickCount64 on Windows, `/proc/uptime` on Linux) now reclaims a same-host lock whose own `at` timestamp predates the current boot, independent of `started`, closing that gap for a full restart; the pid-reused-by-an-unqueryable-process gap remains, stated as a cost rather than fixed. Two Low findings fixed: `process_start_marker`'s bare `except Exception` narrowed to `(OSError, ValueError, IndexError, AttributeError)`, and `--once`/`--drain` now catch `ob.BridgeError` and exit 2 instead of a bare traceback on an unreachable Ollama, matching `run_forever`'s own refusal for the identical failure (R12). One Medium fixed: `vault_daemon._log_bridge_error` caps an unchanging failure message to once per `bridge_error_log_interval_s` (300s, chosen) rather than once per 5s poll pass, since an extended outage could otherwise grow the log unbounded between daemon restarts - the autostart script only rotates it at the NEXT start, and this PR's whole point is a daemon that keeps running through the outage rather than dying and triggering that rotation.

**Found:** review of PR #42 against the 2026-10-01 entry above.

**Proven:** `ollama_bridge.resolve_model` wraps only `model_resolver.ResolverError`, verified rather than changed - reading `model_resolver.py` confirms every raise reachable from `resolve()` (the subprocess call in `_ollama_list_raw`, every JSON load) is already converted to `ResolverError` at its own boundary. Two Medium declined with reasons: no restart supervisor for a crash outside the two named failure modes (this PR's scope is #41's two diagnosed causes, not general process supervision), and the Copilot `testing.instructions.md` mirror regenerated via `install.ps1 -Profile engineering` rather than hand-edited. `test_vault_lock.py` 23 -> 29, `test_vault_daemon.py` 18 -> 22, each regression watched failing first; full offline suite green.

## 2026-10-07 - obsidian-cli - PR #42 review round 2: a real bug, an owner-decided margin, and a stated Fast Startup limit

**Change:** M1 (Medium) - the boot check assumes a boot resets the tick counter, which a Windows Fast Startup "shut down then power on" does not: it hibernates the kernel session rather than rebooting it, so `GetTickCount64` keeps counting from the ORIGINAL boot. The owner confirmed Fast Startup is enabled on the daemon machine. Declared a stated limit rather than coded around: a legacy lock (no `started`) survives that specific shutdown path even after round 1's fix; a new lock always carries `started` and is unaffected. Mitigation, confirmed by the owner: restart the vault daemon once after this fix lands, so every lock it holds afterward is reboot-safe whichever way the machine is powered off. Docstrings in `vault_lock.py` corrected from "reboot-safe on the first reboot" to say "full restart" and name the Fast Startup limit explicitly. M2 (Medium, owner-decided "add the margin") - the boot check compares two wall-clock-derived times (a lock's `at`, and `now` minus system uptime); a clock step forward after the daemon wrote its lock (an NTP correction shortly after boot, no RTC, a manual set) could make the computed boot land after a genuinely live daemon's `at`, reclaiming it and letting a second daemon start on the same outbox - reproduced by the reviewer. Fixed: `lock.boot_skew_tolerance_s` (300s, `daemon-config.json`); a lock counts as reused only when its `at` predates boot by MORE than the margin. L1 (Low, a real bug, reproduced live by the reviewer) - a lock's `at` with no UTC offset (hand-edited or foreign-shaped) raised `TypeError: can't compare offset-naive and offset-aware datetimes` out of the comparison itself, escaping `acquire()` and `held_by_live_holder` (which the flush hook calls, R11). Fixed: a naive stamp is now treated as UTC, and the comparison sits inside the existing try/except so any other shape degrades instead of raising. L2 (Low, declined) - an unreadable boot time returns `None` silently with no log line; declined because `vault_lock.py` is a pure library with zero logging calls anywhere in it by design (every other degrade - an unreadable marker, a malformed lock - is equally silent). L3 (Low, acknowledged, not fixed) - whether suspend/sleep is excluded from `GetTickCount64`/`/proc/uptime` uptime is genuinely unverified by either review pass and would need a live measurement across a real sleep cycle; left as a stated open question rather than guessed at (R4/R13: no unmeasured claim). L4 (Low) - the Copilot `testing.instructions.md` thread, marked outdated after round 1's mirror regeneration, resolved on the PR. L5 (Low) - the 2026-10-01 entry's "Known gap" sentence and round 1's "FIRST reboot" wording corrected (this restructuring).

**Found:** second review pass of PR #42, plus 26 one-at-a-time mutations against the three target suites (21 caught, 5 survived).

**Proven:** mutation-testing gaps closed with new tests - the throttle re-logging an unchanged message once the interval actually elapses (round 1 only proved the "suppressed within the interval" half), `_boot_time_utc`'s narrowed except on a forced Windows API failure and a malformed `/proc/uptime`, `process_start_marker`'s narrowed except on a forced Windows API failure, and `--drain` catching `ds.EventRefused` (round 1's test only forced `ob.BridgeError`). `test_vault_lock.py` 29 -> 36, `test_vault_daemon.py` 22 -> 24; full offline suite green.

## 2026-10-07 - obsidian-cli / rt-observe - PR #42 review round 3: the margin reached only two of seven real callers

**Change:** M-A (Medium) - "wired into every real lock call site" (round 2, above) was false: `lock.boot_skew_tolerance_s` reached `daemon_outbox.py`'s two locks and `collect_services.py`'s dashboard read, but FIVE real callers still defaulted to 0 - both `obsidian-outbox-flush.py` call sites, `vault_daemon_e2e.py`, and the inline Python in `run-drill.ps1` and `vault-daemon-autostart.ps1`. All EIGHT real call sites in the repository now pass the configured margin (round 3 undercounted this as seven, treating the hook's two sites as one); the hook's two sites already sat inside an existing `except outbox_io.ConfigError` that degrades silently (R11), so no new error handling was needed there. M-B (Medium) - no test read back the actual argument reaching `held_by_live_holder`/`VaultLock`, only the True/False result, so the wiring itself (not merely its presence) was unproven; fixed with tests that construct the daemon/collector through its REAL config path with a distinctive margin value and assert it reached the lock object or the fake `held_by_live_holder`'s own recorded call. M-C (Medium) - the margin bounds a forward clock step to 300s; a larger one (no RTC, a dead CMOS battery, a manual set further off) still reclaims a live daemon's lock. Named explicitly in `daemon-config.json`'s provenance rather than left implicit. L-A (Low) - this file's dated headings restructured so each entry's own "Proven" line states the counts true at THAT point, rather than one 2026-10-01 heading silently accumulating material through 2026-10-07. L-B (Low) - a missing `lock.boot_skew_tolerance_s` raised `outbox_io.ConfigError` as a bare traceback inside `run_forever`'s singleton-lock acquisition, with no handler for it; every required config key is now read BEFORE anything is acquired, and a missing one is a stated exit-2 refusal (R12), so a stale config also never leaves an orphaned lock behind. L-C (Low) - added tests pinning the EXACT margin boundary in both directions (a lock exactly 300s before boot survives, one 301s before is reclaimed), since the strict `<` comparison's edge was previously unproven. L-D (the stated limits from round 2, L2/L3) and L-E (CI state unreadable from the review session) are accepted as-is, not code findings.

**Found:** third review pass of PR #42, naming the five un-wired call sites by file and line, plus one mutation (S1) that survived because no test exercised the real wiring path.

**Proven:** `test_daemon_queue.py` 12 -> 15 (the write lock and singleton lock each carry the configured margin; a missing key is a named `ConfigError`), `test_rt_collectors.py` 42 -> 43 (the dashboard's liveness read carries it, proven via a spy `held_by_live_holder` that records its own call), `test_vault_lock.py` 36 -> 38 (the exact boundary, both directions), `test_vault_daemon.py` 24 -> 25 (`run_forever` exits 2 on a missing config key, with no lock left acquired); full offline suite green.

## 2026-10-07 - obsidian-cli / rt-observe - PR #42 review round 4: the margin reached 3 of 8 call sites, and one existing test was coincidentally blind

**Change:** M-A (Medium, count correction) - round 3 said "every real call site" and counted seven; the actual count is EIGHT (`obsidian-outbox-flush.py` has two, not one, which round 3's own fix list undercounted). M-B (Medium) - five of those eight still had no test proving they received the margin at all (the hook's two sites, `vault_daemon_e2e.py`, and the two PowerShell call sites): fixed for the hook's two sites with the same real-config-path pattern used for `daemon_outbox.py` and the dashboard; `vault_daemon_e2e.py`'s `check_lock` is accepted as out of scope, since every step function in that script is untestable offline by the script's own design (it mutates a REAL vault against a REAL daemon, the one script in this skill a session must not run - only the harness around the steps is unit-tested); the two PowerShell call sites (`run-drill.ps1`, `vault-daemon-autostart.ps1`) are accepted as the reviewer's own stated limit, inline Python inside a here-string with no offline harness to drive it. `collect_services.py`'s own `config_values.get("lock_boot_skew_tolerance_s", 0.0)` was ALSO a real gap - a silent 0.0 default on a missing key is the exact failure class the margin exists to prevent - fixed to a required key (R8), with a test proving a missing key is a named `KeyError` rather than a silently wrong 0. One Low (a real test-quality bug, not just a gap): the throttle re-log test's fake clock started at 0.0, which coincided with `_last_bridge_error`'s own uninitialized default, so dropping the `last["at"] = now` update was invisible to it - reproduced by actually applying that mutation locally and watching the test still pass; fixed by starting the clock at 1000.0, which the same mutation now fails correctly. Four more narrow-except survivors closed: `process_start_marker`'s ValueError (a non-numeric `/proc/<pid>/stat` field) and AttributeError (a ctypes binding gap) paths, and `_boot_time_utc`'s IndexError (an empty `/proc/uptime`) and OSError (an unreadable one, proven only on the Windows path before this round) paths.

**Found:** fourth review pass of PR #42, naming the undercount, the five still-unwired sites, and five mutation survivors by exact line.

**Proven:** `test_vault_lock.py` 38 -> 42, `test_vault_daemon.py`'s throttle test rewritten (count unchanged at 25, assertion strengthened), `test_obsidian_outbox_flush.py` 21 -> 24, `test_rt_collectors.py` 43 -> 44; full offline suite green.

## 2026-10-07 - obsidian-cli / rt-observe - PR #49 re-review round 2: H3 (a repo: vault property had no allowlist), M3, L2, M6, L4, M8 partial

**Change:** merged `main` into `feat/voice-graph-lookup` (7 real conflicts, all content-level: `security.md`, `testing.md`, `daemon-config.json`, `_daemon_fixtures.py`, `test_vault_daemon.py`, both `.github/instructions` mirrors, `IMPROVEMENTS.md` - every one resolved by keeping both sides' additions, regenerating the two mirrors, and merging `test_vault_daemon.py`'s two independent test classes). **H3** (High, R24): `daemon_graph._resolve_repo_claim` checked only absolute/exists/has-a-graph.json, so any vault note's `repo:` property - untrusted input, writable by any local process able to touch the outbox or a future consolidation/phantom-repair edit - could point `graphify query`'s subprocess `cwd` at an arbitrary directory. Fixed with `load_allowed_roots()`, reading a machine-local, gitignored `.claude/local-ask-graph-roots.json` (`{"allowed_roots": [...]}`); absent, unparsable, non-object, or non-list-valued degrades to an empty allowlist (fail CLOSED, R8), never fail-open. The allowlist's location (env var vs gitignored file vs deriving one from the vault itself) was a genuine open design question; the operator chose the gitignored file, since the mapped repos sit under the operator's own account directory and the alternative (baking literal paths into `daemon-config.json`, which is tracked) would leak the account path (R34). **M3** (privacy): a graph-part refusal reason can embed an absolute repo path, and the answer is served to a browser; promoted `rt_openobserve.py`'s private `_redact` into a shared `rt_redact.redact_json` (R18, now two callers) and wired it into `rt_state.answer_fn` before the answer leaves the process. **L2**: `rt_state.py`'s `_ANSWER_ID.match()` used a pattern ending in `$`, which matches just before a trailing newline as well as end-of-string, so a valid 16-hex id plus `\n` passed; changed to `.fullmatch()`. **L4**: `observe-config.json`'s `voice_ask_wait.unit` still described the retired blocking semantics (`POST /api/voice/ask` has returned 202 at once since 2026-10-02); corrected to describe what it actually bounds, the voice panel's own poll loop. **M6**: `testing.md` gained the missing `test_outbox_io.py` line (it never had one) and the `test_vault_daemon.py` / `test_daemon_graph.py` / `test_daemon_ask.py` counts are now current. **M8** (partial): added a round-trip test proving a value starting with `#` or `:` is still read back verbatim by this module's own regex reader, a presentation note against a real YAML engine rather than a vulnerability; CRLF-in-body and read-only-target paths are left to the existing generic `except (OSError, FrontmatterError)` in `flush_one` rather than independently tested.

**Declined, with reasons recorded in the PR:** **L3** - the literal `"10_Projets"` in `daemon_ask._entity_folder` encodes the PARA convention's own structural distinction (which vault folder nests one level deeper), closer to R0's domain-constant carve-out than to a tunable value; left as is. **L8** (R14) - `query_graph`'s argv order was flagged as possibly fooling an argparse-based CLI with a leading-dash keyword, but reordering to add a `--` separator cannot be verified against the real `graphify` CLI, which is not installed in this sandbox either; guessing a reorder risks breaking the one thing that currently works, so it is left as a stated, unverified risk rather than a blind fix. **M4/Q3** (residual ask-queue access path) and **M7** (an unrelated `CLAUDE.template.md` section, now moot after the `main` merge folded it in as part of `main`'s own content) remain operator decisions, not code fixes.

**Found:** a second re-review (after the first PR #49 Copilot-finding round already closed) that merged `main` first, then re-verified every earlier fix against the merged head, and found H3 still open plus the items above.

**Proven:** `test_daemon_graph.py` 23 -> 34 (11 new: `load_allowed_roots`'s four degrade-to-empty cases, the allowlist membership check in both directions including a `..` escape past an allowlisted root proving resolve()-then-equality beats a naive startswith(), and the omitted-argument default actually calling the real loader), `test_daemon_ask.py` 50 -> 51 (the full `answer()` path, not only the unit test, refuses a repo outside the allowlist), `test_outbox_io.py` 14 -> 15, `test_rt_state.py` 82 -> 89 (the trailing-newline id regression plus a redaction regression proving a home-rooted path is rewritten to `~` in a served answer), `test_rt_openobserve.py` unchanged at 16 after the `_redact` promotion. Full offline suite 106 passed / 0 failed / 1 not run (pyhanko, pre-existing, unrelated) after every change in this round.

## 2026-10-07 - obsidian-cli / rt-observe - PR #49 re-review round 3: F1 (redaction broken by repr on Windows), a cross-platform test failure, three mutation survivors, F2/L6 (poll loop), L8 (leading-dash guard)

**Change:** **F1** (blocker, Medium-High): `daemon_graph._resolve_repo_claim`'s four refusal reasons interpolated the raw `repo:` value with `{value!r}`. On Windows, `repr()` of a path string doubles every backslash in the rendered text, so `rt_redact.home_tilde`'s plain substring replace of the single-backslash home prefix never matched - the account path survived "redaction" and reached the browser via `GET /api/voice/answer`, exactly the M3 leak the previous round believed it had closed. Changed all four to plain `'{value}'` (no repr). **Cross-platform test fix**: `test_a_repo_pointing_nowhere_names_the_reason` built a literal `C:\does\not\exist\anywhere` string, which is not absolute under POSIX pathlib semantics, so the reviewer's Linux sandbox hit "is not absolute" instead of "does not exist"; rebuilt from `tempfile.mkdtemp()` plus a never-created child name, which is absolute and nonexistent on every platform (R21 spirit). **Mutation survivors closed**: S1 (a sibling directory sharing a string prefix, e.g. `<repo>` vs `<repo>-evil`, is refused - proves resolved EQUALITY is used, not `startswith`), S2 (a trailing-`.` spelling of an allowed root still resolves and is accepted - proves the CLAIM is resolved, not compared raw), S3 (same, for an allowlist entry itself spelled with a trailing `.` - proves `load_allowed_roots` resolves its own entries). **F2** (Medium, page poll loop, `rt_state.html`): `setInterval` fired a new `fetch` every tick with no guard against the previous one still being outstanding, so a response slower than the poll cadence could arrive out of order; and a late response from a SUPERSEDED poll (a new question already started) could still append stale text or queue stale speech, since `stopAnswerPoll()` clears the timer but cannot abort an in-flight fetch. Fixed with a `fetchInFlight` boolean (checked at the top of the interval callback) and an `answerPollGeneration` counter captured per-call and checked in both the success and error handlers. **L6** (bundled with F2): a new question now calls `speechSynthesis.cancel()` before polling, so it replaces rather than queues behind the previous answer's speech. **L8** (revisited): rather than guess at adding a `--` argv separator - still unverifiable without the real `graphify` CLI installed - `query_graph` now refuses any keyword beginning with `-` before the join; cheap, and needs no knowledge of the CLI's own argument parsing. **F6** (Low-Medium, M6): `rt-observe/SKILL.md`'s voice section gained the two-part progressive answer, the 202/poll contract, and the allowlist gate - it previously only described the push-to-talk/STT half, predating this feature.

**Operator decisions on the three remaining findings**: **F3** (Medium, concurrency - no cap on pending ask requests, no sweep for orphaned answer files) tracked as issue #58 (added to the ResearchTools Roadmap board) rather than scoped into this PR. **F4/Q3** (Medium, the ask queue's `from:` field is a routing label not access control) accepted as documented, consistent with the outbox's existing single-user trust model. **F5/M7** (the unrelated `CLAUDE.template.md` commit 9244182, confirmed absent from `main` by `git show origin/main:CLAUDE.template.md`) kept bundled in this PR rather than split into its own.

**Found:** a third re-review (head e72ddfa) that verified H3 sound, then ran a mutation check against the round-2 allowlist tests and found the real F1 bug plus the three survivors.

**Proven:** `test_daemon_graph.py` 34 -> 40 (F1 regression, S1-S3, the leading-dash guard and its mixed-keywords case), `test_rt_view.py` 76 -> 79 (the in-flight guard, the generation-discard check in both handlers, the speech-cancel-on-new-question check). Full offline suite 106 passed / 0 failed / 1 not run (pyhanko, pre-existing, unrelated).

## 2026-10-08 - obsidian-cli / rt-observe - PR #49 re-review round 4: two of round 3's own "closed" claims did not hold, plus two stale documents and a cheap page fix

**Change:** **B1** (Low-Medium, the F1 regression test itself was not portable): `test_the_refusal_reason_names_the_path_plainly_not_via_repr` asserted `assertNotIn(repr(str(path)), reason)`, which is a no-op on POSIX - a backslash-free path's `repr()` equals its own plain quoted form, so the assertion could never tell `!r` apart from a plain `{value}` there, and would have passed identically with the bug still in the code. Rewritten to embed a LITERAL backslash character in the claim and assert the single-backslash form is present while the repr-doubled form is explicitly absent - this depends only on Python's own `repr()` semantics, which double a backslash on every platform, never on which OS runs the suite. **B2** (Medium, S2/S3 were not actually closed): both tests used `self.repo / "."`, but `pathlib` COLLAPSES a trailing `.` segment the moment the `Path` object is constructed (`str(repo / ".") == str(repo)` already, before `resolve()` is ever called), so both tests passed whether or not `resolve()` ran on the claim or on a `load_allowed_roots()` entry - confirmed by manually mutating each `resolve()` call out and watching both tests still pass. Rewritten as a `..` segment through a directory that is NEVER created, which is NOT collapsed at construction time and is only normalised by `resolve()`'s own lexical collapsing (no intermediate needs to exist on disk) - re-verified by the same manual mutation: both now fail when either `resolve()` call is removed, and pass when it is restored. **B3** (Low-Medium, R23/R31): `testing.md`'s inventory counts for `test_daemon_graph.py` (34, now 40), `test_rt_state.py` (82, now 89), `test_rt_view.py` (76, now 79) and `test_voice_ask.py` (10, now 11) had not been updated across the three prior rounds despite each round's own commit message and IMPROVEMENTS.md entry claiming otherwise - fixed, and the two `.github/instructions` mirrors regenerated. Separately, the F4/Q3 accepted-risk decision (round 2) was never written into `security.md` itself, only into a PR reply and `daemon_ask.py`'s own docstring - added two paragraphs to the "A second reader" section: the ask-queue's `from:` field is a routing label and not access control (an explicit statement a future reader of the rules file can find without re-deriving it from the diff), and the allowlist's EQUALITY semantics (a `repo:` value must name an allowlisted root exactly, not a subdirectory of one). **L5/F8** (Low, a one-line fix the review named directly): `GET /api/voice/answer`'s 501 response (no ask relay installed) carries `status: "unavailable"`, which was missing from the page's `ANSWER_TERMINAL` table - the poll loop ran the full `voice_ask_wait` (85s) on a condition that will never resolve instead of stopping at once. Added `unavailable: 1`.

**Found:** a fourth re-review (head ae8b70b) that re-ran the round-3 mutation checks and found S2/S3 both survived identically to before (same root cause the F1 test itself had: `pathlib` normalises `.` before any code runs), reproduced the F1 test's own POSIX no-op, and diffed `testing.md`'s counts against the actual suites.

**Proven:** `test_daemon_graph.py` unchanged at 40 (two tests REPLACED with genuinely-discriminating versions, not added - counts stay the same but the assertions now actually exercise what they claim to), both confirmed to fail under the named mutation and pass once restored (manual one-at-a-time mutation, not merely reasoned about). `test_rt_view.py` 79 -> 80 (the `unavailable`-is-terminal check). Full offline suite 106 passed / 0 failed / 1 not run (pyhanko, pre-existing, unrelated).

## 2026-10-08 - rt-observe - PR #49 re-review round 5: the documented count for test_rt_view.py drifted again within the SAME commit that fixed it, plus a self-reported mutation survivor

**Change:** `testing.md`'s `test_rt_view.py` line said 79 while the round-4 commit that landed the `unavailable`-is-terminal test had already brought the real count to 80 - the L5/F8 test was added to the file AFTER the count comment was last written in that round, so the count comment itself never caught up within its own commit. Fixed to the true count. Closed the one gap the reviewer named as non-blocking but worth doing: the new `unavailable`-is-terminal test only asserted `unavailable`'s presence, so MUTATING OUT `ok` (or any of the other three statuses `daemon_ask`/`voice_ask` actually publish) survived every test in the suite - the page would silently stop recognising a normal completed answer as terminal and poll the full 85s wait for nothing on an ordinary successful question. Added a second test asserting all five real terminal statuses (`voice_ask.TERMINAL_STATUSES` - ok/error/expired/refused - plus the page's own client-side `unavailable`) stay in `ANSWER_TERMINAL`, confirmed by manually mutating `ok` back out and watching the new test (and only the new test) fail.

**Found:** a fifth re-review (head 6ffe326) that re-diffed every testing.md count against the real suites one more time and caught the self-inflicted drift, plus ran the mutation the previous round's own test left unguarded.

**Proven:** `test_rt_view.py` 80 -> 81; the `ok`-removal mutation now fails exactly the new test (confirmed by manual mutation, restored, confirmed green). Full offline suite 106 passed / 0 failed / 1 not run (pyhanko, pre-existing, unrelated).


## 2026-10-09 — `model_resolver.py` gains a manually-adoptable role; PR #61 review fixes (claude-switch.ps1)

**Owner:** `loop-engineer` skill (`model_resolver.py`) and the repo-wide `scripts/local/` home (`claude-switch.ps1`, no owning skill).

**Change:** The GitHub code review on PR #61 / Issue #60 found that `scripts/local/claude-switch.ps1` hardcoded its default Ollama tag (`qwen3.8-maxctx:latest`), violating R2 ("model_resolver.py is the only thing that names a tag"). `resolve(role)` was already role-agnostic (it reads `current_by_role[role]` for any string), but the only writer of that map required a `qualification/tasks.json` task of that `kind`, and no oracle exists for "is this a good interactive Claude Code session" the way one exists for `writer`/`coder` code/doc generation. Added `model_resolver.py --adopt-role ROLE TAG --reason "..."`, which writes `current_by_role[role]` directly with no qualification run, refusing a missing `--reason` (R4) or an uninstalled tag, and refusing to seed an empty state file from nothing. Declared a new `session` role in R5's enum text (`code-style.md`). Deliberately did NOT declare the tag in `local-models.json`: that file feeds `--matrix`, which checks every candidate against `local-model-config.json`'s GPU-residency sweep, and a CPU/RAM-thread-sweep-measured tag (`aider-thread-probe.py`) has no entry there and would print a false "NOT RUNNABLE".

The same review found three further real defects in `claude-switch.ps1`, all fixed: (1) `claude-cloud` never restored `ANTHROPIC_API_KEY` after `claude-ollama` deleted it - now snapshotted and genuinely restored; (2) the Ollama-reachability guard checked only that a port answered, not that the requested tag was actually installed - now cross-checked against `ollama list`; (3) the test's own `Clear-SwitchEnv` wiped the CALLER's real `ANTHROPIC_*` env vars with no restore - the test now snapshots and restores the real environment around the whole run. `testing.md`'s stale check counts (both the resolver suite and the switch-script suite) were corrected to match.

**Found:** GitHub code review on Issue #60 (two comments: a weekly review plan, then a `/code-review --level high` follow-up), triggered by the professor via the Claude GitHub App.

**Process note:** mid-fix, the `model_resolver.py` edits were mistakenly made in the shared main checkout instead of the `claude-switch` worktree (R32) - caught before committing, copied into the worktree, verified byte-identical, and the main checkout's uncommitted copy discarded. The gitignored `local-model-state.json` (where the real `--adopt-role session qwen3.8-maxctx:latest` adoption lives) was likewise copied into the worktree so the worktree's own test run reflects the real, adopted state rather than an empty one `git worktree add` does not populate.

**Proven:** `test_model_resolver.py` 39 -> 43 tests (4 new: adopt-role success/round-trip through `resolve()`, refuse-no-reason, refuse-uninstalled, refuse-no-incumbent-state), all green. `verify-claude-switch.ps1` rewritten, 15 -> 21 checks, all green, run from both the main checkout and the worktree. Full offline suite from the worktree: 106 passed / 0 failed / 1 not run (pyhanko, pre-existing, unrelated); `.rt-green.json` written. Mirrors regenerated (`install.ps1 -Profile engineering`). Real adoption verified end to end: `--adopt-role session qwen3.8-maxctx:latest --reason "..."` then `--resolve --role session` returns it, from both checkouts.
