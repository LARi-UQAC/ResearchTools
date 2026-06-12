---
name: litreview
description: "Launch the scopus-researcher agent for a full autonomous literature review on a given topic. The agent searches Scopus, validates all references, extracts abstracts, and produces a structured review with BibTeX."
---

Launch the `scopus-researcher` agent to perform a complete literature review on the following topic:

$ARGUMENTS

Delegate this task fully to the agent. It will autonomously:

1. Search Scopus for relevant papers (targeting ≥10 results)
2. Retrieve and validate metadata for each result: title, authors, journal, DOI
3. Extract and summarize each abstract in 2–3 sentences
4. Group findings into 3–5 thematic clusters
5. Produce a structured review with `[N]` inline citations
6. Output a numbered reference list and a BibTeX block for LaTeX use

Do not interrupt the agent mid-pipeline. Report the full completed review when done.

Respond in French unless the topic or the retrieved papers are predominantly in English.
