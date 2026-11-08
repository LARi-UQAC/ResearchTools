"""
aider-rules-sync - derive aider's coding rules from their canonical source.

Aider has no notion of a rule file of its own: it reads whatever the config
names under `read:`. This script writes that file rather than anyone editing
it, so the rules aider follows cannot drift away from the ones the repository
enforces. Re-run it after any rule changes.

Stage: machine setup. Reads .claude/rules/*.md, writes ~/.aider-rules.md.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import sys

# The canonical rules directory. Resolved from the environment so no machine
# path is written into the code (R1); the default is documented rather than
# silently assumed, and a missing directory is an explicit error (R3).
ENV_VAR = "AIDER_RULES_SOURCE"

# A rules directory beside the generated file, for rules this kit adds and for
# rules a student writes. It is a sibling of rules.md rather than a path of its
# own so that setup.ps1 installs it with everything else, and so a student who
# opens their configuration directory finds it without being told.
LOCAL_SOURCE_NAME = "rules-local"
# Resolved from this script's own location rather than written as a literal
# (R1): this script now lives inside ResearchTools itself, at
# .claude/skills/aider-setup/scripts/aider-rules-sync.py, so its canonical
# rules directory is always the repository's own .claude/rules, wherever the
# clone sits. build_kit.py blanks this line to an empty string when it ships
# the kit to a student, whose machine has no such repository (R1, R2).
DEFAULT_SOURCE = str(pathlib.Path(__file__).resolve().parents[4] / ".claude" / "rules")

# A rule opens with **Rn - <statement>.** and runs to the next rule, the next
# heading, or the end of the file. The statement itself may wrap across lines,
# which is why this is not a line-oriented match.
RULE_OPEN = re.compile(r"\*\*R(\d+)\b(.*?)\*\*", re.DOTALL)
STOP = re.compile(r"^#{1,6} |\*\*R\d+\b", re.MULTILINE)


def extract(text: str, origin: str) -> dict[int, tuple[str, str]]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Pull every numbered rule out of one rules file.

    Inputs:
        text (str): the file's whole content.
        origin (str): the file's name, kept so each rule cites where it lives.

    Outputs:
        rules (dict[int, tuple[str, str]]): number -> (body, origin).
    --------------------------------------------------------------------------
    """
    rules: dict[int, tuple[str, str]] = {}
    for m in RULE_OPEN.finditer(text):
        number = int(m.group(1))
        tail = text[m.start():]
        # Skip this rule's own opening before looking for the next stop mark.
        nxt = STOP.search(tail, m.end() - m.start())
        body = tail[: nxt.start()] if nxt else tail
        rules[number] = (body.strip(), origin)
    return rules


def count_tokens(text: str):
    """
    Token count with the same encoding aider uses for its own estimates, or
    None when tiktoken is not installed.

    None is a degradation and not a failure: the cap is an optimisation, and a
    machine without tiktoken should still get correct rules. The caller says so
    out loud rather than capping on a guessed characters-per-token ratio, and
    the driver measures rules.md against its ceiling on every run anyway, so an
    uncapped file is reported downstream instead of passing unnoticed.
    """
    try:
        import tiktoken
    except Exception:
        return None
    return len(tiktoken.get_encoding("cl100k_base").encode(text))


# Sentence ends, used to truncate a rule body somewhere a reader can stop.
# Cutting mid-sentence produces a rule whose last clause reverses its meaning
# ("never write a literal, except" -> "never write a literal, except").
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


def cap_body(body: str, max_tokens: int) -> tuple[str, bool]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Trim one rule's body to at most max_tokens, keeping whole sentences.
        The bolded statement is never cut: it is what binds, and a rule
        stripped of its statement is not a shorter rule but a different one.

    Inputs:
        body (str): the rule as extracted, statement first.
        max_tokens (int): the per-rule cap, from configuration.

    Outputs:
        (text, trimmed): the possibly shortened body, and whether it was cut.
        A body already inside the cap is returned unchanged, so most rules pass
        through byte-identical.
    --------------------------------------------------------------------------
    """
    total = count_tokens(body)
    if total is None or total <= max_tokens:
        return body, False

    sentences = _SENTENCE_END.split(body)
    kept: list[str] = []
    for sentence in sentences:
        candidate = " ".join(kept + [sentence])
        if kept and count_tokens(candidate) > max_tokens:
            break
        kept.append(sentence)
    # Always keep at least the first sentence, which carries the statement,
    # even where that alone exceeds the cap. A cap is not a licence to emit a
    # rule with no statement in it.
    if not kept:
        kept = [sentences[0]]
    return " ".join(kept).rstrip() + " [...]", True


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source", action="append", default=None,
                    help=f"a rules directory; repeat for several. Default: "
                         f"${ENV_VAR} (else the documented path), then "
                         f"{LOCAL_SOURCE_NAME} beside the generated file if it exists")
    ap.add_argument("--out",
                    default=str(pathlib.Path.home() / ".config" / "aider" / "rules.md"),
                    help="generated rules file (default: ~/.config/aider/rules.md)")
    ap.add_argument("--dry-run", action="store_true",
                    help="report what would be written and write nothing")
    ap.add_argument("--max-rule-tokens", type=int, default=None,
                    help="cap on ONE rule's body, whole sentences kept. Default: "
                         "ceilings.rule_body_tokens in context-budget.json beside "
                         "the generated file. 0 disables capping")
    ap.add_argument("--budget-file", default=None,
                    help="where to read the cap from (default: "
                         "context-budget.json beside --out)")
    args = ap.parse_args()

    # The cap is configuration, never a literal here (R0), and a value that is
    # configured nowhere is named rather than defaulted (R3).
    max_rule_tokens = args.max_rule_tokens
    if max_rule_tokens is None:
        budget_file = (pathlib.Path(args.budget_file) if args.budget_file
                       else pathlib.Path(args.out).parent / "context-budget.json")
        if not budget_file.is_file():
            print(f"REFUSED: no cap for a rule's body. Looked for "
                  f"'ceilings.rule_body_tokens' in {budget_file}, which does not "
                  f"exist.\n  Pass --max-rule-tokens N, or --max-rule-tokens 0 to "
                  f"emit every rule in full.", file=sys.stderr)
            return 2
        try:
            budget = json.loads(budget_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            print(f"REFUSED: {budget_file} does not parse: {exc}", file=sys.stderr)
            return 2
        value = (budget.get("ceilings") or {}).get("rule_body_tokens")
        if value is None:
            print(f"REFUSED: 'ceilings.rule_body_tokens' is absent from "
                  f"{budget_file}.\n  Pass --max-rule-tokens N, or 0 to emit every "
                  f"rule in full.", file=sys.stderr)
            return 2
        max_rule_tokens = int(value)

    # Several sources, because the canonical rules directory is not always
    # writable and on a student machine it does not exist at all. A local
    # directory beside the generated file is where a rule this kit adds lives,
    # and where a student puts one of their own. Without it the only ways to add
    # a rule are to edit another repository or to hand-edit the generated file,
    # and the generated file says not to.
    if args.source:
        sources = [pathlib.Path(s) for s in args.source]
    else:
        # Since 2026-11-07 the canonical rules directory of the repository is NOT
        # imported by default: which rules bind a model that writes code is a
        # judgement, made by a person and written into the kit's own rules-local
        # file, never a copy of every rule of the toolkit. The environment
        # variable still points at a directory on purpose, for a person who
        # chooses to read one.
        sources = []
        if os.environ.get(ENV_VAR):
            sources.append(pathlib.Path(os.environ[ENV_VAR]))
        local = pathlib.Path(args.out).parent / LOCAL_SOURCE_NAME
        if local.is_dir():
            sources.append(local)

    usable = [s for s in sources if s.is_dir()]
    if not usable:
        print("REFUSED: no rules directory found. Looked in:", file=sys.stderr)
        for s in sources:
            print(f"  {s}", file=sys.stderr)
        print(f"  Set {ENV_VAR} to the .claude/rules directory, or create "
              f"{LOCAL_SOURCE_NAME} beside the generated file.", file=sys.stderr)
        return 2

    found: dict[int, tuple[str, str]] = {}
    origin: dict[int, str] = {}
    for source in usable:
        for f in sorted(source.glob("*.md")):
            for number, rule in extract(
                    f.read_text(encoding="utf-8", errors="replace"), f.name).items():
                # A number defined twice is ambiguous, and silently keeping the
                # last one read would make the rules depend on directory order.
                # Refuse and name both, the way a missing key is named (R3).
                if number in found:
                    print(f"REFUSED: R{number} is defined twice:", file=sys.stderr)
                    print(f"  {origin[number]}", file=sys.stderr)
                    print(f"  {source / f.name}", file=sys.stderr)
                    print("  Two definitions of one rule is not a merge, it is a "
                          "question nobody answered.", file=sys.stderr)
                    return 2
                found[number] = rule
                origin[number] = str(source / f.name)

    if not found:
        print("REFUSED: no numbered rule found under "
              + ", ".join(str(s) for s in usable), file=sys.stderr)
        return 2

    numbers = sorted(found)
    gaps = [n for n in range(numbers[0], numbers[-1] + 1) if n not in found]
    # A gap list is a warning that a rule was written as a citation rather than a
    # statement, which is worth seeing. A hundred of them is not: one rule with a
    # far-off number, say a local R99, would report every number between as
    # missing and drown the real signal. Measured 2026-09-03 on exactly that case.
    GAPS_SHOWN = 8
    gaps_text = ", ".join("R%d" % g for g in gaps[:GAPS_SHOWN])
    if len(gaps) > GAPS_SHOWN:
        gaps_text += ", and %d more" % (len(gaps) - GAPS_SHOWN)

    # Apply the per-rule cap. A rule already inside it passes through
    # byte-identical, so most of the file is untouched and a diff shows exactly
    # which rules were long enough to matter.
    bodies: dict[int, str] = {}
    trimmed: list[int] = []
    for n in numbers:
        if max_rule_tokens > 0:
            text, was_cut = cap_body(found[n][0], max_rule_tokens)
        else:
            text, was_cut = found[n][0], False
        bodies[n] = text
        if was_cut:
            trimmed.append(n)

    if max_rule_tokens > 0 and count_tokens("probe") is None:
        print("WARNING: tiktoken is not installed, so nothing was capped and "
              "rules.md is emitted in full. The rules are correct but the file "
              "may exceed its ceiling, which the driver reports on every run. "
              "Install tiktoken, or pass --max-rule-tokens 0 to make it the "
              "intent.", file=sys.stderr)

    # The paragraph that used to sit here apologised for examples naming another
    # repository's files. With bodies capped most of those examples are gone, so
    # the apology is only written when something was actually abridged - and it
    # then says what was cut, which the apology never did.
    # The model reads this file on every call, so it carries rules and nothing
    # about where they came from: no source names, no generator, no abridging
    # note. A rule cut by the per-rule cap is still reported to the person who
    # runs the generator, on stderr, and never inside the file.
    if trimmed:
        print("WARNING: cut at the per-rule cap of %d tokens: %s. Shorten the rule "
              "in its source instead." % (max_rule_tokens, ", ".join("R%d" % n for n in trimmed)),
              file=sys.stderr)

    header = (
        "# Coding rules\n\n"
        "These rules bind every file you write. Follow them exactly.\n\n"
        f"Rules: {len(found)} (R{numbers[0]}-R{numbers[-1]})\n\n"
        "---\n\n"
    )

    body = "\n\n".join(bodies[n] for n in numbers)
    out_text = header + body + "\n"

    if args.dry_run:
        print(f"would write {args.out}: {len(out_text)} bytes, "
              f"{len(found)} rules R{numbers[0]}-R{numbers[-1]}"
              + (f", absent {gaps}" if gaps else ""))
        return 0

    pathlib.Path(args.out).write_text(out_text, encoding="utf-8")
    # Verify the effect rather than trusting the call (R9).
    written = pathlib.Path(args.out).read_text(encoding="utf-8")
    if len(written) != len(out_text):
        print("FAILED: what landed on disk is not what was written", file=sys.stderr)
        return 1
    print(f"wrote {args.out}: {len(written)} bytes, {len(found)} rules "
          f"R{numbers[0]}-R{numbers[-1]}" + (f", absent {gaps}" if gaps else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
