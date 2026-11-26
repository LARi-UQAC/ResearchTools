"""
Purpose: Grade rubric items using local models.
"""

import json
import math
import sys
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

# Add loop-engineer and its scripts to path
_LOOP_ENGINEER_ROOT = Path(__file__).resolve().parent.parent.parent / "loop-engineer"
_LOOP_ENGINEER_SCRIPTS = _LOOP_ENGINEER_ROOT / "scripts"
for _p in (_LOOP_ENGINEER_SCRIPTS, _LOOP_ENGINEER_ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from ugs_text import StepContext, fill, page_blocks, prompt_section, select_pages
from ugs_events import page_range
from ugs_bridge import NotRun
from ugs_config import default_path
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
    "unknown_level",
    "score_negative",
    "score_missing",
    "unknown_status",
    "not_applicable_with_score",
    "unparsable_answer",
    "schema_invalid",
    "no_fit",
    "over_budget",
    "timeout",
    "not_applicable_not_allowed",
)

# The refusals asked again with a template of the prompts folder (plan 22 task 2, R01 case 4): the maximum is named,
# in the report language, from retry_grade_item.md. Each code names its section of that file.
RETRY_SECTION_BY_CODE = {
    "score_above_max": "score",
    "not_applicable_not_allowed": "not_applicable",
}

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
    "timeout": "timeout",
}

# Plan 25 Task 1: the grader names a level from grade_levels.json; the code computes the points. The file holds the
# fractions, so no prompt carries a number the model could copy as a score.
GRADE_LEVELS_FILE = Path(__file__).resolve().parent.parent / "assets" / "grade_levels.json"
GRADE_STEP_KEY = "grade.score_step"


def load_grade_levels(path: Path = GRADE_LEVELS_FILE) -> Dict[str, Decimal]:
    """
    Purpose: Read the level names and their fractions of the maximum from grade_levels.json (plan 25, Task 1).
    Inputs:
        path: Path - The levels file, the shipped one by default.
    Outputs:
        Dict[str, Decimal] - Each level name with its fraction, exact.
    Raises:
        ValueError: If the file is unreadable, has no levels, or a fraction is not a number from 0 to 1 (R3).
    """
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read {path}: {exc}") from exc
    levels = raw.get("levels") if isinstance(raw, dict) else None
    if not isinstance(levels, dict) or not levels:
        raise ValueError(f"no 'levels' object in {path}")
    result: Dict[str, Decimal] = {}
    for name, entry in levels.items():
        fraction = entry.get("fraction") if isinstance(entry, dict) else None
        if isinstance(fraction, bool) or not isinstance(fraction, (int, float)) or not 0 <= fraction <= 1:
            raise ValueError(f"level '{name}' needs a fraction from 0 to 1 in {path}")
        result[name] = Decimal(str(fraction))
    return result


def read_grade_step(path: Path) -> Decimal:
    """
    Purpose: Read the rounding step of the points from the configuration (plan 25, Task 1).
    Inputs:
        path: Path - The configuration JSON, normally ugs_config.default_path().
    Outputs:
        Decimal - The step in points, exact and positive.
    Raises:
        ValueError: If the file is unreadable, the key is absent or the value is not a positive number (R3).
    """
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read {path}: {exc}") from exc
    entry = raw.get(GRADE_STEP_KEY) if isinstance(raw, dict) else None
    if not isinstance(entry, dict) or "value" not in entry:
        raise ValueError(f"missing key '{GRADE_STEP_KEY}' in {path}")
    value = entry["value"]
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        raise ValueError(f"'{GRADE_STEP_KEY}' must be a positive number in {path}")
    return Decimal(str(value))


def points_for_level(level: str, max_points: Any, levels: Dict[str, Decimal], step: Decimal) -> float:
    """
    Purpose: Give the points of a level: its fraction times the maximum, rounded to the nearest multiple of the step,
        a tie going up (plan 25, Task 1). 0.88 of 0.5 is 0.44, rounded to 0.5; 0.88 of 10 is 8.8, rounded to 8.75.
    Inputs:
        level: str - A key of levels.
        max_points: Any - The maximum of the item, a number.
        levels: Dict[str, Decimal] - The fractions, from load_grade_levels.
        step: Decimal - The rounding step, from read_grade_step.
    Outputs:
        float - The points, never above the maximum.
    Raises:
        KeyError: If the level is not in levels (the caller refuses it first as unknown_level).
    """
    value = levels[level] * Decimal(str(max_points))
    units = (value / step).to_integral_value(rounding=ROUND_HALF_UP)
    return float(units * step)


def with_level_score(answer: dict, item: dict, levels: Dict[str, Decimal], step: Decimal) -> dict:
    """
    Purpose: Give a copy of a rated answer with the points of its level in score, so the score checks and the record
        work on the computed number (plan 25, Task 1). An answer with no known level is returned unchanged and is
        refused by check_grade_answer as unknown_level.
    Inputs:
        answer: dict - The model's answer.
        item: dict - The rubric item; its max_points is used.
        levels: Dict[str, Decimal] - The fractions.
        step: Decimal - The rounding step.
    Outputs:
        dict - The answer, with its score computed when its level is known.
    Raises:
        None.
    """
    if answer.get("status") != "rated" or answer.get("level") not in levels:
        return answer
    computed = dict(answer)
    computed["score"] = points_for_level(answer["level"], item.get("max_points", 0), levels, step)
    return computed


# The configuration key of the longest `missing` kept in a grade record (D2). Its value and provenance live in
# assets/ugs_config.json; the code holds no literal for it.
MISSING_MAX_CHARS_KEY = "grade.missing_max_chars"


def read_missing_max_chars(path: Path) -> int:
    """
    Purpose: Read the character limit of the missing-element text from the configuration file (D2).
    Details: The file is read on its own, not through ugs_config.load, which demands its whole key set. A
        missing key, a missing entry or a value that is not a positive integer is a named error.
    Inputs:
        path: Path - The configuration JSON file, normally ugs_config.default_path().
    Outputs:
        int - The limit in characters.
    Raises:
        ValueError: If the file is unreadable, the key is absent or its value is not a positive integer (R3).
    """
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read {path}: {exc}") from exc
    entry = raw.get(MISSING_MAX_CHARS_KEY) if isinstance(raw, dict) else None
    if not isinstance(entry, dict) or "value" not in entry:
        raise ValueError(f"missing key '{MISSING_MAX_CHARS_KEY}' in {path}")
    value = entry["value"]
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"'{MISSING_MAX_CHARS_KEY}' must be a positive integer in {path}")
    return value


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
    if status == "rated" and answer.get("level") not in load_grade_levels():
        return "unknown_level", "level must be one of the levels of grade_levels.json"
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
        if not item.get("optional"):
            return "not_applicable_not_allowed", "not_applicable is allowed only for an optional item"
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


def _missing_text(answer: dict, raw_score: Any, max_points: Any, max_chars: int) -> str:
    """
    Purpose: Give the `missing` value of a grade record: the element that cost the points, or "".
    Details: Empty at the maximum score, when the answer has no `missing`, or when it is not a string. Otherwise
        the text is kept as the model gave it, stripped and cut to max_chars. It is model text saved in
        grade.json only: it never reaches the ledger note, a log or the dashboard (see ugs_run._grade_mark).
    Inputs:
        answer: dict - The model's answer, as given.
        raw_score: Any - The score the model gave, None when there is none.
        max_points: Any - The maximum of the rubric item.
        max_chars: int - The character limit, from grade.missing_max_chars (D2).
    Outputs:
        str - The missing text, possibly empty.
    """
    if _is_number(raw_score) and raw_score == max_points:
        return ""
    value = answer.get("missing")
    if not isinstance(value, str):
        return ""
    return value.strip()[:max_chars]


def _strict_score(raw: Any) -> Tuple[Any, Optional[str]]:
    """
    Purpose: Split the score the model gave into a strict-JSON value and its raw text, for grade.json (D1).
    Details: json.dumps writes NaN and Infinity as literals that no strict JSON reader accepts. A non-finite
        float therefore becomes null, and its text ("nan", "inf", "-inf") is kept beside it in model_score_raw.
    Inputs:
        raw: Any - The score as the model gave it, possibly None.
    Outputs:
        Tuple[Any, Optional[str]] - (model_score, model_score_raw); the second is None unless the score was
            a non-finite float.
    """
    if isinstance(raw, float) and not math.isfinite(raw):
        return None, str(raw)
    return raw, None


def _record_from_answer(
    item_id: str,
    answer: dict,
    code: str,
    attempts: int,
    max_points: Any,
    missing_max_chars: Optional[int] = None
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
        missing_max_chars: Optional[int] - The limit of the missing text; None reads it from the configuration.
    Outputs:
        dict - The grade record, flagged unless the code is "ok".
    """
    if missing_max_chars is None:
        missing_max_chars = read_missing_max_chars(default_path())
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
    level = answer.get("level")  # plan 25: model_score keeps the level name the model chose, the score is computed
    model_score, model_score_raw = _strict_score(level if isinstance(level, str) else raw_score)
    record = {
        "item_id": item_id,
        "status": status,
        "score": score,
        "comment": answer.get("comment", ""),
        "evidence": [] if evidence is None else evidence,
        "missing": _missing_text(answer, raw_score, max_points, missing_max_chars),
        "audit": "not_run",
        "flag": code != "ok",
        "model_score": model_score,
        "validation": code,
        "attempts": attempts,
    }
    if model_score_raw is not None:
        record["model_score_raw"] = model_score_raw
    return record


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


def _retry_note(ctx: StepContext, code: str, item: dict, answer: dict, language: str) -> str:
    """
    --------------------------------------------------------------------------
    Purpose:
        Build the note that asks the model again after a score above the maximum, or a not_applicable on a required
        item. The wording lives in the retry_grade_item prompt file, never in code (R6).

    Inputs:
        ctx (StepContext): the step context; its prompts hold retry_grade_item.
        code (str): the refusal code, a key of RETRY_SECTION_BY_CODE.
        item (dict): the rubric item, its max_points is named in the note.
        answer (dict): the refused answer, its score is named in the note.
        language (str): the report language, fr or en; it selects the section.

    Outputs:
        str: the note, stripped.

    Raises:
        PromptError: when the template or its section for this language is missing (R3).
    --------------------------------------------------------------------------
    """
    section = RETRY_SECTION_BY_CODE[code]
    template = prompt_section(ctx.prompts["retry_grade_item"], f"{language}_{section}")
    values = {"MAX": str(item.get("max_points", 0))}
    if section == "score":  # the not_applicable template has no SCORE slot, and fill refuses a value with no slot
        values["SCORE"] = str(answer.get("score"))
    return fill(template, values).strip()


def grade_item(
    item: dict,
    pages: List[str],
    call: Callable,
    ctx: StepContext,
    language: str,
    calibration_note: str,
    report_id: Optional[str] = None,
    missing_max_chars: Optional[int] = None
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
        missing_max_chars: int or None - The limit of the missing text; None reads grade.missing_max_chars once.
    Outputs:
        dict - The grade record: item_id, status, score, comment, evidence, missing, audit, flag, then model_score,
            validation and attempts.
    Raises:
        NotRun: If the model fails with an unretryable error (an unreachable daemon, for example).
    """
    item_id = item["id"]
    if missing_max_chars is None:
        missing_max_chars = read_missing_max_chars(default_path())

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
    levels = load_grade_levels()  # plan 25 task 1: the points are computed from the level, never asked of the model
    step = read_grade_step(default_path())

    last_error_reason = None
    last_retry_note = ""
    code = "schema_invalid"
    last_answer = None
    for attempt in range(ctx.grade_retries + 1):
        current_note = calibration_note
        if last_retry_note:
            current_note = f"{calibration_note}\n{last_retry_note}" if calibration_note else last_retry_note
        elif last_error_reason:
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
            last_retry_note = ""
            code = NO_ANSWER_CODES.get(e.kind, "schema_invalid")
            last_answer = None
            continue

        answer = with_level_score(answer, item, levels, step)
        code, message = check_grade_answer(answer, item, pages)
        if code == "ok":
            return _record_from_answer(item_id, answer, "ok", attempt + 1, item.get("max_points", 0), missing_max_chars)
        last_error_reason = message
        last_retry_note = _retry_note(ctx, code, item, answer, language) if code in RETRY_SECTION_BY_CODE else ""
        last_answer = answer

    attempts = ctx.grade_retries + 1
    if last_answer is None:
        return _no_answer_record(item_id, code, attempts, "")
    return _record_from_answer(item_id, last_answer, code, attempts, item.get("max_points", 0), missing_max_chars)


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
    missing_max_chars = read_missing_max_chars(default_path())
    if existing and "items" in existing:
        for item in existing["items"]:
            existing_items[item["item_id"]] = item

    for item in rubric["items"]:
        item_id = item["id"]
        if item_id in existing_items:
            items_to_grade.append(existing_items[item_id])
        else:
            record = grade_item(
                item, pages, call, ctx, language, calibration_note, report_id, missing_max_chars
            )
            items_to_grade.append(record)
            if on_item:
                on_item(item_id, record)

    return {
        "report_id": report_id,
        "loop": loop,
        "items": items_to_grade
    }
