---
name: bibclean
description: "Clean and validate a BibTeX file: check required fields, normalize author names, detect duplicates, enrich missing DOIs via Scopus, annotate journal quality (SJR quartile), flag non-approved publishers. Produces a cleaned .bib file and a report. Trigger on: /bibclean, requests to clean or validate a .bib file."
---

Launch the `bib-cleaner` agent to clean and validate the following BibTeX file:

$ARGUMENTS

If no argument is provided, use the `.bib` file currently open in the IDE.

The agent will autonomously:

1. Parse all entries and check required fields per entry type (`@article`, `@inproceedings`, `@book`, etc.) — flags `[MISSING FIELD: X]`, `[MISSING DOI]`
2. Normalize author name formatting — flag `[AUTHOR FORMAT INCONSISTENT]` with suggested corrections
3. Detect duplicate entries by matching DOIs and titles — flag `[DUPLICATE: key1, key2]`
4. Validate all DOIs against Scopus — flag `[DOI INVALID]` or `[DOI MISMATCH]`; propose missing DOIs for entries without one
5. Annotate each journal with SJR quartile and CiteScore — flag `[LOW IMPACT — Q3/Q4]`
6. Flag entries from non-approved publishers — `[PUBLISHER NOT APPROVED]` (requires professor approval)
7. Check journal name abbreviation consistency — flag `[ABBREVIATION INCONSISTENT]`
8. Save `<basename>_clean.bib` with inline `% [FLAG]` and `% SUGGESTED:` comments
9. Save `<basename>_bib_report.md` with a full audit summary and temporal distribution histogram

All original entries are preserved — duplicates are commented out, never deleted.

Respond in French unless the `.bib` file contains predominantly English titles.
