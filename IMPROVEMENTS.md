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

**Changed:** new section "Skill-first rule (R34)" inside the RT-EXPORT region, so it reaches `CLAUDE.template.md` (RT-CONTRACT block, regenerated) and the live global file at the next `-Sync`; a routing-table row for a task no skill covers; the rule in full in `workflows.md`; "Skill provenance" in `security.md`; the rule index in `code-style.md`; a statement of the rule in the three heredocs of `install.ps1` (Copilot master, `AGENTS.md`, `CONVENTIONS.md`) and so in their regenerated mirrors; `docs/manual/04-skills.md` and `docs/authoring-and-mirrors.md`.

**Proven:** `test_skill_first_rule.py`, with negative controls for the region finder and the phrase finder. It proves the rule is written in each place, not that a model obeys it.

**Not done:** `local-writer.md` sits close to the Copilot mirror ceiling (`test_agent_mirror_ceiling.py`), so the rule was not added to any agent body; agents receive it through the CLAUDE.md files and the three master mirrors.

**2026-10-02 renumbering (069641f):** PR #40 (`feat/privacy-guard-v2`) forked `main` at the same R0-R32 ceiling and independently claimed R34 (fixtures never carry a real identity) and R35 (security gate before a PR); #40 merged first with CI green. This rule moves from R34 to R36 across every source file, the three `install.ps1` heredocs, the test, and the rule index, since #40 was further along and cheaper to leave untouched. No functional change.

**2026-10-06 correction plan review:** the plan flagged the R34 collision (fixed above by renumbering), the "ask vs author" order for a missing skill left undefined, "task" having no exemption list (`local-coder.md` carries the `Skill` tool but is not required to invoke it on a non-skill task), the plugin ban in `.claude/rules/security.md` conflicting with the `skill-creator@claude-plugins-official` plugin the template itself enables, the installer-heredoc mirror lacking the same carve-out and fallback as `.claude/CLAUDE.md`, the exported region's repo-relative doc links breaking outside ResearchTools, the PR body's stale test count, and 4 Copilot review threads answered in-thread but left unresolved on GitHub. Rebased onto `main` after #40 and #52 merged; `install.ps1 -Profile engineering` regenerates every mirror from the corrected sources rather than hand-editing generated files.
