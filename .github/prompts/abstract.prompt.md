---
description: "Extract a paper's own content and draft (or refresh) its abstract, following composition_rules.md; for a UQAC thesis, drafts the Resume (French) + Abstract (English) pair from the same extraction. Trigger on: /abstract, write the abstract, draft the abstract, refresh the abstract."
---

Launch the `abstract-writer` agent on the following paper:

the file(s) or topic given after the command in the chat message (if none was given, use the file currently open in the editor)

If no argument is provided, use the `.tex` file currently open in the IDE.

The agent executes its FULL contractual pipeline as defined in
.claude/agents/abstract-writer.md, including the mandatory self-check (composition_rules.md +
latex-hygiene aiscan) and the overwrite-confirmation pause when an abstract/résumé already exists.
Do not restate or reduce that pipeline here. If the agent pauses for confirmation, relay its
question to the user verbatim and send the answer back via SendMessage to resume.

Deliverables: the paper's `.tex` updated in place with the new abstract (+ résumé for a thesis),
plus `<basename>_abstract_extraction.json` beside it.

