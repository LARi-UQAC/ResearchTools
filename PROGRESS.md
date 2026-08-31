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
- suite: 64 suites green, .rt-green.json written with 157 code file hashes
- matrix: lost 0, stale 0, orphan 0, by-design 10, stubbed 7, trimmed 11, ok 104
- verify-no-personal-data.ps1: all checks passed
- session: researchtools-34, 2026-08-30
- constraint: this session runs no git command at all; the operator owns git

## Phases

- [x] Phase 0 - consult both memories first | evidence: local-writer dispatched, graph answered 3 of 8 questions and the vault 1 of 6; digest folded into Amendment 1 of the plan
- [x] Phase 1 - policy extraction and the mirror matrix | evidence: mirror-policy.json + install.ps1 -Manifest, extraction proven inert by hashing 83 generated files before and after, 23 tests in test_rt_mirrors.py, full suite green
- [x] Phase 2 - core collectors and adapters | evidence: collect_registry/repo/progress/graph/services + adapters contract and 2 adapters, 35 tests in test_rt_collectors.py and 21 in test_adapters.py, full suite 64 green
- [ ] Phase 3 - server, then the designed view
- [ ] Phase 4 - actions
- [ ] Phase 5 - optional agent-flow pane
- [x] Phase 6 - register and prove | evidence: README counts corrected and rt-observe section added, Architecture Layer 6, routing-table row in .claude/CLAUDE.md, workflows.md flow row plus both stale "skills have no mirror" sentences corrected and -Personal documented, testing.md script surface and three suite entries, IMPROVEMENTS.md entry
- [x] Phase 7 - mirror to every harness, then let the dashboard prove it | evidence: install.ps1 -Profile engineering -Manifest -Personal, then install-junctions.ps1 -Sync, then check-deployment.ps1 40 items in step; the matrix then reported lost 0, stale 0, orphan 0 and 64 suites green
- [ ] Phase 8 - write both memories back

**NEXT ACTION**: Phase 3, the only substantial phase left. Server first - `rt_state.py --serve`, the three routes, the loopback bind and the session token, then the `rt-dashboard` launcher and its wrappers with their three refusals. Only THEN the view, and the view starts with the design passes (`frontend-design`, then `clarify`, `onboard`, `colorize`, `dataviz`, `animate`) BEFORE any markup exists. Writing markup first and styling it afterwards produces exactly the templated result those skills exist to prevent. Phases 4, 5 and 8 follow. Phase 6 and 7 were done AHEAD of 3, 4 and 5 on the operator's instruction, to bank the durable value before a usage limit; the plan's stated order is otherwise unchanged.

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

## Findings this work has produced, beyond its own deliverables

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
