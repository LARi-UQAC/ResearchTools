---
description: "Launch the scopus-researcher agent for a full autonomous literature review on a given topic. The agent searches Scopus, validates all references, extracts abstracts, and produces a structured review with BibTeX."
---

Launch the scopus-researcher agent on the following topic: the file(s) or topic given after the command in the chat message (if none was given, use the file currently open in the editor)

Pass ONLY the topic and any output target (file, section, language). Do NOT restate,
summarize, or reduce the agent's pipeline: the agent executes its full contractual
pipeline (Steps 0-17) as defined in .claude/agents/scopus-researcher.md, including the
mandatory skills extract-statistic, extract-futureworks and deliberation, the PRISMA
diagram, gap map, coverage and Pareto matrices, hypotheses and traceability matrix,
ending with the Step 16 checklist.

The agent WILL pause at Step 1a (Scopus.AI manual checkpoint) with status
"PIPELINE-PAUSED @ Step 1a". When it does: relay its prompt menu to the user verbatim,
wait for the user's pasted Scopus.AI output (or an explicit skip), then send it back to
the same agent via SendMessage so it resumes. Never instruct the agent to run without
interruption and never answer the checkpoint yourself.

On completion, verify the Step 16 checklist is present and contains no unsanctioned ✗
before presenting the review to the user. If the checklist is missing or fails, send the
agent back to complete the missing steps instead of reporting the result.
