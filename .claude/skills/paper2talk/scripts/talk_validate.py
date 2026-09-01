"""
talk_validate - gate a built deck before anybody looks at it.

Three jobs, in the order they catch things:

    package     delegate to the document-skills pptx validator when it is
                installed, else run the checks the skill cannot ship without
    legibility  no run below the audience's font floor, which is what replaces
                the reference skills' bullet cap
    hierarchy   no text-only content slide, because cards and chips are prose in
                boxes and a deck of them reads as designed while arguing nothing

The plugin validator lives at a cache path carrying a hash that changes whenever
the plugin updates, so it is located rather than copied or hardcoded:

    $DOCUMENT_SKILLS_PPTX, else the newest match of
    ~/.claude/plugins/cache/anthropic-agent-skills/document-skills/*/skills/pptx/
    scripts/office/validate.py

Always pass --original for a template-derived deck. The lab gabarit contains parts
the XSD already rejects, so a bare run reports failures nobody caused and buries the
regression that matters.

The other two targets are validated where their errors actually surface: a Beamer
deck by its LaTeX log (hand off to /latex), and the web deck by the property that
defines it - one self-contained file, so any external http(s) reference in src, href
or url() is a failure.

Usage
-----
    python talk_validate.py deck.pptx --original gabarit.pptx --audience field
    python talk_validate.py deck.pptx --model talk_model.json
    python talk_validate.py --web deck.html
    python talk_validate.py --beamer main.tex

Exit codes: 0 clean, 1 a failure, 2 a usage or file error. Warnings (text-only
slides, frames needing a visual check) do not fail the run: they are the
professor's call, made with the number in front of him.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import subprocess
import sys
import zipfile

TAG = "[VALIDATE]"

PLUGIN_GLOB = os.path.join(
    os.path.expanduser("~"), ".claude", "plugins", "cache", "anthropic-agent-skills",
    "document-skills", "*", "skills", "pptx", "scripts", "office", "validate.py",
)

# Font floors in OOXML hundredths of a point, per audience. Captions and
# references may go to 1400 in the two academic columns.
FONT_FLOOR = {"field": 1600, "academic": 1600, "public": 2000}
CAPTION_FLOOR = {"field": 1400, "academic": 1400, "public": 1800}
CAPTION_HINTS = ("caption", "reference", "credit", "source", "footnote")

_RE_SLIDE = re.compile(r"^ppt/slides/slide(\d+)\.xml$")
_RE_EMBED = re.compile(r'r:(?:embed|link|id)="([^"]+)"')
_RE_RELID = re.compile(r'Id="([^"]+)"')
_RE_SZ = re.compile(r'\bsz="(\d+)"')
_RE_RPR = re.compile(r"<a:(?:def)?rPr\b[^>]*>")
_RE_SLDNUM = re.compile(r'<p:ph\b[^>]*type="sldNum"')
_RE_SLDID = re.compile(r'<p:sldId\b[^>]*r:id="([^"]+)"')
_RE_PIC = re.compile(r"<p:pic\b")
_RE_FRAME = re.compile(r"<p:graphicFrame\b")
_RE_SUBSUP = re.compile(r'<a:rPr\b[^>]*baseline="-?\d+"')
_RE_SHAPE_NAME = re.compile(r'<p:cNvPr\b[^>]*name="([^"]*)"')
_RE_OFF = re.compile(r'<a:off\b[^>]*x="(-?\d+)"[^>]*y="(-?\d+)"')
_RE_EXT = re.compile(r'<a:ext\b[^>]*cx="(\d+)"[^>]*cy="(\d+)"')
_RE_EXTERNAL = re.compile(r'(?:src|href)\s*=\s*["\']https?://|url\(\s*["\']?https?://')


def find_plugin_validator(env: dict | None = None, pattern: str = PLUGIN_GLOB) -> str | None:
    """
    --------------------------------------------------------------------------
    Purpose:
        Locate the document-skills pptx validator without hardcoding its cache
        hash, which changes on every plugin update.

    Inputs:
        env (dict): environment to read DOCUMENT_SKILLS_PPTX from; default os.environ
        pattern (str): glob for the plugin cache

    Outputs:
        path (str): the validator, newest match when several are cached, or None
    --------------------------------------------------------------------------
    """
    env = os.environ if env is None else env
    explicit = env.get("DOCUMENT_SKILLS_PPTX")
    if explicit and os.path.isfile(explicit):
        return explicit
    matches = [p for p in glob.glob(pattern) if os.path.isfile(p)]
    if not matches:
        return None
    return max(matches, key=os.path.getmtime)


def check_package(deck: str) -> list[str]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Run the structural checks the skill cannot do without when the plugin
        validator is unavailable: every relationship id used in a part resolves,
        every part has a content-type override, the slide list matches the slide
        parts, and no chart declares a secondary value axis without declaring the
        axes themselves.

        That last one is the failure that makes PowerPoint call a file corrupt
        while python-pptx, LibreOffice and the XSD all accept it.

    Inputs:
        deck (str): path to the .pptx

    Outputs:
        problems (list): one line per failure, empty when clean
    --------------------------------------------------------------------------
    """
    problems: list[str] = []
    with zipfile.ZipFile(deck) as z:
        names = set(z.namelist())
        content_types = z.read("[Content_Types].xml").decode("utf8") if \
            "[Content_Types].xml" in names else ""

        for part in sorted(n for n in names if n.endswith(".xml") and n.startswith("ppt/")):
            xml = z.read(part).decode("utf8", "replace")
            folder, base = os.path.split(part)
            rels_path = f"{folder}/_rels/{base}.rels"
            declared = set()
            if rels_path in names:
                declared = set(_RE_RELID.findall(z.read(rels_path).decode("utf8")))
            for rid in set(_RE_EMBED.findall(xml)):
                if rid not in declared:
                    problems.append(f"{TAG} {part} uses {rid} but no relationship declares it")

        for part in sorted(names):
            if part.startswith("ppt/") and part.endswith(".xml"):
                override = f'PartName="/{part}"'
                if content_types and override not in content_types:
                    problems.append(f"{TAG} {part} has no content-type override")

        if "ppt/presentation.xml" in names:
            pres = z.read("ppt/presentation.xml").decode("utf8")
            rels = z.read("ppt/_rels/presentation.xml.rels").decode("utf8") \
                if "ppt/_rels/presentation.xml.rels" in names else ""
            listed = _RE_SLDID.findall(pres)
            declared = set(_RE_RELID.findall(rels))
            missing = [r for r in listed if r not in declared]
            if missing:
                problems.append(
                    f"{TAG} sldIdLst references {', '.join(missing)} with no relationship"
                )
            n_parts = sum(1 for n in names if _RE_SLIDE.match(n))
            if listed and len(listed) != n_parts:
                problems.append(
                    f"{TAG} sldIdLst lists {len(listed)} slide(s) but the package holds "
                    f"{n_parts}"
                )

        for part in sorted(n for n in names if n.startswith("ppt/charts/") and
                           n.endswith(".xml")):
            xml = z.read(part).decode("utf8", "replace")
            if "secondaryValAxis" in xml and ("<c:valAx>" not in xml
                                              or "<c:catAx>" not in xml):
                problems.append(
                    f"{TAG} {part} declares a secondary value axis without both "
                    "<c:valAx> and <c:catAx>; PowerPoint rejects the file while the "
                    "XSD accepts it"
                )
    return problems


def check_legibility(deck: str, audience: str = "field") -> tuple[list[str], list[str]]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Enforce the audience's font floor, which is the mechanical gate that
        replaces the reference skills' 3-to-5 bullet cap. A slide may carry seven
        equations; what it may not do is put them below the floor.

    Inputs:
        deck (str): path to the .pptx
        audience (str): field, academic, or public

    Outputs:
        (problems, warnings): runs below the floor fail; frames whose fit cannot
            be measured without font metrics are flagged for visual inspection
    --------------------------------------------------------------------------
    """
    floor = FONT_FLOOR.get(audience, FONT_FLOOR["field"])
    cap_floor = CAPTION_FLOOR.get(audience, CAPTION_FLOOR["field"])
    problems: list[str] = []
    warnings: list[str] = []
    with zipfile.ZipFile(deck) as z:
        for name in sorted(n for n in z.namelist() if _RE_SLIDE.match(n)):
            n = int(_RE_SLIDE.match(name).group(1))
            xml = z.read(name).decode("utf8", "replace")
            for shape in xml.split("<p:sp>")[1:]:
                match = _RE_SHAPE_NAME.search(shape)
                shape_name = match.group(1) if match else ""
                # The slide-number placeholder is master chrome, not body text.
                if _RE_SLDNUM.search(shape):
                    continue
                named_caption = any(h in shape_name.lower() for h in CAPTION_HINTS)
                for rpr in _RE_RPR.findall(shape):
                    sz_match = _RE_SZ.search(rpr)
                    if not sz_match:
                        continue
                    sz = int(sz_match.group(1))
                    # A generator names its shapes automatically, so the caption
                    # exemption cannot rely on the name alone: the design system
                    # sets captions and references in italic, and that survives
                    # into the XML.
                    is_caption = named_caption or 'i="1"' in rpr
                    limit = cap_floor if is_caption else floor
                    if sz < limit:
                        problems.append(
                            f"{TAG} slide {n} shape '{shape_name or 'unnamed'}' runs at "
                            f"{sz / 100:g} pt, below the {limit / 100:g} pt floor for "
                            f"audience {audience}"
                        )
                        break
                if "normAutofit" in shape and "fontScale" in shape:
                    warnings.append(
                        f"{TAG} slide {n} shape '{shape_name or 'unnamed'}' relies on "
                        "autofit shrinking; inspect it visually, the rendered size may be "
                        "below the floor"
                    )
    return problems, warnings


def check_text_only(deck: str, model: dict | None = None) -> list[str]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Name the content slides that carry no exhibit. A picture is worth a
        thousand words, so a content slide with neither figure, table, chart,
        quantity-bearing diagram nor equation is a defect - and rounded rectangles
        holding bullets do not count, which is exactly the failure mode worth
        catching.

    Inputs:
        deck (str): path to the .pptx
        model (dict): a parsed talk_model.json, used to skip chrome slides

    Outputs:
        warnings (list): one line per offending slide, plus the count
    --------------------------------------------------------------------------
    """
    chrome: set[int] = set()
    if model:
        for slide in model.get("slides", []):
            if str(slide.get("kind", "content")).lower() != "content":
                chrome.add(slide.get("n"))

    offenders: list[int] = []
    total = 0
    with zipfile.ZipFile(deck) as z:
        for name in sorted(n for n in z.namelist() if _RE_SLIDE.match(n)):
            n = int(_RE_SLIDE.match(name).group(1))
            if n in chrome:
                continue
            total += 1
            xml = z.read(name).decode("utf8", "replace")
            has_exhibit = bool(
                _RE_PIC.search(xml) or _RE_FRAME.search(xml) or _RE_SUBSUP.search(xml)
            )
            if not has_exhibit:
                offenders.append(n)

    warnings = [
        f"{TAG} slide {n} is a text-only content slide (no figure, table, chart, matrix, "
        "zone band or equation)" for n in offenders
    ]
    if offenders:
        warnings.append(
            f"{TAG} {len(offenders)} of {total} content slide(s) carry no exhibit; "
            "convert or accept each deliberately"
        )
    return warnings


def _shape_boxes(xml: str) -> list[tuple[str, int, int, int, int]]:
    """Every positioned shape of a slide as (name, x, y, w, h) in EMU."""
    boxes = []
    for chunk in re.split(r"(?=<p:(?:sp|pic|graphicFrame)\b)", xml)[1:]:
        name_match = _RE_SHAPE_NAME.search(chunk)
        off = _RE_OFF.search(chunk)
        ext = _RE_EXT.search(chunk)
        if not off or not ext:
            continue
        boxes.append((
            name_match.group(1) if name_match else "unnamed",
            int(off.group(1)), int(off.group(2)),
            int(ext.group(1)), int(ext.group(2)),
        ))
    return boxes


def _overlap_area(a, b) -> int:
    """Intersection area of two (name, x, y, w, h) boxes, in EMU squared."""
    ax, ay, aw, ah = a[1], a[2], a[3], a[4]
    bx, by, bw, bh = b[1], b[2], b[3], b[4]
    dx = min(ax + aw, bx + bw) - max(ax, bx)
    dy = min(ay + ah, by + bh) - max(ay, by)
    return dx * dy if dx > 0 and dy > 0 else 0


def check_overlaps(deck: str, tolerance: float = 0.15) -> list[str]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Name the shapes that sit on top of each other. A caption under a logo, a
        two-line heading colliding with the row beneath it and a table running
        into the wordmark were the three most frequent defects of the origin
        session, and all three are a bounding-box overlap.

        Small overlaps are normal - a text frame's box is wider than its glyphs -
        so a pair is only reported when the intersection covers more than
        `tolerance` of the smaller shape.

    Inputs:
        deck (str): path to the .pptx
        tolerance (float): fraction of the smaller shape that may overlap

    Outputs:
        warnings (list): one line per offending pair, with the covered fraction
    --------------------------------------------------------------------------
    """
    warnings: list[str] = []
    with zipfile.ZipFile(deck) as z:
        for name in sorted(n for n in z.namelist() if _RE_SLIDE.match(n)):
            n = int(_RE_SLIDE.match(name).group(1))
            boxes = _shape_boxes(z.read(name).decode("utf8", "replace"))
            for i, first in enumerate(boxes):
                for second in boxes[i + 1:]:
                    area = _overlap_area(first, second)
                    if not area:
                        continue
                    smaller = min(first[3] * first[4], second[3] * second[4]) or 1
                    ratio = area / smaller
                    if ratio > tolerance:
                        warnings.append(
                            f"{TAG} slide {n}: '{first[0]}' and '{second[0]}' overlap over "
                            f"{ratio:.0%} of the smaller shape"
                        )
    return warnings


def _luminance(hex_colour: str) -> float:
    """Relative luminance of a six-digit hex colour, 0 (black) to 1 (white)."""
    value = str(hex_colour).lstrip("#")
    r, g, b = (int(value[i:i + 2], 16) / 255 for i in (0, 2, 4))

    def channel(c: float) -> float:
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def check_palette(palette: dict, min_delta: float = 0.10) -> list[str]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Check that the semantic triad is legible to a colour-blind viewer and on
        a washed-out projector. Roughly one man in twelve cannot separate the red
        from the green, so a triad that differs only in hue carries no meaning
        for them - the classes have to differ in lightness as well.

    Inputs:
        palette (dict): the model palette; s1, s2, s3 are the semantic triad
        min_delta (float): minimum relative-luminance separation between any two

    Outputs:
        warnings (list): one line per pair that is too close in luminance
    --------------------------------------------------------------------------
    """
    keys = [k for k in ("s1", "s2", "s3") if palette.get(k)]
    warnings = []
    for i, first in enumerate(keys):
        for second in keys[i + 1:]:
            try:
                delta = abs(_luminance(palette[first]) - _luminance(palette[second]))
            except (ValueError, IndexError):
                continue
            if delta < min_delta:
                warnings.append(
                    f"{TAG} palette {first} (#{palette[first]}) and {second} "
                    f"(#{palette[second]}) differ by {delta:.2f} in luminance; a "
                    "colour-blind viewer or a washed-out projector cannot separate them"
                )
    return warnings


def check_size(deck: str, max_mb: float = 50.0) -> list[str]:
    """A deck past this size is slow to open and awkward to email or upload."""
    mb = os.path.getsize(deck) / (1024 * 1024)
    if mb > max_mb:
        return [f"{TAG} the deck is {mb:.0f} MB (over {max_mb:.0f} MB); re-export the "
                "heaviest figures or drop a backup slide"]
    return []


def check_web(path: str) -> list[str]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Assert the web deck is what it claims to be: one self-contained file. A
        CDN font or a remote image is a deck that fails on a conference laptop
        with no network, which is the situation it will meet.

    Inputs:
        path (str): the .html file

    Outputs:
        problems (list): one line per external reference found
    --------------------------------------------------------------------------
    """
    with open(path, encoding="utf8", errors="replace") as fh:
        html = fh.read()
    problems = []
    for line_no, line in enumerate(html.splitlines(), 1):
        if _RE_EXTERNAL.search(line):
            problems.append(
                f"{TAG} {path}:{line_no} references an external URL; the web target must "
                "inline every asset (data: URIs), or it breaks offline"
            )
    return problems


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Validate a built deck before inspection.")
    ap.add_argument("deck", nargs="?", help="the built .pptx")
    ap.add_argument("--original", help="the template the deck derives from")
    ap.add_argument("--audience", choices=sorted(FONT_FLOOR), default="field")
    ap.add_argument("--model", help="talk_model.json, for the slide tiers")
    ap.add_argument("--web", help="validate a self-contained .html deck instead")
    ap.add_argument("--beamer", help="a Beamer main.tex: hand off to /latex")
    ap.add_argument("--no-plugin", action="store_true",
                    help="skip the plugin validator and run the built-in checks")
    args = ap.parse_args(argv)

    if args.beamer:
        print(
            f"{TAG} Beamer decks are gated by their LaTeX log, not by this script. Compile "
            f"and run /latex on {args.beamer}; the equivalent failures (missing figure, "
            "overfull box, undefined reference) surface there."
        )
        return 0

    if args.web:
        try:
            problems = check_web(args.web)
        except OSError as exc:
            print(f"{TAG} cannot read {args.web}: {exc}", file=sys.stderr)
            return 2
        for line in problems:
            print(line, file=sys.stderr)
        print(f"{TAG} web target {'FAIL' if problems else 'clean'}")
        return 1 if problems else 0

    if not args.deck:
        print(f"{TAG} give a deck, --web <file.html>, or --beamer <main.tex>", file=sys.stderr)
        return 2

    model = None
    if args.model:
        try:
            with open(args.model, encoding="utf8") as fh:
                model = json.load(fh)
        except (OSError, json.JSONDecodeError) as exc:
            print(f"{TAG} cannot read {args.model}: {exc}", file=sys.stderr)
            return 2

    failed = False
    plugin = None if args.no_plugin else find_plugin_validator()
    if plugin:
        print(f"{TAG} package checks: document-skills validator at {plugin}")
        cmd = [sys.executable, plugin, args.deck]
        if args.original:
            cmd += ["--original", args.original]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        sys.stdout.write(proc.stdout)
        sys.stderr.write(proc.stderr)
        failed = failed or proc.returncode != 0
    else:
        print(f"{TAG} package checks: built in (no document-skills validator found)")
        try:
            problems = check_package(args.deck)
        except (OSError, KeyError, zipfile.BadZipFile) as exc:
            print(f"{TAG} cannot read {args.deck}: {exc}", file=sys.stderr)
            return 2
        for line in problems:
            print(line, file=sys.stderr)
        failed = failed or bool(problems)
        if not args.original:
            print(f"{TAG} no --original given; a gabarit-derived deck reports pre-existing "
                  "template failures as if they were yours")

    leg_problems, leg_warnings = check_legibility(args.deck, args.audience)
    for line in leg_problems:
        print(line, file=sys.stderr)
    for line in leg_warnings:
        print(line)
    failed = failed or bool(leg_problems)

    for line in check_text_only(args.deck, model):
        print(line)
    for line in check_overlaps(args.deck):
        print(line)
    for line in check_size(args.deck):
        print(line)
    if model:
        for line in check_palette(model.get("palette") or {}):
            print(line)

    print(f"{TAG} {'FAIL' if failed else 'clean'} (audience {args.audience})")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
