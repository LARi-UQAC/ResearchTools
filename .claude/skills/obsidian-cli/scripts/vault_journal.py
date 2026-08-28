#!/usr/bin/env python3
"""
vault_journal.py - append-only record of every write this machine makes to the
Obsidian vault, plus the undo that record enables.

Stage 0 of the vault event daemon. The vault is not under version control, so
recovery is this journal's job. Two records are appended per write:

    {"path":"30_Ressources/Ollama/x.md","before":0,"after":null,
     "source":"raw/x.md","state":"PENDING","at":"2026-08-28T14:02:11+00:00"}
    {"path":"30_Ressources/Ollama/x.md","before":0,"after":1843,
     "source":"raw/x.md","state":"WRITE","at":"2026-08-28T14:02:11+00:00"}

PENDING is written BEFORE the write and WRITE after the effect has been verified
on disk, so a crash between the two still leaves the byte size the undo needs.
`before` is st_size prior to the write, so an undo is "truncate to before", or
"delete" when before is 0.

The journal is append-only and is never rotated automatically: a rotation that
drops the oldest records drops exactly the writes nobody has looked at yet.
"""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

STATE_PENDING = "PENDING"
STATE_WRITE = "WRITE"
STATE_EDGE = "EDGE"       # consolidation edge appended to an existing note


def utc_now_iso() -> str:
    """Wall clock read in exactly one place, so callers can inject a stamp (R19)."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def record(journal_path, path: str, before: int, after, source: str,
           state: str, at: "str | None" = None) -> dict:
    """
    --------------------------------------------------------------------------
    Purpose:
        Append one journal record and return it.

    Inputs:
        journal_path (Path | str): the .jsonl journal, beside the outbox
        path (str): the note's vault-relative path
        before (int): st_size of the target before the write, 0 when absent
        after (int | None): st_size after the write, None for a PENDING record
        source (str): where the content came from, for a human reading the log
        state (str): STATE_PENDING, STATE_WRITE or STATE_EDGE
        at (str | None): ISO timestamp; generated when the caller passes none

    Outputs:
        entry (dict): the record as written
    --------------------------------------------------------------------------
    """
    entry = {
        "path": path, "before": int(before),
        "after": None if after is None else int(after),
        "source": source, "state": state, "at": at or utc_now_iso(),
    }
    journal = Path(journal_path)
    journal.parent.mkdir(parents=True, exist_ok=True)
    with journal.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry


def read_records(journal_path) -> list[dict]:
    """Every well-formed record, oldest first. A corrupt line is skipped rather
    than aborting the read: a half-written tail must not hide the history."""
    journal = Path(journal_path)
    if not journal.exists():
        return []
    out = []
    for line in journal.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if isinstance(entry, dict) and "path" in entry:
            out.append(entry)
    return out


def undo(vault, entry: dict, write: bool = False) -> dict:
    """
    --------------------------------------------------------------------------
    Purpose:
        Put one journalled note back to the size it had before that write.
        Dry-run by default (R16): nothing is touched until write is True.

    Inputs:
        vault (Path | str): the vault root
        entry (dict): one record from read_records
        write (bool): False previews, True performs

    Outputs:
        report (dict): action ("delete", "truncate", "noop" or "refused"),
        the resolved path, the sizes involved, and a reason when refused.
    --------------------------------------------------------------------------
    """
    root = Path(vault).resolve()
    target = (root / entry["path"]).resolve()
    # The record comes from a file, and a file is untrusted input (R24).
    if root != target and root not in target.parents:
        return {"action": "refused", "path": str(target),
                "reason": "resolves outside the vault"}
    before = int(entry.get("before", 0))
    if not target.exists():
        return {"action": "noop", "path": str(target),
                "reason": "target no longer exists"}
    current = target.stat().st_size
    if before == 0:
        report = {"action": "delete", "path": str(target),
                  "before": before, "current": current}
        if write:
            target.unlink()
        return report
    report = {"action": "truncate", "path": str(target),
              "before": before, "current": current}
    if current < before:
        report["reason"] = "file is already smaller than the journalled size"
        report["action"] = "refused"
        return report
    if write:
        with target.open("r+b") as handle:
            handle.truncate(before)
    return report


def main(argv: "list[str] | None" = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--journal", required=True)
    parser.add_argument("--vault", default=None)
    parser.add_argument("--list", action="store_true",
                        help="print every record as JSON, newest last")
    parser.add_argument("--undo", metavar="INDEX", default=None,
                        help="index into --list, or 'last'; dry-run without --yes")
    parser.add_argument("--yes", action="store_true",
                        help="authorise the undo; without it nothing is written")
    args = parser.parse_args(argv)

    records = read_records(args.journal)
    if args.undo is None or args.list:
        print(json.dumps({"records": records}, ensure_ascii=False, indent=2))
        if args.undo is None:
            return 0
    writes = [r for r in records if r.get("state") in (STATE_WRITE, STATE_EDGE)]
    if not writes:
        print("[JOURNAL] no completed write to undo", file=sys.stderr)
        return 1
    try:
        entry = writes[-1] if args.undo == "last" else writes[int(args.undo)]
    except (ValueError, IndexError):
        print(f"[JOURNAL] no record at index {args.undo}", file=sys.stderr)
        return 1
    if not args.vault:
        print("[JOURNAL] --vault is required to undo", file=sys.stderr)
        return 1
    report = undo(args.vault, entry, write=args.yes)
    report["applied"] = bool(args.yes) and report["action"] != "refused"
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if report["action"] == "refused" else 0


if __name__ == "__main__":
    sys.exit(main())
