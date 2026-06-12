# Comparison-table enrichment (Gemini, bounded task)

Single source of truth for the optional Gemini cell-enrichment sub-step used at each agent's
"build comparison table" step (scopus-auditor, paper-auditor, thesis-auditor,
thesis-proposal-auditor, scopus-researcher). It redirects Gemini's scarce free-tier budget to a
bounded, high-value task instead of a whole-draft critique.

## Division of work

- **Claude extracts the axes.** From the validated references, Claude decides the concepts (columns)
  and parameters (rows) per the CLAUDE.md table convention (rows = parameters, columns = concepts).
- **Gemini enriches the cells only.** `gemini_table.py` sends just the axes (+ short context and the
  ref list) and asks Gemini to fill each `(parameter × concept)` cell. Tiny input, bounded output.
- **Claude assembles the LaTeX.** Gemini returns content as JSON; Claude builds the `\begin{table}`
  (bold first row/column, 10% grey header) and writes the two-sentence citation. Gemini never emits
  LaTeX — this keeps its output small and avoids escaping issues.

## Contract

Script: `.claude/skills/scopus/scripts/gemini_table.py`

Input (`--axes-file <path>` or `--stdin`), JSON:

```json
{
  "concepts":  ["Concept A", "Concept B"],
  "parameters":["Parameter 1", "Parameter 2"],
  "context":   "1-2 line framing of the comparison",
  "refs":      [{ "key": "smith2023", "title": "..." }]
}
```

Output, JSON:

```json
{
  "rows": [
    { "parameter": "Parameter 1", "cells": { "Concept A": "...", "Concept B": "..." } }
  ],
  "notes": "<= 2 sentences on any gap or caveat"
}
```

Bounds: `max_output_tokens = max(1024, rows*cols*24)`; input is trimmed (ref titles first, then
context) if it exceeds `--max-input-tokens` (default 4000). Cells are caveman-terse (≤12 words).

## Invocation

```powershell
echo '<axes json>' | python ".claude/skills/scopus/scripts/gemini_table.py" --stdin
# or
python ".claude/skills/scopus/scripts/gemini_table.py" --axes-file "<axes.json>"
```

## Graceful skip

If `GEMINI_API_KEY` is unset (or any API failure), the script prints `{"skipped": true, ...}` and
exits 0. The agent's table step is unaffected: Claude authors the table either way. Enrichment is a
bonus when Gemini is available, never a dependency.

## Boundaries

- Do not let Gemini invent references; it may use only the `refs` passed in.
- The table itself, its formatting, and its in-text citation stay Claude-authored.
- This is not deliberation. The two-round debate panel
  (`.claude/skills/deliberation/`) is separate and unrelated.
