---
name: auditreview
description: "Audit an existing review text: validate all references against Scopus, flag errors, analyze coverage gaps, and produce an executable improvement plan file. Trigger on: /auditreview, requests to validate or improve an existing review, reference checking requests."
---

Launch the `scopus-auditor` agent to audit the following review:

$ARGUMENTS

If no argument is provided, use the file currently open in the IDE.
If a file path is provided, the agent reads that file (and a sibling `.bib` if it exists).
If text is pasted directly, the agent treats it as the review content.

The agent will autonomously:

1. Extract and parse all references from the source
2. Validate each reference against Scopus (DOI lookup or title search); assign a confidence level (`[HIGH/MEDIUM/LOW CONFIDENCE]`) based on how well the Scopus abstract matches the citation context in the text; write a one-sentence justification as a LaTeX comment after each reference entry in the source (`% [CONFIDENCE: HIGH] — ...`); flag `[REFERENCE NOT INTRODUCED: key]` for any cited paper not presented with at least one descriptive sentence in the text
3. Flag validation errors: `[DOI INVALID]`, `[AUTHOR MISMATCH]`, `[YEAR MISMATCH]`, `[NOT FOUND]`, `[PUBLISHER NOT APPROVED]`
4. Identify coverage gaps: uncited sections, unsupported claims, over-relied sources
5. Search Scopus for candidate references to fill each gap
5b. Check whether the review cites enough recent work to demonstrate the main contribution is new: minimum 5 references from the last 5 years, and at least 1 from the last 12 months directly related to the main contribution; when either threshold is not met, search Scopus for candidate recent papers and propose insertion points with example text in Section G of the plan
6. Generate a LaTeX comparison table (rows = Author et al., columns = key parameters per CLAUDE.md)
7. Save an executable improvement plan as `<basename>_improvement_plan.md` alongside the source

The plan has sections: Strengths, Weaknesses, Text Improvements (A), Reference Improvements (B), Coverage Gaps (C), Comparison Table (D), General Critical Assessment (E), Academic Novelty Checklist (F), Recent Papers Novelty Check (G).

After reviewing the plan, the user can edit it, mark items `[SKIP]`, then ask:
"Execute the improvement plan for [filename]"

When executed, all changes are marked in LaTeX using the `changes` package:
- Added text (sentences, tables, figures): `\added[id=AU]{...}`
- Modified text: `\replaced[id=AU]{new text}{old text}`
- Deleted text: `\deleted[id=AU]{...}`
- Original text is never deleted silently — always preserved with `\deleted{}` if replaced

Respond in French unless the source text is predominantly in English.
