"""
plan_clean.py - strip from a spec or a plan what the local writer model cannot use.

The writer model sees only the mounted project and takes every sentence as a fact about its own world.
A rule number, a decision number, "the owner", a date or a header written for another program only
confuses it. This script applies the mechanical part of that cleaning, from the rules in plan-clean.json,
and lists every hit it cannot fix so the author rewrites those by hand.
"""
import argparse
import json
import re
import sys
from pathlib import Path

EXIT_CLEAN = 0
EXIT_HITS = 1
EXIT_REFUSED = 2
RULES_FILE = Path(__file__).resolve().parent / "plan-clean.json"


def load_rules(path: Path) -> dict:
    """
    --------------------------------------------------------------------------
    Purpose:
        Read the cleaning rules and compile their patterns.

    Inputs:
        path (Path): the rules file

    Outputs:
        rules (dict): strip_front_matter (bool), substitutions (list of dicts with compiled
            pattern and optional compiled line filter) and detect (compiled pattern)

    Raises:
        ValueError: the file is missing, is not JSON, or lacks a required key (the key is named).
    --------------------------------------------------------------------------
    """
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ValueError(f"cannot read the rules file {path}: {error}")
    for key in ("strip_front_matter", "substitutions", "detect"):
        if key not in raw:
            raise ValueError(f"key '{key}' is missing from {path}")
    subs = []
    for sub in raw["substitutions"]:
        only = sub.get("only_lines_matching")
        subs.append({"name": sub["name"], "pattern": re.compile(sub["pattern"]), "replace": sub["replace"],
                     "only": re.compile(only) if only else None})
    return {"strip_front_matter": bool(raw["strip_front_matter"]), "substitutions": subs,
            "detect": re.compile(raw["detect"], re.IGNORECASE)}


def strip_front_matter(text: str) -> str:
    """
    --------------------------------------------------------------------------
    Purpose:
        Remove a front matter block (a first line of three dashes up to the next line of three dashes).

    Inputs:
        text (str): the document

    Outputs:
        text (str): the document without the block, or unchanged when it has none
    --------------------------------------------------------------------------
    """
    unix = text.replace("\r\n", "\n")
    if unix.startswith("---\n") and "\n---\n" in unix[4:]:
        return unix.split("\n---\n", 1)[1].lstrip("\n")
    return text


def clean_text(text: str, rules: dict) -> tuple:
    """
    --------------------------------------------------------------------------
    Purpose:
        Apply the substitutions line by line, then report what is still left.

    Inputs:
        text (str): the document
        rules (dict): the compiled rules

    Outputs:
        (cleaned, changes, hits) (tuple): the cleaned text, a dict of rule name to number of
            substitutions, and a list of (line number, line) that still match the detect pattern
    --------------------------------------------------------------------------
    """
    if rules["strip_front_matter"]:
        text = strip_front_matter(text)
    changes = {}
    lines = []
    for line in text.split("\n"):
        for sub in rules["substitutions"]:
            if sub["only"] is not None and not sub["only"].search(line):
                continue
            line, count = sub["pattern"].subn(sub["replace"], line)
            if count:
                changes[sub["name"]] = changes.get(sub["name"], 0) + count
        lines.append(line)
    cleaned = "\n".join(lines)
    hits = [(number, line.strip()) for number, line in enumerate(cleaned.split("\n"), 1)
            if rules["detect"].search(line)]
    return cleaned, changes, hits


def collect_files(targets: list) -> list:
    """
    --------------------------------------------------------------------------
    Purpose:
        Expand the arguments into the Markdown files to clean.

    Inputs:
        targets (list[str]): files, or folders searched for spec.md and plan*.md

    Outputs:
        files (list[Path]): sorted, unique

    Raises:
        ValueError: a target does not exist.
    --------------------------------------------------------------------------
    """
    found = set()
    for target in targets:
        path = Path(target)
        if path.is_dir():
            found.update(path.glob("spec.md"))
            found.update(path.glob("plan*.md"))
        elif path.is_file():
            found.add(path)
        else:
            raise ValueError(f"no such file or folder: {target}")
    return sorted(found)


def main(argv: list = None) -> int:
    """
    --------------------------------------------------------------------------
    Purpose:
        Command line: clean the named files, dry run unless --write.

    Inputs:
        argv (list[str]): arguments; targets, --rules FILE, --write, --json

    Outputs:
        code (int): 0 every file clean, 1 hits remain for a hand fix, 2 refusal.
        Side effect: with --write each changed file is rewritten in place (UTF-8, LF).
    --------------------------------------------------------------------------
    """
    parser = argparse.ArgumentParser(description="Clean a spec or plans for the local writer model.")
    parser.add_argument("targets", nargs="+")
    parser.add_argument("--rules", default=str(RULES_FILE))
    parser.add_argument("--write", action="store_true", help="rewrite the files (default is a dry run)")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        rules = load_rules(Path(args.rules))
        files = collect_files(args.targets)
    except ValueError as error:
        print(f"REFUSED: {error}", file=sys.stderr)
        return EXIT_REFUSED
    report = []
    for path in files:
        original = path.read_text(encoding="utf-8")
        cleaned, changes, hits = clean_text(original, rules)
        changed = cleaned.replace("\r\n", "\n") != original.replace("\r\n", "\n")
        if args.write and changed:
            path.write_text(cleaned, encoding="utf-8", newline="\n")
        report.append({"file": str(path), "changed": changed, "written": bool(args.write and changed),
                       "changes": changes, "hits": [{"line": n, "text": t} for n, t in hits]})
    remaining = sum(len(item["hits"]) for item in report)
    if args.json:
        print(json.dumps({"files": report, "remaining": remaining}, indent=2, ensure_ascii=False))
    else:
        for item in report:
            state = "written" if item["written"] else ("would change" if item["changed"] else "unchanged")
            print(f"{Path(item['file']).name}: {state}, {sum(item['changes'].values())} substitution(s), "
                  f"{len(item['hits'])} hit(s) left")
            for hit in item["hits"]:
                print(f"    line {hit['line']}: {hit['text'][:150]}")
        print(f"{remaining} hit(s) left to rewrite by hand")
    return EXIT_HITS if remaining else EXIT_CLEAN


if __name__ == "__main__":
    sys.exit(main())
