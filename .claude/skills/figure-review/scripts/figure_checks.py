"""
Purpose: Script-measured figure criteria checks.
"""
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

# Constants for exit codes (R12)
EXIT_SUCCESS = 0
EXIT_FAILURE = 1
EXIT_REFUSAL = 2


class CriteriaError(ValueError):
    """Raised when criteria data is invalid or a requested criterion is not found."""
    pass


def load_criteria(path: Path) -> Dict[str, Any]:
    """
    Purpose: Load and validate the figure criteria JSON file.
    Inputs:
        path: Path to the JSON file.
    Outputs:
        Dict containing the criteria data.
    Raises:
        CriteriaError: If the file is missing keys or structure is invalid.
    """
    if not path.exists():
        raise CriteriaError(f"Criteria file not found: {path}")
    
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        raise CriteriaError(f"Invalid JSON in criteria file: {e}")

    required_keys = ["criteria"]
    for key in required_keys:
        if key not in data:
            raise CriteriaError(f"Missing key '{key}' in criteria file")
            
    criteria_list = data["criteria"]
    if not isinstance(criteria_list, list):
        raise CriteriaError("Key 'criteria' must be a list")
        
    for i, crit in enumerate(criteria_list):
        crit_id = crit.get("id", f"index_{i}")
        required_crit_keys = ["id", "level", "scope", "judged_by", "applies_to", "threshold", "label_fr", "label_en", "comment_fr", "comment_en"]
        for key in required_crit_keys:
            if key not in crit:
                raise CriteriaError(f"Criterion '{crit_id}' is missing key '{key}'")
                
    return data


def _get_threshold(criteria_doc: Dict[str, Any], criterion_id: str) -> Optional[float]:
    """
    Purpose: Get the threshold value for a specific criterion.
    Inputs:
        criteria_doc: The loaded criteria document.
        criterion_id: The ID of the criterion.
    Outputs:
        The threshold value (float) or None.
    Raises:
        CriteriaError: If the criterion is not found.
    """
    for crit in criteria_doc["criteria"]:
        if crit["id"] == criterion_id:
            threshold_obj = crit.get("threshold")
            if threshold_obj is None:
                return None
            if "value" not in threshold_obj:
                raise CriteriaError(f"Criterion '{criterion_id}' threshold is missing 'value'")
            return threshold_obj["value"]
    raise CriteriaError(f"Criterion '{criterion_id}' not found")


def check(figures: List[Dict], pages: List[str], body_font_size: float, criteria_doc: Dict[str, Any]) -> List[Dict]:
    """
    Purpose: Check the six script-measured criteria for each figure.
    Inputs:
        figures: List of figure records.
        pages: List of page texts.
        body_font_size: The body font size of the document.
        criteria_doc: The loaded criteria document.
    Outputs:
        List of figure records with 'criteria' object added.
    """
    results = []
    
    # Pre-calculate numbering sequence
    # Extract numbers from captions
    figure_numbers = []
    for fig in figures:
        caption = fig.get("caption")
        if caption:
            match = re.search(r"Figure\s+(\d+)", caption)
            if match:
                figure_numbers.append(int(match.group(1)))
            else:
                figure_numbers.append(None)
        else:
            figure_numbers.append(None)
            
    # Check sequence
    # Expected: 1, 2, 3...
    is_sequence_ok = True
    if figure_numbers:
        # If any is None, we can't verify sequence fully, but let's check the ones we have?
        # Plan says: "figure numbers read from the captions are 1, 2, 3 in order"
        # If a number is missing, it's a fail? 
        # "numbered_in_sequence (figure numbers read from the captions are 1, 2, 3 in order)"
        # Let's assume if we can't read a number, it fails or is not_run? 
        # The plan implies we check the ones we have. If there's a gap or repeat, fail.
        
        # Simple check: sort them and see if they match 1..N
        valid_numbers = [n for n in figure_numbers if n is not None]
        if len(valid_numbers) != len(figure_numbers):
             # Some missing numbers
             is_sequence_ok = False
        else:
             expected = list(range(1, len(figure_numbers) + 1))
             if sorted(valid_numbers) != expected:
                 is_sequence_ok = False

    # Pre-calculate first mention page for each figure number
    # We need to find the first page where "Figure N" or "Fig. N" appears
    first_mention_page = {}
    for page_idx, page_text in enumerate(pages):
        # Search for Figure N or Fig. N
        matches = re.findall(r"(?:Figure|Fig\.)\s*(\d+)", page_text)
        for num_str in matches:
            num = int(num_str)
            if num not in first_mention_page:
                first_mention_page[num] = page_idx + 1 # 1-based page number

    for i, fig in enumerate(figures):
        result_fig = fig.copy()
        result_fig["criteria"] = {}
        
        # 1. space_used_over_70
        crit_id = "space_used_over_70"
        threshold = _get_threshold(criteria_doc, crit_id)
        ratio = fig.get("drawing_area_ratio")
        if ratio is None or threshold is None:
            result_fig["criteria"][crit_id] = {"verdict": "not_run", "reason": "Missing data or threshold"}
        else:
            if ratio >= threshold:
                result_fig["criteria"][crit_id] = {"verdict": "pass", "reason": f"Ratio {ratio} >= {threshold}"}
            else:
                result_fig["criteria"][crit_id] = {"verdict": "fail", "reason": f"Ratio {ratio} < {threshold}"}

        # 2. effective_resolution
        crit_id = "effective_resolution"
        threshold = _get_threshold(criteria_doc, crit_id)
        source = fig.get("source")
        if source == "vector":
            result_fig["criteria"][crit_id] = {"verdict": "not_applicable", "reason": "Vector figure"}
        else:
            pixel_size = fig.get("pixel_size")
            rect = fig.get("rect")
            if not pixel_size or not rect or threshold is None:
                result_fig["criteria"][crit_id] = {"verdict": "not_run", "reason": "Missing data or threshold"}
            else:
                # rect is [x0, y0, x1, y1] in points
                width_pt = rect[2] - rect[0]
                height_pt = rect[3] - rect[1]
                # Use max dimension for DPI calculation? Or area? 
                # Usually DPI is based on one dimension. Let's use width.
                # 1 inch = 72 points
                width_inch = width_pt / 72.0
                if width_inch <= 0:
                     result_fig["criteria"][crit_id] = {"verdict": "not_run", "reason": "Invalid width"}
                else:
                    dpi = pixel_size[0] / width_inch
                    if dpi >= threshold:
                        result_fig["criteria"][crit_id] = {"verdict": "pass", "reason": f"DPI {dpi:.2f} >= {threshold}"}
                    else:
                        result_fig["criteria"][crit_id] = {"verdict": "fail", "reason": f"DPI {dpi:.2f} < {threshold}"}

        # 3. text_size
        crit_id = "text_size"
        threshold = _get_threshold(criteria_doc, crit_id)
        source = fig.get("source")
        if source == "raster":
            result_fig["criteria"][crit_id] = {"verdict": "not_run", "reason": "Raster figure"}
        else:
            text_sizes = fig.get("text_sizes")
            if not text_sizes or threshold is None or body_font_size is None:
                result_fig["criteria"][crit_id] = {"verdict": "not_run", "reason": "Missing data or threshold"}
            else:
                min_size = min(text_sizes)
                min_allowed = threshold * body_font_size
                if min_size >= min_allowed:
                    result_fig["criteria"][crit_id] = {"verdict": "pass", "reason": f"Min size {min_size} >= {min_allowed}"}
                else:
                    result_fig["criteria"][crit_id] = {"verdict": "fail", "reason": f"Min size {min_size} < {min_allowed}"}

        # 4. numbered_in_sequence
        crit_id = "numbered_in_sequence"
        if not is_sequence_ok:
             result_fig["criteria"][crit_id] = {"verdict": "fail", "reason": "Numbering sequence is irregular"}
        else:
             result_fig["criteria"][crit_id] = {"verdict": "pass", "reason": "Numbering sequence is correct"}

        # 5. called_before_appearing
        crit_id = "called_before_appearing"
        caption = fig.get("caption")
        if caption:
            match = re.search(r"Figure\s+(\d+)", caption)
            if match:
                num = int(match.group(1))
                fig_page = fig.get("page")
                mention_page = first_mention_page.get(num)
                
                if mention_page is None:
                    result_fig["criteria"][crit_id] = {"verdict": "fail", "reason": f"Figure {num} not called in text"}
                elif mention_page > fig_page:
                    result_fig["criteria"][crit_id] = {"verdict": "fail", "reason": f"Figure {num} called on page {mention_page}, appears on page {fig_page}"}
                else:
                    result_fig["criteria"][crit_id] = {"verdict": "pass", "reason": f"Figure {num} called on page {mention_page}, appears on page {fig_page}"}
            else:
                result_fig["criteria"][crit_id] = {"verdict": "not_run", "reason": "No figure number in caption"}
        else:
            result_fig["criteria"][crit_id] = {"verdict": "not_run", "reason": "No caption"}

        # 6. source_cited
        crit_id = "source_cited"
        if caption is None:
            result_fig["criteria"][crit_id] = {"verdict": "not_run", "reason": "No caption"}
        else:
            # Check for bracket reference [1] or word "Source"
            if re.search(r"\[\d+\]", caption) or "Source" in caption:
                result_fig["criteria"][crit_id] = {"verdict": "pass", "reason": "Source cited in caption"}
            else:
                result_fig["criteria"][crit_id] = {"verdict": "fail", "reason": "No source cited in caption"}

        results.append(result_fig)
        
    return results


def body_font_size(pdf: Path) -> float:
    """
    Purpose: Determine the most frequent span size in the PDF.
    Inputs:
        pdf: Path to the PDF file.
    Outputs:
        The most frequent font size (float).
    Raises:
        ValueError: If the PDF cannot be read or has no text.
    """
    import fitz # PyMuPDF
    
    if not pdf.exists():
        raise ValueError(f"PDF file not found: {pdf}")
        
    doc = fitz.open(str(pdf))
    sizes = []
    
    for page in doc:
        blocks = page.get_text("dict")["blocks"]
        for block in blocks:
            if block["type"] == 0: # Text block
                for line in block["lines"]:
                    for span in line["spans"]:
                        sizes.append(span["size"])
                        
    doc.close()
    
    if not sizes:
        raise ValueError("No text found in PDF")
        
    # Find most frequent
    from collections import Counter
    counter = Counter(sizes)
    most_common_size = counter.most_common(1)[0][0]
    
    return most_common_size


def failure_comment(criterion_id: str, criteria: List[Dict], language: str) -> str:
    """
    Purpose: Get the failure comment for a criterion in the specified language.
    Inputs:
        criterion_id: The ID of the criterion.
        criteria: The list of criteria dicts.
        language: "fr" or "en".
    Outputs:
        The comment string.
    Raises:
        CriteriaError: If the criterion or language is not found.
    """
    key = f"comment_{language}"
    if key not in ["comment_fr", "comment_en"]:
        raise CriteriaError(f"Unknown language: {language}")
        
    for crit in criteria:
        if crit["id"] == criterion_id:
            return crit[key]
            
    raise CriteriaError(f"Criterion '{criterion_id}' not found")


def main(argv: Optional[List[str]] = None) -> None:
    """
    Purpose: Main entry point for the figure checks script.
    Inputs:
        argv: Command line arguments.
    Outputs:
        None. Prints JSON to stdout.
    Raises:
        SystemExit: With code 0, 1, or 2.
    """
    import argparse
    
    parser = argparse.ArgumentParser(description="Check script-measured figure criteria")
    parser.add_argument("--figures", required=True, help="Path to figures JSON file")
    parser.add_argument("--pdf", required=True, help="Path to PDF file")
    parser.add_argument("--criteria", required=True, help="Path to criteria JSON file")
    parser.add_argument("--out", required=True, help="Path to output JSON file")
    parser.add_argument("--json", action="store_true", help="Output JSON to stdout as well")
    
    args = parser.parse_args(argv)
    
    try:
        # Load inputs
        with open(args.figures, 'r', encoding='utf-8') as f:
            figures = json.load(f)
            
        criteria_doc = load_criteria(Path(args.criteria))
        
        # Get body font size
        pdf_path = Path(args.pdf)
        b_font_size = body_font_size(pdf_path)
        
        # Read pages
        import fitz
        doc = fitz.open(str(pdf_path))
        pages = []
        for page in doc:
            pages.append(page.get_text())
        doc.close()
        
        # Check
        results = check(figures, pages, b_font_size, criteria_doc)
        
        # Write output
        with open(args.out, 'w', encoding='utf-8') as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
            
        if args.json:
            print(json.dumps(results, indent=2, ensure_ascii=False))
            
        # Print counts
        pass_count = sum(1 for fig in results for crit in fig["criteria"].values() if crit["verdict"] == "pass")
        fail_count = sum(1 for fig in results for crit in fig["criteria"].values() if crit["verdict"] == "fail")
        na_count = sum(1 for fig in results for crit in fig["criteria"].values() if crit["verdict"] == "not_applicable")
        nr_count = sum(1 for fig in results for crit in fig["criteria"].values() if crit["verdict"] == "not_run")
        
        print(f"Pass: {pass_count}, Fail: {fail_count}, Not Applicable: {na_count}, Not Run: {nr_count}")
        
    except CriteriaError as e:
        print(f"Criteria Error: {e}", file=sys.stderr)
        sys.exit(EXIT_REFUSAL)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(EXIT_FAILURE)


if __name__ == "__main__":
    main()
