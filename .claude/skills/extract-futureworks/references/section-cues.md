# Section cues for future-works detection

The heading cues `scan_sections()` (in
`.claude/skills/extract-statistic/scripts/extract_text.py`) matches to locate the relevant passages.
The scanner detects a heading (Markdown `#`..`######`, LaTeX `\section`/`\subsection`, or a short
plain-text title line) and classifies it against these cues, case-insensitively, in English and
French. The first matching category wins.

## Categories and cues

| Label | English cues | French cues |
|---|---|---|
| `future_work` | future work(s), future directions, future research, further work(s) | travaux futurs, perspectives, recommandations |
| `open_problems` | open problems, open questions, open challenges, challenges | problemes ouverts, defis |
| `limitations` | limitations | limites |
| `conclusion` | conclusion(s), concluding remarks | conclusion(s) |

Notes:
- `future_work` is the primary signal for the `mine` mode: a statement under one of these headings is
  an author-declared next step, the highest-value seed for the gap map and hypotheses.
- `limitations` and `conclusion` are secondary: a future work is often stated inside a Conclusion or
  framed as the flip side of a Limitation, so these passages are captured too and the host links each
  future-work item to the limitation it answers (`[FW NOT LINKED TO LIMITATION]` when none exists).
- A heading that matches several cues is assigned the first category in the table order
  (future_work > open_problems > limitations > conclusion), so "Conclusion and Future Work" is tagged
  `future_work`.
- Cues are matched on the heading text only, not the body, to avoid false positives from the prose.
- French cues are matched without relying on accents (the parser lower-cases and the cue list uses
  unaccented forms) so `Perspectives` and `Limites` are caught regardless of encoding.

## Extending the cues

Add a new `(label, pattern)` entry to `_SECTION_CUES` in `extract_text.py` and a row here. Keep the
patterns anchored to whole words (`\b...\b`) and case-insensitive. Do not add cues that collide with
common body words (for example a bare "results") - the heading heuristic already limits matches to
title-like lines, but an over-broad cue would still raise false sections.
