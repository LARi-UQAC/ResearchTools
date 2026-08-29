# ResearchTools improvements

What the toolkit has learned, newest last. Appended automatically whenever a ResearchTools
weakness is fixed from inside another project, and whenever an attempt is abandoned.

There is no git in that loop, so this file is the record: it answers "what has my toolkit
learned" and "when did this behaviour change". The full rule is the RT-CONTRACT block in
`~/.claude/CLAUDE.md`, whose source is `CLAUDE.template.md`.

Format: one entry per fix. Date, owning skill or agent, what changed, where it was found,
and how it was proven. An abandoned attempt is marked ABANDONED and names the failing test,
its error, and any file left behind skip-marked.


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
