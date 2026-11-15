import argparse
import json
import sys
from pathlib import Path
from typing import List, Dict, Optional, Any
import fitz

CLUSTER_GAP_PT = 2.0
RENDER_DPI = 150.0
# Axis labels sit outside the lines of a chart. Author's choice, unmeasured.
LABEL_MARGIN_PT = 30.0
CAPTION_PREFIXES = ("Figure", "Fig.", "Fig ")


def drawing_area_ratio(samples: bytes, width: int, height: int, n: int, threshold: int) -> float:
    """
    Purpose: Calculate the area of the bounding box of pixels darker than threshold.
    Inputs:
        samples: bytes - Raw pixel data.
        width: int - Image width in pixels.
        height: int - Image height in pixels.
        n: int - Number of channels.
        threshold: int - Brightness threshold (0-255).
    Outputs:
        float - Ratio of bounding box area to total image area.
    Raises:
        ValueError: If a dimension is not positive or samples is shorter than width * height * n.
    """
    if width <= 0 or height <= 0 or n <= 0:
        raise ValueError("image dimensions must be positive")
    if len(samples) < width * height * n:
        raise ValueError("samples is shorter than width * height * n")
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


def _touch(a: "fitz.Rect", b: "fitz.Rect", gap: float) -> bool:
    """
    Purpose: Tell whether two rectangles overlap or lie within gap points of each other.
    Details: Done by hand because PyMuPDF treats a zero-width or zero-height rectangle
        (every straight line of a chart) as empty and then never reports an overlap.
    Inputs:
        a: fitz.Rect - First rectangle.
        b: fitz.Rect - Second rectangle.
        gap: float - Largest gap in points that still counts as touching.
    Outputs:
        bool - True when the rectangles touch or overlap within gap.
    """
    dx = max(a.x0 - b.x1, b.x0 - a.x1)
    dy = max(a.y0 - b.y1, b.y0 - a.y1)
    return dx <= gap and dy <= gap


def _union(a: "fitz.Rect", b: "fitz.Rect") -> "fitz.Rect":
    """
    Purpose: Return the smallest rectangle holding both inputs, empty ones included.
    Inputs:
        a: fitz.Rect - First rectangle.
        b: fitz.Rect - Second rectangle.
    Outputs:
        fitz.Rect - The bounding rectangle.
    """
    return fitz.Rect(min(a.x0, b.x0), min(a.y0, b.y0), max(a.x1, b.x1), max(a.y1, b.y1))


def _merge_clusters(rects: List["fitz.Rect"], gap: float) -> List["fitz.Rect"]:
    """
    Purpose: Merge rectangles that touch within gap into clusters, until none touch.
    Inputs:
        rects: list of fitz.Rect - The drawing rectangles of one page.
        gap: float - Largest gap in points that still counts as touching.
    Outputs:
        list of fitz.Rect - One bounding rectangle per cluster.
    """
    clusters = list(rects)
    changed = True
    while changed:
        changed = False
        merged: List["fitz.Rect"] = []
        for rect in clusters:
            for i, other in enumerate(merged):
                if _touch(rect, other, gap):
                    merged[i] = _union(other, rect)
                    changed = True
                    break
            else:
                merged.append(rect)
        clusters = merged
    return clusters


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
        ValueError: If a figure file would be written outside out_dir (R24).
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

        merged_vector_rects = _merge_clusters(vector_rects, CLUSTER_GAP_PT)

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
            zoom = RENDER_DPI / 72
            mat = fitz.Matrix(zoom, zoom)
            pix = page.get_pixmap(matrix=mat, clip=rect)
            
            # Save PNG
            file_name = f"{figure_id}.png"
            out_root = out_dir.resolve()
            file_path = (out_root / file_name).resolve()
            if out_root not in file_path.parents:
                raise ValueError("figure file path leaves the output folder")
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
            ratio = drawing_area_ratio(samples, pix.width, pix.height, n, background_threshold)
            record["drawing_area_ratio"] = round(ratio, 3)

            if source == "raster":
                record["pixel_size"] = [pix.width, pix.height]
            else:
                # Vector
                # Sizes of the label spans around the drawing, caption lines excluded
                text_sizes = []
                zone = fitz.Rect(rect.x0 - LABEL_MARGIN_PT, rect.y0 - LABEL_MARGIN_PT,
                                 rect.x1 + LABEL_MARGIN_PT, rect.y1 + LABEL_MARGIN_PT)
                blocks = page.get_text("dict", clip=zone)["blocks"]
                for block in blocks:
                    if block["type"] != 0:
                        continue
                    for line in block["lines"]:
                        line_text = "".join(span["text"] for span in line["spans"]).strip()
                        if line_text.startswith(CAPTION_PREFIXES):
                            continue
                        for span in line["spans"]:
                            if zone.contains(fitz.Rect(span["bbox"])):
                                text_sizes.append(span["size"])

                record["text_sizes"] = text_sizes

            # Find Caption
            # Nearest text block below, else above, that starts with Figure/Fig.
            blocks = page.get_text("blocks")
            caption = None

            # Search below
            candidates_below = []
            for b in blocks:
                b_rect = fitz.Rect(b[:4])
                if b_rect.y0 >= rect.y1:
                    text = b[4].strip()
                    if text.startswith(CAPTION_PREFIXES):
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
                        if text.startswith(CAPTION_PREFIXES):
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
        int - Exit code: 0 done, 2 refusal (missing PDF, invalid path), 1 failure.
    Raises:
        SystemExit: argparse exits with code 2 on an unknown or missing option.
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--pdf", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--min-area", type=float, required=True)
    parser.add_argument("--threshold", type=int, required=True)
    parser.add_argument("--json", action="store_true")

    args = parser.parse_args(argv)

    pdf_path = Path(args.pdf)
    out_dir = Path(args.out)

    # R17: confine every path derived from input
    try:
        out_dir_resolved = out_dir.resolve()
        pdf_path_resolved = pdf_path.resolve()
    except Exception as e:
        print(f"Error: Invalid path: {e}", file=sys.stderr)
        return 2

    if not pdf_path_resolved.exists():
        print(f"Error: PDF file not found", file=sys.stderr)
        return 2

    # Check if out_dir is inside a valid location? 
    # Spec says: "2 on a refusal (missing file, output outside the output folder)" 
    # This likely means out_dir must be resolvable and writable.
    
    try:
        out_dir_resolved.mkdir(parents=True, exist_ok=True)
        records = extract(pdf_path_resolved, out_dir_resolved, args.min_area, args.threshold)
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
