"""
fig_export - turn a paper figure into a projector-grade asset.

The figures shipped next to an article are the wrong ones for a talk. They were
exported at the size the Word document needed (571 x 358 px for the Smart Safety
Helmet figure), which is unusable at five inches on a projector. The .svg beside
them is usually a draw.io wrapper, and pulling the base64 raster embedded in it
returns only the photo layer (425 x 567 px) and loses every vector label - measured,
and worse than the PNG it was meant to replace.

The correct move is to re-export the source through the draw.io CLI at scale 3,
which produced 4663 x 2435 and 3095 x 1551 on the CASE 2026 figures.

    drawio.exe -x -f png -s 3 --crop -o out.png in.svg

Two behaviours of that CLI cost time and are handled here: it returns before the
file is flushed on Windows, so the output is polled until its size is stable rather
than slept on; and a label typo in the source has to be fixed in the mxfile, which
--fix-text does into a copy under figsrc/, never in the figure the paper cites.

Usage
-----
    python fig_export.py fig1.svg --out assets/fig1_station.png
    python fig_export.py fig1.svg --out assets/fig1.png --scale 3 --fix-text typos.json
    python fig_export.py fig1.drawio --out assets/fig1.png --slide-width-in 5

typos.json is a flat {"wrong": "right"} map.

Exit codes: 0 exported, 1 the export produced nothing, 2 a usage error, a raster
input, or no draw.io CLI.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import struct
import subprocess
import sys
import time
import urllib.parse
import xml.sax.saxutils as saxutils

TAG = "[FIGEXPORT]"

RASTER_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tif", ".tiff", ".webp")
VECTOR_SUFFIXES = (".svg", ".drawio", ".xml")

# Where the draw.io CLI usually is on Windows, after the explicit flag and the
# environment variable have been tried.
DEFAULT_WINDOWS_PATHS = (
    os.path.expandvars(r"%LOCALAPPDATA%\Programs\draw.io\draw.io.exe"),
    os.path.expandvars(r"%ProgramFiles%\draw.io\draw.io.exe"),
)

# Below this, a figure looks soft on a projector.
MIN_DPI = 150


def find_drawio(explicit: str | None = None) -> str | None:
    """
    --------------------------------------------------------------------------
    Purpose:
        Locate the draw.io CLI in a fixed order, so a machine with an unusual
        install can be fixed with a flag or an environment variable rather than an
        edit to this file.

    Inputs:
        explicit (str): a path given on the command line, tried first

    Outputs:
        path (str): the executable, or None when nothing was found
    --------------------------------------------------------------------------
    """
    candidates = [explicit, os.environ.get("DRAWIO_EXE"), *DEFAULT_WINDOWS_PATHS]
    for cand in candidates:
        if cand and os.path.isfile(cand):
            return cand
    return shutil.which("drawio") or shutil.which("draw.io")


def png_size(path: str) -> tuple[int, int] | None:
    """
    --------------------------------------------------------------------------
    Purpose:
        Read a PNG's pixel size from its IHDR chunk, with no image library, so the
        resolution report costs nothing and works in an offline test.

    Inputs:
        path (str): path to a .png

    Outputs:
        size (tuple): width and height in pixels, or None when the file is not a PNG
    --------------------------------------------------------------------------
    """
    try:
        with open(path, "rb") as fh:
            head = fh.read(24)
    except OSError:
        return None
    if len(head) < 24 or head[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    w, h = struct.unpack(">II", head[16:24])
    return int(w), int(h)


def apply_fix_text(src: str, dst: str, mapping: dict[str, str]) -> dict[str, int]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Rewrite label typos inside a draw.io figure, into a copy. The mxfile lives
        URL-encoded in the SVG's `content` attribute, so the substitution has to
        happen after decoding and be re-encoded and re-escaped afterwards; the
        source figure the paper cites is never touched.

    Inputs:
        src (str): the .svg or .drawio to read
        dst (str): the copy to write
        mapping (dict): {"wrong": "right"} substitutions

    Outputs:
        counts (dict): substitutions applied, per key, zero entries included
    --------------------------------------------------------------------------
    """
    with open(src, encoding="utf8") as fh:
        text = fh.read()
    counts = {k: 0 for k in mapping}

    def substitute(payload: str) -> str:
        for wrong, right in mapping.items():
            counts[wrong] += payload.count(wrong)
            payload = payload.replace(wrong, right)
        return payload

    marker = 'content="'
    start = text.find(marker)
    if start != -1:
        start += len(marker)
        end = text.find('"', start)
        raw = text[start:end]
        decoded = urllib.parse.unquote(saxutils.unescape(raw))
        fixed = substitute(decoded)
        if fixed != decoded:
            reencoded = saxutils.escape(urllib.parse.quote(fixed, safe=""), {'"': "&quot;"})
            text = text[:start] + reencoded + text[end:]
    # Labels also appear as plain text in the rendered SVG body and in a bare
    # .drawio file, so the same substitution runs over the whole document.
    text = substitute(text)

    os.makedirs(os.path.dirname(os.path.abspath(dst)), exist_ok=True)
    with open(dst, "w", encoding="utf8") as fh:
        fh.write(text)
    return counts


def wait_for_output(path: str, timeout: float = 60.0, interval: float = 0.5) -> bool:
    """
    --------------------------------------------------------------------------
    Purpose:
        Wait for the draw.io CLI to finish writing. It returns before the file is
        flushed on Windows, so the file is considered done only once its size is
        the same across two consecutive reads.

    Inputs:
        path (str): the expected output file
        timeout (float): seconds before giving up
        interval (float): seconds between polls

    Outputs:
        ok (bool): True when the file exists and stopped growing
    --------------------------------------------------------------------------
    """
    deadline = time.monotonic() + timeout
    last = -1
    while time.monotonic() < deadline:
        if os.path.exists(path):
            size = os.path.getsize(path)
            if size > 0 and size == last:
                return True
            last = size
        time.sleep(interval)
    return os.path.exists(path) and os.path.getsize(path) > 0


def export(src: str, out: str, scale: int = 3, drawio: str | None = None,
           timeout: float = 60.0) -> bool:
    """
    --------------------------------------------------------------------------
    Purpose:
        Run the draw.io CLI export and wait for the result.

    Inputs:
        src (str): the vector source
        out (str): destination .png
        scale (int): export scale; 3 is what produced projector-grade assets
        drawio (str): CLI path override
        timeout (float): seconds to wait for the flush

    Outputs:
        ok (bool): True when a non-empty file exists afterwards
    --------------------------------------------------------------------------
    """
    exe = find_drawio(drawio)
    if not exe:
        raise RuntimeError(
            f"{TAG} draw.io CLI not found. Pass --drawio <path>, set DRAWIO_EXE, or "
            "install draw.io Desktop."
        )
    os.makedirs(os.path.dirname(os.path.abspath(out)) or ".", exist_ok=True)
    subprocess.run(
        [exe, "-x", "-f", "png", "-s", str(scale), "--crop", "-o",
         os.path.abspath(out), os.path.abspath(src)],
        check=False, capture_output=True,
    )
    return wait_for_output(os.path.abspath(out), timeout=timeout)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Export a figure at projector resolution.")
    ap.add_argument("source")
    ap.add_argument("--out", required=True)
    ap.add_argument("--scale", type=int, default=3)
    ap.add_argument("--fix-text", help="JSON map of label substitutions")
    ap.add_argument("--figsrc", default="figsrc",
                    help="directory for the corrected copy (default figsrc/)")
    ap.add_argument("--drawio", help="path to the draw.io CLI")
    ap.add_argument("--slide-width-in", type=float, default=5.0,
                    help="width the figure will occupy on the slide, for the DPI report")
    ap.add_argument("--timeout", type=float, default=60.0)
    args = ap.parse_args(argv)

    suffix = os.path.splitext(args.source)[1].lower()
    if suffix in RASTER_SUFFIXES:
        print(
            f"{TAG} {args.source} is a raster. Upscaling it would invent detail; export the "
            "vector source (.svg or .drawio) instead. Extracting the base64 raster embedded "
            "in a draw.io SVG is not a fallback either: it returns the photo layer only and "
            "loses every vector label.",
            file=sys.stderr,
        )
        return 2
    if suffix not in VECTOR_SUFFIXES:
        print(f"{TAG} unsupported input {suffix or '(none)'}; expected .svg or .drawio",
              file=sys.stderr)
        return 2

    source = args.source
    if args.fix_text:
        try:
            with open(args.fix_text, encoding="utf8") as fh:
                mapping = json.load(fh)
        except (OSError, json.JSONDecodeError) as exc:
            print(f"{TAG} cannot read {args.fix_text}: {exc}", file=sys.stderr)
            return 2
        copy = os.path.join(args.figsrc, os.path.basename(args.source))
        counts = apply_fix_text(args.source, copy, mapping)
        for wrong, n in counts.items():
            print(f"{TAG} '{wrong}' -> '{mapping[wrong]}' x{n}")
        if not any(counts.values()):
            print(f"{TAG} no substitution applied; check the map against the figure labels")
        source = copy

    try:
        ok = export(source, args.out, args.scale, args.drawio, args.timeout)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if not ok:
        print(f"{TAG} the export produced no file at {args.out}", file=sys.stderr)
        return 1

    size = png_size(args.out)
    if size:
        w, h = size
        dpi = w / args.slide_width_in if args.slide_width_in else 0
        print(f"{TAG} {args.out}  {w} x {h} px  -> {dpi:.0f} DPI at "
              f"{args.slide_width_in:g} in wide")
        if dpi < MIN_DPI:
            print(f"{TAG} WARNING below {MIN_DPI} DPI; raise --scale or narrow the placement")
    else:
        print(f"{TAG} {args.out} written (size unread: not a PNG)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
