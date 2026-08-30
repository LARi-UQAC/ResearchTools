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


## 2026-08-30 - repo-wide hooks - the inventory was timing out, not missing

**Found:** a session printed the `Session:` status line and then reported that no
`[HOOKS ACTIVE]` inventory existed, which reads as "every hook is dead". Nothing was dead.
The session transcript recorded the truth: two `hook_cancelled` entries for
`session-hooks-inventory.py` (`"Listing active hooks..."`), at 10641 ms and 10967 ms against
its declared `timeout: 10` (10000 ms). Seven of the eight most recent sessions in this project
had no cancellation at all, so it is a race, not a break. Everything else checked out - the
global settings.json parsed, all fourteen declared hook scripts were on disk, no matcher
restricted any SessionStart entry, and the hook itself exits 0 with correct output in 150 to
221 ms warm, 587 ms cold.

**Two causes, both structural.** The repository carried its own `.claude/settings.json`, which
redeclared twelve of the fourteen entries, so PROJECT scope and USER scope each launched the
same hooks and every one of them ran twice - the two cancellation records are the proof that
the inventory was started twice. And the inventory held the shortest timeout of the heavy
SessionStart hooks (10 s) while `install-junctions.ps1`, the `git fetch` of the auto-sync check
and `obsidian-outbox-flush.py` each held 30 s, so a Python cold start competed with a
PowerShell sync over 140 file hashes, a network fetch and two Node launches and lost.

**Changed:** deleted the repository's `.claude/settings.json`, which `setup.ps1` no longer
generates since the CLAUDE\*.md consolidation and which `.gitignore` already excluded; its one
project-only setting, the `engineering@knowledge-work-plugins` plugin and its marketplace, was
migrated to the global file first so nothing was lost. Raised the inventory's timeout from 10 s
to 30 s in `.claude/settings.template.json`, matching its neighbours. Added to
`CLAUDE.template.md` the distinction the fallback sentence lacked: an expiry and an absence look
identical from inside a session, because a hook killed by its timeout returns nothing exactly as
a deleted one does, so the inventory cannot report its own death - the transcript's
`hook_cancelled` / `timedOut: true` entry can, and the fix is the timeout, never a rewrite of a
script that does its work in a fifth of a second.

**Also fixed in passing:** that project settings file carried a live instance of the
doubly-escaped substitution defect - `CLAUDE_CODE_GIT_BASH_PATH` decoded with doubled
separators and its `statusLine` command carried both spellings in one string - and project
scope overrides user scope, so this repository had been running on the doubled path. Windows
opens such a path anyway, which is why it was never noticed.

**Proven:** `scripts/audit/check-claude-template.ps1` exit 0 with the five new lines classified
on the allowed-divergence list; the edited global `settings.json` re-read and re-parsed after
the edit, with its hook count, env keys and every other entry unchanged (R9).

## 2026-08-30 - the drain's NameError, and the head-truncation that hid it twice

**Defect:** the live drill's consolidation drain died. `vault_consolidate.py` used
`collections.Counter()` in `main()` while the `import collections` had left with the code moved
out during the 2026-08-28 split into `vault_corpus` / `vault_links` / `vault_apply`. The 35-case
suite stayed green throughout, because every case calls the functions directly and none runs the
entry point - and the daemon's consolidation drain is that entry point's ONLY caller.

**What made it expensive:** three nested layers each truncated the captured stderr from the
FRONT - the drill at 300 characters, `candidate_pairs` and the phantom audit at 200. A Python
traceback names its exception on the LAST line and opens with frames identical on every failure,
so each layer kept the noise and discarded the fact. Two full drill runs, each writing to the
real vault, were spent reaching a one-line NameError.

**Change:** `outbox_io.tail()` is now the single implementation of quoting a failed subprocess,
used by `daemon_drains` (both sites), `daemon_phantoms` and the drill, which no longer keeps a
copy of its own. `import collections` restored.

**Proven:** `test_vault_consolidate.py` gains three cases running `main()` in-process on a
fixture vault for `--mode candidates`, `--mode links` and the default mode - the regression test
the split never had, 38 in total. `test_vault_daemon_e2e.py` gains five on `tail()`, including a
negative control asserting the old head truncation would have lost the exception. The NameError
was reproduced OFFLINE on a fixture vault before the fix, so the diagnosis cost the professor no
further drill run. `scripts/test/run-offline-tests.ps1` green: 58 PASSED, 0 FAILED, 0 NOT RUN.

**Noted, not fixed:** `vault_corpus.py:67` reads notes without closing them, which surfaces as a
`ResourceWarning` under the new CLI cases. Harmless here, out of scope for this fix.

## 2026-08-30 - the drain step failed on a working daemon

**Defect:** with the NameError fixed, `run-drill.ps1 -Only drain` still reported
`pass: false, accepted: 0, rejected: 0` against a daemon that was working correctly. A drain
judges what FILING enqueued, so with an empty consolidate queue `drain()` never calls
`drain_consolidation` and returns a null consolidation. `check_drain` read that null as "judged
nothing" and failed the step, which reads as a broken drain and sends the reader looking for a
fault that is not there.

**Change:** a null consolidation is now `pass: null` with the reason stated and the remedy named
(`-Only filed,drain`). The drill's exit code already counts only `pass is False`, and the
collision step has answered null on the same grounds since it was written, so this is the
established shape rather than a new one. The hairball warning keeps its teeth: a consolidation
that RAN and produced neither an acceptance nor a rejection still fails. `run-drill.ps1`'s
`-Only` help now names both dependent steps.

**Proven:** four cases in `test_vault_daemon_e2e.py` (20 in total) - an empty queue is null, a
null is not counted as failed, a judged-nothing drain still fails, and a rejection carrying its
reason passes. `scripts/test/run-offline-tests.ps1` green: 58 PASSED, 0 FAILED, 0 NOT RUN.

**Still unmeasured:** the drain's real behaviour against the model. Every drill run so far has
either crashed before the judgment or found an empty queue, so the accept-to-reject ratio that
`daemon.classify_confidence_min` and the hairball warning are read from has not been observed
since the 2026-08-28 classifier change.

## 2026-08-30 - R25, the question-clarity gate, and the hook-deployment hole it uncovered

**Origin:** the professor reported that questions reaching him through `AskUserQuestion` were
vague, unexplained and hard to answer, and asked where a rule requiring the opposite should
live. Nothing in `.claude/rules/` governed what a question must contain, so every session
invented its own standard.

**Change (rule):** `R25` in `.claude/rules/preferences.md`, under a new "Asking the user"
section. A question states the ORIGIN of the choice (file and line, flag, measurement, failing
case), the BEHAVIOUR of each option in its `description` rather than its `label`, the
CONSEQUENCE each option carries, and puts the RECOMMENDED option first, marked. The
rule-identifier index in `code-style.md` now reads `R0` to `R25`.

**Change (mechanism):** `.claude/hooks/askuserquestion-clarity.py`, a `PreToolUse` gate on
`AskUserQuestion` that refuses a call failing those structural minima and returns the reason so
the question is rewritten rather than dropped. Thresholds live in `askuserquestion-clarity.json`
beside it (R0); a missing or unparsable config disables the gate in silence (R11). Declared in
`settings.template.json`, so `Merge-RtGlobalSettings` distributes it additively.

**Measured first, because the documentation does not say:** the Claude Code hook reference names
only `EndConversation` as excluded from `PreToolUse` and says nothing about `AskUserQuestion`. A
throwaway probe hook, installed in the gitignored project `settings.local.json` and removed
afterwards, recorded `tool_name: "AskUserQuestion"`, `hook_event_name: "PreToolUse"` and a
`tool_input` carrying one key, `questions`. Building the gate on an assumption there would have
produced a hook that could never fire.

**The hole this uncovered, and the reason the change is larger than the request:** `setup.ps1
-All` calls `install-junctions.ps1` WITHOUT `-Sync`, and that legacy flow has no hook handling at
all. Hook scripts reach `~/.claude/hooks/` only through `rt-sync.ps1`, whose copy is gated on
`.rt-green.json`, which is gitignored and therefore absent from every clone. `Merge-RtGlobalSettings`
meanwhile did add the hook ENTRIES. A student installing this toolkit therefore received four
hooks declared and none deployed - and a declared hook whose script is absent makes the
interpreter exit non-zero, which refuses every tool in that hook's matcher. That is the
2026-08-27 `vault-access-guard.py` failure, which refused Read, Grep and Bash for four turns,
reproduced by construction on every machine the toolkit was installed on. `check-deployment.ps1`
already printed it as MISSING; nothing acted on it. Adding a fifth hook without fixing this would
have widened it.

`Install-RtGlobalHooks` in `scripts/lib/rt-global-config.ps1` closes it, obeying the same
contract as the two writers beside it: ADD what is absent, never overwrite what the operator
has. A student's own edit to a deployed hook survives byte-identical and is reported as differing
instead, updating being `-Sync`'s job where the file has been proven green. `setup.ps1` calls it
BEFORE the settings merge that declares the hooks, so ordering cannot produce the broken state
even transiently. `rt-sync.ps1`'s hook filter was widened from `.py` to `.py` and `.json` in the
same pass, since a hook whose config did not travel with it disables itself in silence.

**Proven:** `scripts/test/run-offline-tests.ps1` green at 61 PASSED, 0 FAILED, 0 NOT RUN, with
`.claude/hooks/Test/test_askuserquestion_clarity.py` (26 tests) new among them.
`verify-setup-writes.ps1` 46/46 and `verify-sync-writes.ps1` 18/18. The hook suite paid for
itself immediately: it caught a defect where the `(Recommended)` marker, left inside the
normalized label, made the restatement check unable to fire on the recommended option, which is
the one likeliest to carry a lazy description.

**Not done, and deliberately:** the four pre-existing hooks are still not deployed on machines
where setup already ran once. `Install-RtGlobalHooks` seeds only what is ABSENT, so those
machines are fixed by the next `setup.ps1` run, and a machine whose hooks were hand-edited keeps
them. `check-deployment.ps1` remains the way to see the current state.

## 2026-08-30 - setup.ps1 finished the job it only half declared: the vault variable, the Python environment, and a prompt that assumed

**Found:** three gaps that shared one shape - setup reported success, and something it had
never actually done then failed somewhere else, far from the run.

`OBSIDIAN_VAULT` was read by `vault-access-guard.py`, `obsidian-outbox-flush.py`,
`vault_daemon.py`, `run-drill.ps1` and `vault-daemon-autostart.ps1`, because R1 forbids a
hardcoded vault path. No installer in this repository ever set it: measured 2026-08-29,
neither `SetEnvironmentVariable` nor `setx` appeared anywhere. `setup.ps1` asked for the vault
path, substituted it into a document, and stopped. On a fresh machine every one of those five
then refused, and `-InstallDaemon` already had to print a warning about exactly this.

`scripts/test/run-offline-tests.ps1` resolves `.venv-skills\Scripts\python.exe` first, and no
installer created it or installed a requirement. A new user cloned, ran setup, ran the suite,
and read NOT RUN across the thirteen `paper2talk` cases. The runner reports that honestly,
which is why it went unnoticed: nothing was red, the suite simply was not proving what it
looked like it was proving.

And `setup.ps1` had three `Read-Host` prompts plus a `Proceed?` confirmation with no
non-interactive path. With no console attached, `Read-Host` returns empty and the run proceeds
anyway, so a scripted bootstrap silently took every default - including skipping the vault.

**Change:** `Resolve-RtVaultEnvironmentAction` and `Set-RtVaultEnvironment` in
`scripts/lib/rt-daemon-install.ps1`, offered from `setup.ps1` before the Startup entry is
created and re-read afterwards. Add-only, in the shape of the other global writers: an
existing value is printed and kept unless `-Force` confirms a repoint, and a path that does
not exist is refused rather than stored - validated BEFORE the comparison, so the refusal
holds even when the variable is unset and even when confirmation was given. USER scope, never
process scope, because the Startup shortcut passes no argument and a login-started daemon
reads the user environment block.

`scripts/lib/rt-python-env.ps1` and `setup.ps1 -InstallPython`: `.venv-skills` plus what the
offline suite imports, then `pip-audit` on each file per `security.md`. Scope is the suite and
nothing else, chosen by the repository owner over installing all six requirements files -
`docling` alone pulls `torch`, and one CVE in a skill nobody runs would block the environment
the tests need. The heavier optional dependencies stay a manual step, now written down in
README.md as Step 5 rather than left to silence.

`Read-RtAnswer` wraps every prompt: with `-NonInteractive` it refuses with exit 2 (R12) and
names the switch that would have supplied the answer, instead of assuming a default.

**Proven:** `scripts/test/verify-python-env.ps1` (33 checks, new) and
`scripts/test/verify-daemon-install.ps1` (49, up from 22). Both drive the pure decision
functions with injected values and never call the writer, so the live `OBSIDIAN_VAULT` and the
real `.venv-skills` are read once at the top and asserted unchanged at the bottom - the same
discipline the daemon suite already applied to the Startup folder. No pip process is started.
`.\setup.ps1 -Preview -NonInteractive` was run against the live global files and refused with
exit 2 with `~/.claude/CLAUDE.md` and `~/.claude/settings.json` hashed identical before and
after; `.\setup.ps1 -InstallDaemon -Preview` took the add-only branch and printed
`OBSIDIAN_VAULT already holds ...` while changing nothing.

**Still unmeasured:** the `-InstallPython` install path itself. Every check here stops at the
boundary where pip would run, because that needs a network and minutes, so what is proven is
the decision, the refusals and the dry run - not that a fresh `.venv-skills` ends up able to
run the suite. The first person to clone this on a new machine measures that, and the honest
place to find out is `run-offline-tests.ps1` reporting PASSED where it used to report NOT RUN.

## 2026-08-30 - the second memory was routed in prose only, and was bypassed three times

**Found:** `.claude/CLAUDE.md` routes BOTH memories through `local-writer` and says outright that
consulting or refreshing the graph by hand is the same breach as reading the vault by hand. Only
the vault half was ever enforced. `vault-access-guard.py` named the graph nowhere - `graphify`
appeared zero times in its 170 lines - so the graph half held by discipline alone, and discipline
failed in three separate sessions.

The third one is the instructive one, because a path-matching guard would not have caught it. The
session ran `scripts/audit/check-graph-health.ps1` twice, once inside a verification sweep and
once deliberately to learn whether the graph had been refreshed, and the string `graphify-out`
never appeared in either command. The access was hidden by a wrapper, not by a spelling. That is
the 2026-08-27 vault lesson repeating one level up: back then the rule was phrased per COMMAND and
`cat`, `grep` and a Python script walked through it, so it was rephrased per PATH; a read-only
audit script defeats a per-path rule the same way.

A second cause sat underneath: the documentation contradicted itself. `.claude/rules/testing.md`
registered both graph audit scripts as repo audits a session runs, and listed one in a
verification sweep, while the routing table said only `local-writer` touches the graph. A session
following one document broke the other, and both were authoritative.

**Change:** `vault-access-guard.py` gains a graph arm, keeping its filename so the settings entry,
the hook inventory and the existing tests are undisturbed. It refuses three things rather than
one: the `graphify-out/` path, matched wherever it appears like the vault root; the `graphify` CLI
at COMMAND POSITION, so a chained `cd ... && graphify update` is caught while `grep graphify` is
not; and both audit scripts BY NAME, in an executed command only. That last restriction is what
makes the script names safe to guard - matching them against a path key too would have locked the
repository's own audit scripts behind an agent with no business owning them. Running one reads the
graph; maintaining one does not.

The contradiction is closed in the same commit: both scripts' entries in `testing.md` now open
with LOCAL-WRITER ONLY and name the dispatch, and the graphify routing row states that the rule is
enforced rather than merely stated. That row sits inside the RT-EXPORT region, so the sentence
propagates to `CLAUDE.template.md` and from there to every project on the machine, which is U6
doing its job on its first real edit.

**Proven:** `.claude/hooks/Test/test_vault_access_guard.py`, 29 tests, up from 15. The fourteen new
ones pin the three refusals, `local-writer`'s exemption and another subagent's lack of one, the
two arms printing DIFFERENT messages so the reader is sent to the right remedy, and - the half
that decides whether the guard survives contact - four negative controls: `grep graphify`,
`rtk grep graphify`, an `echo` of the word, and reading the vendored
`.claude/skills/graphify/SKILL.md`, which is the skill and not the graph. A guard that fires on
prose gets switched off, and then nothing is enforced at all.

**Still unmeasured:** whether the guard actually refuses this in a live session. It is enforced by
the copy in `~/.claude/hooks/`, which `install-junctions.ps1 -Sync` deploys only from a green
tree, so the earliest proof is the next session's first attempt. The tests prove the decision; the
deployment proves the enforcement, and those are different claims.
