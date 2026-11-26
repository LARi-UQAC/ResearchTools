"""
Purpose: Grade rubric items using local models.

The model names, for each rubric item, the elements the item requires and a verdict on each (present, partial or
absent). The code computes the level from those verdicts (grade_levels.json) and the points from the level.
"""

import json
import math
import sys
from dataclasses import dataclass
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
    "elements_missing",
    "exceptional_unsupported",
    "unknown_level",
    "not_applicable_with_score",
    "unknown_status",
    "unparsable_answer",
    "schema_invalid",
    "no_fit",
    "over_budget",
    "timeout",
    "not_applicable_not_allowed",
)

# The refusals asked again with a template of the prompts folder: each code names its section of
# retry_grade_item.md, in the report language.
RETRY_SECTION_BY_CODE = {
    "elements_missing": "elements",
    "not_applicable_not_allowed": "not_applicable",
    "exceptional_unsupported": "exceptional",
}

# A refused proof keeps the level and the points the verdicts give: only the evidence is refused.
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

# The verdicts the model may give an element of the rubric item.
VERDICTS = ("present", "partial", "absent")
PRESENT_VERDICTS = ("present", "partial")

# The fractions, the partial weight and the bands live in assets/grade_levels.json (R0, R4); no code holds a number.
GRADE_LEVELS_FILE = Path(__file__).resolve().parent.parent / "assets" / "grade_levels.json"
GRADE_STEP_KEY = "grade.score_step"
EXCEPTIONAL_LEVEL = "exemplary"
FULL_LEVEL = "complete_correct"
ABSENT_LEVEL = "absent"


@dataclass(frozen=True)
class GradeScale:
    """
    Purpose: The level scale of grade_levels.json: the fraction of each level, the weight of a partial element and the
        bands, highest first, that map the share of present elements to a level.
    """

    fractions: Dict[str, Decimal]
    partial_weight: Decimal
    bands: Tuple[Tuple[Decimal, str], ...]


def _config_value(raw: Any, key: str, path: Path) -> Any:
    """
    Purpose: Read the value of one keyed entry of the levels file, a named error when it is missing (R3).
    Inputs:
        raw: Any - The parsed JSON document.
        key: str - The entry name.
        path: Path - The file, for the message.
    Outputs:
        Any - The value of the entry.
    Raises:
        ValueError: If the entry or its value is missing.
    """
    entry = raw.get(key) if isinstance(raw, dict) else None
    if not isinstance(entry, dict) or "value" not in entry:
        raise ValueError(f"missing key '{key}' in {path}")
    return entry["value"]


def _ratio(value: Any, name: str, path: Path) -> Decimal:
    """
    Purpose: Check that a value is a number from 0 to 1 and give it exactly.
    Inputs:
        value: Any - The value read from the file.
        name: str - The name, for the message.
        path: Path - The file, for the message.
    Outputs:
        Decimal - The value.
    Raises:
        ValueError: If the value is not a number from 0 to 1.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= 1:
        raise ValueError(f"'{name}' must be a number from 0 to 1 in {path}")
    return Decimal(str(value))


def load_grade_scale(path: Path = GRADE_LEVELS_FILE) -> GradeScale:
    """
    Purpose: Read the level scale from grade_levels.json (plan 25; review round 1, decision 1).
    Inputs:
        path: Path - The levels file, the shipped one by default.
    Outputs:
        GradeScale - The fractions, the partial weight and the bands, highest first.
    Raises:
        ValueError: If the file is unreadable or incomplete, a band names no level, or the last band does not reach
            a share of 0 (R3).
    """
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read {path}: {exc}") from exc
    levels = raw.get("levels") if isinstance(raw, dict) else None
    if not isinstance(levels, dict) or not levels:
        raise ValueError(f"no 'levels' object in {path}")
    fractions = {name: _ratio(entry.get("fraction") if isinstance(entry, dict) else None,
                              f"levels.{name}.fraction", path)
                 for name, entry in levels.items()}
    partial_weight = _ratio(_config_value(raw, "partial_weight", path), "partial_weight", path)
    block = raw.get("bands") if isinstance(raw, dict) else None
    rows = block.get("list") if isinstance(block, dict) else None
    if not isinstance(rows, list) or not rows:
        raise ValueError(f"no 'bands.list' in {path}")
    bands = []
    for row in rows:
        if not isinstance(row, dict) or row.get("level") not in fractions:
            raise ValueError(f"a band of 'bands.list' names no known level in {path}")
        bands.append((_ratio(row.get("min_share"), "bands.list.min_share", path), row["level"]))
    bands.sort(key=lambda band: band[0], reverse=True)
    if bands[-1][0] != 0:
        raise ValueError(f"the last band of 'bands.list' must have min_share 0 in {path}")
    return GradeScale(fractions=fractions, partial_weight=partial_weight, bands=tuple(bands))


def load_grade_levels(path: Path = GRADE_LEVELS_FILE) -> Dict[str, Decimal]:
    """
    Purpose: Give the fraction of each level of grade_levels.json (the points are fraction times maximum).
    Inputs:
        path: Path - The levels file, the shipped one by default.
    Outputs:
        Dict[str, Decimal] - The fraction of each level name, exact.
    Raises:
        ValueError: As load_grade_scale.
    """
    return load_grade_scale(path).fractions


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


def points_for_level(level: str, max_points: Any, fractions: Dict[str, Decimal], step: Decimal) -> float:
    """
    Purpose: Give the points of a level: its fraction times the maximum, rounded to the nearest multiple of the step
        (a tie going up), and never above the maximum (review round 1, decision 3).
    Inputs:
        level: str - A key of fractions.
        max_points: Any - The maximum of the item, a number.
        fractions: Dict[str, Decimal] - The fraction of each level, from load_grade_levels.
        step: Decimal - The rounding step, from read_grade_step.
    Outputs:
        float - The points, from 0 to the maximum.
    Raises:
        KeyError: If the level is not in fractions.
    """
    maximum = Decimal(str(max_points))
    value = min(fractions[level] * maximum, maximum)
    units = (value / step).to_integral_value(rounding=ROUND_HALF_UP)
    return min(float(units * step), float(maximum))


def count_verdicts(elements: List[dict]) -> Dict[str, int]:
    """
    Purpose: Count the present, partial and absent verdicts of an item's elements.
    Inputs:
        elements: List[dict] - The elements of an answer, each with a verdict.
    Outputs:
        Dict[str, int] - The count of each verdict, zero when none.
    Raises:
        None.
    """
    counts = {verdict: 0 for verdict in VERDICTS}
    for element in elements:
        if isinstance(element, dict) and element.get("verdict") in counts:
            counts[element["verdict"]] += 1
    return counts


def element_summary(elements: Any) -> Optional[str]:
    """
    Purpose: Give the element summary kept in a grade record as model_score (review round 1, decision 6): the count
        of each verdict, as text. None when the answer names no elements.
    Inputs:
        elements: Any - The elements of an answer.
    Outputs:
        Optional[str] - The summary text, or None.
    Raises:
        None.
    """
    if not isinstance(elements, list):
        return None
    counts = count_verdicts(elements)
    return "present %d, partial %d, absent %d" % (counts["present"], counts["partial"], counts["absent"])


def level_for_elements(elements: List[dict], exceptional: bool, scale: GradeScale) -> str:
    """
    Purpose: Compute the level of an item from its element verdicts (review round 1, decision 1): exemplary only
        when the model claims it as exceptional, complete_correct when every element is present, absent when none is
        present or partial, else the first band the share of present elements reaches.
    Inputs:
        elements: List[dict] - The elements of the answer, each with a verdict.
        exceptional: bool - The explicit claim of an exceptional report.
        scale: GradeScale - The bands and the partial weight.
    Outputs:
        str - A level name of grade_levels.json.
    Raises:
        None.
    """
    if exceptional:
        return EXCEPTIONAL_LEVEL
    counts = count_verdicts(elements)
    total = len(elements)
    if total == 0 or (counts["present"] == 0 and counts["partial"] == 0):
        return ABSENT_LEVEL
    if counts["present"] == total:
        return FULL_LEVEL
    share = (Decimal(counts["present"]) + scale.partial_weight * counts["partial"]) / total
    for min_share, level in scale.bands:
        if share >= min_share:
            return level
    return ABSENT_LEVEL


def _elements_are_list_of_objects(elements: Any) -> bool:
    """
    Purpose: Tell whether an answer's elements are a non-empty list of objects, before any verdict is read.
    Inputs:
        elements: Any - The elements of an answer.
    Outputs:
        bool - True for a non-empty list in which every entry is an object.
    Raises:
        None.
    """
    return isinstance(elements, list) and bool(elements) and all(isinstance(entry, dict) for entry in elements)


def _quote_verified(page_num: Any, quote: Any, pages: List[str]) -> bool:
    """
    Purpose: Tell whether an element's quote is found on its page, after the same normalisation as check_grade_answer.
    Inputs:
        page_num: Any - The page number of the element.
        quote: Any - The quote of the element.
        pages: List[str] - The page texts.
    Outputs:
        bool - True only when the page exists and the normalised quote is found on it.
    Raises:
        None.
    """
    if not _is_page_number(page_num) or not 1 <= page_num <= len(pages):
        return False
    if not isinstance(quote, str) or not normalize(quote).strip():
        return False
    return normalize(quote) in normalize(pages[page_num - 1])


def _exceptional_holds(elements: List[dict], pages: List[str]) -> bool:
    """
    Purpose: Tell whether an exceptional claim holds: every element present, each with a quote found on its page (the
        security review of round 1: an unverifiable quote never earns exemplary points).
    Inputs:
        elements: List[dict] - The elements of the answer.
        pages: List[str] - The page texts.
    Outputs:
        bool - True only when every element is present and verified.
    Raises:
        None.
    """
    return all(entry.get("verdict") == "present" and _quote_verified(entry.get("page"), entry.get("quote"), pages)
               for entry in elements)


# The keys of a rated answer that only the code computes.
MODEL_DERIVED_KEYS = ("level", "score", "evidence")


def with_level_score(answer: dict, item: dict, scale: GradeScale, step: Decimal, pages: List[str]) -> dict:
    """
    Purpose: Give a copy of a rated answer with its level, its points and its evidence computed from the element
        verdicts (review round 1, decisions 1 and 2). An answer with no usable elements is returned unchanged and is
        refused by check_grade_answer.
    Inputs:
        answer: dict - The model's answer.
        item: dict - The rubric item; its max_points is used.
        scale: GradeScale - The level scale.
        step: Decimal - The rounding step.
    Outputs:
        dict - The answer with level, score and evidence (the present and partial quotes) when computable.
    Raises:
        None.
    """
    if answer.get("status") != "rated":
        return answer  # a not_applicable answer keeps its payload, so check_grade_answer can refuse it
    # Security review of round 1: a level, a score and evidence written by the model are never kept; only the values
    # computed here from the verdicts are (a level the model names is not a verdict).
    answer = {key: value for key, value in answer.items() if key not in MODEL_DERIVED_KEYS}
    if not _elements_are_list_of_objects(answer.get("elements")):
        return answer
    elements = answer["elements"]
    claimed = answer.get("exceptional") is True and _exceptional_holds(elements, pages)  # refused proof: no claim
    level = level_for_elements(elements, claimed, scale)
    computed = dict(answer)
    computed["level"] = level
    computed["score"] = points_for_level(level, item.get("max_points", 0), scale.fractions, step)
    computed["evidence"] = [{"page": entry.get("page"), "quote": entry.get("quote")} for entry in elements
                            if entry.get("verdict") in PRESENT_VERDICTS]
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
    pages: List[str],
    scale: Optional[GradeScale] = None
) -> Tuple[str, str]:
    """
    Purpose: Check one model answer against its rubric item and the page texts, and name the first defect.
    Details: The answer names the elements the item requires, each with a verdict. Every present or partial element
        needs a page and a quote found on it (the evidence). A rated item with no present or partial element that
        verifies is refused whatever its level (review round 1, decision 2). An exceptional claim needs every element
        present and a verified one. The codes are the table GRADE_CODES. A refused proof is a defect of the evidence
        only. The message names a page number or a count, never a quote.
    Inputs:
        answer: dict - The model's answer, as given.
        item: dict - The rubric item, with its max_points and its optional flag.
        pages: List[str] - The page texts of the report.
        scale: Optional[GradeScale] - The level scale the level of an answer must belong to; None loads
            grade_levels.json (review round 1, decision 6: the tests inject their own scale).
    Outputs:
        Tuple[str, str] - The code, and a short message: "ok" with an empty message on success.
    Raises:
        None.
    """
    status = answer.get("status")
    if status not in ("rated", "not_applicable"):
        return "unknown_status", "status must be rated or not_applicable"
    if scale is None:
        scale = load_grade_scale()
    if "level" in answer and answer["level"] not in scale.fractions:  # the injected scale names every level it may give
        return "unknown_level", "level must be one of the levels of grade_levels.json"
    if status == "not_applicable":
        if answer.get("score") is not None or answer.get("evidence"):
            return "not_applicable_with_score", "not_applicable must carry no score and no evidence"
        if not item.get("optional"):
            return "not_applicable_not_allowed", "not_applicable is allowed only for an optional item"
        return "ok", ""

    elements = answer.get("elements")
    if not isinstance(elements, list):
        return "schema_invalid", "elements must be a list"
    if not elements:
        return "elements_missing", "a rated item names the elements it requires"
    for entry in elements:
        if not isinstance(entry, dict) or not isinstance(entry.get("element"), str) \
                or entry.get("verdict") not in VERDICTS:
            return "schema_invalid", "each element needs its name and a verdict: present, partial or absent"

    verified = 0
    for entry in elements:
        if entry.get("verdict") not in PRESENT_VERDICTS:
            continue
        page_num = entry.get("page")
        quote = entry.get("quote")
        if not _is_page_number(page_num) or not isinstance(quote, str) or not normalize(quote).strip():
            return "evidence_incomplete", "a present or partial element needs a page number and a quote"
        if page_num < 1 or page_num > len(pages):
            return "evidence_page_out_of_range", f"evidence page {page_num} is out of range"
        if normalize(quote) not in normalize(pages[page_num - 1]):
            return "quote_not_found", f"quote not found on page {page_num}"
        verified += 1
    if verified == 0:
        return "evidence_missing", "no element is present or partial with a quote found on its page"

    if answer.get("exceptional") is True:
        counts = count_verdicts(elements)
        if counts["present"] != len(elements):
            return "exceptional_unsupported", "an exceptional report has every element present"
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
    Raises:
        None.
    """
    code, message = check_grade_answer(answer, item, pages)
    return None if code == "ok" else message


def _missing_text(answer: dict, max_points: Any, points: Any, max_chars: int) -> str:
    """
    Purpose: Give the `missing` value of a grade record: the element that cost the points, or "".
    Details: Empty at the maximum points or when every element is present, when the answer has no `missing`, or when
        it is not a string. Otherwise the
        text is kept as the model gave it, stripped and cut to max_chars. It is model text saved in grade.json only:
        it never reaches the ledger note, a log or the dashboard (see ugs_run._grade_mark).
    Inputs:
        answer: dict - The model's answer, as given.
        max_points: Any - The maximum of the rubric item.
        points: Any - The points of the item, None when there are none.
        max_chars: int - The character limit, from grade.missing_max_chars (D2).
    Outputs:
        str - The missing text, possibly empty.
    Raises:
        None.
    """
    if _is_number(points) and points == max_points:
        return ""
    elements = answer.get("elements")
    if isinstance(elements, list) and elements and count_verdicts(elements)["present"] == len(elements):
        return ""  # every element present: nothing cost the points
    value = answer.get("missing")
    if not isinstance(value, str):
        return ""
    return value.strip()[:max_chars]


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
    Details: A success keeps the status, the points and the level computed from the elements. A refused proof keeps
        status rated and the computed points. Any other refusal drops the points (status not_run, score null). The
        model_score field holds the element summary ("present N, partial N, absent N"), as the review round 1 decision
        6 records it; the element verdicts are kept in elements, with their pages and no quote (the quotes are in
        evidence). The key order is the saved order of grade.json.
    Inputs:
        item_id: str - The rubric item identifier.
        answer: dict - The model's answer, with the computed level, score and evidence when computable.
        code: str - The code of check_grade_answer, "ok" for a success.
        attempts: int - The number of model calls made, this one included.
        max_points: Any - The maximum of the rubric item.
        missing_max_chars: Optional[int] - The limit of the missing text; None reads it from the configuration.
    Outputs:
        dict - The grade record, flagged unless the code is "ok".
    Raises:
        ValueError: If the configuration has no positive missing limit and none is given (R3).
    """
    if missing_max_chars is None:
        missing_max_chars = read_missing_max_chars(default_path())
    elements = answer.get("elements")
    # Only a level computed by with_level_score makes a score and evidence trustworthy (security review of round 1).
    usable = answer.get("status") == "rated" and "level" in answer
    if code == "ok":
        status = answer.get("status")
        score = answer.get("score") if usable else None
    elif code in PROOF_REFUSAL_CODES:
        status = "rated"
        score = answer.get("score") if usable else None
    else:
        status = "not_run"
        score = None
    evidence = answer.get("evidence") if usable else []
    record = {
        "item_id": item_id,
        "status": status,
        "score": score,
        "comment": answer.get("comment", ""),
        "evidence": [] if evidence is None else evidence,
        "missing": _missing_text(answer, max_points, score, missing_max_chars),
        "audit": "not_run",
        "flag": code != "ok",
        "model_score": element_summary(elements) if usable else None,
        "validation": code,
        "attempts": attempts,
        "level": answer.get("level"),
        "elements": [] if not usable or not isinstance(elements, list) else [
            {"element": entry.get("element"), "verdict": entry.get("verdict"), "page": entry.get("page")}
            for entry in elements if isinstance(entry, dict)],
    }
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
    Raises:
        None.
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
        "level": None,
        "elements": [],
    }


def _retry_note(ctx: StepContext, code: str, item: dict, language: str) -> str:
    """
    Purpose: Build the note that asks the model again after a refusal that names its missing part: no elements, an
        exceptional claim without support, or a not_applicable on a required item. The wording lives in the
        retry_grade_item prompt file, never in code (R6).
    Inputs:
        ctx: StepContext - The step context; its prompts hold retry_grade_item.
        code: str - The refusal code, a key of RETRY_SECTION_BY_CODE.
        item: dict - The rubric item, its max_points is named in the note.
        language: str - The report language, fr or en; it selects the section.
    Outputs:
        str - The note, stripped.
    Raises:
        PromptError: When the template or its section for this language is missing (R3).
    """
    section = RETRY_SECTION_BY_CODE[code]
    template = prompt_section(ctx.prompts["retry_grade_item"], f"{language}_{section}")
    return fill(template, {}).strip()  # the retry sections name no slot: the wording is fixed by the item kind


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
    Details: When ctx.emit is set, one `read` record gives the page range selected and one `call` record each model
        call, both with identifiers only (R11). With no emitter nothing is recorded. The level and the points are
        computed from the element verdicts of the answer (review round 1). A refused attempt is retried once with its
        reason; the record is built from the last answer given, with its validation code (plan 12, R12).
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
        dict - The grade record: item_id, status, score, comment, evidence, missing, audit, flag, model_score,
            validation, attempts, level and elements.
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
    scale = load_grade_scale()
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

        answer = with_level_score(answer, item, scale, step, pages)
        code, message = check_grade_answer(answer, item, pages, scale)
        if code == "ok":
            return _record_from_answer(item_id, answer, "ok", attempt + 1, item.get("max_points", 0), missing_max_chars)
        last_error_reason = message
        last_retry_note = _retry_note(ctx, code, item, language) if code in RETRY_SECTION_BY_CODE else ""
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
