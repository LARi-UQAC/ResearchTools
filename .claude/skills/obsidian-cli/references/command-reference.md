# Obsidian CLI - Full Command Reference

Complete reference for all official Obsidian CLI commands (v1.12+), corrected for use in
this vault. Several commands documented below are forbidden here even though the upstream
CLI supports them; each forbidden entry is marked at its point of use with the reason and a
pointer back to `../SKILL.md`. The doctrine and rationale live in `SKILL.md`; this file is
the command inventory (syntax, flags, output formats) and does not restate that argument.

**Syntax**: `obsidian [vault] <command> [subcommand] [key=value ...] [flags]`

All parameters use `key=value` syntax. Quote values containing spaces: `content="hello world"`.

---

## Writing to This Vault: the Outbox Pattern

Read this before the Files or Daily Notes sections below. `create`, `append`, `prepend`,
and `daily:append`/`daily:prepend` are forbidden in this vault (see `../SKILL.md`, section
"Forbidden commands", for the measured reasons). Every write goes through the outbox
instead; the vault root is read from the `OBSIDIAN_VAULT` environment variable (documented
default `C:\Martin Otis\Vault`), never a hand-written drive letter.

Worked example, replacing what `create` or `daily:append` would otherwise have done:

1. Draft the note body.
2. Write one file to `~/.claude/obsidian-outbox/<name>.md`. Its first line is the
   directive, the rest is the content:

   ```
   <!-- obsidian: create path="30_Ressources/<Technology>/<note>.md" -->
   # <Note title>

   <body text>
   ```

3. On the next SessionStart or SessionEnd, `.claude/hooks/obsidian-outbox-flush.py`
   delivers it from disk, not by calling the CLI:
   - it creates any missing parent folder under the vault root;
   - if the target file already exists, it degrades the `create` to an append, and if the
     body is already present in the file it treats the note as already delivered instead
     of duplicating it;
   - it matches the first line against an exact regex; a malformed directive leaves the
     file untouched in the outbox rather than guessing at the intent;
   - it refuses to write to a path that resolves outside the vault root;
   - it verifies the write by comparing the file's size before and after, since a return
     code is not trustworthy evidence for this CLI (see `../SKILL.md`).
4. Obsidian itself is never called for the write; it watches the filesystem and reloads
   the note on its own.

This single pattern is what replaces both the daily-note write commands and the
`create`-with-template pattern documented further below. There is no case in this vault
where calling the CLI to perform a write is the correct next step; the outbox is the write
path, not a fallback.

---

## Table of Contents

1. [Files](#files)
2. [Daily Notes](#daily-notes)
3. [Search](#search)
4. [Properties](#properties)
5. [Tags](#tags)
6. [Tasks](#tasks)
7. [Links](#links)
8. [Bookmarks](#bookmarks)
9. [Templates](#templates)
10. [Plugins](#plugins)
11. [Sync](#sync)
12. [Themes](#themes)
13. [CSS Snippets](#css-snippets)
14. [Commands & Hotkeys](#commands--hotkeys)
15. [Obsidian Bases](#obsidian-bases)
16. [History](#history)
17. [Workspace & Tabs](#workspace--tabs)
18. [Diff](#diff)
19. [Developer](#developer)
20. [Vault & System](#vault--system)

---

## Files

File operations: read, write, create, move, delete, list.

### Reading Notes

```bash
obsidian read path="folder/note.md"
```

Prints raw markdown content of a note to stdout. Path is vault-relative.

### Creating Notes

```bash
obsidian create path="folder/note" content="# Title\n\nBody text"  # FORBIDDEN in this vault
obsidian create path="folder/note" template="template-name"        # FORBIDDEN in this vault
```

- Path should **not** include `.md` - it is appended automatically.
- Use `template=` to create from a template file.
- Use `content=` to set initial content directly.

**FORBIDDEN in this vault:** `create` - the CLI truncates past a threshold on the whole
JSON header and the write silently does not happen, it exits 0 even on failure, and
`create` on an existing file writes a numbered duplicate such as `Decisions 1.md`. See
`../SKILL.md`, section "Forbidden commands", and the [outbox pattern](#writing-to-this-vault-the-outbox-pattern)
above, which is what to use instead - including in place of the `template=` form.

### Appending & Prepending

```bash
obsidian append path="folder/note.md" content="Appended text"    # FORBIDDEN in this vault
obsidian prepend path="folder/note.md" content="Prepended text"  # FORBIDDEN in this vault
```

- `append` adds content at the end of the file.
- `prepend` adds content after the frontmatter (not at byte 0).

**FORBIDDEN in this vault:** `append` and `prepend` - the CLI truncates past a threshold on
the whole JSON header and the write silently does not happen, it exits 0 even on failure,
and (for the `create` sibling of this pair) an existing file gets a numbered duplicate
instead of a clean write. See `../SKILL.md`, section "Forbidden commands", and the
[outbox pattern](#writing-to-this-vault-the-outbox-pattern) above.

### Moving & Renaming

```bash
obsidian move path="old/path/note.md" to="new/path/note.md"
```

- `to=` is the full vault-relative target path including the `.md` extension.
- Can be used to move, rename, or both in a single command.
- Moving into a folder that does not yet exist fails with `ENOENT` and exits 0 without
  creating the tree; create the parent folder first (see `../SKILL.md`, "Allowed surface").

### Deleting

```bash
obsidian delete path="folder/note.md"           # Moves to trash
obsidian delete path="folder/note.md" permanent  # Permanent deletion
```

### File Discovery

```bash
obsidian files                       # List all files in vault
obsidian files ext=md                # Filter by extension
obsidian files folder="subfolder"    # Files in specific folder
obsidian files total                 # Just the file count
obsidian folders                     # List all folders
obsidian file path="folder/note.md"  # File info (size, created, modified dates)
```

### Random Notes

```bash
obsidian random           # Open a random note in Obsidian
obsidian random:read      # Print content of a random note to stdout
```

### Renaming

```bash
obsidian rename path="folder/note.md" name="new-name"
```

- `name=` is the new filename only (no path, no `.md` extension).
- Use `move` when you also want to change the folder.

---

## Daily Notes

Operations on the daily note (requires Daily Notes core plugin enabled). In this vault the
"one note per day" convention itself was retired on 2026-08-03 (root `CLAUDE.md`); the read
commands below remain accurate for the underlying CLI, but there is no daily-note write
target to append or prepend to.

```bash
obsidian daily                           # Open today's daily note in Obsidian
obsidian daily:read                      # Print today's daily note content to stdout
obsidian daily:append content="text"     # FORBIDDEN in this vault
obsidian daily:prepend content="text"    # FORBIDDEN in this vault
obsidian daily:path                      # Print vault-relative path of today's note
```

**FORBIDDEN in this vault:** `daily:append` and `daily:prepend` - both are writes, and the
daily-note layer itself was retired on 2026-08-03, so there is no daily note to append to.
See `../SKILL.md`, section "Forbidden commands", and the
[outbox pattern](#writing-to-this-vault-the-outbox-pattern) above.

**Notes:**
- `daily:prepend` inserts content after the frontmatter block, not at the very beginning.
- If today's note doesn't exist, `daily` will create it (using the configured template if set).
- Daily note format/folder are configured in Obsidian's Daily Notes plugin settings.

---

## Search

Full-text search across the vault.

```bash
obsidian search query="search text"
obsidian search query="text" path="folder"         # Scope to folder
obsidian search query="text" limit=10               # Limit results
obsidian search query="text" format=json            # JSON output (array of file paths)
obsidian search query="text" matches                # Accepted but returns file paths only
obsidian search query="text" case                   # Case-sensitive search
```

**Parameters:**
- `query=` - Search term (required)
- `path=` - Restrict search to a folder
- `limit=` - Maximum number of results
- `format=json` - Returns a JSON array of matching file paths: `["folder/note.md", ...]`
- `matches` - Flag accepted by the CLI but does not return match context/snippets in v1.12
- `case` - Enable case-sensitive matching

### Search with Context

```bash
obsidian search:context query="search text"
obsidian search:context query="text" path="folder" limit=10
obsidian search:context query="text" case
obsidian search:context query="text" format=json
```

Returns matching lines with surrounding context (not just file paths). Useful when you need to see the actual content that matched rather than just file paths.

### Open Search View

```bash
obsidian search:open query="search text"
```

Opens the Obsidian search panel in the UI with the given query.

---

## Properties

Manage frontmatter (YAML metadata) on notes.

### Read All Properties

```bash
obsidian properties path="note.md"
```

### Read Single Property

```bash
obsidian property:read path="note.md" name="status"
```

### Set Property

```bash
obsidian property:set path="note.md" name="status" value="active"
obsidian property:set path="note.md" name="tags" value="[project, alpha]"
obsidian property:set path="note.md" name="date" value="2026-02-27"
```

> **Note:** `property:set` always stores `value=` as a string. Passing `value="[project, alpha]"` writes
> the literal string `[project, alpha]`, not a YAML array. For true array-typed properties (e.g. `tags`),
> edit the note's frontmatter directly instead of reaching for `eval` with the Obsidian API.
>
> **FORBIDDEN in this vault:** `eval` - arbitrary JavaScript and unguarded devtools access
> against the whole vault. See `../SKILL.md`, section "Forbidden commands". Editing the
> note's frontmatter directly is the only option here; there is no outbox substitute for an
> in-place property edit on an existing note.

### Remove Property

```bash
obsidian property:remove path="note.md" name="draft"
```

### Aliases

```bash
obsidian aliases path="note.md"
```

Lists all aliases defined in the note's frontmatter.

---

## Tags

Tag discovery and filtering.

```bash
obsidian tags                          # List all tags in the vault
obsidian tags counts                   # Tags with usage counts
obsidian tags counts sort=count        # Sorted by frequency (most used first)
obsidian tags path="note.md"           # Tags in a specific file
obsidian tag name="project/alpha"      # List notes with a specific tag
```

**Notes:**
- Nested tags are supported (e.g., `project/alpha`).
- Tags from both frontmatter and inline `#tag` syntax are included.

---

## Tasks

Query and manage checkbox tasks across the vault.

### Querying Tasks

```bash
obsidian tasks                         # All tasks (same as tasks all in v1.12)
obsidian tasks all                     # All tasks (complete + incomplete)
obsidian tasks done                    # Only completed tasks
obsidian tasks path="note.md"          # Tasks in a specific file
obsidian tasks daily                   # Tasks in today's daily note
```

> **Note:** In v1.12, `tasks` with no arguments returns all tasks (complete + incomplete), identical to `tasks all`. Filtering to incomplete-only is not currently supported without post-processing (e.g. pipe to `grep "\[ \]"`).

### Toggling Task Status

```bash
obsidian task path="note.md" line=12 toggle
```

Toggles the checkbox on the specified line number between `- [ ]` and `- [x]`.

---

## Links

Graph analysis and link management.

```bash
obsidian backlinks path="note.md"         # Notes linking TO this note
obsidian backlinks path="note.md" counts  # With link counts per file
obsidian links path="note.md"             # Outgoing links FROM this note
obsidian unresolved                        # All unresolved [[wikilinks]]
obsidian orphans                           # Notes with no incoming or outgoing links
obsidian deadends                          # Notes with no outgoing links
```

---

## Bookmarks

Manage Obsidian bookmarks (requires Bookmarks core plugin).

```bash
obsidian bookmarks                                      # List all bookmarks
obsidian bookmark file="folder/note.md"                 # Bookmark a note
obsidian bookmark file="folder/note.md" subpath="#Heading"  # Bookmark a heading
obsidian bookmark folder="projects"                     # Bookmark a folder
obsidian bookmark search="query text" title="My Search" # Bookmark a search
obsidian bookmark url="https://example.com" title="Link" # Bookmark a URL
```

---

## Templates

Work with note templates (requires Templates or Templater plugin).

```bash
obsidian templates                                      # List available templates
obsidian template:read name="weekly-review"             # Read template content
obsidian template:read name="weekly-review" resolve title="My Note"  # Render with variables
obsidian template:insert name="weekly-review"           # Insert template into the active Obsidian UI file
```

**Parameters:**
- `name=` - Template name (without path prefix or extension)
- `resolve` - Process template variables (`{{date}}`, `{{title}}`, etc.)
- Title and other variables can be passed as `key=value` for template rendering.

> **Note:** `template:insert` inserts into whichever file is currently active in the Obsidian UI - it does not accept a `path=` parameter. If no file is open, it returns `Error: No active editor. Open a file first.`
>
> **FORBIDDEN in this vault:** creating a new file from a template with
> `obsidian create path="..." template="..."` - the same `create` failure mode applies
> (truncation past a header threshold, exit 0 on failure, numbered duplicate on an existing
> file). See `../SKILL.md`, section "Forbidden commands". Use the
> [outbox pattern](#writing-to-this-vault-the-outbox-pattern) above: draft the body,
> including whatever the template would have supplied, and deposit it in the outbox.

---

## Plugins

Manage community and core plugins.

```bash
obsidian plugins                         # List all plugins (core + community)
obsidian plugins:enabled                 # Only enabled plugins
obsidian plugins versions                # Plugins with version numbers (community only)
obsidian plugins:restrict                # Show restricted mode status
obsidian plugins:restrict on             # Enable restricted mode (disables community plugins)
obsidian plugins:restrict off            # Disable restricted mode
obsidian plugin id="dataview"            # Get info about a specific plugin
obsidian plugin:enable id="canvas"       # Enable a plugin
obsidian plugin:disable id="canvas"      # Disable a plugin
obsidian plugin:install id="dataview"    # FORBIDDEN in this vault
obsidian plugin:uninstall id="dataview"  # Uninstall a community plugin
obsidian plugin:reload id="my-plugin"    # Reload a plugin (useful for dev)
```

**FORBIDDEN in this vault:** `plugin:install` - unaudited third-party code; the user
installs those through the Obsidian interface. See `../SKILL.md`, section
"Forbidden commands".

> **Note:** `plugins versions` only shows version numbers for community plugins. Core (built-in) plugins share Obsidian's version and display blank version fields.

---

## Sync

Manage Obsidian Sync (requires active Sync subscription). Every command in this section is
forbidden in this vault except the read-only `sync:history`.

```bash
obsidian sync                                   # FORBIDDEN in this vault
obsidian sync on                                # FORBIDDEN in this vault
obsidian sync off                               # FORBIDDEN in this vault
obsidian sync:status                            # FORBIDDEN in this vault
obsidian sync:history path="note.md"            # Allowed - read-only version history for a file
obsidian sync:read path="note.md" version=3     # FORBIDDEN in this vault
obsidian sync:restore path="note.md" version=3  # FORBIDDEN in this vault
obsidian sync:deleted                           # FORBIDDEN in this vault
obsidian sync:open                              # FORBIDDEN in this vault
```

**FORBIDDEN in this vault:** every `sync*` command above except `sync:history` - mutates
remote state; only the read-only `sync:history` is allowed. See `../SKILL.md`, section
"Forbidden commands". These are reserved for the user acting directly in Obsidian.

---

## Themes

Manage appearance themes.

```bash
obsidian themes                            # List installed themes
obsidian themes versions                   # List installed themes with version numbers
obsidian theme                             # Show the currently active theme
obsidian theme name="Minimal"              # Get details about a specific theme
obsidian theme:set name="Minimal"          # Switch to a theme
obsidian theme:set name=""                 # Switch back to default theme
obsidian theme:install name="Minimal"      # FORBIDDEN in this vault
obsidian theme:install name="Minimal" enable  # FORBIDDEN in this vault
obsidian theme:uninstall name="Minimal"    # Uninstall a theme
```

**FORBIDDEN in this vault:** `theme:install` - unaudited third-party code; the user installs
those through the Obsidian interface. See `../SKILL.md`, section "Forbidden commands".

---

## CSS Snippets

Manage custom CSS snippet files (snippets live in `.obsidian/snippets/`).

```bash
obsidian snippets                          # List all installed CSS snippets
obsidian snippets:enabled                  # List only enabled snippets
obsidian snippet:enable name="my-style"    # Enable a snippet
obsidian snippet:disable name="my-style"   # Disable a snippet
```

---

## Commands & Hotkeys

Execute any Obsidian command by its ID, and inspect hotkey bindings.

```bash
obsidian commands                          # List all available command IDs
obsidian command id="app:reload"           # Execute a command by ID
obsidian command id="editor:toggle-bold"   # Example: toggle bold in active editor
obsidian hotkeys                           # List all hotkeys (tab-separated: id \t keybinding)
obsidian hotkey id="app:open-settings"     # Get hotkey for a specific command
obsidian hotkey id="app:open-settings" verbose  # Show if custom or default
```

**Typical workflow - find and run a command:**

```bash
obsidian commands | grep "canvas"          # Find canvas-related command IDs
obsidian command id="canvas:new-file"      # Execute the matched command
```

**Getting plugin command IDs:**

```bash
obsidian commands | grep "dataview"        # List all Dataview plugin commands
```

---

## Obsidian Bases

Obsidian Bases (v1.12+) is a built-in database feature. Base files (`.base`) store structured data and support multiple views.

```bash
obsidian bases                                    # List all .base files in vault
obsidian base:query file="tasks" format=json      # Query default view of a base
obsidian base:query file="tasks" view="Kanban"    # Query a specific view
obsidian base:query path="folder/tasks.base" format=csv  # Query by path
obsidian base:views file="tasks"                  # List all views in a base file
obsidian base:create file="tasks" title="Buy milk"  # Add an item to a base
```

**Supported output formats for `base:query`:** `json` (default), `csv`, `tsv`, `md`, `paths`

---

## History

File version history (built-in to Obsidian, separate from Sync). Requires the File Recovery core plugin.

```bash
obsidian history:list                             # List all files that have history
obsidian history path="folder/note.md"            # List versions of a specific file
obsidian history:read path="folder/note.md"       # Read the latest saved version
obsidian history:read path="folder/note.md" version=3  # Read a specific version
obsidian history:restore path="folder/note.md" version=3  # Restore a version
obsidian history:open path="folder/note.md"       # Open file recovery UI for a file
```

> **Note:** History is distinct from [Sync version history](#sync). History uses Obsidian's built-in File Recovery snapshots; Sync history uses Obsidian Sync cloud versions.

---

## Workspace & Tabs

Inspect and manage the Obsidian workspace layout and open tabs.

```bash
obsidian workspace                                # Show the full workspace tree
obsidian tabs                                     # List all open tabs (flat list)
obsidian tab:open file="folder/note.md"           # Open a file in a new tab
obsidian tab:open view="graph"                    # Open a view type in a new tab
```

---

## Diff

Compare local and sync versions of a file.

```bash
obsidian diff path="folder/note.md"               # List available versions (local + sync)
obsidian diff path="folder/note.md" from=1 to=2   # Diff two specific versions
obsidian diff path="folder/note.md" filter=local  # Show only local versions
obsidian diff path="folder/note.md" filter=sync   # Show only sync versions
```

---

## Developer

Debugging and development tools. Every command in this section is forbidden in this vault:
`eval` runs arbitrary JavaScript with full API access, and every `dev:*` command (plus the
bare `devtools` toggle, which opens the same unguarded Electron DevTools surface) is grouped
under the same ban. See `../SKILL.md`, section "Forbidden commands", for all of them.

### Screenshots

```bash
obsidian dev:screenshot path="folder/screenshot.png"  # FORBIDDEN in this vault
```

**FORBIDDEN in this vault:** `dev:screenshot` - arbitrary JavaScript and unguarded devtools
access against the whole vault. See `../SKILL.md`, section "Forbidden commands".

Takes a screenshot of the Obsidian window and saves it. **Path must be vault-relative** - absolute filesystem paths are silently ignored.

### JavaScript Evaluation

```bash
obsidian eval code="app.vault.getFiles().length"                                    # FORBIDDEN in this vault
obsidian eval code="app.vault.getMarkdownFiles().map(f => f.path).join('\n')"       # FORBIDDEN in this vault
```

**FORBIDDEN in this vault:** `eval` - arbitrary JavaScript and unguarded devtools access
against the whole vault. See `../SKILL.md`, section "Forbidden commands".

Executes arbitrary JavaScript in the Obsidian app context. Has access to the full Obsidian API (`app`, `app.vault`, `app.workspace`, `app.metadataCache`, etc.).

> **Multiline scripts:** Passing multiline JavaScript inline fails with "Invalid or unexpected token".
> Write the code to a temp file and use command substitution instead:
>
> ```bash
> cat > /tmp/obs.js << 'JS'
> var files = app.vault.getMarkdownFiles();
> files.map(f => f.path).join('\n');
> JS
> obsidian eval code="$(cat /tmp/obs.js)"   # FORBIDDEN in this vault
> ```

### Console & Errors

```bash
obsidian dev:debug on              # FORBIDDEN in this vault
obsidian dev:debug off             # FORBIDDEN in this vault
obsidian dev:console limit=20      # FORBIDDEN in this vault
obsidian dev:errors                # FORBIDDEN in this vault
```

**FORBIDDEN in this vault:** `dev:debug`, `dev:console`, `dev:errors` - arbitrary JavaScript
and unguarded devtools access against the whole vault. See `../SKILL.md`, section
"Forbidden commands".

> **Note:** `dev:console` will return an error unless `dev:debug on` has been run first in the current session.

### DOM Inspection

```bash
obsidian dev:dom selector=".view-content"             # FORBIDDEN in this vault
obsidian dev:dom selector=".view-content" all         # FORBIDDEN in this vault
obsidian dev:dom selector=".view-content" text        # FORBIDDEN in this vault
obsidian dev:dom selector=".view-content" total       # FORBIDDEN in this vault
obsidian dev:dom selector=".view-content" attr=class  # FORBIDDEN in this vault
obsidian dev:dom selector=".view-content" css=color   # FORBIDDEN in this vault
```

**FORBIDDEN in this vault:** `dev:dom` - arbitrary JavaScript and unguarded devtools access
against the whole vault. See `../SKILL.md`, section "Forbidden commands".

### CSS Inspection

```bash
obsidian dev:css selector=".view-content"              # FORBIDDEN in this vault
obsidian dev:css selector=".view-content" prop=color   # FORBIDDEN in this vault
```

**FORBIDDEN in this vault:** `dev:css` - arbitrary JavaScript and unguarded devtools access
against the whole vault. See `../SKILL.md`, section "Forbidden commands".

### Chrome DevTools Protocol

```bash
obsidian devtools                                      # FORBIDDEN in this vault
obsidian dev:cdp method="Runtime.evaluate" params='{"expression":"1+1"}'  # FORBIDDEN in this vault
```

**FORBIDDEN in this vault:** `devtools` and `dev:cdp` - arbitrary JavaScript and unguarded
devtools access against the whole vault (this is the literal Chrome DevTools Protocol
surface the reason clause refers to). See `../SKILL.md`, section "Forbidden commands".

### Mobile Emulation

```bash
obsidian dev:mobile on                                 # FORBIDDEN in this vault
obsidian dev:mobile off                                # FORBIDDEN in this vault
```

**FORBIDDEN in this vault:** `dev:mobile` - arbitrary JavaScript and unguarded devtools
access against the whole vault. See `../SKILL.md`, section "Forbidden commands".

---

## Vault & System

### Vault Information

```bash
obsidian vault                         # Current vault: name, path, file/folder counts
obsidian vaults                        # List all known vaults
```

### Other Utilities

```bash
obsidian version                       # Obsidian version info
obsidian outline path="note.md"        # Heading structure of a note
obsidian wordcount path="note.md"      # Word and character count
obsidian recents                       # Recently opened files
obsidian reload                        # Reload the vault (re-index)
obsidian restart                       # Restart the Obsidian app
```

---

## Output Formatting & Piping

The CLI outputs plain text by default, ideal for piping into Unix tools.

### Supported `format=` values

| Format | Description | Best for |
|---|---|---|
| `text` | Plain text (default) | Piping to grep/awk/sed |
| `json` | JSON array or object | Processing with jq, AI agents |
| `csv` | Comma-separated values | Spreadsheet import |
| `tsv` | Tab-separated values | Shell parsing with cut/awk |
| `yaml` | YAML output | Config-style processing |
| `md` | Markdown table | Embedding results in notes |
| `paths` | One path per line | Batch file operations |
| `tree` | Tree view | Visual hierarchy |

Not all formats are supported by every command. Use `text` or `json` when in doubt.

### Examples

```bash
# Count notes in a folder
obsidian files folder="projects" | wc -l

# Find notes with a specific tag, then read them
obsidian tag name="urgent" | while read -r note; do
  echo "=== $note ==="
  obsidian read path="$note"
done

# Export search results as JSON and process with jq
# format=json returns an array of file path strings: ["folder/note.md", ...]
obsidian search query="meeting" format=json | jq '.[]'

# Query a base as CSV
obsidian base:query file="tasks" format=csv

# Filter console errors
obsidian dev:debug on              # FORBIDDEN in this vault
obsidian dev:console limit=50 | grep -i error  # FORBIDDEN in this vault
```

**FORBIDDEN in this vault:** `dev:debug` and `dev:console` - arbitrary JavaScript and
unguarded devtools access against the whole vault. See `../SKILL.md`, section "Forbidden
commands".

---

## Multi-Vault Usage

When working with multiple vaults, pass the vault name as the **first argument** (before the command):

```bash
obsidian "Personal" daily:read
obsidian "Work" search query="standup"
obsidian "Archive" files total
```

If the vault name contains spaces, quote it. The vault name must match what's shown in `obsidian vaults`.

> **Compatibility note:** On some environments, `obsidian "My Vault" command` returns
> `Error: Command "My Vault" not found`. If this occurs, omit the vault name - the CLI will target
> the most recently active vault. Switch vaults in the Obsidian UI before running CLI commands
> when targeting a specific vault.

---

## Headless / Server Setup (Linux)

For running Obsidian CLI on a headless Linux server (useful for AI agent integration):

1. Install the `.deb` package (not snap - snap confinement breaks IPC)
2. Install and start `xvfb`: `Xvfb :5 -screen 0 1920x1080x24 &`
3. Start Obsidian under xvfb: `DISPLAY=:5 obsidian &`
4. Run CLI commands: `DISPLAY=:5 obsidian daily:read`

**Systemd note**: If running as a service, ensure `PrivateTmp=false` so the IPC socket is accessible.

**Stderr filtering**: Headless environments produce harmless GPU warnings. Filter with:

```bash
DISPLAY=:5 obsidian search query="test" 2>/dev/null
```
