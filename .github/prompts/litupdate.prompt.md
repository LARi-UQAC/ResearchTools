---
description: "Incrementally update an existing literature review (from a prior /litreview run) with newly published papers via the litreview-updater agent: windowed Scopus + Consensus search, validation, preemption check (deliberation + scholar-evaluation), and a dated track-changed copy <basename>_up_YYYYMMDD.tex with a CHANGELOG."
---

Launch the litreview-updater agent on the following existing review: the file(s) or topic given after the command in the chat message (if none was given, use the file currently open in the editor)

Pass ONLY the path to the existing review `.tex` and any options (since-date for the search
window, output target, language). Do NOT restate, summarize, or reduce the agent's pipeline:
the agent executes its full contractual pipeline (Steps 0-10) as defined in
.claude/agents/litreview-updater.md, including the mandatory skills extract-futureworks,
extract-statistic, deliberation, and scholar-evaluation, the delta dedup, the publisher/grade
gate, the dated `\added{}` track-changed merge, and the CHANGELOG, ending with the Step 10
checklist.

The agent WILL pause at Step 1a (Scopus.AI manual checkpoint) with status
"PIPELINE-PAUSED @ Step 1a" when run interactively. When it does: relay its prompt menu to the
user verbatim, wait for the user's pasted Scopus.AI output (or an explicit skip), then send it
back to the same agent via SendMessage so it resumes. Never instruct the agent to run without
interruption and never answer the checkpoint yourself. For a scheduled/unattended run, the agent
auto-skips Step 1a with a log line and produces a draft + REVIEW REQUIRED summary instead.

On completion, verify the Step 10 checklist is present and contains no unsanctioned ✗ before
presenting the update to the user. If the checklist is missing or fails, send the agent back to
complete the missing steps instead of reporting the result. Confirm the original review `.tex`
was not modified and that the changes live in the dated `_up_` copy.

Respond in French unless the active file is in English.
