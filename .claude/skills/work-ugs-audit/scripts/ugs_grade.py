"""
Purpose: Grade rubric items using local models.
"""

import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

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


def _validate_grade_answer(
    answer: dict,
    item: dict,
    pages: List[str]
) -> Optional[str]:
    """
    Purpose: Validate a grade answer against the item and pages.
    Inputs:
        answer: dict - The model's answer.
        item: dict - The rubric item.
        pages: List[str] - The page texts.
    Outputs:
        Optional[str] - None if valid, else a reason string.
    """
    status = answer.get("status")
    score = answer.get("score")
    evidence = answer.get("evidence", [])
    
    if status not in ("rated", "not_applicable"):
        return f"unknown status {status}"
        
    if status == "not_applicable":
        if score is not None:
            return "not_applicable must have null score"
        return None
        
    if status == "rated":
        max_points = item.get("max_points", 0)
        if score is None:
            return "rated must have a score"
        if score < 0:
            return "score must be non-negative"
        if score > max_points:
            return f"score {score} above max {max_points}"
            
        # Evidence check
        if score < max_points:
            if not evidence:
                return "score below max requires evidence"
                
            for ev in evidence:
                page_num = ev.get("page")
                quote = ev.get("quote")
                if page_num is None or quote is None:
                    return "evidence entry missing page or quote"
                if page_num < 1 or page_num > len(pages):
                    return f"evidence page {page_num} out of range"
                page_text = pages[page_num - 1]
                norm_quote = normalize(quote)
                norm_page = normalize(page_text)
                if norm_quote not in norm_page:
                    return f"quote not found in page {page_num}"
                    
    return None


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
    Inputs:
        item: dict - The rubric item.
        pages: List[str] - The page texts.
        call: Callable - The model call function.
        ctx: StepContext - The context for the step.
        language: str - The language of the report.
        calibration_note: str - The current calibration note.
        report_id: str or None - The identifier of the report, for the action records only.
    Outputs:
        dict - The grade record.
    Raises:
        NotRun: If the model fails with an unretryable error.
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
            return {
                "item_id": item_id,
                "status": "not_run",
                "score": None,
                "comment": "no_fit",
                "evidence": [],
                "audit": "not_run",
                "flag": True
            }
        sections_text = page_blocks(pages, selected_pages)

    if ctx.emit is not None:
        ctx.emit("read", page_range(selected_pages), report_id=report_id)
    schema = ctx.schemas["grade_item"]
    
    last_error_reason = None
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
            reason = _validate_grade_answer(answer, item, pages)
            if reason is None:
                return {
                    "item_id": item_id,
                    "status": answer["status"],
                    "score": answer["score"],
                    "comment": answer.get("comment", ""),
                    "evidence": answer.get("evidence", []),
                    "audit": "not_run",
                    "flag": False
                }
            else:
                last_error_reason = reason
        except NotRun as e:
            if e.kind == "over_budget":
                return {
                    "item_id": item_id,
                    "status": "not_run",
                    "score": None,
                    "comment": "over_budget",
                    "evidence": [],
                    "audit": "not_run",
                    "flag": True
                }
            if not e.retryable:
                raise
            last_error_reason = e.reason
            # Continue to retry
            
    # Exhausted retries
    return {
        "item_id": item_id,
        "status": "not_run",
        "score": None,
        "comment": "invalid_answer",
        "evidence": [],
        "audit": "not_run",
        "flag": True
    }


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
