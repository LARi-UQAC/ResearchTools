# Conventions

Specialized agent definitions for this repository live in `.claude/agents/` (one
flat markdown file per agent, YAML frontmatter). When performing a task covered by
one of them (literature review, paper/thesis audit, BibTeX cleaning, reviewer
response, submission check, LaTeX/TiKZ authoring, Word-to-LaTeX conversion), read
the matching `.claude/agents/<name>.md` in full and follow it. The routing table
is in `.claude/CLAUDE.md`. Academic writing rules: validate references against
Scopus, never fabricate DOIs, LaTeX output in `out/`.
