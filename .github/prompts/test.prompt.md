---
description: "Run project tests"
---

Run the tests for the active project following the procedure in `.claude/rules/testing.md`.

Steps:

1. Read `.claude/rules/testing.md` to identify exact commands and working directories
2. Identify the correct Python virtual environment (root `.venv` or `cost_estimator_project/.venv` depending on the layer under test)
3. Display the full command before executing it
4. After execution, report: **tests passed / total** — list only failures with their short error message
5. For each failure, propose the most likely cause in one sentence

If the file(s) or topic given after the command in the chat message (if none was given, use the file currently open in the editor) is provided, restrict the run to that specific module or file.

the file(s) or topic given after the command in the chat message (if none was given, use the file currently open in the editor)

