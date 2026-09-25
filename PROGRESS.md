# PROGRESS - rt-observe journal durable (identity + traces/audit)

plan: docs/superpowers/plans/done/2026-09-24-rt-observe-journal-durable-DONE.md

- context: executes the plan's five phases inside ResearchTools, in one session, no
  subagent, following the architecture sketch of
  `C:\Martin Otis\OutilsLogiciels\VibeDesignBook\plans\todo\chCC-Harnais.tex`. The
  non-negotiable constraint (plan section 3): rt-observe keeps working with neither
  PostgreSQL nor OpenObserve configured.

### Phase 1 - Persistence layer, optional by construction

- [x] Phase 1 - Persistence layer, optional by construction | evidence: `rt_store.py`
  added (`.claude/skills/rt-observe/scripts/`), the ONLY module importing `psycopg`,
  lazily; `NullStore`/`StoreError`/`StoreUnavailable` three-state split (undeclared
  block = disabled by design, declared-but-incomplete = R3 error, complete-but-
  unreachable = caught unavailable); `--migrate --dry-run` (default) / `--yes` (R16),
  JSON report (R17). `test_rt_store.py`, 15/15. Acceptance test
  `test_rt_persistence_invariant.py` (5/5) proves every pre-existing snapshot section
  builds identically whether or not an unrelated postgres/openobserve block is
  present, and that identity/traces report `unavailable` with a named reason when
  unconfigured - the meaningful reading of "sortie JSON identique a aujourd'hui"
  once ANY key is added (documented in the test's own docstring, since a literal
  forever-byte-identical string cannot survive that and every existing collector
  here - mcp, graph, services - already proves so by existing as a key regardless
  of harness presence).

### Phase 2 - Identity and per-user audit

- [x] Phase 2 - Identity and per-user audit | evidence: three tables in
  `rt_store.SCHEMA_STATEMENTS` (`rt_persons`, `rt_person_identifiers`,
  `rt_snapshot_history`); `rt_openobserve.py` added, the ONLY module knowing
  OpenObserve exists, stdlib-only (`urllib`); `rt_actions.py` gained an additive
  `remote_sink` (second sink for the audit log), with the JSONL fallback proven to
  survive a sink outage and a regression control proving every pre-2026-09-24 call
  site gets an unchanged payload (`test_rt_actions_remote.py`, 7/7). Redaction
  (`rt_redact.home_tilde`) applied BEFORE serialization, proven with an account-
  name-shaped string never reaching the bytes handed to the HTTP opener
  (`test_rt_openobserve.py`, 16/16).

### Phase 3 - Trace collector

- [x] Phase 3 - Trace collector | evidence: `collect_traces.py` added, same
  `probe`-less collector contract as every other section, bounded pagination
  (`caps.traces_page_size` / `traces_max_pages`, R10), explicit timeout
  (`timeouts_seconds.openobserve_search`), unavailable-with-reason on any failure,
  and deliberately no re-derived token total (owned by `collect_usage.py`).
  `test_collect_traces.py`, 4/4.

### Phase 4 - Panels

- [x] Phase 4 - Panels (reduced scope, stated rather than overclaimed) | evidence:
  a seventh rail tab "Journal" added to `assets/rt_state.html`
  (`renderJournalPanel`), reading the `identity` and `traces` sections - persons/
  identifiers/snapshots counts, and trace row/session/newest-event counts. The
  plan asked for two fuller views (a browsable per-person history, an execution
  feed replayed from the store in place of live transcripts); given the single-
  session, no-subagent, no-live-OpenObserve constraint, this session shipped the
  summary panel only and left the per-person drill-down as a follow-up, recorded
  below rather than claimed done. `test_rt_view.py` updated for the seventh tab
  (6->7 rail panels, two assertions fixed), 71/71.

### Phase 5 - Multi-sandbox aggregation

- [~] Phase 5 - Multi-sandbox aggregation | evidence: documentation-only by the
  plan's own design (one central OpenObserve, one server-side rt-observe, the
  mirror matrix staying per-clone) - written into `docs/rt-observe.md`'s new
  section and `Architecture.md`'s Layer 6. No code required beyond what Phases
  1-3 already ship, since a container's export target is a deployment fact, not a
  new collector. Not proven live: no second machine or container was available
  this session, so this phase is documented rather than exercised end to end.

### Phase 6 - Register and prove the whole repository

- [x] Phase 6 - Register and prove the whole repository | evidence:
  `.claude/rules/testing.md` (new script-surface bullet, 6 new test-invocation
  lines, `RT_PG_PASSWORD`/`RT_OO_USER`/`RT_OO_PASSWORD` in the env-var table, the
  two "six panels" mentions this session made stale, fixed); `README.md`,
  `Architecture.md`, `docs/rt-observe.md`, `.claude/skills/rt-observe/SKILL.md`,
  and the ResearchTools `.claude/CLAUDE.md` routing-table row (RT-EXPORT region)
  all updated. `IMPROVEMENTS.md` logged. OpenHands's `documented_not_built`
  registration in `harnesses.json`/`mirror-policy.json` was ALREADY present
  (done 2026-09-24 during the aider-kit integration this same day) - verified,
  nothing to add. Full rt-observe suite: 396/396 across 14 files, 0 failed.
  While proving the WHOLE repository suite: `run-offline-tests.ps1` crashed
  silently, deterministically, always right after `test_adapters.py`
  (alphabetically next: `.claude/skills/rt-observe/scripts/adapters/aider.py`'s
  own test). Root-caused by bisection to `_alive()`'s `os.kill(pid, 0)`, which
  on Windows is not a null-signal check - it maps to
  `GenerateConsoleCtrlEvent(CTRL_C_EVENT, ...)` and killed the PARENT
  PowerShell process under the runner's own `Start-Process -RedirectStandardError`
  invocation style. Not this plan's file, but it blocked this plan's own
  acceptance criterion ("Suite hors ligne passe en entier"), so fixed in place:
  `_alive_windows()` added, `test_aider_adapter.py` 22->24. Logged in
  `IMPROVEMENTS.md` and in `docs/superpowers/todo/2026-09-24-aider-kit-
  remaining-work.md` item 11, since that file is where that skill's own open
  items are tracked.

Full offline suite (whole repository, all 85 discovered suites): PASSED 84,
FAILED 0, NOT RUN 1 (`test_sign_form.py`, missing `pyhanko`, pre-existing,
unrelated to this plan). `.rt-green.json` written (205 code file hashes).
`install.ps1 -Profile engineering`: completed clean, "Done. Commit the
regenerated mirrors." `install-junctions.ps1 -Sync`: synced 2 (a hook script,
the CLAUDE.md contract block), held 2 (`hooks\askuserquestion-clarity.json`,
`hooks\rt-inbox-deliver.json` - both pre-existing and unrelated to this plan,
not touched this session).

NEXT ACTION: review the diff and commit - this session never runs git.

### Memory upkeep - deferred, not actioned this session

The Stop hook asked for vault + graphify upkeep via `local-writer` (Agent tool).
Not dispatched: the operator's instruction for this whole session was "do not use
subagent, make all the system here in this chat session," which takes precedence
over the hook's default routing. Recorded here instead so a future session (or the
operator, running `local-writer` directly) can capture it:

- **Reusable learning (candidate for `30_Ressources/Python/` or
  `30_Ressources/ResearchTools/`)**: a `plan:` line in a `PROGRESS.md`-shaped file
  cannot point at a path containing a space - `collect_progress.py`'s
  `PLAN_LINE` regex is `plan:\s*(\S+)\s*$`, so a filename such as
  `"...journal-durable DONE.md"` (the repo's own `<title> DONE.md` convention)
  silently breaks the plan crosscheck with no error, just
  `"no 'plan:' line"`. Archived plan files meant to be referenced FROM a
  `PROGRESS.md` need a space-free name (hyphen instead), even though the same
  convention elsewhere (files never referenced by a `plan:` line) tolerates the
  space.
- **Reusable learning**: OpenObserve's plain JSON bulk-ingestion endpoint
  (`POST /api/{org}/{stream}/_json`) and its `_search` endpoint are a
  stdlib-only (`urllib`), dependency-free alternative to its OTLP ingestion
  path for a Python client that must not add `requests`/`opentelemetry-*`.
- **Graphify**: every changed/added file this session is Python or Markdown
  inside `.claude/skills/rt-observe/` plus a few repo-root docs; an AST-only
  `graphify update .` covers the code, but the new module docstrings and the
  new `docs/rt-observe.md` section are prose a semantic pass would be needed
  for, and semantic passes cost a model call - not run silently, left for the
  operator to request.
