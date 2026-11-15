"""rubric_check - validates a normalized work-ugs-audit rubric (Issue 104, plan 3)."""

import argparse
import json
import re
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path

ASSESSMENT_TYPES = ("lab_report", "project_report")
ID_PATTERN = r"^I[0-9]{2}$"


class RubricError(ValueError):
    """Raised when a rubric is malformed or its points do not add up."""


def _fmt(value: Decimal) -> str:
    """
    Purpose: Format a Decimal without an exponent and without trailing zeros.
    Inputs: value (Decimal): the number to format.
    Outputs: str: an integral string for a whole number, else a plain decimal.
    """
    if value == value.to_integral_value():
        return str(int(value))
    return format(value.normalize(), "f")


def _decimal(value, where: str) -> Decimal:
    """
    Purpose: Convert a points value to Decimal from its string form.
    Inputs: value (int, float or str): the value; where (str): name used in messages.
    Outputs: Decimal: the exact value.
    Raises: RubricError: when the value is a bool, another type, or not a number.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise RubricError(f"{where} must be a number")
    try:
        return Decimal(str(value))
    except InvalidOperation as exc:
        raise RubricError(f"{where} is not a number: {value!r}") from exc


def validate(rubric: dict) -> dict:
    """
    Purpose: Check a normalized rubric and summarise its points.
    Inputs: rubric (dict): the parsed rubric.json content.
    Outputs: dict: {"items": int, "total_points": str}.
    Raises: RubricError: on a missing key, an unknown assessment type, an empty or
        malformed item list, a duplicate or malformed id, a non-positive or empty
        title, or an item sum that differs from total_points (both sums named).
    """
    if not isinstance(rubric, dict):
        raise RubricError("rubric must be an object")
    for key in ("assessment_type", "total_points", "items"):
        if key not in rubric:
            raise RubricError(f"missing key: {key}")
    if rubric["assessment_type"] not in ASSESSMENT_TYPES:
        raise RubricError(f"unknown assessment_type: {rubric['assessment_type']!r}")
    items = rubric["items"]
    if not isinstance(items, list):
        raise RubricError("items must be a list")
    if not items:
        raise RubricError("items is empty")
    seen: set[str] = set()
    total = Decimal("0")
    for item in items:
        if not isinstance(item, dict):
            raise RubricError("each item must be an object")
        item_id = item.get("id")
        if not isinstance(item_id, str) or not re.match(ID_PATTERN, item_id):
            raise RubricError(f"item id {item_id!r} must match {ID_PATTERN}")
        if item_id in seen:
            raise RubricError(f"duplicate item id {item_id}")
        seen.add(item_id)
        title = item.get("title")
        if not isinstance(title, str) or not title.strip():
            raise RubricError(f"item {item_id} title must be a non-empty string")
        if "max_points" not in item:
            raise RubricError(f"item {item_id} is missing max_points")
        max_points = _decimal(item["max_points"], f"item {item_id} max_points")
        if max_points <= 0:
            raise RubricError(f"item {item_id} max_points must be positive")
        total += max_points
    declared = _decimal(rubric["total_points"], "total_points")
    if total != declared:
        raise RubricError(f"items sum to {_fmt(total)} but total_points is {_fmt(declared)}")
    return {"items": len(items), "total_points": _fmt(declared)}


def main(argv=None) -> int:
    """
    Purpose: Validate a rubric file from the command line.
    Inputs: argv (list of str or None): arguments; the rubric path and optional --json.
    Outputs: int: 0 when valid, 2 on a refusal (unreadable file or invalid rubric).
    """
    parser = argparse.ArgumentParser(description="Validate a work-ugs-audit rubric.json.")
    parser.add_argument("rubric", help="path to rubric.json")
    parser.add_argument("--json", action="store_true", help="print the result as JSON")
    args = parser.parse_args(argv)
    try:
        rubric = json.loads(Path(args.rubric).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"error: cannot read {args.rubric}: {exc}", file=sys.stderr)
        return 2
    try:
        result = validate(rubric)
    except RubricError as exc:
        if args.json:
            print(json.dumps({"error": str(exc), "exit_code": 2}, ensure_ascii=False))
        else:
            print(f"error: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"OK: {result['items']} items, total {result['total_points']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
