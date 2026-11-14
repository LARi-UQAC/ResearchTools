import sys
import argparse
import io
import json
import re
import html
from pathlib import Path
from typing import Optional, List, Dict

import fitz

# Constants for PDF layout
PAGE_MARGIN = 36

DEFAULT_TEMPLATE = Path(__file__).resolve().parent.parent / "assets" / "annex.template.html"


class AnnexError(ValueError):
    """
    Purpose: Error raised when annex generation fails.
    """
    pass

def render_rows(rubric: dict, grade: dict, totals: dict) -> str:
    """
    Purpose: Render HTML rows for the rubric table.
    Inputs:
        rubric: dict - The rubric definition.
        grade: dict - The grade data.
        totals: dict - The totals data.
    Outputs:
        str - HTML string of table rows.
    """
    grade_items = {item["item_id"]: item for item in grade.get("items", [])}
    rows = []
    
    for item in rubric.get("items", []):
        item_id = item["id"]
        title = html.escape(item.get("title", ""))
        max_points = item.get("max_points", 0)
        
        grade_item = grade_items.get(item_id, {})
        status = grade_item.get("status", "not_run")
        score = grade_item.get("score")
        comment = html.escape(grade_item.get("comment", ""))
        
        if status == "not_run":
            score_str = "not_run"
        else:
            score_str = f"{score} / {max_points}"
            
        row = f"<tr><td>{title}</td><td>{score_str}</td><td>{status}</td><td>{comment}</td></tr>"
        rows.append(row)
        
    return "\n".join(rows)

def build_html(template: str, rows: str, report_id: str, loop: int, total: Optional[str]) -> str:
    """
    Purpose: Build the final HTML annex.
    Inputs:
        template: str - The HTML template.
        rows: str - The rendered rows.
        report_id: str - The report ID.
        loop: int - The loop number.
        total: Optional[str] - The total score string or None.
    Outputs:
        str - The final HTML string.
    Raises:
        AnnexError: If a placeholder is left unreplaced.
    """
    total_str = total if total is not None else "-"
    
    replacements = {
        "{{REPORT_ID}}": report_id,
        "{{LOOP}}": str(loop),
        "{{ROWS}}": rows,
        "{{TOTAL}}": total_str
    }
    
    result = template
    for placeholder, value in replacements.items():
        result = result.replace(placeholder, value)
        
    # Check for unreplaced placeholders
    remaining = re.findall(r"\{\{.*?\}\}", result)
    if remaining:
        raise AnnexError(f"Unreplaced placeholders found: {remaining}")
        
    return result

def append_annex(pdf: Path, html: str) -> int:
    """
    Purpose: Append the HTML annex to the PDF.
    Inputs:
        pdf: Path - Path to the PDF file.
        html: str - The HTML content to append.
    Outputs:
        int - Number of pages added.
    """
    buffer = io.BytesIO()
    writer = fitz.DocumentWriter(buffer)
    story = fitz.Story(html=html)

    page_rect = fitz.paper_rect("a4")
    content_rect = page_rect + (PAGE_MARGIN, PAGE_MARGIN, -PAGE_MARGIN, -PAGE_MARGIN)

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
        int - Exit code.
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--pdf", required=True)
    parser.add_argument("--rubric", required=True)
    parser.add_argument("--grade", required=True)
    parser.add_argument("--totals", required=True)
    parser.add_argument("--report-id", required=True)
    parser.add_argument("--loop", type=int, required=True)
    parser.add_argument("--template", default=None)
    parser.add_argument("--json", action="store_true")
    
    args = parser.parse_args(argv)
    
    pdf_path = Path(args.pdf)
    template_path = Path(args.template) if args.template else DEFAULT_TEMPLATE
    # Messages name no path: a file name can carry a student name.
    for path in (pdf_path, Path(args.rubric), Path(args.grade), Path(args.totals), template_path):
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

        rows = render_rows(rubric, grade, totals)
        html_text = build_html(template, rows, args.report_id, args.loop, totals.get("total"))
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
