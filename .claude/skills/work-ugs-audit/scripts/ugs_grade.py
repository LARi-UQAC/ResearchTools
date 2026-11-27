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
import quote_match

# The one table of validation codes (R5). A code is snake_case, at most 30 characters, never report text.
# A quote that no tier verifies is no longer an item refusal (review round 2, item 2): it makes its element partial.
GRADE_CODES = (
    "ok",
    "evidence_missing",
    "elements_missing",
    "elements_too_few",
    "unknown_status",
    "unparsable_answer",
    "schema_invalid",
    "no_fit",
    "over_budget",
    "timeout",
    "not_applicable_not_allowed",
    "not_applicable_with_score",
    "elements_mismatch",
    "comment_scope",
)

# The refusals asked again with a template of the prompts folder: each code names its section of
# retry_grade_item.md, in the report language.
RETRY_SECTION_BY_CODE = {
    "elements_missing": "elements",
    "elements_too_few": "elements",
    "elements_mismatch": "mismatch",
    "evidence_missing": "evidence",
    "not_applicable_not_allowed": "not_applicable",
    "not_applicable_with_score": "not_applicable",
    "comment_scope": "comment",
}

# The credit of a verdict in the points (owner, 2026-11-27): present 1, partial the partial weight, absent 0.
CREDIT_FULL = Decimal(1)
COMMENT_OPENINGS_KEY = "grade.comment_forbidden_openings"

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
UNVERIFIED_KEY = "grade.unverified_present_counts_as"
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
    Purpose: Read the level scale from grade_levels.json (plan 25; review rounds 1 and 2).
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


def read_max_elements(path: Path) -> int:
    """
    Purpose: Read the cap on the elements verified in one item (review round 2, item 3, grade.max_elements).
    Inputs:
        path: Path - The configuration JSON.
    Outputs:
        int - A positive whole number of elements.
    Raises:
        ValueError: If the file is unreadable, the key is absent or the value is not a positive whole number (R3).
    """
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read {path}: {exc}") from exc
    entry = raw.get("grade.max_elements") if isinstance(raw, dict) else None
    if not isinstance(entry, dict) or "value" not in entry:
        raise ValueError(f"missing key 'grade.max_elements' in {path}")
    value = entry["value"]
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"'grade.max_elements' must be a positive whole number in {path}")
    return value


def read_unverified_as(path: Path) -> str:
    """
    Purpose: Read the verdict an element marked present takes when no tier verifies its quote (review round 2, item 2).
    Inputs:
        path: Path - The configuration JSON, normally ugs_config.default_path().
    Outputs:
        str - "partial" or "absent".
    Raises:
        ValueError: If the file is unreadable, the key is absent or its value is not partial or absent (R3).
    """
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read {path}: {exc}") from exc
    entry = raw.get(UNVERIFIED_KEY) if isinstance(raw, dict) else None
    if not isinstance(entry, dict) or "value" not in entry:
        raise ValueError(f"missing key '{UNVERIFIED_KEY}' in {path}")
    if entry["value"] not in ("partial", "absent"):
        raise ValueError(f"'{UNVERIFIED_KEY}' must be partial or absent in {path}")
    return entry["value"]


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


def _credit(verdict: Any, scale: GradeScale) -> Decimal:
    """
    Purpose: Give the credit of one effective verdict: present 1, partial the partial weight, absent or unknown 0.
    Inputs:
        verdict: Any - The effective verdict of an element.
        scale: GradeScale - The partial weight.
    Outputs:
        Decimal - The credit, from 0 to 1.
    Raises:
        None.
    """
    if verdict == "present":
        return CREDIT_FULL
    if verdict == "partial":
        return scale.partial_weight
    return Decimal(0)


def points_for_elements(elements: List[dict], max_points: Any, scale: GradeScale, step: Decimal) -> Decimal:
    """
    Purpose: Give the points of an item from its elements (owner, 2026-11-27): the maximum times the sum of the element
        credits over the number of elements, rounded to the nearest multiple of the step, a tie going up.
    Inputs:
        elements: List[dict] - The prepared elements, each with its effective verdict.
        max_points: Any - The maximum of the item.
        scale: GradeScale - The partial weight.
        step: Decimal - The rounding step, from read_grade_step.
    Outputs:
        Decimal - The points, from 0 to the maximum; zero when there is no element.
    Raises:
        None.
    """
    if not elements:
        return Decimal(0)
    maximum = Decimal(str(max_points))
    credit = sum(_credit(entry.get("effective"), scale) for entry in elements)
    value = min(maximum * credit / len(elements), maximum)
    units = (value / step).to_integral_value(rounding=ROUND_HALF_UP)
    return min(units * step, maximum)


def element_losses(elements: List[dict], max_points: Any, scale: GradeScale) -> List[dict]:
    """
    Purpose: Name every element that cost points, with the points it cost (owner, 2026-11-27: the comment names each
        lost fraction). An element marked present whose quote no tier verified is listed as its partial verdict with
        unverified set, so the student sees why it cost.
    Inputs:
        elements: List[dict] - The prepared elements, each with its id, element text, verdict and effective verdict.
        max_points: Any - The maximum of the item.
        scale: GradeScale - The partial weight.
    Outputs:
        List[dict] - One entry per element that is not present: id, text, verdict (the effective one), lost (points)
            and unverified (bool). Empty when every element is present.
    Raises:
        None.
    """
    if not elements:
        return []
    maximum = Decimal(str(max_points))
    losses = []
    for entry in elements:
        effective = entry.get("effective")
        if effective == "present":
            continue
        lost = maximum * (CREDIT_FULL - _credit(effective, scale)) / len(elements)
        losses.append({"id": entry.get("id"), "text": entry.get("element"), "verdict": effective,
                       "lost": float(lost), "unverified": entry.get("verdict") == "present" and not entry.get("verified")})
    return losses


def count_verdicts(elements: List[dict]) -> Dict[str, int]:
    """
    Purpose: Count the effective verdicts of an item's elements: an element marked present whose quote no tier verified
        counts as the unverified verdict (review round 2, item 2); an element never checked keeps its verdict.
    Inputs:
        elements: List[dict] - The elements of an answer.
    Outputs:
        Dict[str, int] - The count of each verdict, zero when none.
    Raises:
        None.
    """
    counts = {verdict: 0 for verdict in VERDICTS}
    for element in elements:
        if isinstance(element, dict):
            verdict = element.get("effective", element.get("verdict"))
            if verdict in counts:
                counts[verdict] += 1
    return counts


def element_summary(elements: Any) -> Optional[str]:
    """
    Purpose: Give the element summary kept in a grade record as model_score (review round 1, decision 6): the count
        of each effective verdict, as text. None when the answer names no elements.
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
    Purpose: Compute the level of an item from its effective element verdicts (review rounds 1 and 2): exemplary only
        when the claim holds (decided by the caller), complete_correct when every element is present and verified,
        absent when none is present or partial, else the first band the share of present elements reaches.
    Inputs:
        elements: List[dict] - The elements of the answer, with their effective verdicts.
        exceptional: bool - The claim of an exceptional report, already checked against the verified elements.
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


def _ids_match(elements: List[Any], rubric: List[dict]) -> bool:
    """
    Purpose: Tell whether the answer names exactly the element ids of the rubric item, each once (owner, 2026-11-27).
    Inputs:
        elements: List[Any] - The elements of the answer, as the model gave them.
        rubric: List[dict] - The rubric elements, each with its id.
    Outputs:
        bool - True when the sets of ids are equal and no id is repeated.
    Raises:
        None.
    """
    given = [entry.get("id") if isinstance(entry, dict) else None for entry in elements]
    wanted = [ref["id"] for ref in rubric]
    return len(given) == len(wanted) and sorted(given, key=str) == sorted(wanted, key=str)


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


def read_grade_settings(path: Path = None) -> Dict[str, Any]:
    """
    Purpose: Read every setting the grader needs from the configuration: the quote settings (quote_match), the
        verdict of an unverified present element, and the rounding step.
    Inputs:
        path: Path - The configuration JSON; None reads ugs_config.default_path().
    Outputs:
        dict - quote (the quote settings), unverified_as and step.
    Raises:
        ValueError: As the readers, each naming its key and file (R3).
    """
    config = default_path() if path is None else Path(path)
    return {"quote": quote_match.read_quote_settings(config), "unverified_as": read_unverified_as(config),
            "step": read_grade_step(config), "max_elements": read_max_elements(config),
            "comment_openings": read_comment_openings(config)}


def read_comment_openings(path: Path) -> List[str]:
    """
    Purpose: Read the openings a comment may not start with: a comment on the whole report instead of its section
        (owner, 2026-11-27), case-folded at the time of the check.
    Inputs:
        path: Path - The configuration JSON, normally ugs_config.default_path().
    Outputs:
        List[str] - The forbidden openings, case-folded, non-empty.
    Raises:
        ValueError: If the file is unreadable, the key is absent or the value is not a non-empty list of text (R3).
    """
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read {path}: {exc}") from exc
    entry = raw.get(COMMENT_OPENINGS_KEY) if isinstance(raw, dict) else None
    if not isinstance(entry, dict) or "value" not in entry:
        raise ValueError(f"missing key '{COMMENT_OPENINGS_KEY}' in {path}")
    value = entry["value"]
    if not isinstance(value, list) or not value or not all(isinstance(text, str) and text.strip() for text in value):
        raise ValueError(f"'{COMMENT_OPENINGS_KEY}' must be a non-empty list of text in {path}")
    return [text.strip().casefold() for text in value]


def opens_forbidden(comment: Any, openings: List[str]) -> bool:
    """
    Purpose: Tell whether a comment opens on a forbidden opening, compared case-folded on its first words.
    Inputs:
        comment: Any - The comment of an answer; a non-text value never opens anything.
        openings: List[str] - The forbidden openings, case-folded.
    Outputs:
        bool - True when the comment starts with one of the openings.
    Raises:
        None.
    """
    if not isinstance(comment, str):
        return False
    head = " ".join(comment.split()).casefold()
    return any(head.startswith(opening) for opening in openings)


# The keys of a rated answer that only the code computes (review round 1, security): the model's values are never kept.
MODEL_DERIVED_KEYS = ("level", "score", "evidence")


def _name_key(name: Any) -> str:
    """
    Purpose: Give the key of an element name, for the deduplication of repeated elements (review round 2, item 6).
    Inputs:
        name: Any - The element name as the model gave it.
    Outputs:
        str - The name in lower case with its spaces collapsed; empty for a name that is not text.
    Raises:
        None.
    """
    return " ".join(name.split()).casefold() if isinstance(name, str) else ""


def prepare_elements(elements: List[dict], pages: List[str], settings: Dict[str, Any],
                     unverified_as: str, max_elements: int) -> Tuple[List[dict], int]:
    """
    Purpose: Verify each present or partial element's quote and give every element its effective verdict (review
        round 2, items 1 and 2). A repeated element name is counted once (item 6).
    Details: A present element whose quote no tier verifies takes the verdict unverified_as in the level. The verified
        page and tier replace the named ones, and page_corrected says the match is not on the named page.
    Inputs:
        elements: List[dict] - The elements of the answer, as the model gave them.
        pages: List[str] - The page texts of the report.
        settings: dict - The quote settings, from read_quote_settings.
        unverified_as: str - "partial" or "absent".
        max_elements: int - The most elements verified in one item (grade.max_elements); the rest are ignored.
    Outputs:
        Tuple[List[dict], int] - The verified elements (at most max_elements), and the number ignored beyond the cap.
            Each entry: element, verdict, effective, verified, tier, page, page_corrected,
            tiers_tried and quote.
    Raises:
        None.
    """
    distinct: List[dict] = []
    seen = set()
    for element in elements:
        key = _name_key(element.get("element"))
        if key in seen:
            continue
        seen.add(key)
        distinct.append(element)
    # Review round 2, item 3: the elements beyond the cap are ignored and counted, never verified.
    kept = distinct[:max_elements]
    prepared: List[dict] = []
    for element in kept:
        verdict = element.get("verdict")
        entry = {"id": element.get("id"), "element": element.get("element"), "verdict": verdict,
                 "page": element.get("page"),
                 "quote": element.get("quote"), "verified": False, "tier": None, "page_corrected": False,
                 "tiers_tried": []}
        if verdict in PRESENT_VERDICTS:
            found = quote_match.verify_element(element.get("quote"), element.get("page"), pages, settings)
            entry.update(verified=found["verified"], tier=found["tier"], tiers_tried=found["tiers_tried"],
                         page_corrected=found["page_corrected"])
            if found["verified"]:
                entry["page"] = found["page"]
        # An unverified present element takes unverified_as (review round 2, item 2); an unverified partial is absent
        # (review round 2 security, item 1): no credit is given for a quote that no tier verifies.
        if verdict == "present" and not entry["verified"]:
            entry["effective"] = unverified_as
        elif verdict == "partial" and not entry["verified"]:
            entry["effective"] = "absent"
        else:
            entry["effective"] = verdict
        prepared.append(entry)
    return prepared, len(distinct) - len(kept)


def checklist_count(item: dict) -> int:
    """
    Purpose: Give the number of elements the rubric item asks for, from its checklist or else its criteria (review
        round 2, item 6). Repeated entries count once.
    Inputs:
        item: dict - The rubric item.
    Outputs:
        int - The number of distinct checklist (or criteria) entries, zero when there are none.
    Raises:
        None.
    """
    for key in ("checklist", "criteria"):
        entries = item.get(key)
        if isinstance(entries, list) and entries:
            return len({_name_key(entry) for entry in entries if isinstance(entry, str) and entry.strip()})
    return 0


def with_level_score(answer: dict, item: dict, scale: GradeScale, step: Decimal, pages: List[str],
                     settings: Dict[str, Any], unverified_as: str, max_elements: int) -> dict:
    """
    Purpose: Verify the elements of a rated answer and compute its level, points and evidence from the verified verdicts
        (review round 2, items 1, 2 and 4). The model's level, score and evidence are never kept (security review).
        An exceptional claim holds only when every element is present and verified; otherwise it is dropped.
    Inputs:
        answer: dict - The model's answer.
        item: dict - The rubric item; its max_points is used.
        scale: GradeScale - The level scale.
        step: Decimal - The rounding step.
        pages: List[str] - The page texts of the report.
        settings: dict - The quote settings, from read_quote_settings.
        unverified_as: str - "partial" or "absent".
    Outputs:
        dict - The answer, with prepared elements, and level, score and evidence when the elements are usable. A
            not_applicable answer is returned unchanged, so check_grade_answer can refuse its payload.
    Raises:
        None.
    """
    if answer.get("status") != "rated":
        return answer
    answer = {key: value for key, value in answer.items() if key not in MODEL_DERIVED_KEYS}
    if not _elements_are_list_of_objects(answer.get("elements")):
        return answer
    source, cap = answer["elements"], max_elements
    rubric = item.get("elements") or []
    if rubric:
        # The rubric defines the elements (owner, 2026-11-27): each answer element is matched by id, its name is the
        # rubric text, and the cap of model-named elements does not apply. A mismatch is left for check_grade_answer.
        if not _ids_match(source, rubric):
            return answer
        by_id = {entry.get("id"): entry for entry in source}
        source = [dict(by_id[ref["id"]], element=ref["text"], id=ref["id"]) for ref in rubric]
        cap = len(rubric)
    elements, ignored = prepare_elements(source, pages, settings, unverified_as, cap)
    claimed = answer.get("exceptional") is True and all(entry["effective"] == "present" for entry in elements)
    level = level_for_elements(elements, claimed, scale)
    computed = dict(answer)
    computed["elements"] = elements
    computed["exceptional"] = claimed
    computed["elements_ignored"] = ignored
    computed["level"] = level
    computed["score"] = float(points_for_elements(elements, item.get("max_points", 0), scale, step))
    computed["losses"] = element_losses(elements, item.get("max_points", 0), scale)
    computed["evidence"] = [{"element": entry["element"], "page": entry["page"], "quote": entry["quote"]}
                            for entry in elements if entry["verified"] and entry["effective"] in PRESENT_VERDICTS]
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
    Purpose: Check one prepared answer against its rubric item, and name the first defect.
    Details: The answer must have been prepared by with_level_score, so each element carries its verified flag and its
        effective verdict. An item needs at least one verified present or partial element; when no element is present
        or partial, the item is accepted only with a non-empty missing text (review round 2, item 3). The elements must
        cover the checklist or criteria of the item (item 6). A quote no tier verifies is not a refusal here: it only
        leaves its element unverified. The message names a count, never a quote.
    Inputs:
        answer: dict - The prepared answer.
        item: dict - The rubric item, with its max_points, its optional flag and its checklist or criteria.
        pages: List[str] - The page texts (the verification is done by with_level_score, not here).
    Outputs:
        Tuple[str, str] - The code, and a short message: "ok" with an empty message on success.
    Raises:
        None.
    """
    status = answer.get("status")
    if status not in ("rated", "not_applicable"):
        return "unknown_status", "status must be rated or not_applicable"
    if status == "not_applicable":
        if answer.get("score") is not None or answer.get("evidence"):
            return "not_applicable_with_score", "not_applicable must carry no score and no evidence"
        if not item.get("optional"):
            return "not_applicable_not_allowed", "not_applicable is allowed only for an optional item"
        return "ok", ""

    elements = answer.get("elements")
    if elements is None or elements == []:
        return "elements_missing", "a rated item names the elements it requires"
    if not isinstance(elements, list):
        return "schema_invalid", "elements must be a list"
    if item.get("elements") and not _ids_match(elements, item["elements"]):
        return "elements_mismatch", "the answer must give a verdict for exactly the element ids of the item"
    for entry in elements:
        if not isinstance(entry, dict) or not isinstance(entry.get("element"), str) \
                or entry.get("verdict") not in VERDICTS:
            return "schema_invalid", "each element needs its name and a verdict: present, partial or absent"
    if len(elements) < checklist_count(item):
        return "elements_too_few", "the item asks for more elements than the answer names"

    engaged = [entry for entry in elements if entry.get("effective") in PRESENT_VERDICTS]
    if not engaged:
        if isinstance(answer.get("missing"), str) and answer["missing"].strip():
            return "ok", ""
        return "evidence_missing", "every element is absent: the item needs its missing text"
    if not any(entry.get("verified") for entry in engaged):
        return "evidence_missing", "no present or partial element has a quote found on its page"
    return "ok", ""


def _validate_grade_answer(
    answer: dict,
    item: dict,
    pages: List[str]
) -> Optional[str]:
    """
    Purpose: Give the message of the check of one answer, or None when it passes.
    Inputs:
        answer: dict - The prepared answer.
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
    Details: Empty at the maximum points or when every element is present and verified, when the answer has no
        `missing`, or when it is not a string. Otherwise the text is kept as the model gave it, stripped and cut to
        max_chars. It is model text saved in grade.json only: it never reaches the ledger note, a log or the dashboard
        (see ugs_run._grade_mark).
    Inputs:
        answer: dict - The prepared answer.
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
    if isinstance(elements, list) and elements and all(entry.get("effective") == "present" for entry in elements):
        return ""
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
    Purpose: Build the grade record of an answer, with its validation code (review round 2, item 2).
    Details: Only a rated answer whose level the code computed keeps its points, its evidence (verified quotes only)
        and its elements. Any refusal is status not_run with no score. The model_score is the element summary of the
        effective verdicts; the elements keep their verified flags and tiers and no quote (the quotes are in evidence).
    Inputs:
        item_id: str - The rubric item identifier.
        answer: dict - The prepared answer, or the raw answer of a refusal that no preparation reached.
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
    usable = answer.get("status") == "rated" and "level" in answer
    if code == "ok":
        status = answer.get("status")
        score = answer.get("score") if usable else None
    else:
        status = "not_run"
        score = None
    elements = answer.get("elements") if usable else []
    keep_evidence = code == "ok" and usable
    evidence = answer.get("evidence") if keep_evidence else []
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
        "level": answer.get("level") if usable else None,
        "elements_ignored": answer.get("elements_ignored", 0) if usable else 0,
        "losses": answer.get("losses", []) if usable else [],
        "elements": [] if not isinstance(elements, list) else [
            {"id": entry.get("id"), "element": entry.get("element"), "verdict": entry.get("verdict"),
             "effective": entry.get("effective"), "verified": entry.get("verified"), "tier": entry.get("tier"),
             "tiers_tried": entry.get("tiers_tried", []), "page": entry.get("page"),
             "page_corrected": entry.get("page_corrected", False)}
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


def _retry_note(ctx: StepContext, code: str, language: str) -> str:
    """
    Purpose: Build the note that asks the model again after a refusal that names its missing part. The wording lives in
        the retry_grade_item prompt file, never in code (R6).
    Inputs:
        ctx: StepContext - The step context; its prompts hold retry_grade_item.
        code: str - The refusal code, a key of RETRY_SECTION_BY_CODE.
        language: str - The report language, fr or en; it selects the section.
    Outputs:
        str - The note, stripped.
    Raises:
        PromptError: When the template or its section for this language is missing (R3).
    """
    section = RETRY_SECTION_BY_CODE[code]
    template = prompt_section(ctx.prompts["retry_grade_item"], f"{language}_{section}")
    return fill(template, {}).strip()


def _verified_count(answer: dict) -> int:
    """
    Purpose: Count the verified elements of a prepared answer, to keep the best answer across attempts (review round 2,
        item 2).
    Inputs:
        answer: dict - The prepared answer, or a raw one (then zero).
    Outputs:
        int - The number of elements whose quote a tier verified.
    Raises:
        None.
    """
    elements = answer.get("elements")
    if not isinstance(elements, list):
        return 0
    return sum(1 for entry in elements if isinstance(entry, dict) and entry.get("verified"))


def _item_text(item: dict) -> str:
    """
    Purpose: The ITEM text of the grader prompt: the rubric section, then its elements with their ids when the rubric
        lists them (owner, 2026-11-27), so the model answers each id.
    Inputs:
        item: dict - The rubric item, with its optional elements (id and text).
    Outputs:
        str - The text of the item for the prompt.
    Raises:
        None.
    """
    text = item_prompt_text(item)
    rubric = item.get("elements") or []
    if not rubric:
        return text
    lines = ["%s: %s" % (ref["id"], ref["text"]) for ref in rubric]
    return text + "\n\nElements to judge, one verdict for each id:\n" + "\n".join(lines)


def grade_item(
    item: dict,
    pages: List[str],
    call: Callable,
    ctx: StepContext,
    language: str,
    calibration_note: str,
    report_id: Optional[str] = None,
    missing_max_chars: Optional[int] = None,
    settings: Optional[Dict[str, Any]] = None
) -> dict:
    """
    Purpose: Grade a single rubric item.
    Details: When ctx.emit is set, one `read` record gives the page range selected and one `call` record each model
        call, both with identifiers only (R11). With no emitter nothing is recorded. Each answer is verified element by
        element; an answer refused for a structural reason is asked again (retry_grade_item), and the record is built
        from the answer with the most verified elements across the attempts (review round 2, item 2).
    Inputs:
        item: dict - The rubric item.
        pages: List[str] - The page texts.
        call: Callable - The model call function.
        ctx: StepContext - The context for the step.
        language: str - The language of the report.
        calibration_note: str - The current calibration note.
        report_id: str or None - The identifier of the report, for the action records only.
        missing_max_chars: int or None - The limit of the missing text; None reads grade.missing_max_chars once.
        settings: dict or None - The grade settings from read_grade_settings; None reads the configuration.
    Outputs:
        dict - The grade record: item_id, status, score, comment, evidence, missing, audit, flag, model_score,
            validation, attempts, level and elements.
    Raises:
        NotRun: If the model fails with an unretryable error (an unreachable daemon, for example).
    """
    item_id = item["id"]
    if missing_max_chars is None:
        missing_max_chars = read_missing_max_chars(default_path())
    settings = read_grade_settings() if settings is None else settings

    # Determine pages to send
    budget_tokens = ctx.window_tokens - ctx.reserve_tokens

    # Estimate overhead: token count of filled prompt with empty sections
    prompt_template = ctx.prompts["grade_item"]
    overhead_prompt = fill(prompt_template, {
        "ITEM": _item_text(item),
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
    quote_settings = settings["quote"]
    unverified_as = settings["unverified_as"]
    max_elements = settings["max_elements"]
    step = settings["step"]
    openings = settings["comment_openings"]

    last_error_reason = None
    last_retry_note = ""
    code = "schema_invalid"
    scope_asked = False  # a comment on the whole report is asked again once, then its sentence is dropped
    best = None  # (answer, code, verified count): the answer with the most verified elements across the attempts
    for attempt in range(ctx.grade_retries + 1):
        current_note = calibration_note
        if last_retry_note:
            current_note = f"{calibration_note}\n{last_retry_note}" if calibration_note else last_retry_note
        elif last_error_reason:
            current_note = f"{calibration_note}\nPrevious refusal: {last_error_reason}" if calibration_note else f"Previous refusal: {last_error_reason}"

        prompt = fill(prompt_template, {
            "ITEM": _item_text(item),
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
            continue

        answer = with_level_score(answer, item, scale, step, pages, quote_settings, unverified_as, max_elements)
        code, message = check_grade_answer(answer, item, pages)
        if code == "ok" and opens_forbidden(answer.get("comment"), openings):
            if not scope_asked:
                scope_asked = True
                last_error_reason = message = "the comment opens on the whole report, not on this section"
                last_retry_note = _retry_note(ctx, "comment_scope", language)
                continue
            # Asked again and still on the whole report: the model sentence is dropped, the code justification stays.
            record = _record_from_answer(item_id, dict(answer, comment=""), "ok", attempt + 1,
                                         item.get("max_points", 0), missing_max_chars)
            record["comment_code"] = "comment_scope"
            return record
        if code == "ok":
            return _record_from_answer(item_id, answer, "ok", attempt + 1, item.get("max_points", 0), missing_max_chars)
        support = _verified_count(answer)
        if best is None or support >= best[2]:
            best = (answer, code, support)
        last_error_reason = message
        last_retry_note = _retry_note(ctx, code, language) if code in RETRY_SECTION_BY_CODE else ""

    attempts = ctx.grade_retries + 1
    if best is None:
        return _no_answer_record(item_id, code, attempts, "")
    return _record_from_answer(item_id, best[0], best[1], attempts, item.get("max_points", 0), missing_max_chars)


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
