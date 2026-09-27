#!/usr/bin/env python3
"""
note_fidelity.py - refuse a drafted vault note that states a fact its brief never gave.

The gate between local-writer's local model and the outbox. Measured 2026-09-26: handed a
precise brief, the local model drafted five notes that all carried invented facts - an
unmeasured "1405 MiB", functions from an unrelated module, a wrong [[project]] link - and the
wrapper reported them as correct, because every existing check proved only that a file
existed on disk. Once flushed, six writes had to be undone from the vault journal.

What it checks, mechanically: every FACT TOKEN of the draft must appear in the brief. A fact
token is a number (a decimal comma read as a point; an integer shorter than
min_integer_digits is prose and skipped), a backticked span, a function call name(), a file
name, a snake_case identifier, a commit hash, or a [[wiki-link]] target. The directive line
and the frontmatter keys in unchecked_frontmatter_keys are the writer's own choices, not facts.

What it cannot check, stated so no document claims more (R15): a claim re-worded into its
opposite with no new token passes - the inverted 2026-09-26 WDDM draft would have. Reading
the staged note is still required. Nor does it notice a fact the brief gave that the draft
dropped.

Exit codes (R12): 0 faithful (and staged when --stage), 2 refused by design (a token not in
the brief, no directive line to stage, an unsafe slug), 1 failure (a file or key missing).
"""
import argparse
import json
import re
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import outbox_io  # noqa: E402

CONFIG_PATH = SCRIPTS.parent / "note-fidelity.json"

# Order matters: each span is blanked once matched, so "gpu_memory.py" is one file-name token
# rather than also a snake_case token and a stray number.
_IDENTIFIERS = [
    ("backtick", re.compile(r"`([^`\n]+)`")),
    ("link", re.compile(r"\[\[([^\]|#\n]+)(?:[#|][^\]\n]*)?\]\]")),
    ("call", re.compile(r"\b([A-Za-z_][\w.]*)\(\)")),
    ("file", re.compile(r"\b([\w.-]+\.(?:py|ps1|psm1|json|jsonl|md|ya?ml|txt|js|ts|html|css|bat"
                        r"|sh|toml|cfg|ini))\b", re.I)),
    ("hash", re.compile(r"\b((?=[0-9a-f]*\d)(?=[0-9a-f]*[a-f])[0-9a-f]{7,40})\b")),
    ("snake", re.compile(r"\b([A-Za-z][A-Za-z0-9]*_\w+)\b")),
]
_NUMBER = re.compile(r"(?<![\w.,])(\d+(?:[.,]\d+)?)(?!\w)")
_FRONTMATTER_KEY = re.compile(r"^([A-Za-z_][\w-]*)\s*:")


def load_config(path: Path = CONFIG_PATH) -> dict:
    """
    --------------------------------------------------------------------------
    Purpose:
        Parse note-fidelity.json.

    Inputs:
        path (Path): the configuration file

    Outputs:
        config (dict): the parsed file

    Raises:
        FileNotFoundError: the file does not exist.
        ValueError: the file is not valid JSON.
    --------------------------------------------------------------------------
    """
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path} is not valid JSON: {exc}") from exc


def _value(config: dict, key: str):
    """Purpose: a config entry's value. Raises: KeyError naming the key and file (R3)."""
    if key not in config or "value" not in config[key]:
        raise KeyError(f"note-fidelity.json declares no '{key}'")
    return config[key]["value"]


def _fact_text(note: str, unchecked: list) -> str:
    """
    --------------------------------------------------------------------------
    Purpose:
        The part of a draft that states facts: without the directive line and
        without the frontmatter lines whose key the writer chooses freely.

    Inputs:
        note (str): the drafted note, directive line included if any
        unchecked (list[str]): frontmatter keys that are not facts

    Outputs:
        text (str): the text to check
    --------------------------------------------------------------------------
    """
    lines = note.splitlines()
    if lines and outbox_io.DIRECTIVE.match(lines[0]):
        lines = lines[1:]
    out, in_front, seen_front = [], False, False
    for line in lines:
        if line.strip() == "---" and not seen_front and not in_front and not any(o.strip() for o in out):
            in_front = True
            continue
        if in_front and line.strip() == "---":
            in_front, seen_front = False, True
            continue
        if in_front:
            key = _FRONTMATTER_KEY.match(line)
            if key and key.group(1) in unchecked:
                continue
        out.append(line)
    return "\n".join(out)


def _numbers(text: str, min_digits: int, check_short: bool) -> set:
    found = set()
    for raw in _NUMBER.findall(text):
        num = raw.replace(",", ".")
        if "." not in num and len(num) < min_digits and check_short:
            continue
        found.add(num)
    return found


def fact_tokens(text: str, min_digits: int) -> list:
    """
    --------------------------------------------------------------------------
    Purpose:
        The fact tokens of a text, each once, in reading order.

    Inputs:
        text (str): fact text (see _fact_text)
        min_digits (int): integers shorter than this are prose, not facts

    Outputs:
        tokens (list[tuple[str, str]]): (kind, token) pairs; a link is kept
        in its [[...]] form, a call with its parentheses
    --------------------------------------------------------------------------
    """
    tokens, work = [], text
    for kind, pattern in _IDENTIFIERS:
        for match in pattern.finditer(work):
            token = match.group(1).strip()
            shown = f"[[{token}]]" if kind == "link" else (f"{token}()" if kind == "call" else token)
            if (kind, shown) not in tokens:
                tokens.append((kind, shown))
        work = pattern.sub(lambda m: " " * len(m.group(0)), work)
    for num in sorted(_numbers(work, min_digits, True), key=work.find):
        tokens.append(("number", num))
    return tokens


def _supported(kind: str, token: str, brief: str, brief_lower: str, brief_numbers: set) -> bool:
    if kind == "number":
        return token in brief_numbers
    bare = token[2:-2] if kind == "link" else (token[:-2] if kind == "call" else token)
    return bare.lower() in brief_lower


def check(note: str, brief: str, config: dict) -> dict:
    """
    --------------------------------------------------------------------------
    Purpose:
        Decide whether every fact token of a drafted note comes from its brief.

    Inputs:
        note (str): the drafted note, directive line included if any
        brief (str): the facts the writer was given, verbatim
        config (dict): parsed note-fidelity.json

    Outputs:
        verdict (dict): status ("faithful" | "unfaithful"), unsupported (list
        of tokens not found in the brief, in reading order), checked (int)

    Raises:
        KeyError: a configuration key is absent (R3).
    --------------------------------------------------------------------------
    """
    min_digits = _value(config, "min_integer_digits")
    unchecked = _value(config, "unchecked_frontmatter_keys")
    tokens = fact_tokens(_fact_text(note, unchecked), min_digits)
    brief_numbers = _numbers(brief, 0, False)
    unsupported = [t for k, t in tokens
                   if not _supported(k, t, brief, brief.lower(), brief_numbers)]
    return {"status": "unfaithful" if unsupported else "faithful",
            "unsupported": unsupported, "checked": len(tokens)}


def main(argv=None, config: dict = None) -> int:
    """
    --------------------------------------------------------------------------
    Purpose:
        CLI: check a draft against its brief and, with --stage, put it in the
        outbox only when faithful.

    Inputs:
        argv (list[str] | None): arguments; None reads sys.argv
        config (dict | None): injected configuration; None reads note-fidelity.json

    Outputs:
        code (int): 0 faithful (staged with --stage), 2 refused, 1 failure (R12).
        A JSON verdict on stdout (R17); with --stage and not --dry-run, the
        staged <slug>.md in the outbox.
    --------------------------------------------------------------------------
    """
    p = argparse.ArgumentParser(description="Refuse a drafted vault note stating facts its brief never gave.")
    p.add_argument("--brief", required=True, help="file holding the facts given, verbatim")
    p.add_argument("--note", required=True, help="the drafted note, directive line first")
    p.add_argument("--stage", metavar="SLUG", help="stage as <outbox>/<SLUG>.md when faithful")
    p.add_argument("--outbox", help="outbox root (default: the vault daemon's OUTBOX)")
    p.add_argument("--dry-run", action="store_true", help="check and report, stage nothing")
    args = p.parse_args(argv)
    try:
        config = config if config is not None else load_config()
        brief = Path(args.brief).read_text(encoding="utf-8")
        note = Path(args.note).read_text(encoding="utf-8")
        verdict = check(note, brief, config)
    except (OSError, KeyError, ValueError) as exc:
        print(f"FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    if verdict["status"] != "faithful":
        print(json.dumps(verdict, ensure_ascii=False))
        print("REFUSED: fix the draft from the brief or drop the claim; never widen the brief.",
              file=sys.stderr)
        return 2
    if args.stage:
        directive, _, content = note.partition("\n")
        if not outbox_io.DIRECTIVE.match(directive):
            print(json.dumps(verdict | {"status": "refused", "reason": "no directive line"}))
            return 2
        if not re.fullmatch(r"[\w][\w.-]*", args.stage):
            print(json.dumps(verdict | {"status": "refused", "reason": "unsafe slug"}))
            return 2
        if args.outbox:
            outbox = Path(args.outbox)
        else:
            from vault_daemon import OUTBOX
            outbox = OUTBOX
        if args.dry_run:
            verdict["would_stage"] = str(outbox / f"{args.stage}.md")
        else:
            verdict["staged"] = str(outbox_io.stage(outbox, args.stage, content.lstrip("\n"),
                                                    directive=directive))
    print(json.dumps(verdict, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    outbox_io.configure_streams()
    sys.exit(main())
