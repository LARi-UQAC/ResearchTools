---
description: "Audit an existing review text: validate all references against Scopus, flag errors, analyze coverage gaps, and produce an executable improvement plan file. Trigger on: /auditreview, requests to validate or improve an existing review, reference checking requests."
---

Launch the `scopus-auditor` agent to audit the following review:

the file(s) or topic given after the command in the chat message (if none was given, use the file currently open in the editor)

If no argument is provided, use the file currently open in the IDE.
If a file path is provided, the agent reads that file (and a sibling `.bib` if it exists).
If text is pasted directly, the agent treats it as the review content.

The agent executes its FULL contractual pipeline as defined in
.claude/agents/scopus-auditor.md, including every mandatory skill invocation
(deliberation, scholar-evaluation, extract-statistic, extract-futureworks, scopus where
applicable). Do not restate or reduce that pipeline here. If the agent returns
"PIPELINE-PAUSED @ ...", relay its request to the user verbatim, then resume the same
agent via SendMessage with the user's answer. On completion, verify the agent's final
checklist before presenting the result; if it is missing or contains an unsanctioned ✗,
send the agent back to complete the missing steps.

Deliverable: an executable improvement plan saved as `<basename>_improvement_plan.md`
alongside the source. The plan has sections: Strengths, Weaknesses, Text Improvements (A),
Reference Improvements (B), Coverage Gaps (C), Comparison Table (D), General Critical
Assessment (E), Academic Novelty Checklist (F), Recent Papers Novelty Check (G).

After reviewing the plan, the user can edit it, mark items `[SKIP]`, then ask:
"Execute the improvement plan for [filename]"

When executed, all changes are marked in LaTeX using the `changes` package:
- Added text (sentences, tables, figures): `\added[id=AU]{...}`
- Modified text: `\replaced[id=AU]{new text}{old text}`
- Deleted text: `\deleted[id=AU]{...}`
- Original text is never deleted silently — always preserved with `\deleted{}` if replaced

Respond in French unless the source text is predominantly in English.
