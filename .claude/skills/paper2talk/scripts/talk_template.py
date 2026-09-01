"""
talk_template - read a template .pptx and emit its brand contract as JSON.

A lab gabarit is rarely a layout. The LAR.i deck carries one slideLayout and the
whole brand is a full-slide JPEG in the master plus a picture cropped with
srcRect b="71648". Re-creating that by eye wastes a pass and gets the geometry
wrong; reading it out of the XML gets it exact, which is why the generator reads
this file instead of guessing.

Two conversions matter and both were verified against the rendered template:

    EMU to inches      off/ext divided by 914400
    srcRect            l/t/r/b in thousandths of a percent, so b="71648" crops
                       71.648 % off the bottom and keeps the top 28.352 %

The package is only ever read. Round-tripping OOXML through ElementTree rewrites
namespace prefixes and corrupts the file, so nothing here writes back into the
.pptx; --extract-media copies bytes out untouched.

Usage
-----
    python talk_template.py template.pptx
    python talk_template.py template.pptx --out brand.json --extract-media assets/
    python talk_template.py template.pptx --slides 1,2,3

Exit codes: 0 read, 2 a usage or file error.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import zipfile

try:  # defusedxml refuses entity expansion; a .pptx is still someone else's file
    from defusedxml import ElementTree as ET
    _PARSER = "defusedxml"
except ImportError:  # pragma: no cover - exercised only on a machine without it
    import xml.etree.ElementTree as ET  # noqa: S405 - read-only, never written back
    _PARSER = "xml.etree (defusedxml not installed)"

TAG = "[TEMPLATE]"

EMU_PER_INCH = 914400.0
# srcRect crops are thousandths of a percent: 100000 is the whole edge.
SRCRECT_FULL = 100000.0

NS = {
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
}

_RE_SLIDE = re.compile(r"^ppt/slides/slide(\d+)\.xml$")
_RE_LAYOUT = re.compile(r"^ppt/slideLayouts/slideLayout(\d+)\.xml$")


def emu_to_in(value: str | int | float | None) -> float | None:
    """
    --------------------------------------------------------------------------
    Purpose:
        Convert an OOXML English Metric Unit to inches, the unit every renderer
        in this skill positions with.

    Inputs:
        value: an EMU quantity as written in the XML, or None

    Outputs:
        inches (float): the value in inches, or None when the attribute is absent
    --------------------------------------------------------------------------
    """
    if value in (None, ""):
        return None
    return round(float(value) / EMU_PER_INCH, 4)


def src_rect_keep(attrs: dict) -> dict | None:
    """
    --------------------------------------------------------------------------
    Purpose:
        Turn a srcRect crop into the fraction of the source image that survives,
        which is what a generator needs. The raw attributes say how much is thrown
        away, in thousandths of a percent, and that inversion is the step that is
        easy to get backwards.

    Inputs:
        attrs (dict): the srcRect element's attributes (l, t, r, b), any missing

    Outputs:
        keep (dict): l, t, r, b as crop fractions plus keep_w and keep_h, or None
            when nothing is cropped
    --------------------------------------------------------------------------
    """
    if not attrs:
        return None
    crop = {k: float(attrs.get(k, 0)) / SRCRECT_FULL for k in ("l", "t", "r", "b")}
    keep_w = 1.0 - crop["l"] - crop["r"]
    keep_h = 1.0 - crop["t"] - crop["b"]
    return {
        "crop_l": round(crop["l"], 6),
        "crop_t": round(crop["t"], 6),
        "crop_r": round(crop["r"], 6),
        "crop_b": round(crop["b"], 6),
        "keep_w": round(keep_w, 6),
        "keep_h": round(keep_h, 6),
    }


def _xfrm(elem) -> dict:
    """Position and size of a shape, in inches, or an empty dict when inherited."""
    xfrm = elem.find("./p:spPr/a:xfrm", NS)
    if xfrm is None:
        return {}
    off = xfrm.find("a:off", NS)
    ext = xfrm.find("a:ext", NS)
    out = {}
    if off is not None:
        out["x_in"] = emu_to_in(off.get("x"))
        out["y_in"] = emu_to_in(off.get("y"))
    if ext is not None:
        out["w_in"] = emu_to_in(ext.get("cx"))
        out["h_in"] = emu_to_in(ext.get("cy"))
    if xfrm.get("rot"):
        out["rot_deg"] = round(float(xfrm.get("rot")) / 60000.0, 2)
    return out


def _text_of(elem) -> dict:
    """Text, first run's size and weight, and the paragraph alignment."""
    body = elem.find("./p:txBody", NS)
    if body is None:
        return {}
    runs = body.findall(".//a:r", NS)
    text = "".join((r.findtext("a:t", default="", namespaces=NS) or "") for r in runs)
    out: dict = {"text": text.strip()}
    if runs:
        rpr = runs[0].find("a:rPr", NS)
        if rpr is not None:
            if rpr.get("sz"):
                out["font_size_pt"] = float(rpr.get("sz")) / 100.0
            out["bold"] = rpr.get("b") == "1"
            latin = rpr.find("a:latin", NS)
            if latin is not None:
                out["typeface"] = latin.get("typeface")
    ppr = body.find(".//a:pPr", NS)
    if ppr is not None and ppr.get("algn"):
        out["align"] = ppr.get("algn")
    return out


def read_objects(xml: str, rels: dict[str, str]) -> list[dict]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Describe every picture and text box on one slide, so the generator can
        place its own content in the same rectangles instead of approximating
        them.

    Inputs:
        xml (str): the slide part, decoded
        rels (dict): relationship id -> target, for resolving picture sources

    Outputs:
        objects (list): one dict per shape, with geometry, text and src_rect
    --------------------------------------------------------------------------
    """
    root = ET.fromstring(xml)
    tree = root.find("./p:cSld/p:spTree", NS)
    if tree is None:
        return []
    objects: list[dict] = []
    for pic in tree.findall("p:pic", NS):
        entry = {"type": "picture"}
        name = pic.find("./p:nvPicPr/p:cNvPr", NS)
        if name is not None:
            entry["name"] = name.get("name")
        entry.update(_xfrm(pic))
        blip = pic.find("./p:blipFill/a:blip", NS)
        if blip is not None:
            rid = blip.get(f"{{{NS['r']}}}embed")
            entry["media"] = rels.get(rid)
        rect = pic.find("./p:blipFill/a:srcRect", NS)
        if rect is not None:
            entry["src_rect"] = src_rect_keep(rect.attrib)
        objects.append(entry)
    for shape in tree.findall("p:sp", NS):
        entry = {"type": "shape"}
        name = shape.find("./p:nvSpPr/p:cNvPr", NS)
        if name is not None:
            entry["name"] = name.get("name")
        entry.update(_xfrm(shape))
        entry.update(_text_of(shape))
        objects.append(entry)
    return objects


def read_rels(z: zipfile.ZipFile, part: str) -> dict[str, str]:
    """Relationship id -> package path, for one part."""
    folder, name = os.path.split(part)
    rels_path = f"{folder}/_rels/{name}.rels"
    if rels_path not in z.namelist():
        return {}
    root = ET.fromstring(z.read(rels_path).decode("utf8"))
    out = {}
    for rel in root:
        target = rel.get("Target", "")
        rid = rel.get("Id")
        if target.startswith("../"):
            target = "ppt/" + target[3:]
        elif not target.startswith("/") and folder:
            target = f"{folder}/{target}"
        out[rid] = target.lstrip("/")
    return out


# A legacy binary PowerPoint file is an OLE compound document, not a zip.
_OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"

# PowerPoint's ppSaveAsOpenXMLPresentation export format.
PP_SAVE_AS_PPTX = 24


def is_legacy_ppt(path: str) -> bool:
    """
    --------------------------------------------------------------------------
    Purpose:
        Tell a legacy `.ppt` from an OOXML `.pptx` by its magic bytes rather than
        its extension, so the caller gets an actionable message instead of a
        BadZipFile traceback. The 4:3 lab gabarit shipped in this format.

    Inputs:
        path (str): the file to test

    Outputs:
        legacy (bool): True when the file is an OLE compound document
    --------------------------------------------------------------------------
    """
    try:
        with open(path, "rb") as fh:
            return fh.read(8) == _OLE_MAGIC
    except OSError:
        return False


def convert_legacy(path: str, out_path: str | None = None) -> str:
    """
    --------------------------------------------------------------------------
    Purpose:
        Save a legacy `.ppt` as `.pptx` through PowerPoint COM, leaving the
        original untouched. Nothing in this toolchain can read the binary format,
        and re-typing a gabarit by hand is how branding drifts.

    Inputs:
        path (str): the legacy .ppt
        out_path (str): destination; default is the same name with a .pptx suffix

    Outputs:
        out_path (str): the converted file
    --------------------------------------------------------------------------
    """
    import subprocess

    src = os.path.abspath(path)
    dst = os.path.abspath(out_path or os.path.splitext(src)[0] + ".pptx")
    script = (
        "$ErrorActionPreference = 'Stop';"
        "$pp = New-Object -ComObject PowerPoint.Application;"
        f"$deck = $pp.Presentations.Open('{src}', $true, $false, $false);"
        f"$deck.SaveAs('{dst}', {PP_SAVE_AS_PPTX});"
        "$deck.Close(); $pp.Quit();"
        "[System.Runtime.InteropServices.Marshal]::ReleaseComObject($pp) | Out-Null;"
    )
    subprocess.run(["powershell.exe", "-NonInteractive", "-NoProfile", "-Command", script],
                   check=True, capture_output=True)
    if not os.path.exists(dst):
        raise RuntimeError(f"{TAG} the conversion produced no file at {dst}")
    print(f"{TAG} converted {os.path.basename(src)} -> {os.path.basename(dst)}")
    return dst


def read_contract(path: str, slides: list[int] | None = None) -> dict:
    """
    --------------------------------------------------------------------------
    Purpose:
        Read the whole brand contract of a template: canvas, layouts, master
        background, and the objects of the sample slides. No LAR.i constant lives
        anywhere in this file - any .pptx must work, because the lab gabarit is
        still being prepared and the CASE 2026 deck is only a stand-in.

    Inputs:
        path (str): path to the template .pptx
        slides (list): 1-based slide numbers to describe; default the first two

    Outputs:
        contract (dict): canvas, layouts, master_background, objects, parser
    --------------------------------------------------------------------------
    """
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        pres = ET.fromstring(z.read("ppt/presentation.xml").decode("utf8"))
        size = pres.find("p:sldSz", NS)
        w_in = emu_to_in(size.get("cx")) if size is not None else None
        h_in = emu_to_in(size.get("cy")) if size is not None else None
        ratio = (w_in / h_in) if (w_in and h_in) else None
        aspect = None
        if ratio:
            aspect = min(
                (("4:3", 4 / 3), ("16:9", 16 / 9), ("9:16", 9 / 16)),
                key=lambda kv: abs(kv[1] - ratio),
            )[0]

        layouts = []
        for name in sorted(n for n in names if _RE_LAYOUT.match(n)):
            root = ET.fromstring(z.read(name).decode("utf8"))
            csld = root.find("p:cSld", NS)
            layouts.append({"part": name, "name": csld.get("name") if csld is not None else None})

        master_background = None
        master = "ppt/slideMasters/slideMaster1.xml"
        if master in names:
            rels = read_rels(z, master)
            root = ET.fromstring(z.read(master).decode("utf8"))
            blip = root.find(".//p:bg//a:blip", NS)
            if blip is None:
                # Many gabarits carry the background as a full-slide picture in the
                # master's shape tree rather than in <p:bg>.
                blip = root.find("./p:cSld/p:spTree/p:pic/p:blipFill/a:blip", NS)
            if blip is not None:
                master_background = rels.get(blip.get(f"{{{NS['r']}}}embed"))

        available = sorted(
            int(m.group(1)) for m in (_RE_SLIDE.match(n) for n in names) if m
        )
        wanted = slides or available[:2]
        objects = {}
        for n in wanted:
            part = f"ppt/slides/slide{n}.xml"
            if part not in names:
                continue
            objects[str(n)] = read_objects(
                z.read(part).decode("utf8"), read_rels(z, part)
            )

        media = sorted(n for n in names if n.startswith("ppt/media/"))

    return {
        "template": os.path.abspath(path),
        "parser": _PARSER,
        "canvas": {"w_in": w_in, "h_in": h_in, "aspect": aspect, "ratio": ratio},
        "layouts": {"count": len(layouts), "items": layouts},
        "master_background": master_background,
        "media": media,
        "slides_read": wanted,
        "objects": objects,
    }


def extract_media(path: str, out_dir: str) -> list[str]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Copy ppt/media/* out of the package so the generator can reuse the
        background and the logo directly. The bytes are copied, never re-encoded:
        a re-encoded brand asset is a visibly different brand asset.

    Inputs:
        path (str): the template .pptx
        out_dir (str): destination directory, created if absent

    Outputs:
        written (list): the paths written
    --------------------------------------------------------------------------
    """
    os.makedirs(out_dir, exist_ok=True)
    written = []
    with zipfile.ZipFile(path) as z:
        for name in z.namelist():
            if not name.startswith("ppt/media/"):
                continue
            dst = os.path.join(out_dir, os.path.basename(name))
            with z.open(name) as src, open(dst, "wb") as fh:
                fh.write(src.read())
            written.append(dst)
    return written


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Emit a template's brand contract as JSON.")
    ap.add_argument("template")
    ap.add_argument("--out", help="write the contract here instead of stdout")
    ap.add_argument("--extract-media", help="copy ppt/media/* into this directory")
    ap.add_argument("--slides", help="1-based slide numbers to describe, e.g. 1,2,3")
    ap.add_argument("--convert", action="store_true",
                    help="a legacy .ppt: save it as .pptx through PowerPoint COM first")
    args = ap.parse_args(argv)

    slides = None
    if args.slides:
        slides = [int(s) for s in args.slides.split(",") if s.strip()]

    template = args.template
    if is_legacy_ppt(template):
        if not args.convert:
            print(
                f"{TAG} {template} is a legacy binary PowerPoint file (OLE compound "
                "document), not OOXML. Nothing in this toolchain reads that format. "
                "Re-run with --convert to save a .pptx beside it through PowerPoint COM, "
                "or open it once in PowerPoint and Save As .pptx.",
                file=sys.stderr,
            )
            return 2
        try:
            template = convert_legacy(template)
        except Exception as exc:
            print(f"{TAG} conversion failed: {exc}", file=sys.stderr)
            return 2

    try:
        contract = read_contract(template, slides)
    except (OSError, KeyError, zipfile.BadZipFile) as exc:
        print(f"{TAG} cannot read {args.template}: {exc}", file=sys.stderr)
        return 2

    if args.extract_media:
        contract["extracted_media"] = extract_media(template, args.extract_media)
        print(f"{TAG} extracted {len(contract['extracted_media'])} media file(s) "
              f"to {args.extract_media}", file=sys.stderr)

    text = json.dumps(contract, indent=2)
    if args.out:
        with open(args.out, "w", encoding="utf8") as fh:
            fh.write(text + "\n")
        print(f"{TAG} wrote {args.out} ({contract['canvas']['aspect']}, "
              f"{contract['layouts']['count']} layout(s))")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
