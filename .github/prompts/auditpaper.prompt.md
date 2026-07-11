---
description: "Audit a complete scientific paper: references, methodology, results, discussion, future works. Validates all citations against Scopus, flags content issues, runs cross-review via Gemini + GitHub Copilot, and produces an executable improvement plan file. Trigger on: /auditpaper, requests to audit or improve a full paper (not just the literature review)."
---

Launch the `paper-auditor` agent to audit the following paper:

the file(s) or topic given after the command in the chat message (if none was given, use the file currently open in the editor)

If no argument is provided, use the file currently open in the IDE.
If a file path is provided, the agent reads that file (and a sibling `.bib` if it exists).
If text is pasted directly, the agent treats it as the paper content.

The agent executes its FULL contractual pipeline as defined in
.claude/agents/paper-auditor.md, including every mandatory skill invocation
(deliberation, scholar-evaluation, extract-statistic, extract-futureworks, scopus where
applicable). Do not restate or reduce that pipeline here. If the agent returns
"PIPELINE-PAUSED @ ...", relay its request to the user verbatim, then resume the same
agent via SendMessage with the user's answer. On completion, verify the agent's final
checklist before presenting the result; if it is missing or contains an unsanctioned ✗,
send the agent back to complete the missing steps.

Deliverable: an executable improvement plan saved as `<basename>_paper_audit_plan.md`
alongside the source, plus a standalone ScholarEval score report. The plan has sections:
Strengths, Weaknesses, Reference Issues (A), Methodology Issues (B), Results Issues (C),
Discussion Issues (D), Future Works Issues (E), Missing Sections (F), General Critical
Assessment (G), Cross-Review Log (H), Figure and Table Issues (I), LLM Usage Assessment
(J), Equations and Acronyms (K), Abstract Consistency (L), Section Flow Issues (M),
Literature Review Audit (N).

After reviewing the plan, the user can edit it, mark items `[SKIP]`, then ask:
"Execute the paper audit plan for [filename]"

When executed, all changes are marked in LaTeX using the `changes` package:
- Added text (sentences, tables, figures): `\added[id=AU]{...}`
- Modified text: `\replaced[id=AU]{new text}{old text}`
- Deleted text: `\deleted[id=AU]{...}`
- Original text is never deleted silently — always preserved with `\deleted{}` if replaced

Respond in French unless the source paper is predominantly in English.
