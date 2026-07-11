---
description: "Generate point-by-point LaTeX reviewer response letters and apply track-change markup directly in the paper using the changes package (\\added, \\deleted, \\replaced). The reviewer ID in the markup is the direct link between paper modifications and the response letter. One response .tex file per reviewer comment file. Trigger on: /replyreviewer, requests to respond to peer review comments, requests to create author response letters."
---

Launch the `reviewer-response` agent with the following arguments:

the file(s) or topic given after the command in the chat message (if none was given, use the file currently open in the editor)

Expected usage:

    /replyreviewer --paper paper.tex --reviewers r1.txt r2.txt --title "Title" --editor "Name"

Arguments:

- `--paper <path.tex>` : path to the original LaTeX paper (required)
- `--reviewers <files>` : one or more reviewer comment files (.txt); first = R1, second = R2, etc. (required)
- `--title "..."` : paper title for the letter header (optional; extracted from `\title{}` if omitted)
- `--editor "..."` : editor name for the salutation (optional; defaults to `[EDITOR NAME]`)

The agent executes its FULL contractual pipeline as defined in
.claude/agents/reviewer-response.md, including every mandatory skill invocation
(deliberation, scholar-evaluation, extract-statistic, extract-futureworks, scopus where
applicable). Do not restate or reduce that pipeline here. If the agent returns
"PIPELINE-PAUSED @ ...", relay its request to the user verbatim, then resume the same
agent via SendMessage with the user's answer. On completion, verify the agent's final
checklist before presenting the result; if it is missing or contains an unsanctioned ✗,
send the agent back to complete the missing steps.

Deliverables: one `.tex` response letter per reviewer, saved as
`<basename>_response_R<N>.tex`, plus the paper annotated with traceable track-change
markup (`\added[id=RN]{...}`, `\replaced[id=RN]{new}{old}`, `\deleted[id=RN]{...}`) — the
reviewer ID in each command is the direct link between the paper modification and the
response letter item — and a summary of all files created, changes applied, and any
comments requiring manual review.

Response letter structure:

- Formal opening (standard thank-you paragraph addressed to the editor)
- Section 1.1 General Comments
- Section 1.2 Specific Comments (numbered point-by-point: verbatim comment, author response, then paper location reference)
- Section 2 References Added (IEEE style, Scopus-validated, clickable DOI)

After generation, review the `.tex` letter files and edit the author responses as needed.
Once satisfied, remove `\added{}`/`\deleted{}`/`\replaced{}` markup before final submission,
then run `/auditpaper` to verify the cleaned paper.
