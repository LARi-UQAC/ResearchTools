#!/usr/bin/env python3
"""Correspondence score (/5) for the professor-expertise-finder skill.

Five subscores A-E, each one of pef_config.json's subscore_values (see
references/scoring.md). Usage:
    python3 score.py --a 1 --b 1 --c 0.5 --d 0 --e 1
    -> 3.5/5 (A 1, B 1, C 0.5, D 0, E 1) - Very close
Exits 1 with an explanation if a subscore is invalid, or if E = 0 (fewer
than two verified in-field articles - a hard exclusion regardless of the
other subscores).
"""
from __future__ import annotations

import argparse
import sys

from pef_common import load_config, write_json

NAMES = ["a", "b", "c", "d", "e"]

# Interpretation bands, 1:1 with references/scoring.md's table (provenance:
# the professor's own rubric; not moved into pef_config.json because they
# are presentation labels over the total, not an enforced policy value).
BANDS = [
    (4.5, "Direct expert in the niche"),
    (3.5, "Very close"),
    (2.5, "Adjacent - transferable expertise"),
    (1.5, "Peripheral"),
    (0.0, "Do not retain"),
]


def fmt(value: float) -> str:
    """
    --------------------------------------------------------------------------
    Purpose:
        Render a score value without a trailing ".0" for whole numbers.

    Inputs:
        value (float): a subscore or total.

    Outputs:
        text (str): "1" for 1.0, "0.5" for 0.5, etc.
    --------------------------------------------------------------------------
    """
    return str(int(value)) if value == int(value) else str(value)


def total(sub: dict[str, float], allowed: set[float]) -> float:
    """
    --------------------------------------------------------------------------
    Purpose:
        Sum the five subscores into the /5 total, after validating each
        one and applying the E = 0 hard-exclusion rule.

    Inputs:
        sub (dict[str, float]): one entry per name in NAMES.
        allowed (set[float]): the rubric's allowed subscore values (from
            pef_config.json's subscore_values).

    Outputs:
        total (float): the sum of the five subscores.

    Raises:
        ValueError: a subscore is outside `allowed`, or sub["e"] == 0.0
            (fewer than two verified in-field articles).
    --------------------------------------------------------------------------
    """
    for name, value in sub.items():
        if value not in allowed:
            allowed_text = ", ".join(fmt(v) for v in sorted(allowed))
            raise ValueError(f"subscore {name.upper()} = {value}: only {allowed_text} are allowed")
    if sub["e"] == 0.0:
        raise ValueError("E = 0: fewer than two verified in-field articles - professor must be excluded")
    return sum(sub.values())


def band(total_score: float) -> str:
    """
    --------------------------------------------------------------------------
    Purpose:
        Map a /5 total to its interpretation band label.

    Inputs:
        total_score (float): the computed total.

    Outputs:
        label (str): the matching BANDS entry's label.
    --------------------------------------------------------------------------
    """
    for floor, label in BANDS:
        if total_score >= floor:
            return label
    return BANDS[-1][1]


def main(argv: list[str]) -> int:
    """
    --------------------------------------------------------------------------
    Purpose:
        CLI entry point: validate the five subscores, compute the total,
        print it with its band, and optionally write a JSON report.

    Inputs:
        argv (list[str]): command-line arguments, excluding the program name.

    Outputs:
        exit_code (int): 0 on success, 1 on invalid input or policy config.
    --------------------------------------------------------------------------
    """
    parser = argparse.ArgumentParser(description=__doc__)
    for name in NAMES:
        parser.add_argument(f"--{name}", type=float, required=True)
    parser.add_argument("--json", dest="json_path", default=None,
                        help="also write a machine-readable report to this path")
    args = parser.parse_args(argv)
    sub = {name: getattr(args, name) for name in NAMES}

    try:
        config = load_config()
    except (FileNotFoundError, ValueError) as exc:
        print(f"INVALID: {exc}")
        return 1
    allowed = set(config["subscore_values"])
    retain_threshold = config["retain_threshold"]

    try:
        t = total(sub, allowed)
    except ValueError as exc:
        print(f"INVALID: {exc}")
        return 1

    detail = ", ".join(f"{name.upper()} {fmt(sub[name])}" for name in NAMES)
    label = band(t)
    retained = t >= retain_threshold
    print(f"{fmt(t)}/5 ({detail}) - {label}"
          + ("" if retained else f"  [below retain threshold {fmt(retain_threshold)}]"))

    write_json(args.json_path, {
        "subscores": sub, "total": t, "band": label,
        "retain_threshold": retain_threshold, "retained": retained,
    })
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
