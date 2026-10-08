#!/usr/bin/env python3
"""Search a reference list FIRST for keyword matches (professor-expertise-finder).

The optional reference file (Excel or CSV, e.g. a national reviewers list)
is expected to carry, in any layout the parser can find:
  - a reviewer/professor name column ("External Reviewer Name", "Name",
    "Nom", "Professor", ...)
  - institution and department columns
  - an "Areas of Expertise / Domaines de compétence" column
  - optionally language-capability columns (Read/Write/Speak English /
    French, marked X) and an availability column ("Not available this
    year / Non disponible cette année")

The header row is located by searching for a name-like header cell, so
title/blank rows above the real header (common in such exports) are fine.

Usage:
  python3 file_search.py --file reviewers.xlsx --terms terms.txt --out matches.csv
  python3 file_search.py --file reviewers.xlsx --terms "computer vision, surface inspection"
  python3 file_search.py --file reviewers.xlsx --terms terms.txt --out matches.csv --dry-run

Output CSV columns: name, institution, department, areas_of_expertise,
matched_terms, match_count, languages_declared, availability.
Sorted by match_count descending. This is a shortlist for the web phase,
not a result: affiliation, email, articles and the /5 score are always
established on the web afterwards.
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path

from pef_common import norm

NAME_HINTS = ["external reviewer name", "reviewer name", "nom d", "name", "nom", "professor", "professeur"]
EXPERTISE_HINTS = ["areas of expertise", "domaines de competence", "expertise", "competence"]
INSTITUTION_HINTS = ["institution", "etablissement", "university", "universite"]
DEPARTMENT_HINTS = ["department", "departement"]
AVAILABILITY_HINTS = ["availability", "disponibilite"]
NOT_AVAILABLE = "not available"

OUTPUT_FIELDS = ["name", "institution", "department", "areas_of_expertise",
                  "matched_terms", "match_count", "languages_declared",
                  "availability"]


def read_grid(path: Path) -> list[list[str]]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Read a reference file into a plain string grid, from either Excel
        or CSV.

    Inputs:
        path (Path): a .xlsx/.xlsm or .csv file.

    Outputs:
        grid (list[list[str]]): one list of cell strings per row.
    --------------------------------------------------------------------------
    """
    if path.suffix.lower() in (".xlsx", ".xlsm"):
        from openpyxl import load_workbook

        ws = load_workbook(path, read_only=True, data_only=True).active
        return [["" if c is None else str(c) for c in row]
                for row in ws.iter_rows(values_only=True)]
    with path.open(newline="", encoding="utf-8-sig") as fh:
        return [list(r) for r in csv.reader(fh)]


def find_header(grid: list[list[str]]) -> int:
    """
    --------------------------------------------------------------------------
    Purpose:
        Locate the header row among possible title/blank rows above it.

    Inputs:
        grid (list[list[str]]): the file's rows, as read by read_grid.

    Outputs:
        index (int): the 0-based row index of the header.

    Raises:
        ValueError: no row carries both a name-like and an expertise-like
            header cell.
    --------------------------------------------------------------------------
    """
    for i, row in enumerate(grid):
        cells = [norm(c) for c in row]
        if any(any(h in cell for h in NAME_HINTS) and "reviewer" in cell or
               cell.startswith("external reviewer") for cell in cells):
            return i
        if any("areas of expertise" in cell or "domaines de competence" in cell
               for cell in cells) and any("name" in cell or "nom" in cell for cell in cells):
            return i
    raise ValueError("header row not found (no name + expertise columns)")


def col_index(header: list[str], hints: list[str]) -> int | None:
    """
    --------------------------------------------------------------------------
    Purpose:
        Find the first header cell matching one of a set of candidate
        column-name hints.

    Inputs:
        header (list[str]): the header row's raw cells.
        hints (list[str]): candidate substrings, in priority order.

    Outputs:
        index (int | None): the matching column's 0-based index, or None.
    --------------------------------------------------------------------------
    """
    cells = [norm(c) for c in header]
    for hint in hints:
        for i, cell in enumerate(cells):
            if hint in cell:
                return i
    return None


def language_columns(header: list[str]) -> list[tuple[int, str]]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Find every Read/Write/Speak x English/French column in the header.

    Inputs:
        header (list[str]): the header row's raw cells.

    Outputs:
        columns (list[tuple[int, str]]): (column index, label) pairs,
            e.g. (4, "read EN").

    Known limitation (declined, 2026-10-02 code review): only English and
    French are recognized. A reference file declaring a third language
    (e.g. "Write Spanish" for a worldwide search) has that column silently
    ignored rather than reported - this skill's professors are presumed
    EN/FR in Workflow 6c for the same reason, and generalizing to arbitrary
    language names would need a maintained language-name table this skill
    does not otherwise carry. Not fixed here; flagged for the professor to
    decide whether a third language is worth that table.
    --------------------------------------------------------------------------
    """
    out = []
    for i, cell in enumerate(header):
        c = norm(cell)
        lang = "EN" if "english" in c or "anglais" in c else \
               "FR" if "french" in c or "francais" in c else None
        skill = "read" if c.startswith("read") or c.startswith("lire") else \
                "write" if c.startswith("write") or c.startswith("ecrire") else \
                "speak" if c.startswith("speak") or c.startswith("parler") else None
        if lang and skill:
            out.append((i, f"{skill} {lang}"))
    return out


def get(row: list[str], idx: int | None) -> str:
    """
    --------------------------------------------------------------------------
    Purpose:
        Read one cell of a data row by (possibly absent) column index.

    Inputs:
        row (list[str]): one data row.
        idx (int | None): the column index, or None when the column was
            not found in the header.

    Outputs:
        value (str): the trimmed cell value, or "" when idx is None or out
            of range.
    --------------------------------------------------------------------------
    """
    return row[idx].strip() if idx is not None and idx < len(row) else ""


def main(argv: list[str]) -> int:
    """
    --------------------------------------------------------------------------
    Purpose:
        CLI entry point: load the reference file, match its rows against
        the supplied keywords, and write the sorted shortlist.

    Inputs:
        argv (list[str]): command-line arguments, excluding the program name.

    Outputs:
        exit_code (int): 0 on success, 1 if the name or expertise column
            could not be found in the header.
    --------------------------------------------------------------------------
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", required=True)
    parser.add_argument("--terms", required=True,
                        help="comma-separated terms, or a path to a file with one term per line")
    parser.add_argument("--out", required=True)
    parser.add_argument("--min-matches", type=int, default=1)
    parser.add_argument("--dry-run", action="store_true",
                        help="report the match count, write nothing")
    args = parser.parse_args(argv)

    terms_path = Path(args.terms)
    if terms_path.exists() and terms_path.suffix in (".txt", ".md", ".csv"):
        raw_terms = [line.strip(" -\t") for line in
                     terms_path.read_text(encoding="utf-8").splitlines()]
        terms = [t for t in raw_terms if t and not t.startswith("#")]
    else:
        terms = [t.strip() for t in args.terms.split(",") if t.strip()]
    norm_terms = [(t, norm(t)) for t in terms]

    grid = read_grid(Path(args.file))
    try:
        h = find_header(grid)
    except ValueError as exc:
        print(f"INVALID: {exc}")
        return 1
    header = grid[h]
    ci_name = col_index(header, NAME_HINTS)
    ci_exp = col_index(header, EXPERTISE_HINTS)
    ci_inst = col_index(header, INSTITUTION_HINTS)
    ci_dept = col_index(header, DEPARTMENT_HINTS)
    ci_avail = col_index(header, AVAILABILITY_HINTS)
    lang_cols = language_columns(header)
    if ci_name is None or ci_exp is None:
        print("INVALID: name or expertise column not found in header:", header)
        return 1

    matches, total, unavailable = [], 0, 0
    for row in grid[h + 1:]:
        name = get(row, ci_name)
        expertise = get(row, ci_exp)
        if not name or not expertise:
            continue
        total += 1
        exp_norm = norm(expertise)
        hit = [orig for orig, nt in norm_terms if nt and nt in exp_norm]
        if len(hit) < args.min_matches:
            continue
        # Only the "not available" flag is normalized to a fixed label; any
        # other declared text (e.g. "Available for 2 reviews max") is kept
        # VERBATIM rather than flattened to a bare "Available" - the SKILL.md
        # workflow (6c) and this script's own docstring promise the file's
        # declared data is surfaced, not summarized (2026-10-08 code review).
        availability = get(row, ci_avail)
        if NOT_AVAILABLE in norm(availability):
            availability = "Not available this year"
            unavailable += 1
        langs = sorted({label for idx, label in lang_cols
                        if idx < len(row) and row[idx].strip()})
        matches.append({
            "name": name,
            "institution": get(row, ci_inst),
            "department": get(row, ci_dept),
            "areas_of_expertise": re.sub(r"\s+", " ", expertise),
            "matched_terms": "; ".join(hit),
            "match_count": len(hit),
            "languages_declared": "; ".join(langs),
            "availability": availability,
        })

    matches.sort(key=lambda m: (-m["match_count"], m["name"]))
    out = Path(args.out)
    if args.dry_run:
        print(f"DRY RUN - ROWS SCANNED: {total}  MATCHES: {len(matches)}  "
              f"(of which not-available: {unavailable})  (would write {out})")
    else:
        with out.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=OUTPUT_FIELDS)
            writer.writeheader()
            writer.writerows(matches)
        print(f"ROWS SCANNED: {total}  MATCHES: {len(matches)}  "
              f"(of which not-available: {unavailable})  -> {out}")
    for m in matches[:20]:
        flag = " [NOT AVAILABLE]" if m["availability"].startswith("Not") else ""
        print(f"  {m['match_count']}x {m['name']} - {m['institution']}{flag}: {m['matched_terms']}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
