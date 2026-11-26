import json
import re
import os
from pathlib import Path
from typing import Callable, List, Dict, Any, Optional, Tuple

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))

_SKILLS_DIR = Path(__file__).resolve().parent.parent.parent
_FIGURE_REVIEW_SCRIPTS = _SKILLS_DIR / "figure-review" / "scripts"
_SHIPPED_CRITERIA = _SKILLS_DIR / "figure-review" / "assets" / "figure_criteria.json"
sys.path.insert(0, str(_FIGURE_REVIEW_SCRIPTS))

from figure_checks import failure_comment, load_criteria
from grade_total import compute
from pdf_annotate import annotate
from pdf_annex import DEFAULT_LABELS, TITLE_KIND_CODES, render_rows, build_html, append_annex, load_labels, render_checks
from ref_check import check_all, _default_resolver
from ugs_text import REF_HEADING_RE, split_body_and_references
from ugs_tables import load_elements
import ugs_config
import element_labels
import crossref_checks
import front_matter
from crossref_checks import (TITLE_KIND_CHECK_ID, run_checks, load_settings as load_checks_settings, DEFAULT_MARKERS_PATH,
                             misplaced_citations, load_citation_rules)

REPORT_LANGUAGES = ("fr", "en")
CHECKS_FILE_NAME = "checks.json"
CITATION_CHECK_ID = crossref_checks.CITATION_CHECK_ID
FIGURE_COUNT_CHECK_ID = crossref_checks.FIGURE_COUNT_CHECK_ID
TABLE_COUNT_CHECK_ID = crossref_checks.TABLE_COUNT_CHECK_ID
UNTITLED_CHECK_ID = crossref_checks.UNTITLED_CHECK_ID
APPENDIX_CHECK_ID = crossref_checks.APPENDIX_CHECK_ID
APPENDIX_STATUS = {"ok": "ok", "not_ok": "not_ok", "not_applicable": "not_applicable"}
CITATION_CODE = "CIT"
CITATION_KIND = "citation"
META_NAME_KEY = "reports.meta_file_name"
ELEMENTS_NAME_KEY = "reports.elements_file_name"
EXCLUDED_PAGES_KEY = "excluded_pages"


def _body_pages(pages: List[str]) -> List[str]:
    """
    Purpose: Keep the pages before the reference list, the only pages a citation placement is judged on (N5).
    Details: The page holding the reference heading is kept up to that heading (F6); later pages are dropped.
    Inputs:
        pages: List[str] - the page texts of the report.
    Outputs:
        List[str] - the body pages, all of them when no reference list is found.
    Raises:
        None.
    """
    for index in range(1, len(pages) + 1):
        if split_body_and_references(pages[:index])[1]:
            kept = []
            for line in pages[index - 1].split("\n"):  # F6: the body lines before the reference heading stay
                if REF_HEADING_RE.match(line.strip()):
                    break
                kept.append(line)
            return pages[:index - 1] + ["\n".join(kept)]
    return list(pages)


def citation_placement_row(body_pages: List[str], language: str) -> dict:
    """
    Purpose: Build the check row of misplaced citations for checks.json and the annex (N5).
    Inputs:
        body_pages: List[str] - the body page texts (see _body_pages).
        language: str - the report language, selecting the abbreviations of citation_rules.json.
    Outputs:
        dict - {"id", "status" (ok or not_ok), "detail": {"count": n}}.
    Raises:
        CrossrefConfigError: the citation rules file lacks the language (R3).
    """
    found = misplaced_citations(body_pages, load_citation_rules(language))
    status = "ok" if not found else "not_ok"
    return {"id": CITATION_CHECK_ID, "status": status, "detail": {"count": len(found)}}


def citation_annotations(body_pages: List[str], language: str) -> List[dict]:
    """
    Purpose: One annotation per misplaced citation, with its quote and its comment in the report language (N5).
    Inputs:
        body_pages: List[str] - the body page texts (see _body_pages).
        language: str - the report language.
    Outputs:
        List[dict] - annotations with page, kind, code, quote, rect and comment.
    Raises:
        CrossrefConfigError: the citation rules file lacks the language (R3).
    """
    comment = load_labels(DEFAULT_LABELS, language)["citation_comment"]
    return [{"page": found["page"], "kind": CITATION_KIND, "code": CITATION_CODE, "quote": found["quote"],
             "rect": None, "comment": comment}
            for found in misplaced_citations(body_pages, load_citation_rules(language))]


COUNT_STATUS_TO_CHECK = {"ok": "ok", "mismatch": "not_ok", "not_found": "not_applicable"}


def title_kind_row(figures: Optional[dict]) -> dict:
    """
    --------------------------------------------------------------------------
    Purpose:
        Build the title_kind check row of the annex (N7, plan 20): every element whose printed title contradicts its
        kind, by id.

    Details:
        Ok when no element is flagged, not_ok with the ids otherwise. An absent figures file, or one written before
        the title_kind_mismatch key existed, is not_applicable, never ok: an old run must not read as a pass.

    Inputs:
        figures (dict | None): the figures.json of the report, None when absent.

    Outputs:
        row (dict): id, status and detail (ids only).

    Raises:
        None.
    --------------------------------------------------------------------------
    """
    records = (figures or {}).get("figures", [])
    if not any("title_kind_mismatch" in record for record in records):
        return {"id": TITLE_KIND_CHECK_ID, "status": "not_applicable", "detail": {}}
    ids = [record["figure_id"] for record in records if record.get("title_kind_mismatch")]
    if not ids:
        return {"id": TITLE_KIND_CHECK_ID, "status": "ok", "detail": {}}
    return {"id": TITLE_KIND_CHECK_ID, "status": "not_ok", "detail": {"ids": ids}}


def title_kind_annotations(figures: dict, language: str) -> List[dict]:
    """
    --------------------------------------------------------------------------
    Purpose:
        One PDF annotation per element whose title contradicts its kind (N7, plan 20), on the printed caption, with
        the comment of its code in the report language.

    Inputs:
        figures (dict): the figures.json of the report.
        language (str): "fr" or "en".

    Outputs:
        annotations (list[dict]): page, kind, code, quote (the caption), rect and comment, as the other annotations.

    Raises:
        AnnexError: from load_labels when a comment is missing from annex_labels.json (R3).
    --------------------------------------------------------------------------
    """
    comments = load_labels(DEFAULT_LABELS, language)["title_kind_comments"]
    annotations = []
    for record in figures.get("figures", []):
        code = record.get("title_kind_mismatch")
        if code not in TITLE_KIND_CODES:
            continue
        annotations.append({"page": record.get("page"), "kind": "figure", "code": code,
                            "quote": record.get("caption") or None, "rect": record.get("rect"),
                            "comment": comments[code]})
    return annotations


def count_rows(meta: dict) -> List[dict]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Turn the declared against extracted counts of a report (report_meta.json, plan 6, E2) into two check rows,
        one for the figures and one for the tables, shown in the annex.

    Details:
        A mismatch is `not_ok` and shows the declared and the extracted count; a list not found, or a report prepared
        before the counts existed, is `not_applicable` with no number. The printed numbers that differ stay in
        report_meta.json: the annex shows the counts only.

    Inputs:
        meta (dict): the report_meta.json of the report ({} when the file is absent).

    Outputs:
        List[dict]: the rows figure_counts, table_counts and untitled_elements, each with id, status and detail.

    Raises:
        None.
    --------------------------------------------------------------------------
    """
    rows = []
    for check_id, kind in ((FIGURE_COUNT_CHECK_ID, "figure"), (TABLE_COUNT_CHECK_ID, "table")):
        status = COUNT_STATUS_TO_CHECK.get(meta.get(f"{kind}_count_status"), "not_applicable")
        detail: dict = {}
        if status in ("ok", "not_ok"):
            detail = {"declared": meta[f"declared_{kind}s"], "extracted": meta[f"extracted_{kind}s"]}
        rows.append({"id": check_id, "status": status, "detail": detail})
    if "untitled_figures" in meta or "untitled_tables" in meta:
        untitled = meta.get("untitled_figures", {}).get("count", 0) + meta.get("untitled_tables", {}).get("count", 0)
        rows.append({"id": UNTITLED_CHECK_ID, "status": "not_ok" if untitled else "ok", "detail": {"count": untitled}})
    else:  # a report prepared before this check existed: not applicable, never zero
        rows.append({"id": UNTITLED_CHECK_ID, "status": "not_applicable", "detail": {}})
    return rows


def _plain_line(line: str) -> str:
    """
    --------------------------------------------------------------------------
    Purpose:
        Remove the markup of a Markdown line (heading marks, bold, italics, table bars) before a heading test.

    Inputs:
        line (str): one line of a page text.

    Outputs:
        str: the stripped line.

    Raises:
        None.
    --------------------------------------------------------------------------
    """
    return re.sub(r"[#*_|]", "", line).strip()


def appendix_row(pages: List[str], meta: dict) -> dict:
    """
    --------------------------------------------------------------------------
    Purpose:
        Build the annex row that checks the appendices of a report (plan 15, N4): each appendix listed in the
        contents is found after the references, and each one found there is listed.

    Details:
        The reference heading is searched from the body start (review round 1 I3), so a contents line 'Références'
        does not start the end. The heading test is the one of ugs_text, after the Markdown markup is removed.

    Inputs:
        pages (List[str]): the text of each page, index 0 for page 1.
        meta (dict): report_meta.json; its front_roles give the contents pages and body_start the search start.

    Outputs:
        dict: id, status and detail; the detail holds missing (listed, not found) and extra (found, not listed) ids.

    Raises:
        FrontMatterEntryError: when the appendix settings are missing from the data file.
    --------------------------------------------------------------------------
    """
    roles = meta.get("front_roles") or {}
    body_start = roles.get("body_start") or 1
    end_start = next((index + 1 for index in range(max(body_start, 1) - 1, len(pages))
                      if any(REF_HEADING_RE.match(_plain_line(line)) for line in pages[index].splitlines())), None)
    result = crossref_checks.appendix_check(pages, roles.get("table_of_contents"), end_start,
                                            front_matter.load_appendix_settings())
    status = APPENDIX_STATUS[result["status"]]
    detail: dict = {}
    if status in ("ok", "not_ok"):
        detail = {"missing": result["listed_missing"], "extra": result["unlisted_present"]}
    return {"id": APPENDIX_CHECK_ID, "status": status, "detail": detail}


def _read_report_meta(path: Path) -> dict:
    """
    --------------------------------------------------------------------------
    Purpose:
        Read the report_meta.json of a report; a file that is absent gives an empty dict (no count is then judged).

    Inputs:
        path (Path): the metadata file of the report.

    Outputs:
        dict: the parsed object, or {} when the file does not exist.

    Raises:
        ValueError: when the file exists but is not a JSON object.
    --------------------------------------------------------------------------
    """
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} must hold a JSON object")
    return data


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


def _atomic_write_text(path: Path, text: str) -> None:
    """
    Purpose: Write a text file in one step: the content goes to a temporary file beside it, then replaces it.
    Inputs:
        path: Path - The destination file.
        text: str - The content, written as UTF-8.
    Outputs:
        None.
    Raises:
        OSError: If the file cannot be written or replaced.
    """
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, path)


def _read_excluded(meta_path: Path) -> List[dict]:
    """
    Purpose: Read the pages excluded from evaluation from the report metadata (spec R7).
    Details: A report folder with no metadata file was not prepared, and its excluded pages are unknown. That is
        refused rather than read as "no excluded page" (R8): the preparation step writes the file for every
        report, so its absence is a missing preparation to be run again.
    Inputs:
        meta_path: Path - The report metadata file (reports.meta_file_name of ugs_config.json).
    Outputs:
        List[dict] - The records {"page": int, "reason": str} in file order.
    Raises:
        ValueError: If the file is missing, naming the file and the report folder; if it is not JSON, or
            excluded_pages is not a list of records with a page number and a reason. The message names the file
            and the key, never its content.
    """
    if not meta_path.exists():
        raise ValueError(
            f"report metadata file {meta_path.name} is missing in report folder {meta_path.parent}: "
            "the report was not prepared, run the preparation step again")
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"report metadata is not readable JSON: {meta_path.name}") from exc
    if not isinstance(meta, dict) or not isinstance(meta.get(EXCLUDED_PAGES_KEY, []), list):
        raise ValueError(f"key {EXCLUDED_PAGES_KEY} must be a list in {meta_path.name}")
    excluded = meta.get(EXCLUDED_PAGES_KEY, [])
    for record in excluded:
        if not isinstance(record, dict) or not isinstance(record.get("page"), int) \
                or not isinstance(record.get("reason"), str):
            raise ValueError(f"each {EXCLUDED_PAGES_KEY} record needs a page number and a reason in {meta_path.name}")
    return excluded


def build_excluded_note(excluded: List[dict], labels: dict) -> str:
    """
    Purpose: Write the excluded-page note of the annex: each page with its reason, in the report language.
    Inputs:
        excluded: List[dict] - The records {"page": int, "reason": str}, the reason being a code (cover,
            signature_table, version_table).
        labels: dict - The labels of one language, from load_labels.
    Outputs:
        str - For example "page 1 : cover page ; page 5 : signature table"; an empty string when there is none.
    Raises:
        ValueError: If a reason code has no label; the message names the code.
    """
    items = []
    for record in excluded:
        reason = record.get("reason")
        if reason not in labels["excluded_reason_values"]:
            raise ValueError(f"no label for the excluded reason {reason!r}")
        items.append(labels["excluded_item"].format(
            page=record.get("page"), reason=labels["excluded_reason_values"][reason]))
    return labels["excluded_separator"].join(items)


def run_report_checks(src_pdf: Path, source_dir: Path, pages: List[str]) -> Tuple[List[dict], List[dict]]:
    """
    Purpose: Run the five cross-reference checks of the last step on one report (spec R9).
    Details: The element file and the report metadata are read from the report folder of the work folder, whose
        file names come from ugs_config.json. With no element file the figure and table checks are not
        applicable. The equation check reads the PDF, and the excluded pages are not searched.
    Inputs:
        src_pdf: Path - The PDF of the report, read for the equation numbers.
        source_dir: Path - The report folder of the work folder (<work>/<report_id>).
        pages: List[str] - The text of each page, index 0 for page 1.
    Outputs:
        Tuple[List[dict], List[dict]] - The five check entries, and the excluded-page records.
    Raises:
        ugs_config.ConfigError: If a configuration key is missing or malformed (R3).
        crossref_checks.CrossrefConfigError: If a check setting or a marker list is missing (R3).
        element_labels.MarkerError: If the markers file is missing or malformed.
        ugs_tables.TablesError: If the element file is not a list of records.
        ValueError: If the metadata file is missing or not usable.
    """
    config = ugs_config.load(ugs_config.default_path())
    elements = load_elements(source_dir / config[ELEMENTS_NAME_KEY])
    excluded = _read_excluded(source_dir / config[META_NAME_KEY])
    markers = element_labels.load_markers(DEFAULT_MARKERS_PATH)
    settings = load_checks_settings()
    skipped = [record["page"] for record in excluded]
    checks = run_checks(src_pdf, pages, elements, markers, settings, skipped)
    return checks, excluded


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
        annotations.extend(title_kind_annotations(figures_data, language))

    # N5: misplaced citations on the body pages, one annotation each and one row of the checks table.
    body_pages = _body_pages(pages)
    annotations.extend(citation_annotations(body_pages, language))

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

    # Cross-reference checks (spec R9): saved in the loop folder and printed in the annex.
    checks, excluded = run_report_checks(src_pdf, report_dir.parent.parent / report_id, pages)
    checks.append(citation_placement_row(body_pages, language))
    meta_name = ugs_config.load(ugs_config.default_path())[META_NAME_KEY]
    report_meta = _read_report_meta(report_dir.parent.parent / report_id / meta_name)
    checks.extend(count_rows(report_meta))
    checks.append(title_kind_row(figures_data))
    checks.append(appendix_row(pages, report_meta))
    _atomic_write_text(report_dir / CHECKS_FILE_NAME, json.dumps(checks, indent=2))

    # Append annex
    template = settings["annex_template"]
    # The labels come from the report language, through the same label file pdf_annex.main reads.
    labels = load_labels(DEFAULT_LABELS, language)
    rows = render_rows(rubric, grade, totals, labels)
    html_text = build_html(template, rows, report_id, loop, totals.get("total"), labels,
                           excluded_note=build_excluded_note(excluded, labels),
                           checks_html=render_checks(checks, labels))
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
