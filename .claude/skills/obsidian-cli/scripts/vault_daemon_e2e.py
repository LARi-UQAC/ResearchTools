#!/usr/bin/env python3
"""
vault_daemon_e2e.py - the end-to-end drill for the vault event daemon.

Everything else about this daemon is proved against fixtures. This one runs
against the REAL vault, the real daemon and the real model, because the offline
suite cannot see the things that only fail in production: a prefix cache that
stops hitting, a lock two OS processes actually contend for, a model that files
a note somewhere plausible and wrong.

It MUTATES the vault and DOES NOT CLEAN UP AFTER ITSELF. Every note it causes to
be filed stays in the vault when the run ends. Step 7 undoes exactly ONE record,
the last journalled write, because undoing one is how the journal is tested; it
is not a teardown, and there is no --keep flag (this docstring claimed both until
2026-08-28, when the first live run was prepared against it). Removing the rest
is manual, through the journal, which is why the drill refuses to start without
--yes:

    python vault_journal.py --journal <outbox parent>/vault-journal.jsonl --list
    python vault_journal.py --journal ... --vault <root> --undo <index> --yes

Every drop it creates is prefixed, so what it made is identifiable if a run is
interrupted.

Run it with the daemon already started in another window:

    python vault_daemon.py                 # window 1
    python vault_daemon_e2e.py --yes       # window 2

Steps 1 to 8 need only the daemon. Step 9 additionally evicts the resident model
to measure the reload cost, so it is opt-in with --with-eviction: it leaves the
GPU holding a different model than it found.

No vault path and no model tag is written here. The vault comes from
OBSIDIAN_VAULT via outbox_io.resolve_vault, and the tag from the resolver, which
refuses rather than substituting a weaker one.
"""
import argparse
import json
import sys
import time
from datetime import date
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import daemon_states as ds  # noqa: E402
import outbox_io  # noqa: E402
import vault_journal  # noqa: E402
import vault_lock  # noqa: E402
from daemon_states import ob  # noqa: E402

OUTBOX = Path.home() / ".claude" / "obsidian-outbox"
PREFIX = "e2e-drill"
EXPECTED_EVENT_SECONDS = 72.0   # the plan's ~1.2 min for two model calls


def drop(outbox: Path, name: str, subject: str, body: str, project=None) -> Path:
    """Stage one raw drop the way any producer would, atomically."""
    front = f"---\nsource: {PREFIX}\nsubject: {subject}\n"
    if project:
        front += f"project: {project}\n"
    return outbox_io.stage(outbox, f"{PREFIX}-{name}", front + "---\n" + body + "\n",
                           subdir="raw")


def wait_for(predicate, timeout_s: float, poll_s: float = 2.0):
    """Bounded wait (R10). Returns the elapsed seconds, or None on timeout."""
    started = time.monotonic()
    while time.monotonic() - started < timeout_s:
        found = predicate()
        if found:
            return time.monotonic() - started, found
        time.sleep(poll_s)
    return None


def journal_records(journal: Path, since: int) -> list:
    return vault_journal.read_records(journal)[since:]


def check_filed(vault, outbox, journal, since, timeout_s) -> dict:
    """Steps 1 and 5: a reusable and a project drop, filed, journalled,
    archived, and timed."""
    reusable = drop(outbox, "reusable",
                    "the outbox lock is reclaimed when its holder is gone",
                    "A lock file left by a killed process blocked every writer "
                    "until the staleness ceiling expired.")
    project = drop(outbox, "project",
                   "stage 2 of the vault daemon is code complete",
                   "The daemon files raw drops and drains consolidation in batch.",
                   project="ResearchTools")
    result = {"step": "filed and timed", "drops": [reusable.name, project.name]}
    waited = wait_for(lambda: [r for r in journal_records(journal, since)
                               if r.get("state") == vault_journal.STATE_WRITE],
                      timeout_s)
    if waited is None:
        result["pass"] = False
        result["why"] = f"nothing was journalled within {timeout_s}s"
        return result
    elapsed, records = waited
    result["seconds_to_first_write"] = round(elapsed, 1)

    # Both drops, not "at least one". Measured 2026-08-28: the step passed on a
    # run where one drop was filed and the other went to the wrong shelf, since
    # the old gate was true as soon as ONE landed.
    expected = {reusable.name, project.name}
    both = wait_for(
        lambda: expected <= {p.name for p in
                             (outbox / "raw" / "sent").glob(f"{PREFIX}-*")},
        timeout_s)
    records = [r for r in journal_records(journal, since)
               if r.get("state") == vault_journal.STATE_WRITE]
    result["written"] = [r["path"] for r in records]
    result["archived"] = sorted(p.name for p in
                                (outbox / "raw" / "sent").glob(f"{PREFIX}-*"))
    result["pass"] = both is not None
    if not result["pass"]:
        missing = sorted(expected - set(result["archived"]))
        result["why"] = (f"only {len(result['archived'])} of {len(expected)} drops "
                         f"filed within {timeout_s}s; missing {missing}. Read the "
                         "daemon window: a wrong shelf leaves no park.")
    # Step 5: the number matters as much as the pass. Materially over budget
    # means the fixed prefix is not being re-used and Stage 1 needs re-running.
    result["within_expected_time"] = elapsed <= EXPECTED_EVENT_SECONDS
    if not result["within_expected_time"]:
        result["why"] = (f"took {elapsed:.0f}s against an expected "
                         f"{EXPECTED_EVENT_SECONDS:.0f}s; re-run "
                         "local_capability_probe.py before trusting the prefix cache")
    return result


def check_parked(outbox, timeout_s) -> dict:
    """Step 2: an ambiguous drop must be parked, never guessed."""
    staged = drop(outbox, "ambiguous", "it did not work as expected",
                  "Something was slow and then it was fine again.")
    waited = wait_for(lambda: list((outbox / "needs-review").glob(f"{PREFIX}-ambiguous*")),
                      timeout_s)
    if waited is None:
        return {"step": "ambiguous parked", "pass": False,
                "why": "the daemon filed it or is still working; a guess on this "
                       "drop means the confidence threshold is too low",
                "drop": staged.name}
    _, parked = waited
    reason = parked[0].read_text(encoding="utf-8").splitlines()[0]
    return {"step": "ambiguous parked", "pass": True, "reason": reason}


def check_containment(vault, outbox, timeout_s) -> dict:
    """Step 3: nothing the model says may put a file outside the vault, and the
    daemon must survive the attempt. The drop invites a folder that cannot
    exist; the assertion is about the filesystem, not about the verdict."""
    root = Path(vault).resolve()
    outbox_root = Path(outbox).resolve()

    def siblings():
        """Everything beside the vault EXCEPT the outbox, which this drill
        legitimately writes to and which may sit in the same parent."""
        if not root.parent.exists():
            return set()
        return {p for p in root.parent.iterdir()
                if p.resolve() != outbox_root and outbox_root not in p.resolve().parents}

    before = siblings()
    drop(outbox, "escape", "../../escape and other path traversal notation",
         "A note whose subject names a traversal sequence.")
    time.sleep(min(timeout_s, 30))
    created = sorted(p.name for p in siblings() - before)
    return {"step": "containment", "pass": not created,
            "created_outside_vault": created,
            "note": "the daemon must also still be running; check its window"}


def check_collision(vault, outbox, timeout_s) -> dict:
    """Step 4: a name collision must produce a dated atomic note and leave the
    existing one byte-identical."""
    subject = "the outbox lock is reclaimed when its holder is gone"
    slug = ds.slugify(subject)
    folders = ds.technology_folders(vault)
    existing = None
    for folder in folders:
        candidate = Path(vault) / ds.RESOURCES / folder / f"{slug}.md"
        if candidate.exists():
            existing = candidate
            break
    if existing is None:
        return {"step": "collision", "pass": None,
                "why": f"no note named {slug}.md exists yet; run step 1 first, "
                       "then re-run this step so the collision is real"}
    before = existing.read_text(encoding="utf-8")
    drop(outbox, "collision", subject, "A second, unrelated learning with the same subject.")
    dated = f"{slug}-{date.today().isoformat()}.md"
    waited = wait_for(lambda: list(Path(vault).rglob(dated)), timeout_s)
    return {"step": "collision", "pass": waited is not None
            and existing.read_text(encoding="utf-8") == before,
            "expected_note": dated,
            "original_untouched": existing.read_text(encoding="utf-8") == before}


def check_drain(vault) -> dict:
    """Step 6: the deferred drain links a real pair and rejects a topic-only one
    WITH its reason. A drain that rejects nothing is the hairball warning."""
    import subprocess
    result = subprocess.run(
        [sys.executable, str(SCRIPTS / "vault_daemon.py"), "--drain"],
        capture_output=True, text=True, timeout=3600)
    try:
        report = json.loads(result.stdout)
    except ValueError:
        return {"step": "drain", "pass": False, "why": result.stderr.strip()[:300]}
    consolidation = report.get("consolidation") or {}
    accepted = consolidation.get("accepted", [])
    rejected = consolidation.get("rejected", [])
    return {"step": "drain", "pass": bool(accepted or rejected),
            "accepted": len(accepted), "rejected": len(rejected),
            "rejections_carry_reasons": all(r.get("why") for r in rejected),
            "phantoms": report.get("phantoms"),
            "note": "a drain that rejects almost nothing means the mechanism "
                    "test has stopped being applied"}


def check_undo(vault, journal) -> dict:
    """Step 7: the journal must return one note to its prior state."""
    records = [r for r in vault_journal.read_records(journal)
               if r.get("state") in (vault_journal.STATE_WRITE,
                                     vault_journal.STATE_EDGE,
                                     vault_journal.STATE_SNAPSHOT)]
    if not records:
        return {"step": "undo", "pass": False, "why": "nothing journalled to undo"}
    entry = records[-1]
    preview = vault_journal.undo(vault, entry, write=False)
    applied = vault_journal.undo(vault, entry, write=True)
    return {"step": "undo", "pass": applied.get("action") != "refused",
            "path": entry["path"], "preview": preview, "applied": applied}


def check_lock(vault, outbox, config, timeout_s) -> dict:
    """Step 8: hold the write lock the way a second writer would, and confirm
    the daemon defers instead of losing the drop."""
    lock = vault_lock.VaultLock(
        outbox.parent / "obsidian-outbox.lock",
        acquire_timeout_s=outbox_io.require(config, "lock", "acquire_timeout_s"),
        stale_after_s=outbox_io.require(config, "lock", "stale_after_s"),
        poll_interval_s=outbox_io.require(config, "lock", "poll_interval_s"))
    staged = drop(outbox, "contended", "a second writer held the lock",
                  "The daemon must defer this drop, not park it and not lose it.")
    with lock:
        time.sleep(min(timeout_s, 60))
        still_queued = staged.exists() or bool(
            list((outbox / "working").glob(f"{PREFIX}-contended*")))
    waited = wait_for(lambda: list((outbox / "raw" / "sent").glob(f"{PREFIX}-contended*")),
                      timeout_s)
    return {"step": "lock contention", "pass": still_queued and waited is not None,
            "held_while_locked": still_queued,
            "filed_after_release": waited is not None,
            "parked": bool(list((outbox / "needs-review").glob(f"{PREFIX}-contended*")))}


def check_residency(with_eviction: bool) -> dict:
    """Step 9: residency now, and what a reload costs after another role's model
    has evicted the writer. The coder tag is asked of the resolver, never named."""
    import subprocess
    ps = subprocess.run(["ollama", "ps"], capture_output=True, text=True, timeout=60)
    smi = subprocess.run(["nvidia-smi", "--query-gpu=memory.free",
                          "--format=csv,noheader"], capture_output=True,
                         text=True, timeout=60)
    report = {"step": "residency", "ollama_ps": ps.stdout.strip(),
              "free_vram": smi.stdout.strip(),
              "resident_forever": "Forever" in ps.stdout}
    if not with_eviction:
        report["eviction"] = "skipped; pass --with-eviction to measure the reload"
        report["pass"] = report["resident_forever"]
        return report
    coder = ob.resolve_model("coder")
    started = time.monotonic()
    ob._post_generate(ob.build_payload("Return the word ok.", coder,
                                       ob.DEFAULT_SEED, 2048), 600.0)
    report["coder_call_seconds"] = round(time.monotonic() - started, 1)
    report["pass"] = report["resident_forever"]
    report["note"] = ("time the next vault event by hand now: the difference is "
                      "the eviction and reload cost this design accepts")
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--yes", action="store_true",
                        help="authorise writes to the real vault; without it "
                             "the drill only reports what it would do")
    parser.add_argument("--outbox", default=str(OUTBOX))
    parser.add_argument("--timeout", type=float, default=300.0,
                        help="seconds to wait for the daemon on each step")
    parser.add_argument("--only", default=None,
                        help="comma-separated step names to run")
    parser.add_argument("--with-eviction", action="store_true",
                        help="step 9 also loads the coder-role model, evicting "
                             "the writer from the card")
    args = parser.parse_args(argv)

    vault = outbox_io.resolve_vault()
    if vault is None:
        print("[E2E] no vault (set OBSIDIAN_VAULT); refusing to run",
              file=sys.stderr)
        return 1
    outbox = Path(args.outbox)
    config = outbox_io.load_config()
    journal = outbox.parent / "vault-journal.jsonl"
    since = len(vault_journal.read_records(journal))

    steps = {
        "filed": lambda: check_filed(vault, outbox, journal, since, args.timeout),
        "parked": lambda: check_parked(outbox, args.timeout),
        "containment": lambda: check_containment(vault, outbox, args.timeout),
        "collision": lambda: check_collision(vault, outbox, args.timeout),
        "drain": lambda: check_drain(vault),
        "undo": lambda: check_undo(vault, journal),
        "lock": lambda: check_lock(vault, outbox, config, args.timeout),
        "residency": lambda: check_residency(args.with_eviction),
    }
    wanted = args.only.split(",") if args.only else list(steps)

    if not args.yes:
        print(json.dumps({"would_run": wanted, "vault": str(vault),
                          "note": "dry run: pass --yes to write to the vault"},
                         indent=2))
        return 0

    results = []
    for name in wanted:
        if name not in steps:
            results.append({"step": name, "pass": False, "why": "unknown step"})
            continue
        try:
            results.append(steps[name]())
        except Exception as exc:                       # noqa: BLE001
            results.append({"step": name, "pass": False, "why": repr(exc)})
        print(json.dumps(results[-1], ensure_ascii=False), file=sys.stderr)

    failed = [r for r in results if r.get("pass") is False]
    print(json.dumps({"results": results, "failed": len(failed)},
                     ensure_ascii=False, indent=2))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
