import sys
import argparse
import json
import html
from pathlib import Path
from typing import Optional, List, Dict

import fitz

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
    import re
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
    import tempfile
    
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp_path = Path(tmp.name)
    
    # Create a new PDF with the story content
    writer = fitz.DocumentWriter(str(tmp_path))
    story = fitz.Story(html=html)
    
    page_rect = fitz.Rect(0, 0, 595, 842)
    
    while story.write(writer, page_rect):
        pass
    
    writer.close()
    
    # Open the original PDF and append the new pages
    doc = fitz.open(str(pdf))
    initial_pages = doc.page_count
    annex_doc = fitz.open(str(tmp_path))
    doc.insert_pdf(annex_doc)
    doc.saveIncr()
    doc.close()
    annex_doc.close()
    
    tmp_path.unlink()
    
    # Count pages added
    new_doc = fitz.open(str(pdf))
    pages_added = new_doc.page_count - initial_pages
    new_doc.close()
    
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
    
    try:
        with open(args.rubric, "r", encoding="utf-8") as f:
            rubric = json.load(f)
        with open(args.grade, "r", encoding="utf-8") as f:
            grade = json.load(f)
        with open(args.totals, "r", encoding="utf-8") as f:
            totals = json.load(f)
            
        if args.template:
            with open(args.template, "r", encoding="utf-8") as f:
                template = f.read()
        else:
            # Default template
            template = "<html><body><h1>{{REPORT_ID}} - Loop {{LOOP}}</h1><table>{{ROWS}}</table><p>Total: {{TOTAL}}</p></body></html>"
            
        rows = render_rows(rubric, grade, totals)
        html = build_html(template, rows, args.report_id, args.loop, totals.get("total"))
        
        pages_added = append_annex(Path(args.pdf), html)
        
        if args.json:
            print(json.dumps({"pages_added": pages_added}))
        else:
            print(pages_added)
            
        return 0
        
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

if __name__ == "__main__":
    sys.exit(main())
