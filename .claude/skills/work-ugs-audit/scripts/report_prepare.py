"""
Report preparation - gives every PDF report of a folder a stable pseudonymous id, and writes its pages, its
metadata and its elements into the work folder.

Purpose: the ids (R01, R02...) replace the file names everywhere after this step. For each report the preparation
detects the language once from the text layer, proves that OCR works for the languages of the map, repairs the
damaged pages by OCR in the detected language, marks the excluded pages, extracts the elements (figures, tables,
logos) and adds the Markdown of each table to the text of its page. The result is written per report as
`report_meta.json` and `elements.json`, with the page files. File names appear only in the id map.
Exit codes: 0 done, 1 unexpected failure, 2 refusal.
"""
import argparse
import json
import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

SCRIPTS_DIR = Path(__file__).resolve().parent
FIGURE_REVIEW_DIR = SCRIPTS_DIR.parent.parent / "figure-review"
for _folder in (SCRIPTS_DIR, FIGURE_REVIEW_DIR / "scripts"):
    if str(_folder) not in sys.path:
        sys.path.insert(0, str(_folder))

import fitz  # noqa: E402
import element_labels  # noqa: E402
import count_check  # noqa: E402
import front_matter  # noqa: E402
import front_pages  # noqa: E402
import page_roles  # noqa: E402
import text_quality  # noqa: E402
import ugs_config  # noqa: E402
from figure_extract import ELEMENT_SETTING_KEYS, extract_elements  # noqa: E402
from text_quality import OcrUnavailable, TextQualityError  # noqa: E402
from ugs_tables import TablesError, enrich_page_text, load_min_anchor_chars, load_table_text, tables_on_page  # noqa: E402
from ugs_text import LanguageUndecidable, detect_language, load_hints  # noqa: E402

EXIT_OK = 0
EXIT_FAILURE = 1
EXIT_REFUSAL = 2
IDS_FILE_NAME = "ids.json"
PAGES_FOLDER = "pages"
TABLE_STATS_FILE = "table_extraction.json"
PAGE_FILE_PREFIX = "p"
ASSETS_DIR = SCRIPTS_DIR.parent / "assets"
HINTS_FILE = ASSETS_DIR / "language_hints.json"
PAGE_ROLES_FILE = ASSETS_DIR / "page_roles.json"
FIGURE_CRITERIA_FILE = FIGURE_REVIEW_DIR / "assets" / "figure_criteria.json"
ELEMENT_MARKERS_FILE = FIGURE_REVIEW_DIR / "assets" / "element_markers.json"
EXTRACTION_BLOCK = "extraction"
CONFIG_KEYS = (
    "reports.id_prefix",
    "reports.id_digits",
    "reports.page_digits",
    "reports.meta_file_name",
    "reports.elements_file_name",
    "reports.figures_folder",
    "text.excluded_folder",
    "text.excluded_marker",
    "text.min_replacement_chars",
    "text.min_words_per_page",
    "text.ocr_dpi",
    "pages.small_image_max_area_ratio",
)


class PrepareError(ValueError):
    """Raised when the reports cannot be prepared. Its message never holds a file name."""


class OcrPreflightError(PrepareError):
    """Raised when OCR cannot run for the languages of the map. Its message names the missing tool or data."""


@dataclass(frozen=True)
class PrepHooks:
    """
    Purpose: The effects a preparation run needs from outside, so that the tests can inject them.
    Inputs (fields):
        preflight (Callable[[List[str]], None]): proves OCR works for the Tesseract codes given, raises on failure.
        ocr_page (Callable[[Path, int, str], str]): OCR of one page, given the 1-based page and the Tesseract code(s).
        find_elements (Callable[[Path, Path, List[int]], List[dict]]): the element records of a PDF, given the
            folder for the figure files and the 1-based pages to skip.
    Outputs:
        PrepHooks: the bundle of the three callables.
    Raises:
        None.
    """

    preflight: Callable[[List[str]], None]
    ocr_page: Callable[[Path, int, str], str]
    find_elements: Callable[[Path, Path, List[int]], List[Dict[str, Any]]]


def _is_pdf(file_path: Path) -> bool:
    """
    Purpose: Tell whether a file is a PDF by its extension.
    Inputs:
        file_path (Path): the file.
    Outputs:
        bool: True for a .pdf file, whatever the case of the extension.
    Raises:
        None.
    """
    return file_path.suffix.lower() == ".pdf"


def _load_settings() -> dict:
    """
    Purpose: Read the id, page, file, text and page-role formats from the shipped configuration.
    Inputs:
        None.
    Outputs:
        dict: the keys of CONFIG_KEYS with their values.
    Raises:
        PrepareError: when the configuration cannot be read or a key is missing (the message names the key).
    """
    try:
        config = ugs_config.load(ugs_config.default_path())
    except ugs_config.ConfigError as error:
        raise PrepareError(f"configuration unreadable: {error}") from error
    for key in CONFIG_KEYS:
        if key not in config:
            raise PrepareError(f"configuration key '{key}' is missing")
    return {key: config[key] for key in CONFIG_KEYS}


def _load_context() -> dict:
    """
    Purpose: Read the data files of the preparation: the language hints, the OCR language map and the page-role
        markers. Each is named in the error when it cannot be read (R3).
    Inputs:
        None.
    Outputs:
        dict: 'hints' (language hints), 'ocr' (the OCR data values) and 'markers' (the page-role markers).
    Raises:
        PrepareError: when a data file is unreadable or incomplete (the message names the key or file).
    """
    try:
        hints = load_hints(HINTS_FILE)
        ocr = text_quality.load_ocr_settings()
        markers = page_roles.load_markers(PAGE_ROLES_FILE)
        front_matter_settings = front_matter.load_entry_settings()
    except (OSError, ValueError, TextQualityError, page_roles.PageRolesConfigError,
            front_pages.FrontMatterConfigError) as error:
        raise PrepareError(f"data file unreadable: {error}") from error
    return {"hints": hints, "ocr": ocr, "markers": markers, "front_matter": front_matter_settings}


def _ocr_languages(language_codes: Dict[str, List[str]]) -> List[str]:
    """
    Purpose: List every Tesseract code of the language map once, in the map's order.
    Inputs:
        language_codes (dict): the language map of the OCR data file (key to list of codes).
    Outputs:
        list[str]: the distinct codes, e.g. ["fra", "eng"].
    Raises:
        PrepareError: when an entry is not a list of codes.
    """
    codes: List[str] = []
    for entry in language_codes.values():
        if not isinstance(entry, list) or not all(isinstance(code, str) and code for code in entry):
            raise PrepareError("the OCR language map holds an entry that is not a list of codes")
        for code in entry:
            if code not in codes:
                codes.append(code)
    return codes


def _load_extraction_settings() -> Dict[str, Any]:
    """
    Purpose: Read the element extraction settings from the `extraction` block of the figure criteria file, as plain
        values (R0, R3). Each key of ELEMENT_SETTING_KEYS must be present.
    Inputs:
        None.
    Outputs:
        dict: the value of each key of ELEMENT_SETTING_KEYS.
    Raises:
        PrepareError: when the file is unreadable or a key is missing (the message names the key).
    """
    try:
        document = json.loads(FIGURE_CRITERIA_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise PrepareError("the figure criteria file is unreadable") from error
    block = document.get(EXTRACTION_BLOCK) if isinstance(document, dict) else None
    if not isinstance(block, dict):
        raise PrepareError(f"the '{EXTRACTION_BLOCK}' block is missing from the figure criteria")
    settings: Dict[str, Any] = {}
    for key in ELEMENT_SETTING_KEYS:
        entry = block.get(key)
        if not isinstance(entry, dict) or "value" not in entry:
            raise PrepareError(f"extraction setting '{key}' is missing from the figure criteria")
        settings[key] = entry["value"]
    return settings


def _run_preflight(languages: List[str]) -> None:
    """
    Purpose: Prove that OCR works for each Tesseract code, through text_quality.ocr_preflight.
    Inputs:
        languages (list[str]): the Tesseract codes to prove.
    Outputs:
        None. Returns only when every language is proven.
    Raises:
        OcrUnavailable: when a tool or a language data file is missing, or the probe word is not read.
    """
    text_quality.ocr_preflight(languages)


def _run_ocr_page(pdf_path: Path, page_number: int, tesseract_language: str, dpi: int) -> str:
    """
    Purpose: OCR one page of a PDF with pymupdf4llm, in the given language and at the given resolution. The OCR is
        forced, so the text layer of the page is replaced by the text read from its image.
    Inputs:
        pdf_path (Path): the PDF.
        page_number (int): the 1-based page.
        tesseract_language (str): the Tesseract code(s), joined with '+' when there are several.
        dpi (int): the resolution of the OCR, in dots per inch.
    Outputs:
        str: the text of the page read by OCR.
    Raises:
        PrepareError: when pymupdf4llm is missing or the OCR call fails (the message holds no file name).
    """
    try:
        import pymupdf4llm
    except ImportError as error:
        raise PrepareError("pymupdf4llm is required and is not installed") from error
    try:
        chunks = pymupdf4llm.to_markdown(str(pdf_path), pages=[page_number - 1], page_chunks=True,
                                         force_ocr=True, ocr_language=tesseract_language, ocr_dpi=dpi)
    except Exception as error:
        raise PrepareError(f"OCR of a page failed: {type(error).__name__}") from error
    return "\n".join(chunk.get("text", "") for chunk in chunks)


def _tables_dropped(report_dir: Path) -> int:
    """
    Purpose: Read how many tables the element extraction dropped for having no readable cells (F0).
    Inputs:
        report_dir (Path): the report folder, holding TABLE_STATS_FILE once the extraction has run.
    Outputs:
        int - the count; 0 when the extraction wrote no statistics file.
    Raises:
        PrepareError: the statistics file is unreadable or holds no whole number.
    """
    path = report_dir / TABLE_STATS_FILE
    if not path.exists():
        return 0
    try:
        value = json.loads(path.read_text(encoding="utf-8")).get("tables_dropped")
    except (OSError, ValueError, AttributeError) as error:
        raise PrepareError(f"{TABLE_STATS_FILE} is unreadable") from error
    if isinstance(value, bool) or not isinstance(value, int):
        raise PrepareError(f"{TABLE_STATS_FILE} holds no whole number of dropped tables")
    return value


def _run_find_elements(pdf_path: Path, figures_dir: Path, skip_pages: List[int]) -> List[Dict[str, Any]]:
    """
    Purpose: Extract the elements of a PDF with figure-review's extract_elements, the settings and the markers read
        from the figure-review data files.
    Inputs:
        pdf_path (Path): the PDF.
        figures_dir (Path): the folder for the figure files.
        skip_pages (list[int]): the 1-based pages to leave out (excluded pages).
    Outputs:
        list[dict]: the element records in reading order.
    Raises:
        PrepareError: when a settings or marker file is unreadable or incomplete.
    """
    settings = _load_extraction_settings()
    try:
        markers = element_labels.load_markers(ELEMENT_MARKERS_FILE)
    except (OSError, ValueError, element_labels.MarkerError) as error:
        raise PrepareError("the element markers file is unreadable or incomplete") from error
    stats: Dict[str, Any] = {}
    records = extract_elements(pdf_path, figures_dir, settings, markers, skip_pages=skip_pages, stats=stats)
    _write_atomic(figures_dir.parent / TABLE_STATS_FILE, json.dumps(stats, indent=2))
    return records


def _default_hooks(dpi: int) -> PrepHooks:
    """
    Purpose: Build the hooks of a real run: the OCR preflight, the real OCR of a page and the real element extraction.
    Inputs:
        dpi (int): the resolution of the OCR of a page (text.ocr_dpi).
    Outputs:
        PrepHooks: the real hooks.
    Raises:
        None.
    """
    return PrepHooks(
        preflight=_run_preflight,
        ocr_page=lambda pdf_path, page_number, language: _run_ocr_page(pdf_path, page_number, language, dpi),
        find_elements=_run_find_elements,
    )


def _extract_page_text(pdf_path: Path) -> list[str]:
    """
    Purpose: Extract the Markdown text of every page of a PDF from its text layer, page by page. OCR is off here:
        the damaged pages are repaired in a later stage, in the detected language.
    Inputs:
        pdf_path (Path): the PDF.
    Outputs:
        list[str]: one text per page, index 0 being page 1.
    Raises:
        PrepareError: when pymupdf4llm is missing or cannot read the file (the message holds no file name).
    """
    try:
        import pymupdf4llm
    except ImportError as error:
        raise PrepareError("pymupdf4llm is required and is not installed") from error
    try:
        chunks = pymupdf4llm.to_markdown(str(pdf_path), page_chunks=True, use_ocr=False)
    except Exception as error:
        raise PrepareError(f"text extraction failed: {type(error).__name__}") from error
    return [chunk.get("text", "") for chunk in chunks]


def _write_atomic(path: Path, text: str) -> None:
    """
    Purpose: Write a text file in one step: the content goes to a temporary file, which then replaces the target.
    Inputs:
        path (Path): the file to write; its folder is created when absent.
        text (str): the content, written as UTF-8.
    Outputs:
        None. Writes path, and no temporary file remains beside it.
    Raises:
        OSError: when the file cannot be written.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, path)


def _route_library_messages() -> None:
    """
    Purpose: Send the messages of PyMuPDF and pymupdf4llm (the OCR progress, the parser notes) to stderr. Their
        default is stdout, which would put text ahead of the single JSON line the command prints.
    Inputs:
        None.
    Outputs:
        None. Changes the destination of the library messages for the rest of the process.
    Raises:
        None.
    """
    fitz.set_messages(stream=sys.stderr)


def _load_ids(ids_file: Path) -> dict[str, str]:
    """
    Purpose: Read the id map written by an earlier run.
    Inputs:
        ids_file (Path): the id map file.
    Outputs:
        dict[str, str]: id to file name, empty when the file does not exist.
    Raises:
        PrepareError: when the file is not a JSON object.
    """
    if not ids_file.exists():
        return {}
    try:
        ids = json.loads(ids_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise PrepareError("the id map is not valid JSON") from error
    if not isinstance(ids, dict):
        raise PrepareError("the id map is not a JSON object")
    return ids


def _check_work_dir(reports_dir: Path, work_dir: Path) -> None:
    """
    Purpose: Refuse a work folder that is not a folder directly inside the reports folder.
    Details: The paths are resolved first, so links and '..' cannot escape the check. The work folder must be a
        direct child of the reports folder (owner decision 2026-11-15) and must not be the reports folder itself.
        The listing of the reports reads files only, so the work folder is never taken for a report.
    Inputs:
        reports_dir (Path): the reports folder.
        work_dir (Path): the work folder.
    Outputs:
        None.
    Raises:
        PrepareError: when the work folder is the reports folder or is not directly inside it.
    """
    reports = reports_dir.resolve()
    work = work_dir.resolve()
    if work == reports or work.parent != reports:
        raise PrepareError("the work folder must be a folder directly inside the reports folder")


def _prepare_report(pdf_file: Path, report_id: str, work_dir: Path, settings: dict, context: dict,
                    hooks: PrepHooks) -> dict:
    """
    Purpose: Prepare one report: detect its language, repair its damaged pages, mark its excluded pages, extract its
        elements and write its page files, report_meta.json and elements.json.
    Details: The order is fixed: language from the text layer, OCR repair of the damaged and text-less pages, excluded
        pages from the repaired text, elements with the excluded pages skipped, then the table Markdown added to each
        page that is kept. The original text of an excluded page is kept in the excluded folder. When the text layer
        gives no language decision, the report is refused before any file of it is written, and the result carries
        the reason under 'refused'; the other reports are still prepared.
    Inputs:
        pdf_file (Path): the PDF of the report.
        report_id (str): the id of the report.
        work_dir (Path): the work folder.
        settings (dict): the values of CONFIG_KEYS.
        context (dict): the hints, the OCR data and the page-role markers (see _load_context).
        hooks (PrepHooks): the OCR page call and the element finder.
    Outputs:
        dict: 'report_id', 'pages' (count), 'empty_pages' (1-based numbers of the pages with no text layer before
        repair) and, for a refused report only, 'refused' (the reason, which names the id and never the file).
        Side effects: writes the page files, the excluded folder, elements.json and report_meta.json of the report
        (none for a refused report). report_meta.json lists the empty pages still unreadable after OCR under
        'unreadable_pages'.
    Raises:
        PrepareError: when the text, the repair or the elements cannot be produced.
    """
    report_dir = work_dir / report_id
    texts = _extract_page_text(pdf_file)
    empty_pages = [number for number, text in enumerate(texts, start=1) if not text.strip()]
    try:
        language = detect_language(texts, context["hints"])
    except LanguageUndecidable as error:
        return {"report_id": report_id, "pages": len(texts), "empty_pages": empty_pages,
                "refused": f"{report_id}: {error}"}
    # D4: the configured anchor length is read before any file of this report is written, so a missing key
    # refuses the preparation with nothing on disk for it, instead of failing midway through the pages.
    try:
        minimum_anchor = load_min_anchor_chars()
        table_texts = load_table_text(language)
    except TablesError as error:
        raise PrepareError(str(error)) from None

    repair_settings = {"min_replacement_chars": settings["text.min_replacement_chars"],
                       "min_words_per_page": settings["text.min_words_per_page"],
                       "language_codes": context["ocr"]["language_codes"]}
    new_texts, quality = text_quality.repair_pages(pdf_file, texts, language, repair_settings, hooks.ocr_page)

    small_images = page_roles.small_image_counts(pdf_file, settings["pages.small_image_max_area_ratio"])
    excluded = page_roles.excluded_pages(new_texts, small_images, context["markers"])
    reasons = {entry["page"]: entry["reason"] for entry in excluded}
    try:
        front_roles = front_pages.find_front_roles(new_texts, language, context["front_matter"], small_images)
        declared = front_matter.declared_counts(new_texts, front_roles, language, context["front_matter"])
    except front_pages.FrontMatterConfigError as error:
        raise PrepareError(str(error)) from None

    excluded_dir = report_dir / settings["text.excluded_folder"]
    if excluded_dir.exists():
        shutil.rmtree(excluded_dir)
    # N3 (plan 16): a front page (cover, version, contents, lists) is never sent to the element finder as content.
    front_skip = [page for page, mode in front_pages.page_modes(front_roles, context["front_matter"]).items()
                  if mode != front_pages.FULL_MODE]
    skip_pages = sorted(set(reasons) | set(front_skip))
    elements = hooks.find_elements(pdf_file, report_dir / settings["reports.figures_folder"], skip_pages)
    _write_atomic(report_dir / settings["reports.elements_file_name"],
                  json.dumps(elements, indent=2, ensure_ascii=False))

    for number, text in enumerate(new_texts, start=1):
        page_path = report_dir / PAGES_FOLDER / f"{PAGE_FILE_PREFIX}{number:0{settings['reports.page_digits']}d}.md"
        if number in reasons:
            marker = settings["text.excluded_marker"].format(reason=reasons[number])
            _write_atomic(page_path, marker)
            _write_atomic(excluded_dir / page_path.name, texts[number - 1])
        else:
            _write_atomic(page_path, enrich_page_text(text, tables_on_page(elements, number), language,
                                                      minimum_anchor, table_texts))

    unreadable_pages = [entry["page"] for entry in quality if entry["empty"]]
    meta = {"language": language, "excluded_pages": excluded, "text_quality": quality,
            "tables_dropped": _tables_dropped(report_dir),
            "unreadable_pages": unreadable_pages, "front_roles": front_roles, **declared,
            **count_check.compare_counts(declared, elements)}
    _write_atomic(report_dir / settings["reports.meta_file_name"], json.dumps(meta, indent=2, ensure_ascii=False))
    return {"report_id": report_id, "pages": len(texts), "empty_pages": empty_pages}


def prepare(reports_dir: Path, work_dir: Path, hooks: Optional[PrepHooks] = None) -> list[dict]:
    """
    Purpose: Give every PDF of the reports folder a stable id and prepare its pages, metadata and elements.
    Details: Ids follow the sorted file names. A rerun keeps the ids already given, and a report added later takes
        the next number. The OCR preflight runs once, before any file is written, for every Tesseract code of the
        language map; a failure stops the run with nothing written.
    Inputs:
        reports_dir (Path): the folder holding the PDF reports.
        work_dir (Path): the work folder, directly inside the reports folder.
        hooks (PrepHooks | None): the injected effects; None means the real OCR and element extraction.
    Outputs:
        list[dict]: one dict per PDF with 'report_id', 'pages' (count), 'empty_pages' (1-based numbers) and, for a
        refused report, 'refused' (see _prepare_report).
        Side effects: writes ids.json and, per report, its page files, excluded folder, elements.json and
        report_meta.json in work_dir.
    Raises:
        PrepareError: when the work folder is not directly inside the reports folder, the id map is unreadable, the
            configuration or a data file is incomplete, or a PDF cannot be read.
        OcrPreflightError: when OCR cannot run for a language of the map (the message names the tool or the data).
    """
    _check_work_dir(reports_dir, work_dir)
    _route_library_messages()
    settings = _load_settings()
    context = _load_context()
    prefix = settings["reports.id_prefix"]
    id_digits = settings["reports.id_digits"]
    if hooks is None:
        hooks = _default_hooks(settings["text.ocr_dpi"])

    ids_file = work_dir / IDS_FILE_NAME
    ids = _load_ids(ids_file)
    id_of_name = {name: report_id for report_id, name in ids.items()}
    taken = [int(report_id[len(prefix):]) for report_id in ids if report_id[len(prefix):].isdigit()]
    next_number = max(taken, default=0) + 1

    assignments = []
    for pdf_file in sorted(path for path in reports_dir.iterdir() if path.is_file() and _is_pdf(path)):
        report_id = id_of_name.get(pdf_file.name)
        if report_id is None:
            report_id = f"{prefix}{next_number:0{id_digits}d}"
            ids[report_id] = pdf_file.name
            id_of_name[pdf_file.name] = report_id
            next_number += 1
        assignments.append((pdf_file, report_id))

    try:
        hooks.preflight(_ocr_languages(context["ocr"]["language_codes"]))
    except OcrUnavailable as error:
        raise OcrPreflightError(str(error)) from error

    results = [_prepare_report(pdf_file, report_id, work_dir, settings, context, hooks)
               for pdf_file, report_id in assignments]
    work_dir.mkdir(parents=True, exist_ok=True)
    _write_atomic(ids_file, json.dumps(ids, indent=2, ensure_ascii=False))
    return results


def skipped_count(reports_dir: Path) -> int:
    """
    Purpose: Count the files of the reports folder that are not PDFs.
    Inputs:
        reports_dir (Path): the reports folder.
    Outputs:
        int: the number of non-PDF files (folders are not counted).
    Raises:
        None.
    """
    return sum(1 for path in reports_dir.iterdir() if path.is_file() and not _is_pdf(path))


def main(argv: Optional[list[str]] = None) -> int:
    """
    Purpose: Command-line entry point. Prints one JSON line made of ids and counts only, never a file name. A refused
        OCR preflight also prints its reason, which names the missing tool or language data and no report.
    Inputs:
        argv (list[str] | None): --reports DIR --work DIR [--dry-run] [--json].
    Outputs:
        int: 0 done, 2 refusal, 1 unexpected failure. With --dry-run nothing is written.
    Raises:
        None. Every error is turned into a printed JSON line and an exit code.
    """
    parser = argparse.ArgumentParser(description="Give the PDF reports of a folder an id and a Markdown file per page.")
    parser.add_argument("--reports", required=True, help="Folder of the reports.")
    parser.add_argument("--work", required=True, help="Work folder, directly inside the reports folder.")
    parser.add_argument("--dry-run", action="store_true", help="Count the reports and write nothing.")
    parser.add_argument("--json", action="store_true", help="JSON output (the only output).")
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)

    reports_dir = Path(args.reports)
    work_dir = Path(args.work)
    if not reports_dir.is_dir():
        print(json.dumps({"error": "reports folder not found", "status": "refused"}))
        return EXIT_REFUSAL
    try:
        if args.dry_run:
            _check_work_dir(reports_dir, work_dir)
            pdf_count = sum(1 for path in reports_dir.iterdir() if path.is_file() and _is_pdf(path))
            print(json.dumps({"reports": pdf_count, "skipped": skipped_count(reports_dir)}))
            return EXIT_OK
        results = prepare(reports_dir, work_dir)
        refused = [{"report_id": result["report_id"], "reason": result["refused"]}
                   for result in results if "refused" in result]
        print(json.dumps({"reports": len(results), "skipped": skipped_count(reports_dir),
                          "ids": [result["report_id"] for result in results], "refused": refused}))
        return EXIT_OK
    except OcrPreflightError as error:
        print(json.dumps({"error": "OCR preflight refused", "reason": str(error), "status": "refused"}))
        return EXIT_REFUSAL
    except PrepareError:
        print(json.dumps({"error": "preparation refused", "status": "refused"}))
        return EXIT_REFUSAL
    except Exception as error:
        print(json.dumps({"error": "unexpected error during preparation", "error_type": type(error).__name__,
                          "status": "failure"}))
        return EXIT_FAILURE


if __name__ == "__main__":
    sys.exit(main())
