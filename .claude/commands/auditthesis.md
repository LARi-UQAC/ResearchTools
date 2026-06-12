---
name: auditthesis
description: "Audit a UQAC Master's or PhD thesis (LaTeX, uqac.cls): front matter compliance, hypothesis flow across all chapters, chapter structure (sujet amené/posé/divisé), reference validation via Scopus, figure/table/equation/acronym audits, LLM-style detection, bilingual résumé/abstract consistency, and UQAC formatting compliance. Produces an executable improvement plan. Trigger on: /auditthesis, requests to audit or improve a thesis, UQAC mémoire audit requests."
---

Launch the `thesis-auditor` agent to audit the following thesis:

$ARGUMENTS

If no argument is provided, use the file currently open in the IDE (should be `main.tex`).
If a directory path is provided, the agent looks for `src/main.tex` inside it.
If a file path is provided, the agent reads that file and follows all `\input{}`/`\include{}` macros recursively to merge the full thesis.

The agent will autonomously run 16 steps:

1. Parse the full thesis structure by merging all chapter files via `\input{}`/`\include{}` (up to 4 levels deep)
1b. Detect the thesis form — classic monograph or article-based (3 accepted papers as chapters) — and record it in the plan header as `[THESIS FORM: MONOGRAPH]` or `[THESIS FORM: ARTICLE-BASED]`; this controls how step 6 runs
2. Audit all front matter elements: title page, jury composition (4–5 members required), French résumé (6 structural components, 250–350 words), English abstract (same), dédicace, remerciements, avant-propos, keywords
3. **Hypothesis flow validation** — the central UQAC check: extract all hypotheses from Chapter 2, trace each one through Chapter 3 (methodology), Chapters 4+ (results), and the Conclusion — flags: `[HYPOTHESIS SECTION MISSING]`, `[HYPOTHESIS NOT TESTABLE]`, `[HYPOTHESIS NOT TESTED: H_N]`, `[HYPOTHESIS NOT VALIDATED: H_N]`, `[HYPOTHESIS NOT CONCLUDED: H_N]`
4. Chapter structure audit — "sujet amené / sujet posé / sujet divisé" and chapter conclusion — flags: `[SUJET AMENE WEAK]`, `[SUJET POSE MISSING]`, `[SUJET DIVISE MISSING]`, `[CHAPTER CONCLUSION MISSING]`, `[CHAPTER TRANSITION MISSING]`
5. Reference audit (all chapters) via Scopus — flags: `[DOI INVALID]`, `[NOT FOUND]`, `[PUBLISHER NOT APPROVED]`, `[LOW IMPACT — Q3/Q4]`, `[REFERENCE NOT INTRODUCED]` (cited paper with no presentation sentence in text), `[INSUFFICIENT REFERENCES]` (< 30 for a mémoire); assigns confidence levels (`[HIGH/MEDIUM/LOW CONFIDENCE]`) with a one-sentence justification written as a LaTeX comment after each entry in the `.bib` file (`% [CONFIDENCE: HIGH] — ...`); temporal distribution histogram; self-citation rate
6. Literature review audit — two branches driven by the thesis form detected in step 1b: (A) monograph: runs the full `scopus-auditor` pipeline (reference validation, coverage-gap analysis, comparison table) on Chapter 2 (Revue de littérature); (B) article-based: runs the same pipeline independently on each paper chapter's "Related Works" section, then generates a cross-paper literature synthesis table that maps thematic clusters across all three papers
7. Methodology audit (Chapter 3) — reproducibility, hypothesis linkage, algorithm French keywords, theorem proofs
8. Results audit (Chapters 4+) — metrics, baselines, hypothesis validation statements, multi-chapter differentiation
9. Figure and table audit — citation, proximity (120-line threshold), 2-sentence description, UQAC chapter-based numbering (Figure N-M), image resolution (≥ 300 DPI for rasters)
10. Equation and acronym audit — every labeled equation referenced and explained, acronym package (`\ac{}`) consistency, undefined/unused/redefined acronyms
11. Abstract consistency check — abstract and résumé quantitative claims cross-checked against the Results chapters; bilingual consistency between French résumé and English abstract
12. LLM usage evaluation — per-chapter and overall AI-style risk score (target < 10 %); detects em dashes, smart quotes, zero-width spaces, AI transition phrases, sentence-length uniformity
13. UQAC formatting compliance — `uqac.cls`, font size, bibliography style (`apa-uqac-fr` etc.), `\opening`/`\maincontent` markers, `soul` package
14. Cross-review via Gemini 2.0 Flash and GitHub Copilot with consensus arbitration
15. Executable improvement plan saved as `<basename>_thesis_audit_plan.md` alongside `main.tex`

The plan has sections:
- Hypothesis flow summary table (H_N × chapters)
- Strengths / Weaknesses
- Section A: Front Matter Issues
- Section B: Hypothesis Flow Issues (always High-priority)
- Section C: Chapter Structure Issues
- Section D: Literature Review Issues — monograph: Chapter 2 audit; article-based: sub-sections D.1/D.2/D.3 per paper + D.X cross-paper synthesis table
- Section E: Reference Issues
- Section F: Methodology Issues
- Section G: Results Issues
- Section H: Figure and Table Issues
- Section I: Equations and Acronyms
- Section J: LLM Usage Assessment (per-chapter scores)
- Section K: Abstract / Résumé Consistency
- Section L: UQAC Formatting Compliance
- Section M: General Critical Assessment (maturity verdict: major revision / minor revision / ready for defence)
- Section N: Cross-Review Log
- Section O: Missing Chapters or Sections

After reviewing the plan, edit it, mark items `[SKIP]`, then ask:
"Execute the thesis audit plan for [path/to/main.tex]"

Changes are applied in the relevant chapter `.tex` files using the `changes` package:
- Added text: `\added[id=AU]{...}`
- Modified text: `\replaced[id=AU]{new text}{old text}`
- Deleted text: `\deleted[id=AU]{...}`
- Original text is never deleted silently

Respond in French unless the thesis is predominantly in English.
