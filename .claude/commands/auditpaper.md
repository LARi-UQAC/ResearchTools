---
name: auditpaper
description: "Audit a complete scientific paper: references, methodology, results, discussion, future works. Validates all citations against Scopus, flags content issues, runs cross-review via Gemini + GitHub Copilot, and produces an executable improvement plan file. Trigger on: /auditpaper, requests to audit or improve a full paper (not just the literature review)."
---

Launch the `paper-auditor` agent to audit the following paper:

$ARGUMENTS

If no argument is provided, use the file currently open in the IDE.
If a file path is provided, the agent reads that file (and a sibling `.bib` if it exists).
If text is pasted directly, the agent treats it as the paper content.

The agent will autonomously:

1. Parse the paper structure and identify all standard sections (Abstract, Introduction, Methodology, Results, Discussion, Conclusion/Future Works, References)
1b. Detect and audit any literature review content — a dedicated "Related Works" / "Literature Review" / "État de l'art" section, or citation clusters in the Introduction (≥ 3 citations within 150 words) — running the same validation, coverage-gap analysis, and comparison-table generation as the `scopus-auditor` agent; results go in Section N of the plan
2. Validate every `\cite{}` reference against Scopus — flags: `[DOI INVALID]`, `[AUTHOR MISMATCH]`, `[YEAR MISMATCH]`, `[NOT FOUND]`, `[PUBLISHER NOT APPROVED]` — assign a confidence level (`[HIGH/MEDIUM/LOW CONFIDENCE]`) with a one-sentence justification written as a LaTeX comment after each entry in the `.bib` file (`% [CONFIDENCE: HIGH] — ...`), and flag `[REFERENCE NOT INTRODUCED: key]` for any cited paper not presented with at least one descriptive sentence in the text
3. Search Scopus for the current state of the art to benchmark the paper's methodology and results
4. Audit the Methodology section — flags: `[NOT REPRODUCIBLE]`, `[NO COMPARISON]`, `[INCOMPLETE SETUP]`, `[OUTDATED METHOD]`, `[UNSUPPORTED CLAIM]`
5. Audit every figure and table — flags: `[NOT CITED]`, `[CITATION FAR]`, `[INSUFFICIENT DESCRIPTION]`, `[LOW RESOLUTION]` (raster images below 300 DPI), `[IMAGE FILE MISSING]`
6. Audit the Results section — flags: `[NO METRICS]`, `[NO BASELINE]`, `[NO STATISTICS]`, `[BELOW STATE-OF-ART]`, `[FIGURE NOT CITED]`, `[ORPHAN RESULT]`
7. Audit the Discussion section — flags: `[OBJECTIVE NOT ADDRESSED]`, `[NO INTERPRETATION]`, `[NO LIMITATIONS]`, `[UNSUPPORTED CONCLUSION]`, `[NOT POSITIONED]`
8. Audit Future Works statements using the H1–H5 novelty checklist — flags: `[ALREADY EXISTS IN LITERATURE]`, `[NOT TESTABLE]`, `[GENERAL KNOWLEDGE]`, `[PASSES H1–H5]`
9. Evaluate LLM usage across all prose sections — detects em dashes, smart quotes, zero-width spaces, AI transition phrases, sentence-length uniformity, and perfect parallel lists — produces an AI-style risk score (target < 10 % per CLAUDE.md)
10. Run cross-review via Gemini 2.0 Flash and GitHub Copilot (GPT-4o) with consensus arbitration
11. Generate an executable improvement plan as `<basename>_paper_audit_plan.md` alongside the source

The plan has sections: Strengths, Weaknesses, Reference Issues (A), Methodology Issues (B), Results Issues (C), Discussion Issues (D), Future Works Issues (E), Missing Sections (F), General Critical Assessment (G), Cross-Review Log (H), Figure and Table Issues (I), LLM Usage Assessment (J), Equations and Acronyms (K), Abstract Consistency (L), Section Flow Issues (M), Literature Review Audit (N).

After reviewing the plan, the user can edit it, mark items `[SKIP]`, then ask:
"Execute the paper audit plan for [filename]"

When executed, all changes are marked in LaTeX using the `changes` package:
- Added text (sentences, tables, figures): `\added[id=AU]{...}`
- Modified text: `\replaced[id=AU]{new text}{old text}`
- Deleted text: `\deleted[id=AU]{...}`
- Original text is never deleted silently — always preserved with `\deleted{}` if replaced

Respond in French unless the source paper is predominantly in English.
