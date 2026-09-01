---
description: "Clean and validate a BibTeX file: check required fields, normalize author names, detect duplicates, enrich missing DOIs via Scopus, annotate journal quality (SJR quartile), flag non-approved publishers. Produces a cleaned .bib file and a report. Trigger on: /bibclean, requests to clean or validate a .bib file."
---

Launch the `bib-cleaner` agent to clean and validate the following BibTeX file:

the file(s) or topic given after the command in the chat message (if none was given, use the file currently open in the editor)

If no argument is provided, use the `.bib` file currently open in the IDE.

The agent executes its FULL contractual pipeline as defined in
.claude/agents/bib-cleaner.md, including every mandatory skill invocation
(deliberation, scholar-evaluation, extract-statistic, extract-futureworks, scopus where
applicable). Do not restate or reduce that pipeline here. If the agent returns
"PIPELINE-PAUSED @ ...", relay its request to the user verbatim, then resume the same
agent via SendMessage with the user's answer. On completion, verify the agent's final
checklist before presenting the result; if it is missing or contains an unsanctioned ✗,
send the agent back to complete the missing steps.

The measurement is scripted (`.claude/skills/scopus/scripts/bib_audit.py`); the judgment is
the agent's. Do not ask it to re-check entries by hand.

Deliverables: `<basename>_clean.bib` saved alongside the source, with inline `% [FLAG]`,
`% Journal:` and `% SUGGESTED:` comments and high-confidence DOIs added (all original
entries preserved in their original order — never deleted, never reordered); plus
`<basename>_bib_report.md` carrying the measured audit (summary, temporal distribution,
per-entry flags, venue-metrics table) followed by the agent's verdict, fix list, and the
entries to submit to the professor.

Respond in the language the audit reports as `corpus_language` (French unless the `.bib`
contains predominantly English titles).

