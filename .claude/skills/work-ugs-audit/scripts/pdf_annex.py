import sys
import argparse
import io
import json
import re
import html
from pathlib import Path
from typing import Optional, List, Dict

import fitz

# The validation codes are owned by ugs_grade (R2): the annex only labels them.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ugs_grade import GRADE_CODES
from crossref_checks import CHECK_IDS, STATUS_OK, STATUS_NOT_OK, STATUS_NOT_APPLICABLE

DEFAULT_TEMPLATE = Path(__file__).resolve().parent.parent / "assets" / "annex.template.html"
DEFAULT_LABELS = Path(__file__).resolve().parent.parent / "assets" / "annex_labels.json"

LABEL_LANGUAGES = ("fr", "en")
LABEL_TEXT_KEYS = ("title", "loop", "item", "score", "status", "comment", "total", "excluded")
STATUS_KEYS = ("rated", "not_applicable", "not_run")
COLUMN_KEYS = ("item", "score", "status")
PERCENT_TOTAL = 100
# The detail keys crossref_checks writes (missing, out_of_order, repeated, skipped); the annex labels each one.
CHECK_DETAIL_KEYS = ("missing", "out_of_order", "repeated", "skipped")
CHECK_STATUS_KEYS = (STATUS_OK, STATUS_NOT_OK, STATUS_NOT_APPLICABLE)

# One placeholder: an upper-case name between double braces. Filled in a single pass (see build_html).
PLACEHOLDER_RE = re.compile(r"\{\{([A-Z_]+)\}\}")


class AnnexError(ValueError):
    """
    Purpose: Error raised when annex generation fails.
    """
    pass


def _read_json_file(path: Path) -> dict:
    """
    Purpose: Read a JSON object from a file of the skill, with a named error for each failure.
    Inputs:
        path: Path - The JSON file.
    Outputs:
        dict - The parsed object.
    Raises:
        AnnexError: If the file cannot be read, is not JSON, or is not a JSON object.
    """
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as e:
        raise AnnexError(f"annex data file cannot be read: {path}") from e
    try:
        data = json.loads(text)
    except ValueError as e:
        raise AnnexError(f"annex data file is not valid JSON: {path}") from e
    if not isinstance(data, dict):
        raise AnnexError(f"annex data file must hold a JSON object: {path}")
    return data


def _require(mapping: dict, key: str, path: Path, where: str):
    """
    Purpose: Return one required value of a data file, or raise a named error for a missing one (R3).
    Inputs:
        mapping: dict - The object holding the key.
        key: str - The key required.
        path: Path - The data file, named in the message.
        where: str - The dotted place of the object, named in the message.
    Outputs:
        The value stored under the key.
    Raises:
        AnnexError: If the key is absent or null.
    """
    if mapping.get(key) is None:
        raise AnnexError(f"key {where}.{key} is missing in {path}")
    return mapping[key]


def _require_text(mapping: dict, key: str, path: Path, where: str) -> str:
    """
    Purpose: Return one required non-empty text of a data file.
    Inputs:
        mapping: dict - The object holding the key.
        key: str - The key required.
        path: Path - The data file, named in the message.
        where: str - The dotted place of the object, named in the message.
    Outputs:
        str - The text.
    Raises:
        AnnexError: If the key is absent or the value is not a non-empty string.
    """
    value = _require(mapping, key, path, where)
    if not isinstance(value, str) or not value.strip():
        raise AnnexError(f"key {where}.{key} must be a non-empty text in {path}")
    return value


def _is_number(value: object) -> bool:
    """
    Purpose: Tell a number from anything else, a boolean included.
    Inputs:
        value: object - The value to test.
    Outputs:
        bool - True for an int or a float that is not a boolean.
    """
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def load_layout(path: Path = DEFAULT_LABELS) -> dict:
    """
    Purpose: Return the layout block of the labels file, validated.
    Inputs:
        path: Path - The labels file.
    Outputs:
        dict - The keys page_margin (points, every side), text_top_inset (points, added at the top of the text
            area), max_unbroken_run (characters a run without a space may reach before a space is inserted) and
            column_widths_percent (the three fixed column widths; the comment takes the rest).
    Raises:
        AnnexError: If a layout key is missing or not a usable number, or the fixed columns leave no width.
    """
    data = _read_json_file(path)
    layout = _require(data, "layout", path, "root")
    if not isinstance(layout, dict):
        raise AnnexError(f"key layout must be an object in {path}")
    margin = _require(layout, "page_margin", path, "layout")
    if not _is_number(margin) or margin <= 0:
        raise AnnexError(f"key layout.page_margin must be a positive number in {path}")
    inset = _require(layout, "text_top_inset", path, "layout")
    if not _is_number(inset) or inset < 0:
        raise AnnexError(f"key layout.text_top_inset must be a number of zero or more in {path}")
    run = _require(layout, "max_unbroken_run", path, "layout")
    if isinstance(run, bool) or not isinstance(run, int) or run <= 0:
        raise AnnexError(f"key layout.max_unbroken_run must be a positive whole number in {path}")
    widths = _require(layout, "column_widths_percent", path, "layout")
    if not isinstance(widths, dict):
        raise AnnexError(f"key layout.column_widths_percent must be an object in {path}")
    for key in COLUMN_KEYS:
        value = _require(widths, key, path, "layout.column_widths_percent")
        if not _is_number(value) or value <= 0:
            raise AnnexError(f"key layout.column_widths_percent.{key} must be a positive number in {path}")
    if sum(widths[key] for key in COLUMN_KEYS) >= PERCENT_TOTAL:
        raise AnnexError(f"the fixed columns of layout.column_widths_percent leave no width for the comment in {path}")
    return {
        "page_margin": margin,
        "text_top_inset": inset,
        "max_unbroken_run": run,
        "column_widths_percent": {key: widths[key] for key in COLUMN_KEYS},
    }


def load_default_language(path: Path = DEFAULT_LABELS) -> str:
    """
    Purpose: Give the language the annex uses when the caller names none, read from the labels file.
    Inputs:
        path: Path - The labels file.
    Outputs:
        str - The language code, "fr" or "en".
    Raises:
        AnnexError: If the key is missing or the language is not a known one.
    """
    data = _read_json_file(path)
    language = _require_text(data, "default_language", path, "root")
    if language not in LABEL_LANGUAGES:
        raise AnnexError(f"key default_language must be one of {LABEL_LANGUAGES} in {path}")
    return language


def _text_map(block: dict, key: str, path: Path, where: str, allowed: Optional[tuple]) -> Dict[str, str]:
    """
    Purpose: Return one required map of non-empty texts of a language block, optionally with fixed keys.
    Inputs:
        block: dict - The language block holding the key.
        key: str - The key of the map.
        path: Path - The labels file, named in the message.
        where: str - The dotted place of the block, named in the message.
        allowed: Optional[tuple] - The exact keys required, or None when any non-empty set of keys is accepted.
    Outputs:
        Dict[str, str] - The map, every value a non-empty text.
    Raises:
        AnnexError: If the map is absent, not an object, lacks an allowed key, holds an unexpected key, or holds
            an empty text.
    """
    values = _require(block, key, path, where)
    if not isinstance(values, dict) or not values:
        raise AnnexError(f"key {where}.{key} must be a non-empty object in {path}")
    if allowed is not None:
        missing = [name for name in allowed if name not in values]
        if missing:
            raise AnnexError(f"key {where}.{key} is missing {missing} in {path}")
        extra = sorted(set(values) - set(allowed))
        if extra:
            raise AnnexError(f"key {where}.{key} has keys with no meaning in {path}: {extra}")
    return {name: _require_text(values, name, path, f"{where}.{key}") for name in values}


def _load_check_labels(block: dict, path: Path, where: str) -> dict:
    """
    Purpose: Read the labels of the cross-reference checks and of the excluded pages from one language block (R3).
    Inputs:
        block: dict - The language block of the labels file.
        path: Path - The labels file, named in the message.
        where: str - The language, named in the message.
    Outputs:
        dict - The keys checks_title, check_column, numbers_column, check_values (one label per check id),
            check_status_values (ok, not_ok, not_applicable), check_detail_values (one label per detail key),
            excluded_reason_values, excluded_item (text with {page} and {reason}) and excluded_separator.
    Raises:
        AnnexError: If a label is missing, empty, or a map holds a key the checks do not produce.
    """
    labels = {
        "checks_title": _require_text(block, "checks_title", path, where),
        "check_column": _require_text(block, "check_column", path, where),
        "numbers_column": _require_text(block, "numbers_column", path, where),
        "check_values": _text_map(block, "check_values", path, where, tuple(CHECK_IDS)),
        "check_status_values": _text_map(block, "check_status_values", path, where, CHECK_STATUS_KEYS),
        "check_detail_values": _text_map(block, "check_detail_values", path, where, CHECK_DETAIL_KEYS),
        "excluded_reason_values": _text_map(block, "excluded_reason_values", path, where, None),
        "excluded_item": _require_text(block, "excluded_item", path, where),
    }
    separator = _require(block, "excluded_separator", path, where)
    if not isinstance(separator, str) or not separator:
        raise AnnexError(f"key {where}.excluded_separator must be a non-empty text in {path}")
    labels["excluded_separator"] = separator
    return labels


def load_labels(path: Path, language: str) -> dict:
    """
    Purpose: Load the annex labels of one language, with the column widths of the layout block.
    Details: The labels are French and English data (R6). The validation labels must cover exactly the codes of
        ugs_grade.GRADE_CODES except ok, so a new code without a label is refused here, before any page is written.
    Inputs:
        path: Path - The labels file (annex_labels.json).
        language: str - "fr" or "en".
    Outputs:
        dict - The keys title, loop, item, score, status, comment, total, excluded (texts), status_values (a map
            of grade status to label), validation_values (a map of each refusal code to its label) and
            column_widths_percent (the three fixed column widths).
    Raises:
        AnnexError: If the language is not fr or en, or a label, a status or a code is missing or empty (R3).
    """
    if language not in LABEL_LANGUAGES:
        raise AnnexError(f"annex language must be one of {LABEL_LANGUAGES}, not {language!r}")
    data = _read_json_file(path)
    block = _require(data, language, path, "root")
    if not isinstance(block, dict):
        raise AnnexError(f"key {language} must be an object in {path}")
    where = language
    labels = {key: _require_text(block, key, path, where) for key in LABEL_TEXT_KEYS}

    statuses = _require(block, "status_values", path, where)
    if not isinstance(statuses, dict):
        raise AnnexError(f"key {where}.status_values must be an object in {path}")
    labels["status_values"] = {
        key: _require_text(statuses, key, path, f"{where}.status_values") for key in STATUS_KEYS
    }

    codes = _require(block, "validation_values", path, where)
    if not isinstance(codes, dict):
        raise AnnexError(f"key {where}.validation_values must be an object in {path}")
    refusals = [code for code in GRADE_CODES if code != "ok"]
    for code in refusals:
        _require_text(codes, code, path, f"{where}.validation_values")
    extra = sorted(set(codes) - set(refusals))
    if extra:
        raise AnnexError(f"key {where}.validation_values has codes with no grade meaning in {path}: {extra}")
    labels["validation_values"] = {code: codes[code] for code in refusals}

    labels.update(_load_check_labels(block, path, where))

    layout = load_layout(path)
    labels["column_widths_percent"] = layout["column_widths_percent"]
    labels["max_unbroken_run"] = layout["max_unbroken_run"]
    return labels


def _break_long_runs(text: str, run_chars: int) -> str:
    """
    Purpose: Insert a space into every run of non-space characters longer than run_chars, so the engine wraps it.
    Details: The story engine clips a word wider than its cell instead of breaking it, so a long address or an
        unbroken string would otherwise be lost or pushed past the margin. Only the display changes, never the text
        order; a run of run_chars or fewer is left as written.
    Inputs:
        text: str - The text of a cell.
        run_chars: int - The longest run kept whole, from the layout block.
    Outputs:
        str - The text with a space every run_chars characters inside each long run.
    """
    def split(match: "re.Match[str]") -> str:
        """
        Purpose: Cut one matched run into pieces of run_chars characters, joined by spaces.
        Inputs:
            match: re.Match[str] - The match of one run of non-space characters.
        Outputs:
            str - The run with a space every run_chars characters.
        """
        run = match.group(0)
        return " ".join(run[i:i + run_chars] for i in range(0, len(run), run_chars))

    return re.sub(rf"\S{{{run_chars + 1},}}", split, text)


def _status_text(status: str, labels: Optional[dict]) -> str:
    """
    Purpose: Give the text shown for a grade status, the raw status when no labels are given.
    Inputs:
        status: str - The grade status.
        labels: Optional[dict] - The labels of one language, or None.
    Outputs:
        str - The label of the status, or the status itself when labels is None.
    Raises:
        AnnexError: If labels are given and hold no label for the status.
    """
    if labels is None:
        return status
    if status not in labels["status_values"]:
        raise AnnexError(f"no label for the grade status {status!r}")
    return labels["status_values"][status]


def _validation_text(code: str, labels: dict) -> str:
    """
    Purpose: Give the label of a refusal code in the document language.
    Inputs:
        code: str - The validation code of the grade item, not "ok".
        labels: dict - The labels of one language.
    Outputs:
        str - The short label of the code.
    Raises:
        AnnexError: If the code has no label.
    """
    if code not in labels["validation_values"]:
        raise AnnexError(f"no label for the validation code {code!r}")
    return labels["validation_values"][code]


def render_rows(rubric: dict, grade: dict, totals: dict, labels: Optional[dict] = None) -> str:
    """
    Purpose: Render HTML rows for the rubric table.
    Details: With labels, statuses and the not-run score use the document language, a refused proof
        (validation other than ok, absent counts as ok) shows its label under the comment, and a run of text
        longer than the layout's max_unbroken_run is split so the engine wraps it. Without labels the rows are
        rendered as before, with the raw status, no validation label and no split.
    Inputs:
        rubric: dict - The rubric definition.
        grade: dict - The grade data.
        totals: dict - The totals data.
        labels: Optional[dict] - The labels of one language, from load_labels, or None.
    Outputs:
        str - HTML string of table rows.
    Raises:
        AnnexError: If labels are given and a status or a validation code has no label.
    """
    grade_items = {item["item_id"]: item for item in grade.get("items", [])}
    rows = []

    for item in rubric.get("items", []):
        item_id = item["id"]
        max_points = item.get("max_points", 0)

        grade_item = grade_items.get(item_id, {})
        status = grade_item.get("status", "not_run")
        score = grade_item.get("score")
        raw_title = item.get("title", "")
        raw_comment = grade_item.get("comment", "")
        if labels is not None:
            raw_title = _break_long_runs(raw_title, labels["max_unbroken_run"])
            raw_comment = _break_long_runs(raw_comment, labels["max_unbroken_run"])
        title = html.escape(raw_title)
        comment = html.escape(raw_comment)

        if status == "not_run":
            score_str = _status_text("not_run", labels)
        else:
            score_str = f"{score} / {max_points}"
        status_str = html.escape(_status_text(status, labels))

        if labels is not None:
            code = grade_item.get("validation", "ok")
            if code != "ok":
                comment += f"<br><i>{html.escape(_validation_text(code, labels))}</i>"

        row = f"<tr><td>{title}</td><td>{score_str}</td><td>{status_str}</td><td>{comment}</td></tr>"
        rows.append(row)

    return "\n".join(rows)


def _is_whole_number(value: object) -> bool:
    """
    Purpose: Tell a whole number from anything else, a boolean included.
    Inputs:
        value: object - The value to test.
    Outputs:
        bool - True for an int that is not a boolean.
    """
    return isinstance(value, int) and not isinstance(value, bool)


def _number_text(number: object) -> str:
    """
    Purpose: Format one number of a check the way the report writes it, its parts joined by dots.
    Inputs:
        number: object - A non-empty list or tuple of whole numbers, for example (2, 1) for 2.1.
    Outputs:
        str - The dotted number, for example "2.1".
    Raises:
        AnnexError: If the value is not a non-empty list or tuple of whole numbers.
    """
    if not isinstance(number, (list, tuple)) or not number or not all(_is_whole_number(p) for p in number):
        raise AnnexError("a check number must be a list of whole numbers")
    return ".".join(str(part) for part in number)


def _check_numbers_text(detail: object, labels: dict) -> str:
    """
    Purpose: Print the numbers of one check's detail, numbers only, grouped under the label of each detail key.
    Details: Only the numbers are printed. The keys are printed as their labels, in the fixed order of
        CHECK_DETAIL_KEYS, and a key with no number is left out.
    Inputs:
        detail: object - The detail of one check: an object of number lists.
        labels: dict - The labels of one language, from load_labels.
    Outputs:
        str - For example "Missing : 2.1, 2.3"; an empty string when every list is empty.
    Raises:
        AnnexError: If the detail is not an object, holds a key with no label, or a value that is not a list.
    """
    if not isinstance(detail, dict):
        raise AnnexError("a check detail must be an object")
    unknown = sorted(set(detail) - set(CHECK_DETAIL_KEYS))
    if unknown:
        raise AnnexError(f"no label for the check detail keys {unknown}")
    parts = []
    for key in CHECK_DETAIL_KEYS:
        if key not in detail:
            continue
        value = detail[key]
        if not isinstance(value, (list, tuple)):
            raise AnnexError(f"the check detail {key!r} must be a list")
        numbers = [_number_text(number) for number in value]
        if numbers:
            parts.append(f"{labels['check_detail_values'][key]} : {', '.join(numbers)}")
    return "; ".join(parts)


def render_checks(checks: List[dict], labels: dict) -> str:
    """
    Purpose: Render the table of the cross-reference checks: the label of each check, its status label and its
        numbers. The three columns take the widths of the rubric table (item and status), the numbers the rest.
    Details: Nothing from a check's detail is printed except its numbers, so no text of a report reaches the annex
        through this table (spec R9).
    Inputs:
        checks: List[dict] - The check entries of crossref_checks.run_checks: id, status and detail.
        labels: dict - The labels of one language, from load_labels.
    Outputs:
        str - An HTML heading and table.
    Raises:
        AnnexError: If a check id or status has no label, or a detail is not made of numbers.
    """
    widths = labels["column_widths_percent"]
    numbers_width = PERCENT_TOTAL - widths["item"] - widths["status"]
    header = (
        f"<tr><th style=\"width:{widths['item']:g}%\">{html.escape(labels['check_column'])}</th>"
        f"<th style=\"width:{widths['status']:g}%\">{html.escape(labels['status'])}</th>"
        f"<th style=\"width:{numbers_width:g}%\">{html.escape(labels['numbers_column'])}</th></tr>"
    )
    rows = []
    for check in checks:
        check_id = check.get("id")
        status = check.get("status")
        if check_id not in labels["check_values"]:
            raise AnnexError(f"no label for the check {check_id!r}")
        if status not in labels["check_status_values"]:
            raise AnnexError(f"no label for the check status {status!r}")
        name = html.escape(labels["check_values"][check_id])
        status_text = html.escape(labels["check_status_values"][status])
        numbers = html.escape(_check_numbers_text(check.get("detail"), labels))
        rows.append(f"<tr><td>{name}</td><td>{status_text}</td><td>{numbers}</td></tr>")
    return (
        f"<h3>{html.escape(labels['checks_title'])}</h3>\n"
        "<table style=\"width:100%; border-collapse:collapse;\" border=\"1\" cellpadding=\"4\">\n"
        f"{header}\n" + "\n".join(rows) + "\n</table>"
    )


def _label_placeholders(labels: dict) -> Dict[str, str]:
    """
    Purpose: Map each label and column width of one language to its template placeholder.
    Inputs:
        labels: dict - The labels of one language, from load_labels.
    Outputs:
        Dict[str, str] - Placeholder name (without braces) to its escaped text; the comment width is the remainder.
    """
    values = {f"L_{key.upper()}": html.escape(labels[key]) for key in LABEL_TEXT_KEYS}
    widths = labels["column_widths_percent"]
    for key in COLUMN_KEYS:
        values[f"W_{key.upper()}"] = f"{widths[key]:g}"
    values["W_COMMENT"] = f"{PERCENT_TOTAL - sum(widths[key] for key in COLUMN_KEYS):g}"
    return values


def build_html(template: str, rows: str, report_id: str, loop: int, total: Optional[str],
               labels: Optional[dict] = None, excluded_note: str = "", checks_html: str = "") -> str:
    """
    Purpose: Build the final HTML annex.
    Details: Every placeholder is replaced in one pass, so a value that itself contains braces is never
        replaced again. The excluded note is escaped, since it is text and not markup. The checks table is
        HTML built by render_checks and is inserted as it is.
    Inputs:
        template: str - The HTML template.
        rows: str - The rendered rows.
        report_id: str - The report ID.
        loop: int - The loop number.
        total: Optional[str] - The total score string or None.
        labels: Optional[dict] - The labels of one language, from load_labels, or None when the template has
            no label placeholder.
        excluded_note: str - The text of the excluded pages, empty when there are none.
        checks_html: str - The HTML of the cross-reference checks (render_checks), empty when there are none.
    Outputs:
        str - The final HTML string.
    Raises:
        AnnexError: If the template holds a placeholder this function does not fill.
    """
    total_str = total if total is not None else "-"

    replacements = {
        "REPORT_ID": report_id,
        "LOOP": str(loop),
        "ROWS": rows,
        "TOTAL": total_str,
        "EXCLUDED": html.escape(excluded_note),
        "CHECKS": checks_html,
    }
    if labels is not None:
        replacements.update(_label_placeholders(labels))

    unknown = sorted({name for name in PLACEHOLDER_RE.findall(template) if name not in replacements})
    if unknown:
        raise AnnexError(f"Unreplaced placeholders found: {['{{' + name + '}}' for name in unknown]}")

    return PLACEHOLDER_RE.sub(lambda match: replacements[match.group(1)], template)


def append_annex(pdf: Path, html: str) -> int:
    """
    Purpose: Append the HTML annex to the PDF.
    Details: The margin and the top inset come from the layout block of annex_labels.json, and every word of the
        annex lies inside the margin. The annex is laid out by PyMuPDF's story engine.
    Inputs:
        pdf: Path - Path to the PDF file.
        html: str - The HTML content to append.
    Outputs:
        int - Number of pages added.
    Raises:
        AnnexError: If the layout block cannot be read from the labels file.
    """
    buffer = io.BytesIO()
    writer = fitz.DocumentWriter(buffer)
    story = fitz.Story(html=html)

    layout = load_layout(DEFAULT_LABELS)
    margin = layout["page_margin"]
    page_rect = fitz.paper_rect("a4")
    content_rect = page_rect + (margin, margin + layout["text_top_inset"], -margin, -margin)

    def rectfn(rect_num, filled):
        return (page_rect, content_rect, fitz.Identity)

    story.write(writer, rectfn)
    writer.close()

    # The annex stays in memory: a temporary file on disk stays locked on Windows
    annex_doc = fitz.open("pdf", buffer.getvalue())
    doc = fitz.open(str(pdf))
    initial_pages = doc.page_count
    doc.insert_pdf(annex_doc)
    pages_added = doc.page_count - initial_pages
    annex_doc.close()
    doc.saveIncr()
    doc.close()

    return pages_added


def main(argv: Optional[List[str]] = None) -> int:
    """
    Purpose: Main entry point.
    Inputs:
        argv: Optional[List[str]] - Command line arguments.
    Outputs:
        int - Exit code: 0 done, 2 refusal (a missing input, a file that is not a PDF, a label or layout the
            annex cannot use), 1 failure.
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--pdf", required=True)
    parser.add_argument("--rubric", required=True)
    parser.add_argument("--grade", required=True)
    parser.add_argument("--totals", required=True)
    parser.add_argument("--report-id", required=True)
    parser.add_argument("--loop", type=int, required=True)
    parser.add_argument("--template", default=None)
    parser.add_argument("--labels", default=None)
    parser.add_argument("--language", choices=LABEL_LANGUAGES, default=None,
                        help="the language of the report; the default comes from the labels file")
    parser.add_argument("--json", action="store_true")

    args = parser.parse_args(argv)

    pdf_path = Path(args.pdf)
    template_path = Path(args.template) if args.template else DEFAULT_TEMPLATE
    labels_path = Path(args.labels) if args.labels else DEFAULT_LABELS
    # Messages name no path: a file name can carry a student name.
    for path in (pdf_path, Path(args.rubric), Path(args.grade), Path(args.totals), template_path, labels_path):
        if not path.is_file():
            print("Refusal: an input file is missing", file=sys.stderr)
            return 2
    with open(pdf_path, "rb") as handle:
        if handle.read(5) != b"%PDF-":
            print("Refusal: the file to extend is not a PDF", file=sys.stderr)
            return 2

    try:
        rubric = json.loads(Path(args.rubric).read_text(encoding="utf-8"))
        grade = json.loads(Path(args.grade).read_text(encoding="utf-8"))
        totals = json.loads(Path(args.totals).read_text(encoding="utf-8"))
        template = template_path.read_text(encoding="utf-8")

        language = args.language or load_default_language(labels_path)
        labels = load_labels(labels_path, language)

        rows = render_rows(rubric, grade, totals, labels)
        html_text = build_html(template, rows, args.report_id, args.loop, totals.get("total"), labels)
        pages_added = append_annex(pdf_path, html_text)

        if args.json:
            print(json.dumps({"pages_added": pages_added}))
        else:
            print(pages_added)
        return 0

    except AnnexError as e:
        print(f"Refusal: {e}", file=sys.stderr)
        return 2
    except Exception as e:
        print(f"Failure: {type(e).__name__}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
