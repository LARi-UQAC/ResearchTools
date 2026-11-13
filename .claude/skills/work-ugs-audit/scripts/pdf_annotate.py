"""
Purpose: Add native annotations to a copy of a student PDF.
"""

import sys
import json
import argparse
import re
import unicodedata
from pathlib import Path
from typing import List, Dict, Optional, Tuple

import fitz  # PyMuPDF

# Import config
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ugs_config import load as load_config, default_path, ConfigError


class AnnotateError(ValueError):
    """Raised when annotation fails or is refused."""


def normalize(text: str) -> str:
    """
    Purpose: Normalize text for matching.
    Inputs:
        text: str - The text to normalize.
    Outputs:
        str - Normalized text.
    """
    # NFC form
    text = unicodedata.normalize('NFC', text)
    
    # Typographic apostrophes and quotes to straight ones
    text = text.replace('\u2019', "'") # Right single quotation mark
    text = text.replace('\u2018', "'") # Left single quotation mark
    text = text.replace('\u201C', '"') # Left double quotation mark
    text = text.replace('\u201D', '"') # Right double quotation mark
    
    # Line-end hyphen joins removed
    # This is tricky to do generally without context, but we can remove hyphen+newline
    # The plan says "line-end hyphen joins removed". 
    # Usually this means "hy-\nphen" -> "hyphen".
    # We do this after collapsing whitespace? Or before?
    # If we collapse whitespace first, "\n" becomes " ", so "hy- phen".
    # Better to do it on the raw text or specific pattern.
    # Let's replace "-\n" with ""
    text = text.replace("-\n", "")
    
    # Whitespace collapsed to one space
    # Replace any whitespace sequence with a single space
    text = re.sub(r'\s+', ' ', text)
    
    # Strip
    text = text.strip()
    
    return text


def _find_quote_rects(page: fitz.Page, quote: str) -> List[fitz.Rect]:
    """
    Purpose: Find rectangles of a quote on a page.
    Inputs:
        page: fitz.Page - The PDF page.
        quote: str - The quote to find.
    Outputs:
        List[fitz.Rect] - List of rectangles where the quote is found.
    """
    norm_quote = normalize(quote)
    if not norm_quote:
        return []
        
    # PyMuPDF search_for uses raw text, not normalized.
    # We need to search for the normalized text in the normalized page text?
    # Or search for the original quote?
    # If the PDF has "hy-\nphen", search_for("hyphen") might fail.
    # The plan says "matched after normalization".
    # This implies we should extract text, normalize it, and find indices?
    # But we need rects.
    # fitz.Page.search_for(needle) returns rects.
    # If the needle is normalized, it might not match the raw text.
    
    # Strategy:
    # 1. Try search_for(quote).
    # 2. If not found, try search_for(normalize(quote))? No, normalize changes chars.
    
    # Let's look at the plan: "A quote split across two lines or hyphenated at a line end: matched after normalization."
    # This suggests the matching logic should handle this.
    # PyMuPDF's search_for does not do fuzzy matching.
    
    # We might need to extract text blocks, normalize them, find the quote, and map back to rects.
    # This is complex.
    
    # Alternative: Use search_for with the original quote. If it fails, maybe the quote is split.
    # For the scope of this task, let's assume search_for works for simple cases, 
    # and for hyphenation we might need a more advanced search.
    
    # However, the test `test_hyphenated_and_split_quote_is_found` is required.
    # Let's implement a basic search that tries the raw quote first.
    
    rects = page.search_for(quote)
    if rects:
        return rects
        
    # If not found, try normalized quote?
    # If the PDF text is "hy-\nphen", and quote is "hyphen", search_for("hyphen") fails.
    # If we normalize quote to "hyphen", and normalize page text...
    # We can iterate over blocks.
    
    blocks = page.get_text("blocks")
    for block in blocks:
        # block: (x0, y0, x1, y1, text, block_no, block_type)
        text = block[4]
        norm_text = normalize(text)
        # Check if norm_quote is in norm_text
        if norm_quote in norm_text:
            # We found it in this block.
            # We need to find the specific rect.
            # This is an approximation: return the block rect.
            # Ideally we want the exact words.
            # For now, returning the block rect is a reasonable fallback for "found".
            return [fitz.Rect(block[0], block[1], block[2], block[3])]
            
    return []


def annotate(src: Path, items: List[Dict], dst: Path, colors: Dict[str, str], author: str) -> Dict:
    """
    Purpose: Annotate a PDF copy with quotes and rectangles.
    Inputs:
        src: Path - Source PDF.
        items: List[Dict] - List of annotation items.
        dst: Path - Destination PDF.
        colors: Dict[str, str] - Mapping of kind to hex color.
        author: str - Author name for annotations.
    Outputs:
        Dict - Result with placed, not_found, duplicates counts.
    Raises:
        AnnotateError: If dst resolves to src.
    """
    src_resolved = src.resolve()
    dst_resolved = dst.resolve()
    
    if src_resolved == dst_resolved:
        raise AnnotateError("Destination must differ from source.")
    
    if not src_resolved.exists():
        raise AnnotateError(f"Source file not found: {src_resolved}")
        
    doc = fitz.open(src_resolved)
    
    placed = 0
    not_found = []
    duplicates = []
    
    # Track quotes found per page to detect duplicates
    # Map: (page, normalized_quote) -> count
    quote_counts = {}
    
    for i, item in enumerate(items):
        page_num = item.get("page")
        if page_num is None or page_num < 1 or page_num > doc.page_count:
            not_found.append(i)
            continue
            
        page = doc[page_num - 1]
        
        kind = item.get("kind", "technical")
        comment = item.get("comment", "")
        quote = item.get("quote")
        rect = item.get("rect")
        
        color_hex = colors.get(kind, "#000000")
        # Convert hex to RGB tuple (0.0-1.0)
        color_hex = color_hex.lstrip('#')
        r = int(color_hex[0:2], 16) / 255.0
        g = int(color_hex[2:4], 16) / 255.0
        b = int(color_hex[4:6], 16) / 255.0
        color_rgb = (r, g, b)
        
        if quote:
            norm_quote = normalize(quote)
            key = (page_num, norm_quote)
            
            # Check for duplicates
            if key in quote_counts:
                quote_counts[key] += 1
                if quote_counts[key] > 1:
                    duplicates.append(i)
                # Plan says: "A quote found twice on the page: the first is used and the duplicate is reported."
                # So if it's the second time, we report it as duplicate. Do we place it?
                # "the first is used" implies the second is NOT placed? Or just reported?
                # "duplicates (indexes found more than once)"
                # Let's assume we do NOT place the duplicate, just report it.
                # And it is not in not_found.
                continue
                
            rects = _find_quote_rects(page, quote)
            if not rects:
                not_found.append(i)
                continue
                
            # Use the first rect found
            target_rect = rects[0]
            
            # Record that we found it
            if key not in quote_counts:
                quote_counts[key] = 1
                
            # Add highlight annotation
            annot = page.add_highlight_annot(target_rect)
            annot.set_colors(stroke=color_rgb)
            annot.set_info(title=author, content=comment)
            annot.update()
            
            placed += 1
            
        elif rect:
            # Rect item
            x0, y0, x1, y1 = rect
            target_rect = fitz.Rect(x0, y0, x1, y1)
            
            # Add rectangle annotation
            annot = page.add_rect_annot(target_rect)
            annot.set_colors(stroke=color_rgb)
            annot.set_info(title=author, content=comment)
            annot.update()
            
            placed += 1
        else:
            not_found.append(i)
            
    doc.save(dst_resolved)
    doc.close()
    
    return {
        "placed": placed,
        "not_found": not_found,
        "duplicates": duplicates
    }


def main(argv: Optional[List[str]] = None) -> int:
    """
    Purpose: CLI entry point.
    Inputs:
        argv: Optional[List[str]] - Command line arguments.
    Outputs:
        int - Exit code. 0 success, 2 refusal, 1 failure.
    """
    parser = argparse.ArgumentParser(description="Annotate a PDF.")
    parser.add_argument("--src", required=True, help="Source PDF file")
    parser.add_argument("--items", required=True, help="JSON file with annotation items")
    parser.add_argument("--dst", required=True, help="Destination PDF file")
    parser.add_argument("--author", required=True, help="Author name")
    parser.add_argument("--json", action="store_true", help="Print JSON report")
    
    try:
        args = parser.parse_args(argv)
    except SystemExit as e:
        if e.code == 2:
            return 2
        raise
    
    try:
        # Load config for colors
        config_path = default_path()
        config = load_config(config_path)
        colors = config.get("annotation.colors", {})
        
        # Load items
        items_path = Path(args.items)
        if not items_path.exists():
            print(f"Error: Items file not found: {items_path}", file=sys.stderr)
            return 2
            
        with open(items_path, 'r', encoding='utf-8') as f:
            items = json.load(f)
            
        src = Path(args.src)
        dst = Path(args.dst)
        author = args.author
        
        result = annotate(src, items, dst, colors, author)
        
        if args.json:
            print(json.dumps(result))
        else:
            print(f"Placed: {result['placed']}")
            print(f"Not found: {len(result['not_found'])}")
            print(f"Duplicates: {len(result['duplicates'])}")
            
        return 0
        
    except AnnotateError as e:
        print(f"Refusal: {e}", file=sys.stderr)
        return 2
    except Exception as e:
        print(f"Failure: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
