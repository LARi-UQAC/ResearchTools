"""
docx_inspect.py — Extract every value needed to build a faithful LaTeX preamble
from a Word .docx template.

Usage:
    python docx_inspect.py <file.docx>

Outputs a structured report (stdout) covering:
  - Default font and size, line spacing, paragraph spacing
  - Each <w:sectPr>: orientation, page size, margins, header/footer references
  - Heading1, Heading2, Title styles (font, size, color, alignment)
  - Table border defaults
  - Image catalog (path, dimensions, RGB stats, transparency)
  - Header and footer texts per section

Every value extracted from the .docx XML traces back to a Word feature so the
agent can map it to a LaTeX construct without inventing values.

Word units used in this script:
  - 1 twip = 1/1440 in (margins, line lengths)
  - 1 EMU = 1/914400 in (image extents)
  - 1 half-pt = 0.5 pt (font size, sz)
  - w:line value 276 = 1.15x line spacing (276 / 240)
"""

from __future__ import annotations

import io
import re
import sys
import zipfile
from pathlib import Path

W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def twip_to_cm(twips: int) -> float:
    return twips / 1440 * 2.54


def twip_to_in(twips: int) -> float:
    return twips / 1440


def emu_to_cm(emu: int) -> float:
    return emu / 914400 * 2.54


def hp_to_pt(half_points: int) -> float:
    return half_points / 2


def find_style_block(content: str, style_id: str) -> str | None:
    pattern = r'<w:style[^>]*w:styleId="' + re.escape(style_id) + r'"[^>]*>.*?</w:style>'
    match = re.search(pattern, content, re.DOTALL)
    return match.group(0) if match else None


def extract_attr(xml_block: str, tag: str, attr: str) -> str | None:
    """Return the value of the attribute attr on the first <w:tag> element."""
    pattern = r"<w:" + tag + r"[^/>]*\bw:" + attr + r'="([^"]*)"'
    match = re.search(pattern, xml_block)
    return match.group(1) if match else None


def report_section(title: str) -> None:
    print()
    print("=" * 78)
    print(f" {title}")
    print("=" * 78)


def inspect_defaults(styles_xml: str) -> None:
    report_section("DEFAULTS (<w:docDefaults>)")
    match = re.search(r"<w:docDefaults>.*?</w:docDefaults>", styles_xml, re.DOTALL)
    if not match:
        print("  (no docDefaults block — uncommon)")
        return
    block = match.group(0)
    font = extract_attr(block, "rFonts", "ascii") or "(not set, Calibri assumed)"
    sz = extract_attr(block, "sz", "val")
    line = extract_attr(block, "spacing", "line")
    before = extract_attr(block, "spacing", "before")
    after = extract_attr(block, "spacing", "after")

    print(f"  Default font     : {font}")
    if sz:
        print(f"  Default size     : {sz} half-pts = {hp_to_pt(int(sz))} pt")
    if line:
        ratio = int(line) / 240
        print(f"  Line spacing     : w:line={line} -> {ratio:.3f}x baseline")
    if before:
        print(f"  Paragraph before : {before} twips = {twip_to_cm(int(before)):.2f} cm")
    if after:
        print(f"  Paragraph after  : {after} twips = {twip_to_cm(int(after)):.2f} cm")


def inspect_headings(styles_xml: str) -> None:
    report_section("HEADING STYLES")
    for style_id, label in [
        ("Heading1", "Heading 1  -> \\section"),
        ("Heading2", "Heading 2  -> \\subsection"),
        ("Heading3", "Heading 3  -> \\subsubsection"),
        ("Title", "Title       -> banner / cover"),
    ]:
        block = find_style_block(styles_xml, style_id)
        print(f"\n  [{label}]")
        if not block:
            print("    (not defined)")
            continue
        font = extract_attr(block, "rFonts", "ascii") or extract_attr(block, "rFonts", "asciiTheme") or "(theme default)"
        sz = extract_attr(block, "sz", "val")
        jc = extract_attr(block, "jc", "val")
        color = extract_attr(block, "color", "val")
        bold = "<w:b/>" in block or '<w:b ' in block
        ind_left = extract_attr(block, "ind", "left")
        ind_hanging = extract_attr(block, "ind", "hanging")

        print(f"    font     : {font}")
        if sz:
            print(f"    size     : {sz} half-pts = {hp_to_pt(int(sz))} pt")
        if jc:
            print(f"    align    : {jc}")
        if color:
            print(f"    color    : #{color}")
        print(f"    bold     : {bold}")
        if ind_left:
            print(f"    indent L : {ind_left} twips = {twip_to_cm(int(ind_left)):.2f} cm")
        if ind_hanging:
            print(f"    hanging  : {ind_hanging} twips = {twip_to_cm(int(ind_hanging)):.2f} cm")


def inspect_sections(document_xml: str) -> None:
    report_section("SECTIONS (<w:sectPr>)")
    matches = list(re.finditer(r"<w:sectPr[^>]*>.*?</w:sectPr>", document_xml, re.DOTALL))
    if not matches:
        print("  (no sectPr — uncommon)")
        return
    for idx, m in enumerate(matches):
        block = m.group(0)
        pg_w = extract_attr(block, "pgSz", "w")
        pg_h = extract_attr(block, "pgSz", "h")
        orient = extract_attr(block, "pgSz", "orient") or "portrait"
        mar_top = extract_attr(block, "pgMar", "top")
        mar_right = extract_attr(block, "pgMar", "right")
        mar_bottom = extract_attr(block, "pgMar", "bottom")
        mar_left = extract_attr(block, "pgMar", "left")
        mar_header = extract_attr(block, "pgMar", "header")
        mar_footer = extract_attr(block, "pgMar", "footer")
        has_titlepg = "<w:titlePg/>" in block

        header_refs = re.findall(r'<w:headerReference[^>]*w:type="([^"]+)"[^>]*r:id="([^"]+)"', block)
        footer_refs = re.findall(r'<w:footerReference[^>]*w:type="([^"]+)"[^>]*r:id="([^"]+)"', block)

        print(f"\n  Section {idx}: orientation = {orient}")
        if pg_w and pg_h:
            print(f"    page         : {twip_to_in(int(pg_w)):.2f} x {twip_to_in(int(pg_h)):.2f} in"
                  f"  ({pg_w} x {pg_h} twips)")
        if mar_top:
            print(f"    margin top   : {twip_to_in(int(mar_top)):.3f} in = {twip_to_cm(int(mar_top)):.2f} cm  ({mar_top} twips)")
        if mar_right:
            print(f"    margin right : {twip_to_in(int(mar_right)):.3f} in = {twip_to_cm(int(mar_right)):.2f} cm")
        if mar_bottom:
            print(f"    margin bot   : {twip_to_in(int(mar_bottom)):.3f} in = {twip_to_cm(int(mar_bottom)):.2f} cm")
        if mar_left:
            print(f"    margin left  : {twip_to_in(int(mar_left)):.3f} in = {twip_to_cm(int(mar_left)):.2f} cm")
        if mar_header:
            print(f"    header dist  : {twip_to_in(int(mar_header)):.3f} in = {twip_to_cm(int(mar_header)):.2f} cm")
        if mar_footer:
            print(f"    footer dist  : {twip_to_in(int(mar_footer)):.3f} in = {twip_to_cm(int(mar_footer)):.2f} cm")
        print(f"    titlePg      : {has_titlepg}  (true = first page uses 'first' header/footer)")
        for kind, rid in header_refs:
            print(f"    headerRef    : type={kind}, r:id={rid}")
        for kind, rid in footer_refs:
            print(f"    footerRef    : type={kind}, r:id={rid}")


def inspect_table_borders(document_xml: str) -> None:
    report_section("TABLE BORDERS (<w:tblBorders> samples)")
    blocks = re.findall(r"<w:tblBorders>.*?</w:tblBorders>", document_xml, re.DOTALL)
    if not blocks:
        print("  (no explicit tblBorders — tables use Word defaults, usually no borders)")
        return
    # Only summarize the first 3 unique borders blocks.
    seen = set()
    count = 0
    for block in blocks:
        key = block
        if key in seen:
            continue
        seen.add(key)
        count += 1
        if count > 3:
            break
        print(f"\n  Table border #{count}:")
        for side in ["top", "left", "bottom", "right", "insideH", "insideV"]:
            attrs = re.search(r"<w:" + side + r"[^/>]*/>", block)
            if attrs:
                val = re.search(r'\bw:val="([^"]*)"', attrs.group(0))
                sz = re.search(r'\bw:sz="([^"]*)"', attrs.group(0))
                color = re.search(r'\bw:color="([^"]*)"', attrs.group(0))
                print(f"    {side:<8}: val={val.group(1) if val else '?'} sz={sz.group(1) if sz else '?'} color=#{color.group(1) if color else '?'}")
    print()
    print("  RULE: if insideH and insideV are non-'nil', the LaTeX longtable")
    print("        needs '|' between every column AND a \\hline after every row.")


def inspect_images(zip_archive: zipfile.ZipFile) -> None:
    report_section("IMAGES (word/media/)")
    try:
        from PIL import Image
        import numpy as np
        pil_available = True
    except ImportError:
        pil_available = False
        print("  (Pillow/numpy not installed — only listing names)")

    media = [n for n in zip_archive.namelist() if n.startswith("word/media/")]
    if not media:
        print("  (no embedded images)")
        return

    for name in sorted(media):
        with zip_archive.open(name) as f:
            data = f.read()
        size_kb = len(data) / 1024
        print(f"\n  {name}  ({size_kb:.1f} kB)")
        if not pil_available:
            continue
        if not name.lower().endswith(("png", "jpg", "jpeg", "gif")):
            continue
        try:
            img = Image.open(io.BytesIO(data))
        except Exception as exc:
            print(f"    (could not open: {exc})")
            continue
        print(f"    dims   : {img.size[0]} x {img.size[1]} px, mode={img.mode}")
        arr = np.array(img)
        if arr.ndim == 3 and arr.shape[-1] == 4:
            alpha = arr[:, :, 3]
            visible = alpha > 30
            if visible.any():
                rgb = arr[visible][:, :3]
                mean = rgb.mean(axis=0)
                if (mean > 240).all():
                    color_note = "  (white logo — meant for colored banner)"
                elif (mean[2] > mean[0] and mean[2] > 100):
                    color_note = "  (blue-dominant — Mitacs wordmark variant)"
                else:
                    color_note = ""
                print(f"    mean RGB of visible pixels: ({mean[0]:.0f},{mean[1]:.0f},{mean[2]:.0f}){color_note}")


def inspect_headers_footers(zip_archive: zipfile.ZipFile) -> None:
    report_section("HEADERS / FOOTERS")
    members = [n for n in zip_archive.namelist() if re.match(r"word/(header|footer)\d+\.xml$", n)]
    if not members:
        print("  (no header/footer files)")
        return
    for name in sorted(members):
        with zip_archive.open(name) as f:
            xml = f.read().decode("utf-8", errors="replace")
        # Extract plain text inside <w:t> elements
        texts = re.findall(r"<w:t[^>]*>([^<]*)</w:t>", xml)
        joined = " | ".join(t for t in texts if t.strip())
        has_image = "<w:drawing>" in xml
        align = re.search(r'<w:jc\s+w:val="([^"]+)"', xml)
        print(f"\n  {name}")
        if has_image:
            print(f"    contains image : YES")
        if align:
            print(f"    paragraph jc   : {align.group(1)}")
        if joined:
            preview = joined if len(joined) < 200 else joined[:200] + "..."
            print(f"    text           : {preview}")


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: python docx_inspect.py <file.docx>", file=sys.stderr)
        return 2
    path = Path(sys.argv[1])
    if not path.exists():
        print(f"File not found: {path}", file=sys.stderr)
        return 2

    print(f"Inspecting: {path}")
    with zipfile.ZipFile(path) as z:
        with z.open("word/document.xml") as f:
            document_xml = f.read().decode("utf-8", errors="replace")
        with z.open("word/styles.xml") as f:
            styles_xml = f.read().decode("utf-8", errors="replace")

        inspect_defaults(styles_xml)
        inspect_headings(styles_xml)
        inspect_sections(document_xml)
        inspect_table_borders(document_xml)
        inspect_images(z)
        inspect_headers_footers(z)

    report_section("END OF REPORT")
    print("Use these values when building the LaTeX preamble.")
    print("See .claude/skills/word2latex/references/preamble_patches.md for copy-pasteable blocks.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
