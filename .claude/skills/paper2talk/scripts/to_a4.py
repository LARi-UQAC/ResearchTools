"""
to_a4 - reflow a slide-sized PDF onto real paper sheets.

The deck keeps its slide geometry (720 x 540 pt for 4:3) so the branded template
background is never stretched. Printing is a separate problem, solved after
rendering: each slide is scaled to fit a sheet and centred, leaving a printable
margin.

Do not get a paper-sized PDF by changing the slide size. PowerPoint's "A4 Paper"
preset is 10.83 x 7.5 in, a 1.444 ratio against 4:3's 1.333, so it stretches a
branded master background by 8 % and visibly distorts a logo.

Verify the result with `pdfinfo`, which prints the literal token (A4) next to the
page size when the box matches 841.89 x 595.276 pt. Assert on that token rather than
on the numbers.

Usage
-----
    python to_a4.py src.pdf dst.pdf
    python to_a4.py src.pdf dst.pdf --paper letter --orientation portrait
    python to_a4.py src.pdf dst.pdf --handout 4 --margin-mm 8

Exit codes: 0 written, 2 a usage, geometry or file error.
"""
from __future__ import annotations

import argparse
import sys

TAG = "[A4]"

MM = 72.0 / 25.4

# Portrait sizes in points. Letter landscape is 792 x 612.
PAPERS: dict[str, tuple[float, float]] = {
    "a4": (210.0 * MM, 297.0 * MM),
    "letter": (612.0, 792.0),
}

# Slides per sheet -> (columns, rows) on a PORTRAIT sheet. A landscape sheet swaps
# them, so a 2-up landscape handout puts the slides side by side rather than
# stacked, which is what a reader expects.
HANDOUT_GRIDS: dict[int, tuple[int, int]] = {
    1: (1, 1),
    2: (1, 2),
    4: (2, 2),
    6: (2, 3),
}


def sheet_size(paper: str, orientation: str) -> tuple[float, float]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Resolve a paper name and an orientation to a sheet in points.

    Inputs:
        paper (str): a4 or letter
        orientation (str): landscape or portrait

    Outputs:
        size (tuple): width and height in points
    --------------------------------------------------------------------------
    """
    key = (paper or "").strip().lower()
    if key not in PAPERS:
        raise ValueError(f"{TAG} unknown paper {paper!r}; expected one of {', '.join(PAPERS)}")
    w, h = PAPERS[key]
    if orientation == "landscape":
        w, h = h, w
    elif orientation != "portrait":
        raise ValueError(f"{TAG} unknown orientation {orientation!r}")
    return w, h


def grid_cells(handout: int, orientation: str) -> tuple[int, int]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Give the column and row count for a handout, transposed on a landscape
        sheet so the cells keep roughly the aspect of the slide they hold.

    Inputs:
        handout (int): slides per sheet, one of 1, 2, 4, 6
        orientation (str): landscape or portrait

    Outputs:
        grid (tuple): columns, rows
    --------------------------------------------------------------------------
    """
    if handout not in HANDOUT_GRIDS:
        raise ValueError(
            f"{TAG} handout {handout} not supported; expected one of "
            f"{', '.join(str(k) for k in HANDOUT_GRIDS)}"
        )
    cols, rows = HANDOUT_GRIDS[handout]
    return (rows, cols) if orientation == "landscape" else (cols, rows)


def placement(
    src_w: float, src_h: float, sheet_w: float, sheet_h: float,
    margin: float, cols: int = 1, rows: int = 1, index: int = 0,
) -> tuple[float, float, float]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Compute where one slide lands on a sheet: the uniform scale that fits it
        in its cell, and the offset that centres it there. Uniform scale is the
        whole point - a non-uniform fit is exactly the distortion this script
        exists to avoid.

    Inputs:
        src_w, src_h (float): the source page size in points
        sheet_w, sheet_h (float): the sheet size in points
        margin (float): margin on every side, in points
        cols, rows (int): the handout grid
        index (int): position in the grid, reading order, 0-based

    Outputs:
        placement (tuple): scale, dx, dy in points
    --------------------------------------------------------------------------
    """
    avail_w = sheet_w - 2 * margin
    avail_h = sheet_h - 2 * margin
    if avail_w <= 0 or avail_h <= 0:
        raise ValueError(f"{TAG} margin {margin / MM:.1f} mm too large for the sheet")
    cell_w = avail_w / cols
    cell_h = avail_h / rows
    scale = min(cell_w / src_w, cell_h / src_h)
    col = index % cols
    row = index // cols
    # PDF user space has its origin bottom-left, so row 0 sits at the top.
    cell_x = margin + col * cell_w
    cell_y = margin + (rows - 1 - row) * cell_h
    dx = cell_x + (cell_w - src_w * scale) / 2.0
    dy = cell_y + (cell_h - src_h * scale) / 2.0
    return scale, dx, dy


def reflow(
    src_path: str, dst_path: str, paper: str = "a4", orientation: str = "landscape",
    margin_mm: float = 5.0, handout: int = 1, verbose: bool = True,
) -> int:
    """
    --------------------------------------------------------------------------
    Purpose:
        Write every source page onto real sheets, centred and uniformly scaled,
        one slide per sheet or a handout grid of them.

    Inputs:
        src_path, dst_path (str): source and destination PDFs
        paper (str): a4 or letter
        orientation (str): landscape or portrait
        margin_mm (float): margin on every side; 5 mm because no desk printer
            reaches the sheet edge
        handout (int): slides per sheet, 1, 2, 4 or 6
        verbose (bool): print the first-page diagnostic line

    Outputs:
        pages (int): number of sheets written
    --------------------------------------------------------------------------
    """
    from pypdf import PageObject, PdfReader, PdfWriter, Transformation

    w, h = sheet_size(paper, orientation)
    cols, rows = grid_cells(handout, orientation)
    margin = margin_mm * MM

    reader = PdfReader(src_path)
    writer = PdfWriter()
    per_sheet = cols * rows
    sheet = None
    for i, src in enumerate(reader.pages):
        slot = i % per_sheet
        if slot == 0:
            sheet = PageObject.create_blank_page(width=w, height=h)
            writer.add_page(sheet)
            sheet = writer.pages[-1]
        sw = float(src.mediabox.width)
        sh = float(src.mediabox.height)
        scale, dx, dy = placement(sw, sh, w, h, margin, cols, rows, slot)
        sheet.merge_transformed_page(
            src, Transformation().scale(scale).translate(dx, dy)
        )
        if i == 0 and verbose:
            print(
                f"{TAG} source {sw:.0f} x {sh:.0f} pt -> sheet {w:.2f} x {h:.2f} pt "
                f"({paper} {orientation}, {cols}x{rows}), scale {scale:.4f}, "
                f"offset {dx / MM:.1f} / {dy / MM:.1f} mm"
            )

    with open(dst_path, "wb") as fh:
        writer.write(fh)
    if verbose:
        print(f"{TAG} wrote {len(writer.pages)} sheet(s) to {dst_path}")
    return len(writer.pages)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Reflow a slide-sized PDF onto paper sheets.")
    ap.add_argument("src")
    ap.add_argument("dst")
    ap.add_argument("--paper", choices=sorted(PAPERS), default="a4")
    ap.add_argument("--orientation", choices=["landscape", "portrait"], default="landscape")
    ap.add_argument("--margin-mm", type=float, default=5.0)
    ap.add_argument("--handout", type=int, default=1,
                    help="slides per sheet: 1, 2, 4 or 6")
    args = ap.parse_args(argv)

    try:
        reflow(args.src, args.dst, args.paper, args.orientation,
               args.margin_mm, args.handout)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"{TAG} cannot process {args.src}: {exc}", file=sys.stderr)
        return 2
    except ImportError:
        print(f"{TAG} pypdf is required: pip install pypdf", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
