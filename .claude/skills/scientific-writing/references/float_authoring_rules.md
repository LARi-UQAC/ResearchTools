# Float authoring rules (equations, tables, figures)

Canonical, project-wide rules for every figure, table, and equation that the academic agents
(scopus-auditor, paper-auditor, thesis-auditor, thesis-proposal-auditor, scopus-researcher,
reviewer-response) ADD to a document or PRESCRIBE as a fix in an improvement plan. Source: the
project `CLAUDE.md`.

These rules bind at authoring time AND when a plan is executed. Inserting the float is not enough:
the in-text citation and the explanatory sentences must be inserted in the prose as well. A fix that
flags an uncited equation but adds only the equation (no citation, no variable definitions, no
explanation) is NON-COMPLIANT.

## Universal (every figure, table, equation)

1. Label — has a `\label{...}` using the meaningful naming convention: `fig:three-words` for a figure,
   `tab:three-words` for a table, `eq:three-words` for an equation (lowercase, hyphenated, descriptive).
2. Citation — cited in the running text via `\ref` / `\eqref` / `\cref`. A float never referenced in
   prose is non-compliant. Place the float near its first mention: keep the environment within about
   100 lines of its `\ref{}` so it floats close to where it is introduced.
3. Explanation — at least two sentences in the prose explain what the float shows and why it matters.

## Equations

- Cited BEFORE the equation: the sentence referencing `\eqref{eq:...}` appears in the text above the
  equation and introduces it. Citing only after the equation, or not at all, is non-compliant.
- Numbered: every display equation that is referenced must be NUMBERED. Do not use `equation*`,
  `align*`, `eqnarray*`, or a bare `\[ ... \]` block for an equation you reference; an unnumbered
  equation cannot be cited precisely during peer review.
- Label inside the equation environment (`\label{eq:...}`).
- Variable definitions directly under the equation: every symbol is defined immediately below the
  equation (a "where ..." block), unless it was already defined in the preceding text.
- Punctuation: the equation is part of the sentence. Put a comma right after the expression when the
  sentence continues (typically a "where ..." clause), and a period when the sentence ends. Use
  `\text{,}` / `\text{.}` (amsmath), not a bare math-mode `,`/`.`, so the mark keeps the upright shape,
  weight, and font of the body text. It goes INSIDE the equation environment, after the expression and
  before `\label` (`... + O \text{,} \label{eq:cost}` when "where" follows; `... + O \text{.}
  \label{eq:cost}` when nothing follows).
- At least two explanatory sentences (the introducing sentence plus at least one more on meaning,
  assumptions, or use).

Compliant skeleton:

```latex
The total cost is given by Eq.~\eqref{eq:cost}, which combines the wall term and the openings term.
\begin{equation}
  C = P \cdot h \cdot u + O \text{,} \label{eq:cost}
\end{equation}
where $C$ is the total cost, $P$ the perimeter, $h$ the height, $u$ the unit price, and $O$ the
openings cost. Isolating the linear wall term from the fixed openings term lets the sensitivity to
$u$ be read directly.
```

## Tables

- Cited in the text via `\ref{tab:...}` with at least one sentence presenting the table, and at least
  two sentences total explaining it.
- Label (`\label{tab:...}`).
- Orientation: ROWS are the parameters / criteria analyzed; COLUMNS are the concepts / methods
  compared.
- First row (header) AND first column in bold.
- First row shaded 10% grey: `\rowcolor[gray]{0.9}` (requires `xcolor` / `colortbl`).

Compliant skeleton:

```latex
Table~\ref{tab:cmp} compares the three controllers across two criteria. PID is the simplest but shows
the largest overshoot, whereas MPC trades computation for the best tracking.
\begin{table}[ht]
  \centering
  \begin{tabular}{|l|c|c|c|}
    \hline
    \rowcolor[gray]{0.9}
    \textbf{Critère} & \textbf{PID} & \textbf{LQR} & \textbf{MPC} \\ \hline
    \textbf{Dépassement} & 12\% & 5\% & 2\% \\ \hline
    \textbf{Calcul}      & faible & moyen & élevé \\ \hline
  \end{tabular}
  \caption{Comparaison des contrôleurs.} \label{tab:cmp}
\end{table}
```

## Figures

- TiKZ (`.tikz`, for TiKZiT) is the default authoring medium. AI-generated schematics are optional;
  when it is unclear whether a figure should be hand-authored in TiKZ or AI-generated, ASK the user
  (AskUserQuestion) before generating.
- Cited in the text via `\ref{fig:...}` with at least one sentence presenting the figure, and at least
  two sentences total explaining it.
- Label (`\label{fig:...}`).
- Raster image (`.png`, `.jpg`, `.jpeg`, `.bmp`, `.tif`): at least 300 DPI on both axes. Prefer a
  vector format (`.pdf`, `.eps`, `.svg`, `.tikz`, `.pgf`) so resolution is never an issue.
- TikZ figures additionally follow the enumerated TikZ geometry rules below.

## TikZ geometry (canonical)

Mirror of the nine figure rules in `.claude/CLAUDE.md`. Every TiKZ figure authored or fixed must
satisfy all nine:

1. Anchored with the `positioning` library and `node distance` rather than absolute coordinates.
2. Arrows do not pass over geometric shapes, rectangles, or squares.
3. Arrows do not overlap and are not juxtaposed to another geometry.
4. Arrows start and end at 90 degrees (perpendicular) to the geometry (block, rectangle, circle).
5. Rectangles and shapes do not overlap or juxtapose; keep a minimum 3-character distance between them.
6. Text on arrows does not overlap or juxtapose; keep a minimum distance between text elements on arrows.
7. The figure is cited in the text with at least two explanatory sentences.
8. The TikZ code is simple for the TiKZiT parser; named styles live in the `.tikzstyles` file.
9. Citation uses `\ref{}` with a `fig:three-words` label, and at least one sentence presents the figure.

### Required libraries and arrow tips

- Load the libraries the figure uses in the preamble: `\usetikzlibrary{positioning}` always (rule 1);
  add `arrows.meta` for arrow tips, `decorations.pathreplacing` for braces, and `backgrounds` only when
  a background layer is genuinely needed.
- Arrow-tip convention: use `arrows.meta` tips, e.g. `-{Latex[length=2mm]}`, rather than the legacy
  `->` default, for a consistent look across figures.
- `backgrounds` caveat: never wrap a `\begin{scope}[on background layer]` inside `\resizebox` /
  `\scalebox`; use `transform canvas={scale=...}` or smaller node dimensions instead (same caveat the
  `/tikz` command checks).

### Overlap prevention (no superposition of arrow, box, or object)

Construction makes superposition structurally hard — apply it while authoring, do not rely on
catching overlaps afterward:

- Place every node only with `positioning` + `node distance` (no absolute coordinates), and keep at
  least a 3-character gap between shapes (rule 5).
- Anchor every arrow perpendicular to a named anchor (`.north` / `.south` / `.east` / `.west`), not to
  a diagonal corner (rule 4).
- Route a long arrow around any intervening box with explicit waypoints (`-|`, `|-`) or a gentle
  `to[bend left=NN]`, never straight through a shape (rules 2-3).
- Prefer one-direction chains so arrows do not cross each other (rule 3).

This is prevention, not a geometric proof: there is no bounding-box checker, so an arrow crossing a
box, or an arrow crossing another arrow, is caught only by the two gates below.

### Validation gates (mandatory before a TikZ figure is done)

1. Run `/tikz` on the figure and resolve every flagged overlap, arrow angle, or spacing violation.
2. Render in TiKZiT (or compile the PDF, e.g. `pdftoppm -png -r 150 out.pdf page`) and visually
   confirm that no arrow crosses a shape and that no two arrows or text labels superpose.

### Converted figures (drawio2tikz) exception

A figure produced by the `drawio2tikz` skill (a coordinate-exact conversion of a `.drawio` sheet) is
the sanctioned ABSOLUTE-coordinate case. It is exempt from the relative-positioning rule (1), the
TiKZiT-simple rule (8), and the perpendicular-arrow / no-overlap geometry rules (2-6): exact
reproduction of the source drawing wins, so connectors and shapes follow the original even when they
sit at an angle or close together. Such a figure MUST still satisfy the float rules in this file: a
`fig:three-words` `\label`, a citation via `\ref{}` with at least two explanatory sentences, and a
real caption (replace the converter's TODO). See `.claude/skills/drawio2tikz/SKILL.md` for the
conversion and embedding workflow.

## Self-check before finalizing

For each float added or fixed, verify and resolve every miss, flagged
`[FLOAT NON-COMPLIANT: <id> — <what>]`:

- [ ] has `\label` using the naming convention (`fig:` / `tab:` / `eq:` + three hyphenated words)
- [ ] cited in prose (equation: the citation appears BEFORE the equation), near its first mention
- [ ] >= 2 explanatory sentences in prose
- [ ] equation: numbered (no `equation*` / `align*` / `eqnarray*` / `\[ \]` for a referenced equation)
- [ ] equation: every variable defined directly under it (or already defined earlier)
- [ ] equation: `\text{,}` after the expression if a "where"/sentence continues, `\text{.}` if the sentence ends (amsmath, not a bare math-mode `,`/`.`)
- [ ] table: rows = parameters, columns = concepts; first row and first column bold; first row 10% grey
- [ ] figure: raster >= 300 DPI (or vector); the nine TikZ geometry rules met
- [ ] TikZ overlap gates passed: `/tikz` clean AND TiKZiT render shows no arrow/box/label superposition

A plan entry that fixes a flagged float MUST carry the full compliant replacement (the float plus the
prose citation and explanation to insert), never a bare "add a citation" note.
