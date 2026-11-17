import json
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

# Add loop-engineer and its scripts to path
_LOOP_ENGINEER_ROOT = Path(__file__).resolve().parent.parent.parent / "loop-engineer"
_LOOP_ENGINEER_SCRIPTS = _LOOP_ENGINEER_ROOT / "scripts"
for _p in (_LOOP_ENGINEER_SCRIPTS, _LOOP_ENGINEER_ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

# Ensure local scripts are also on path for direct imports if needed
_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from ugs_text import StepContext, PromptError, fill, page_blocks, select_pages
from ugs_bridge import NotRun
from ugs_grade import grade_item
from rubric_split import item_prompt_text

# The slot of the report language, the same name the grading prompt uses (grade_item.md).
LANGUAGE_SLOT = "LANGUAGE_OF_REPORT"

def audit_item(
    item: dict,
    record: dict,
    pages: List[str],
    call: Callable,
    ctx: StepContext,
    language: Optional[str] = None
) -> dict:
    """
    Purpose: Audit a single graded item.
    Inputs:
        item: dict - The rubric item.
        record: dict - The grade record.
        pages: List[str] - The page texts.
        call: Callable - The model call function.
        ctx: StepContext - The context for the step.
        language: Optional[str] - The report language ('fr' or 'en'), filled into LANGUAGE_OF_REPORT when the
            audit prompt holds that slot; None when the prompt has no such slot.
    Outputs:
        dict - The audit result {verdict, reason}.
    Raises:
        NotRun: If the model fails with an unretryable error.
        PromptError: If the audit prompt holds the language slot and no language is given.
    """
    # Prepare evidence pages
    evidence_pages = []
    if record.get("evidence"):
        for ev in record["evidence"]:
            if "page" in ev:
                evidence_pages.append(ev["page"])
        if not evidence_pages:
            evidence_pages = select_pages(item, pages, ctx.window_tokens - ctx.reserve_tokens, ctx.count, ctx.min_word_len)
    else:
        evidence_pages = select_pages(item, pages, ctx.window_tokens - ctx.reserve_tokens, ctx.count, ctx.min_word_len)
        
    evidence_text = page_blocks(pages, evidence_pages) if evidence_pages else ""
    
    # The auditor judges the grade, not the bookkeeping of its validation (plan 12, R12): these keys stay in the
    # saved record, which audit_report copies, and never reach the prompt.
    record_for_prompt = {k: v for k, v in record.items()
                         if k not in ("audit", "flag", "validation", "attempts", "model_score")}
    
    prompt_template = ctx.prompts["audit_item"]
    schema = ctx.schemas["audit_item"]
    values = {
        "ITEM": item_prompt_text(item),
        "GRADE_RECORD": json.dumps(record_for_prompt),
        "EVIDENCE_PAGES": evidence_text
    }
    if "{{%s}}" % LANGUAGE_SLOT in prompt_template:
        if not language:
            raise PromptError(f"audit prompt needs the report language for slot {LANGUAGE_SLOT}")
        values[LANGUAGE_SLOT] = language

    last_error = None
    for attempt in range(ctx.audit_retries + 1):
        prompt = fill(prompt_template, values)
        
        try:
            answer = call(prompt, schema)
            verdict = answer.get("verdict")
            if verdict not in ("agree", "disagree"):
                raise NotRun("invalid", f"Unknown verdict: {verdict}")
            return {
                "verdict": verdict,
                "reason": answer.get("reason", "")
            }
        except NotRun as e:
            if not e.retryable:
                raise
            last_error = e
            continue
            
    return {
        "verdict": "not_run",
        "reason": last_error.reason if last_error else "exhausted retries"
    }

def audit_report(
    rubric: dict,
    pages: List[str],
    grade: dict,
    call: Callable,
    ctx: StepContext,
    language: str,
    calibration_note: str,
    on_item: Optional[Callable] = None
) -> dict:
    """
    Purpose: Audit all items in a grade report.
    Inputs:
        rubric: dict - The rubric.
        pages: List[str] - The page texts.
        grade: dict - The grade report.
        call: Callable - The model call function.
        ctx: StepContext - The context for the step.
        language: str - The language of the report.
        calibration_note: str - The current calibration note.
        on_item: Optional[Callable] - Callback for each audited item.
    Outputs:
        dict - The new grade report.
    Raises:
        NotRun: If the model fails with an unretryable error during audit.
    """
    items = []
    rubric_items = {item["id"]: item for item in rubric["items"]}
    
    for record in grade["items"]:
        item_id = record["item_id"]
        item = rubric_items.get(item_id)
        
        # Skip if not rated
        if record["status"] != "rated":
            new_record = dict(record)
            new_record["audit"] = "not_run"
            items.append(new_record)
            continue
            
        if not item:
            # Should not happen if grade is valid against rubric
            new_record = dict(record)
            new_record["audit"] = "not_run"
            items.append(new_record)
            continue
            
        # Audit
        audit_result = audit_item(item, record, pages, call, ctx, language)
        
        if audit_result["verdict"] == "agree":
            new_record = dict(record)
            new_record["audit"] = "agree"
            items.append(new_record)
            if on_item:
                on_item(item_id, new_record)
                
        elif audit_result["verdict"] == "disagree":
            # Regrade with auditor reason
            regrade_note = f"{calibration_note}\nAuditor disagreement: {audit_result['reason']}" if calibration_note else f"Auditor disagreement: {audit_result['reason']}"
            
            try:
                regraded_record = grade_item(
                    item, pages, call, ctx, language, regrade_note
                )
            except NotRun as e:
                if not e.retryable:
                    raise
                # If regrade fails with retryable error, we might want to mark as not_run or keep original?
                # Spec: "a second disagreement sends the item back to the grader once... if it disagrees again the first record is kept"
                # If regrade fails (NotRun), what then?
                # "The auditor call fails after its retries: the audit field is not_run and the flag stays false."
                # This applies to auditor call. What about regrade?
                # Let's assume if regrade fails, we treat it as if the auditor disagreed and we couldn't regrade, so we keep original and flag?
                # Or mark as not_run?
                # Plan says: "on disagree the grader regrades the item once... if it agrees the new record replaces the first... if it disagrees again the first record is kept with audit disagree and flag true."
                # It doesn't explicitly say what happens if regrade fails with NotRun.
                # Given "Local models only", and "NotRun" is a failure, let's propagate if unretryable.
                # If retryable, we've already used our retry budget in grade_item? No, grade_item has its own retries.
                # If grade_item raises NotRun, it means it failed completely.
                # Let's mark as not_run and flag? Or just not_run?
                # Let's mark as not_run to be safe, as we don't have a valid regrade.
                new_record = dict(record)
                new_record["audit"] = "not_run"
                items.append(new_record)
                if on_item:
                    on_item(item_id, new_record)
                continue

            # Audit the regraded record
            audit_result_2 = audit_item(item, regraded_record, pages, call, ctx, language)
            
            if audit_result_2["verdict"] == "agree":
                new_record = dict(regraded_record)
                new_record["audit"] = "agree"
                items.append(new_record)
                if on_item:
                    on_item(item_id, new_record)
            else:
                # Disagree again
                new_record = dict(record)
                new_record["audit"] = "disagree"
                new_record["flag"] = True
                items.append(new_record)
                if on_item:
                    on_item(item_id, new_record)
                
        else:
            # not_run
            new_record = dict(record)
            new_record["audit"] = "not_run"
            items.append(new_record)
            if on_item:
                on_item(item_id, new_record)

    return {
        "report_id": grade["report_id"],
        "loop": grade["loop"],
        "items": items
    }
