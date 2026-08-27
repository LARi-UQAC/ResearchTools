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

## Sentence-level cues (in-prose signals)

The categories above match a heading. Prose does not always carry one: a future-work statement
can sit inside a paragraph of the Conclusion, the Discussion, or anywhere else with no heading of
its own to catch it. The cues below match at the sentence level instead, for a scan of running text
rather than section titles.

| Label | English cue phrases |
|---|---|
| `plan_stated` | we plan to, plan to extend |
| `next_step` | next step |
| `temporal_marker` | in the future |
| `open_ended` | remain(s) open, remain(s) an open |
| `deferred_scope` | leave(s/d) to future, leave(s/d) for future |
| `further_variant` | further research, further study, further investigation |

Notes:
- These extend, not duplicate, the heading table: future work(s), future research, future
  direction(s), open problem(s)/challenge(s), limitation(s), and further work(s) already have a
  heading-level equivalent above and are not repeated here.
- `further_variant` generalizes the heading table's "further work(s)" to the other nouns the same
  construction takes.
- No French sentence-level cues are listed here; the source below worked from English full text
  only, so a French set would need its own validation before use.
- Cues are salvaged from a throwaway extraction script written during the 2026-08-25
  Penelope_Allan audit session
  (`docs/superpowers/todo/2026-08-27-audit-scripts-src/fw_extract2.py`); they exist to match a
  future-work statement inside running prose, when no dedicated section heading exists.

## Extending the cues

Add a new `(label, pattern)` entry to `_SECTION_CUES` in `extract_text.py` and a row here. Keep the
patterns anchored to whole words (`\b...\b`) and case-insensitive. Do not add cues that collide with
common body words (for example a bare "results") - the heading heuristic already limits matches to
title-like lines, but an over-broad cue would still raise false sections.
