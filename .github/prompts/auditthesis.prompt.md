---
description: "Audit a UQAC Master's or PhD thesis (LaTeX, uqac.cls): front matter compliance, hypothesis flow across all chapters, chapter structure (sujet amené/posé/divisé), reference validation via Scopus, figure/table/equation/acronym audits, LLM-style detection, bilingual résumé/abstract consistency, and UQAC formatting compliance. Produces an executable improvement plan. Trigger on: /auditthesis, requests to audit or improve a thesis, UQAC mémoire audit requests."
---

Launch the `thesis-auditor` agent to audit the following thesis:

the file(s) or topic given after the command in the chat message (if none was given, use the file currently open in the editor)

If no argument is provided, use the file currently open in the IDE (should be `main.tex`).
If a directory path is provided, the agent looks for `src/main.tex` inside it.
If a file path is provided, the agent reads that file and follows all `\input{}`/`\include{}` macros recursively to merge the full thesis.

The agent executes its FULL contractual pipeline as defined in
.claude/agents/thesis-auditor.md, including every mandatory skill invocation
(deliberation, scholar-evaluation, extract-statistic, extract-futureworks, scopus where
applicable). Do not restate or reduce that pipeline here. If the agent returns
"PIPELINE-PAUSED @ ...", relay its request to the user verbatim, then resume the same
agent via SendMessage with the user's answer. On completion, verify the agent's final
checklist before presenting the result; if it is missing or contains an unsanctioned ✗,
send the agent back to complete the missing steps.

Deliverable: an executable improvement plan saved as `<basename>_thesis_audit_plan.md`
alongside `main.tex`, with the thesis form recorded in the header as
`[THESIS FORM: MONOGRAPH]` or `[THESIS FORM: ARTICLE-BASED]`. The plan has sections:

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
