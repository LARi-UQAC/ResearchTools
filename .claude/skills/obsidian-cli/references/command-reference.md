# Obsidian CLI - command reference for this vault

Syntax of the commands this vault allows, and the status of every other command of the
upstream CLI (v1.12+). The doctrine and the measured reasons for the forbidden commands live in
`../SKILL.md` and are not restated here, nor is the write path (the outbox, same file).

**Syntax**: `obsidian <command> [key=value ...] [flags]`. Parameters take no dashes. Quote
values containing spaces: `content="hello world"`. Paths are vault-relative, with the `.md`
extension. Command names below were checked against `obsidian help` on 2026-11-15; the
`property:read`, `files` and `folders` options were read from `obsidian help <command>`, the
rest is copied from the upstream manual and not re-measured.

## Status of every command

| Status | Commands |
|---|---|
| **Allowed** (syntax below) | `read`, `search`, `files`, `folders`, `property:read`, `property:set`, `tasks`, `links`, `tags`, `move`, `rename`, and the read-only `sync:history` |
| **Forbidden** (see `../SKILL.md`) | `create`, `append`, `prepend`, `daily:append`, `daily:prepend`, `eval`, `devtools`, every `dev:*` (`dev:screenshot`, `dev:debug`, `dev:console`, `dev:errors`, `dev:dom`, `dev:css`, `dev:cdp`, `dev:mobile`), `plugin:install`, `theme:install`, every `sync*` except `sync:history` |
| **Confirm with the owner first** - writes to notes | `delete`, `task` (toggle, done, todo), `base:create`, `property:remove`, `template:insert`, `history:restore` |
| **Confirm with the owner first** - changes the app | `daily` (creates today's note, a layer retired 2026-08-03), `command id=`, `reload`, `restart`, `tab:open`, `plugin:enable`, `plugin:disable`, `plugin:uninstall`, `plugin:reload`, `plugins:restrict`, `theme:set`, `theme:uninstall`, `snippet:enable`, `snippet:disable`, `random` |
| **Confirm with the owner first** - read-only extras | `properties`, `aliases`, `search:context`, `search:open`, `tag`, `backlinks`, `unresolved`, `orphans`, `deadends`, `file`, `outline`, `wordcount`, `recents`, `vault`, `vaults`, `version`, `daily:read`, `daily:path`, `bases`, `base:query`, `base:views`, `templates`, `template:read`, `bookmarks`, `hotkeys`, `commands`, `history:list`, `history`, `history:read`, `workspace`, `tabs`, `diff`, `plugins`, `themes`, `snippets` |

A command absent from this table is not allowed: ask the owner (global rule), and add it here
once decided.

## Allowed commands

### Read, search

```bash
obsidian read path="folder/note.md"                  # raw markdown to stdout
obsidian search query="text"                         # file paths, most relevant first
obsidian search query="text" path="folder" limit=10  # scope to a folder, cap the count
obsidian search query="text" format=json             # JSON array of file paths
obsidian search query="text" case                    # case-sensitive
```

`search` returns paths only: the `matches` flag is accepted but returns no context in v1.12.

### List files and folders

```bash
obsidian files                      # every file
obsidian files ext=md folder="sub"  # filter by extension and folder
obsidian files total                # the count only
obsidian folders                    # every folder (folder= and total also accepted)
```

### Properties

```bash
obsidian property:read path="note.md" name="status"            # one value (file= also accepted)
obsidian property:set path="note.md" name="status" value="active"
```

`property:set` always stores `value=` as a string, so `value="[a, b]"` writes the literal
text, not a YAML array. For a true array, or for a clean in-place edit through the outbox, use
the `set-property` directive of `../SKILL.md`; there is no CLI substitute for an array.

### Tasks, links, tags

```bash
obsidian tasks                    # all tasks, complete and incomplete (v1.12 has no incomplete-only filter)
obsidian tasks done               # completed tasks only
obsidian tasks path="note.md"     # tasks of one file
obsidian links path="note.md"     # outgoing links of a note
obsidian tags                     # all tags
obsidian tags counts sort=count   # usage counts, most used first
obsidian tags path="note.md"      # tags of one note
```

### Move and rename

```bash
obsidian move path="old/note.md" to="new/note.md"   # to= is the full target path with .md
obsidian rename path="folder/note.md" name="new-name"   # name= is the file name only
```

`move` into a folder that does not exist fails `ENOENT` and still exits 0, so create the parent
first. Use `move` rather than `rename` when the folder changes.

### Read-only version history

```bash
obsidian sync:history path="note.md"   # versions of a file, read-only
```

## Output formats

`format=` takes `text` (default), `json`, `csv`, `tsv`, `yaml`, `md`, `paths` or `tree`, but not
every command accepts every format: use `text` or `json` when in doubt. Pipe `text` into
standard tools, and use `format=json` for a script.
