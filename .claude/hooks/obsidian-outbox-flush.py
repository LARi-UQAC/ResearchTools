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

STAGE 0 EXTRACTION (vault event daemon)
---------------------------------------
The write logic itself now lives in the obsidian-cli skill, in outbox_io.py, so
this hook and the daemon share ONE implementation rather than two that drift.
The hook keeps three things of its own: the documented default vault root, the
outbox location, and the promise that it never blocks a session. It now also
takes vault_lock around the flush, because the outbox is machine-global and a
daemon is a separate OS process that vault-access-guard.py never sees, and it
records every write through vault_journal so a write can be undone.

The skill is a dependency this hook may not have. A copy installed without it
exits 0 and says nothing (R11): a hook whose dependency is missing must never
refuse the tools in its matcher, which is what cost four unusable turns on
2026-08-27.
"""
import sys
from pathlib import Path

VAULT_DEFAULT = Path(r"C:\Martin Otis\Vault")
OUTBOX = Path.home() / ".claude" / "obsidian-outbox"
SENT = OUTBOX / "sent"
JOURNAL_NAME = "vault-journal.jsonl"
LOCK_NAME = "obsidian-outbox.lock"


def _journal_path():
    """Beside the outbox, never inside the vault: a recovery record must survive
    a vault this machine does not have. Derived at call time so a test pointing
    OUTBOX at a temporary tree redirects the journal with it."""
    return OUTBOX.parent / JOURNAL_NAME


def _lock_path():
    return OUTBOX.parent / LOCK_NAME


def _skills_dir():
    """The obsidian-cli scripts directory: the repository copy when this hook
    runs inside ResearchTools, otherwise the machine-wide install. Returns None
    when neither exists, which is a silent no-op, never a refusal."""
    for candidate in (Path(__file__).resolve().parents[1] / "skills",
                      Path.home() / ".claude" / "skills"):
        scripts = candidate / "obsidian-cli" / "scripts"
        if (scripts / "outbox_io.py").exists():
            return scripts
    return None


def _load():
    """Import the shared write path. Returns (outbox_io, vault_lock) or None."""
    scripts = _skills_dir()
    if scripts is None:
        return None
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    try:
        import outbox_io
        import vault_lock
    except ImportError:
        return None
    return outbox_io, vault_lock


def resolve_vault():
    """Kept as a module-level name because it is this hook's public surface:
    the offline suite asserts, before writing a byte, that the redirection to a
    temporary vault actually took effect."""
    modules = _load()
    if modules is None:
        return None
    return modules[0].resolve_vault(VAULT_DEFAULT)


def main() -> int:
    if not OUTBOX.is_dir():
        return 0
    modules = _load()
    if modules is None:
        return 0
    outbox_io, vault_lock = modules
    pending = sorted(p for p in OUTBOX.glob("*.md") if p.is_file())
    if not pending:
        return 0
    vault = outbox_io.resolve_vault(VAULT_DEFAULT)
    if vault is None:
        print("[OUTBOX] no vault (set OBSIDIAN_VAULT); leaving outbox intact",
              file=sys.stderr)
        return 0
    try:
        config = outbox_io.load_config()
        lock = vault_lock.VaultLock(
            _lock_path(),
            acquire_timeout_s=outbox_io.require(config, "lock", "hook_acquire_timeout_s"),
            stale_after_s=outbox_io.require(config, "lock", "stale_after_s"),
            poll_interval_s=outbox_io.require(config, "lock", "poll_interval_s"),
        )
    except outbox_io.ConfigError as exc:
        print(f"[OUTBOX] {exc}; leaving outbox intact", file=sys.stderr)
        return 0
    try:
        with lock:
            for reason in lock.reclaimed:
                print(f"[OUTBOX] reclaimed a stale lock: {reason}", file=sys.stderr)
            flushed, total = outbox_io.flush_outbox(
                OUTBOX, SENT, vault, _journal_path())
    except vault_lock.LockError as exc:
        # Another writer holds the lock. The notes stay in the outbox and the
        # next SessionStart flushes them; blocking the session is never an option.
        print(f"[OUTBOX] {exc} Notes kept for the next run.", file=sys.stderr)
        return 0
    print(f"[OUTBOX] {flushed}/{total} note(s) flushed to vault", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
