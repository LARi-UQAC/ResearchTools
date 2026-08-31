#!/usr/bin/env python3
"""
daemon_outbox.py - the outbox layout the vault daemon works on, and nothing else.

Split out of vault_daemon.py so neither file passes the 4096-token ceiling, and
because these two things fail for different reasons: what follows is filesystem
mechanics, while the loop next door is the event traversal that calls a model.

The filesystem IS the queue, so no broker and no dependency:

    raw/            inbound, written by any session, subagent or hook
    working/        claimed, owned by exactly one daemon
    raw/sent/       delivered
    needs-review/   parked, for a human or for local-writer
    state/          one JSON file per in-flight event
    queue/*         deferred work, drained in batch

Two DIFFERENT locks live here and they are not interchangeable. The write lock
serializes writers so a file is never corrupted. The singleton lock admits one
daemon per machine: without it two daemons classify and draft every drop twice,
paying two model calls for one result, which serializing the writes does not
prevent. Claiming is the third mechanism, a rename out of raw/, atomic, so the
winner owns the drop and the loser gets nothing.
"""
import json
import sys
from datetime import date
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import outbox_io  # noqa: E402
import vault_lock  # noqa: E402

RAW = "raw"
SENT = "sent"
NEEDS_REVIEW = "needs-review"
STATE = "state"
QUEUE = "queue"
WORKING = "working"


class OutboxLayout:
    """
    --------------------------------------------------------------------------
    Purpose:
        Own the outbox directories, the configuration lookups, the two locks,
        the claim, the recovery sweep and the deferred queues. The daemon loop
        inherits this and adds only the event traversal.

    Inputs:
        vault (Path), outbox (Path), config (dict), today (str | None)

    Outputs:
        Instance methods; nothing here calls a model except drain(), which
        delegates to daemon_drains.
    --------------------------------------------------------------------------
    """

    def __init__(self, vault, outbox, config, today=None):
        self.vault = Path(vault)
        self.outbox = Path(outbox)
        self.config = config
        self.today = today or date.today().isoformat()
        self.reports = []
        for folder in (RAW, f"{RAW}/{SENT}", SENT, NEEDS_REVIEW, STATE, QUEUE,
                       WORKING):
            (self.outbox / folder).mkdir(parents=True, exist_ok=True)

    def _cfg(self, key):
        return outbox_io.require(self.config, "daemon", key)

    def _lock(self):
        return vault_lock.VaultLock(
            self.outbox.parent / "obsidian-outbox.lock",
            acquire_timeout_s=outbox_io.require(self.config, "lock", "acquire_timeout_s"),
            stale_after_s=outbox_io.require(self.config, "lock", "stale_after_s"),
            poll_interval_s=outbox_io.require(self.config, "lock", "poll_interval_s"))

    def pending(self) -> list:
        """Only *.md, so a note still being staged as .tmp is invisible."""
        return sorted(p for p in (self.outbox / RAW).glob("*.md") if p.is_file())

    def singleton_lock(self):
        """A SECOND lock, distinct from the write lock: this one says one daemon
        per machine. The outbox is machine-global, so two sessions each starting
        a daemon would both poll the same raw/ directory. The write lock alone
        does not prevent that - it serializes the writes, so the vault survives,
        but each drop is classified and drafted twice, which is two model calls
        and two journal records for one learning."""
        return vault_lock.VaultLock(
            self.outbox.parent / "vault-daemon.lock",
            acquire_timeout_s=0,
            stale_after_s=outbox_io.require(self.config, "lock", "stale_after_s"),
            poll_interval_s=outbox_io.require(self.config, "lock", "poll_interval_s"))

    def recover_working(self) -> list:
        """
        ----------------------------------------------------------------------
        Purpose:
            Put back into raw/ every drop claimed by a daemon that died before
            finishing it. Claiming moves the file out of raw/, so without this
            sweep a crash mid-event strands the drop in working/ and it is
            never seen again - the opposite of the replay guarantee the crash
            ordering was designed for.

            Safe to run at startup only because one daemon runs per machine:
            with the singleton lock held, nothing in working/ can belong to a
            LIVE daemon.

        Inputs:
            none (reads outbox/working/)

        Outputs:
            recovered (list): the file names put back
        ----------------------------------------------------------------------
        """
        recovered = []
        stale_states = sorted(p.name for p in (self.outbox / STATE).glob("*.json"))
        if stale_states:
            # A state file outlives its event only when the daemon died between
            # the write and the archive. Naming them is the point: they say
            # which notes to check in the journal.
            print(f"[DAEMON] {len(stale_states)} event(s) left state behind: "
                  f"{', '.join(stale_states)}", file=sys.stderr)
        for stranded in sorted((self.outbox / WORKING).glob("*.md")):
            target = self.outbox / RAW / stranded.name
            if target.exists():
                stranded.unlink()      # the drop came back on its own
                continue
            stranded.rename(target)
            recovered.append(stranded.name)
        if recovered:
            print(f"[DAEMON] recovered {len(recovered)} stranded drop(s): "
                  f"{', '.join(recovered)}", file=sys.stderr)
        return recovered

    def drain(self, model: str, window: int) -> dict:
        """Consume both deferred queues. Kept off the event path: judging
        fifteen pairs inline would pin the GPU for about ten minutes per drop
        at the measured median call time."""
        import daemon_drains
        report = {"consolidation": None, "phantoms": None, "graphify": None}
        journal = self.outbox.parent / "vault-journal.jsonl"
        queued = self.read_queue("consolidate")
        if queued:
            report["consolidation"] = daemon_drains.drain_consolidation(
                self.vault, model, window, self.config, journal, self._lock())
            self.clear_queue("consolidate")
        # Dead links are the vault's other defect, and the local model judges
        # them too: a vault it manages has to be clean, not merely appended to.
        # Unlike the consolidation queue this one is not driven by what was just
        # written, since a phantom can be created by any writer at any time.
        try:
            import daemon_phantoms
            report["phantoms"] = daemon_phantoms.drain_phantoms(
                self.vault, model, window, self.config, journal, self._lock())
        except Exception as exc:                       # noqa: BLE001
            # A failed link audit must never cost the rest of the drain.
            report["phantoms"] = {"error": str(exc)}

        graph_paths = self.read_queue("graphify")
        if graph_paths:
            root = self.config.get("daemon", {}).get("graphify_repo_root")
            if not root:
                print("[DAEMON] daemon.graphify_repo_root is not configured, so "
                      f"{len(graph_paths)} queued path(s) will never be graphed. "
                      "Set it to a repository root, or accept that this queue is "
                      "inert.", file=sys.stderr)
                # R1/R3: no configured repository is a stated skip, never a
                # guess from the working directory the operator started in.
                report["graphify"] = {
                    "skipped": "daemon.graphify_repo_root is not configured"}
            else:
                report["graphify"] = daemon_drains.drain_graphify(
                    graph_paths, Path(root),
                    outbox_io.require(self.config, "probe", "request_timeout_s"))
                self.clear_queue("graphify")
        return report

    def read_queue(self, name: str) -> list:
        path = self.outbox / QUEUE / name
        if not path.exists():
            return []
        return [line.strip() for line in
                path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def clear_queue(self, name: str) -> None:
        (self.outbox / QUEUE / name).write_text("", encoding="utf-8", newline="")

    def claim(self, drop_file: Path):
        """
        ----------------------------------------------------------------------
        Purpose:
            Take exclusive ownership of one drop by renaming it out of raw/.
            The rename is the claim: whoever wins it processes the drop, and a
            loser sees FileNotFoundError because the source is already gone.
            Belt and braces with the singleton lock, since a stale singleton
            lock can be reclaimed while its holder is still alive.

        Inputs:
            drop_file (Path): the drop in outbox/raw/

        Outputs:
            claimed (Path | None): the working copy, or None if someone else
            took it first.
        ----------------------------------------------------------------------
        """
        target = self.outbox / WORKING / drop_file.name
        try:
            drop_file.rename(target)
        except (FileNotFoundError, OSError):
            return None
        return target

    def park(self, drop_file: Path, reason: str) -> None:
        target = self.outbox / NEEDS_REVIEW / drop_file.name
        note = (f"<!-- parked: {reason} -->\n"
                + drop_file.read_text(encoding="utf-8"))
        target.write_text(note, encoding="utf-8", newline="")
        drop_file.unlink()
        print(f"[DAEMON] parked {drop_file.name}: {reason}", file=sys.stderr)

    def clear_state(self, event_id: str) -> None:
        """Remove the in-flight marker once the event is over, so a state file
        that survives means a crash and nothing else."""
        (self.outbox / STATE / f"{event_id}.json").unlink(missing_ok=True)

    def write_state(self, event_id: str, payload: dict) -> Path:
        path = self.outbox / STATE / f"{event_id}.json"
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                        encoding="utf-8", newline="\n")
        return path

    def enqueue(self, rel: str) -> None:
        """
        ----------------------------------------------------------------------
        Purpose:
            Append the written path to both deferred queues, without duplicates
            and under a ceiling.

            The ceiling exists because a drain can be permanently skipped: with
            no configured repository the graphify drain never runs, correctly
            never clears its queue, and that file would otherwise grow by one
            line per filed note forever. The OLDEST entries are the ones to
            trim, since a rebuild most needs the newest paths.

        Inputs:
            rel (str): the vault-relative path just written

        Outputs:
            None. Writes both queue files.
        ----------------------------------------------------------------------
        """
        ceiling = outbox_io.require(self.config, "daemon", "queue_max_entries")
        for name in ("consolidate", "graphify"):
            entries = self.read_queue(name)
            if rel in entries:
                continue
            entries.append(rel)
            if len(entries) > ceiling:
                dropped = len(entries) - ceiling
                entries = entries[-ceiling:]
                print(f"[DAEMON] queue {name} hit its {ceiling}-entry ceiling; "
                      f"dropped {dropped} oldest entry(ies). A queue that only "
                      "grows means its drain never runs.", file=sys.stderr)
            (self.outbox / QUEUE / name).write_text(
                "\n".join(entries) + "\n", encoding="utf-8", newline="\n")
