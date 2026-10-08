#!/usr/bin/env python3
"""Selection registry — the no-reuse rule (professor-expertise-finder).

In batch/allocation mode, a professor who is in the FINAL selection for
one keyword set (e.g. one funding application) must not be selected for
another set in the same batch — nobody should be asked to review two or
three applications. This script is the single source of truth:

    <data root>/batches/<batch-slug>/selections.csv

where <data root> is pef_common.data_root() (PROFESSOR_EXPERTISE_DATA, or
~/workspace/professor-expertise by default, R1).

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
  - `add --status final` is REJECTED (exit 1) if the professor is already
    final in a DIFFERENT application of the same batch.
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
import json
import sys
from datetime import date
from pathlib import Path

from pef_common import data_root, load_config, name_key, norm, slugify

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
    with path.open("w", newline="", encoding="utf-8") as fh:
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
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=HEADER)
        writer.writeheader()
        writer.writerows(rows)


def finals_for(rows: list[dict], key: tuple[str, ...]) -> list[dict]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Find every FINAL row for a given normalized professor-name key.

    Inputs:
        rows (list[dict]): the registry's rows.
        key (tuple[str, ...]): a name_key() result.

    Outputs:
        matches (list[dict]): the matching final rows.
    --------------------------------------------------------------------------
    """
    return [r for r in rows if r["status"] == "final"
            and name_key(r["professor"]) == key]


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
            if args.json_path:
                Path(args.json_path).write_text(json.dumps(
                    {"status": "taken", "professor": args.professor, "applications": apps}),
                    encoding="utf-8")
            return 1
        proposed = sorted({r["application"] for r in rows if r["status"] == "proposed"
                           and name_key(r["professor"]) == key})
        status = "available_proposed" if proposed else "available"
        if proposed:
            print(f"AVAILABLE (but proposed for: {', '.join(proposed)})")
        else:
            print("AVAILABLE")
        if args.json_path:
            Path(args.json_path).write_text(json.dumps(
                {"status": status, "professor": args.professor, "proposed_for": proposed}),
                encoding="utf-8")
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
               and norm(r["university"]) == norm(args.university)]
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
        try:
            max_per_university = load_config()["max_per_university"]
        except (FileNotFoundError, ValueError) as exc:
            print(f"INVALID: {exc}")
            return 1
        key = name_key(args.professor)
        # Conflict of interest: an evaluator may not evaluate an
        # application originating from their own university.
        origin = read_origins(args.batch).get(args.application, "")
        if origin and args.university and norm(origin) == norm(args.university):
            print(f"REJECTED: conflict of interest - {args.professor} is at "
                  f"{args.university}, the applicant university of "
                  f"{args.application}.")
            return 1
        finals = finals_for(rows, key)
        other_finals = [r for r in finals if r["application"] != args.application]
        if other_finals:
            apps = ", ".join(sorted({r["application"] for r in other_finals}))
            print(f"REJECTED: {args.professor} is already FINAL for {apps} "
                  f"in batch '{args.batch}' - no reuse across applications.")
            return 1
        # University cap: at most max_per_university professors from the
        # same university in the FINAL selection of one application.
        if args.status == "final" and args.university:
            same_uni = [r for r in rows
                        if r["status"] == "final"
                        and r["application"] == args.application
                        and name_key(r["professor"]) != key
                        and norm(r["university"]) == norm(args.university)]
            if len(same_uni) >= max_per_university:
                names = ", ".join(r["professor"] for r in same_uni)
                print(f"REJECTED: {args.application} already has {max_per_university} "
                      f"professors from {args.university} ({names}) - maximum "
                      f"{max_per_university} per university per application.")
                return 1
        if args.dry_run:
            print(f"DRY RUN - would add ({args.status}): {args.professor} -> {args.application}")
            return 0
        # idempotent within the same application: replace the existing row
        rows = [r for r in rows if not (name_key(r["professor"]) == key
                                        and r["application"] == args.application)]
        rows.append({"batch": args.batch, "application": args.application,
                     "keywords": args.keywords, "professor": args.professor,
                     "university": args.university, "score": args.score,
                     "status": args.status, "date": date.today().isoformat()})
        write_rows(path, rows)
        print(f"ADDED ({args.status}): {args.professor} -> {args.application}")
        if args.json_path:
            Path(args.json_path).write_text(json.dumps(
                {"status": "added", "professor": args.professor,
                 "application": args.application, "add_status": args.status}),
                encoding="utf-8")
        return 0

    if args.command == "list":
        finals = [r for r in rows if r["status"] == "final"]
        proposed = [r for r in rows if r["status"] == "proposed"]
        apps: dict[str, list[dict]] = {}
        for r in finals:
            apps.setdefault(r["application"], []).append(r)
        distinct = len({name_key(r["professor"]) for r in finals})
        print(f"BATCH: {args.batch} - {len(finals)} final, {len(proposed)} proposed, "
              f"{distinct} distinct professors")
        origins = read_origins(args.batch)
        for app in sorted(apps):
            origin = origins.get(app)
            suffix = f" [applicant university: {origin}]" if origin else ""
            print(f"\n{app} (keywords: {apps[app][0]['keywords']}){suffix}")
            for r in apps[app]:
                print(f"  - {r['professor']} ({r['university']}) {r['score']}")
        if args.json_path:
            Path(args.json_path).write_text(json.dumps({
                "batch": args.batch, "final_count": len(finals),
                "proposed_count": len(proposed), "distinct_professors": distinct,
                "applications": {app: [{"professor": r["professor"],
                                         "university": r["university"],
                                         "score": r["score"]} for r in rs]
                                 for app, rs in apps.items()},
            }, indent=2, ensure_ascii=False), encoding="utf-8")
        return 0

    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
