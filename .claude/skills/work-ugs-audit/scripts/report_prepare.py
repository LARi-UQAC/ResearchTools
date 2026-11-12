"""
Report preparation - gives every PDF report of a folder a stable pseudonymous id and writes one Markdown file per page.

Purpose: the ids (R01, R02...) replace the file names everywhere after this step, and each page is kept as its own
Markdown file so that a later quote can be anchored on its page. File names appear only in the id map.
Exit codes: 0 done, 1 unexpected failure, 2 refusal.
"""
import argparse
import json
import sys
from pathlib import Path
from typing import Optional

import ugs_config

EXIT_OK = 0
EXIT_FAILURE = 1
EXIT_REFUSAL = 2
IDS_FILE_NAME = "ids.json"
PAGES_FOLDER = "pages"
PAGE_FILE_PREFIX = "p"
CONFIG_KEYS = ("reports.id_prefix", "reports.id_digits", "reports.page_digits")


class PrepareError(ValueError):
    """Raised when the reports cannot be prepared. Its message never holds a file name."""


def _is_pdf(file_path: Path) -> bool:
    """
    Purpose: Tell whether a file is a PDF by its extension.
    Inputs:
        file_path (Path): the file.
    Outputs:
        bool: True for a .pdf file, whatever the case of the extension.
    """
    return file_path.suffix.lower() == ".pdf"


def _load_settings() -> dict:
    """
    Purpose: Read the id and page-number formats from the shipped configuration.
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


def _extract_page_text(pdf_path: Path) -> list[str]:
    """
    Purpose: Extract the Markdown text of every page of a PDF, page by page.
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
        chunks = pymupdf4llm.to_markdown(str(pdf_path), page_chunks=True)
    except Exception as error:
        raise PrepareError(f"text extraction failed: {type(error).__name__}") from error
    return [chunk.get("text", "") for chunk in chunks]


def _write_page(work_dir: Path, report_id: str, page_number: int, text: str, page_digits: int) -> None:
    """
    Purpose: Write the Markdown file of one page.
    Inputs:
        work_dir (Path): the work folder.
        report_id (str): the id of the report.
        page_number (int): 1-based page number.
        text (str): the page text.
        page_digits (int): width of the zero-padded page number.
    Outputs:
        None. Writes work_dir/<id>/pages/p<number>.md.
    """
    pages_dir = work_dir / report_id / PAGES_FOLDER
    pages_dir.mkdir(parents=True, exist_ok=True)
    (pages_dir / f"{PAGE_FILE_PREFIX}{page_number:0{page_digits}d}.md").write_text(text, encoding="utf-8")


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
    Purpose: Refuse a work folder that is not a sibling of the reports folder.
    Details: The paths are resolved first, so links and '..' cannot escape the check. The work folder must share the
        parent of the reports folder and must not be the reports folder itself.
    Inputs:
        reports_dir (Path): the reports folder.
        work_dir (Path): the work folder.
    Outputs:
        None.
    Raises:
        PrepareError: when the work folder is the reports folder or is not beside it.
    """
    reports = reports_dir.resolve()
    work = work_dir.resolve()
    if work == reports or work.parent != reports.parent:
        raise PrepareError("the work folder must be a different folder beside the reports folder")


def prepare(reports_dir: Path, work_dir: Path) -> list[dict]:
    """
    Purpose: Give every PDF of the reports folder a stable id and write its pages as Markdown files.
    Details: Ids follow the sorted file names. A rerun keeps the ids already given, and a report added later takes
        the next number.
    Inputs:
        reports_dir (Path): the folder holding the PDF reports.
        work_dir (Path): the work folder, beside the reports folder.
    Outputs:
        list[dict]: one dict per PDF with 'report_id', 'pages' (count) and 'empty_pages' (1-based numbers).
        Side effects: writes ids.json and the page files in work_dir.
    Raises:
        PrepareError: when the work folder is not beside the reports folder, the id map is unreadable, the
            configuration is incomplete or a PDF cannot be read.
    """
    _check_work_dir(reports_dir, work_dir)
    settings = _load_settings()
    prefix = settings["reports.id_prefix"]
    id_digits = settings["reports.id_digits"]
    page_digits = settings["reports.page_digits"]

    ids_file = work_dir / IDS_FILE_NAME
    ids = _load_ids(ids_file)
    id_of_name = {name: report_id for report_id, name in ids.items()}
    taken = [int(report_id[len(prefix):]) for report_id in ids if report_id[len(prefix):].isdigit()]
    next_number = max(taken, default=0) + 1

    results = []
    for pdf_file in sorted(path for path in reports_dir.iterdir() if path.is_file() and _is_pdf(path)):
        report_id = id_of_name.get(pdf_file.name)
        if report_id is None:
            report_id = f"{prefix}{next_number:0{id_digits}d}"
            ids[report_id] = pdf_file.name
            id_of_name[pdf_file.name] = report_id
            next_number += 1
        pages = _extract_page_text(pdf_file)
        for number, text in enumerate(pages, start=1):
            _write_page(work_dir, report_id, number, text, page_digits)
        results.append({"report_id": report_id, "pages": len(pages),
                        "empty_pages": [number for number, text in enumerate(pages, start=1) if not text.strip()]})

    work_dir.mkdir(parents=True, exist_ok=True)
    ids_file.write_text(json.dumps(ids, indent=2, ensure_ascii=False), encoding="utf-8")
    return results


def skipped_count(reports_dir: Path) -> int:
    """
    Purpose: Count the files of the reports folder that are not PDFs.
    Inputs:
        reports_dir (Path): the reports folder.
    Outputs:
        int: the number of non-PDF files (folders are not counted).
    """
    return sum(1 for path in reports_dir.iterdir() if path.is_file() and not _is_pdf(path))


def main(argv: Optional[list[str]] = None) -> int:
    """
    Purpose: Command-line entry point. Prints one JSON line made of ids and counts only, never a file name.
    Inputs:
        argv (list[str] | None): --reports DIR --work DIR [--dry-run] [--json].
    Outputs:
        int: 0 done, 2 refusal, 1 unexpected failure. With --dry-run nothing is written.
    """
    parser = argparse.ArgumentParser(description="Give the PDF reports of a folder an id and a Markdown file per page.")
    parser.add_argument("--reports", required=True, help="Folder of the reports.")
    parser.add_argument("--work", required=True, help="Work folder, beside the reports folder.")
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
        print(json.dumps({"reports": len(results), "skipped": skipped_count(reports_dir),
                          "ids": [result["report_id"] for result in results]}))
        return EXIT_OK
    except PrepareError:
        print(json.dumps({"error": "preparation refused", "status": "refused"}))
        return EXIT_REFUSAL
    except Exception as error:
        print(json.dumps({"error": "unexpected error during preparation", "error_type": type(error).__name__,
                          "status": "failure"}))
        return EXIT_FAILURE


if __name__ == "__main__":
    sys.exit(main())
