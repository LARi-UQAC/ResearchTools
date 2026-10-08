#!/usr/bin/env python3
"""Department-table instances for the professor-expertise-finder skill.

Location-agnostic: the location string given by the user (e.g. "Canada",
"Canada, Ontario", "France, Île-de-France", "Worldwide") is turned into a
slug, and the table for that location lives at:

    <data root>/<slug>/departments.csv

where <data root> is the PROFESSOR_EXPERTISE_DATA environment variable,
or pef_config.json's default_data_root when unset (pef_common.data_root,
R1 - the default lives in that config file, never as a literal here).

Commands:
    path      print the CSV path for a location
    check     report whether the table exists, is valid, and its row count
    init      create an empty table (header only) if missing; never overwrite
    validate  check header, required fields and duplicate rows

Usage:
    python3 table.py check --location "Canada, Ontario"
    python3 table.py init  --location "Canada, Ontario" --dry-run
    python3 table.py check --location "Canada, Ontario" --json report.json
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

from pef_common import data_root, slugify, write_json

HEADER = ["university", "department", "department_url", "faculty_list_url", "note"]


def csv_path(location: str) -> Path:
    """
    --------------------------------------------------------------------------
    Purpose:
        Resolve the department-table CSV path for one search location.

    Inputs:
        location (str): free-text location, e.g. "Canada, Ontario".

    Outputs:
        path (Path): <data root>/<slugified location>/departments.csv.
    --------------------------------------------------------------------------
    """
    return data_root() / slugify(location) / "departments.csv"


def read_rows(path: Path) -> list[dict]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Read every row of an existing department table.

    Inputs:
        path (Path): a departments.csv that exists.

    Outputs:
        rows (list[dict]): one dict per data row, keyed by HEADER.

    Raises:
        ValueError: the file's header does not match HEADER exactly.
    --------------------------------------------------------------------------
    """
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        if reader.fieldnames != HEADER:
            raise ValueError(f"bad header: {reader.fieldnames!r} (expected {HEADER!r})")
        return list(reader)


def validate(path: Path) -> list[str]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Check a department table for a correct header, non-empty required
        fields, duplicate (university, department) rows, and well-formed
        URLs.

    Inputs:
        path (Path): a departments.csv that exists.

    Outputs:
        problems (list[str]): one line per issue found; empty when valid.
    --------------------------------------------------------------------------
    """
    return _validate_with_rows(path)[0]


def _validate_with_rows(path: Path) -> tuple[list[str], list[dict]]:
    """
    --------------------------------------------------------------------------
    Purpose:
        validate()'s own implementation, additionally returning the parsed
        rows so a caller needing both (check/validate's CLI handlers) reads
        the file once instead of calling read_rows() a second time.

    Inputs:
        path (Path): a departments.csv that exists.

    Outputs:
        problems (list[str]): one line per issue found; empty when valid.
        rows (list[dict]): the parsed rows, or [] on a header/parse error.
    --------------------------------------------------------------------------
    """
    problems: list[str] = []
    try:
        rows = read_rows(path)
    except Exception as exc:  # header / parse error
        return [str(exc)], []
    seen: set[tuple[str, str]] = set()
    for i, row in enumerate(rows, start=2):
        if not (row.get("university") or "").strip():
            problems.append(f"line {i}: empty university")
        if not (row.get("department") or "").strip():
            problems.append(f"line {i}: empty department")
        key = ((row.get("university") or "").strip().lower(),
               (row.get("department") or "").strip().lower())
        if key in seen:
            problems.append(f"line {i}: duplicate row {key}")
        seen.add(key)
        for col in ("department_url", "faculty_list_url"):
            url = (row.get(col) or "").strip()
            if url and not url.startswith(("http://", "https://")):
                problems.append(f"line {i}: {col} is not an http(s) URL: {url!r}")
    return problems, rows


def main(argv: list[str]) -> int:
    """
    --------------------------------------------------------------------------
    Purpose:
        CLI entry point: path / check / init / validate.

    Inputs:
        argv (list[str]): command-line arguments, excluding the program name.

    Outputs:
        exit_code (int): 0 on success, 1 on a reported problem, 2 on an
            unrecognized command.
    --------------------------------------------------------------------------
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["path", "check", "init", "validate"])
    parser.add_argument("--location", required=True,
                        help='e.g. "Canada", "Canada, Ontario", "Worldwide"')
    parser.add_argument("--dry-run", action="store_true",
                        help="init: report what would be created, create nothing")
    parser.add_argument("--json", dest="json_path", default=None,
                        help="also write a machine-readable report to this path")
    args = parser.parse_args(argv)

    path = csv_path(args.location)

    if args.command == "path":
        print(path)
        return 0

    if args.command == "init":
        if path.exists():
            print(f"EXISTS (unchanged): {path}")
            write_json(args.json_path, {"command": "init", "path": str(path),
                                         "created": False, "dry_run": args.dry_run})
            return 0
        if args.dry_run:
            print(f"DRY RUN - would create: {path}")
            write_json(args.json_path, {"command": "init", "path": str(path),
                                         "created": False, "dry_run": True})
            return 0
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="", encoding="utf-8") as fh:
            csv.writer(fh).writerow(HEADER)
        print(f"CREATED: {path}")
        write_json(args.json_path, {"command": "init", "path": str(path),
                                     "created": True, "dry_run": False})
        return 0

    if not path.exists():
        print(f"MISSING: {path}")
        write_json(args.json_path, {"command": args.command, "path": str(path),
                                     "status": "missing"})
        return 1

    if args.command in ("check", "validate"):
        # check and validate report the same thing (header, required fields,
        # duplicates, URL shape); they differ only in their status label -
        # "ok"/"OK" vs "valid"/"VALID" - so one body serves both rather than
        # two near-identical blocks drifting apart (2026-10-08 code review).
        ok_word = "ok" if args.command == "check" else "valid"
        problems, rows = _validate_with_rows(path)
        if problems:
            print(f"INVALID: {path}")
            for p in problems:
                print(f"  - {p}")
            write_json(args.json_path, {"command": args.command, "path": str(path),
                                         "status": "invalid", "problems": problems})
            return 1
        print(f"{ok_word.upper()}: {path} ({len(rows)} rows)")
        write_json(args.json_path, {"command": args.command, "path": str(path),
                                     "status": ok_word, "row_count": len(rows)})
        return 0

    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
