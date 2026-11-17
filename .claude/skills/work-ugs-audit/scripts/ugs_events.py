"""
ugs_events - the action records of a local role, for the dashboard (plan 10, task 1, R11).

A grading step reads pages, writes an output file, marks a ledger line and makes a model call. Each of those is
one record in the machine-local bridge log, so the dashboard shows the role as steps of its lane. A record holds
identifiers only: a report id, an item label, a page range, the base name of an output file and a counter.
Nothing a report says can reach a record, because a target or a detail that does not match the allow-list is
dropped, never truncated.
"""
import re
from typing import Callable, List, Optional

ACTIONS = ("read", "write", "mark", "call", "check")

# The spec's choice (spec.md R11): an item label is at most 40 characters. Not a measurement.
LABEL_MAX_CHARS = 40
# Chosen here, with no number in the spec: the longest bare output file name accepted, base name included.
FILE_NAME_MAX_CHARS = 80
# Chosen here, with no number in the spec: the longest extension accepted on an output file name.
FILE_EXTENSION_MAX_CHARS = 8

# A report-item label: letters (any alphabet), digits, space, dot, dash, underscore.
LABEL_PATTERN = r"[\w .\-]{1,%d}" % LABEL_MAX_CHARS
# A compact 1-based page range: p12-15, p3-5,9 (see page_range).
PAGE_RANGE_PATTERN = r"p[0-9]+(?:-[0-9]+)?(?:,[0-9]+(?:-[0-9]+)?)*"
# A bare output file name: no separator, no drive colon.
FILE_NAME_PATTERN = r"[\w .\-]{1,%d}\.[A-Za-z0-9]{1,%d}" % (FILE_NAME_MAX_CHARS, FILE_EXTENSION_MAX_CHARS)

_ALLOWED_RE = (
    re.compile(LABEL_PATTERN),
    re.compile(PAGE_RANGE_PATTERN),
    re.compile(FILE_NAME_PATTERN),
)


def _is_allowed(value: str) -> bool:
    """
    Purpose: Decide whether a target or a detail is one of the three identifier shapes of the allow-list.
    Details: Full match only, so a value with a separator, a colon, a newline or a leading or trailing
        character outside the shape is refused rather than cut.
    Inputs:
        value (str): the candidate target or detail.
    Outputs:
        bool: True when the value matches a label, a page range or a bare output file name.
    Raises:
        None.
    """
    if not isinstance(value, str):
        return False
    return any(pattern.fullmatch(value) for pattern in _ALLOWED_RE)


def action_record(
    role: str,
    action: str,
    target: str,
    now: str,
    report_id: Optional[str] = None,
    detail: Optional[str] = None,
) -> Optional[dict]:
    """
    Purpose: Build one action record for the bridge log, or refuse it.
    Details: The record carries no text of a report. A target or a detail outside the allow-list makes the
        whole record None, and the caller counts it as not written.
    Inputs:
        role (str): the local role that acted, for example the grader role name.
        action (str): one of ACTIONS.
        target (str): an item label, a page range or a bare output file name.
        now (str): the clock stamp of the record.
        report_id (str or None): the identifier of the report, never its name.
        detail (str or None): an optional allow-listed detail, for example a ledger mark. None is allowed.
    Outputs:
        dict or None: {"event", "at", "role", "action", "target", "report_id", "detail"}, or None when the
        action is unknown or the target or the detail fails the allow-list.
    Raises:
        None.
    """
    if action not in ACTIONS:
        return None
    if not _is_allowed(target):
        return None
    if detail is not None and not _is_allowed(detail):
        return None
    return {
        "event": "action",
        "at": now,
        "role": role,
        "action": action,
        "target": target,
        "report_id": report_id,
        "detail": detail,
    }


def page_range(numbers: List[int]) -> str:
    """
    Purpose: Write a list of 1-based page numbers as one compact range, so a long selection is one record.
    Details: Duplicates and unsorted input are handled. Consecutive numbers join into a run, and runs are
        separated by commas, for example [3, 4, 5, 9] gives "p3-5,9".
    Inputs:
        numbers (list of int): page numbers, each at least 1. An empty list is allowed.
    Outputs:
        str: the compact range, or "" for an empty list.
    Raises:
        ValueError: when a number is not an int, is a bool, or is below 1.
    """
    cleaned = set()
    for number in numbers:
        if isinstance(number, bool) or not isinstance(number, int):
            raise ValueError(f"page numbers must be integers, got {type(number).__name__}")
        if number < 1:
            raise ValueError(f"page numbers are 1-based, got {number}")
        cleaned.add(number)
    if not cleaned:
        return ""
    ordered = sorted(cleaned)
    runs = []
    start = previous = ordered[0]
    for number in ordered[1:]:
        if number == previous + 1:
            previous = number
            continue
        runs.append((start, previous))
        start = previous = number
    runs.append((start, previous))
    parts = [f"{first}" if first == last else f"{first}-{last}" for first, last in runs]
    return "p" + ",".join(parts)


def make_emitter(
    log: Callable[[dict], None],
    role_for: Callable[[], str],
    clock: Callable[[], str],
) -> Callable[..., None]:
    """
    Purpose: Build the emit function a grading step calls to record one action, which never raises.
    Details: A record refused by action_record is counted in neither the log nor the lost counter. A failure of
        the log, of role_for or of clock is counted in `lost` and the step goes on, so a broken log never stops
        a grading run. The count is exposed as the attribute `lost` of the returned function.
    Inputs:
        log (callable): receives each accepted record dict; may raise.
        role_for (callable): returns the role name of the acting step at the time of the call.
        clock (callable): returns the stamp of the record at the time of the call.
    Outputs:
        callable: emit(action, target, report_id=None, detail=None) -> None, with attribute lost (int, starts at 0).
    Raises:
        None: the returned function never raises.
    """

    def emit(action: str, target: str, report_id: Optional[str] = None, detail: Optional[str] = None) -> None:
        """
        Purpose: Record one action through the log of this emitter.
        Inputs:
            action (str): one of ACTIONS.
            target (str): an item label, a page range or a bare output file name.
            report_id (str or None): the identifier of the report.
            detail (str or None): an optional allow-listed detail.
        Outputs:
            None. Increments emit.lost on a failure of the log, role_for or clock.
        Raises:
            None.
        """
        try:
            record = action_record(role_for(), action, target, clock(), report_id, detail)
        except Exception:  # noqa: BLE001 - the emitter never stops a grading step
            emit.lost += 1
            return
        if record is None:
            return
        try:
            log(record)
        except Exception:  # noqa: BLE001 - a broken log is counted, never raised
            emit.lost += 1

    emit.lost = 0
    return emit
