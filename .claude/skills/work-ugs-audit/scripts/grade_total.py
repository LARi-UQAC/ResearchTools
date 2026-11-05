"""grade_total - turns a rubric and one grade record into totals (Issue 104, plan 3)."""

import argparse
import json
import sys
from decimal import Decimal
from pathlib import Path

from rubric_check import RubricError, validate, _decimal, _fmt

STATUSES = ("rated", "not_applicable", "not_run")


class GradeError(ValueError):
    """Raised when a grade record does not match its rubric or holds an invalid score."""


def _load(path: str) -> dict:
    """
    Purpose: Read one JSON file as UTF-8.
    Inputs: path (str): the file to read.
    Outputs: dict: the parsed content.
    Raises: GradeError: when the file cannot be read or is not valid JSON.
    """
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise GradeError(f"cannot read {path}: {exc}") from exc


def _check_ids(rubric_ids: list, grade_ids: list) -> None:
    """
    Purpose: Refuse a grade whose item ids differ from the rubric's.
    Inputs: rubric_ids (list): ids of the rubric; grade_ids (list): ids of the grade.
    Outputs: None.
    Raises: GradeError: on a duplicate grade id, or any missing or extra id (both listed).
    """
    duplicates = sorted({item_id for item_id in grade_ids if grade_ids.count(item_id) > 1}, key=str)
    if duplicates:
        raise GradeError(f"grade lists an item_id more than once: {duplicates}")
    missing = sorted(set(rubric_ids) - set(grade_ids))
    extra = sorted(set(grade_ids) - set(rubric_ids))
    if missing or extra:
        raise GradeError(f"item ids differ from the rubric: missing {missing}, extra {extra}")


def _score_of(item_id: str, entry: dict, max_points: Decimal) -> Decimal | None:
    """
    Purpose: Check one grade entry's status and score against its maximum.
    Inputs: item_id (str): the item; entry (dict): its grade entry; max_points (Decimal): its maximum.
    Outputs: Decimal or None: the score for a rated item, None otherwise.
    Raises: GradeError: on an unknown status, a missing or out-of-range score, or a score
        given for a not_run or not_applicable item.
    """
    status = entry.get("status")
    if status not in STATUSES:
        raise GradeError(f"item {item_id} has unknown status {status!r}")
    score = entry.get("score")
    if status != "rated":
        if score is not None:
            raise GradeError(f"item {item_id} is {status} and must carry no score")
        return None
    if score is None:
        raise GradeError(f"item {item_id} is rated and needs a score")
    try:
        value = _decimal(score, f"item {item_id} score")
    except RubricError as exc:
        raise GradeError(str(exc)) from exc
    if value < 0 or value > max_points:
        raise GradeError(f"item {item_id} score {_fmt(value)} is outside 0 to {_fmt(max_points)}")
    return value


def compute(rubric: dict, grade: dict) -> dict:
    """
    Purpose: Compute the total, the maximum and the percentage of one graded report.
    Inputs: rubric (dict): the rubric, validated first; grade (dict): one grade.json record.
    Outputs: dict: report_id, total (str or None), max_rated (str), percent (float or None),
        by_item, not_run (list of ids) and complete (bool). A not_run item makes total and
        percent None; an undefined percentage (nothing rated) is None, never a division.
    Raises: RubricError: when the rubric is invalid. GradeError: on any grade defect.
    """
    validate(rubric)
    if not isinstance(grade, dict) or not isinstance(grade.get("report_id"), str) or not grade["report_id"]:
        raise GradeError("grade needs a non-empty report_id")
    if not isinstance(grade.get("items"), list):
        raise GradeError("grade needs an items list")
    maxima = {item["id"]: _decimal(item["max_points"], item["id"]) for item in rubric["items"]}
    order = [item["id"] for item in rubric["items"]]
    entries = {}
    for entry in grade["items"]:
        if not isinstance(entry, dict):
            raise GradeError("each grade item must be an object")
        entries[entry.get("item_id")] = entry
    _check_ids(order, [entry.get("item_id") for entry in grade["items"]])
    by_item = {}
    not_run = []
    total = Decimal("0")
    max_rated = Decimal("0")
    for item_id in order:
        entry = entries[item_id]
        score = _score_of(item_id, entry, maxima[item_id])
        status = entry["status"]
        if status == "not_run":
            not_run.append(item_id)
        if status == "rated":
            total += score
            max_rated += maxima[item_id]
        by_item[item_id] = {
            "status": status,
            "score": None if score is None else _fmt(score),
            "max": _fmt(maxima[item_id]),
        }
    complete = not not_run
    if not complete:
        total_out, percent = None, None
    else:
        total_out = _fmt(total)
        percent = None if max_rated == 0 else float((total * 100 / max_rated).quantize(Decimal("0.01")))
    return {
        "report_id": grade["report_id"],
        "total": total_out,
        "max_rated": _fmt(max_rated),
        "percent": percent,
        "by_item": by_item,
        "not_run": not_run,
        "complete": complete,
    }


def main(argv=None) -> int:
    """
    Purpose: Compute the totals of one grade from the command line.
    Inputs: argv (list of str or None): the rubric path, the grade path and an optional --json.
    Outputs: int: 0 on success, 2 on a refusal (unreadable file, invalid rubric or grade).
    """
    parser = argparse.ArgumentParser(description="Compute the totals of one graded report.")
    parser.add_argument("rubric", help="path to rubric.json")
    parser.add_argument("grade", help="path to grade.json")
    parser.add_argument("--json", action="store_true", help="print the result as JSON")
    args = parser.parse_args(argv)
    try:
        result = compute(_load(args.rubric), _load(args.grade))
    except (GradeError, RubricError) as exc:
        if args.json:
            print(json.dumps({"error": str(exc), "exit_code": 2}, ensure_ascii=False))
        else:
            print(f"error: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif result["complete"]:
        print(f"report {result['report_id']}: total {result['total']} of {result['max_rated']}")
    else:
        print(f"report {result['report_id']}: incomplete, not run: {', '.join(result['not_run'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
