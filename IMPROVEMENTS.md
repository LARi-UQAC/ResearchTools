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
