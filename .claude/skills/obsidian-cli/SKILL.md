---
name: obsidian-cli
description: Use when a task needs Claude to act on the Obsidian vault - read or search a note, list or count notes, inspect tags, tasks, links or properties, move or rename a file, or deposit a captured learning for the vault. Also use when a vault write appeared to succeed but the note is absent, when a numbered duplicate such as "Decisions 1.md" appears, or when Obsidian shows "A JavaScript error occurred in the main process". Skip for questions about the Obsidian GUI, themes, plugins or sync conflicts, where an explanation is wanted rather than a vault operation.
---

# Obsidian CLI

Vault root: `OBSIDIAN_VAULT` (default `C:\Martin Otis\Vault`). Write
vault-internal paths relative to that root, e.g.
`30_Ressources/Obsidian/_Convention_Capture.md`, never a drive letter.

## Writing to the vault

Write sequence:

1. Draft the note body.
2. Write it to `~/.claude/obsidian-outbox/<slug>.md`. First line:
   `<!-- obsidian: create|append path="..." -->` - lowercase `obsidian:`,
   whole line, nothing after `-->`, or the file is skipped silently and
   stays in the outbox. Rest is content. Default to `create`: it degrades
   to `append` on an existing file and skips a body already present, so a
   replay never doubles the note.
3. `path=` is vault-relative only - no leading slash, no drive letter (a
   leading slash escapes the join on Windows, landing outside the vault,
   which the hook refuses). The outbox filename is scratch; only `path=`
   decides the target. No folder needs preparing - the hook creates any
   missing parent, so never `move` a note into place first.
4. `obsidian-outbox-flush.py` runs at SessionStart and SessionEnd only, not
   continuously, so a note waits until one fires: never report a write as
   done before it has. It processes files alphabetically, not by age;
   competing appends follow filename order. It verifies the effect by file
   size before/after and only then moves a file to `outbox/sent/`; one left
   behind means the write did not land, and nothing is lost - it flushes at
   the next start.
5. Obsidian watches the disk and reloads on its own once the file lands.

This is the write path, not a fallback.

## Forbidden commands

`create`, `append`, `prepend` - including `daily:*` writes (`daily:append`,
`daily:prepend`): that daily-note layer was retired 2026-08-03. Also
`eval`, `dev:*`, `plugin:install`, `theme:install`, every `sync*` except
read-only `sync:history`.

`create`/`append`/`prepend` carry a measured reason:

- Failure is in the whole JSON header (content, path, `tty`/`cwd`), not
  content alone: 3850 bytes passes, 4343 does not, 4096 - a Windows
  named-pipe buffer - falls between. Reproduced on 1.13.4 and 1.13.7; trace
  in `.claude/hooks/obsidian-outbox-flush.py`.
- Exits 0 on failure too: archives notes never written.
- `create` on an existing file writes a numbered duplicate
  (`Decisions 1.md`) instead of failing.

Cause stays open: chunk reassembly, newline framing, and split UTF-8 were
checked and ruled out. Unproven: a client exiting before `drain`.

## Allowed surface

`read`, `search`, `list`, `property:get`, `property:set`, `tasks`, `links`,
`tags`, `move`, `rename`. Full syntax: `references/command-reference.md`.

Traps: `obsidian create --help` creates `Untitled.md`, not help - use
`obsidian help <command>`; parameters take no dashes (`path=`, `to=`,
`content=`); `obsidian move` to a missing folder fails `ENOENT` without
creating it, while exiting 0 - create the parent first.

Transport: Git Bash needs `~/bin/obsidian` (bare `obsidian` resolves to
`Obsidian.exe` and hangs); PowerShell calls `Obsidian.com` directly.

## Rationalization table

| Excuse | Reality |
|---|---|
| "Short note, under the threshold" | Threshold is the whole header; a note grows and breaks later. |
| "The command returned 0" | Returns 0 on failure too. Only a disk size change is evidence. |
| "create just for an empty index.md" | Forks a numbered duplicate on an existing file. Use the outbox. |
| "The reference documents append, so it's supported" | Documents an API, not this vault's measured constraints. |
| "Exit 0 is Unix convention for success" | Not measured here either: check the file's size before/after - the only real evidence. |
| "Empty stderr means no problem" | Measured empty on a run where the note never reached the vault. |
| "content= has no stated size limit" | Undocumented, not unmeasured: the limit is the header size. |
| "Command finished, so the write is done" | Hook checks size before/after; a bare call checks nothing. |
| "Colons unavailable, fall back to daily:path + append" | This vault's Windows Git Bash case, but `append` still risks truncation, targeting a daily layer retired 2026-08-03. |

## Where a captured learning goes

`scripts/vault_consolidate.py` (this skill's directory): deterministic half
of consolidation, measures shared tags/`domaine`/term overlap, proposes
links, decides nothing. `--mode links` additionally reports dead wiki-links
read-only, and `--apply <map.json> --yes` is the one guarded exception to
the outbox-only write rule: a dry-run-by-default, path-escape-refused,
map-validated, single-pass rewrite of existing links, run only by
`local-writer`.

New notes follow `30_Ressources/Obsidian/_Convention_Capture.md`: filed by
technology, never by project.
