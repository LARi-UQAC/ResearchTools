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
STATE_SNAPSHOT = "SNAPSHOT"   # full text kept before an in-place substitution


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


def snapshot(journal_path, path: str, content: str, source: str,
             at: "str | None" = None) -> dict:
    """
    --------------------------------------------------------------------------
    Purpose:
        Keep a note's FULL text before an in-place substitution, so the edit can
        be undone.

        A size is enough to undo an append, since the addition sits at the end
        and truncating removes exactly it. A link rewrite replaces text in the
        middle and can leave the file the same length, so size says nothing and
        truncation would corrupt. That asymmetry is why phantom repair was
        judged irreversible and kept out of the daemon; this record is what
        makes it reversible, and therefore allowed.

    Inputs:
        journal_path (Path | str): the .jsonl journal
        path (str): the note's vault-relative path
        content (str): the note's text BEFORE the edit
        source (str): what is about to edit it
        at (str | None): ISO timestamp; generated when the caller passes none

    Outputs:
        entry (dict): the record as written
    --------------------------------------------------------------------------
    """
    entry = {"path": path, "before": len(content.encode("utf-8")), "after": None,
             "source": source, "state": STATE_SNAPSHOT, "at": at or utc_now_iso(),
             "content": content}
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
    if entry.get("state") == STATE_SNAPSHOT and "content" in entry:
        # A substitution is undone by restoring the text, never by truncating:
        # the edit sat in the middle and may not have changed the length at all.
        report = {"action": "restore", "path": str(target),
                  "before": entry.get("before")}
        if write:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(entry["content"], encoding="utf-8", newline="")
        return report
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


def undo_since(vault, records: list, since: int, write: bool = False) -> dict:
    """
    --------------------------------------------------------------------------
    Purpose:
        Undo every undoable record from the end of the journal back down to
        `since`, NEWEST FIRST, and report what each one did.

        Newest first is not a preference. An append is undone by truncating to
        a journalled size, so undoing an older record before a newer one leaves
        the file shorter than the newer record's baseline, and that newer undo
        is then correctly refused. Walking backwards is what makes a run of
        undos compose.

        This is the teardown the e2e drill never had: the drill files notes into
        the real vault and stops, so `since` is the undoable-record count taken
        BEFORE it ran, and everything after that index is the drill's.

    Inputs:
        vault (Path | str): the vault root
        records (list): every record, from read_records
        since (int): index into the UNDOABLE subset; records below it are left
        write (bool): False previews, True performs (R16)

    Outputs:
        report (dict): undone (list of per-record reports), refused (int),
        and the range that was considered.
    --------------------------------------------------------------------------
    """
    undoable = [r for r in records
                if r.get("state") in (STATE_WRITE, STATE_EDGE, STATE_SNAPSHOT)]
    since = max(0, int(since))
    targets = list(range(since, len(undoable)))
    done = []
    for index in reversed(targets):
        report = undo(vault, undoable[index], write=write)
        report["index"] = index
        done.append(report)
    return {"considered": {"from": since, "to": len(undoable)},
            "undone": done,
            "refused": sum(1 for r in done if r["action"] == "refused"),
            "applied": bool(write)}


def main(argv: "list[str] | None" = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--journal", required=True)
    parser.add_argument("--vault", default=None)
    parser.add_argument("--list", action="store_true",
                        help="print every record as JSON, newest last")
    parser.add_argument("--undo", metavar="INDEX", default=None,
                        help="index into --list, or 'last'; dry-run without --yes")
    parser.add_argument("--undo-since", metavar="INDEX", type=int, default=None,
                        dest="undo_since",
                        help="undo every record from INDEX to the end, newest "
                             "first; the teardown for a drill run. Dry-run "
                             "without --yes")
    parser.add_argument("--count", action="store_true",
                        help="print the number of undoable records and exit, "
                             "so a caller can record a baseline before a run")
    parser.add_argument("--yes", action="store_true",
                        help="authorise the undo; without it nothing is written")
    args = parser.parse_args(argv)

    records = read_records(args.journal)

    if args.count:
        # The baseline a drill takes before it runs. Printed bare, so a shell
        # can capture it without parsing JSON.
        print(len([r for r in records if r.get("state")
                   in (STATE_WRITE, STATE_EDGE, STATE_SNAPSHOT)]))
        return 0

    if args.undo_since is not None:
        if not args.vault:
            print("[JOURNAL] --vault is required to undo", file=sys.stderr)
            return 1
        report = undo_since(args.vault, records, args.undo_since,
                            write=args.yes)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 1 if report["refused"] else 0

    if args.undo is None or args.list:
        print(json.dumps({"records": records}, ensure_ascii=False, indent=2))
        if args.undo is None:
            return 0
    writes = [r for r in records
              if r.get("state") in (STATE_WRITE, STATE_EDGE, STATE_SNAPSHOT)]
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
