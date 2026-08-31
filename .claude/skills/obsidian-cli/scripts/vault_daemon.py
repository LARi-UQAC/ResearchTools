#!/usr/bin/env python3
"""
vault_daemon.py - the loop that files raw knowledge drops into the vault.

A foreground console script, started by hand. No Windows service and no
scheduled task until it has run unattended for several days.

    outbox/raw/<slug>.md  ->  CLASSIFY -> ROUTE -> DRAFT -> WRITE -> ENQUEUE

CLASSIFY and DRAFT call the local model (daemon_states.py). ROUTE, WRITE and
ENQUEUE are Python. Anything ROUTE refuses moves to outbox/needs-review/ with
the reason, and the daemon carries on: a session picks those up by dispatching
local-writer, which classifies with the whole reusable layer in context. The
daemon never retries a parked event, since re-running a judgment the model
already failed produces the same answer more slowly.

Crash ordering, per event: journal, write, verify by st_size, then move the
source to raw/sent/. A crash between any two of those leaves the source in
raw/, so the event replays on restart, and the replay is a no-op because
outbox_io.write_note returns early when the body is already present.

State lives on disk, never in a conversation: one JSON file per in-flight event
under outbox/state/. The model is stateless between events.

Consolidation and graphify are NOT on this path. At the measured median call
time, judging fifteen candidate pairs inline would pin the GPU for about ten
minutes per drop; they are queued and drained in batch (daemon_drains.py).
"""
import argparse
import json
import signal
import sys
import time
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import daemon_states as ds  # noqa: E402
import outbox_io  # noqa: E402
import vault_lock  # noqa: E402
from daemon_outbox import (NEEDS_REVIEW, OutboxLayout, QUEUE,  # noqa: E402
                           RAW, SENT, STATE, WORKING)
from daemon_states import ob  # noqa: E402

OUTBOX = Path.home() / ".claude" / "obsidian-outbox"

_STOP = {"requested": False}


def _request_stop(signum, frame):
    """Finish the event in flight, release the lock, leave the state file. A
    lock abandoned by a killed daemon blocks every session's local-writer until
    the staleness ceiling expires."""
    _STOP["requested"] = True
    print("[DAEMON] stop requested, finishing the event in flight",
          file=sys.stderr)


class VaultDaemon(OutboxLayout):
    """
    --------------------------------------------------------------------------
    Purpose:
        One event's traversal, and the loop that feeds it. The outbox
        mechanics it stands on live in daemon_outbox.OutboxLayout.

    Inputs:
        vault (Path), outbox (Path), config (dict), today (str | None)

    Outputs:
        Used through run_once() for one poll, or run_forever() for the loop.
    --------------------------------------------------------------------------
    """

    def handle(self, drop_file: Path, model: str, window: int) -> dict:
        """
        ----------------------------------------------------------------------
        Purpose:
            Take one raw drop from CLASSIFY to ENQUEUE.

        Inputs:
            drop_file (Path): the drop in outbox/raw/
            model (str): the resolved tag
            window (int): the measured window for that tag

        Outputs:
            report (dict): the observability line - event id, technology,
            confidence, states traversed, model calls, wall time. Enough to
            tune the confidence threshold from evidence rather than opinion.
        ----------------------------------------------------------------------
        """
        started = time.monotonic()
        event_id = drop_file.stem
        report = {"event": event_id, "states": [], "model_calls": 0,
                  "technology": None, "confidence": None, "scope": None,
                  "model_project": None, "source_project": None,
                  "scope_divergence": None, "parked": None}
        timeout = outbox_io.require(self.config, "probe", "request_timeout_s")
        try:
            drop = ds.read_drop(drop_file)
            report["states"].append("READ")

            folders = ds.technology_folders(self.vault)
            classification = ds.classify(drop, folders, model, window, timeout)
            report["model_calls"] += 1
            report["states"].append("CLASSIFY")
            report["technology"] = classification.get("technology")
            report["confidence"] = classification.get("confidence")
            report["scope"] = classification.get("scope")
            # What the model ANSWERED for project, beside what the source
            # declared. Routing uses the source alone, so the pair is the only
            # place a divergence shows: a threshold cannot be tuned from a log
            # that records agreement it never checked.
            report["model_project"] = classification.get("project")
            report["source_project"] = drop["project"] or None
            # A drop naming a project and filed as reusable is LEGITIMATE - the
            # documented raw drop does exactly that, a reusable lesson tagged
            # with where it came from. It is also how a genuine project entry
            # goes silently to the wrong shelf, which happened on 2026-08-28 at
            # 0.95 confidence. Unverifiable either way, so it is flagged rather
            # than refused: one greppable field beats a misfiling nobody sees.
            report["scope_divergence"] = bool(
                drop["project"] and classification.get("scope") == "reusable")

            route = ds.route(classification, drop, self.vault, folders,
                             self._cfg("classify_confidence_min"), self.today)
            report["states"].append("ROUTE")

            body = ds.draft(drop, route, classification, model, window, timeout,
                            self.today, self._cfg("draft_max_attempts"),
                            vault=self.vault)
            report["model_calls"] += 1
            report["states"].append("DRAFT")

            self.write_state(event_id, {"event": event_id, "state": "WRITE",
                                        "rel": route["rel"],
                                        "action": route["action"],
                                        "source": drop_file.name})
            directive = (f'<!-- obsidian: {route["action"]} '
                         f'path="{route["rel"]}" -->')
            staged = outbox_io.stage(self.outbox, event_id, body, directive)
            with self._lock():
                written = outbox_io.flush_one(
                    staged, self.vault, self.outbox / SENT,
                    self.outbox.parent / "vault-journal.jsonl")
            if not written:
                raise ds.EventRefused("the write had no effect on disk")
            report["states"].append("WRITE")
            report["rel"] = route["rel"]

            self.enqueue(route["rel"])
            report["states"].append("ENQUEUE")
            # Last, and only now: the source leaves raw/. Anything that fails
            # before this point replays on the next poll.
            drop_file.replace(self.outbox / RAW / SENT / drop_file.name)
        except ds.EventRefused as exc:
            report["parked"] = str(exc)
            if drop_file.exists():
                self.park(drop_file, str(exc))
        except vault_lock.LockError as exc:
            # Contention is not a defect of the drop: put it BACK in raw/ so the
            # next poll retries it, and never park it as if it were unfilable.
            # Measured 2026-08-28 on the first live drill: run_once claims a
            # drop by renaming it into working/ BEFORE calling this, so the
            # earlier "leave it in raw/" left it somewhere only a daemon
            # RESTART would look, through recover_working(). The drill reported
            # filed_after_release false and the drop sat in working/ for over
            # an hour with the daemon polling beside it.
            report["parked"] = f"deferred, {exc}"
            back = self.outbox / RAW / drop_file.name
            if drop_file.exists() and drop_file != back:
                if back.exists():
                    drop_file.unlink()     # the drop came back on its own
                else:
                    drop_file.replace(back)
        self.clear_state(event_id)
        report["seconds"] = round(time.monotonic() - started, 2)
        self.reports.append(report)
        print("[DAEMON] " + json.dumps(report, ensure_ascii=False),
              file=sys.stderr)
        return report

    def run_once(self) -> list:
        drops = self.pending()
        if not drops:
            return []
        model = ob.resolve_model("writer")
        window = context_window(model)
        reports = []
        for drop in drops:
            claimed = self.claim(drop)
            if claimed is None:
                # Another daemon took it between the glob and the rename.
                continue
            reports.append(self.handle(claimed, model, window))
        return reports

    def run_forever(self) -> int:
        interval = self._cfg("poll_interval_s")
        try:
            singleton = self.singleton_lock().acquire()
        except vault_lock.LockError:
            print("[DAEMON] another daemon is already watching this outbox; "
                  "refusing to start a second one", file=sys.stderr)
            return 1
        self.recover_working()
        drain_every = self._cfg("drain_idle_s")
        last_drain = time.monotonic()
        print(f"[DAEMON] watching {self.outbox / RAW} every {interval}s",
              file=sys.stderr)
        while not _STOP["requested"]:
            try:
                self.run_once()
            except ob.BridgeError as exc:
                # No fallback tag (R8). Say it and keep watching, so the drops
                # wait in raw/ rather than being filed by something weaker.
                print(f"[DAEMON] {exc}", file=sys.stderr)
            if (time.monotonic() - last_drain >= drain_every
                    and not self.pending()):
                # Quiet interval only: no event in flight, nothing waiting.
                try:
                    model = ob.resolve_model("writer")
                    print("[DAEMON] " + json.dumps(
                        self.drain(model, context_window(model)),
                        ensure_ascii=False), file=sys.stderr)
                except (ob.BridgeError, ds.EventRefused) as exc:
                    print(f"[DAEMON] drain skipped: {exc}", file=sys.stderr)
                last_drain = time.monotonic()
            time.sleep(interval)
        singleton.release()
        print("[DAEMON] stopped", file=sys.stderr)
        return 0


def context_window(model: str) -> int:
    import context_budget
    return context_budget.read_retained_num_ctx(
        context_budget.DEFAULT_CONFIG_PATH, model)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Vault event daemon.")
    parser.add_argument("--outbox", default=str(OUTBOX))
    parser.add_argument("--once", action="store_true",
                        help="handle what is pending, then exit")
    parser.add_argument("--drain", action="store_true",
                        help="run the deferred drains by hand, then exit")
    parser.add_argument("--dry-run", action="store_true",
                        help="list what would be handled, touch nothing")
    args = parser.parse_args(argv)

    config = outbox_io.load_config()
    vault = outbox_io.resolve_vault()
    if vault is None:
        print("[DAEMON] no vault (set OBSIDIAN_VAULT); nothing to do",
              file=sys.stderr)
        return 0
    daemon = VaultDaemon(vault, Path(args.outbox), config)
    if args.dry_run:
        print(json.dumps({"pending": [p.name for p in daemon.pending()]},
                         ensure_ascii=False, indent=2))
        return 0
    signal.signal(signal.SIGINT, _request_stop)
    signal.signal(signal.SIGTERM, _request_stop)
    if args.drain:
        model = ob.resolve_model("writer")
        print(json.dumps(daemon.drain(model, context_window(model)),
                         ensure_ascii=False, indent=2))
        return 0
    if args.once:
        daemon.recover_working()
        daemon.run_once()
        return 0
    return daemon.run_forever()


if __name__ == "__main__":
    sys.exit(main())
