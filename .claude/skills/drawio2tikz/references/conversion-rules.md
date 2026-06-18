# draw.io -> TikZ conversion rules and pitfalls

Reference for `scripts/drawio2tikz.py`. Every rule here came from a real bug.
Read this before changing the script or hand-patching generated TikZ.

## Coordinate model

- draw.io is **y-down**; TikZ is **y-up**. Flip: `y_tikz = -y_draw`.
- Scale: ~`0.0264` cm per px (≈ draw.io's px->cm). Absolute placement
  (`\node at (x,y)`, `\draw (x1,y1) -- (x2,y2)`). Always wrap the picture in
  `\resizebox{\linewidth}{!}{...}` so the chosen scale never breaks column fit;
  fonts scale with it, so set node font sizes proportional to px
  (`fpt = font_px * scale * 28.4528`).
- Use absolute coordinates here even though hand-authored TikZ in this workspace
  normally prefers `positioning`. Exact reproduction of a fixed drawing needs
  absolute placement; this is the documented exception.
- `\resizebox` caveat: wrap the whole `tikzpicture`, but never wrap a
  `\begin{scope}[on background layer]` inside `\resizebox` / `\scalebox` (it breaks
  the background layer); use `transform canvas={scale=...}` for that scope. Mirrors
  the `/tikz` command's backgrounds rule.

## Cell structure

- Cells are `<mxCell>` OR wrapped: `<object id=.. label=..><mxCell .../></object>`.
  For wrapped cells the **id and label live on `<object>`**, style/parent on the
  inner `<mxCell>`. Parse both.
- **Skip** layer/root cells: not an edge, zero width/height, no text (e.g. ids
  `0`, `1`). Emitting them creates stray 0x0 nodes.
- **Skip** group containers (`style` contains `group`) — they only translate
  children; do not draw them.

## Group offsets (nesting)

Child coordinates are **relative to the parent group**. Resolve absolute
position by summing the x/y of every ancestor *vertex* up the `parent` chain
(edges contribute no offset). Groups can nest (group inside group inside the
figure root group); sum them all.

## Edges — the highest-risk area

draw.io stores `sourcePoint`/`targetPoint` (`mxPoint`) as **fallback only**.
The rendered endpoint depends on connectivity:

1. **`source`/`target` id present** -> the endpoint is on the SHAPE, not the
   stored point:
   - With `exitX/exitY` (source) or `entryX/entryY` (target): the point is
     `shape_xy + (exitX*w + exitDx, exitY*h + exitDy)` in the shape's own space,
     then offset to absolute. `exitPerimeter=0` means use that exact point (no
     perimeter projection).
   - Without an anchor: fall back to the shape centre (or perimeter toward the
     next point). Using the stale `mxPoint` here makes the line float off the
     box — a visible "disconnected" defect.
2. **No id** -> the `mxPoint` is the real endpoint; use it.

**`<Array>` waypoints** are real intermediate points and must be inserted into
the polyline: `source -> wp1 -> wp2 -> ... -> target`. Dropping them can leave a
gap (a waypoint may even extend the line *past* its stored target; reproduce the
full polyline faithfully — the overlap is invisible, the reach is what matters).

Arrow tips: `endArrow=classic|block` -> `-{Latex[length=2mm]}`. `strokeWidth>=3`
-> scaled `line width`. `dashed=1` -> `dashed`.

## Shapes (vertices)

- Render as a `\node[draw,...] at (centre)` with `minimum width/height` = w/h in
  cm, `inner sep=0`. This handles fill, stroke, rotation, and text uniformly.
- `rounded=1` -> `rounded corners=2pt`.
- Text-only cell (`text;`, `edgeLabel`, or `fillColor=none` + `strokeColor=none`)
  -> node with no `draw`/`fill`.
- Colours: `fillColor`/`strokeColor`/`fontColor` `#RRGGBB` -> inline
  `{rgb,255:red,R;green,G;blue,B}`. Honour `none`. Default stroke black.
  (Note: a raster export of an older sheet may lack colours the current XML has;
  the XML is the source of truth, keep the colours.)
- Text: strip HTML tags, unescape entities (`&lt; &gt; &quot; &#39; &nbsp; &amp;`),
  read `font-size:Npx`, detect bold (`<b`).

## Rotation

- `rotation=-360` (and any multiple of 360) == 0; ignore.
- TikZ angle = `-rotation` (the Y flip reverses sense). Rotation is about the
  cell centre, which matches a node placed at the centre with `rotate=`.

## curlyBracket -> brace

- Spine runs along the cell **height**; half-length = `h/2`.
- `rotation` 90/270 -> horizontal brace; else vertical.
- Bulge side is heuristic: mirror horizontal braces (underbrace opening down
  toward a label), leave vertical ones. Expose `--brace-mirror auto|on|off`.
- Amplitude must be visibly large (default 10pt) — a 4pt brace under a 12cm span
  reads as a flat line. **Always visually verify brace direction after compile.**

## Verification

Never declare done without rendering the figure page (`pdftoppm`) and comparing
to the draw.io sheet. Check: every connector meets its shape, braces open the
right way, rotated labels sit correctly, colours and module/terminal layout match.

For the surrounding figure (label, caption, citation, explanatory sentences),
follow `.claude/skills/scientific-writing/references/float_authoring_rules.md`; a
drawio2tikz figure is the sanctioned absolute-coordinate exception described there.
