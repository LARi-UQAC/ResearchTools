#!/usr/bin/env python3
"""
obsidian-outbox-flush.py - SessionStart / SessionEnd hook.

Flushes deferred Obsidian notes from the outbox into the vault. Acts as the
automatic safety net of the two-part capture method (instruction-driven writes
at checkpoints + this session-end flush).

Each *.md file in the outbox begins with a directive line, e.g.:

    <!-- obsidian: create path="30_Ressources/LaTEX/foo.md" -->
    <!-- obsidian: append path="10_Projets/LaTEX/Bar/Decisions.md" -->

The remaining lines are the note content. On success the file is moved to
outbox/sent/; on failure it is left in place for the next run. Zero LLM tokens.
Never blocks the session: always exits 0.

WHY THIS WRITES TO DISK INSTEAD OF CALLING THE OBSIDIAN CLI
-----------------------------------------------------------
Measured on 2026-08-03 with Obsidian 1.13.4. The CLI hands the command to the
main process over a socket, as JSON. Past a threshold the main process's
JSON.parse receives a truncated header and throws an uncaught exception, popping
a "A JavaScript error occurred in the main process" dialog, and the write never
happens:

    SyntaxError: Unexpected token ']', ..."eview.md"],"tty":"fa"... is not valid
      at JSON.parse (<anonymous>)
      at Socket.n (obsidian-1.13.4.asar\\main.js:80:136)
      at addChunk (node:internal/streams/readable:561:12)

The threshold is on the whole JSON header (content plus path plus tty/cwd
metadata), not on the content alone: a 3850-byte header goes through, a
4343-byte one does not, and 4096 -- a Windows named-pipe buffer -- falls between
the two.

Reproduced on 2026-08-13 with Obsidian 1.13.7: same trace shape, same truncated
header, at obsidian-1.13.7.asar\\main.js:64:136 instead of 80:136. The defect is
therefore not confined to 1.13.4 and was not fixed upstream between the two.

The exact cause is deliberately left open. The server code, read out of the
.asar, does reassemble chunks and does frame on a newline, so the defect is not
there:

    let n = s => { r += s.toString();
                   let d = r.indexOf("\\n");
                   if (d !== -1) { ... y(JSON.parse(r.slice(0, d))) } };

A UTF-8 sequence split across a chunk boundary was ruled out by measurement (the
only non-ASCII bytes of the failing note sit at offsets 1156-1184, far from the
boundary). What remains, unproven, is a client that does not wait for the socket
'drain' event before exiting and so loses the tail of the message. Verifying it
would mean reproducing the crash. The threshold alone is enough to decide.

Two further CLI defects, both measured, which this hook used to inherit:

  1. it exits 0 even when the command fails, so `returncode != 0` never fired
     and notes were archived to sent/ without ever reaching the vault;
  2. `create` on an existing file silently writes a numbered duplicate
     ("Decisions 1.md") instead of failing, which is how the vault accumulated
     strict md5-identical duplicates.

Writing to disk avoids the socket entirely. Obsidian watches the filesystem and
reloads on its own, so the note appears just the same. The single-serialised-
writer rule of the global CLAUDE.md is preserved: this hook stays the only
writer of the outbox path.
"""
import os
import re
import sys
from pathlib import Path

VAULT_DEFAULT = Path(r"C:\Martin Otis\Vault")
OUTBOX = Path.home() / ".claude" / "obsidian-outbox"
SENT = OUTBOX / "sent"

_DIRECTIVE = re.compile(
    r'^<!--\s*obsidian:\s*(create|append)\s+path="([^"]+)"\s*-->\s*$'
)

# P14: the link shapes and the code regions to ignore. Deliberately duplicated from
# vault_consolidate.py rather than imported: this hook is COPIED to ~/.claude/hooks/ and
# runs with no repository on sys.path, so an import would work here and fail on every
# machine that only has the hook.
_LINK = re.compile(r"\[\[([^\]|#]+)(?:[|#][^\]]*)?\]\]")
_FENCE = re.compile(r"(?ms)^```.*?^```")
_CODE_SPAN = re.compile(r"`[^`\n]*`")


def _vault_link_names(vault: Path) -> set:
    """
    --------------------------------------------------------------------------
    Purpose:
        Every string an existing note can be designated by: its bare name, its
        relative path, and each intermediate path suffix, all without the .md.

    Inputs:
        vault (Path): the vault root

    Outputs:
        names (set): resolvable link targets currently in the vault
    --------------------------------------------------------------------------
    """
    names = set()
    for path in vault.rglob("*.md"):
        rel = path.relative_to(vault).as_posix()[:-3]
        parts = rel.split("/")
        for i in range(len(parts)):
            names.add("/".join(parts[i:]))
    return names


def _warn_unresolved_links(rel: str, content: str, vault: Path) -> None:
    """
    --------------------------------------------------------------------------
    Purpose:
        Warn when a note about to be written carries a wiki-link that resolves
        to nothing. This exists because the rule was written down and enforced
        nowhere: local-writer.md says to wrap an illustrative or anti-example
        link in backticks so it does not become a live link, and the first note
        produced after that rule was written broke it three times, creating
        three phantoms of its own - two of them pointing at FOLDERS, which can
        never resolve.

        A WARNING, never a refusal: a link to a note that does not exist yet is
        legitimate in Obsidian, and this hook's contract is that it never blocks
        a session. The point is that the writer sees it at write time instead of
        an auditor finding it weeks later.

    Inputs:
        rel (str): the note's vault-relative path, for the message
        content (str): the note body, directive line already stripped
        vault (Path): the vault root

    Outputs:
        None. Prints one line to stderr when something is unresolved.
    --------------------------------------------------------------------------
    """
    prose = _CODE_SPAN.sub(" ", _FENCE.sub(" ", content))
    targets = {m.strip() for m in _LINK.findall(prose)}
    if not targets:
        return
    try:
        known = _vault_link_names(vault)
    except OSError:
        return
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


def resolve_vault() -> "Path | None":
    """
    --------------------------------------------------------------------------
    Purpose:
        Locate the vault without hardcoding one machine into a shared repository.
        OBSIDIAN_VAULT wins; the documented default is the fallback; anything
        else is a silent no-op, because a session must never be blocked by a
        vault this contributor does not have.

    Inputs:
        none (reads OBSIDIAN_VAULT from the environment)

    Outputs:
        vault (Path | None): an existing vault directory, else None
    --------------------------------------------------------------------------
    """
    env = os.environ.get("OBSIDIAN_VAULT", "").strip()
    if env:
        candidate = Path(env)
        return candidate if candidate.is_dir() else None
    return VAULT_DEFAULT if VAULT_DEFAULT.is_dir() else None


def _write(action: str, target: Path, content: str) -> bool:
    """
    --------------------------------------------------------------------------
    Purpose:
        Write one note to the vault and verify the effect on disk. The effect is
        checked, never a return code: the Obsidian CLI reports success on
        failure, and that is precisely the defect this hook works around.

    Inputs:
        action (str): "create" or "append"
        target (Path): absolute path of the note inside the vault
        content (str): note body, directive line already stripped

    Outputs:
        ok (bool): True when the file grew or was created with content
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
            return True
        merged = (previous + "\n\n" + body).lstrip() + "\n"
    else:
        merged = content.rstrip() + "\n"

    target.write_text(merged, encoding="utf-8", newline="")
    after = target.stat().st_size
    return after > before or (before == 0 and after > 0)


def _flush_one(md_file: Path, vault: Path) -> bool:
    """
    --------------------------------------------------------------------------
    Purpose:
        Push a single outbox note into the vault, then archive it only once the
        write has been verified on disk.

    Inputs:
        md_file (Path): outbox .md file whose first line is the directive
        vault (Path): resolved vault root, already verified to exist by the caller

    Outputs:
        ok (bool): True if the note was written and archived, else False
    --------------------------------------------------------------------------
    """
    lines = md_file.read_text(encoding="utf-8").splitlines()
    if not lines:
        return False
    directive = _DIRECTIVE.match(lines[0])
    if not directive:
        print(f"[OUTBOX] skip (no directive): {md_file.name}", file=sys.stderr)
        return False
    action, rel = directive.group(1), directive.group(2)
    content = "\n".join(lines[1:]).lstrip("\n")

    target = (vault / rel).resolve()
    # A path escaping the vault is refused: the directive comes from a file, and
    # a file is untrusted input.
    if vault.resolve() not in target.parents:
        print(f"[OUTBOX] refused (outside vault): {rel}", file=sys.stderr)
        return False

    _warn_unresolved_links(rel, content, vault)

    try:
        ok = _write(action, target, content)
    except OSError as exc:
        print(f"[OUTBOX] write failed, keep {md_file.name}: {exc}",
              file=sys.stderr)
        return False
    if not ok:
        print(f"[OUTBOX] no effect on disk, keep {md_file.name}",
              file=sys.stderr)
        return False

    SENT.mkdir(parents=True, exist_ok=True)
    md_file.replace(SENT / md_file.name)
    print(f"[OUTBOX] flushed {action} -> {rel}", file=sys.stderr)
    return True


def main() -> int:
    if not OUTBOX.is_dir():
        return 0
    pending = sorted(p for p in OUTBOX.glob("*.md") if p.is_file())
    if not pending:
        return 0
    vault = resolve_vault()
    if vault is None:
        print("[OUTBOX] no vault (set OBSIDIAN_VAULT); leaving outbox intact",
              file=sys.stderr)
        return 0
    flushed = sum(_flush_one(md, vault) for md in pending)
    print(f"[OUTBOX] {flushed}/{len(pending)} note(s) flushed to vault",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
