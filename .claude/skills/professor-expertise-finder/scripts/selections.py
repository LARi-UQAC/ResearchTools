#!/usr/bin/env python3
"""Selection registry — the no-reuse rule (professor-expertise-finder).

In batch/allocation mode, a professor who is in the FINAL selection for
one keyword set (e.g. one funding application) must not be selected for
another set in the same batch — nobody should be asked to review two or
three applications. This script is the single source of truth:

    <data root>/batches/<batch-slug>/selections.csv

where <data root> is pef_common.data_root() (PROFESSOR_EXPERTISE_DATA, or
pef_config.json's default_data_root when unset, R1).

Commands:
    init   --batch "concours-2027"                 create registry if missing
    add    --batch B --application D1 --professor "Jane Doe" \
           --university U --keywords "..." --score "4.5/5" --status final
    check  --batch B --professor "Jane Doe"        AVAILABLE or TAKEN (by whom)
    origin --batch B --application D1 --university U
                                                   declare the applicant
                                                   university of an application
                                                   (conflict of interest);
                                                   without --university,
                                                   just display it
    list   --batch B                               final choices per application

Rules enforced here, not in prose:
  - `add` REQUIRES --university, whatever the status: a `proposed` add
    needs it to disambiguate a same-named evaluator in the no-reuse check
    below, and a `final` add additionally needs it to enforce the
    per-university cap and conflict-of-interest - omitting it is refused
    rather than silently skipping any of the three.
  - `add --status final` is REJECTED (exit 1) if the professor is already
    final in a DIFFERENT application of the same batch - disambiguated by
    university, so a different person sharing a name is not blocked by
    someone else's registration elsewhere.
  - A `proposed` entry for a professor already final elsewhere is also
    rejected; `proposed` entries do not block, but `check` reports them.
  - Matching is by normalized name (accent/case-insensitive,
    first/last order-insensitive).
  - All evaluators of one application must come from distinct
    universities: at most pef_config.json's max_per_university (currently
    1) professors from the same university in the FINAL selection of one
    application (`add` rejects a second one from a university already
    used there).
  - Conflict of interest: once an application's applicant university
    is declared (`origin`), `add` rejects any professor from that
    university for that application; declaring an origin also
    retro-audits the professors already registered for it.

`--dry-run` on init/add/origin reports what would change and writes
nothing. `--json <path>` on add/check/list additionally writes a
machine-readable report.
"""
from __future__ import annotations

import argparse
import csv
import sys
from datetime import date
from pathlib import Path

from pef_common import (atomic_open, canonical_university, data_root, load_config,
                         name_key, slugify, write_json)

HEADER = ["batch", "application", "keywords", "professor", "university",
          "score", "status", "date"]
APP_HEADER = ["application", "origin_university"]


def registry_path(batch: str) -> Path:
    """
    --------------------------------------------------------------------------
    Purpose:
        Resolve the selections.csv path for one batch.

    Inputs:
        batch (str): free-text batch identifier, e.g. "Concours 2027".

    Outputs:
        path (Path): <data root>/batches/<slugified batch>/selections.csv.
    --------------------------------------------------------------------------
    """
    return data_root() / "batches" / slugify(batch) / "selections.csv"


def apps_path(batch: str) -> Path:
    """
    --------------------------------------------------------------------------
    Purpose:
        Resolve the applications.csv (origin-university declarations) path
        for one batch, beside its selections.csv.

    Inputs:
        batch (str): free-text batch identifier.

    Outputs:
        path (Path): registry_path(batch) with the filename replaced.
    --------------------------------------------------------------------------
    """
    return registry_path(batch).with_name("applications.csv")


def read_origins(batch: str) -> dict[str, str]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Read the declared applicant university per application, for one
        batch.

    Inputs:
        batch (str): free-text batch identifier.

    Outputs:
        origins (dict[str, str]): application -> origin_university; {}
            when applications.csv does not exist yet.
    --------------------------------------------------------------------------
    """
    path = apps_path(batch)
    if not path.exists():
        return {}
    with path.open(newline="", encoding="utf-8") as fh:
        return {r["application"]: r["origin_university"]
                for r in csv.DictReader(fh)}


def write_origins(batch: str, origins: dict[str, str]) -> None:
    """
    --------------------------------------------------------------------------
    Purpose:
        Persist the declared applicant universities for one batch.

    Inputs:
        batch (str): free-text batch identifier.
        origins (dict[str, str]): application -> origin_university, the
            full set to write (not a delta).

    Outputs:
        None. Overwrites applications.csv.
    --------------------------------------------------------------------------
    """
    path = apps_path(batch)
    path.parent.mkdir(parents=True, exist_ok=True)
    with atomic_open(path, newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=APP_HEADER)
        writer.writeheader()
        for app, uni in sorted(origins.items()):
            writer.writerow({"application": app, "origin_university": uni})


def read_rows(path: Path) -> list[dict]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Read a batch's selections.csv.

    Inputs:
        path (Path): the registry path; may not exist yet.

    Outputs:
        rows (list[dict]): one dict per row, keyed by HEADER; [] when the
            file does not exist.

    Raises:
        ValueError: the file exists but its header does not match HEADER.
    --------------------------------------------------------------------------
    """
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        if reader.fieldnames != HEADER:
            raise ValueError(f"bad header in {path}: {reader.fieldnames!r}")
        return list(reader)


def write_rows(path: Path, rows: list[dict]) -> None:
    """
    --------------------------------------------------------------------------
    Purpose:
        Overwrite a batch's selections.csv with the given rows.

    Inputs:
        path (Path): the registry path.
        rows (list[dict]): the full row set to write.

    Outputs:
        None.
    --------------------------------------------------------------------------
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with atomic_open(path, newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=HEADER)
        writer.writeheader()
        writer.writerows(rows)


def _same_person(recorded_university: str, candidate_university: str) -> bool:
    """
    --------------------------------------------------------------------------
    Purpose:
        Decide whether a name match found in the registry is plausibly the
        SAME person as a candidate being added, using university as a
        disambiguator for homonyms (2026-10-08 code review finding: two
        different real people can share a name, and matching on name alone
        wrongly blocked a legitimate second "John Smith" at a different
        university).

    Inputs:
        recorded_university (str): the registry row's university field.
        candidate_university (str): the university being checked against.

    Outputs:
        same (bool): False only when BOTH sides name a university and they
            differ after CANONICALIZATION (2026-10-09 review finding:
            exact-string equality let a spelling variant like "UQAC" vs
            "Université du Québec à Chicoutimi" silently bypass this check -
            see pef_common.canonical_university()); True whenever either
            side is unknown (errs toward treating a name match as the same
            person when there is not enough information to tell them apart,
            which keeps the no-reuse rule's existing protection intact).
    --------------------------------------------------------------------------
    """
    a, b = canonical_university(recorded_university), canonical_university(candidate_university)
    return not (a and b and a != b)


def finals_for(rows: list[dict], key: tuple[str, ...],
                university: str | None = None) -> list[dict]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Find every FINAL row for a given normalized professor-name key,
        optionally disambiguated by university.

    Inputs:
        rows (list[dict]): the registry's rows.
        key (tuple[str, ...]): a name_key() result.
        university (str | None): when given, a row whose own university
            disagrees with it (both sides known, both non-empty) is
            excluded from the match - see _same_person(). None keeps the
            name-only behaviour used by `check`, which has no university
            of its own to disambiguate with.

    Outputs:
        matches (list[dict]): the matching final rows.
    --------------------------------------------------------------------------
    """
    return [r for r in rows if r["status"] == "final"
            and name_key(r["professor"]) == key
            and (university is None or _same_person(r["university"], university))]


def main(argv: list[str]) -> int:
    """
    --------------------------------------------------------------------------
    Purpose:
        CLI entry point: path / init / add / check / origin / list.

    Inputs:
        argv (list[str]): command-line arguments, excluding the program name.

    Outputs:
        exit_code (int): 0 on success or an informational result
            (AVAILABLE, no conflict), 1 on a rejection or missing input,
            2 on an unrecognized command.
    --------------------------------------------------------------------------
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["path", "init", "add", "check",
                                            "origin", "list"])
    parser.add_argument("--batch", required=True)
    parser.add_argument("--application", default="")
    parser.add_argument("--keywords", default="")
    parser.add_argument("--professor", default="")
    parser.add_argument("--university", default="")
    parser.add_argument("--score", default="")
    parser.add_argument("--status", choices=["proposed", "final"], default="final")
    parser.add_argument("--dry-run", action="store_true",
                        help="init/add/origin: report what would change, write nothing")
    parser.add_argument("--json", dest="json_path", default=None,
                        help="add/check/list: also write a machine-readable report")
    args = parser.parse_args(argv)

    path = registry_path(args.batch)

    if args.command == "path":
        print(path)
        return 0

    if args.command == "init":
        if path.exists():
            print(f"EXISTS (unchanged): {path} ({len(read_rows(path))} rows)")
            return 0
        if args.dry_run:
            print(f"DRY RUN - would create: {path}")
            return 0
        write_rows(path, [])
        print(f"CREATED: {path}")
        return 0

    rows = read_rows(path)
    if not path.exists():
        print(f"MISSING registry: {path} (run init first)")
        return 1

    if args.command == "check":
        if not args.professor:
            print("INVALID: --professor required")
            return 1
        key = name_key(args.professor)
        finals = finals_for(rows, key)
        if finals:
            apps = sorted({r["application"] for r in finals})
            print(f"TAKEN: {args.professor} is already FINAL for: {', '.join(apps)}")
            write_json(args.json_path,
                       {"status": "taken", "professor": args.professor, "applications": apps})
            return 1
        proposed = sorted({r["application"] for r in rows if r["status"] == "proposed"
                           and name_key(r["professor"]) == key})
        status = "available_proposed" if proposed else "available"
        if proposed:
            print(f"AVAILABLE (but proposed for: {', '.join(proposed)})")
        else:
            print("AVAILABLE")
        write_json(args.json_path,
                   {"status": status, "professor": args.professor, "proposed_for": proposed})
        return 0

    if args.command == "origin":
        if not args.application:
            print("INVALID: --application is required")
            return 1
        origins = read_origins(args.batch)
        if not args.university:
            origin = origins.get(args.application)
            if origin:
                print(f"{args.application}: applicant university = {origin}")
            else:
                print(f"{args.application}: no applicant university declared")
            return 0
        if args.dry_run:
            print(f"DRY RUN - would set: {args.application} -> {args.university}")
            return 0
        origins[args.application] = args.university
        write_origins(args.batch, origins)
        print(f"ORIGIN SET: {args.application} -> {args.university}")
        bad = [r for r in rows
               if r["application"] == args.application and r["university"]
               and canonical_university(r["university"]) == canonical_university(args.university)]
        for r in bad:
            print(f"CONFLICT: {r['professor']} ({r['status']}) is at the "
                  f"applicant university of {args.application}.")
        if not bad:
            print("No registered professor in conflict for this application.")
        return 0

    if args.command == "add":
        if not args.professor or not args.application:
            print("INVALID: --professor and --application are required")
            return 1
        if not args.university:
            # Required for EVERY add, not just final (third 2026-10-08
            # code-review round): a proposed add with no university made
            # finals_for()'s university disambiguation see an "unknown"
            # value, which _same_person() treats as a possible match -
            # so a different person sharing a name with an already-final
            # evaluator was wrongly rejected as reuse. A final add without
            # one also cannot enforce the university cap or
            # conflict-of-interest (the original, first-round finding).
            print("INVALID: --university is required for add "
                  "(needed to disambiguate a same-named evaluator, and, for "
                  "a final add, to enforce the university cap and conflict of interest)")
            return 1
        try:
            max_per_university = load_config()["max_per_university"]
        except (FileNotFoundError, ValueError) as exc:
            print(f"INVALID: {exc}")
            return 1
        key = name_key(args.professor)
        # Conflict of interest: an evaluator may not evaluate an
        # application originating from their own university.
        origin = read_origins(args.batch).get(args.application, "")
        if origin and args.university and canonical_university(origin) == canonical_university(args.university):
            print(f"REJECTED: conflict of interest - {args.professor} is at "
                  f"{args.university}, the applicant university of "
                  f"{args.application}.")
            return 1
        # No-reuse, disambiguated by university so a different person who
        # happens to share a name is not blocked by someone else's FINAL
        # registration elsewhere (2026-10-08 code review).
        finals = finals_for(rows, key, university=args.university)
        other_finals = [r for r in finals if r["application"] != args.application]
        if other_finals:
            apps = ", ".join(sorted({r["application"] for r in other_finals}))
            print(f"REJECTED: {args.professor} is already FINAL for {apps} "
                  f"in batch '{args.batch}' - no reuse across applications.")
            return 1
        # University cap: at most max_per_university professors from the
        # same university in the FINAL selection of one application.
        if args.status == "final":
            same_uni = [r for r in rows
                        if r["status"] == "final"
                        and r["application"] == args.application
                        and name_key(r["professor"]) != key
                        and canonical_university(r["university"]) == canonical_university(args.university)]
            if len(same_uni) >= max_per_university:
                names = ", ".join(r["professor"] for r in same_uni)
                print(f"REJECTED: {args.application} already has {max_per_university} "
                      f"professors from {args.university} ({names}) - maximum "
                      f"{max_per_university} per university per application.")
                return 1
        if args.dry_run:
            print(f"DRY RUN - would add ({args.status}): {args.professor} -> {args.application}")
            return 0
        # Idempotent within the same application: replace the existing row
        # for the SAME person only. Matching by name_key + application
        # alone (dropped 2026-10-08, second code-review round) would have
        # deleted a different homonym's own registration on the same
        # application - exactly the protection _same_person() exists to
        # give, bypassed at the one place that actually writes the file.
        rows = [r for r in rows if not (name_key(r["professor"]) == key
                                        and r["application"] == args.application
                                        and _same_person(r["university"], args.university))]
        rows.append({"batch": args.batch, "application": args.application,
                     "keywords": args.keywords, "professor": args.professor,
                     "university": args.university, "score": args.score,
                     "status": args.status, "date": date.today().isoformat()})
        write_rows(path, rows)
        print(f"ADDED ({args.status}): {args.professor} -> {args.application}")
        write_json(args.json_path,
                   {"status": "added", "professor": args.professor,
                    "application": args.application, "add_status": args.status})
        return 0

    if args.command == "list":
        finals = [r for r in rows if r["status"] == "final"]
        proposed = [r for r in rows if r["status"] == "proposed"]
        apps: dict[str, list[dict]] = {}
        for r in finals:
            apps.setdefault(r["application"], []).append(r)
        # Keyed on (name, university), not name alone: two different
        # people sharing a name (the same homonym case _same_person()
        # disambiguates elsewhere in this file) must count as two, not
        # collapse into one distinct professor.
        distinct = len({(name_key(r["professor"]), canonical_university(r["university"]))
                        for r in finals})
        print(f"BATCH: {args.batch} - {len(finals)} final, {len(proposed)} proposed, "
              f"{distinct} distinct professors")
        origins = read_origins(args.batch)
        for app in sorted(apps):
            origin = origins.get(app)
            suffix = f" [applicant university: {origin}]" if origin else ""
            print(f"\n{app} (keywords: {apps[app][0]['keywords']}){suffix}")
            for r in apps[app]:
                print(f"  - {r['professor']} ({r['university']}) {r['score']}")
        write_json(args.json_path, {
            "batch": args.batch, "final_count": len(finals),
            "proposed_count": len(proposed), "distinct_professors": distinct,
            "applications": {app: [{"professor": r["professor"],
                                     "university": r["university"],
                                     "score": r["score"]} for r in rs]
                             for app, rs in apps.items()},
        })
        return 0

    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
