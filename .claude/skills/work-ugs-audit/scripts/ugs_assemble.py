import json
from pathlib import Path
from typing import Callable, List, Dict, Any, Optional

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))

_SKILLS_DIR = Path(__file__).resolve().parent.parent.parent
_FIGURE_REVIEW_SCRIPTS = _SKILLS_DIR / "figure-review" / "scripts"
_SHIPPED_CRITERIA = _SKILLS_DIR / "figure-review" / "assets" / "figure_criteria.json"
sys.path.insert(0, str(_FIGURE_REVIEW_SCRIPTS))

from figure_checks import failure_comment, load_criteria
from grade_total import compute
from pdf_annotate import annotate
from pdf_annex import DEFAULT_LABELS, render_rows, build_html, append_annex, load_labels
from ref_check import check_all, _default_resolver
from ugs_text import split_body_and_references

REPORT_LANGUAGES = ("fr", "en")


def grade_annotations(rubric: dict, grade: dict) -> List[dict]:
    """
    Purpose: Generate annotations for rated items with evidence.
    Inputs:
        rubric: dict - The rubric definition.
        grade: dict - The grade data.
    Outputs:
        List[dict] - List of annotation dictionaries.
    """
    annotations = []
    for item in grade.get("items", []):
        if item.get("status") != "rated":
            continue
        item_id = item.get("item_id")
        score = item.get("score")
        comment = item.get("comment", "")
        max_points = None
        for r_item in rubric.get("items", []):
            if r_item.get("id") == item_id:
                max_points = r_item.get("max_points")
                break
        
        if max_points is None:
            continue

        for evidence in item.get("evidence", []):
            annotations.append({
                "page": evidence.get("page"),
                "kind": "technical",
                "code": item_id,
                "quote": evidence.get("quote"),
                "rect": None,
                "comment": f"{item_id} {score} / {max_points}: {comment}"
            })
    return annotations


def _check_language(language: str) -> None:
    """
    Purpose: Refuse a report language other than the two the annex and the prompts are written in.
    Inputs:
        language: str - Language code read from the report.
    Outputs:
        None.
    Raises:
        ValueError: If the language is neither "fr" nor "en" (named in the message, no silent English).
    """
    if language not in REPORT_LANGUAGES:
        raise ValueError(f"Unknown report language: {language!r}; expected one of {', '.join(REPORT_LANGUAGES)}")


def figure_annotations(figures: dict, criteria: Optional[List[dict]] = None, language: str = "en") -> List[dict]:
    """
    Purpose: Generate annotations for failed figure criteria, with the comment in the report language
        when the criterion is judged by a script.
    Details: A criterion judged by a script takes its comment from the criteria data (failure_comment). A
        criterion judged by a model keeps the reason the model wrote. Without criteria, every comment is
        the reason, as before.
    Inputs:
        figures: dict - The figures data.
        criteria: Optional[List[dict]] - Criteria of figure-review (each with id, judged_by and comments).
        language: str - Report language, "fr" or "en".
    Outputs:
        List[dict] - List of annotation dictionaries.
    Raises:
        ValueError: If the language is neither "fr" nor "en".
    """
    _check_language(language)
    criteria_list = criteria or []
    by_id = {crit["id"]: crit for crit in criteria_list}
    annotations = []
    for figure in figures.get("figures", []):
        page = figure.get("page")
        rect = figure.get("rect")
        criteria_results = figure.get("criteria", {})
        for criterion_id, result in criteria_results.items():
            if result.get("verdict") == "fail":
                comment = result.get("reason", "")
                criterion = by_id.get(criterion_id)
                if criterion is not None and criterion.get("judged_by") == "script":
                    comment = failure_comment(criterion_id, criteria_list, language)
                if comment:
                    annotations.append({
                        "page": page,
                        "kind": "figure",
                        "code": criterion_id,
                        "quote": None,
                        "rect": rect,
                        "comment": comment
                    })
    return annotations


def reference_annotations(results: List[dict], entries: List[dict], comments: dict, language: str, quote_chars: int) -> List[dict]:
    """
    Purpose: Generate annotations for problematic references.
    Inputs:
        results: List[dict] - Results from ref_check.
        entries: List[dict] - Reference entries with page and text.
        comments: dict - Mapping of code to comments by language.
        language: str - Language code ('en' or 'fr').
        quote_chars: int - Max characters for quote.
    Outputs:
        List[dict] - List of annotation dictionaries.
    """
    annotations = []
    for i, result in enumerate(results):
        status = result.get("status")
        cited = result.get("cited")
        code = None
        if status in ("malformed", "unreachable", "blocked"):
            code = status
        elif cited is False:
            code = "uncited"
        
        if code:
            entry = entries[i] if i < len(entries) else {}
            text = entry.get("text", "")
            quote = text[:quote_chars] if quote_chars > 0 else text
            comment_text = comments.get(code, {}).get(language, code)
            annotations.append({
                "page": entry.get("page"),
                "kind": "reference",
                "code": code,
                "quote": quote,
                "rect": None,
                "comment": comment_text
            })
    return annotations


def assemble_report(src_pdf: Path, report_dir: Path, report_id: str, loop: int, rubric: dict, pages: List[str], language: str, settings: dict, fetch: Optional[Callable], criteria: Optional[List[dict]] = None) -> dict:
    """
    Purpose: Assemble the annotated report PDF with annex and compute totals.
    Inputs:
        src_pdf: Path - Path to source PDF.
        report_dir: Path - Directory for report outputs.
        report_id: str - Report ID.
        loop: int - Loop number.
        rubric: dict - Rubric definition.
        pages: List[str] - Page texts.
        language: str - Language code, "fr" or "en".
        settings: dict - Settings including colors, author, etc.
        fetch: Optional[Callable] - Fetch function for ref_check.
        criteria: Optional[List[dict]] - Figure criteria; None loads the shipped figure-review criteria.
    Outputs:
        dict - Summary of the assembly process.
    Raises:
        ValueError: If a required setting is missing, or the language is neither "fr" nor "en".
    """
    _check_language(language)
    required_settings = ["colors", "author", "quote_chars", "url_timeout_s", "max_retries", "patterns", "ref_comments", "annex_template"]
    for key in required_settings:
        if key not in settings:
            raise ValueError(f"Missing setting: {key}")

    # Read grade
    grade_path = report_dir / "grade.json"
    grade = json.loads(grade_path.read_text(encoding="utf-8"))

    # Compute totals
    totals = compute(rubric, grade)
    (report_dir / "totals.json").write_text(json.dumps(totals, indent=2), encoding="utf-8")

    # Read optional files
    language_path = report_dir / "language.json"
    language_data = json.loads(language_path.read_text(encoding="utf-8")) if language_path.exists() else None

    figures_path = report_dir / "figures.json"
    figures_data = json.loads(figures_path.read_text(encoding="utf-8")) if figures_path.exists() else None

    # Generate annotations
    annotations = []
    annotations.extend(grade_annotations(rubric, grade))
    
    if language_data:
        # ugs_language.py returns "annotations" key
        findings = language_data.get("annotations", language_data.get("findings", []))
        for finding in findings:
            annotations.append({
                "page": finding.get("page"),
                "kind": "language",
                "code": finding.get("code"),
                "quote": finding.get("quote"),
                "rect": None,
                "comment": finding.get("comment", "")
            })

    if figures_data:
        figure_criteria = criteria if criteria is not None else load_criteria(_SHIPPED_CRITERIA)["criteria"]
        annotations.extend(figure_annotations(figures_data, figure_criteria, language))

    # Reference annotations
    body_text, refs = split_body_and_references(pages)
    if refs:
        ref_results = check_all(
            [r["text"] for r in refs],
            body_text,
            settings["patterns"],
            fetch,
            settings["url_timeout_s"],
            settings["max_retries"],
            _default_resolver,
            0
        )
        annotations.extend(reference_annotations(ref_results, refs, settings["ref_comments"], language, settings["quote_chars"]))

    (report_dir / "annotations.json").write_text(json.dumps(annotations, indent=2), encoding="utf-8")

    # Annotate PDF
    dst_pdf = report_dir / "annotated.pdf"
    annotate_result = annotate(
        src_pdf,
        annotations,
        dst_pdf,
        settings["colors"],
        settings["author"]
    )

    # Append annex
    template = settings["annex_template"]
    # The labels come from the report language, through the same label file pdf_annex.main reads.
    labels = load_labels(DEFAULT_LABELS, language)
    rows = render_rows(rubric, grade, totals, labels)
    html_text = build_html(template, rows, report_id, loop, totals.get("total"), labels)
    annex_pages = append_annex(dst_pdf, html_text)

    return {
        "report_id": report_id,
        "placed": annotate_result["placed"],
        "not_found": annotate_result["not_found"],
        "duplicates": annotate_result["duplicates"],
        "annex_pages": annex_pages,
        "complete": totals["complete"],
        "percent": totals["percent"]
    }


if __name__ == "__main__":
    pass
