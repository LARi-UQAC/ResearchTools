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
from datetime import datetime, timezone
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

CODER_SCRIPTS = SCRIPTS.parent.parent / "loop-engineer" / "scripts"
if str(CODER_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(CODER_SCRIPTS))

import context_budget  # noqa: E402
import daemon_ask  # noqa: E402
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

    def pending_asks(self) -> list:
        """
        ----------------------------------------------------------------------
        Purpose:
            List ask requests waiting to be answered, without touching them.
            The caller uses this to decide whether resolving a model tag is
            worth doing at all (#6: resolving on every poll pass even with
            an empty queue costs a model-resolution round trip per pass and,
            worse, dies on a tag with no measured window before a single
            real request has ever arrived).

        Inputs:
            None

        Outputs:
            requests (list): sorted Path list of outbox/ask/requests/*.json,
            empty when the directory does not exist yet or holds nothing.
        ----------------------------------------------------------------------
        """
        requests_dir = self.outbox / "ask" / "requests"
        if not requests_dir.is_dir():
            return []
        return sorted(requests_dir.glob("*.json"))

    def _write_answer(self, request_file: Path, result: dict) -> dict:
        """Write one answer atomically, named after the request file (R24),
        then consume the request."""
        answers_dir = self.outbox / "ask" / "answers"
        answers_dir.mkdir(parents=True, exist_ok=True)
        result["id"] = request_file.stem
        tmp = answers_dir / f"{request_file.stem}.json.tmp"
        final = answers_dir / f"{request_file.stem}.json"
        tmp.write_text(json.dumps(result, ensure_ascii=False),
                       encoding="utf-8", newline="\n")
        tmp.replace(final)
        request_file.unlink(missing_ok=True)
        return result

    def fail_pending_asks(self, reason: str, now: str) -> list:
        """
        ----------------------------------------------------------------------
        Purpose:
            Answer every waiting request with status=error and the reason,
            so the caller sees why instead of timing out on a daemon that is
            running but cannot reach its model.

        Inputs:
            reason (str): what failed, shown to the caller verbatim
            now (str): ISO 8601 stamp for answered_at (R19)

        Outputs:
            answers (list): one record per request answered
        ----------------------------------------------------------------------
        """
        return [self._write_answer(request_file,
                                   {"answered_at": now, "status": "error",
                                    "reason": reason})
                for request_file in self.pending_asks()]

    def answer_pending_asks(self, now: str, resolve=None,
                            window_of=None) -> list:
        """
        ----------------------------------------------------------------------
        Purpose:
            Resolve the writer-role model and answer every pending ask. The
            single entry point both run_forever and --once use, so a model
            that cannot be resolved (no state file, no measured window,
            Ollama down) is reported to each waiting caller rather than only
            printed to this daemon's own console.

        Inputs:
            now (str): ISO 8601 "now", injected (R19)
            resolve (callable): role -> tag; defaults to ob.resolve_model
            window_of (callable): tag -> retained window; defaults to
                context_window

        Outputs:
            answers (list): one record per request handled; empty, and no
            model resolved at all, when nothing is waiting
        ----------------------------------------------------------------------
        """
        if not self.pending_asks():
            return []
        resolve = resolve or ob.resolve_model
        window_of = window_of or context_window
        try:
            model = resolve("writer")
            window = window_of(model)
        except Exception as exc:  # noqa: BLE001 - reported, never substituted
            return self.fail_pending_asks(
                f"local model unavailable: {type(exc).__name__}: {exc}", now)
        return self.run_ask_once(model, window, now=now)

    def run_ask_once(self, model: str, window: int, now: str = None) -> list:
        """
        ----------------------------------------------------------------------
        Purpose:
            Drain outbox/ask/requests/, answering each with the local model
            and vault search, then remove the request once answered so a
            crash mid-answer simply retries it on the next poll (the answer
            write is atomic tmp+replace, same discipline as write_note).
            Also prunes any answer file older than the TTL that nothing has
            polled for, so outbox/ask/answers/ does not grow forever when a
            caller times out before reading its own answer.

        Inputs:
            model (str): the resolved writer-role tag
            window (int): the measured retained window for that tag
            now (str | None): ISO 8601 "now" for age/TTL math, injected by
            the caller (R19); defaults to self.today, the same value every
            existing caller of this method already relied on before this
            parameter existed

        Outputs:
            answers (list): one record per request handled, for the report
        ----------------------------------------------------------------------
        """
        now = now or self.today
        requests_dir = self.outbox / "ask" / "requests"
        answers_dir = self.outbox / "ask" / "answers"
        requests_dir.mkdir(parents=True, exist_ok=True)
        answers_dir.mkdir(parents=True, exist_ok=True)
        # An answer nothing ever polled for (the caller timed out first, or
        # never polled) sits in answers_dir forever otherwise. Pruned by
        # real mtime age, the same class of disk-hygiene check
        # vault_lock.py's own staleness ceiling already uses - the answer
        # file's age is a fact about the filesystem, not something a test
        # needs to control through the `now` this method's callers inject.
        # An answer nothing ever polled for (the caller timed out first, or
        # never polled) sits in answers_dir forever otherwise. Pruned by
        # real mtime age, the same class of disk-hygiene check
        # vault_lock.py's own staleness ceiling already uses - the answer
        # file's age is a fact about the filesystem, not something a test
        # needs to control through the `now` this method's callers inject.
        ttl = outbox_io.require(self.config, "daemon", "ask_request_ttl_s")
        for stale in answers_dir.glob("*.json"):
            try:
                age = time.time() - stale.stat().st_mtime
            except OSError:
                continue
            if age > ttl:
                stale.unlink(missing_ok=True)
        timeout = outbox_io.require(self.config, "probe", "request_timeout_s")
        handled = []
        for request_file in self.pending_asks():
            try:
                request = daemon_ask.read_request(request_file)
                result = daemon_ask.answer(
                    request, self.vault, model, window, timeout,
                    self.config, today=now)
            except daemon_ask.AskRefused as exc:
                result = {"answered_at": now, "status": "refused",
                         "reason": str(exc)}
            except Exception as exc:  # noqa: BLE001 - R8/R11 defence in
                # depth: one request's unexpected failure (a bad timestamp
                # shape, a search_vault I/O error, anything not already
                # named above) must never take the whole poll loop down.
                result = {"answered_at": now, "status": "error",
                         "reason": f"internal error: {exc}"}
            # The answer's identity is always the REQUEST FILE'S OWN name
            # (already constrained by the glob that found it), never the
            # payload's declared "id" (R24: an untrusted "id" of
            # "../../evil" must not be able to name a file outside
            # answers_dir, and an absent "id" must not collide on "None").
            handled.append(self._write_answer(request_file, result))
        return handled

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

    def _log_bridge_error(self, message: str, interval_s: float) -> None:
        """
        ----------------------------------------------------------------------
        Purpose:
            Print a BridgeError at most once per `interval_s` for an
            UNCHANGED message; a changed message always prints at once. PR
            #42 review (Medium): poll_interval_s is a few seconds, so an
            extended Ollama outage used to write one identical line per poll
            pass - unbounded growth between daemon restarts, since the log
            only rotates at the NEXT start (vault-daemon-autostart.ps1), not
            while a long-running daemon (this PR's whole point) keeps
            polling through the outage.

        Inputs:
            message (str): the exception text to show
            interval_s (float): minimum seconds between two IDENTICAL
            messages (R0, read by the caller from daemon-config.json)

        Outputs:
            None. Side effect: writes "[DAEMON] <message>" to stderr, at
            most once per interval for a repeated message.
        ----------------------------------------------------------------------
        """
        last = self._last_bridge_error
        now = time.monotonic()
        if message == last["message"] and (now - last["at"]) < interval_s:
            return
        print(f"[DAEMON] {message}", file=sys.stderr)
        last["message"] = message
        last["at"] = now

    def run_forever(self) -> int:
        interval = self._cfg("poll_interval_s")
        try:
            singleton = self.singleton_lock().acquire()
        except vault_lock.LockError:
            print("[DAEMON] another daemon is already watching this outbox; "
                  "refusing to start a second one", file=sys.stderr)
            return 1
        self._last_bridge_error = {"message": None, "at": 0.0}
        bridge_error_log_interval_s = self._cfg("bridge_error_log_interval_s")
        self.recover_working()
        drain_every = self._cfg("drain_idle_s")
        last_drain = time.monotonic()
        print(f"[DAEMON] watching {self.outbox / RAW} every {interval}s",
              file=sys.stderr)
        ask_interval = self._cfg("ask_poll_interval_s")
        last_ask = time.monotonic()
        while not _STOP["requested"]:
            try:
                self.run_once()
            except ob.BridgeError as exc:
                # No fallback tag (R8). Say it and keep watching, so the drops
                # wait in raw/ rather than being filed by something weaker.
                # Covers an unreachable Ollama (resolve_model wraps the
                # resolver's ResolverError) and a tag with no measured window
                # (context_window wraps ContextBudgetError). Diagnosed
                # 2026-10-01: before the wrapping, 11 login-time deaths in
                # vault-daemon.log, Ollama not yet listening.
                self._log_bridge_error(str(exc), bridge_error_log_interval_s)
            if time.monotonic() - last_ask >= ask_interval:
                # answer_pending_asks resolves a model only when a request is
                # waiting, and a resolution failure becomes an error answer
                # the caller reads, never just a line on this console.
                for answer in self.answer_pending_asks(
                        datetime.now(timezone.utc).isoformat()):
                    if answer.get("status") != "ok":
                        print(f"[DAEMON] ask {answer['id']}: "
                              f"{answer['status']} - {answer.get('reason')}",
                              file=sys.stderr)
                last_ask = time.monotonic()
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
            # The ask queue's own cadence (ask_poll_interval_s) is what
            # plan1's Review Focus calls for: a caller waiting on
            # /api/voice/ask should not sit behind the raw-drop poll
            # interval, which is typically much coarser.
            time.sleep(min(interval, ask_interval))
        singleton.release()
        print("[DAEMON] stopped", file=sys.stderr)
        return 0


def context_window(model: str) -> int:
    """
    --------------------------------------------------------------------------
    Purpose:
        Read the measured context window retained for `model`.

    Inputs:
        model (str): the tag the resolver returned

    Outputs:
        window (int): retained num_ctx, in tokens

    Raises:
        ob.BridgeError: no usable measurement for this tag (a
        context_budget.ContextBudgetError, chained). Surfaced as the bridge's
        own refusal type so run_forever's existing handlers keep the daemon
        polling; diagnosed 2026-10-01, see run_forever.
    --------------------------------------------------------------------------
    """
    try:
        return context_budget.read_retained_num_ctx(
            context_budget.DEFAULT_CONFIG_PATH, model)
    except context_budget.ContextBudgetError as exc:
        raise ob.BridgeError(str(exc)) from exc


def main(argv=None) -> int:
    outbox_io.configure_streams()
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
        print(json.dumps({
            "pending": [p.name for p in daemon.pending()],
            "pending_asks": [p.name for p in daemon.pending_asks()],
        }, ensure_ascii=False, indent=2))
        return 0
    signal.signal(signal.SIGINT, _request_stop)
    signal.signal(signal.SIGTERM, _request_stop)
    if args.drain:
        try:
            model = ob.resolve_model("writer")
            window = context_window(model)
            result = daemon.drain(model, window)
        except (ob.BridgeError, ds.EventRefused) as exc:
            # PR #42 review (Low): --drain used to let this propagate as a
            # bare traceback when Ollama was down, rather than the explicit
            # refusal run_forever already gives the same failure (R12: 2 is
            # a refusal by design, not a crash).
            print(f"[DAEMON] drain refused: {exc}", file=sys.stderr)
            return 2
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    if args.once:
        daemon.recover_working()
        try:
            daemon.run_once()
        except ob.BridgeError as exc:
            # Same refusal run_forever's own loop already catches (R12); only
            # run_once's model resolution can raise here, and only when a
            # drop is actually pending - an empty raw/ never touches Ollama.
            print(f"[DAEMON] once refused: {exc}", file=sys.stderr)
            return 2
        daemon.answer_pending_asks(datetime.now(timezone.utc).isoformat())
        return 0
    return daemon.run_forever()


if __name__ == "__main__":
    sys.exit(main())
