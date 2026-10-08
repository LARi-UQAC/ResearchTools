#!/usr/bin/env python3
"""Apply a user-supplied exclusion list to a ranking CSV.

The exclusion file (Excel .xlsx or CSV) lists professors to remove, e.g.
because they are unavailable this year. Expected columns, any order, extra
columns ignored:
  - a name: `name` / `professor` / `nom`, or `first_name`+`last_name`
    (also `prenom`+`nom`, `given_name`+`family_name`)
  - optionally `university` / `universite`
  - optionally `reason` / `raison`

Matching is by normalized name only (accent/case-insensitive,
first/last order-insensitive); university is reported, not used to block
a match, so an exclusion is never lost over a spelling variant.

Usage:
  python3 exclusions.py --ranking ranking.csv --exclusions list.xlsx --out filtered.csv
  python3 exclusions.py --ranking r.csv --exclusions l.csv --out f.csv --dry-run
  python3 exclusions.py --ranking r.csv --exclusions l.csv --out f.csv --json report.json

Prints the excluded professors (with reason), and any exclusion entry
that matched nobody (so typos surface instead of doing nothing).
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

from pef_common import name_key, norm

NAME_COLS = ["name", "professor", "nom", "full_name", "professeur"]
FIRST_COLS = ["first_name", "prenom", "given_name", "first"]
LAST_COLS = ["last_name", "family_name", "last", "surname"]
UNI_COLS = ["university", "universite", "institution", "etablissement"]
REASON_COLS = ["reason", "raison", "motif", "note"]


def pick(row: dict, cols: list[str]) -> str:
    """
    --------------------------------------------------------------------------
    Purpose:
        Read the first non-empty value among a set of candidate column
        names, matched case/accent-insensitively.

    Inputs:
        row (dict): one parsed row, keyed by its original header text.
        cols (list[str]): candidate column names, in priority order.

    Outputs:
        value (str): the first non-empty match, or "" if none.
    --------------------------------------------------------------------------
    """
    lowered = {norm(k): v for k, v in row.items() if k}
    for col in cols:
        if col in lowered and str(lowered[col]).strip():
            return str(lowered[col]).strip()
    return ""


def row_name(row: dict) -> str:
    """
    --------------------------------------------------------------------------
    Purpose:
        Resolve a row's professor name, from a single name column or from
        separate first/last columns.

    Inputs:
        row (dict): one parsed exclusion-file row.

    Outputs:
        name (str): the resolved full name, or "" if none of the expected
            columns carried a value.
    --------------------------------------------------------------------------
    """
    direct = pick(row, NAME_COLS)
    if direct:
        return direct
    first, last = pick(row, FIRST_COLS), pick(row, LAST_COLS)
    return f"{first} {last}".strip()


def read_rows(path: Path) -> list[dict]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Read an exclusion file's rows, from either Excel or CSV.

    Inputs:
        path (Path): a .xlsx/.xlsm or .csv file.

    Outputs:
        rows (list[dict]): one dict per row, keyed by the file's own header
            text (not normalized here - callers use `pick`/`norm`).
    --------------------------------------------------------------------------
    """
    if path.suffix.lower() in (".xlsx", ".xlsm"):
        from openpyxl import load_workbook

        ws = load_workbook(path, read_only=True, data_only=True).active
        rows = list(ws.iter_rows(values_only=True))
        if not rows:
            return []
        header = [str(c) if c is not None else "" for c in rows[0]]
        return [{header[i]: ("" if v is None else str(v))
                 for i, v in enumerate(r) if i < len(header)}
                for r in rows[1:] if any(v is not None for v in r)]
    with path.open(newline="", encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


def apply_exclusions(ranking: list[dict], exclusion_rows: list[dict]) -> tuple[list[dict], list[tuple[dict, dict]], list[dict]]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Partition a ranking into kept and excluded rows against a parsed
        exclusion list, and report which exclusion entries matched nobody.

    Inputs:
        ranking (list[dict]): parsed ranking CSV rows; each must carry a
            "professor" field.
        exclusion_rows (list[dict]): parsed exclusion-file rows (raw, as
            read_rows returns them).

    Outputs:
        kept (list[dict]): ranking rows not matched by any exclusion.
        excluded (list[tuple[dict, dict]]): (ranking_row, exclusion_entry)
            pairs for each match.
        unmatched (list[dict]): exclusion entries that matched nobody.
    --------------------------------------------------------------------------
    """
    exclusions = []
    for row in exclusion_rows:
        name = row_name(row)
        if name:
            exclusions.append({"name": name, "key": name_key(name),
                               "university": pick(row, UNI_COLS),
                               "reason": pick(row, REASON_COLS)})

    kept, excluded = [], []
    matched: set[int] = set()
    for row in ranking:
        key = name_key(row.get("professor", ""))
        hit = next((i for i, ex in enumerate(exclusions) if ex["key"] == key), None)
        if hit is None:
            kept.append(row)
        else:
            matched.add(hit)
            excluded.append((row, exclusions[hit]))
    unmatched = [ex for i, ex in enumerate(exclusions) if i not in matched]
    return kept, excluded, unmatched


def main(argv: list[str]) -> int:
    """
    --------------------------------------------------------------------------
    Purpose:
        CLI entry point: read a ranking and an exclusion file, apply the
        exclusions, and write the filtered ranking (unless --dry-run).

    Inputs:
        argv (list[str]): command-line arguments, excluding the program name.

    Outputs:
        exit_code (int): 0 on success, 1 if the ranking CSV has no
            "professor" column.
    --------------------------------------------------------------------------
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ranking", required=True)
    parser.add_argument("--exclusions", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--dry-run", action="store_true",
                        help="report what would be kept/excluded, write nothing")
    parser.add_argument("--json", dest="json_path", default=None,
                        help="also write a machine-readable report to this path")
    args = parser.parse_args(argv)

    ranking_path, excl_path, out_path = (Path(args.ranking),
                                         Path(args.exclusions), Path(args.out))
    with ranking_path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        fieldnames = reader.fieldnames or []
        ranking = list(reader)
    if "professor" not in fieldnames:
        print("INVALID: ranking CSV has no 'professor' column")
        return 1

    kept, excluded, unmatched = apply_exclusions(ranking, read_rows(excl_path))

    if args.dry_run:
        print(f"DRY RUN - KEPT: {len(kept)}  EXCLUDED: {len(excluded)}  (would write {out_path})")
    else:
        with out_path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(kept)
        print(f"KEPT: {len(kept)}  EXCLUDED: {len(excluded)}  -> {out_path}")

    for row, ex in excluded:
        reason = ex["reason"] or "raison non précisée"
        print(f"  EXCLUDED: {row.get('professor')} ({row.get('university', '')}) - {reason}")
    for ex in unmatched:
        print(f"  UNMATCHED EXCLUSION (matched nobody): {ex['name']}")

    if args.json_path:
        Path(args.json_path).write_text(json.dumps({
            "kept_count": len(kept), "excluded_count": len(excluded),
            "excluded": [{"professor": row.get("professor"), "reason": ex["reason"]}
                         for row, ex in excluded],
            "unmatched": [ex["name"] for ex in unmatched],
            "dry_run": args.dry_run, "out": str(out_path),
        }, indent=2, ensure_ascii=False), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
