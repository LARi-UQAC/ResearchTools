---
description: "Check whether a LaTeX paper meets the submission requirements of a target journal. Verifies page count, required sections, reference style, abstract length, keywords, figure count, and anonymization. Produces an executable submission checklist. Trigger on: /submitcheck, requests to check paper readiness for submission to a specific journal."
---

Launch the `submit-checker` agent to check submission readiness:

the file(s) or topic given after the command in the chat message (if none was given, use the file currently open in the editor)

Provide both the source file path and the target journal name, separated by a space, for example:
`/submitcheck paper.tex "IEEE Transactions on Industrial Informatics"`

If no journal is specified, the agent will ask for it before proceeding.

The agent executes its FULL contractual pipeline as defined in
.claude/agents/submit-checker.md, including every mandatory skill invocation
(deliberation, scholar-evaluation, extract-statistic, extract-futureworks, scopus where
applicable). Do not restate or reduce that pipeline here. If the agent returns
"PIPELINE-PAUSED @ ...", relay its request to the user verbatim, then resume the same
agent via SendMessage with the user's answer. On completion, verify the agent's final
checklist before presenting the result; if it is missing or contains an unsanctioned ✗,
send the agent back to complete the missing steps.

Deliverable: `<basename>_submit_<journal-slug>.md` saved alongside the source file, with
the journal profile (publisher, SJR quartile, CiteScore), a detailed pass/fail checklist,
a lightweight ScholarEval readiness score, and prioritized "Actions Required" /
"Actions Recommended" lists.

Respond in French unless the source paper is predominantly in English.
