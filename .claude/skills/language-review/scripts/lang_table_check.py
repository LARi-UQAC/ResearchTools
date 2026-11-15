"""
lang_table_check - validate the language-review category table and list an agent's language flags.

The table (assets/language_categories.json) is the single source of the language-only correction
codes shared by the research auditors (LaTeX target) and the undergraduate grader (PDF target).
This checker refuses a malformed table by name and, for a given agent definition, lists the table
flags it prints and the language flags it prints that the table lacks, so a migration can prove no
flag was lost (Issue #104, plan 1 and plan 2).

Exit codes: 0 clean, 1 unknown language flags found, 2 refusal (unreadable or malformed table,
missing agent file).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REQUIRED_KEYS = ("code", "flag", "label_fr", "label_en", "severity", "scope", "rule",
                 "latex_action", "pdf_action")
SEVERITIES = ("minor", "major")
SCOPES = ("research", "undergraduate", "both")
LATEX_ACTIONS = ("direct_fix", "replaced")
# The content codes of reviewer-response classify reviewer comments, not language (spec D9).
CONTENT_CODES = frozenset({"SC", "M", "R", "D", "FT", "EQ", "REF", "Q", "MAJ"})
DEFAULT_TABLE = Path(__file__).resolve().parent.parent / "assets" / "language_categories.json"

_CODE_RE = re.compile(r"[A-Z]{1,6}")
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
_BRACKET_RE = re.compile(r"\[([A-Z][^\[\]\n]*)\]")
_FLAG_RE = re.compile(r"[A-Z][A-Z0-9-]*(?: [A-Z][A-Z0-9-]*)+")


class TableError(ValueError):
    """Raised when the language table is unreadable or malformed."""


def configure_streams() -> None:
    """
    --------------------------------------------------------------------------
    Purpose:
        Put stdout and stderr on utf-8 so an accented label never kills a
        report on a cp1252 console (own copy of extract_text's pattern, R18).

    Inputs:
        None

    Outputs:
        None. Reconfigures sys.stdout and sys.stderr when they allow it.
    --------------------------------------------------------------------------
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            try:
                reconfigure(errors="replace")
            except (ValueError, OSError):
                pass


def _read_json(path: Path) -> dict:
    """
    --------------------------------------------------------------------------
    Purpose:
        Read the table file as JSON.

    Inputs:
        path (Path): table file.

    Outputs:
        data (dict): parsed object.

    Raises:
        TableError: the file is missing, not utf-8, not JSON, or not an object.
    --------------------------------------------------------------------------
    """
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TableError(f"cannot read table {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise TableError(f"table {path} is not a JSON object")
    return data


def _check_entry(index: int, entry: object) -> None:
    """
    --------------------------------------------------------------------------
    Purpose:
        Validate one table entry against the fixed shape.

    Inputs:
        index (int): position in the entries list, used when the code is absent.
        entry (object): the entry to check.

    Outputs:
        None.

    Raises:
        TableError: naming the entry and the faulty key.
    --------------------------------------------------------------------------
    """
    if not isinstance(entry, dict):
        raise TableError(f"entry {index} is not an object")
    name = entry.get("code") or f"#{index}"
    for key in REQUIRED_KEYS:
        if key not in entry:
            raise TableError(f"entry {name}: missing key '{key}'")
    code = entry["code"]
    if not isinstance(code, str) or not _CODE_RE.fullmatch(code):
        raise TableError(f"entry {name}: key 'code' must be 1 to 6 upper-case letters")
    if code in CONTENT_CODES:
        raise TableError(f"entry {name}: key 'code' is a content code, not a language code")
    if entry["flag"] is not None and (not isinstance(entry["flag"], str) or not entry["flag"]):
        raise TableError(f"entry {name}: key 'flag' must be a non-empty string or null")
    for key in ("label_fr", "label_en"):
        if not isinstance(entry[key], str) or not entry[key].strip():
            raise TableError(f"entry {name}: key '{key}' must be a non-empty string")
    if entry["severity"] not in SEVERITIES:
        raise TableError(f"entry {name}: key 'severity' must be one of {SEVERITIES}")
    if entry["scope"] not in SCOPES:
        raise TableError(f"entry {name}: key 'scope' must be one of {SCOPES}")
    if entry["rule"] is not None and not (isinstance(entry["rule"], str)
                                          and re.fullmatch(r"R\d+\.\d+", entry["rule"])):
        raise TableError(f"entry {name}: key 'rule' must look like R1.7 or be null")
    if entry["latex_action"] not in LATEX_ACTIONS:
        raise TableError(f"entry {name}: key 'latex_action' must be one of {LATEX_ACTIONS}")
    pdf = entry["pdf_action"]
    if not isinstance(pdf, dict):
        raise TableError(f"entry {name}: key 'pdf_action' must be an object")
    for key in ("color", "prefix"):
        if not isinstance(pdf.get(key), str) or not pdf[key].strip():
            raise TableError(f"entry {name}: key 'pdf_action.{key}' must be a non-empty string")


def load_table(path: Path) -> list[dict]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Load and validate the language table.

    Inputs:
        path (Path): language_categories.json.

    Outputs:
        entries (list[dict]): the validated entries, in file order. The
            'not_language' block is read separately with not_language(path).

    Raises:
        TableError: unreadable file, missing 'entries', a malformed entry, or
            two entries sharing a code or a flag.
    --------------------------------------------------------------------------
    """
    data = _read_json(path)
    entries = data.get("entries")
    if not isinstance(entries, list) or not entries:
        raise TableError(f"table {path}: missing or empty key 'entries'")
    seen_codes: set[str] = set()
    seen_flags: set[str] = set()
    for index, entry in enumerate(entries):
        _check_entry(index, entry)
        if entry["code"] in seen_codes:
            raise TableError(f"entry {entry['code']}: duplicate code")
        seen_codes.add(entry["code"])
        if entry["flag"]:
            if entry["flag"] in seen_flags:
                raise TableError(f"entry {entry['code']}: duplicate flag '{entry['flag']}'")
            seen_flags.add(entry["flag"])
    return entries


def not_language(path: Path) -> set[str]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Read the flags declared as not-language (structure or process flags
        that appear in a composition section but stay in the agents).

    Inputs:
        path (Path): language_categories.json.

    Outputs:
        flags (set[str]): declared flags, '_provenance' excluded.

    Raises:
        TableError: unreadable file, or 'not_language' not an object.
    --------------------------------------------------------------------------
    """
    block = _read_json(path).get("not_language", {})
    if not isinstance(block, dict):
        raise TableError(f"table {path}: key 'not_language' must be an object")
    return {key for key in block if not key.startswith("_")}


def _composition_blocks(agent_text: str) -> list[str]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Cut out the parts of an agent file that carry its language flags: every
        heading whose title names 'Composition', down to the next heading of
        the same or a higher level.

    Inputs:
        agent_text (str): the agent definition.

    Outputs:
        blocks (list[str]): one text block per composition heading.
    --------------------------------------------------------------------------
    """
    lines = agent_text.splitlines()
    blocks: list[str] = []
    for start, line in enumerate(lines):
        match = _HEADING_RE.match(line)
        if not match or "composition" not in match.group(2).lower():
            continue
        level = len(match.group(1))
        end = len(lines)
        for later in range(start + 1, len(lines)):
            other = _HEADING_RE.match(lines[later])
            if other and len(other.group(1)) <= level:
                end = later
                break
        blocks.append("\n".join(lines[start:end]))
    return blocks


def _bracket_flags(text: str) -> set[str]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Extract flag names from bracketed tags, splitting alternatives on ' / '
        and dropping any ': detail' suffix.

    Inputs:
        text (str): text to scan.

    Outputs:
        flags (set[str]): upper-case multi-word flag names.
    --------------------------------------------------------------------------
    """
    flags: set[str] = set()
    for body in _BRACKET_RE.findall(text):
        for part in body.split(" / "):
            head = part.split(":", 1)[0].strip()
            if _FLAG_RE.fullmatch(head):
                flags.add(head)
    return flags


def flags_in(agent_text: str, table: list[dict]) -> set[str]:
    """
    --------------------------------------------------------------------------
    Purpose:
        List the table flags an agent file prints, anywhere in the file.

    Inputs:
        agent_text (str): the agent definition.
        table (list[dict]): validated table entries.

    Outputs:
        flags (set[str]): table flags found in a bracketed tag.
    --------------------------------------------------------------------------
    """
    known = {entry["flag"] for entry in table if entry["flag"]}
    return known & _bracket_flags(agent_text)


def unknown_flags(agent_text: str, table: list[dict],
                  excluded: set[str] | None = None) -> set[str]:
    """
    --------------------------------------------------------------------------
    Purpose:
        List the language flags an agent prints in its composition sections
        that the table lacks.

    Inputs:
        agent_text (str): the agent definition.
        table (list[dict]): validated table entries.
        excluded (set[str] | None): declared not-language flags; None reads
            the shipped table's 'not_language' block.

    Outputs:
        flags (set[str]): flags missing from the table.
    --------------------------------------------------------------------------
    """
    if excluded is None:
        excluded = not_language(DEFAULT_TABLE)
    known = {entry["flag"] for entry in table if entry["flag"]}
    found: set[str] = set()
    for block in _composition_blocks(agent_text):
        found |= _bracket_flags(block)
    return found - known - excluded


def main(argv: list[str] | None = None) -> int:
    """
    --------------------------------------------------------------------------
    Purpose:
        Command line: validate the table and report each agent's flags.

    Inputs:
        argv (list[str] | None): arguments; None reads sys.argv.

    Outputs:
        code (int): 0 clean, 1 unknown flags found, 2 refusal. Prints a JSON
            report with --json, else one line per agent.
    --------------------------------------------------------------------------
    """
    configure_streams()
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--table", type=Path, default=DEFAULT_TABLE)
    parser.add_argument("--agent", type=Path, action="append", default=[])
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        table = load_table(args.table)
        excluded = not_language(args.table)
    except TableError as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
    report: dict = {"table": str(args.table), "entries": len(table), "found": {}, "unknown": {}}
    for agent in args.agent:
        try:
            text = agent.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            print(f"REFUSED: cannot read agent {agent}: {exc}", file=sys.stderr)
            return 2
        report["found"][agent.name] = sorted(flags_in(text, table))
        missing = sorted(unknown_flags(text, table, excluded))
        if missing:
            report["unknown"][agent.name] = missing
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"table: {len(table)} entries")
        for name, flags in report["found"].items():
            extra = report["unknown"].get(name, [])
            print(f"{name}: {len(flags)} table flags, unknown: {', '.join(extra) or 'none'}")
    return 1 if report["unknown"] else 0


if __name__ == "__main__":
    sys.exit(main())
