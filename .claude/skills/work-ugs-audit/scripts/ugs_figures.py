"""
ugs_figures.py - the figure step of the grading of one report (Issue #104).

It extracts the figures of the PDF, runs the script-measured criteria, and when a vision model is validated
gives each new figure ONE model call on its fitted image, then one call on a contact sheet for the style
across figures. Only the criteria of the `undergraduate` scope are applied: a research-only criterion of the
shared criteria file is never sent to a model. A model answer naming an id that was not sent is refused and
the call repeated. Unretryable NotRun kinds propagate.
"""
import re
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

# Add figure-review scripts to path
_FR_SCRIPTS = Path(__file__).resolve().parent.parent.parent / "figure-review" / "scripts"
if str(_FR_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_FR_SCRIPTS))

from figure_extract import extract
from figure_checks import check, body_font_size, failure_comment, criteria_for_scope
from figure_image import fit_for_model, contact_sheet
from ugs_text import StepContext, fill, prompt_section
from ugs_bridge import NotRun
from ugs_tables import figure_records

SCOPE = "undergraduate"
RETRYABLE_KINDS = ("unparsable", "invalid")
VERDICTS = ("pass", "fail", "not_applicable")
DEFAULT_KIND = "other"
SET_CRITERION_ID = "style_consistency"
EXTRACTION_KEYS = ("min_area_pt2", "background_threshold", "max_long_edge", "photo_colors", "jpeg_quality")
POINTS_PER_INCH = 72.0  # points per inch, the unit of a PDF rectangle


def citing_text(pages: List[str], number: int) -> str:
    """
    --------------------------------------------------------------------------
    Purpose:
        Find the first paragraph that cites a figure without being its caption.

    Inputs:
        pages (list[str]): the page texts
        number (int): the figure number

    Outputs:
        text (str): the first blank-line paragraph that mentions `Figure N` or `Fig. N` and does not start
        with it, or an empty string.
    --------------------------------------------------------------------------
    """
    pattern = rf"(?:Figure|Fig\.)\s*{number}\b"
    starts = (f"Figure {number}", f"Fig. {number}")
    for page in pages:
        for paragraph in page.split("\n\n"):
            if re.search(pattern, paragraph) and not paragraph.strip().startswith(starts):
                return paragraph.strip()
    return ""


def _setting(criteria_doc: Dict[str, Any], key: str) -> Any:
    """Read one value of the `extraction` block; a missing key is named (R3)."""
    try:
        return criteria_doc["extraction"][key]["value"]
    except KeyError:
        raise KeyError(f"missing extraction.{key} in the figure criteria") from None


def _effective_dpi(figure: Dict[str, Any]) -> Optional[float]:
    """Pixel width over the displayed width in inches, one decimal, for a raster figure; else None."""
    size, rect = figure.get("pixel_size"), figure.get("rect")
    if not size or not rect or rect[2] <= rect[0]:
        return None
    return round(size[0] / ((rect[2] - rect[0]) / POINTS_PER_INCH), 1)


def _valid_figure_answer(answer: Any, sent_ids: List[str]) -> bool:
    """True when the answer has a kind and only criteria that were sent, each with a known verdict."""
    if not isinstance(answer, dict) or not isinstance(answer.get("kind"), str):
        return False
    items = answer.get("criteria")
    if not isinstance(items, list):
        return False
    return all(isinstance(i, dict) and i.get("id") in sent_ids and i.get("verdict") in VERDICTS for i in items)


def _ask(call: Callable, prompt: str, schema: Any, images: List[str], retries: int,
         accepts: Callable[[Any], bool]) -> Optional[Dict[str, Any]]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Call the model until its answer is accepted, at most `retries` + 1 times.

    Inputs:
        call (Callable): the injected model call
        prompt, schema, images: the call arguments
        retries (int): the number of repeats after the first call
        accepts (Callable): the check an answer must pass to be kept

    Outputs:
        answer (dict | None): the accepted answer, or None when every attempt was invalid.

    Raises:
        NotRun: a kind that is not retryable propagates.
    --------------------------------------------------------------------------
    """
    for _ in range(retries + 1):
        try:
            answer = call(prompt, schema, images)
        except NotRun as exc:
            if exc.kind in RETRYABLE_KINDS:
                continue
            raise
        if accepts(answer):
            return answer
    return None


def _judge_figure(record: Dict[str, Any], fig: Dict[str, Any], criteria: List[Dict[str, Any]], pages: List[str],
                  report_dir: Path, call: Callable, ctx: StepContext, language: str, settings: Dict[str, int]) -> None:
    """Fit the image, ask the model once about the figure and write the verdicts into the record."""
    figure_id = record["figure_id"]
    fitted = fit_for_model(report_dir / "figures" / fig["file"], report_dir / "model_images", settings["max_long_edge"],
                           settings["photo_colors"], settings["jpeg_quality"])
    record["model_image"] = fitted["file"]
    sent = []
    for crit in criteria:
        script_verdict = fig["criteria"].get(crit["id"], {}).get("verdict")
        if crit["level"] == "figure" and (crit["judged_by"] == "model" or
                                          (crit.get("model_when_script_not_run") and script_verdict == "not_run")):
            sent.append(crit)
    sent_ids = [c["id"] for c in sent]
    number = int(figure_id[1:])
    prompt = fill(prompt_section(ctx.prompts["figure"], "single"), {
        "CAPTION": record["caption"] or "",
        "CITING_TEXT": citing_text(pages, number),
        "SCRIPT_VERDICTS": "\n".join(f"{cid}: {v['verdict']} ({v['reason']})" for cid, v in fig["criteria"].items()),
        "CRITERIA": "\n".join(f"{c['id']} | {c[f'label_{language}']} | applies to: {', '.join(c['applies_to'])}"
                              for c in sent),
    })
    answer = _ask(call, prompt, ctx.schemas["figure"], [str(report_dir / "model_images" / fitted["file"])],
                  ctx.grade_retries, lambda a: _valid_figure_answer(a, sent_ids))
    if answer is None:
        for cid in sent_ids:
            record["criteria"][cid] = {"verdict": "not_run", "reason": "invalid_answer"}
        return
    record["kind"] = answer["kind"]
    answered = {item["id"]: item for item in answer["criteria"]}
    for crit in sent:
        cid, item = crit["id"], answered.get(crit["id"])
        if item is None:
            record["criteria"][cid] = {"verdict": "not_run", "reason": "no_answer"}
        elif "all" not in crit["applies_to"] and record["kind"] not in crit["applies_to"]:
            record["criteria"][cid] = {"verdict": "not_applicable", "reason": "not_applicable_to_kind"}
        else:
            reason = item.get("reason", "")
            result = {"verdict": item["verdict"], "reason": reason}
            if item["verdict"] == "fail":
                result["comment"] = f"{failure_comment(cid, criteria, language)} {reason}"
            record["criteria"][cid] = result


def _judge_style(figures: List[Dict[str, Any]], criteria: List[Dict[str, Any]], report_dir: Path, call: Callable,
                 ctx: StepContext, language: str, max_long_edge: int) -> Dict[str, Any]:
    """One call on a contact sheet of every fitted figure; returns the `report_criteria` mapping."""
    crit = next((c for c in criteria if c["id"] == SET_CRITERION_ID), None)
    files = [report_dir / "model_images" / f["model_image"] for f in figures if f.get("model_image")]
    if crit is None or len(files) < 2:
        return {}
    sheet = contact_sheet(files, report_dir / "model_images" / "sheet.png", max_long_edge)
    prompt = fill(prompt_section(ctx.prompts["figure"], "set"),
                  {"FIGURE_COUNT": str(len(files)), "CRITERION": crit[f"label_{language}"]})
    answer = _ask(call, prompt, ctx.schemas["figure_set"], [str(report_dir / "model_images" / sheet["file"])],
                  ctx.grade_retries,
                  lambda a: isinstance(a, dict) and a.get("verdict") in VERDICTS)
    if answer is None:
        return {SET_CRITERION_ID: {"verdict": "not_run", "reason": "invalid_answer"}}
    return {SET_CRITERION_ID: {"verdict": answer["verdict"], "reason": answer.get("reason", ""),
                               "figures_involved": answer.get("figures_involved", [])}}


def figures_report(
    pdf: Path,
    report_dir: Path,
    report_id: str,
    pages: List[str],
    call: Callable,
    ctx: StepContext,
    criteria_doc: Dict[str, Any],
    language: str,
    vision_ok: bool,
    existing: Optional[Dict[str, Any]] = None,
    on_figure: Optional[Callable[[str, Dict[str, Any]], None]] = None,
    elements: Optional[List[Dict[str, Any]]] = None
) -> Dict[str, Any]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Extract and judge the figures of one report.

    Details:
        Script criteria are always recorded. With a validated vision model each figure not already in
        `existing` gets one call, and two or more figures get one more call on a contact sheet for the
        style across figures, written to `report_criteria` and never to a figure. Without it the model
        criteria are `not_run` with reason `vision_not_validated` and no call is made. A criterion that
        does not apply to the kind the model named becomes `not_applicable` whatever it said, one it did
        not answer is `not_run` with reason `no_answer`, and a failed one carries the ready comment and the
        reason. Only criteria of the undergraduate scope are applied.
        When `elements` is given (the records of elements.json), those figure records are the raw list and
        the PDF is not extracted again: the figure files must already be in `report_dir / "figures"`.

    Inputs:
        pdf (Path): the report PDF
        report_dir (Path): the report folder, where `figures` and `model_images` are written
        report_id (str): the report id
        pages (list[str]): the page texts
        call (Callable): the model call, injected
        ctx (StepContext): prompts (`figure`), schemas (`figure`, `figure_set`) and `grade_retries`
        criteria_doc (dict): the figure criteria file
        language (str): `fr` or `en`
        vision_ok (bool): whether the vision model was validated
        existing (dict | None): records already judged, by figure id, not judged again
        on_figure (Callable | None): called with the id and the record after each figure
        elements (list[dict] | None): the element records of the report; when given, only their figure
            records are judged and no extraction runs (None keeps the extraction)

    Outputs:
        report (dict): `report_id`, `figures` (a record per figure) and `report_criteria`.

    Raises:
        NotRun: a model kind that is not retryable.
        KeyError: an `extraction` key is missing from the criteria file.
        TablesError: an element record of a figure has no id, page or rect.
    --------------------------------------------------------------------------
    """
    existing = existing or {}
    settings = {key: _setting(criteria_doc, key) for key in EXTRACTION_KEYS}
    criteria = criteria_for_scope(criteria_doc, SCOPE)
    figures_dir = report_dir / "figures"
    figures_dir.mkdir(parents=True, exist_ok=True)
    if elements is None:
        raw = extract(pdf, figures_dir, settings["min_area_pt2"], settings["background_threshold"])
    else:
        raw = figure_records(elements)
    checked = check(raw, pages, body_font_size(pdf), criteria_doc)

    figures = []
    for fig in checked:
        figure_id = fig["figure_id"]
        if figure_id in existing:
            figures.append(existing[figure_id])
            if on_figure:
                on_figure(figure_id, existing[figure_id])
            continue
        record = {
            "figure_id": figure_id, "page": fig["page"], "rect": fig["rect"], "file": fig["file"],
            "kind": DEFAULT_KIND, "drawing_area_ratio": fig.get("drawing_area_ratio"),
            "effective_dpi": _effective_dpi(fig), "caption": fig.get("caption"),
            "cited_in_text": bool(citing_text(pages, int(figure_id[1:]))), "criteria": dict(fig["criteria"]),
            "model_image": None,
        }
        if vision_ok:
            _judge_figure(record, fig, criteria, pages, report_dir, call, ctx, language, settings)
        else:
            for crit in criteria:
                if crit["level"] == "figure" and crit["judged_by"] == "model":
                    record["criteria"][crit["id"]] = {"verdict": "not_run", "reason": "vision_not_validated"}
        figures.append(record)
        if on_figure:
            on_figure(figure_id, record)

    report_criteria = {}
    if vision_ok:
        report_criteria = _judge_style(figures, criteria, report_dir, call, ctx, language, settings["max_long_edge"])
    return {"report_id": report_id, "figures": figures, "report_criteria": report_criteria}
