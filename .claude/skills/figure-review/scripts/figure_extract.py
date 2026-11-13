import argparse
import json
import sys
from pathlib import Path
from typing import List, Dict, Optional, Any
import fitz


def drawing_area_ratio(samples: bytes, width: int, height: int, n: int, threshold: int, stride: int = None) -> float:
    """
    Purpose: Calculate the area of the bounding box of pixels darker than threshold.
    Inputs:
        samples: bytes - Raw pixel data.
        width: int - Image width in pixels.
        height: int - Image height in pixels.
        n: int - Number of channels.
        threshold: int - Brightness threshold (0-255).
        stride: int - Bytes per row. Defaults to width * n if not provided.
    Outputs:
        float - Ratio of bounding box area to total image area.
    """
    if stride is None:
        stride = width * n

    min_x = width
    min_y = height
    max_x = -1
    max_y = -1

    for y in range(height):
        row_offset = y * stride
        for x in range(width):
            idx = row_offset + x * n
            # Check if any channel is darker than threshold
            # "darker" means value < threshold
            is_dark = False
            for c in range(n):
                if samples[idx + c] < threshold:
                    is_dark = True
                    break
            
            if is_dark:
                if x < min_x: min_x = x
                if y < min_y: min_y = y
                if x > max_x: max_x = x
                if y > max_y: max_y = y

    if max_x == -1:
        return 0.0

    box_area = (max_x - min_x + 1) * (max_y - min_y + 1)
    total_area = width * height
    return box_area / total_area


def extract(pdf: Path, out_dir: Path, min_area_pt2: float, background_threshold: int) -> List[Dict[str, Any]]:
    """
    Purpose: Extract figures from a PDF.
    Inputs:
        pdf: Path - Path to the PDF file.
        out_dir: Path - Directory to save PNGs.
        min_area_pt2: float - Minimum area in pt^2.
        background_threshold: int - Threshold for background detection.
    Outputs:
        List[Dict] - List of figure records.
    Raises:
        FileNotFoundError: If PDF does not exist.
    """
    if not pdf.exists():
        raise FileNotFoundError(f"PDF file not found: {pdf}")

    doc = fitz.open(str(pdf))
    records = []
    figure_count = 0

    for page_num in range(doc.page_count):
        page = doc[page_num]
        page_rect = page.rect

        # 1. Find Raster Images
        raster_rects = []
        for img in page.get_image_info():
            bbox = fitz.Rect(img["bbox"])
            area = bbox.width * bbox.height
            if area >= min_area_pt2:
                raster_rects.append(bbox)

        # 2. Find Vector Drawings
        drawings = page.get_drawings()
        vector_rects = []
        for path in drawings:
            rect = path["rect"]
            # Accept lines (one dimension is 0) and filled shapes (both > 0)
            if rect.width > 0 or rect.height > 0:
                vector_rects.append(rect)

        # Merge touching/overlapping vector rects
        merged_vector_rects = []
        for rect in vector_rects:
            merged = False
            for i, existing in enumerate(merged_vector_rects):
                if existing.intersects(rect):
                    merged_vector_rects[i] = existing | rect
                    merged = True
                    break
            if not merged:
                merged_vector_rects.append(rect)

        # Filter merged vector rects by area and check for raster overlap
        valid_vector_rects = []
        for rect in merged_vector_rects:
            area = rect.width * rect.height
            if area < min_area_pt2:
                continue
            
            # Check if it contains any raster image
            contains_raster = False
            for r_rect in raster_rects:
                if r_rect.intersects(rect):
                    contains_raster = True
                    break
            
            if not contains_raster:
                valid_vector_rects.append(rect)

        # Collect all figures
        page_figures = []
        
        # Raster
        for rect in raster_rects:
            page_figures.append((rect, "raster"))
        
        # Vector
        for rect in valid_vector_rects:
            page_figures.append((rect, "vector"))

        # Sort by Y position (top to bottom) then X
        page_figures.sort(key=lambda item: (item[0].y0, item[0].x0))

        for rect, source in page_figures:
            figure_count += 1
            figure_id = f"F{figure_count:02d}"
            
            # Render to PNG
            # 150 DPI
            zoom = 150 / 72
            mat = fitz.Matrix(zoom, zoom)
            pix = page.get_pixmap(matrix=mat, clip=rect)
            
            # Save PNG
            file_name = f"{figure_id}.png"
            file_path = out_dir / file_name
            pix.save(str(file_path))
            
            record = {
                "figure_id": figure_id,
                "page": page_num + 1,
                "rect": [rect.x0, rect.y0, rect.x1, rect.y1],
                "file": file_name,
                "source": source,
                "drawing_area_ratio": 0.0,
                "caption": None
            }

            # Calculate ratio for both raster and vector using the rendered pixmap
            samples = pix.samples
            n = pix.n
            stride = pix.stride
            ratio = drawing_area_ratio(samples, pix.width, pix.height, n, background_threshold, stride)
            record["drawing_area_ratio"] = round(ratio, 3)

            if source == "raster":
                record["pixel_size"] = [pix.width, pix.height]
            else:
                # Vector
                # Find text sizes inside rect
                text_sizes = []
                blocks = page.get_text("dict", clip=rect)["blocks"]
                for block in blocks:
                    if block["type"] == 0: # Text
                        for line in block["lines"]:
                            for span in line["spans"]:
                                # Check if span is inside rect (already clipped, but just in case)
                                text_sizes.append(span["size"])
                
                record["text_sizes"] = text_sizes

            # Find Caption
            # Nearest text block below, else above, that starts with Figure/Fig.
            blocks = page.get_text("blocks")
            caption = None
            
            # Sort blocks by distance to rect
            def distance_to_rect(b):
                b_rect = fitz.Rect(b[:4])
                if b_rect.is_empty: return 99999
                # Distance from bottom of rect to top of block (below)
                d_below = b_rect.y0 - rect.y1
                # Distance from top of rect to bottom of block (above)
                d_above = rect.y0 - b_rect.y1
                
                # We want nearest.
                # Prefer below? "nearest text block below, else above"
                # This implies search below first? Or just nearest?
                # "nearest text block below, else above" -> Search below. If found, use it. If not, search above.
                
                return 0 # Placeholder

            # Search below
            candidates_below = []
            for b in blocks:
                b_rect = fitz.Rect(b[:4])
                if b_rect.y0 >= rect.y1:
                    text = b[4].strip()
                    if text.startswith("Figure") or text.startswith("Fig.") or text.startswith("Fig "):
                        candidates_below.append((b_rect.y0 - rect.y1, text))
            
            if candidates_below:
                candidates_below.sort(key=lambda x: x[0])
                caption = candidates_below[0][1]
            else:
                # Search above
                candidates_above = []
                for b in blocks:
                    b_rect = fitz.Rect(b[:4])
                    if b_rect.y1 <= rect.y0:
                        text = b[4].strip()
                        if text.startswith("Figure") or text.startswith("Fig.") or text.startswith("Fig "):
                            candidates_above.append((rect.y0 - b_rect.y1, text))
                
                if candidates_above:
                    candidates_above.sort(key=lambda x: x[0])
                    caption = candidates_above[0][1]

            record["caption"] = caption
            
            records.append(record)

    doc.close()
    return records


def main(argv: Optional[List[str]] = None) -> int:
    """
    Purpose: Command line interface for figure extraction.
    Inputs:
        argv: List[str] - Command line arguments.
    Outputs:
        int - Exit code.
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--pdf", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--min-area", type=float, default=100.0)
    parser.add_argument("--threshold", type=int, default=128)
    parser.add_argument("--json", action="store_true")

    args = parser.parse_args(argv)

    pdf_path = Path(args.pdf)
    out_dir = Path(args.out)

    if not pdf_path.exists():
        print(f"Error: PDF file not found: {pdf_path}", file=sys.stderr)
        sys.exit(2)

    try:
        out_dir.mkdir(parents=True, exist_ok=True)
        records = extract(pdf_path, out_dir, args.min_area, args.threshold)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    # Print counts per page
    page_counts = {}
    for rec in records:
        page_counts[rec["page"]] = page_counts.get(rec["page"], 0) + 1

    if args.json:
        print(json.dumps({
            "pages": page_counts,
            "figures": [r["figure_id"] for r in records]
        }, indent=2))
    else:
        for page, count in sorted(page_counts.items()):
            print(f"Page {page}: {count} figure(s)")
        print(f"Figure IDs: {', '.join(r['figure_id'] for r in records)}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
