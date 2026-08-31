# PROGRESS.md - rt-observe dashboard

Where the rt-observe work stands, in the shape `authoring-loop` and
`thesis-to-paper` already define: per-phase checkboxes, a NEXT ACTION line, state
lines, and evidence on every phase that claims to be done.

On a cold resume, read this file first, then the plan, then continue at NEXT
ACTION. Do not re-derive anything recorded here.

The `rt-observe` progression panel parses this file and cross-checks its phase
list against the `### Phase N` headings of the plan named below. A phase in the
plan with no line here is reported `unreported`; a phase ticked with no
`| evidence:` segment is reported `unproven` rather than green.

plan: docs/superpowers/todo/2026-08-30-rt-observe-dashboard.md

- branch: feat/rt-dashboard
- suite: 69 suites green, .rt-green.json written with 166 code file hashes
- matrix: lost 0, stale 1, orphan 0, by-design 10, stubbed 7, trimmed 11, ok 105
  (the one stale cell is the VS Code USER copy of rules/testing.md, which this
  phase edited. Only `install.ps1 -Personal` writes that target, and that stays
  the operator's run - the dashboard now offers it as the `mirrors.personal`
  button, which is a fair first thing to try the action layer on.)
- verify-no-personal-data.ps1: all checks passed
- session: researchtools-35, 2026-08-31
- constraint: this session runs no git command at all; the operator owns git

## Phases

- [x] Phase 0 - consult both memories first | evidence: local-writer dispatched, graph answered 3 of 8 questions and the vault 1 of 6; digest folded into Amendment 1 of the plan
- [x] Phase 1 - policy extraction and the mirror matrix | evidence: mirror-policy.json + install.ps1 -Manifest, extraction proven inert by hashing 83 generated files before and after, 23 tests in test_rt_mirrors.py, full suite green
- [x] Phase 2 - core collectors and adapters | evidence: collect_registry/repo/progress/graph/services + adapters contract and 2 adapters, 35 tests in test_rt_collectors.py and 21 in test_adapters.py, full suite 64 green
- [x] Phase 3 - server, then the designed view | evidence: rt_server.py (loopback bind refused off-loopback before a socket exists, four routes, session token on /api/action, per-section TTL cache with a non-blocking serving mode), rt_redact.py, the two canonical launchers plus three root wrappers and a .vscode/tasks.json entry, .claude/commands/rt-dashboard.md, assets/rt_state.html and the extracted assets/rt-tokens.css; 61 tests in test_rt_state.py, 14 in test_launcher.py, 14 in test_rt_view.py, and the full suite 67 green; the page rendered and measured with Playwright at 385/768/1080/1440/1920 (no body overflow, zero canvas overlaps, zero off-canvas nodes, 10px font floor), both themes and prefers-reduced-motion verified, the eight states proven distinguishable in grayscale
- [x] Phase 4 - actions | evidence: `actions.json` (closed whitelist, 10 ids, fixed argv, data not code) + `scripts/rt_actions.py` (token table, availability, dry run, confirm gate, append-only log, judgement by effect) + `GET /api/actions` + the Actions panel and compose dialog in `assets/rt_state.html` + `.claude/hooks/rt-inbox-deliver.py` with its config and its declaration in `settings.template.json`; 38 tests in test_rt_actions.py, 20 in test_rt_inbox_deliver.py, 8 added to test_rt_view.py, 6 to test_rt_state.py, 3 to test_rt_collectors.py, full suite 69 green; and the whole path exercised in a real browser against a real server - a dry run, a real read-only run reported failed with its own output, a destructive action armed and cancelled without spawning, a real inbox write reported unreachable, and a typed message proven to survive a poll
- [ ] Phase 5 - optional agent-flow pane  (NOT ASKED FOR: do not start without the operator)
- [x] Phase 6 - register and prove | evidence: README counts corrected and rt-observe section added, Architecture Layer 6, routing-table row in .claude/CLAUDE.md, workflows.md flow row plus both stale "skills have no mirror" sentences corrected and -Personal documented, testing.md script surface and three suite entries, IMPROVEMENTS.md entry
- [x] Phase 7 - mirror to every harness, then let the dashboard prove it | evidence: install.ps1 -Profile engineering -Manifest -Personal, then install-junctions.ps1 -Sync, then check-deployment.ps1 40 items in step; the matrix then reported lost 0, stale 0, orphan 0 and 64 suites green
- [x] Phase 8 - write both memories back | evidence: local-writer dispatched, cut off by the account spend limit after one tool call, RESUMED and completed - four atomic notes staged (dead config as a failure class and the bidirectional test that catches it; a UserPromptSubmit hook's session-wide blast radius; transient UI state outside a reconciled DOM; redact-before-truncate) plus one Decisions.md append, with three earlier-phase notes correctly skipped as already staged. Graph refreshed from the REPOSITORY ROOT, AST only: 47/47 files, 6297 nodes, 8874 edges. The notes are STAGED in the outbox and reach the vault at session end through the flush hook, so the write is not proven until that hook runs
- [ ] Phase 9 - the page becomes tabs and fits one screen  (Amendment 2, Part E)
- [ ] Phase 10 - the global interaction layer: hover detail, rounded corners, draggable boxes  (Amendment 2, Part G)
- [ ] Phase 11 - the Real-Time Process tab  (Amendment 2, Part F; read the two VibeDesignBook figures FIRST)

**NEXT ACTION**: Phase 9, 10 and 11 from Amendment 2, in that order: the tabs first because they decide how much any panel may show,
the interaction layer second because the real-time tab is its heaviest consumer, and the
Real-Time Process tab last. Phase 5 stays optional and unasked.

Phase 8, write both memories back. Dispatch `local-writer` (the only
caller allowed at either memory) with the learnings this phase produced - the dead-config
class the `mcp_live` split belongs to, redaction-before-truncation, the two-step confirm
living outside a morphed DOM, and a `UserPromptSubmit` hook's blast radius - plus a
`Decisions.md` append for the project, and an AST refresh of the changed paths pointed at
the REPOSITORY ROOT. Four notes from Phase 3 are already staged in the outbox and must not
be duplicated. Phase 5 is optional and was NOT asked for; leave it unless the operator asks.

## Carried forward, do not re-derive

- The working tree is shared by every session in this directory: `.git/HEAD` is one
  file, so a peer's `git checkout` moves the branch under this work. Read
  `.git/HEAD` as a plain file before any write phase. That is a file read, not a
  git command.
- `docs/superpowers/` is gitignored wholesale (`.gitignore:12`), so the plan
  itself never reaches a clone.
- Two dependency candidates were considered and REJECTED on 2026-08-30, with the
  reasoning recorded in Part D of the plan: React Flow, and Langfuse. Do not
  re-open them. If the hand-written canvas proves inadequate, the smaller option
  is `d3-force` alone.
- The three features the operator added after approval - plan progression,
  session messaging plus headless spawn, and the graph snapshot panel - are
  specified in Part B of the plan and folded into Phases 2, 3, 4 and 6. They do
  not get phases of their own.
- A running dashboard serves the MARKUP from disk on every request, so an edit
  to `rt_state.html` needs only a browser refresh. Anything in Python needs the
  server restarted. Measured 2026-08-31 the hard way, when a page was read as
  broken while the server was simply serving an older view config.
- `requestAnimationFrame` is throttled to roughly one frame per 700 ms under
  the Playwright automation used here, on a page that reports itself visible and
  focused. Any measurement of an animation in that harness is an artefact; the
  stillness and mutation checks are sound, the easing itself is not verifiable
  there. A dead page also mutates no DOM, so a syntax error once read as
  "perfectly stable" - always prove the page is alive before believing a
  stability measurement.

- `ttl_seconds.mcp_live` is no longer dead config. Decided by the operator on
  2026-08-31 in favour of the SPLIT: MCP is its own snapshot section keyed by
  `mcp_live` (300 s), `collect_services.collect()` no longer shells out at all,
  and `state.services.mcp` became `state.mcp` in the collector, the CLI dump,
  the page and three suites. A test now asserts the OTHER direction too - every
  key declared under `ttl_seconds` must be consumed by some section - so a
  second dead TTL cannot appear unnoticed.
- The action layer's safety argument is structural, not procedural: `actions.json`
  holds a FIXED argv per id, the page posts only an id, and a `{token}` inside an
  argv entry resolves from a closed server-side table. Anything else is a refusal.
  If a future phase wants a parameterised action, that is a NEW mechanism to
  design, not a hole to widen here.
- The vault daemon was already back up on arrival (`running=True`, 232 sent), so
  the note about this session having killed it is closed.

- **The page is one scrolling sheet and the operator wants tabs.** Recorded as
  Amendment 2 of the plan on 2026-08-31, with three phases: 9 tabs the fan-out, the
  rail and a new Real-Time Process tab and proves the whole dashboard fits one
  screen with no scrolling; 10 defines ONE interaction layer for every object in
  every tab (hover opens the detail behind a summary - the worked example is the
  fan-out edge reading `1 lost` whose detail is currently unreachable - plus
  rounded corners and draggable boxes whose edges follow); 11 builds the
  Real-Time Process tab itself against the two figures the operator already drew,
  `
ef{c2:fig:hooks_states}` and `
ef{c2:fig:superpowers_collab}` in
  `docs/chapitres/ch02-agent.tex` of VibeDesignBook, which must be read before
  anything is designed.
- **`unreachable` on a session card was questioned and is correct.** It reports the
  delivery PATH, not whether the session is open: Copilot Chat has no hook that
  could drain an inbox and says so, and every Claude Code card stays unreachable
  until `rt-inbox-deliver.py` is deployed to `~/.claude/hooks` and declared in the
  live `settings.json`. That deployment is the operator's `-Sync` plus the settings
  merge. Full answer in Part H of Amendment 2.

## Open, and waiting on the operator rather than on work

Each of these was raised and left deliberately. None blocks Phase 4.

- **`ttl_seconds.mcp_live` is dead config.** It is declared at 300 s and consumed
  by nothing: MCP rides the services section on its 60 s timer, so
  `claude mcp list` - which shells out and reaches the network for 28 servers
  under a 45 s budget - runs five times more often than the plan specified.
  A key that looks configured and does nothing is the failure class this
  repository keeps legislating against. Two fixes were put to the operator and
  neither was chosen yet: SPLIT MCP into its own snapshot section keyed by
  `mcp_live`, which is correct and matches the spec but changes a tested
  contract (`state.services.mcp` becomes `state.mcp`, touching the collector,
  the page and three suites); or DELETE `mcp_live` and accept the 60 s refresh
  as a conscious decision rather than a silently lost one. The recommendation
  was the split.
- **The vault daemon was killed by this session** on 2026-08-31, by an
  over-broad process match while cleaning up dashboard servers - the same
  mistake the `Stop-Process -Name "ollama*"` note warns about. Its singleton
  lock is stale and the dashboard reports `running=False`, correctly. Restoring
  it is one command the operator runs:
  `.\.claude\skills\obsidian-cli\scripts\vault-daemon-autostart.ps1`.
- **A semantic graph pass is pending.** The AST refresh is done and cost no
  model call. The changed documents (README, Architecture, the rule files, the
  HTML and the CSS) would need a semantic pass, which is a model call, so it was
  named rather than run.
- **`SKILL.md` is Phase-2 vintage.** Its "Run it" section documents only
  `rt_state.py` and `--json`; it never mentions `--serve`, the `rt-dashboard`
  launchers or the page, and it is the file the Codex mirror carries and the
  `/rt-dashboard` command tells a reader to open first. Its state table is also
  headed "The five states that matter" while listing eight. One edit, then
  `install.ps1` to refresh the Codex mirror.
- **Four vault notes are staged** in `~/.claude/obsidian-outbox/` from the
  Phase 3 upkeep dispatch, delivered by the flush hook at session end. Phase 8
  must not duplicate them: three atomic notes (subprocess locale decoding, the
  keep-alive body drain, redacting home paths in a rendered UI) and one
  `Decisions.md` append.

## Findings this work has produced, beyond its own deliverables
- Two defects in this phase's own code were found by its suite before anything
  shipped, both in the same class the repository keeps meeting: an action-log
  path that raises `ValueError` rather than `OSError` turned a COMPLETED action
  into a 500 that said nothing about what had run, and redaction ran AFTER
  truncation, so a home path cut in the middle no longer matched the home prefix
  and the account name survived in the fragment the page publishes. Order is the
  fix: redact, then truncate.
- `check-deployment.ps1`, run through the new action layer as its first real
  subprocess, reported itself failed with exit 1 and explained why in its own
  output: `rt-inbox-deliver.py` is declared by the template and not yet deployed
  to `~/.claude/hooks`, and `.rt-green.json` was stale against files edited that
  minute. Both true, both the operator's to clear with `-Sync` and the suite. The
  action layer reporting a real failure on its first real run is the intended
  behaviour, not a defect in it.
- The live `~/.claude/settings.json` does NOT yet declare the inbox hook, and the
  script is not deployed, so there is no half-installed state: sessions correctly
  render `unreachable` and the Send button does not appear. Deploying both is one
  `install-junctions.ps1 -Sync` plus the settings merge, and until then the write
  path is proven only by its suite and by a self-test message that was written,
  reported unreachable, and deleted.

- 6 agents have no GitHub Copilot CLI mirror, the defect the plan was built
  around, reproduced by the instrument.
- A SECOND lost column, which the plan did not know about: 7 commands never
  reached the VS Code user profile, under the same `-Personal` gate.
- 23 mirrors are `stale` rather than absent, so drift was not only about absence.
- Adding `rt-observe` as the 16th skill shrank the Codex per-skill description
  cap enough to cut `geolocalisation`'s mirrored description from 1019 characters
  to 69, losing its trigger vocabulary in that harness. Working as designed, and
  a real loss worth a decision.
- `vault-access-guard.py`'s graph arm matches the graph directory name inside a
  shell heredoc BODY, so a document that merely discusses the graph cannot be
  written that way. A false positive in the safe direction, owned by that hook.
  Hit again in Phase 3 while editing Architecture.md; worked around by naming
  the graph page without its directory.
- Six defects in this repository's own code were found by RENDERING the page and
  measuring it, none of them by reading the code. The account name reached
  `/api/state` twice (a session prompt is free text that quotes home paths, and
  two collectors reported an expanded `~`); five MCP servers all displayed as
  "plugin" because the roster split a name on its first colon; French Windows
  netstat broke a strict cp1252 decode inside subprocess's reader thread, so a
  held port reported "no listener"; a refused cross-origin POST desynchronised
  its keep-alive connection; a section still collecting rendered under the word
  "unavailable"; and the rendered font floor was 9px. Each is fixed with a test.
- SIX stray graph roots across at least three sessions, 1629 nodes of derived
  data, the oldest undetected since the previous day. The refresh takes a
  directory and nothing said WHICH directory: pointed at a subdirectory the tool
  treats it as its own project root, writes a partial graph there and leaves the
  repository graph untouched, reporting success either way. Four of the six were
  found by the guard's FIRST run, not by anyone noticing. Rule written into
  `.claude/CLAUDE.md` and `security.md`, guard in `test_graph_routing.py`, all
  six removed by `local-writer` and the repository graph refreshed from the root.
- A semantic pass over this phase's changed documents is PENDING and is the
  operator's to authorise. The AST refresh is done and cost no model call.
- A second status hue was tried for the matrix and DROPPED on a measurement: on
  this surface every amber step dark enough to clear 3:1 contrast landed within
  normal-vision Delta E 13.6 of the alarm red (floor 15) and collapsed to 3.9
  under deuteranopia. So severity is not carried by hue at all - colour marks the
  one state that must never be missed, and the other seven are carried by a
  two-letter code, a texture and an edge weight.
