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

1. Label — has a `\label{...}`.
2. Citation — cited in the running text via `\ref` / `\eqref` / `\cref`. A float never referenced in
   prose is non-compliant.
3. Explanation — at least two sentences in the prose explain what the float shows and why it matters.

## Equations

- Cited BEFORE the equation: the sentence referencing `\eqref{eq:...}` appears in the text above the
  equation and introduces it. Citing only after the equation, or not at all, is non-compliant.
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

- Cited in the text with at least two sentences.
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
- Cited with at least two sentences.
- Label (`\label{fig:...}`).
- TikZ figures additionally follow the TikZ rules in `CLAUDE.md` (relative positioning, perpendicular
  arrows, 3-character minimum spacing, no overlaps).

## Self-check before finalizing

For each float added or fixed, verify and resolve every miss, flagged
`[FLOAT NON-COMPLIANT: <id> — <what>]`:

- [ ] has `\label`
- [ ] cited in prose (equation: the citation appears BEFORE the equation)
- [ ] >= 2 explanatory sentences in prose
- [ ] equation: every variable defined directly under it (or already defined earlier)
- [ ] equation: `\text{,}` after the expression if a "where"/sentence continues, `\text{.}` if the sentence ends (amsmath, not a bare math-mode `,`/`.`)
- [ ] table: rows = parameters, columns = concepts; first row and first column bold; first row 10% grey

A plan entry that fixes a flagged float MUST carry the full compliant replacement (the float plus the
prose citation and explanation to insert), never a bare "add a citation" note.
