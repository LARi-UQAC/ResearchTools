#!/usr/bin/env python3
"""
outbox_io.py - the one implementation of the vault write path.

Extracted from obsidian-outbox-flush.py in Stage 0 of the vault event daemon so
that the hook and the daemon share one implementation instead of two that drift.
Behaviour is unchanged: a note is written to the FILESYSTEM and the effect is
verified by st_size, never by a return code.

Why not the Obsidian CLI: past a threshold on the whole JSON header handed to the
main process (a 3850-byte header passes, 4343 does not, and 4096, a Windows
named-pipe buffer, falls between), the write silently does not happen; the CLI
exits 0 even then; and a create on an existing file writes a numbered duplicate.
Measured 2026-08-03 on Obsidian 1.13.4 and reproduced 2026-08-13 on 1.13.7. The
full trace and the ruled-out causes are in the hook's own docstring.

This module holds NO vault path (R1). The documented default lives with the
caller that owns it, and resolve_vault takes it as an argument.

Every write here is expected to run under vault_lock.VaultLock and to be recorded
by vault_journal: the outbox is machine-global, so this process is never the only
writer.
"""
import json
import os
import re
import sys
from pathlib import Path

CONFIG_PATH = Path(__file__).resolve().parents[1] / "daemon-config.json"

DIRECTIVE = re.compile(
    r'^<!--\s*obsidian:\s*(create|append)\s+path="([^"]+)"\s*-->\s*$'
)
# A third, narrower directive (R5: one new literal, not a second regex
# dialect): edit ONE frontmatter key of an EXISTING note in place, added
# 2026-10-02 because create/append can only ever ADD a block after the
# existing content - never usable for a key that must live in the block
# Obsidian (and daemon_graph.read_repo_property) actually reads.
SET_PROPERTY_DIRECTIVE = re.compile(
    r'^<!--\s*obsidian:\s*set-property\s+path="([^"]+)"\s+key="([^"]+)"\s*-->\s*$'
)
FRONT_BLOCK = re.compile(r"(?s)\A---\n(.*?)\n---\n")
LINK = re.compile(r"\[\[([^\]|#]+)(?:[|#][^\]]*)?\]\]")
FENCE = re.compile(r"(?ms)^```.*?^```")
CODE_SPAN = re.compile(r"`[^`\n]*`")


class FrontmatterError(RuntimeError):
    """set_frontmatter_property cannot apply: the target is missing, or its
    first block is not a `---`-delimited frontmatter block."""


class ConfigError(RuntimeError):
    """A configuration key is missing. Named, never defaulted (R3)."""


def load_config(config_path=None) -> dict:
    """Read daemon-config.json. A missing file names itself rather than
    yielding a silent default."""
    path = Path(config_path) if config_path else CONFIG_PATH
    if not path.exists():
        raise ConfigError(f"[OUTBOX] no configuration at {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise ConfigError(f"[OUTBOX] {path} is not valid JSON: {exc}") from exc


def configure_streams() -> None:
    """
    --------------------------------------------------------------------------
    Purpose:
        Make stdout and stderr able to carry the glyphs a vault note used, so
        emitting a report cannot fail on one character. Called by the main()
        of every script in this skill that prints JSON.

    Inputs:
        none.

    Outputs:
        none.

    Measured 2026-09-18 on this machine: the console is cp1252, a journal
    record carried U+2212 (minus sign), and `vault_journal.py --list` died on
    `UnicodeEncodeError: 'charmap' codec can't encode character '\\u2212'`
    BEFORE printing anything. That is the vault's recovery tool failing at the
    moment it is needed, and the traceback names cp1252, which a reader then
    misattributes to the notes rather than to the console. One session did
    exactly that and wrote a note blaming a note encoding that was never at
    fault.

        The same defect was measured and fixed in extract-statistic's
        extract_text.py on 2026-09-13. It is reimplemented here rather than
        imported across skills because obsidian-outbox-flush.py and the daemon
        sit on this module's import path, and a cross-skill ImportError there
        would make a hook exit non-zero and refuse every tool in its matcher
        (R11).

        utf-8 is requested first and errors="replace" is the fallback, so a
        stream that cannot be reconfigured degrades to a substituted character
        rather than to a lost report (R8: never a silent nothing).
    --------------------------------------------------------------------------
    """
    for stream in (sys.stdout, sys.stderr):
        if not hasattr(stream, "reconfigure"):
            continue
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError, LookupError):   # pragma: no cover
            try:
                stream.reconfigure(errors="replace")
            except (ValueError, OSError):
                pass


def tail(text: str, limit: int = 700) -> str:
    """
    --------------------------------------------------------------------------
    Purpose:
        Keep the END of a captured stderr, never its beginning, for every
        caller in this skill that quotes a failed subprocess.

        A Python traceback names its exception on the LAST line and opens with
        frames that are identical on every failure, so truncating from the
        front keeps the noise and discards the fact. Measured 2026-08-30 on
        the live drill: three nested layers each truncated from the front
        (300, then 200 characters), and two full drill runs were needed to
        reach a one-line NameError that had been in the discarded tail all
        along.

    Inputs:
        text (str): captured stderr, possibly empty or None.
        limit (int): characters to keep from the end.

    Outputs:
        result (str): the last `limit` characters, marked when anything was
            dropped so a reader knows the head is missing.
    --------------------------------------------------------------------------
    """
    stripped = (text or "").strip()
    if len(stripped) <= limit:
        return stripped
    return "...(truncated, showing the end)...\n" + stripped[-limit:]


def require(config: dict, section: str, key: str):
    """Fetch one configured value, naming the key and the file when absent."""
    value = config.get(section, {}).get(key)
    if value is None:
        raise ConfigError(f"[OUTBOX] '{section}.{key}' is missing from {CONFIG_PATH}")
    return value


def resolve_vault(default=None):
    """
    --------------------------------------------------------------------------
    Purpose:
        Locate the vault without hardcoding one machine into a shared
        repository. OBSIDIAN_VAULT wins; the caller's documented default is
        the fallback; anything else is a silent no-op, because a session must
        never be blocked by a vault this contributor does not have.

    Inputs:
        default (Path | None): the caller's documented default vault root

    Outputs:
        vault (Path | None): an existing vault directory, else None
    --------------------------------------------------------------------------
    """
    env = os.environ.get("OBSIDIAN_VAULT", "").strip()
    if env:
        candidate = Path(env)
        return candidate if candidate.is_dir() else None
    if default is None:
        return None
    default = Path(default)
    return default if default.is_dir() else None


def vault_link_names(vault: Path) -> set:
    """Every string an existing note can be designated by: its bare name, its
    relative path, and each intermediate path suffix, all without the .md."""
    names = set()
    for path in Path(vault).rglob("*.md"):
        rel = path.relative_to(vault).as_posix()[:-3]
        parts = rel.split("/")
        for i in range(len(parts)):
            names.add("/".join(parts[i:]))
    return names


def warn_unresolved_links(rel: str, content: str, vault: Path) -> list:
    """
    --------------------------------------------------------------------------
    Purpose:
        Warn when a note about to be written carries a wiki-link resolving to
        nothing. Obsidian links notes, not folders, so a link to a folder name
        creates a phantom that can never resolve. A WARNING, never a refusal: a
        link to a note that does not exist yet is legitimate, and this path must
        never block a session.

    Inputs:
        rel (str): the note's vault-relative path, for the message
        content (str): the note body, directive line already stripped
        vault (Path): the vault root

    Outputs:
        unresolved (list): the unresolved targets, sorted; one stderr line is
        printed when the list is non-empty.
    --------------------------------------------------------------------------
    """
    prose = CODE_SPAN.sub(" ", FENCE.sub(" ", content))
    targets = {m.strip() for m in LINK.findall(prose)}
    if not targets:
        return []
    try:
        known = vault_link_names(vault)
    except OSError:
        return []
    # The note being written designates itself; it is not a phantom.
    known.add(rel[:-3] if rel.endswith(".md") else rel)
    known.add(Path(rel).stem)
    unresolved = sorted(t for t in targets if t not in known)
    if unresolved:
        print(
            f"[OUTBOX] {rel}: {len(unresolved)} link(s) resolve to nothing: "
            f"{', '.join(unresolved)}. Wrap an illustrative link in backticks, or "
            "create the note it points at.",
            file=sys.stderr,
        )
    return unresolved


def write_note(action: str, target: Path, content: str) -> tuple:
    """
    --------------------------------------------------------------------------
    Purpose:
        Write one note and verify the effect on disk. The effect is checked,
        never a return code: the Obsidian CLI reports success on failure, and
        that is precisely the defect this path works around.

    Inputs:
        action (str): "create" or "append"
        target (Path): absolute path of the note inside the vault
        content (str): note body, directive line already stripped

    Outputs:
        result (tuple): (ok, before, after) where ok is True when the file grew
        or was created with content. A replay whose body is already present
        returns ok with after == before, which is the idempotence the whole
        pipeline rests on; do not remove that guard as dead code.
    --------------------------------------------------------------------------
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    before = target.stat().st_size if target.exists() else 0

    if action == "append" or (action == "create" and target.exists()):
        # A "create" onto an existing file degrades to append rather than
        # producing a numbered duplicate. Losing nothing beats a silent fork.
        previous = target.read_text(encoding="utf-8").rstrip() if before else ""
        body = content.strip()
        if body and body in previous:
            # Already applied by an earlier run: treat as done, do not double.
            return True, before, before
        merged = (previous + "\n\n" + body).lstrip() + "\n"
    else:
        merged = content.rstrip() + "\n"

    target.write_text(merged, encoding="utf-8", newline="")
    after = target.stat().st_size
    return (after > before or (before == 0 and after > 0)), before, after


def parse_directive(text: str) -> tuple:
    """Split a staged note into (action, relative path, content, key), or
    (None, None, None, None) when the first line is not a directive. `key`
    is non-None only for action == "set-property"; create/append always
    return None there, so flush_one can route on `action` alone without a
    second parse."""
    lines = text.splitlines()
    if not lines:
        return None, None, None, None
    match = DIRECTIVE.match(lines[0])
    if match:
        return (match.group(1), match.group(2),
                "\n".join(lines[1:]).lstrip("\n"), None)
    match = SET_PROPERTY_DIRECTIVE.match(lines[0])
    if match:
        return ("set-property", match.group(1),
                "\n".join(lines[1:]).lstrip("\n"), match.group(2))
    return None, None, None, None


def set_frontmatter_property(target: Path, key: str, value: str) -> tuple:
    """
    --------------------------------------------------------------------------
    Purpose:
        Add or replace ONE frontmatter property of an EXISTING note, in
        place, leaving every other key, the body, and the line order
        untouched. append, and create on an existing file (which degrades
        to append), both add a SECOND `---` block after the real one,
        which nothing reads as frontmatter - this is the operation that
        edits the first block, the one Obsidian and
        daemon_graph.read_repo_property actually read. Measured 2026-10-02:
        a staged `repo:` addition went out as `append` and would have
        landed as dead text in a second, unread block.

    Inputs:
        target (Path): absolute path of an EXISTING note inside the vault
        key (str): the frontmatter key to set, e.g. "repo"
        value (str): the value to write, verbatim, on one line

    Outputs:
        result (tuple): (ok, before, after), the same shape write_note
        returns (R9). `ok` is verified by RE-READING the file after the
        write and confirming the key now holds `value` in its first block -
        never inferred from a size delta, since replacing a long value with
        a shorter one shrinks the file.

    Raises:
        FrontmatterError: `target` does not exist (this action never
        creates a file - "create" exists for that); its first block is not
        a `---`-delimited frontmatter block; or `value` contains a CR or LF.
        A staged directive's body can carry more than one content line, and
        embedding that whole blob into `new_line` would insert extra
        frontmatter lines - caught here, before the file is touched, rather
        than at the post-write verification, where the target would already
        be corrupted and the outbox item would replay the same corruption
        forever.
    --------------------------------------------------------------------------
    """
    if "\n" in value or "\r" in value:
        raise FrontmatterError(
            f"set-property value for {key!r} contains a newline; "
            "refusing to write a multiline value into one frontmatter line"
        )
    if not target.exists():
        raise FrontmatterError(f"set-property target does not exist: {target}")
    text = target.read_text(encoding="utf-8")
    match = FRONT_BLOCK.match(text)
    if not match:
        raise FrontmatterError(f"{target} has no frontmatter block to edit")
    before = target.stat().st_size

    front_lines = match.group(1).split("\n")
    key_line = re.compile(r"^%s:\s*.*$" % re.escape(key))
    new_line = f"{key}: {value}"
    replaced = False
    for i, line in enumerate(front_lines):
        if key_line.match(line):
            front_lines[i] = new_line
            replaced = True
            break
    if not replaced:
        front_lines.append(new_line)

    new_text = (text[:match.start(1)] + "\n".join(front_lines)
               + text[match.end(1):])
    target.write_text(new_text, encoding="utf-8", newline="")
    after = target.stat().st_size

    verify = FRONT_BLOCK.match(target.read_text(encoding="utf-8"))
    ok = bool(verify) and new_line in verify.group(1).split("\n")
    return ok, before, after


def contained_target(vault: Path, rel: str):
    """Resolve a directive path and refuse anything leaving the vault (R24).
    The directive comes from a file, and a file is untrusted input."""
    target = (Path(vault) / rel).resolve()
    return target if Path(vault).resolve() in target.parents else None


def stage(outbox: Path, slug: str, content: str, directive=None, subdir=None) -> Path:
    """
    --------------------------------------------------------------------------
    Purpose:
        Put a note into the outbox atomically: write <slug>.md.tmp, then
        os.replace() it onto <slug>.md. Consumers glob *.md only, so a
        half-written file is never visible to them. This closes the race where
        a reader picks up a note mid-write.

    Inputs:
        outbox (Path): the outbox root
        slug (str): file name without the .md extension
        content (str): the note body
        directive (str | None): the pre-routed directive line, when the caller
            has already decided the destination
        subdir (str | None): a subdirectory of the outbox, for example "raw"

    Outputs:
        path (Path): the staged .md file
    --------------------------------------------------------------------------
    """
    folder = Path(outbox) / subdir if subdir else Path(outbox)
    folder.mkdir(parents=True, exist_ok=True)
    body = f"{directive}\n{content}" if directive else content
    tmp = folder / f"{slug}.md.tmp"
    final = folder / f"{slug}.md"
    tmp.write_text(body, encoding="utf-8", newline="")
    os.replace(tmp, final)
    return final


def flush_one(md_file: Path, vault: Path, sent: Path, journal_path=None) -> bool:
    """
    --------------------------------------------------------------------------
    Purpose:
        Push a single outbox note into the vault, then archive it only once the
        write has been verified on disk. Order is journal, write, verify,
        archive: a crash between any two steps leaves the note in the outbox,
        so the flush replays and write_note's idempotence guard absorbs it.

    Inputs:
        md_file (Path): outbox .md file whose first line is the directive
        vault (Path): resolved vault root, already verified to exist
        sent (Path): archive directory for delivered notes
        journal_path (Path | None): the .jsonl journal; None disables recording

    Outputs:
        ok (bool): True if the note was written and archived, else False
    --------------------------------------------------------------------------
    """
    action, rel, content, key = parse_directive(
        md_file.read_text(encoding="utf-8"))
    if action is None:
        print(f"[OUTBOX] skip (no directive): {md_file.name}", file=sys.stderr)
        return False

    target = contained_target(vault, rel)
    if target is None:
        print(f"[OUTBOX] refused (outside vault): {rel}", file=sys.stderr)
        return False

    # set-property edits one existing key, in place; it has no note BODY to
    # scan for a [[link]] the way create/append do.
    if action != "set-property":
        warn_unresolved_links(rel, content, vault)

    # set-property edits the file IN PLACE: the written byte count can be
    # smaller than before (a shorter value replacing a longer one), so a
    # size-based WRITE record would make vault_journal.undo() truncate the
    # note - reversing only an append, never a middle-of-file substitution -
    # and either leave the new value in place while chopping the body, or
    # refuse outright. Capture the full pre-edit text so the undo can be a
    # restore instead (vault_journal.STATE_SNAPSHOT).
    pre_text = (target.read_text(encoding="utf-8")
               if action == "set-property" and target.exists() else None)

    if journal_path is not None:
        import vault_journal
        vault_journal.record(journal_path, rel,
                             target.stat().st_size if target.exists() else 0,
                             None, md_file.name, vault_journal.STATE_PENDING)
    try:
        if action == "set-property":
            ok, before, after = set_frontmatter_property(
                target, key, content.strip())
        else:
            ok, before, after = write_note(action, target, content)
    except (OSError, FrontmatterError) as exc:
        print(f"[OUTBOX] write failed, keep {md_file.name}: {exc}", file=sys.stderr)
        return False
    if not ok:
        print(f"[OUTBOX] no effect on disk, keep {md_file.name}", file=sys.stderr)
        return False
    if journal_path is not None:
        import vault_journal
        if action == "set-property":
            vault_journal.snapshot(journal_path, rel, pre_text, md_file.name)
        else:
            vault_journal.record(journal_path, rel, before, after,
                                 md_file.name, vault_journal.STATE_WRITE)

    sent.mkdir(parents=True, exist_ok=True)
    md_file.replace(sent / md_file.name)
    print(f"[OUTBOX] flushed {action} -> {rel}", file=sys.stderr)
    return True


def flush_outbox(outbox: Path, sent: Path, vault: Path, journal_path=None) -> tuple:
    """Flush every pre-routed note directly in the outbox. Subdirectories
    (raw/, sent/, state/, needs-review/) are deliberately not globbed: a raw
    drop has no directive yet and belongs to the daemon, not to this path."""
    pending = sorted(p for p in Path(outbox).glob("*.md") if p.is_file())
    flushed = sum(flush_one(md, vault, sent, journal_path) for md in pending)
    return flushed, len(pending)
