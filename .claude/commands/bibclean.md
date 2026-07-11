---
name: bibclean
description: "Clean and validate a BibTeX file: check required fields, normalize author names, detect duplicates, enrich missing DOIs via Scopus, annotate journal quality (SJR quartile), flag non-approved publishers. Produces a cleaned .bib file and a report. Trigger on: /bibclean, requests to clean or validate a .bib file."
---

Launch the `bib-cleaner` agent to clean and validate the following BibTeX file:

$ARGUMENTS

If no argument is provided, use the `.bib` file currently open in the IDE.

The agent executes its FULL contractual pipeline as defined in
.claude/agents/bib-cleaner.md, including every mandatory skill invocation
(deliberation, scholar-evaluation, extract-statistic, extract-futureworks, scopus where
applicable). Do not restate or reduce that pipeline here. If the agent returns
"PIPELINE-PAUSED @ ...", relay its request to the user verbatim, then resume the same
agent via SendMessage with the user's answer. On completion, verify the agent's final
checklist before presenting the result; if it is missing or contains an unsanctioned ✗,
send the agent back to complete the missing steps.

Deliverables: `<basename>_clean.bib` saved alongside the source, with inline `% [FLAG]`
and `% SUGGESTED:` comments, high-confidence DOIs added, and duplicates commented out
(all original entries preserved — never deleted); plus `<basename>_bib_report.md` with
the full audit summary and temporal distribution histogram.

Respond in French unless the `.bib` file contains predominantly English titles.