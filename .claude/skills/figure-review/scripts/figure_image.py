import argparse
import json
import math
import sys
from pathlib import Path
from typing import Dict, List, Optional

import fitz


class ImageError(ValueError):
    """Raised when an image operation fails."""


def estimated_tokens(width: int, height: int) -> int:
    """
    Purpose: Estimate the token cost of an image using the 28-pixel patch formula.
    Inputs:
        width: int - The width of the image in pixels.
        height: int - The height of the image in pixels.
    Outputs:
        int - The estimated number of tokens.
    """
    return math.ceil(width / 28) * math.ceil(height / 28)


def fit_for_model(src: Path, dst_dir: Path, max_long_edge: int, photo_colors: int, jpeg_quality: int) -> Dict:
    """
    Purpose: Downscale an image for a model and write it as PNG or JPEG.
    Inputs:
        src: Path - Path to the source image.
        dst_dir: Path - Destination directory for the output image.
        max_long_edge: int - Maximum allowed length of the longest edge.
        photo_colors: int - Threshold for distinct colors to classify as photo.
        jpeg_quality: int - Quality for JPEG output.
    Outputs:
        Dict - Contains 'file', 'format', 'width', 'height', 'estimated_tokens'.
    Raises:
        ImageError - If the source file is missing or unreadable.
    """
    if not src.exists():
        raise ImageError(f"Source file not found: {src}")
    
    try:
        pix = fitz.Pixmap(str(src))
    except Exception as e:
        raise ImageError(f"Unreadable source file: {src}") from e
    
    w, h = pix.width, pix.height
    long_edge = max(w, h)
    
    if long_edge > max_long_edge:
        scale = max_long_edge / long_edge
        new_w = max(1, round(w * scale))
        new_h = max(1, round(h * scale))
        pix = fitz.Pixmap(pix, new_w, new_h)
        w, h = new_w, new_h
    
    is_photo = pix.color_count() > photo_colors
    fmt = "jpeg" if is_photo else "png"
    ext = ".jpg" if is_photo else ".png"
    
    dst_dir.mkdir(parents=True, exist_ok=True)
    dst_path = dst_dir / (src.stem + ext)
    
    if is_photo:
        pix.save(str(dst_path), jpg_quality=jpeg_quality)
    else:
        pix.save(str(dst_path))
    
    return {
        "file": dst_path.name,
        "format": fmt,
        "width": w,
        "height": h,
        "estimated_tokens": estimated_tokens(w, h)
    }


def contact_sheet(files: List[Path], dst: Path, max_long_edge: int) -> Dict:
    """
    Purpose: Tile multiple images into one contact sheet image.
    Inputs:
        files: List[Path] - List of image paths to include.
        dst: Path - Path for the output contact sheet image.
        max_long_edge: int - Maximum allowed length of the longest edge for the sheet.
    Outputs:
        Dict - Contains 'file', 'tiles', 'width', 'height', 'estimated_tokens'.
    Raises:
        ImageError - If the list of files is empty.
    """
    if not files:
        raise ImageError("Empty list of files for contact sheet")
    
    n = len(files)
    cols = math.ceil(math.sqrt(n))
    rows = math.ceil(n / cols)
    
    max_cell = max_long_edge // max(cols, rows)
    cell_size = max(1, max_cell)
    
    sheet_w = cols * cell_size
    sheet_h = rows * cell_size
    
    doc = fitz.open()
    page = doc.new_page(width=sheet_w, height=sheet_h)
    
    for i, f in enumerate(files):
        r, c = divmod(i, cols)
        x0 = c * cell_size
        y0 = r * cell_size
        x1 = x0 + cell_size
        y1 = y0 + cell_size
        page.insert_image(fitz.Rect(x0, y0, x1, y1), filename=str(f))
    
    dst.parent.mkdir(parents=True, exist_ok=True)
    pix = page.get_pixmap()
    pix.save(str(dst))
    
    return {
        "file": dst.name,
        "tiles": n,
        "width": sheet_w,
        "height": sheet_h,
        "estimated_tokens": estimated_tokens(sheet_w, sheet_h)
    }


def main(argv: Optional[List[str]] = None) -> int:
    """
    Purpose: Command-line interface for fit_for_model.
    Inputs:
        argv: Optional[List[str]] - Command line arguments.
    Outputs:
        int - Exit code (0 success, 2 refusal, 1 failure).
    """
    parser = argparse.ArgumentParser(description="Fit image for model")
    parser.add_argument("--src", required=True, type=Path)
    parser.add_argument("--dst", required=True, type=Path)
    parser.add_argument("--max-long-edge", required=True, type=int)
    parser.add_argument("--photo-colors", required=True, type=int)
    parser.add_argument("--jpeg-quality", required=True, type=int)
    parser.add_argument("--json", action="store_true")
    
    args = parser.parse_args(argv)
    
    try:
        result = fit_for_model(args.src, args.dst, args.max_long_edge, args.photo_colors, args.jpeg_quality)
        if args.json:
            print(json.dumps(result))
        else:
            for k, v in result.items():
                print(f"{k}: {v}")
        return 0
    except ImageError:
        return 2
    except Exception:
        return 1


if __name__ == "__main__":
    sys.exit(main())
