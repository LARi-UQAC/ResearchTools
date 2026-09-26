---
name: rt-observe
description: Report the state of this toolkit as one local page - the mirror matrix of every agent, skill, command and rule against every harness dialect, plus live sessions, services and plan progress. Trigger on rt-dashboard, mirror matrix, mirror drift, is my toolkit deployed, which harness is missing an agent, toolkit status, harness state. Runs on any OS from a bare clone with no harness installed, because the matrix compares files rather than asking a tool.
---

# rt-observe

One local view that answers, harness-neutrally: is this toolkit correctly deployed to every
harness in use, what is running right now, and which safe action fixes what is broken.

## Why it exists

ResearchTools keeps one canonical definition set and `install.ps1` fans it out into several
harness dialects. The installer computes a verdict for every target, prints it, and throws it
away. Nothing observes whether the fan-out stayed intact, and drift is therefore invisible
until something behaves like an older version of itself.

A cell being empty is not the problem. **Not knowing which empty cells are deliberate** is the
problem. That is the one thing this skill exists to make impossible to get wrong.

## Run it

```bash
python .claude/skills/rt-observe/scripts/rt_state.py            # human summary
python .claude/skills/rt-observe/scripts/rt_state.py --json     # the whole snapshot
```

Standard library only. No pip install, no npm, no Docker, no build step, and no PowerShell:
the core never shells out to a `.ps1`. Exit 0 is clean, 1 means something is `lost` or
`stale`, 2 is a refusal by design (R12).

To reproduce a fresh clone on a machine with nothing installed, point it at an empty home:

```bash
python .../rt_state.py --json --home /tmp/empty-home
```

## The five states that matter

| State | Meaning |
|---|---|
| `ok` | present, and nothing says it is degraded |
| `by-design` | the generator deliberately skips it, per `mirror-policy.json` |
| `stubbed` | present but reduced to a pointer, body over the Copilot ceiling |
| `trimmed` | present with a shortened description, Codex list budget |
| `stale` | present, but the canonical source is newer than the mirror |
| `lost` | absent with **no** design reason |
| `orphan` | present in a dialect with no canonical source |
| `unknown` | that dialect is not installed here, so nothing can be said about it |

`by-design` and `lost` look identical on disk. Intent comes from `mirror-policy.json` at the
repository root, which `install.ps1` reads as well, so there is one declaration and two
consumers.

## What it will not do

It reports and it recovers; it does not author. It never edits an agent, a skill or a hook.

It never reads the Obsidian vault, and it never reads the code graph: the graph panel renders
a snapshot that `local-writer` produced, because `vault-access-guard.py` refuses
`graphify-out/` to every other caller and a server reading the graph on a caller's behalf is
exactly what that guard exists to stop. The voice panel's questions are relayed to the vault
daemon's own ask queue and never read either store from this process.

## Known limitation

Live MCP connection state exists on no file on disk, so the roster read from configuration is
reported as *configured, liveness unavailable* unless the `claude` binary is on PATH. That is
stated on screen rather than blanked.

## The optional journal (2026-09-24)

Two more panels, both absent by default and both additive: an identity/account-to-container
layer in PostgreSQL (`rt_store.py`, the only module that knows postgres exists) and a
trace/audit journal in OpenObserve (`rt_openobserve.py`, the only module that knows it exists;
also a second sink beside the existing `~/.claude/rt-state-actions.jsonl`, which remains the
fallback). Neither is required: with no `postgres`/`openobserve` block declared in
`observe-config.json`, every panel above is unaffected and the two new ones report
`unavailable` with a named reason. Full design, the store split rationale, and the known
limitations (no RBAC in OpenObserve's open-source edition, its 5-hour silent ingest window, and
identifier spoofing across containers) are in
[docs/rt-observe.md](../../../docs/rt-observe.md#the-optional-journal-identity-traces-audit).

## The voice panel (2026-09-26)

A push-to-talk voice panel (hold P, release to send), one place this skill adds an optional
dependency (`requirements-voice.txt` for `faster-whisper`, lazily imported inside
`stt_engine.py`'s default loader only, absent by default reports unavailable with the install
command rather than breaking the dashboard). Every question is relayed to the vault daemon's
own ask queue (`.claude/skills/obsidian-cli`'s `daemon_ask.py`) and answered there - this
process never opens `OBSIDIAN_VAULT` or `graphify-out/` itself. TTS in this phase is the
browser's own `speechSynthesis`, not a new server-side engine. Language is a dropdown
(auto/en/fr) next to the panel, not auto-detected alone. Full design:
[docs/rt-observe.md](../../../docs/rt-observe.md#the-voice-panel-2026-09-26).
