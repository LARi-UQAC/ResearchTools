"""
aider-rules-check - validate the kit's coding rules file, never rewrite it.

`rules.md` is written by hand and is the only copy: the model reads it on every call, so a rule that is
too long, a number used twice or a gap in the numbering costs a student a wrong night. The driver runs
this check before every pass and refuses, naming the rule, when the file is not valid. Until 2026-11-11 a
generator derived the file from a second one and CUT a long rule at the cap without a word inside the
file; that is replaced by a refusal, because a rule silently shortened is a rule nobody wrote.

Stage: before every run. Reads one file, writes nothing.
Exit codes (R12): 0 valid, 2 refusal by design (the file is missing, empty, or breaks a rule below),
1 the token counter could not be loaded.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Callable, Optional

# A rule opens with a bolded id at the start of a line and runs to the next such line or the end.
RULE_START = re.compile(r"(?m)^\*\*R(\d+) - ")
# How many missing numbers are listed before the rest is summarised: one far-off number would otherwise
# report every number between as missing and drown the real signal.
GAPS_SHOWN = 8
ENCODING_NAME = "cl100k_base"  # the encoder aider uses for its own counts


def load_counter() -> Optional[Callable[[str], int]]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Return a function counting the tokens of a text the way aider does.

    Inputs:
        None

    Outputs:
        counter (callable | None): None when tiktoken is not installed in this interpreter.
    --------------------------------------------------------------------------
    """
    try:
        import tiktoken
    except ImportError:
        return None
    encoder = tiktoken.get_encoding(ENCODING_NAME)
    return lambda text: len(encoder.encode(text, disallowed_special=()))


def split_rules(text: str) -> list[tuple[int, str]]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Cut the file into its numbered rules, in file order.

    Inputs:
        text (str): the content of rules.md

    Outputs:
        rules (list[tuple[int, str]]): (number, full text of the rule, id included).
    --------------------------------------------------------------------------
    """
    starts = list(RULE_START.finditer(text))
    rules = []
    for index, match in enumerate(starts):
        end = starts[index + 1].start() if index + 1 < len(starts) else len(text)
        rules.append((int(match.group(1)), text[match.start():end].strip()))
    return rules


def check(text: str, max_rule_tokens: int, counter: Callable[[str], int]) -> tuple[list[str], dict]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Find what is wrong with a rules file.

    Details:
        Four faults: no rule at all, a number defined twice, numbers that do not run
        R0, R1, R2 ... without a gap, and a rule longer than the cap.

    Inputs:
        text (str): the content of rules.md
        max_rule_tokens (int): the cap on ONE rule, in tokens
        counter (callable): text -> token count

    Outputs:
        result (tuple): (problems, summary). problems is a list of sentences, empty when the file is
        valid. summary holds the rule count, the first and last number, the longest rule and its count.
    --------------------------------------------------------------------------
    """
    rules = split_rules(text)
    if not rules:
        return ["no rule found: a rule opens a line with **R0 - statement.** in bold"], {}
    problems = []
    numbers = [number for number, _ in rules]
    seen = set()
    for number in numbers:
        if number in seen:
            problems.append("R%d is defined twice" % number)
        seen.add(number)
    missing = [n for n in range(0, max(numbers) + 1) if n not in seen]
    if missing:
        shown = ", ".join("R%d" % n for n in missing[:GAPS_SHOWN])
        if len(missing) > GAPS_SHOWN:
            shown += ", and %d more" % (len(missing) - GAPS_SHOWN)
        problems.append("the numbering must run from R0 without a gap, missing: " + shown)
    counts = {number: counter(body) for number, body in rules}
    for number, count in counts.items():
        if count > max_rule_tokens:
            problems.append("R%d is %d tokens, over the cap of %d: shorten it, nothing cuts it for you"
                            % (number, count, max_rule_tokens))
    longest = max(counts, key=counts.get)
    summary = {"rules": len(rules), "first": min(numbers), "last": max(numbers),
               "longest": longest, "longest_tokens": counts[longest]}
    return problems, summary


def main(argv: Optional[list[str]] = None) -> int:
    """
    --------------------------------------------------------------------------
    Purpose:
        Command line entry: check one rules file and print a one-line summary.

    Inputs:
        argv (list[str] | None): arguments, defaults to sys.argv[1:]. The file, and --max-rule-tokens N.

    Outputs:
        code (int): 0 valid, 2 refusal, 1 no token counter. One summary line on stdout when valid, the
        problems on stderr otherwise.
    --------------------------------------------------------------------------
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("rules_file")
    parser.add_argument("--max-rule-tokens", type=int, required=True,
                        help="cap on one rule, from ceilings.rule_body_tokens of context-budget.json")
    args = parser.parse_args(argv)
    path = Path(args.rules_file)
    if not path.is_file():
        print("REFUSED: %s does not exist" % path, file=sys.stderr)
        return 2
    counter = load_counter()
    if counter is None:
        print("tiktoken is not installed in this interpreter, so rule lengths cannot be checked",
              file=sys.stderr)
        return 1
    problems, summary = check(path.read_text(encoding="utf-8", errors="replace"),
                              args.max_rule_tokens, counter)
    if problems:
        print("REFUSED: %s breaks its own format:" % path, file=sys.stderr)
        for problem in problems:
            print("  " + problem, file=sys.stderr)
        return 2
    print("%d rules R%d-R%d, longest R%d at %d of %d tokens" % (
        summary["rules"], summary["first"], summary["last"], summary["longest"],
        summary["longest_tokens"], args.max_rule_tokens))
    return 0


if __name__ == "__main__":
    sys.exit(main())
