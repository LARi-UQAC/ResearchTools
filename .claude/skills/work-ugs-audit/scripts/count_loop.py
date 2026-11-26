"""
count_loop.py - the count loop of the figure preparation (spec E6, plan 12 Task 2).

When the number of figures extracted from a report differs from the number declared in its list of figures,
the extraction is run again with the next setting override (a larger grouping gap joins the fragments of one
diagram), up to a bound. Every attempt is recorded. A remaining mismatch keeps the attempt closest to the
declared count and reports both numbers; no count is ever invented.
"""

from typing import Any, Callable, Dict, List, Optional, Tuple

FIGURE_TYPE = "figure"
MAX_ITERATIONS_KEY = "count_max_iterations"
GAP_STEPS_KEY = "count_gap_steps_pt"
GAP_SETTING = "group_max_gap_pt"


class CountLoopError(ValueError):
    """Raised when the count loop settings are missing or malformed (names the key)."""


def _count_figures(records: List[Dict[str, Any]]) -> int:
    """
    Purpose: Count the figure records of one extraction attempt.
    Inputs:
        records: List[Dict[str, Any]] - the element records returned by an extraction.
    Outputs:
        int - the number of records whose element_type is figure.
    Raises:
        None.
    """
    return sum(1 for record in records if record.get("element_type") == FIGURE_TYPE)


def run_count_loop(extract: Callable[[Dict[str, Any]], List[Dict[str, Any]]], declared_figures: Optional[int],
                   steps: List[Dict[str, Any]], max_iterations: int) -> Dict[str, Any]:
    """
    Purpose: Run the extraction until its figure count equals the declared count, or the bound is reached.
    Details: The first attempt uses no override. Each re-run uses the next entry of steps, at most
        max_iterations re-runs. With no declared count (not_found) the extraction runs once. On a mismatch the
        attempt whose count is closest to the declared one is kept (the earliest on a tie).
    Inputs:
        extract: Callable - takes a dict of setting overrides and returns the element records of one attempt.
        declared_figures: Optional[int] - the declared figure count, None when the list was not found.
        steps: List[Dict[str, Any]] - the override dicts of the re-runs, in order.
        max_iterations: int - the largest number of re-runs after the first attempt.
    Outputs:
        Dict[str, Any] - keys status (ok, mismatch or not_found), declared, records (of the kept attempt),
            kept_attempt (its index in attempts) and attempts (each with overrides, extracted and status).
    Raises:
        None: an extraction error is the caller's to handle.
    """
    if declared_figures is None:
        records = extract({})
        count = _count_figures(records)
        attempt = {"overrides": {}, "extracted": count, "status": "not_found"}
        return {"status": "not_found", "declared": None, "records": records, "attempts": [attempt],
                "kept_attempt": 0}

    plan: List[Dict[str, Any]] = [{}] + list(steps[:max(max_iterations, 0)])
    attempts: List[Dict[str, Any]] = []
    kept: Optional[Tuple[int, int, List[Dict[str, Any]]]] = None
    for index, overrides in enumerate(plan):
        records = extract(dict(overrides))
        count = _count_figures(records)
        distance = abs(count - declared_figures)
        status = "ok" if distance == 0 else "mismatch"
        attempts.append({"overrides": dict(overrides), "extracted": count, "status": status})
        if kept is None or distance < kept[0]:
            kept = (distance, index, records)
        if status == "ok":
            break
    return {
        "status": "ok" if kept[0] == 0 else "mismatch",
        "declared": declared_figures,
        "records": kept[2],
        "attempts": attempts,
        "kept_attempt": kept[1],
    }


def read_loop_settings(extraction_block: Dict[str, Any]) -> Tuple[int, List[Dict[str, Any]]]:
    """
    Purpose: Read the count loop settings from the extraction block of figure_criteria.json and turn the gap
        steps into override dicts.
    Inputs:
        extraction_block: Dict[str, Any] - the extraction block, each key a {value, provenance} entry.
    Outputs:
        Tuple[int, List[Dict[str, Any]]] - max_iterations and the override dict of each gap step.
    Raises:
        CountLoopError: If a key is missing, its value is not a whole number of re-runs, or a gap step is not a
            positive number. The message names the key.
    """
    for key in (MAX_ITERATIONS_KEY, GAP_STEPS_KEY):
        if key not in extraction_block:
            raise CountLoopError(f"count loop setting '{key}' is missing from the extraction block")
    max_iterations = extraction_block[MAX_ITERATIONS_KEY]["value"]
    if isinstance(max_iterations, bool) or not isinstance(max_iterations, int) or max_iterations < 0:
        raise CountLoopError(f"count loop setting '{MAX_ITERATIONS_KEY}' must be a whole number of 0 or more")
    gaps = extraction_block[GAP_STEPS_KEY]["value"]
    if not isinstance(gaps, list):
        raise CountLoopError(f"count loop setting '{GAP_STEPS_KEY}' must be a list of points")
    steps: List[Dict[str, Any]] = []
    for gap in gaps:
        if isinstance(gap, bool) or not isinstance(gap, (int, float)) or gap <= 0:
            raise CountLoopError(f"count loop setting '{GAP_STEPS_KEY}' must hold positive numbers")
        steps.append({GAP_SETTING: gap})
    return max_iterations, steps
