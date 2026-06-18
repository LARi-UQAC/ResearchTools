"""
drawio2tikz.py - Convert one draw.io diagram (sheet) to a TikZ fragment.

Faithful, coordinate-exact conversion of a single `<diagram>` from a `.drawio`
file into TikZ `\\node`/`\\draw` commands using ABSOLUTE coordinates. Built to
avoid the conversion mistakes catalogued in
`../references/conversion-rules.md`.

Hard-won rules baked in (see reference for the why):
  * Skip layer/root cells (no geometry, no text, not an edge).
  * Resolve nested group offsets by summing ancestor vertex x/y.
  * Handle `<object><mxCell></object>` wrapping (id/label live on `<object>`).
  * Edge endpoints come from the SHAPE perimeter when a `source`/`target` id is
    set (using exitX/exitY / entryX/entryY), NOT the stale `mxPoint` fallback.
  * `<Array>` waypoints are inserted into the polyline (a waypoint can extend a
    line beyond its stored target -> dropping it leaves a visible gap).
  * Y axis is flipped (draw.io y-down -> TikZ y-up): y_tikz = -y.
  * rotation=-360 == 0; TikZ rotate = -drawio_rotation (because of the Y flip).
  * curlyBracket -> brace decoration; orientation from rotation, bulge heuristic.
  * fillColor/strokeColor/fontColor (#hex) -> inline TikZ rgb; `none` honoured.

Usage:
    python drawio2tikz.py FILE.drawio --diagram "Scenario" [options]
    python drawio2tikz.py FILE.drawio --list

Options:
    --diagram NAME     Substring (case-insensitive) of the diagram name.
    --list             List diagram names and exit.
    --scale F          cm per draw.io px (default 0.0264).
    --translate JSON   JSON dict {french: english} applied to label text.
    --brace-amplitude P  Brace amplitude in pt (default 10).
    --brace-mirror M   auto|on|off bulge direction (default auto).
    --wrap             Emit a full figure+resizebox+tikzpicture skeleton.
    --out FILE         Write to FILE (default: stdout).

The preamble must load: \\usetikzlibrary{decorations.pathreplacing} (braces)
and arrows.meta (arrow tips). Wrap the fragment in \\resizebox{\\linewidth}{!}{...}
so it always fits regardless of --scale.
"""
import argparse
import json
import math
import re
import sys

try:                                  # prefer hardened parser (XXE safe)
    import defusedxml.ElementTree as ET
except ImportError:                   # stdlib fallback; input is a trusted local file
    import xml.etree.ElementTree as ET


# --------------------------------------------------------------------------
# text / colour helpers
# --------------------------------------------------------------------------
def unescape(s):
    if s is None:
        return ""
    for a, b in (("&lt;", "<"), ("&gt;", ">"), ("&quot;", '"'),
                 ("&#39;", "'"), ("&nbsp;", " "), ("&amp;", "&")):
        s = s.replace(a, b)
    return s


def plain_text(value):
    """Strip HTML tags and entities from a draw.io cell value."""
    v = unescape(value)
    v = re.sub(r"<[^>]+>", "", v)
    v = v.replace("\xa0", " ").strip()
    return re.sub(r"\s+", " ", v)


def tex_escape(s):
    return (s.replace("\\", r"\textbackslash{}").replace("&", r"\&")
             .replace("%", r"\%").replace("#", r"\#").replace("_", r"\_")
             .replace("{", r"\{").replace("}", r"\}").replace("$", r"\$")
             .replace("^", r"\^{}").replace("~", r"\textasciitilde{}"))


def style_get(style, key):
    if not style:
        return None
    m = re.search(r"(?:^|;)" + re.escape(key) + r"=([^;]+)", style)
    return m.group(1) if m else None


def tcolor(hexval):
    h = hexval.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return "{rgb,255:red,%d;green,%d;blue,%d}" % (r, g, b)


# --------------------------------------------------------------------------
# parsing
# --------------------------------------------------------------------------
def load_diagrams(path):
    root = ET.parse(path).getroot()
    return list(root.iter("diagram"))


def collect_cells(diagram):
    """Return {id: cell-dict} for one <diagram>. Handles <object> wrapping."""
    model = diagram.find("mxGraphModel")
    rootc = model.find("root")
    cells = {}
    for el in rootc:
        if el.tag == "object":
            mc = el.find("mxCell")
            cid, value = el.get("id"), el.get("label", "")
        elif el.tag == "mxCell":
            mc = el
            cid, value = el.get("id"), el.get("value", "")
        else:
            continue
        if mc is None:
            continue
        geo = mc.find("mxGeometry")
        rec = {
            "id": cid, "value": value, "style": mc.get("style", "") or "",
            "parent": mc.get("parent"), "is_edge": mc.get("edge") == "1",
            "src": mc.get("source"), "tgt": mc.get("target"),
            "x": 0.0, "y": 0.0, "w": 0.0, "h": 0.0,
            "sp": None, "tp": None, "waypoints": [],
        }
        if geo is not None:
            rec["x"] = float(geo.get("x", 0) or 0)
            rec["y"] = float(geo.get("y", 0) or 0)
            rec["w"] = float(geo.get("width", 0) or 0)
            rec["h"] = float(geo.get("height", 0) or 0)
            for pt in geo.findall("mxPoint"):
                role, xy = pt.get("as"), (float(pt.get("x", 0) or 0),
                                          float(pt.get("y", 0) or 0))
                if role == "sourcePoint":
                    rec["sp"] = xy
                elif role == "targetPoint":
                    rec["tp"] = xy
            arr = geo.find("Array")
            if arr is not None:
                rec["waypoints"] = [(float(p.get("x", 0) or 0),
                                     float(p.get("y", 0) or 0))
                                    for p in arr.findall("mxPoint")]
        cells[cid] = rec
    return cells


def abs_offset(cells, cid):
    """Sum x/y of every ancestor vertex (groups translate their children)."""
    ox = oy = 0.0
    p = cells[cid]["parent"]
    seen = set()
    while p in cells and p not in seen:
        seen.add(p)
        c = cells[p]
        if not c["is_edge"]:
            ox += c["x"]
            oy += c["y"]
        p = c["parent"]
    return ox, oy


def abs_pos(cells, cid):
    c = cells[cid]
    ox, oy = abs_offset(cells, cid)
    return ox + c["x"], oy + c["y"]


def anchor_point(cells, shape_id, ex, ey, edx, edy):
    """Perimeter point on a shape from exitX/exitY (or entryX/entryY)."""
    x0, y0 = abs_pos(cells, shape_id)
    c = cells[shape_id]
    return x0 + ex * c["w"] + edx, y0 + ey * c["h"] + edy


# --------------------------------------------------------------------------
# emission
# --------------------------------------------------------------------------
class Emitter:
    def __init__(self, cells, scale, translate, brace_amp, brace_mirror):
        self.cells = cells
        self.s = scale
        self.tr = translate or {}
        self.brace_amp = brace_amp
        self.brace_mirror = brace_mirror
        self.pt = scale * 28.4528          # pt per px (proportional fonts)

    def T(self, x, y):
        """draw.io abs px -> TikZ cm, with Y flip."""
        return x * self.s, -y * self.s

    def translate(self, txt):
        return self.tr.get(txt, txt)

    def font(self, value, default_px, is_text):
        m = re.search(r"font-size:\s*(\d+)px", unescape(value or ""))
        fpx = int(m.group(1)) if m else (default_px if is_text else 9)
        fpt = fpx * self.pt
        cmd = "\\fontsize{%.2f}{%.2f}\\selectfont" % (fpt, fpt * 1.2)
        if "<b" in (value or "") or "font-weight:bold" in (value or ""):
            cmd += "\\bfseries"
        return "{%s}" % cmd

    # ---- edges --------------------------------------------------------
    def edge_points(self, cells, c):
        """Ordered absolute polyline points for an edge."""
        ox, oy = abs_offset(cells, c["id"])
        st = c["style"]
        # source
        if c["src"] in cells:
            ex, ey = style_get(st, "exitX"), style_get(st, "exitY")
            if ex is not None and ey is not None:
                sp = anchor_point(cells, c["src"], float(ex), float(ey),
                                  float(style_get(st, "exitDx") or 0),
                                  float(style_get(st, "exitDy") or 0))
            else:                       # connected, no anchor -> shape centre
                x0, y0 = abs_pos(cells, c["src"])
                sc = cells[c["src"]]
                sp = (x0 + sc["w"] / 2.0, y0 + sc["h"] / 2.0)
        elif c["sp"] is not None:
            sp = (ox + c["sp"][0], oy + c["sp"][1])
        else:
            sp = None
        # target
        if c["tgt"] in cells:
            ex, ey = style_get(st, "entryX"), style_get(st, "entryY")
            if ex is not None and ey is not None:
                tp = anchor_point(cells, c["tgt"], float(ex), float(ey),
                                  float(style_get(st, "entryDx") or 0),
                                  float(style_get(st, "entryDy") or 0))
            else:
                x0, y0 = abs_pos(cells, c["tgt"])
                tc = cells[c["tgt"]]
                tp = (x0 + tc["w"] / 2.0, y0 + tc["h"] / 2.0)
        elif c["tp"] is not None:
            tp = (ox + c["tp"][0], oy + c["tp"][1])
        else:
            tp = None
        if sp is None or tp is None:
            return []
        mids = [(ox + wx, oy + wy) for wx, wy in c["waypoints"]]
        return [sp] + mids + [tp]

    def emit_edge(self, c):
        pts = self.edge_points(self.cells, c)
        if len(pts) < 2:
            return None
        st = c["style"]
        opt = []
        if "classic" in (style_get(st, "endArrow") or "none") or \
           "block" in (style_get(st, "endArrow") or ""):
            opt.append("-{Latex[length=2mm]}")
        sw = style_get(st, "strokeWidth")
        if sw and float(sw) >= 3:
            opt.append("line width=%.2fpt" % (float(sw) * self.pt))
        if "dashed=1" in st:
            opt.append("dashed")
        sc = style_get(st, "strokeColor")
        if sc and sc != "none":
            opt.append("draw=%s" % tcolor(sc))
        optstr = ("[" + ",".join(opt) + "]") if opt else ""
        coords = " -- ".join("(%.3f,%.3f)" % self.T(x, y) for x, y in pts)
        return "  \\draw%s %s;" % (optstr, coords)

    # ---- braces -------------------------------------------------------
    def emit_brace(self, c):
        ox, oy = abs_offset(self.cells, c["id"])
        x0, y0 = ox + c["x"], oy + c["y"]
        cx, cy = x0 + c["w"] / 2.0, y0 + c["h"] / 2.0
        rot = float(style_get(c["style"], "rotation") or 0)
        eff = int(round(rot)) % 180
        half = c["h"] / 2.0                 # spine runs along the height
        horizontal = eff == 90
        if horizontal:
            p1, p2 = (cx - half, cy), (cx + half, cy)
        else:
            p1, p2 = (cx, cy - half), (cx, cy + half)
        mirror = ""
        if self.brace_mirror == "on" or (self.brace_mirror == "auto" and horizontal):
            mirror = "mirror,"
        a, b = self.T(*p1), self.T(*p2)
        return ("  \\draw[decorate,decoration={brace,%samplitude=%dpt}] "
                "(%.3f,%.3f) -- (%.3f,%.3f);"
                % (mirror, self.brace_amp, a[0], a[1], b[0], b[1]))

    # ---- vertices -----------------------------------------------------
    def emit_vertex(self, c):
        st = c["style"]
        ox, oy = abs_offset(self.cells, c["id"])
        cx, cy = self.T(ox + c["x"] + c["w"] / 2.0, oy + c["y"] + c["h"] / 2.0)
        w, h = c["w"] * self.s, c["h"] * self.s
        rot = float(style_get(st, "rotation") or 0)
        if abs(rot) % 360 == 0:
            rot = 0.0
        fill = style_get(st, "fillColor")
        stroke = style_get(st, "strokeColor")
        fontc = style_get(st, "fontColor")
        is_text = ("text;" in st or st.startswith("text") or "edgeLabel" in st
                   or (fill == "none" and stroke == "none"))
        txt = self.translate(plain_text(c["value"]))
        opts = ["inner sep=0", "minimum width=%.3fcm" % w,
                "minimum height=%.3fcm" % h,
                "font=%s" % self.font(c["value"], 10, is_text)]
        if rot:
            opts.append("rotate=%.1f" % (-rot))
        if not is_text:
            opts.append("draw=%s" % (tcolor(stroke)
                                     if stroke and stroke != "none" else "black"))
            if "rounded=1" in st:
                opts.append("rounded corners=2pt")
            if fill and fill != "none":
                opts.append("fill=%s" % tcolor(fill))
        if fontc and fontc != "none":
            opts.append("text=%s" % tcolor(fontc))
        body = tex_escape(txt) if txt else ""
        return "  \\node[%s] at (%.3f,%.3f) {%s};" % (",".join(opts), cx, cy, body)

    # ---- driver -------------------------------------------------------
    def run(self):
        lines = []
        for cid, c in self.cells.items():
            st = c["style"]
            if "group" in st and not c["is_edge"]:
                continue
            if (not c["is_edge"] and c["w"] == 0 and c["h"] == 0
                    and not plain_text(c["value"])):
                continue                       # layer / root cell
            if c["is_edge"]:
                line = self.emit_edge(c)
            elif "curlyBracket" in st:
                line = self.emit_brace(c)
            else:
                line = self.emit_vertex(c)
            if line:
                lines.append(line)
        return lines


def main():
    ap = argparse.ArgumentParser(description="draw.io diagram -> TikZ fragment")
    ap.add_argument("file")
    ap.add_argument("--diagram", help="substring of the diagram name")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--scale", type=float, default=0.0264)
    ap.add_argument("--translate")
    ap.add_argument("--brace-amplitude", type=int, default=10)
    ap.add_argument("--brace-mirror", choices=["auto", "on", "off"], default="auto")
    ap.add_argument("--wrap", action="store_true")
    ap.add_argument("--out")
    args = ap.parse_args()

    diagrams = load_diagrams(args.file)
    names = [d.get("name", "").strip() for d in diagrams]
    if args.list or not args.diagram:
        print("Diagrams:")
        for n in names:
            print("  - %s" % n)
        if args.list:
            return
        sys.exit("Specify --diagram <substring>")

    key = args.diagram.lower()
    matches = [d for d, n in zip(diagrams, names) if key in n.lower()]
    if len(matches) != 1:
        sys.exit("--diagram matched %d diagrams (need exactly 1): %s"
                 % (len(matches), [n for n in names if key in n.lower()]))

    translate = None
    if args.translate:
        with open(args.translate, encoding="utf-8") as f:
            translate = json.load(f)

    cells = collect_cells(matches[0])
    em = Emitter(cells, args.scale, translate, args.brace_amplitude,
                 args.brace_mirror)
    body = "\n".join(em.run())

    if args.wrap:
        out = ("\\begin{figure}[H]\n\\centering\n"
               "\\resizebox{\\linewidth}{!}{%\n\\begin{tikzpicture}\n"
               + body + "\n\\end{tikzpicture}%\n}\n"
               "\\caption{TODO\\label{fig:TODO}}\n\\end{figure}")
    else:
        out = body

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(out + "\n")
        print("wrote %s (%d draw lines)" % (args.out, body.count("\n") + 1))
    else:
        print(out)


if __name__ == "__main__":
    main()
