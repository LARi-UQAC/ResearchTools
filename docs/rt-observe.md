# rt-observe — harness-neutral toolkit state and mirror matrix

Full reference for the `rt-observe` skill: the mirror matrix, the loopback dashboard, and
everything the CLI/JSON snapshot reports. See the root [README.md](../README.md) Skills
table for the one-line summary and [Architecture.md](../Architecture.md) for how it fits the
rest of the toolkit.

Answers one question: is this toolkit correctly deployed to every harness in use, and which
empty cells are deliberate. `install.ps1` computes a verdict for every mirror it generates,
prints it, and throws it away, so drift stays invisible until an agent behaves like an older
version of itself.

The centrepiece is the **mirror matrix**: every canonical agent, skill, command and rule down
the page, every harness dialect across it. Eight states, and the two that matter most are the
two that look identical on disk:

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

Intent comes from [mirror-policy.json](../mirror-policy.json) at the repository root, which
`install.ps1` reads as well: one declaration, two consumers, and the `by-design` / `lost`
distinction becomes readable on any OS from a fresh clone by someone who cannot run PowerShell.

```bash
python .claude/skills/rt-observe/scripts/rt_state.py            # human summary
python .claude/skills/rt-observe/scripts/rt_state.py --json     # the whole snapshot
```

**The dashboard.** `rt-dashboard` starts a loopback server and opens the page. It is a plain
command on purpose, in four spellings, because ResearchTools is cloned by people who do not run
Claude Code:

```powershell
.\rt-dashboard.ps1 -DryRun        # names the interpreter, the bind and every TTL; starts nothing
.\rt-dashboard.ps1 -Open          # serve on 127.0.0.1 and hand the URL to the browser
.\rt-dashboard.bat                # double-click, and cmd
sh ./rt-dashboard.sh --open        # macOS and Linux
```

VS Code users get the same two entries under Run Task, and `/rt-dashboard` is the Claude Code
convenience wrapper. Each root file is a thin forward to the canonical launcher beside its
module; the only decision any of them makes is which Python to use, and with none found it
names every candidate it tried and exits 2 rather than guessing.

The server binds `127.0.0.1` only, refuses any other bind address before a socket exists, and
mints a session token at startup that `POST /api/action` requires. `GET /` serves the page,
`GET /api/state` the cached snapshot, `GET /api/ping` the identity the launcher probes. Two
refusals are worth knowing because they protect you from a wrong answer rather than an error: a
port held by another process is reported **with the holding PID** and the launcher exits
non-zero rather than binding a second port, since two dashboards showing two different
snapshots is worse than none; and a dashboard already running is reported with its URL rather
than started twice.

**One screen, two tab strips.** The page does not scroll, at any width it supports. The sheet
is the viewport, and anything longer than the pane it sits in scrolls inside that pane, which is
what decides how much any one tab may show. The left column carries four views - the mirror
matrix as the landing view, the fan-out diagram, the sessions strip, and the Real-Time Process
tab described below. The right column carries the rail's seven panels
as tabs of their own: repository, plan, services, code graph, hooks, journal and actions. Which tab is in
front is a per-viewer convenience remembered in `localStorage`, the way the theme control is,
and both strips take the arrow keys.

**What the harness is doing right now.** The `Real-Time Process` tab draws the session state
machine of the lab's own figure - SessionStart, waiting, UserPromptSubmit, reasoning and tool
calling, PostToolUse, security audit - with the state a session is in filled dark and the arcs it
has travelled this turn at double width, a marker running along them. Below it, one lane per
session carries the recent steps: history stays on screen in low grey and any step can be picked
back up, a subagent hangs off the session that spawned it and is named by the call that spawned
it, and a call that leaves the machine says so (`mcp` means it went through a server, which may be
remote). Token spend is reported as a total and NOT as a percentage: a transcript records tokens
per message and never the window they sit in, so the bar is relative to the busiest session on
screen and says as much. Adapter-fed like the rest, so Copilot Chat - whose store holds session
metadata and no step timeline - reports that rather than being drawn as idle.

**Four marks, four meanings.** A BOX is an actor: a session, a subagent, a skill, a memory. A
tool call is not an actor but an event on a line, so it is a tick that carries a count when it
repeats. A tool result is not a node either - it is the EDGE leaving the call it answers, solid
once the output came back and dashed while the call is still out, which is the same arrow the
state strip draws from `tool call` to `PostToolUse`. And a hook is drawn as a hook. The page says
all four in a legend rather than leaving them to be inferred.

**The deterministic half is visible too.** Hook firings arrive in a transcript as attachments,
and reading attachments as noise is what once made RTK, caveman, the secret scan and the vault
outbox flush invisible on a tab whose whole subject is what the harness is doing. Each one now
draws the figure's own idiom: a dashed self-loop on the box it runs on, labelled with the hook's
NAME rather than the file that implements it, and drawn in alarm when the hook refused rather than
merely watched. Subagent dispatches are counted apart from tool calls, so a `local-writer`
dispatch cannot be pushed off the lane by the next hundred Bash calls, and an MCP call is named by
its server.

**Three bars, and three maxima you type.** What this session holds, what the week has spent
(summed from the transcripts: new input, cache creation and output, never tokens re-read from
cache, which are the same conversation counted again), and a paid supplement that appears only
once one of the other two is full. None of the three MAXIMA is reported anywhere on this machine,
so each is typed beside its bar and kept per viewer, and a bar with no maximum is not drawn at
all. Nothing here is money: no plan, invoice or payment method is readable from this machine.

**The refresh rate is yours.** Type an interval beside the theme control; the presets are
suggestions. The page then asks the server for data no older than that, and the server clamps the
request up to a configured floor, so no viewer can make the collector that leaves the machine run
faster than its own timer.

**Hovering anything explains it.** One layer, not one tooltip per panel: a cell, a card, a plan
phase, a box or an edge in the fan-out opts in, and a single renderer draws the detail behind the
summary. The case that made it necessary is the fan-out edge that reads `1 lost` - the number was
reachable and the name behind it was not, so the edge now carries which mirror is lost and in what
state. The diagram's boxes can also be dragged, and their edges follow, because every path is
drawn from the node's own coordinates rather than from a stored copy of them.

**Acting on what it reports.** The rail carries an Actions panel, and every button in it runs
one entry of a closed whitelist held as data in
[.claude/skills/rt-observe/actions.json](../.claude/skills/rt-observe/actions.json): an id maps to
a FIXED argv, the page posts only that id, and nothing from the request ever reaches a command
line. Every id points at a script this repository already ships and already tests -
`install.ps1 -Personal` (the fix for the mirrors the matrix reports lost), `-Manifest`,
`install-junctions.ps1 -Sync`, `check-deployment.ps1`, `run-offline-tests.ps1`,
`restart-ollama.ps1`, the vault daemon's status and start, and one action that spawns a fresh
headless session. Each offers a **dry run** that resolves the argv and executes nothing, a
destructive one arms first and then shows the action's own confirm sentence rather than a
generic prompt, and an action whose interpreter is not on this machine renders as a reason
instead of a button that would fail on click.

An action is judged by its **effect, not its exit code**: after it runs, the section it claims
to change is collected again and the panel says `effect confirmed`, `effect NOT confirmed` or
`effect unchecked`. `restart-ollama.ps1` is the reason - it is the documented script that exits
0 while an orphaned child keeps its VRAM. Every attempt, refusals included, appends one JSON
line to `~/.claude/rt-state-actions.jsonl`.

**Messaging a session.** A Claude Code session card carries a Send button when, and only when,
the delivery hook is installed for it. The message is written into `~/.claude/rt-inbox/<session
id>/` and nothing executes; `rt-inbox-deliver.py`, a `UserPromptSubmit` hook, hands it to that
session on its next turn and moves it to `delivered/`. A session with no hook is reported
**unreachable** and never as delivered, because a message written into a directory nobody drains
is worse than no message at all. This does not replace Claude Code's own cross-session
messaging, and it cannot: a browser page cannot call an agent tool. What it adds is a durable
record, a fleet view of who is reachable, and an inbox another harness could read too.

Each section carries its own TTL, so a two-second page poll never re-runs `claude mcp list`,
and a section that has never been collected reads `collecting` rather than blank - the first
`/api/state` answers immediately while the slow collectors fill in behind it.

The page is one self-contained file with no CDN, no npm and no build step, in both themes, from
a 400px side panel to a wide monitor. The eight cell states are distinguishable with colour
removed, because colour marks only the one state that must never be missed: on this surface no
second status hue cleared the colour-vision-deficiency floors against the alarm red, so every
other state is carried by a two-letter code, a texture and an edge weight. Its design tokens
are extracted to [assets/rt-tokens.css](../assets/rt-tokens.css), the first shared token file in
this repository, and a test asserts the page and that file cannot drift apart.

Standard library only: no pip install, no npm, no Docker, no build step, and the core never
shells out to a `.ps1`. Exit 0 is clean, 1 means something is `lost` or `stale`, 2 is a refusal
by design. **Zero harnesses is a supported configuration** - with no adapter present the
matrix, the registry check, the repository panel and the plan progression are all still
complete, which is the majority of the value and the whole of it for a lab member on Codex or
Continue. Point `--home` at an empty directory to reproduce that case.

Beyond the matrix it reports: the canonical definition set's own integrity, the green stamp
and active profile, plan progression read from `PROGRESS.md` and cross-checked against the
plan's own phase headings, the MCP roster (live when the `claude` binary is present, otherwise
the declared roster with liveness stated as unavailable), local model residency, the vault
daemon and its queue depth, and recent sessions from two adapters - Claude Code and GitHub
Copilot Chat. Adding a harness is a new module plus one line in `harnesses.json`, with no core
edit, and a test asserts exactly that.

It never reads the Obsidian vault, and it never reads the code graph: the graph panel renders
a snapshot that `local-writer` produced, because `vault-access-guard.py` refuses the graph to
every other caller and a server reading it on your behalf is the bypass that guard exists to
stop.

## The optional journal (identity, traces, audit)

Added 2026-09-24, per
[docs/superpowers/plans/done/2026-09-24-rt-observe-journal-durable-DONE.md](superpowers/plans/done/2026-09-24-rt-observe-journal-durable-DONE.md),
for the lab's five-student multi-sandbox GPU server.
Every claim above about a fresh clone still holds: with no database and no log store
configured, rt-observe reports exactly what it reported before this section existed, and the
two new panels say `unavailable` with a named reason rather than showing nothing.

**Two stores, split by whether a mistake in them can be corrected.** OpenObserve's own
documentation states that data is immutable once ingested and only a whole retention period can
be dropped - the right shape for a trace/audit log, the wrong one for an identity table a lab
member might need to fix by hand. So:

- **PostgreSQL** ([rt_store.py](../.claude/skills/rt-observe/scripts/rt_store.py)) holds three
  mutable tables: who has an account, which system account/container/OpenObserve organisation
  maps to which person, and a history of snapshots taken. `rt_store.py --migrate --dry-run`
  (default) prints the DDL; `--yes` applies it, idempotently.
- **OpenObserve** ([rt_openobserve.py](../.claude/skills/rt-observe/scripts/rt_openobserve.py))
  holds the immutable stream: agent traces and, as a second sink beside the existing
  `~/.claude/rt-state-actions.jsonl`, the dashboard's own action-audit log. The JSONL is never
  replaced - it is the fallback that survives an OpenObserve outage, since every action is
  still recorded locally even when the remote sink fails or is not configured at all.

Both are declared in `observe-config.json` under `postgres` and `openobserve` blocks that are
**absent by default**. An absent block is the supported, zero-service state; a block that is
present but incomplete is a real misconfiguration and is refused by name (R3), never silently
disabled. Credentials never live in that file: `RT_PG_PASSWORD` for PostgreSQL, `RT_OO_USER` /
`RT_OO_PASSWORD` for OpenObserve, read from the environment only.

**Known limitations, recorded rather than worked around:**

- The open-source edition of OpenObserve has no per-role access control - every account that
  can reach it can read every stream. Acceptable among a handful of lab colleagues on one
  machine; this tool adds no boundary of its own.
- OpenObserve's own default `ZO_INGEST_ALLOWED_UPTO` is 5 hours: an event older than that is
  dropped **on ingest, in silence**. `rt_openobserve.remind_ingest_window()` and
  `verify_ingest_window()` exist so an operator replaying historical transcripts checks by
  **reading a marker back** (R9) rather than trusting a 200 response, but this module cannot
  change a remote server's own environment variable.
- Which container's session maps to which person's identifier can be spoofed by whoever
  controls that container; this layer records a mapping, it does not attest one.
- The plan's own section 2.4 asked to verify, against a live instance, whether OpenObserve's
  documented Claude Code integration page and the harness's native OTLP exporter
  (`CLAUDE_CODE_ENABLE_TELEMETRY=1`, `OTEL_EXPORTER_OTLP_ENDPOINT`) could be reused instead of
  writing a client. That check needs a live network fetch this session did not have available
  without delegating to a subagent, so `rt_openobserve.py` implements OpenObserve's plain JSON
  bulk-ingestion and SQL search endpoints instead - the documented, dependency-free path - and
  the OTLP question is left open for an operator with a running instance to answer.
- Multi-sandbox aggregation (Phase 5 of the plan): each student's container is expected to
  export to one central OpenObserve instance, with a single rt-observe running server-side
  against that store. The mirror matrix itself stays per-clone and is never aggregated, since
  it describes a deployment, not a person.

The **Journal** rail panel shows the identity layer's counts (persons, identifiers, snapshots)
and the trace stream's own shape (row count, distinct sessions, newest event) - never a
recomputed token total, which stays owned by the usage panel's existing, already-decided
counting rule.
