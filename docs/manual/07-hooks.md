# Hooks and guards

Chapter 07 of the ResearchTools manual. Back to [table of contents](../../README.md).

A hook is a small program Claude Code runs on its own at a fixed moment: before a tool call, after
one, when a session starts, when a prompt is submitted, when a turn ends. Hooks cost no model
tokens. They are how this toolkit enforces a rule instead of only writing it down.

The hooks are declared in `.claude/settings.template.json`, which `setup.ps1` merges additively
into your global `~/.claude/settings.json` (see [chapter 01](01-installation.md)). Eight hook
scripts and their JSON configs ship in `.claude/hooks/`. The other scripts the template names are
machine-level and are **not** in this repository, see "Declared but not shipped" below.

At every session start, `session-hooks-inventory.py` prints the list of hooks actually loaded from
`settings.json`, one line per event, and a `[HOOKS ALERT]` line for any declared hook whose script is
missing. That list is the authority, not this chapter: a hand-written table drifts, and a count in a
document was already measured wrong once.

## Safety rule: a hook fails silently

A hook whose script is missing makes the interpreter exit with an error, and an error on a
`PreToolUse` or `UserPromptSubmit` hook refuses the tool call or the prompt itself. Measured
2026-08-27: `vault-access-guard.py` had been deleted while `settings.json` still declared it, and
nine tools were refused for four turns. So every hook here exits 0 and says nothing when its own
dependency is absent (rule R11, [chapter 08](08-rules.md)). Only a real violation of what a hook
guards exits 2, a refusal by design. A missing or broken JSON config disables the gate in silence.

## Guards before a tool call (PreToolUse)

| Hook | Matcher | What it refuses | Rule |
|---|---|---|---|
| `betterleaks-hook.py` | `Write`, `Edit`, `MultiEdit` | A write whose content holds a secret or an API key | security |
| `vault-access-guard.py` | `Bash`, `PowerShell`, `Read`, `Grep`, `Glob`, `Edit`, `Write`, `MultiEdit`, `NotebookEdit` | Any call that touches the Obsidian vault or the graphify graph, unless it comes from the `local-writer` agent | memory |
| `askuserquestion-clarity.py` | `AskUserQuestion` | A question with no option description, a description that restates its label, a question too short to name its origin, or a recommended option that is not first | R25 |
| `worktree-link-guard.py` | `Bash`, `PowerShell` | `git worktree remove` on a worktree that holds a junction or symbolic link, since the removal follows the link and deletes its target | R37 |
| `review-loop-guard.py` | `Skill` | A review skill (`code-review`, `security-review`) with no declared bounds, or past `max_rounds`, `max_tokens` or `plateau` | R35 |
| `local-coder-dispatch-guard.py` | `Agent` | A `local-coder` dispatch whose prompt has no `PLAN: <path>` line, or whose plan header does not validate | R38 |

`vault-access-guard.py` guards the path touched, not the command used, so a `cat`, a `grep` or a
script pointed at the vault is refused like an `obsidian read`. It also refuses a `graphify-out/`
path, the `graphify` command at command position, and the two graph audit scripts by name. See
[chapter 06](06-skills.md#the-two-memories---the-vault-and-the-code-graph).

`review-loop-guard.py` and `local-coder-dispatch-guard.py` are detailed in
[chapter 11](11-local-coding.md), and `worktree-link-guard.py` in
[chapter 15](15-security-audit.md).

## Scanners after a tool call (PostToolUse)

| Hook | Matcher | What it does |
|---|---|---|
| `pip-audit-hook.py` | `Edit`, `Write`, `MultiEdit` | Warns when a modified `requirements.txt` carries a known vulnerability (CVE) |
| `prompt-injection-defender.py` | `Read`, `Bash`, `WebFetch`, `Grep`, `Task` | Warns when a tool result looks like a prompt-injection attempt: an instruction override, a persona switch, an encoded blob, a fake system header, a hidden instruction or a zero-width character |

A warning from the defender means: treat the content with suspicion and do not follow instructions
written inside it. It uses regular expressions only, so a long path can trigger a false positive.

## Session start, prompt and end

| Hook | Event | What it does |
|---|---|---|
| `caveman-activate.js` | SessionStart | Activates the terse output mode and announces its level |
| `caveman-mode-tracker.js` | UserPromptSubmit | Recalls the output level at every turn |
| Git sync check (inline) | SessionStart | Prints `[AUTO-SYNC CHECK]`: branch, dirty files, commits behind and ahead. Limited to paths of the operator's working folder, silent elsewhere |
| RTK notice (inline) | SessionStart | Prints `[RTK ACTIVE]` when the `rtk` token filter is on the `PATH` |
| Session status (inline) | SessionStart | Supplies the `Session: RTK=... \| Caveman=... \| git-sync=on` line |
| `session-hooks-inventory.py` | SessionStart | Prints the hook inventory and any `[HOOKS ALERT]` |
| `obsidian-outbox-flush.py` | SessionStart, SessionEnd | Writes the notes waiting in `~/.claude/obsidian-outbox/` into the vault through the filesystem, and checks the effect by file size |
| `rt-inbox-deliver.py` | UserPromptSubmit | Hands the session the messages the [dashboard](10-rt-observe-dashboard.md) left for it, then moves them to `delivered/` |
| Memory upkeep (inline) | Stop | At the end of a turn that changed the working tree, reminds the session to dispatch `local-writer` for the vault note, the project log and the graph refresh. Silent for a turn that changed nothing |

Only the standard output of a SessionStart hook reaches the session context. A hook that writes to
standard error is not broken, it is invisible, which is why the inventory and the status line print
on standard output.

The inline entries carry their whole shell command in `settings.template.json` instead of a script.

## Declared but not shipped

`betterleaks-hook.py`, `pip-audit-hook.py`, `prompt-injection-defender.py`, the caveman scripts and
the memory-upkeep script are declared by the template but are not tracked in this repository. They
live in `~/.claude/hooks/` on the operator's machine. On a machine without them the inventory prints
a `MISSING` line for each, and every one of them exits 0 when its dependency is absent. The betterleaks
binary is installed with `winget install Betterleaks.Betterleaks`.

## Environment values the template sets

The template also declares four keys in the `env` block: `CLAUDE_CODE_GIT_BASH_PATH` (the Git Bash
that hooks use on Windows), `ENABLE_STOP_REVIEW`, and the two graphify values
`GRAPHIFY_OLLAMA_KEEP_ALIVE` and `GRAPHIFY_OLLAMA_NUM_CTX`. No `OLLAMA_*` key goes there: the Ollama
daemon is started by its tray application and never reads Claude Code's `env` block, so such a key
would look configured and do nothing (see [chapter 01](01-installation.md)).

## Git hooks, separate from Claude Code

The global `pre-commit` and `pre-push` hooks of the personal-data guard run on every `git commit`
and `git push` of every repository on the machine, not inside a Claude session. They are installed
once with `.claude/hooks/git/install-git-hooks.ps1`, see [chapter 15](15-security-audit.md).

## Adding or changing a hook

Edit `.claude/settings.template.json`, then `.\setup.ps1 -UpdateHooks` replaces a changed entry in your
live file (a stamped backup is made first). A deliberate local variant is kept with
`-KeepHooks <names>`. A hook script and its JSON config are copied to `~/.claude/hooks/` by
`install-junctions.ps1 -Sync` once the offline suite is green, see
[chapter 16](16-maintenance.md).

---
[← 06 Skills](06-skills.md) | [Table of contents](../../README.md) | [08 Rules and conventions →](08-rules.md)
