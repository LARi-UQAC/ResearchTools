#!/usr/bin/env python3
"""Apply a user-supplied exclusion list to a ranking CSV.

The exclusion file (Excel .xlsx or CSV) lists professors to remove, e.g.
because they are unavailable this year. Expected columns, any order, extra
columns ignored:
  - a name: `name` / `professor` / `nom`, or `first_name`+`last_name`
    (also `prenom`+`nom`, `given_name`+`family_name`)
  - optionally `university` / `universite`
  - optionally `reason` / `raison`

Matching is by normalized name (accent/case-insensitive, first/last
order-insensitive). University disambiguates a homonym: when BOTH the
exclusion entry and the ranking row carry a university and they do not
match, the pair is reported AMBIGUOUS rather than excluded - a name match
alone is not proof of identity once two different universities are on
record, and excluding the wrong "Jane Doe" would be silent. When either
side has no recorded university, the name match still excludes (an
exclusion is never lost over a spelling variant, or over a file that
never recorded an institution).

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
import sys
from collections import defaultdict
from pathlib import Path

from pef_common import (atomic_open, canonical_university, load_column_hints,
                         name_key, norm, write_json)

_HINTS = load_column_hints("exclusions")
NAME_COLS = _HINTS["name_cols"]
FIRST_COLS = _HINTS["first_cols"]
LAST_COLS = _HINTS["last_cols"]
UNI_COLS = _HINTS["uni_cols"]
REASON_COLS = _HINTS["reason_cols"]


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
        # col itself must be normalized before the lookup: norm() folds an
        # underscore to a space exactly like any other non-alphanumeric
        # run, so "first_name" (as literally written in FIRST_COLS) never
        # matched a normalized header key "first name" until this fixed it
        # (2026-10-08 code review - every first_name/last_name exclusion
        # file silently resolved to no name at all, and not even to an
        # "unmatched" entry, since row_name() returned "").
        ncol = norm(col)
        if ncol in lowered and str(lowered[ncol]).strip():
            return str(lowered[ncol]).strip()
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

        # Closed explicitly (2026-10-09 review finding): read_only still
        # opens a file handle Windows keeps locked until garbage collection.
        wb = load_workbook(path, read_only=True, data_only=True)
        try:
            rows = list(wb.active.iter_rows(values_only=True))
        finally:
            wb.close()
        if not rows:
            return []
        header = [str(c) if c is not None else "" for c in rows[0]]
        return [{header[i]: ("" if v is None else str(v))
                 for i, v in enumerate(r) if i < len(header)}
                for r in rows[1:] if any(v is not None for v in r)]
    with path.open(newline="", encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


def apply_exclusions(ranking: list[dict], exclusion_rows: list[dict]) -> tuple[list[dict], list[tuple[dict, dict]], list[dict], list[tuple[dict, dict]]]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Partition a ranking into kept and excluded rows against a parsed
        exclusion list, disambiguating a same-name match by university
        when both sides have recorded one, and report which exclusion
        entries matched nobody.

    Inputs:
        ranking (list[dict]): parsed ranking CSV rows; each must carry a
            "professor" field.
        exclusion_rows (list[dict]): parsed exclusion-file rows (raw, as
            read_rows returns them).

    Outputs:
        kept (list[dict]): ranking rows not matched by any exclusion
            (ambiguous pairs are also kept, pending a human decision).
        excluded (list[tuple[dict, dict]]): (ranking_row, exclusion_entry)
            pairs excluded with confidence.
        unmatched (list[dict]): exclusion entries that matched nobody.
        ambiguous (list[tuple[dict, dict]]): (ranking_row, exclusion_entry)
            pairs sharing a name but recording two different universities -
            never auto-excluded, since a name match alone is not proof of
            identity once the two universities disagree.
    --------------------------------------------------------------------------
    """
    exclusions = []
    for row in exclusion_rows:
        name = row_name(row)
        if name:
            exclusions.append({"name": name, "key": name_key(name),
                               "university": pick(row, UNI_COLS),
                               "reason": pick(row, REASON_COLS)})

    by_key: dict[tuple, list[int]] = defaultdict(list)
    for i, ex in enumerate(exclusions):
        by_key[ex["key"]].append(i)

    kept, excluded, ambiguous = [], [], []
    matched: set[int] = set()
    for row in ranking:
        key = name_key(row.get("professor", ""))
        candidates = by_key.get(key, [])
        row_uni = canonical_university(row.get("university", ""))
        outcome, chosen, consistent = _resolve_exclusion_match(row_uni, exclusions, candidates)
        if outcome == "exclude":
            # Every candidate judged CONSISTENT with this match - not only
            # the one `chosen` for the reported reason - is marked matched.
            # A duplicate or an empty-university sibling that agreed with
            # the chosen one is not a typo (fifth 2026-10-08 round: it was
            # wrongly reported as "UNMATCHED EXCLUSION (matched nobody)").
            matched.update(consistent)
            excluded.append((row, exclusions[chosen]))
        elif outcome == "ambiguous":
            matched.update(consistent)
            ambiguous.append((row, exclusions[consistent[0]]))
            # An ambiguous row is NOT excluded - it stays in the deliverable
            # pending a human decision, exactly as the module docstring and
            # the printed "(kept)" message already say (bug: it was only
            # appended to `ambiguous`, never to `kept`, so it silently
            # vanished from the written CSV - third 2026-10-08 code-review
            # round).
            kept.append(row)
        else:  # "no_match"
            kept.append(row)
    unmatched = [ex for i, ex in enumerate(exclusions) if i not in matched]
    return kept, excluded, unmatched, ambiguous


def _resolve_exclusion_match(row_uni: str, exclusions: list[dict],
                               candidates: list[int]
                               ) -> tuple[str, int | None, list[int]]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Decide what a ranking row's name match against the exclusion list
        means, when the exclusion file can itself carry more than one
        entry for the same normalized name (its own homonyms).

    Inputs:
        row_uni (str): the ranking row's university, already
            canonical_university()-ed ("" when unknown).
        exclusions (list[dict]): every parsed exclusion entry.
        candidates (list[int]): indices into `exclusions` sharing the
            ranking row's name key; [] when the name matched nobody.

    Outputs:
        outcome (str): "no_match" (the name matched no exclusion entry at
            all), "exclude" (exactly one candidate identified with
            confidence), or "ambiguous" (the name matches, but which
            recorded person it is - or whether it is any of them - cannot
            be told apart from the data available; never auto-excluded).
        index (int | None): the chosen exclusions[] index when outcome is
            "exclude", else None.
        consistent (list[int]): every candidate judged consistent with
            this outcome - for "exclude", every plausible candidate, not
            only the one `chosen` for the reported reason (a duplicate or
            empty-university sibling agreeing with the chosen one is not
            a typo, fifth 2026-10-08 round); for "ambiguous", the full
            `candidates`; empty for "no_match".

    Details:
        A KNOWN disagreement is never read as "confidently not a match":
        once a name matches at all, "every candidate disagrees with the
        row's own university" is ambiguous, not a silent "this must be
        someone else" (single candidate, both universities known and
        disagreeing -> ambiguous, the original round-1 case).

        Among the candidates still PLAUSIBLE given what is known, the
        exclude/ambiguous split is decided by whether they agree with
        EACH OTHER, not by how many of them there are - fixed 2026-10-08,
        third code-review round, after the original `len(matches) == 1`
        rule flagged two IDENTICAL duplicate exclusion-file rows (a
        plausible export glitch, no actual disagreement) as ambiguous
        merely for having two indices, silently dropping a professor who
        should have been cleanly excluded (combined with the companion
        fix above). Zero distinct non-empty universities among the
        plausible candidates, or exactly one, is still a confident
        exclude; two or more distinct ones is the real ambiguity - the
        exclusion file itself lists two different real people under this
        name, and nothing here can tell which one the ranking row is.
    --------------------------------------------------------------------------
    """
    if not candidates:
        return "no_match", None, []
    # canonical_university(), not norm(): a UQAC entry and a Universite du
    # Quebec a Chicoutimi row must agree here, or this exact-matching gap
    # reopens the one selections.py's canonicalization round already
    # closed elsewhere (2026-10-09 review, round 6).
    known = [(i, canonical_university(exclusions[i]["university"])) for i in candidates]
    if row_uni:
        # A candidate with no recorded university is still POSSIBLY this
        # row (missing data, not a mismatch); one with a DIFFERENT known
        # university is ruled out.
        plausible = [i for i, u in known if not u or u == row_uni]
    else:
        plausible = candidates
    if not plausible:
        return "ambiguous", None, candidates
    distinct_unis = {u for i, u in known if i in plausible and u}
    if len(distinct_unis) <= 1:
        chosen = next((i for i in plausible if canonical_university(exclusions[i]["university"])),
                       plausible[0])
        return "exclude", chosen, plausible
    return "ambiguous", None, candidates


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
    # utf-8-sig, same as read_rows() below: a BOM-prefixed export (Excel's
    # "CSV UTF-8", or a PowerShell redirect) would otherwise key the first
    # column as "﻿professor" instead of "professor" (2026-10-08,
    # fourth code-review round).
    with ranking_path.open(newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        fieldnames = reader.fieldnames or []
        ranking = list(reader)
    if "professor" not in fieldnames:
        print("INVALID: ranking CSV has no 'professor' column")
        return 1

    kept, excluded, unmatched, ambiguous = apply_exclusions(ranking, read_rows(excl_path))

    if args.dry_run:
        print(f"DRY RUN - KEPT: {len(kept)}  EXCLUDED: {len(excluded)}  (would write {out_path})")
    else:
        with atomic_open(out_path, newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(kept)
        print(f"KEPT: {len(kept)}  EXCLUDED: {len(excluded)}  -> {out_path}")

    for row, ex in excluded:
        reason = ex["reason"] or "raison non précisée"
        print(f"  EXCLUDED: {row.get('professor')} ({row.get('university', '')}) - {reason}")
    for row, ex in ambiguous:
        print(f"  AMBIGUOUS (kept): {row.get('professor')} - ranking says "
              f"{row.get('university', '')}, exclusion file says {ex['university']} - verify by hand")
    for ex in unmatched:
        print(f"  UNMATCHED EXCLUSION (matched nobody): {ex['name']}")

    write_json(args.json_path, {
        "kept_count": len(kept), "excluded_count": len(excluded),
        "excluded": [{"professor": row.get("professor"), "reason": ex["reason"]}
                     for row, ex in excluded],
        "ambiguous": [{"professor": row.get("professor"),
                       "ranking_university": row.get("university", ""),
                       "exclusion_university": ex["university"]}
                      for row, ex in ambiguous],
        "unmatched": [ex["name"] for ex in unmatched],
        "dry_run": args.dry_run, "out": str(out_path),
    })
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
