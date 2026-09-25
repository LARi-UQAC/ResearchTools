# MEMORY - resume point for a new chat session

For whichever plan `PROGRESS.md` currently tracks. Read `PROGRESS.md` first for the
phase-by-phase evidence; this file is the shorter, decision-level memory a fresh
session needs before touching anything.

## Current plan

`docs/superpowers/plans/done/2026-09-24-rt-observe-journal-durable-DONE.md` (already
moved there this session; see its own header note for what is fully closed versus
left as a stated follow-up).

## Decisions that would otherwise be re-derived

- **Two stores, split by correctability, not by convenience.** PostgreSQL
  (`rt_store.py`) holds mutable identity/mapping/snapshot-history; OpenObserve
  (`rt_openobserve.py`) holds the immutable trace/audit stream, because OpenObserve's
  own docs say ingested data cannot be edited and only a whole retention period can
  be dropped. Do not merge these into one store "for simplicity" - that was
  considered and rejected in the plan itself (section 2).
- **Both are absent by default, and that is the zero-service state, not an error.**
  An operator adds a `postgres`/`openobserve` block to `observe-config.json` to turn
  either on. A block once ADDED must be complete, or `rt_store.py`/`rt_openobserve.py`
  refuse by name (R3) rather than silently degrading - only the UNDECLARED case is
  silent.
- **`rt_actions.py`'s remote sink is additive, never a replacement.** The JSONL at
  `~/.claude/rt-state-actions.jsonl` keeps being written unconditionally; the
  OpenObserve push is best-effort and its result lands in an optional `"remote"` key
  that appears ONLY when a sink is wired. Every call site written before 2026-09-24
  passes no sink and must see byte-identical payloads - that regression control
  lives in `test_rt_actions_remote.py`.
- **Redact before serializing, never after.** `rt_openobserve.send_json` calls
  `rt_redact.home_tilde` recursively on the whole record before `json.dumps`. Do not
  move this to "redact the response" or a log line will carry an account name.
- **stdlib only.** rt-observe's whole reason for existing is zero-dependency
  (`SKILL.md`). `rt_openobserve.py` uses `urllib`, not `requests`, even though the
  rest of the codebase uses `requests` elsewhere (scopus). Do not "simplify" this by
  adding a dependency.

## Left open, not silently dropped

- **A VERIFIED, LIVE check the plan asked for (section 2.4) was not done this
  session**: whether OpenObserve's documented Claude Code integration page and the
  harness's native OTLP exporter (`CLAUDE_CODE_ENABLE_TELEMETRY`,
  `OTEL_EXPORTER_OTLP_ENDPOINT`) could replace `rt_openobserve.py`'s hand-written
  JSON-ingestion client. It needs a live web fetch, which this session could only
  reach via a subagent, and the operator's instructions for this session forbade
  subagents. **Next session with network access: check this before adding more to
  `rt_openobserve.py`.**
- **The 5-hour OpenObserve ingest-window pitfall** (`ZO_INGEST_ALLOWED_UPTO`,
  section 2.3) is coded as a read-back verification helper
  (`rt_openobserve.verify_ingest_window`) but has never been run against a live
  OpenObserve instance - there isn't one on this machine. Run it before any bulk
  replay of historical transcripts.
- **Phase 4's two fuller views** (a browsable per-person history, a replayed
  execution feed from the store rather than live transcripts) were reduced to one
  summary "Journal" panel (counts only) given the single-session constraint. The
  collectors already return enough (`PostgresStore.people()`, `rt_openobserve.search`
  rows) to build the fuller views without new backend work - it is a front-end-only
  follow-up.
- **Phase 5 (multi-sandbox aggregation)** is documentation only; nobody has stood up
  a second container or a real OpenObserve instance to prove the topology end to
  end.
- **`--migrate --yes` and a live OpenObserve** have never been run for real on this
  machine (no PostgreSQL, no OpenObserve installed here). Every test mocks the
  connector/opener. The FIRST real run against live services is unproven territory
  and should be treated as such - re-read `rt_store.py`'s and `rt_openobserve.py`'s
  own docstrings for the R9 read-back discipline before trusting a clean exit code.

## Housekeeping already done, do not repeat

- OpenHands is already registered `documented_not_built` in `harnesses.json` and
  `mirror-policy.json` (done 2026-09-24 during the aider-kit integration, same day,
  different session). Nothing to add there for this plan.
- The old `PROGRESS.md` (aider-kit integration) was archived to
  `docs/superpowers/plans/done/2026-09-07-aider-kit-integration-PROGRESS.md` before
  this file's plan took over the root `PROGRESS.md`. Its own Phase 9 (a full
  overnight aider run; reviewing/committing that diff) is still open and belongs to
  a DIFFERENT session/plan, not this one.

## Standing constraints for this repository, not just this plan

- No git command runs from inside a ResearchTools session by standing instruction;
  the operator reviews and commits.
- `run-offline-tests.ps1` must pass in full before calling anything done; a single
  failure anywhere, even in an untouched skill, means not finished.
- Any new script needs an offline test AND a line in `.claude/rules/testing.md`
  (R23) in the same change.
