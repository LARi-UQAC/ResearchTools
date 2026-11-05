# Language correction table

One row per correction. `code` is a code of `language_categories.json`. `location` is `line N` (or
`Ch.N line M`) for a LaTeX source and `p. N` for a PDF. `proposed` is the full replacement text, never an
instruction. `reason` cites the rule (`R1.7`) when the entry has one, else the label. The rows below are
fictitious examples, one per scope.

| location | code | original | proposed | reason |
|---|---|---|---|---|
| line 42 | SEMI | The gain was raised; the overshoot fell. | The gain was raised. The overshoot then fell. | R1.7 semicolon in prose |
| line 87 | PI | I tuned the controller by hand. | The controller was tuned by hand. | R1.4 pronoun I forbidden |
| p. 3 | SP | Le système est stabe en boucle fermée. | Le système est stable en boucle fermée. | Orthographe |
| p. 5 | AG | Les mesures obtenu montrent un écart. | Les mesures obtenues montrent un écart. | Accord |
