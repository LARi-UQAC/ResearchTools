#!/usr/bin/env python3
"""
obsidian-outbox-flush.py - SessionStart / SessionEnd hook.

Flushes deferred Obsidian notes from the outbox into the vault via the Obsidian
CLI (Obsidian.com). Safety net of the two-part knowledge-capture method:
instruction-driven writes by local-writer during a loop-engineer run, plus this
session-boundary flush for notes deferred while Obsidian was closed.

Each *.md file in the outbox begins with a directive line, e.g.:

    <!-- obsidian: create path="30_Ressources/Apprentissages/foo" -->
    <!-- obsidian: append path="10_Projets/Logiciels/Bar/Decisions.md" -->

The remaining lines are the note content. On success the file is moved to
outbox/sent/; on failure (Obsidian closed, timeout) it is left in place for the
next run. Zero LLM tokens. Never blocks the session: always exits 0.

Obsidian.com is resolved from the OBSIDIAN_COM environment variable, else the
default per-user install path (LOCALAPPDATA on Windows). If it cannot be found
the outbox is left intact.
"""
import os
import re
import subprocess
import sys
from pathlib import Path


def _resolve_obsidian_com() -> Path:
    """
    --------------------------------------------------------------------------
    Purpose:
        Locate the Obsidian CLI launcher portably across contributor machines.

    Inputs:
        none (reads OBSIDIAN_COM / LOCALAPPDATA from the environment)

    Outputs:
        path (Path): candidate path to Obsidian.com (may not exist).
    --------------------------------------------------------------------------
    """
    override = os.environ.get("OBSIDIAN_COM")
    if override:
        return Path(override)
    local_appdata = os.environ.get("LOCALAPPDATA", "")
    return Path(local_appdata) / "Programs" / "Obsidian" / "Obsidian.com"


OBSIDIAN_COM = _resolve_obsidian_com()
OUTBOX = Path.home() / ".claude" / "obsidian-outbox"
SENT = OUTBOX / "sent"
CALL_TIMEOUT = 15  # seconds; guards against a hang when Obsidian is closed

_DIRECTIVE = re.compile(
    r'^<!--\s*obsidian:\s*(create|append)\s+path="([^"]+)"\s*-->\s*$'
)


def _flush_one(md_file: Path) -> bool:
    """
    --------------------------------------------------------------------------
    Purpose:
        Push a single outbox note into the vault via the Obsidian CLI.

    Inputs:
        md_file (Path): outbox .md file whose first line is the directive.

    Outputs:
        ok (bool): True if the note was written and archived, else False.
    --------------------------------------------------------------------------
    """
    lines = md_file.read_text(encoding="utf-8").splitlines()
    if not lines:
        return False
    directive = _DIRECTIVE.match(lines[0])
    if not directive:
        print(f"[OUTBOX] skip (no directive): {md_file.name}", file=sys.stderr)
        return False
    action, path = directive.group(1), directive.group(2)
    content = "\n".join(lines[1:]).lstrip("\n")
    try:
        # No shell: args are passed as a list, so newlines in content are safe.
        result = subprocess.run(
            [str(OBSIDIAN_COM), action, f"path={path}", f"content={content}"],
            capture_output=True,
            text=True,
            timeout=CALL_TIMEOUT,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        print(f"[OUTBOX] Obsidian unreachable, keep {md_file.name}: {exc}",
              file=sys.stderr)
        return False
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        print(f"[OUTBOX] CLI error on {md_file.name}: {detail}",
              file=sys.stderr)
        return False
    SENT.mkdir(parents=True, exist_ok=True)
    md_file.replace(SENT / md_file.name)
    print(f"[OUTBOX] flushed {action} -> {path}", file=sys.stderr)
    return True


def main() -> int:
    if not OUTBOX.is_dir():
        return 0
    pending = sorted(p for p in OUTBOX.glob("*.md") if p.is_file())
    if not pending:
        return 0
    if not OBSIDIAN_COM.exists():
        print("[OUTBOX] Obsidian.com not found; leaving outbox intact",
              file=sys.stderr)
        return 0
    flushed = sum(_flush_one(md) for md in pending)
    print(f"[OUTBOX] {flushed}/{len(pending)} note(s) flushed to vault",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
