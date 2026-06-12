---
name: submitcheck
description: "Check whether a LaTeX paper meets the submission requirements of a target journal. Verifies page count, required sections, reference style, abstract length, keywords, figure count, and anonymization. Produces an executable submission checklist. Trigger on: /submitcheck, requests to check paper readiness for submission to a specific journal."
---

Launch the `submit-checker` agent to check submission readiness:

$ARGUMENTS

Provide both the source file path and the target journal name, separated by a space, for example:
`/submitcheck paper.tex "IEEE Transactions on Industrial Informatics"`

If no journal is specified, the agent will ask for it before proceeding.

The agent will autonomously:

1. Look up the target journal via Scopus to obtain publisher, SJR quartile, CiteScore, and reference style
2. Estimate the compiled page count and flag `[EXCEEDS PAGE LIMIT]` or `[BELOW MINIMUM LENGTH]`
3. Check all required sections for the target publisher (Abstract, Keywords, Data Availability Statement, Ethics Statement, etc.) — flag `[REQUIRED SECTION MISSING: X]`
4. Verify reference style compliance (`\bibliographystyle{...}` vs. expected style) — flag `[REFERENCE STYLE MISMATCH]`
5. Check figure and table count — flag `[HIGH FIGURE COUNT]` if above typical limits
6. Verify author anonymization if the journal uses double-blind review — flag `[ANONYMIZATION INCOMPLETE]`
7. Check abstract word count against venue limits — flag `[ABSTRACT TOO LONG]` or `[ABSTRACT TOO SHORT]`
8. Validate keywords: count, separator style, no title duplication — flag `[TOO FEW KEYWORDS]`, `[KEYWORD SEPARATOR WRONG]`
9. Save `<basename>_submit_<journal-slug>.md` with a detailed pass/fail checklist and a prioritized action list

Respond in French unless the source paper is predominantly in English.
