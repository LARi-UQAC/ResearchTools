---
name: drawio2tikz
description: "Convert one sheet of a .drawio file into a coordinate-exact TikZ fragment for embedding in LaTeX. Use when the user asks to turn a draw.io diagram/figure into TikZ, when a LaTeX figure must reproduce a draw.io sheet exactly (mechanical drawings, flowcharts, module layouts), or for /drawio2tikz. Drives scripts/drawio2tikz.py (absolute coordinates, group-offset resolution, edge anchoring to shape perimeters, waypoints, braces, FR->EN translation)."
allowed-tools: [Read, Write, Edit, Bash]
permissions: [write]
---

# drawio2tikz Skill

Deterministic, by-script conversion of a single `<diagram>` (sheet) from a
`.drawio` file into a TikZ fragment using **absolute coordinates**. The script
encodes every conversion rule that is easy to get wrong by hand; do not
re-transcribe diagrams manually and do not eyeball coordinates.

## When to use

- A LaTeX figure must reproduce a draw.io sheet exactly (no simplification):
  mechanical drawings, battery/module layouts, flowcharts, schematics.
- The user provides a `.drawio` path and names a sheet, or asks for `/drawio2tikz`.
- Re-running after the `.drawio` changed (regenerate, then re-embed).

This script is the source of conversion truth. If a figure already in a `.tex`
looks wrong, prefer **diffing the existing TikZ against the drawio** and patching
the offending lines (see "Fixing an existing figure"); regenerate only when the
whole figure is being (re)built.

## Prerequisites

1. `python` reachable from the shell.
2. Recommended: `pip install defusedxml` (the script falls back to the stdlib
   parser for trusted local files, but defusedxml avoids the XXE warning).
3. The consuming LaTeX preamble must load:
   ```latex
   \usetikzlibrary{arrows.meta,decorations.pathreplacing}
   ```
   (`arrows.meta` for arrow tips, `decorations.pathreplacing` for braces.)
   `xcolor` is pulled in by most classes (mdpi.cls, etc.); colours are emitted
   inline as `{rgb,255:...}`.

## Usage

```bash
# 1. list the sheets
python .claude/skills/drawio2tikz/scripts/drawio2tikz.py FILE.drawio --list

# 2. convert one sheet to a fragment
python .claude/skills/drawio2tikz/scripts/drawio2tikz.py FILE.drawio \
    --diagram "Scenario 2" --out fragment.tex

# with FR->EN label translation and a full figure skeleton
python .claude/skills/drawio2tikz/scripts/drawio2tikz.py FILE.drawio \
    --diagram "Scenario 2" --translate labels.json --wrap --out fragment.tex
```

`--diagram` takes a **case-insensitive substring** of the sheet name and must
match exactly one sheet (accents in `.drawio` names can be awkward in the shell;
a partial like `tude 2` is fine).

| Flag | Effect |
|---|---|
| `--list` | Print sheet names and exit |
| `--diagram NAME` | Substring of the target sheet name (must be unique) |
| `--scale F` | cm per draw.io px (default `0.0264`); irrelevant for fit if wrapped in `\resizebox` |
| `--translate JSON` | `{ "french": "english" }` applied to label text after HTML stripping |
| `--brace-amplitude P` | Brace size in pt (default `10`) |
| `--brace-mirror auto\|on\|off` | Bulge side of `curlyBracket` braces (default `auto` = mirror when horizontal) |
| `--wrap` | Emit a `figure`+`\resizebox`+`tikzpicture` skeleton with a TODO caption |
| `--out FILE` | Write to FILE (default stdout) |

## Workflow

1. `--list` to confirm the exact sheet name.
2. If labels need translating, write a small JSON dict (French key -> English
   value), one entry per distinct label string (exact match after HTML strip).
   Translate only toward the target document's language: if the consuming document
   is French, keep French labels (or translate EN->FR); respect the document's
   original language (the scientific-writing language rule).
3. Run the script with `--out` to a temp fragment.
4. Embed: paste the fragment inside the target `figure` environment, wrapped in
   `\resizebox{\linewidth}{!}{ \begin{tikzpicture} ... \end{tikzpicture} }` so it
   fits the column regardless of `--scale`. Keep the existing `\caption`/`\label`.
   The embedded figure must follow the scientific-writing float rules: a
   `fig:three-words` `\label`, a citation via `\ref{}` with at least two explanatory
   sentences, and a real caption (replace the `--wrap` TODO). See
   `.claude/skills/scientific-writing/references/float_authoring_rules.md`.
5. Compile and **verify visually** (render the figure page with `pdftoppm` and
   compare against the draw.io sheet). Check especially: connectors meeting their
   shapes, brace direction, rotated labels.

The converted output is intentionally NOT TiKZiT-editable and uses **absolute
coordinates** by design (the documented exception to the scientific-writing /
`/tikz` relative-positioning rule). Running `/tikz` on it may flag arrow tips or
spacing, but the absolute coordinates and inline colours are expected here and are
not defects; only arrow tips, true overlaps, and connectors that miss their shapes
are worth acting on.

## Fixing an existing figure (no full reconversion)

When a figure is mostly right but has a defect, do not regenerate blindly:

1. Read the TikZ lines in the `.tex`.
2. Read the corresponding cells in the `.drawio` sheet.
3. Diff numerically; the usual culprits are listed in
   `references/conversion-rules.md` (edge endpoints, braces, rotation).
4. Patch the offending `\draw`/`\node` line(s) directly.

## Brace direction caveat

`curlyBracket` orientation (which way the tongue points) is the one thing the
script infers heuristically: it mirrors horizontal braces (underbrace, opening
down toward a label) and leaves vertical ones un-mirrored. Always eyeball braces
after compiling; flip with `--brace-mirror on|off` or edit the single `\draw`
line if the bulge points the wrong way.

## Error handling

| Symptom | Cause / action |
|---|---|
| `--diagram matched N diagrams` | Substring not unique; pass a longer, unique fragment of the name |
| Connector line floats off a box | Edge anchored via `exit`/`entry` — the script handles this; if it still floats, the shape has no `exit`/`entry` and no useful `mxPoint` (rare) — add the anchor in draw.io or patch the endpoint |
| A line stops short of where it should meet | Missing `<Array>` waypoint in the source, or the waypoint extends past the target (script includes waypoints; verify the source) |
| Brace looks flat / points wrong way | `--brace-amplitude` too small, or wrong `--brace-mirror`; see caveat above |
| Rotated label misplaced | draw.io `rotation` is about the cell centre; the script emits `rotate=-rotation` (Y flip) about the node centre — verify the cell really rotates about its centre in draw.io |
| Garbled accents in `--list` output | Console codepage only; the conversion itself is UTF-8 safe |
| XXE warning on Write/run | Install `defusedxml`; the stdlib fallback is acceptable for a trusted local file |

## See also

- Converter: `scripts/drawio2tikz.py`
- Conversion rules and pitfalls (read before editing the script): `references/conversion-rules.md`
