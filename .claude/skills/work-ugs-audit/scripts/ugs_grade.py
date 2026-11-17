"""
Purpose: Grade rubric items using local models.
"""

import math
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

# Add loop-engineer and its scripts to path
_LOOP_ENGINEER_ROOT = Path(__file__).resolve().parent.parent.parent / "loop-engineer"
_LOOP_ENGINEER_SCRIPTS = _LOOP_ENGINEER_ROOT / "scripts"
for _p in (_LOOP_ENGINEER_SCRIPTS, _LOOP_ENGINEER_ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from ugs_text import StepContext, fill, page_blocks, select_pages
from ugs_events import page_range
from ugs_bridge import NotRun
from rubric_split import item_prompt_text
from rubric_check import validate, RubricError
from pdf_annotate import normalize

# The one table of validation codes (R5). A code is snake_case, at most 30 characters, never report text.
GRADE_CODES = (
    "ok",
    "quote_not_found",
    "evidence_missing",
    "evidence_incomplete",
    "evidence_page_out_of_range",
    "score_above_max",
    "score_negative",
    "score_missing",
    "unknown_status",
    "not_applicable_with_score",
    "unparsable_answer",
    "schema_invalid",
    "no_fit",
    "over_budget",
)

# A refused proof keeps the score the model gave: the number is usable, only the evidence is not.
PROOF_REFUSAL_CODES = (
    "quote_not_found",
    "evidence_missing",
    "evidence_incomplete",
    "evidence_page_out_of_range",
)

# The bridge's retryable refusals carry no answer at all; each maps to the code the record reports.
NO_ANSWER_CODES = {
    "unparsable": "unparsable_answer",
    "invalid": "schema_invalid",
}

# Longest `missing` kept in a grade record, in characters. Provenance: chosen, not measured. grade_item.md asks
# for one sentence, and this bound only stops a model that ignores that from filling grade.json. A bound on the
# text of one saved field, never on what the model is shown, so the professor may raise it without re-measuring.
MISSING_MAX_CHARS = 300


def normalize_rubric(
    rubric_text: str,
    assessment_type: str,
    call: Callable,
    ctx: StepContext
) -> dict:
    """
    Purpose: Normalize rubric text into a structured rubric dict.
    Inputs:
        rubric_text: str - The text of the rubric.
        assessment_type: str - The type of assessment.
        call: Callable - The model call function.
        ctx: StepContext - The context for the step.
    Outputs:
        dict - The normalized rubric.
    Raises:
        NotRun: If the model fails or returns invalid data after retries.
    """
    prompt_template = ctx.prompts["rubric_normalize"]
    schema = ctx.schemas["rubric"]

    last_error = None
    for attempt in range(ctx.grade_retries + 1):
        prompt = fill(prompt_template, {
            "RUBRIC_TEXT": rubric_text,
            "ASSESSMENT_TYPE": assessment_type
        })

        try:
            answer = call(prompt, schema)
            # Validate answer
            validate(answer)
            return answer
        except NotRun as e:
            if not e.retryable:
                raise
            last_error = e
        except (RubricError, Exception) as e:
            # Treat validation errors as retryable invalid answers
            last_error = NotRun("invalid", str(e))

    raise last_error


def _is_number(value: Any) -> bool:
    """
    Purpose: Tell a usable number from anything else, a boolean included.
    Inputs:
        value: Any - The value to test.
    Outputs:
        bool - True for an int or a float that is not a boolean.
    """
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _is_page_number(value: Any) -> bool:
    """
    Purpose: Tell a usable page number from anything else, a boolean included.
    Inputs:
        value: Any - The value to test.
    Outputs:
        bool - True for an int that is not a boolean.
    """
    return isinstance(value, int) and not isinstance(value, bool)


def check_grade_answer(
    answer: dict,
    item: dict,
    pages: List[str]
) -> Tuple[str, str]:
    """
    Purpose: Check one model answer against its rubric item and the page texts, and name the first defect.
    Details: The codes are the table GRADE_CODES. A refused proof (a quote not on its page, missing or
        incomplete evidence, a page out of range) is a defect of the evidence only; the score it carries is
        still reported by the caller. The message names a page number, a score or a count, never a quote.
    Inputs:
        answer: dict - The model's answer, as given.
        item: dict - The rubric item, with its max_points.
        pages: List[str] - The page texts of the report.
    Outputs:
        Tuple[str, str] - The code, and a short message: "ok" with an empty message on success.
    """
    status = answer.get("status")
    score = answer.get("score")
    evidence = answer.get("evidence")
    if evidence is None:
        evidence = []

    if status not in ("rated", "not_applicable"):
        return "unknown_status", "status must be rated or not_applicable"
    if score is not None and not _is_number(score):
        return "schema_invalid", "score is not a number"
    # json.loads accepts NaN and Infinity, and NaN passes every range test below: refuse it before them.
    if isinstance(score, float) and not math.isfinite(score):
        return "score_missing", "score is not a finite number"
    # The evidence has one shape at every score, a full one included: a string is refused before any score test.
    if not isinstance(evidence, list):
        return "schema_invalid", "evidence must be a list"

    if status == "not_applicable":
        if score is not None:
            return "not_applicable_with_score", "not_applicable must have a null score"
        return "ok", ""

    max_points = item.get("max_points", 0)
    if score is None:
        return "score_missing", "rated must have a score"
    if score < 0:
        return "score_negative", "score must be non-negative"
    if score > max_points:
        return "score_above_max", f"score {score} is above the maximum {max_points}"

    # Every evidence entry is checked for its page, at the maximum score too: the audit reads these pages.
    for entry in evidence:
        if not isinstance(entry, dict) or not _is_page_number(entry.get("page")):
            return "evidence_incomplete", "evidence entry needs an integer page number"

    if score < max_points:
        if not evidence:
            return "evidence_missing", "score below the maximum needs evidence"
        for entry in evidence:
            if not isinstance(entry, dict):
                return "evidence_incomplete", "evidence entry is not an object"
            page_num = entry.get("page")
            quote = entry.get("quote")
            if not _is_page_number(page_num) or not isinstance(quote, str) or not normalize(quote).strip():
                return "evidence_incomplete", "evidence entry needs a page number and a quote"
            if page_num < 1 or page_num > len(pages):
                return "evidence_page_out_of_range", f"evidence page {page_num} is out of range"
            if normalize(quote) not in normalize(pages[page_num - 1]):
                return "quote_not_found", f"quote not found on page {page_num}"

    return "ok", ""


def _validate_grade_answer(
    answer: dict,
    item: dict,
    pages: List[str]
) -> Optional[str]:
    """
    Purpose: Give the message of the check of one answer, or None when it passes.
    Inputs:
        answer: dict - The model's answer.
        item: dict - The rubric item.
        pages: List[str] - The page texts.
    Outputs:
        Optional[str] - None if valid, else the message of check_grade_answer.
    """
    code, message = check_grade_answer(answer, item, pages)
    return None if code == "ok" else message


def _missing_text(answer: dict, raw_score: Any, max_points: Any) -> str:
    """
    Purpose: Give the `missing` value of a grade record: the element that cost the points, or "".
    Details: Empty at the maximum score, when the answer has no `missing`, or when it is not a string. Otherwise
        the text is kept as the model gave it, stripped and cut to MISSING_MAX_CHARS. It is model text saved in
        grade.json only: it never reaches the ledger note, a log or the dashboard (see ugs_run._grade_mark).
    Inputs:
        answer: dict - The model's answer, as given.
        raw_score: Any - The score the model gave, None when there is none.
        max_points: Any - The maximum of the rubric item.
    Outputs:
        str - The missing text, possibly empty.
    """
    if _is_number(raw_score) and raw_score == max_points:
        return ""
    value = answer.get("missing")
    if not isinstance(value, str):
        return ""
    return value.strip()[:MISSING_MAX_CHARS]


def _record_from_answer(
    item_id: str,
    answer: dict,
    code: str,
    attempts: int,
    max_points: Any
) -> dict:
    """
    Purpose: Build the grade record of an answer the model gave, with its validation code.
    Details: A success keeps the status and the score as given. A refused proof keeps status rated and the score.
        Any other refusal drops the score (status not_run, score null) and keeps the raw value in model_score.
        The model comment, the evidence and the missing element are kept as given in every case (missing is
        emptied at the maximum score, see _missing_text). The key order is the saved order of grade.json.
    Inputs:
        item_id: str - The rubric item identifier.
        answer: dict - The model's answer, as given.
        code: str - The code of check_grade_answer, "ok" for a success.
        attempts: int - The number of model calls made, this one included.
        max_points: Any - The maximum of the rubric item.
    Outputs:
        dict - The grade record, flagged unless the code is "ok".
    """
    raw_score = answer.get("score")
    evidence = answer.get("evidence")
    if code == "ok":
        status = answer.get("status")
        score = raw_score
    elif code in PROOF_REFUSAL_CODES:
        status = "rated"
        score = raw_score
    else:
        status = "not_run"
        score = None
    return {
        "item_id": item_id,
        "status": status,
        "score": score,
        "comment": answer.get("comment", ""),
        "evidence": [] if evidence is None else evidence,
        "missing": _missing_text(answer, raw_score, max_points),
        "audit": "not_run",
        "flag": code != "ok",
        "model_score": raw_score,
        "validation": code,
        "attempts": attempts,
    }


def _no_answer_record(
    item_id: str,
    code: str,
    attempts: int,
    comment: str
) -> dict:
    """
    Purpose: Build the grade record of an item the model gave no usable answer for.
    Inputs:
        item_id: str - The rubric item identifier.
        code: str - The validation code of the refusal (no_fit, over_budget, unparsable_answer, schema_invalid).
        attempts: int - The number of model calls made, the refused one included.
        comment: str - The comment of the record: the refusal name for no_fit or over_budget, "" otherwise.
    Outputs:
        dict - The grade record, status not_run, score and model_score null, missing empty, flagged.
    """
    return {
        "item_id": item_id,
        "status": "not_run",
        "score": None,
        "comment": comment,
        "evidence": [],
        "missing": "",
        "audit": "not_run",
        "flag": True,
        "model_score": None,
        "validation": code,
        "attempts": attempts,
    }


def grade_item(
    item: dict,
    pages: List[str],
    call: Callable,
    ctx: StepContext,
    language: str,
    calibration_note: str,
    report_id: Optional[str] = None
) -> dict:
    """
    Purpose: Grade a single rubric item.
    Details: When ctx.emit is set, one `read` record gives the page range selected and one `call` record each
        model call, both with identifiers only (R11). With no emitter nothing is recorded.
        After the last attempt the record is built from the last answer the model gave, with its validation
        code (plan 12, R12). A refused attempt is retried with its reason; a retry that fails with no answer
        at all leaves no score.
    Inputs:
        item: dict - The rubric item.
        pages: List[str] - The page texts.
        call: Callable - The model call function.
        ctx: StepContext - The context for the step.
        language: str - The language of the report.
        calibration_note: str - The current calibration note.
        report_id: str or None - The identifier of the report, for the action records only.
    Outputs:
        dict - The grade record: item_id, status, score, comment, evidence, missing, audit, flag, then model_score,
            validation and attempts.
    Raises:
        NotRun: If the model fails with an unretryable error (an unreachable daemon, for example).
    """
    item_id = item["id"]

    # Determine pages to send
    budget_tokens = ctx.window_tokens - ctx.reserve_tokens

    # Estimate overhead: token count of filled prompt with empty sections
    prompt_template = ctx.prompts["grade_item"]
    overhead_prompt = fill(prompt_template, {
        "ITEM": item_prompt_text(item),
        "SECTIONS": "",
        "LEVELS": str(ctx.levels),
        "LANGUAGE_OF_REPORT": language,
        "CALIBRATION_NOTE": calibration_note
    })
    overhead = ctx.count(overhead_prompt)

    effective_budget = budget_tokens - overhead

    all_blocks = page_blocks(pages, list(range(1, len(pages) + 1)))
    if ctx.count(all_blocks) <= effective_budget:
        selected_pages = list(range(1, len(pages) + 1))
        sections_text = all_blocks
    else:
        selected_pages = select_pages(item, pages, effective_budget, ctx.count, ctx.min_word_len)
        if not selected_pages:
            return _no_answer_record(item_id, "no_fit", 0, "no_fit")
        sections_text = page_blocks(pages, selected_pages)

    if ctx.emit is not None:
        ctx.emit("read", page_range(selected_pages), report_id=report_id)
    schema = ctx.schemas["grade_item"]

    last_error_reason = None
    code = "schema_invalid"
    last_answer = None
    for attempt in range(ctx.grade_retries + 1):
        current_note = calibration_note
        if last_error_reason:
            current_note = f"{calibration_note}\nPrevious refusal: {last_error_reason}" if calibration_note else f"Previous refusal: {last_error_reason}"

        prompt = fill(prompt_template, {
            "ITEM": item_prompt_text(item),
            "SECTIONS": sections_text,
            "LEVELS": str(ctx.levels),
            "LANGUAGE_OF_REPORT": language,
            "CALIBRATION_NOTE": current_note
        })

        if ctx.emit is not None:
            ctx.emit("call", item_id, report_id=report_id)
        try:
            answer = call(prompt, schema)
        except NotRun as e:
            if e.kind == "over_budget":
                return _no_answer_record(item_id, "over_budget", attempt + 1, "over_budget")
            if not e.retryable:
                raise
            last_error_reason = e.reason
            code = NO_ANSWER_CODES.get(e.kind, "schema_invalid")
            last_answer = None
            continue

        code, message = check_grade_answer(answer, item, pages)
        if code == "ok":
            return _record_from_answer(item_id, answer, "ok", attempt + 1, item.get("max_points", 0))
        last_error_reason = message
        last_answer = answer

    attempts = ctx.grade_retries + 1
    if last_answer is None:
        return _no_answer_record(item_id, code, attempts, "")
    return _record_from_answer(item_id, last_answer, code, attempts, item.get("max_points", 0))


def grade_report(
    rubric: dict,
    pages: List[str],
    report_id: str,
    loop: int,
    call: Callable,
    ctx: StepContext,
    language: str,
    calibration_note: str,
    existing: Optional[dict] = None,
    on_item: Optional[Callable] = None
) -> dict:
    """
    Purpose: Grade all items in a rubric.
    Inputs:
        rubric: dict - The rubric.
        pages: List[str] - The page texts.
        report_id: str - The report ID.
        loop: int - The loop number.
        call: Callable - The model call function.
        ctx: StepContext - The context for the step.
        language: str - The language of the report.
        calibration_note: str - The current calibration note.
        existing: Optional[dict] - Existing grade records to skip.
        on_item: Optional[Callable] - Callback for each new item.
    Outputs:
        dict - The full grade report.
    """
    items_to_grade = []
    existing_items = {}
    if existing and "items" in existing:
        for item in existing["items"]:
            existing_items[item["item_id"]] = item

    for item in rubric["items"]:
        item_id = item["id"]
        if item_id in existing_items:
            items_to_grade.append(existing_items[item_id])
        else:
            record = grade_item(
                item, pages, call, ctx, language, calibration_note, report_id
            )
            items_to_grade.append(record)
            if on_item:
                on_item(item_id, record)

    return {
        "report_id": report_id,
        "loop": loop,
        "items": items_to_grade
    }
