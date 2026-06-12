# LaTeX diagnosis and fix

Diagnose and fix the LaTeX problem described or visible in the file open in the IDE.

Procedure:

1. If a `.log` file exists in `out/`, read it first to identify errors with exact line numbers
2. For each error: cite the problematic line, explain the cause in one sentence, apply the fix directly in the file
3. Priority checks:
   - `\resizebox` or `\scalebox` wrapping a `tikzpicture` that uses the `backgrounds` library → replace with `transform canvas` or reduce node dimensions
   - `\\` inside a TikZ node with `text centered` style → change to `align=center`
   - `\addcontentsline` placed after `\lstlistoflistings` → swap order
   - Missing packages → add to preamble
4. After fixing, state whether a two-pass recompilation is needed (required when cross-references change)

Read only the files strictly necessary for the diagnosis.
Fix directly — do not ask "would you like me to...".
Respond in French.

$ARGUMENTS
