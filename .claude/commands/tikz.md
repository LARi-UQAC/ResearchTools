# TikZ validation

Validate the provided TikZ code or the .tikz/.tex file open in the IDE against these rules:

1. **Line breaks in nodes**: use `align=center` only — never `text centered` (which does not support `\\`)
2. **backgrounds library + scaling**: never wrap a `tikzpicture` using `\begin{scope}[on background layer]` inside `\resizebox` or `\scalebox` — use `transform canvas={scale=...}` or reduce node dimensions instead
3. **Arrow angles**: arrows must connect perpendicularly to node borders (.north, .south, .east, .west) — no diagonal connections to a straight side
4. **Overlaps**: minimum 3-character gap between rectangles; text on arrows must not overlap other text or geometry
5. **Anchoring**: use `positioning` library and `node distance` — no absolute coordinates
6. **TiKZiT compatibility**: keep code simple; named styles belong in the .tikzstyles file; avoid exotic libraries

For each violation: cite the line, explain the cause in one sentence, provide the corrected code directly.
If no issues are found: confirm in one line.

$ARGUMENTS
