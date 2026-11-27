"""grade_total - turns a rubric and one grade record into totals (Issue 104, plan 3)."""

import argparse
import json
import sys
from decimal import Decimal
from pathlib import Path

from rubric_check import RubricError, validate, _decimal, _fmt
import ugs_grade  # plan 29: the one formula of the section score, shared with the grade step (R18)
from ugs_config import default_path

STATUSES = ("rated", "not_applicable", "not_run")
VERDICTS = ("present", "partial", "absent")


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


def _recompute_item(item_id: str, entry: dict, rubric_item: dict, scale, step: Decimal) -> dict:
    """
    Purpose: Recompute the score of one rated item from its elements with the grade step's own functions (plan 29).
    Inputs: item_id (str): the item; entry (dict): its grade or hand-written entry; rubric_item (dict): the rubric item;
        scale (GradeScale) and step (Decimal): as read by ugs_grade.
    Outputs: dict: item_id, max_points, stored_score, recomputed_score (str or None), losses, and match (true, false or
        "not_recomputed" when the item is not rated, has no elements or no stored score).
    Raises: GradeError: an unknown verdict (naming the item and the element), or an element count or id set that differs
        from the rubric's elements of this item.
    """
    maximum = _decimal(rubric_item["max_points"], item_id)
    base = {"item_id": item_id, "max_points": _fmt(maximum),
            "stored_score": None if entry.get("score") is None else _fmt(_decimal(entry["score"], item_id)),
            "recomputed_score": None, "losses": [], "match": "not_recomputed"}
    elements = entry.get("elements")
    if entry.get("status") != "rated" or not elements:
        return base
    if not isinstance(elements, list) or not all(isinstance(el, dict) for el in elements):
        raise GradeError(f"item {item_id} elements must be a list of objects")
    text_of = {ref["id"]: ref.get("text", ref["id"]) for ref in rubric_item.get("elements") or []}
    prepared = []
    for element in elements:
        identifier = element.get("id")
        verdict = element.get("verdict")
        effective = element.get("effective", verdict)
        for value in (verdict, effective):
            if value not in VERDICTS:
                raise GradeError(f"item {item_id} element {identifier} has the verdict {value!r}")
        prepared.append({"id": identifier, "element": element.get("element") or text_of.get(identifier, identifier),
                         "verdict": verdict, "effective": effective, "verified": element.get("verified", True)})
    # Review round 2, finding 1: a section that lists no element (split_rubric gives []) is recomputed from its own
    # stored elements; the id check applies only where the rubric lists elements.
    if rubric_item.get("elements"):
        wanted = sorted(str(ref["id"]) for ref in rubric_item["elements"])
        given = sorted(str(el["id"]) for el in prepared)
        if given != wanted:
            raise GradeError(f"item {item_id} gives {len(given)} elements, the rubric lists {len(wanted)}: "
                             f"ids differ")
    score = ugs_grade.points_for_elements(prepared, maximum, scale, step)
    base["recomputed_score"] = _fmt(score)
    base["losses"] = ugs_grade.element_losses(prepared, maximum, scale)
    if entry.get("score") is None:
        # Review round 2, finding 8: elements but no stored score is reported as such.
        base["match"] = "no_stored_score"
        return base
    base["match"] = Decimal(str(entry["score"])) == score
    return base


def recompute(rubric: dict, grade: dict, scale, step: Decimal) -> dict:
    """
    Purpose: Recompute every section score and the final score of one grade from its elements (plan 29, owner
        2026-11-27): the section scores come from ugs_grade, the totals from compute.
    Inputs: rubric (dict): the rubric; grade (dict): a grade.json or a hand-written file of the same shape; scale and
        step: as read by ugs_grade.load_grade_scale and ugs_grade.read_grade_step.
    Outputs: dict: report_id, items (see _recompute_item), total, max_rated, percent, complete, not_run, and
        grade_recomputed (the grade with the recomputed scores and losses, for --write), exit_code (0 or 1).
    Raises: GradeError, RubricError: as compute and _recompute_item.
    """
    validate(rubric)
    if not isinstance(grade, dict) or not isinstance(grade.get("items"), list):
        raise GradeError("grade needs an items list")
    rubric_items = {item["id"]: item for item in rubric["items"]}
    entries = {entry.get("item_id"): entry for entry in grade["items"] if isinstance(entry, dict)}
    _check_ids(list(rubric_items), [entry.get("item_id") for entry in grade["items"]])
    items = [_recompute_item(item_id, entries[item_id], rubric_items[item_id], scale, step)
             for item_id in rubric_items]
    written = json.loads(json.dumps(grade))
    by_id = {entry["item_id"]: entry for entry in written["items"]}
    for item in items:
        if item["recomputed_score"] is not None:
            by_id[item["item_id"]]["score"] = float(item["recomputed_score"])
            by_id[item["item_id"]]["losses"] = item["losses"]
    totals = compute(rubric, written)
    mismatch = any(item["match"] is False for item in items)
    return {"report_id": grade["report_id"], "items": items, "total": totals["total"],
            "max_rated": totals["max_rated"], "percent": totals["percent"], "complete": totals["complete"],
            "not_run": totals["not_run"], "grade_recomputed": written, "exit_code": 1 if mismatch else 0}


def _main_recompute(args) -> int:
    """
    Purpose: Run --recompute: print the recomputed scores (JSON with --json, text otherwise) and write OUT when asked.
    Inputs: args (argparse.Namespace): rubric, grade, json, write, yes.
    Outputs: int: 0 when every stored score matches, 1 on a mismatch, 2 on a refusal (R12).
    Raises: None (refusals are returned as exit code 2).
    """
    rubric = _load(args.rubric)
    grade = _load(args.grade)
    scale = ugs_grade.load_grade_scale()
    step = ugs_grade.read_grade_step(default_path())
    result = recompute(rubric, grade, scale, step)
    if args.write:
        out, source = Path(args.write).resolve(), Path(args.grade).resolve()
        if out == source:
            raise GradeError("--write must not name the input file")
        if args.yes:
            out.write_text(json.dumps(result["grade_recomputed"], ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"written: {out}", file=sys.stderr)
        else:
            print(f"dry run: would write {out} (add --yes)", file=sys.stderr)
    shown = {key: value for key, value in result.items() if key not in ("grade_recomputed", "exit_code")}
    if args.json:
        print(json.dumps(dict(shown, items=result["items"], exit_code=result["exit_code"]), ensure_ascii=False,
                         indent=2))
    else:
        for item in result["items"]:
            print(f"{item['item_id']}: stored {item['stored_score']} recomputed {item['recomputed_score']} "
                  f"match {item['match']}")
        print(f"total {result['total']} of {result['max_rated']}")
    return result["exit_code"]


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
    parser.add_argument("--recompute", action="store_true",
                        help="recompute every section and the final score from the elements (plan 29)")
    parser.add_argument("--write", metavar="OUT", help="with --recompute: the grade with the recomputed scores")
    parser.add_argument("--yes", action="store_true", help="with --write: really write OUT (dry run without it)")
    args = parser.parse_args(argv)
    try:
        if args.write and not args.recompute:
            raise GradeError("--write needs --recompute")
        if args.recompute:
            return _main_recompute(args)
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
