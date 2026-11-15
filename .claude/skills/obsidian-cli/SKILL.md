---
name: obsidian-cli
description: Use when a task needs Claude to act on the Obsidian vault - read or search a note, list or count notes, inspect tags, tasks, links or properties, move or rename a file, or deposit a captured learning for the vault. Also use when a vault write appeared to succeed but the note is absent, when a numbered duplicate such as "Decisions 1.md" appears, or when Obsidian shows "A JavaScript error occurred in the main process". Skip for questions about the Obsidian GUI, themes, plugins or sync conflicts, where an explanation is wanted rather than a vault operation.
---

# Obsidian CLI

Vault root: `OBSIDIAN_VAULT` (default `C:\Martin Otis\Vault`). Every vault-internal path is
relative to that root, with no leading slash and no drive letter, e.g.
`30_Ressources/Obsidian/_Convention_Capture.md`. A leading slash escapes the join on Windows and
lands outside the vault, which the hook refuses.

## Writing to the vault

The outbox is the write path, not a fallback.

1. Draft the note body to a scratch file, and keep the facts you were given, verbatim, in a
   brief file.
2. Stage it with `scripts/note_fidelity.py --brief <brief> --note <draft> --stage <slug>`. It
   writes `~/.claude/obsidian-outbox/<slug>.md` ONLY when every number, identifier, file name,
   commit hash and `[[link]]` of the draft appears in the brief, and otherwise stages nothing and
   exits 2 (measured 2026-09-26: one run's five drafts all carried invented facts, and six writes
   had to be undone from the journal). It cannot see a claim re-worded into its opposite, so the
   staged note is still read.
3. First line of the staged file: `<!-- obsidian: create|append path="..." -->` - lowercase
   `obsidian:`, whole line, nothing after `-->`, or the file is skipped silently and stays in the
   outbox. The rest is the content. Default to `create`: it degrades to `append` on an existing
   file and skips a body already present, so a replay never doubles the note. The outbox filename
   is scratch, only `path=` decides the target, and no folder needs preparing: the hook creates
   any missing parent, so never `move` a note into place first.
4. `obsidian-outbox-flush.py` runs at SessionStart and SessionEnd only, not continuously, so a
   note waits until one fires: never report a write as done before it has. It processes files
   alphabetically, not by age, so competing appends follow filename order. It verifies the effect
   by file size before and after and only then moves a file to `outbox/sent/`. A file left behind
   means the write did not land, and nothing is lost: it flushes at the next start.
5. Obsidian watches the disk and reloads on its own once the file lands.

A second entry point exists for a learning whose destination needs no judgment: drop it unrouted
in `~/.claude/obsidian-outbox/raw/` (format in the `local-writer` agent definition) and
`vault_daemon.py` classifies, files and journals it, parking what it is unsure about in
`outbox/needs-review/`.

### Editing one frontmatter property in place

`create` and `append` can only ADD a block after whatever is already in the file, so both degrade
to a second, dead `---` block on a note that already has frontmatter, never the first block that
Obsidian and `daemon_graph.read_repo_property` read. To set or replace one existing key (for
example `repo:` on a project note), use a third directive, added 2026-10-02:

```
<!-- obsidian: set-property path="..." key="repo" -->
the-single-line-value
```

- `path=` follows the same relative-path rule, and the target note MUST already exist: this
  directive never creates a file.
- `key=` is the frontmatter key to set or replace. Every other key, the body and the line order
  are left untouched.
- The value is everything after the directive line and MUST be one line: a value containing a CR
  or LF is refused before the file is touched.

The CLI's `property:set` is the short-operation alternative for a non-sensitive string value.
Prefer the directive when the note is staged through the outbox anyway.

## Forbidden commands

`create`, `append`, `prepend`, including the `daily:append` and `daily:prepend` writes (the
daily-note layer was retired 2026-08-03). Also `eval`, `dev:*`, `devtools`, `plugin:install`,
`theme:install`, and every `sync*` except read-only `sync:history`.

The measured reason for `create`, `append` and `prepend`:

- The failure is in the whole JSON header (content, path, `tty` and `cwd`), not the content
  alone: a 3850-byte header passes, a 4343-byte one does not, and 4096 bytes, a Windows
  named-pipe buffer, falls between. Reproduced on Obsidian 1.13.4 and 1.13.7; trace in
  `.claude/hooks/obsidian-outbox-flush.py`.
- The CLI exits 0 on failure too, so a script that checks the return code archives notes that
  were never written.
- `create` on an existing file writes a numbered duplicate (`Decisions 1.md`) instead of failing.

The cause stays open: chunk reassembly, newline framing and split UTF-8 were checked and ruled
out, and a client exiting before `drain` is unproven.

## Allowed surface

`read`, `search`, `files`, `folders`, `property:read`, `property:set`, `tasks`, `links`, `tags`,
`move`, `rename` (command names checked against `obsidian help` on 2026-11-15; there is no
`list` and no `property:get`). Any other command needs the owner's explicit confirmation first.
Syntax, and the status of every other command, are in `references/command-reference.md`.

Traps: `obsidian create --help` creates `Untitled.md`, not help, so use `obsidian help
<command>`. Parameters take no dashes (`path=`, `to=`, `content=`). `obsidian move` into a
missing folder fails `ENOENT` without creating it, while exiting 0: create the parent first.

Transport: Git Bash needs `~/bin/obsidian` (bare `obsidian` resolves to `Obsidian.exe` and
hangs). PowerShell calls `Obsidian.com` directly.

## Rationalization table

| Excuse | Reality |
|---|---|
| "Short note, under the threshold", "content= has no stated size limit" | The threshold is the whole header, undocumented rather than unmeasured. A note grows and breaks later. |
| "The command returned 0", "stderr is empty", "the command finished" | It returns 0 and prints nothing on a run where the note never arrived. Only a change in the file's size is evidence. |
| "create just for an empty index.md" | On an existing file it forks a numbered duplicate. Use the outbox. |
| "The reference documents append, so it is supported" | It documents the upstream API, not this vault's measured constraints. |

## Where a captured learning goes

`scripts/vault_consolidate.py` is the deterministic half of consolidation: it measures shared
tags, `domaine` and term overlap, proposes links and decides nothing. `--mode links` also
reports dead wiki-links, read-only. `--apply <map.json> --yes` is the one guarded exception to
the outbox-only write rule: a dry-run-by-default, path-escape-refused, map-validated, single-pass
rewrite of existing links, run only by `local-writer`.

New notes follow `30_Ressources/Obsidian/_Convention_Capture.md`: filed by technology, never by
project.

## Vault event daemon's ask queue

`vault_daemon.py` also drains a read-only ask queue (`daemon_ask.py`): a question written to
`~/.claude/obsidian-outbox/ask/requests/<id>.json` is answered by searching the vault and
calling the local LLM, with the answer written to `ask/answers/<id>.json`. The queue is gated to
requests declaring `"from": "rt-dashboard"`, and anything else is answered `status: "refused"`.
Graph-shaped questions call `graphify query` (read-only, never `update` or `save-result`). The
daemon resolves the repository from the vault hit's own `index.md` property, and queries its
graph only when that repository root is listed in the machine-local, gitignored
`.claude/local-ask-graph-roots.json`; an absent or empty file refuses every graph (see
`.claude/rules/security.md`). Vault results are published first through an injected callback,
then the graph part. Keys: `daemon-config.json`, `ask_search_roots` and `ask_graph_*`. This is the
mechanism behind the rt-dashboard voice panel; the `rt-observe` skill documents the other half.
