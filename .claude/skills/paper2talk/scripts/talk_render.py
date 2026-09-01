"""
talk_render - render a deck to PDF and to page images, so the slides can be looked at.

Visual QA is not optional for slide work, and the render loop prescribed by the
document-skills pptx plugin (scripts/office/soffice.py) fails on this workstation:
its wrapper assumes a POSIX socket and raises `module 'socket' has no attribute
'AF_UNIX'`, with no LibreOffice installed behind it anyway. The measured working
path on Windows is PowerPoint COM SaveAs(path, 32) - 32 is ppSaveAsPDF - followed by
pdftoppm, which ships with the MiKTeX Poppler already on the machine.

Backends are tried in order and the chosen one is printed, because a silent
substitution changes what the images prove:

    1. soffice on PATH               (Linux, macOS, or a Windows box with LibreOffice)
    2. Windows PowerPoint COM        (Office 16 / Windows 11, measured working)
    3. fail with a message naming both, never a bare traceback

pdftoppm zero-pads page numbers by page count, so a 22-slide deck yields qa-01.jpg
rather than qa-1.jpg. The results are globbed, never named by construction.

The page count is compared to the slide count and a mismatch exits non-zero: a
silent short render is how a broken slide gets shipped.

Usage
-----
    python talk_render.py deck.pptx
    python talk_render.py deck.pptx --dpi 150 --out-dir qa
    python talk_render.py deck.pptx --paper a4 --orientation landscape

Exit codes: 0 rendered and the page count matches, 1 a page-count mismatch,
2 no backend or a file error.
"""
from __future__ import annotations

import argparse
import glob
import os
import platform
import re
import shutil
import subprocess
import sys
import zipfile

import to_a4

TAG = "[RENDER]"

# PowerPoint's ppSaveAsPDF export format.
PP_SAVE_AS_PDF = 32

_RE_SLIDE = re.compile(r"^ppt/slides/slide(\d+)\.xml$")


def slide_count(deck: str) -> int:
    """
    --------------------------------------------------------------------------
    Purpose:
        Count the slides in a .pptx by looking at the package, which is the only
        count that does not depend on a renderer having behaved.

    Inputs:
        deck (str): path to the .pptx

    Outputs:
        n (int): number of slide parts
    --------------------------------------------------------------------------
    """
    with zipfile.ZipFile(deck) as z:
        return sum(1 for n in z.namelist() if _RE_SLIDE.match(n))


def choose_backend() -> str | None:
    """
    --------------------------------------------------------------------------
    Purpose:
        Pick the conversion backend, in the order that works most often first.

    Inputs:
        None

    Outputs:
        backend (str): "soffice", "powerpoint-com", or None when neither is available
    --------------------------------------------------------------------------
    """
    if shutil.which("soffice"):
        return "soffice"
    if platform.system() == "Windows":
        return "powerpoint-com"
    return None


def _powershell_com_script(deck: str, pdf: str) -> str:
    """The COM conversion, opened read-only with no window and always released."""
    return (
        "$ErrorActionPreference = 'Stop';"
        "$pp = New-Object -ComObject PowerPoint.Application;"
        f"$deck = $pp.Presentations.Open('{deck}', $true, $false, $false);"
        f"$deck.SaveAs('{pdf}', {PP_SAVE_AS_PDF});"
        "$deck.Close();"
        "$pp.Quit();"
        "[System.Runtime.InteropServices.Marshal]::ReleaseComObject($pp) | Out-Null;"
    )


def convert_to_pdf(deck: str, pdf: str, backend: str | None = None) -> str:
    """
    --------------------------------------------------------------------------
    Purpose:
        Convert a .pptx to PDF with the first backend that works, and say which
        one ran.

    Inputs:
        deck (str): path to the .pptx
        pdf (str): destination PDF path
        backend (str): force a backend; default is choose_backend()

    Outputs:
        backend (str): the backend actually used
    --------------------------------------------------------------------------
    """
    backend = backend or choose_backend()
    deck = os.path.abspath(deck)
    pdf = os.path.abspath(pdf)
    if backend == "soffice":
        out_dir = os.path.dirname(pdf) or "."
        subprocess.run(
            ["soffice", "--headless", "--convert-to", "pdf", "--outdir", out_dir, deck],
            check=True, capture_output=True,
        )
        produced = os.path.join(out_dir, os.path.splitext(os.path.basename(deck))[0] + ".pdf")
        if produced != pdf and os.path.exists(produced):
            shutil.move(produced, pdf)
    elif backend == "powerpoint-com":
        subprocess.run(
            ["powershell.exe", "-NonInteractive", "-NoProfile", "-Command",
             _powershell_com_script(deck, pdf)],
            check=True, capture_output=True,
        )
    else:
        raise RuntimeError(
            f"{TAG} no conversion backend. Install LibreOffice so `soffice` is on PATH, "
            "or run this on Windows with PowerPoint (Office 16 or later) available to COM. "
            "The document-skills soffice.py wrapper does not work here: it assumes a POSIX "
            "socket and raises AF_UNIX."
        )
    print(f"{TAG} backend {backend} -> {pdf}")
    return backend


def rasterize(pdf: str, out_dir: str, dpi: int = 100, prefix: str = "qa",
              pages: str | None = None) -> list[str]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Turn the PDF into one JPEG per page for visual inspection, and return the
        paths found on disk rather than the paths expected: pdftoppm zero-pads the
        page number by the page count, so building the name is how an agent ends
        up reading nothing.

    Inputs:
        pdf (str): the rendered PDF
        out_dir (str): destination directory, created if absent
        dpi (int): raster resolution; 100 is legible for layout checks
        prefix (str): file-name prefix
        pages (str): "first-last" to limit the range

    Outputs:
        images (list): absolute paths, sorted
    --------------------------------------------------------------------------
    """
    os.makedirs(out_dir, exist_ok=True)
    cmd = ["pdftoppm", "-jpeg", "-r", str(dpi)]
    if pages:
        first, _, last = pages.partition("-")
        cmd += ["-f", first, "-l", last or first]
    cmd += [os.path.abspath(pdf), os.path.join(os.path.abspath(out_dir), prefix)]
    subprocess.run(cmd, check=True, capture_output=True)
    return sorted(
        os.path.abspath(p) for p in glob.glob(os.path.join(out_dir, prefix + "-*.jpg"))
    )


def pdf_page_count(pdf: str) -> int:
    """
    --------------------------------------------------------------------------
    Purpose:
        Count the pages of the rendered PDF, to compare against the slide count.

    Inputs:
        pdf (str): path to the PDF

    Outputs:
        n (int): page count
    --------------------------------------------------------------------------
    """
    from pypdf import PdfReader

    return len(PdfReader(pdf).pages)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Render a deck to PDF and page images.")
    ap.add_argument("deck")
    ap.add_argument("--dpi", type=int, default=100)
    ap.add_argument("--pages", help="page range for the raster pass, e.g. 1-22")
    ap.add_argument("--out-dir", default="qa")
    ap.add_argument("--pdf", help="PDF path (default: alongside the deck)")
    ap.add_argument("--backend", choices=["soffice", "powerpoint-com"],
                    help="force a backend instead of probing")
    ap.add_argument("--paper", choices=["slide", "a4", "letter"], default="slide",
                    help="also reflow the PDF onto paper sheets (see to_a4.py)")
    ap.add_argument("--orientation", choices=["landscape", "portrait"], default="landscape")
    ap.add_argument("--margin-mm", type=float, default=5.0)
    ap.add_argument("--handout", type=int, default=1, help="slides per sheet: 1, 2, 4 or 6")
    ap.add_argument("--no-raster", action="store_true", help="PDF only, skip the images")
    args = ap.parse_args(argv)

    deck = os.path.abspath(args.deck)
    pdf = os.path.abspath(args.pdf or os.path.splitext(deck)[0] + ".pdf")

    try:
        n_slides = slide_count(deck)
        convert_to_pdf(deck, pdf, args.backend)
    except (OSError, zipfile.BadZipFile, RuntimeError, subprocess.CalledProcessError) as exc:
        detail = getattr(exc, "stderr", b"") or b""
        print(f"{TAG} {exc}", file=sys.stderr)
        if detail:
            print(f"{TAG} {detail.decode('utf8', 'replace').strip()}", file=sys.stderr)
        return 2

    try:
        n_pages = pdf_page_count(pdf)
    except Exception as exc:  # pypdf raises several unrelated types on a broken file
        print(f"{TAG} cannot count pages in {pdf}: {exc}", file=sys.stderr)
        return 2

    print(f"{TAG} {n_slides} slide(s) -> {n_pages} page(s)")

    if args.paper != "slide":
        paper_pdf = os.path.splitext(pdf)[0] + f"_{args.paper}.pdf"
        try:
            to_a4.reflow(pdf, paper_pdf, args.paper, args.orientation,
                         args.margin_mm, args.handout)
        except (OSError, ValueError, ImportError) as exc:
            print(f"{TAG} paper reflow failed: {exc}", file=sys.stderr)
            return 2
        print(f"{TAG} paper PDF {paper_pdf}")

    if not args.no_raster:
        try:
            images = rasterize(pdf, args.out_dir, args.dpi, pages=args.pages)
        except (OSError, subprocess.CalledProcessError) as exc:
            print(f"{TAG} pdftoppm failed ({exc}); install Poppler or add it to PATH",
                  file=sys.stderr)
            return 2
        for path in images:
            print(path)

    if n_pages != n_slides:
        print(
            f"{TAG} FAIL page count {n_pages} does not match slide count {n_slides}; "
            "a short render hides a broken slide",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
