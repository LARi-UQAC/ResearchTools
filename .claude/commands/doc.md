# Generate documentation

Generate or update documentation for: $ARGUMENTS

Read `.claude/rules/code-style.md` if present, then apply the project conventions:

**Python**:

- Module docstring: `"""Module name — Stage N. Short description."""`
- Function docstring: Purpose / Inputs / Outputs format, 8 lines max
- Logger: `logging.getLogger(__name__)` with `[MODULE]` prefix tags

**C# / Blazor**:

- `/// <summary>` only for non-trivial public members
- Reference relevant doc file: `/// See docs/ui/component-patterns.md`

**LaTeX / Markdown**:

- No redundant headings or exhaustive lists
- Equations: `$...$` inline, `$$...$$` display block

**Universal rule**:

- Never explain WHAT the code does — names already do that
- Document only WHY: hidden constraints, subtle invariants, bug workarounds
- No task-reference comments ("added for flow Y") — those belong in the commit message

Write the documentation directly without narrating your approach.
Respond in French unless the active file or codebase is in English.
