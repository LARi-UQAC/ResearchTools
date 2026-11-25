import argparse
import json
import sys
from pathlib import Path
from typing import List, Dict, Optional, Any, Iterable, Tuple
import fitz

import element_labels

CLUSTER_GAP_PT = 2.0
RENDER_DPI = 150.0
# Axis labels sit outside the lines of a chart. Author's choice, unmeasured.
LABEL_MARGIN_PT = 30.0
CAPTION_PREFIXES = ("Figure", "Fig.", "Fig ")

# Keys of the extraction block of figure_criteria.json read by extract_elements (R0, R3).
ELEMENT_SETTING_KEYS = (
    "min_area_pt2",
    "background_threshold",
    "fragment_gap_pt",
    "table_overlap_ratio",
    "logo_max_area_pt2",
    "header_band_pt",
    "repeat_min_pages",
    "logo_size_tolerance_pt",
)
# Element id prefix per element type: F01 figures, T01 tables, L01 logos.
ELEMENT_ID_PREFIX = {"figure": "F", "table": "T", "table_image": "T", "logo": "L"}
TEXT_BLOCK_TYPE = 0


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


def _check_settings(settings: Dict[str, Any]) -> None:
    """
    Purpose: Refuse a settings dict that lacks one of the element extraction keys, naming the key (R3).
    Inputs:
        settings: Dict[str, Any] - the extraction settings as plain numbers.
    Outputs:
        None. Returns normally when every key of ELEMENT_SETTING_KEYS is present.
    Raises:
        ValueError: If a key is absent from settings.
    """
    for key in ELEMENT_SETTING_KEYS:
        if key not in settings:
            raise ValueError(
                f"extract_elements: setting '{key}' is missing "
                "(expected in the 'extraction' block of figure_criteria.json)"
            )


def _intersection_area(a: "fitz.Rect", b: "fitz.Rect") -> float:
    """
    Purpose: Measure the area two rectangles share, zero when they do not overlap.
    Inputs:
        a: fitz.Rect - first rectangle.
        b: fitz.Rect - second rectangle.
    Outputs:
        float - the shared area in square points.
    Raises:
        None.
    """
    width = min(a.x1, b.x1) - max(a.x0, b.x0)
    height = min(a.y1, b.y1) - max(a.y0, b.y0)
    if width <= 0 or height <= 0:
        return 0.0
    return width * height


def _table_overlap_ratio(region: "fitz.Rect", boxes: List["fitz.Rect"]) -> float:
    """
    Purpose: Give the largest share of a drawing region that lies inside one table box.
    Details: A region of zero area (a single rule) counts as inside a table when it touches the box,
        since its share of an area cannot be measured.
    Inputs:
        region: fitz.Rect - the drawing region.
        boxes: List[fitz.Rect] - the table boxes of the page.
    Outputs:
        float - a ratio from 0 to 1.
    Raises:
        None.
    """
    area = region.width * region.height
    best = 0.0
    for box in boxes:
        if area > 0:
            best = max(best, _intersection_area(region, box) / area)
        elif region.x0 <= box.x1 and region.x1 >= box.x0 and region.y0 <= box.y1 and region.y1 >= box.y0:
            best = 1.0
    return best


def _marker_barriers(blocks: List[tuple], markers: Dict[str, Any]) -> List["fitz.Rect"]:
    """
    Purpose: Collect the rectangles of the text blocks that open with a figure or table marker word.
    Details: Such a block is a title, so two regions with one of them between them are two elements (R3).
    Inputs:
        blocks: List[tuple] - the tuples of page.get_text("blocks").
        markers: Dict[str, Any] - the data returned by element_labels.load_markers.
    Outputs:
        List[fitz.Rect] - one rectangle per title-like text block.
    Raises:
        MarkerError: If the markers lack the figure or table prefix list.
    """
    prefixes = (list(element_labels._marker_prefixes(markers, "figure_prefixes"))
                + list(element_labels._marker_prefixes(markers, "table_prefixes")))
    barriers = []
    for block in blocks:
        if len(block) < 7 or block[6] != TEXT_BLOCK_TYPE:
            continue
        if element_labels._starts_with_marker(element_labels._clean(block[4]), prefixes):
            barriers.append(fitz.Rect(block[:4]))
    return barriers


def _blocked_by_title(a: "fitz.Rect", b: "fitz.Rect", barriers: List["fitz.Rect"]) -> bool:
    """
    Purpose: Tell whether a title lies in the vertical gap between two regions, which keeps them apart.
    Inputs:
        a: fitz.Rect - first region.
        b: fitz.Rect - second region.
        barriers: List[fitz.Rect] - the title rectangles of the page.
    Outputs:
        bool - True when a title lies between the two regions and across their horizontal extent.
    Raises:
        None.
    """
    if a.y1 <= b.y0:
        upper, lower = a, b
    elif b.y1 <= a.y0:
        upper, lower = b, a
    else:
        return False
    left = min(a.x0, b.x0)
    right = max(a.x1, b.x1)
    for barrier in barriers:
        if barrier.y0 >= upper.y1 and barrier.y1 <= lower.y0 and barrier.x0 < right and barrier.x1 > left:
            return True
    return False


def _merge_blocked(items: List[Tuple["fitz.Rect", bool]], gap: float,
                   barriers: List["fitz.Rect"]) -> List[Tuple["fitz.Rect", bool]]:
    """
    Purpose: Merge regions that lie within gap of each other, unless a title lies between them (R3).
    Inputs:
        items: List[Tuple[fitz.Rect, bool]] - each region with True when it is a raster image.
        gap: float - largest gap in points that still counts as touching.
        barriers: List[fitz.Rect] - the title rectangles of the page.
    Outputs:
        List[Tuple[fitz.Rect, bool]] - one bounding region per group, raster when any member is.
    Raises:
        None.
    """
    clusters = list(items)
    changed = True
    while changed:
        changed = False
        merged: List[Tuple["fitz.Rect", bool]] = []
        for rect, raster in clusters:
            for i, (other, other_raster) in enumerate(merged):
                if _touch(rect, other, gap) and not _blocked_by_title(rect, other, barriers):
                    merged[i] = (_union(other, rect), raster or other_raster)
                    changed = True
                    break
            else:
                merged.append((rect, raster))
        clusters = merged
    return clusters


def _vector_text_sizes(page: "fitz.Page", rect: "fitz.Rect") -> List[float]:
    """
    Purpose: Collect the font sizes of the labels around a vector drawing, caption lines excluded.
    Inputs:
        page: fitz.Page - the page holding the drawing.
        rect: fitz.Rect - the drawing rectangle.
    Outputs:
        List[float] - the sizes of the spans lying inside the label zone.
    Raises:
        None.
    """
    text_sizes: List[float] = []
    zone = fitz.Rect(rect.x0 - LABEL_MARGIN_PT, rect.y0 - LABEL_MARGIN_PT,
                     rect.x1 + LABEL_MARGIN_PT, rect.y1 + LABEL_MARGIN_PT)
    for block in page.get_text("dict", clip=zone)["blocks"]:
        if block["type"] != TEXT_BLOCK_TYPE:
            continue
        for line in block["lines"]:
            line_text = "".join(span["text"] for span in line["spans"]).strip()
            if line_text.startswith(CAPTION_PREFIXES):
                continue
            for span in line["spans"]:
                if zone.contains(fitz.Rect(span["bbox"])):
                    text_sizes.append(span["size"])
    return text_sizes


def _usable_tables(tables: List[Any]) -> Tuple[List[Tuple["fitz.Rect", str]], int]:
    """
    Purpose: Keep the tables PyMuPDF can read and count the others (F0). A table with no cells, which PyMuPDF
        builds from a table box holding no grid, has a lazy bbox that raises ValueError; such a table is dropped.
    Inputs:
        tables: List[Any] - the Table objects of one page, as find_tables returns them.
    Outputs:
        Tuple[List[Tuple[fitz.Rect, str]], int] - the (rectangle, Markdown) of each readable table, and the number
            of tables dropped.
    Raises:
        None: a ValueError from one table is counted, never raised.
    """
    kept: List[Tuple["fitz.Rect", str]] = []
    dropped = 0
    for table in tables:
        if not getattr(table, "cells", None):
            dropped += 1
            continue
        try:
            rect = fitz.Rect(table.bbox)
            markdown = table.to_markdown() or ""
        except ValueError:
            dropped += 1
            continue
        kept.append((rect, markdown))
    return kept, dropped


def _scan_page(page: "fitz.Page", page_no: int, settings: Dict[str, Any],
               markers: Dict[str, Any]) -> Dict[str, Any]:
    """
    Purpose: First pass over one page: find its tables and the merged regions that may be figures.
    Details: Regions overlapping a table box beyond table_overlap_ratio are dropped, the vector drawings are
        clustered as extract does, then the regions are merged with fragment_gap_pt unless a title lies between.
    Inputs:
        page: fitz.Page - the page to scan.
        page_no: int - the 1-based page number.
        settings: Dict[str, Any] - the extraction settings (see ELEMENT_SETTING_KEYS).
        markers: Dict[str, Any] - the data returned by element_labels.load_markers.
    Outputs:
        Dict[str, Any] - keys page_no, page, height, blocks, words, tables (rectangle and Markdown per table)
            and regions (rectangle and raster flag per figure candidate, area filter applied).
    Raises:
        MarkerError: If the markers are incomplete.
    """
    blocks = page.get_text("blocks")
    words = page.get_text("words")
    tables, tables_dropped = _usable_tables(page.find_tables().tables)
    table_boxes = [rect for rect, _markdown in tables]

    raster = [(fitz.Rect(img["bbox"]), True) for img in page.get_image_info()]
    vector_rects = [path["rect"] for path in page.get_drawings()
                    if path["rect"].width > 0 or path["rect"].height > 0]
    vector = [(rect, False) for rect in _merge_clusters(vector_rects, CLUSTER_GAP_PT)]

    regions = [(rect, is_raster) for rect, is_raster in raster + vector
               if _table_overlap_ratio(rect, table_boxes) < settings["table_overlap_ratio"]]
    merged = _merge_blocked(regions, settings["fragment_gap_pt"], _marker_barriers(blocks, markers))
    min_area = settings["min_area_pt2"]
    figures = [(rect, is_raster) for rect, is_raster in merged if rect.width * rect.height >= min_area]

    return {
        "page_no": page_no,
        "page": page,
        "height": page.rect.height,
        "blocks": blocks,
        "words": words,
        "tables": tables,
        "tables_dropped": tables_dropped,
        "regions": figures,
    }


def _in_band(rect: "fitz.Rect", page_height: float, band: float) -> bool:
    """
    Purpose: Tell whether a rectangle lies in the header or the footer band of its page.
    Inputs:
        rect: fitz.Rect - the rectangle.
        page_height: float - the page height in points.
        band: float - the band height in points.
    Outputs:
        bool - True when the top edge lies within band of the top, or the bottom edge within band of the bottom.
    Raises:
        None.
    """
    return rect.y0 <= band or rect.y1 >= page_height - band


def _is_repeated_logo(rect: "fitz.Rect", own_height: float, scans: List[Dict[str, Any]],
                      settings: Dict[str, Any]) -> bool:
    """
    Purpose: Decide whether a region is a logo: small, in the header or footer band, and of the same size
        in that band on at least repeat_min_pages pages (spec R1, the logo rule of plan 3).
    Inputs:
        rect: fitz.Rect - the candidate region.
        own_height: float - the height of the page holding the candidate.
        scans: List[Dict[str, Any]] - the first-pass results of every page kept.
        settings: Dict[str, Any] - the extraction settings.
    Outputs:
        bool - True when the region is a logo.
    Raises:
        None.
    """
    if rect.width * rect.height > settings["logo_max_area_pt2"]:
        return False
    band = settings["header_band_pt"]
    if not _in_band(rect, own_height, band):
        return False
    tolerance = settings["logo_size_tolerance_pt"]
    pages_with_it = set()
    for scan in scans:
        for other, _ in scan["regions"]:
            same_size = (abs(other.width - rect.width) <= tolerance
                         and abs(other.height - rect.height) <= tolerance)
            if same_size and _in_band(other, scan["height"], band):
                pages_with_it.add(scan["page_no"])
                break
    return len(pages_with_it) >= settings["repeat_min_pages"]


def _render_element(page: "fitz.Page", rect: "fitz.Rect", out_root: Path, file_name: str) -> "fitz.Pixmap":
    """
    Purpose: Render one element to a PNG file inside the output folder, as extract does (R24).
    Inputs:
        page: fitz.Page - the page holding the element.
        rect: fitz.Rect - the element rectangle.
        out_root: Path - the resolved output folder.
        file_name: str - the PNG file name.
    Outputs:
        fitz.Pixmap - the rendered pixels.
    Raises:
        ValueError: If the file would be written outside out_root.
    """
    file_path = (out_root / file_name).resolve()
    if out_root not in file_path.parents:
        raise ValueError("element file path leaves the output folder")
    zoom = RENDER_DPI / 72
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), clip=rect)
    pix.save(str(file_path))
    return pix


def _take_title(available: List[tuple], rect: "fitz.Rect", element_type: str,
                markers: Dict[str, Any]) -> Optional[Dict[str, str]]:
    """
    Purpose: Find the title of one element among the blocks not yet given to another element, and remove
        the block it came from, so that each title is attached to at most one element (plan 3 review focus).
    Inputs:
        available: List[tuple] - the page blocks still free; the chosen block is removed in place.
        rect: fitz.Rect - the element rectangle.
        element_type: str - "figure" or "table".
        markers: Dict[str, Any] - the data returned by element_labels.load_markers.
    Outputs:
        Optional[Dict[str, str]] - the title as element_labels.find_title gives it, or None.
    Raises:
        MarkerError: If the markers are incomplete.
    """
    title = element_labels.find_title(available, rect, element_type, markers)
    if title is None:
        return None
    matches = [block for block in available if element_labels._clean(block[4]) == title["text"]]

    def distance(block: tuple) -> float:
        """
        Purpose: Measure how far a candidate title block lies from the element.
        Inputs:
            block: tuple - a block tuple of page.get_text("blocks").
        Outputs:
            float - the gap in points, infinity when the block is beside the element.
        Raises:
            None.
        """
        placement = element_labels._gap_and_position(block, rect)
        return float("inf") if placement is None else placement[0]

    chosen = min(matches, key=distance)
    available.remove(chosen)
    return title


def extract_elements(pdf: Path, out_dir: Path, settings: Dict[str, Any], markers: Dict[str, Any],
                     skip_pages: Iterable[int] = (), stats: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """
    Purpose: Extract the elements of a PDF with a type: figures, tables and logos, with their titles,
        legends and notes, so that a table is never judged as a figure (spec R1 to R3).
    Details: Per page, the tables found by PyMuPDF are kept as tables and their boxes remove the drawings
        they contain. Figure regions are merged with fragment_gap_pt unless a title lies between them. A
        small region in the header or footer band that recurs on repeat_min_pages pages is a logo. Titles
        are attached once: an element takes the nearest title of its page and that title is no longer free.
        A picture with no figure title but with a table title is a table_image (plan 7, E4), numbered with the
        T prefix. The old extract() is not changed.
    Inputs:
        pdf: Path - the PDF file.
        out_dir: Path - the folder for the PNG files, created when absent.
        settings: Dict[str, Any] - the extraction settings as plain numbers (see ELEMENT_SETTING_KEYS).
        markers: Dict[str, Any] - the data returned by element_labels.load_markers.
        skip_pages: Iterable[int] - 1-based pages to leave out (cover, signature table, version table).
    Outputs:
        List[Dict[str, Any]] - one record per element in reading order, with element_id (F01, T01, L01),
            element_type, page, rect, file, title, legend, notes, caption and drawing_area_ratio (figures
            only); a figure also keeps figure_id, source and pixel_size or text_sizes; a table keeps markdown.
    Raises:
        FileNotFoundError: If the PDF does not exist.
        ValueError: If a setting is missing (naming the key) or a file would leave out_dir (R24).
        MarkerError: If the markers are incomplete.
    """
    _check_settings(settings)
    if not pdf.exists():
        raise FileNotFoundError(f"PDF file not found: {pdf}")
    out_root = out_dir.resolve()
    out_root.mkdir(parents=True, exist_ok=True)
    skipped = {int(page) for page in skip_pages}

    doc = fitz.open(str(pdf))
    try:
        scans = [_scan_page(doc[number - 1], number, settings, markers)
                 for number in range(1, doc.page_count + 1) if number not in skipped]
        if stats is not None:  # F0: tables dropped for having no readable cells, surfaced by the caller
            stats["tables_dropped"] = sum(scan["tables_dropped"] for scan in scans)

        pending: List[Dict[str, Any]] = []
        for scan in scans:
            items: List[Dict[str, Any]] = []
            for rect, markdown in scan["tables"]:
                items.append({"kind": "table", "rect": rect, "markdown": markdown, "raster": False})
            for rect, is_raster in scan["regions"]:
                kind = "logo" if _is_repeated_logo(rect, scan["height"], scans, settings) else "figure"
                items.append({"kind": kind, "rect": rect, "markdown": None, "raster": is_raster})
            items.sort(key=lambda item: (item["rect"].y0, item["rect"].x0))

            available = list(scan["blocks"])
            for item in items:
                item["scan"] = scan
                item["title"] = None
                item["notes"] = []
                item["legend"] = ""
                if item["kind"] in ("figure", "table"):
                    item["title"] = _take_title(available, item["rect"], item["kind"], markers)
                if item["kind"] == "figure" and item["title"] is None:
                    # Plan 7 (E4): a region with no figure title but a table title is a table drawn as a picture.
                    table_title = _take_title(available, item["rect"], "table", markers)
                    if table_title is not None:
                        item["kind"] = "table_image"
                        item["title"] = table_title
                if item["kind"] in ("table", "table_image"):
                    item["notes"] = element_labels.find_notes(scan["blocks"], item["rect"], markers)
                if item["kind"] == "figure":
                    title_text = item["title"]["text"] if item["title"] else None
                    item["legend"] = element_labels.find_legend(scan["words"], item["rect"], title_text)
                pending.append(item)

        counters = {prefix: 0 for prefix in ELEMENT_ID_PREFIX.values()}
        threshold = settings["background_threshold"]
        records: List[Dict[str, Any]] = []
        for item in pending:
            kind = item["kind"]
            prefix = ELEMENT_ID_PREFIX[kind]
            counters[prefix] += 1
            element_id = f"{prefix}{counters[prefix]:02d}"
            file_name = f"{element_id}.png"
            page = item["scan"]["page"]
            rect = item["rect"]
            pix = _render_element(page, rect, out_root, file_name)
            title = item["title"]
            record: Dict[str, Any] = {
                "element_id": element_id,
                "element_type": kind,
                "page": item["scan"]["page_no"],
                "rect": [rect.x0, rect.y0, rect.x1, rect.y1],
                "file": file_name,
                "title": title,
                "legend": item["legend"],
                "notes": item["notes"],
                "caption": title["text"] if title else None,
                "drawing_area_ratio": None,
            }
            if kind in ("figure", "table_image"):
                record["source"] = "raster" if item["raster"] else "vector"
                if item["raster"]:
                    record["pixel_size"] = [pix.width, pix.height]
                else:
                    record["text_sizes"] = _vector_text_sizes(page, rect)
            if kind == "figure":
                record["figure_id"] = element_id
                ratio = drawing_area_ratio(pix.samples, pix.width, pix.height, pix.n, threshold)
                record["drawing_area_ratio"] = round(ratio, 3)
            if kind == "table_image":
                del record["drawing_area_ratio"]  # plan 7: a table_image has no figure_id nor ratio
            if kind == "table":
                record["markdown"] = item["markdown"]
            records.append(record)
        return records
    finally:
        doc.close()


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
