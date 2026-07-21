---
name: ResearchTools agents
description: Routing to the canonical ResearchTools agent definitions
---

This repository defines specialized academic agents as flat markdown files under
`.claude/agents/` (canonical source of truth). When a task matches one of them,
read the corresponding file in full and follow it exactly:

- `authoring-loop` - see `.claude/agents/authoring-loop.md`
- `bib-cleaner` - see `.claude/agents/bib-cleaner.md`
- `cover-paper` - see `.claude/agents/cover-paper.md`
- `latex-writer` - see `.claude/agents/latex-writer.md`
- `litreview-updater` - see `.claude/agents/litreview-updater.md`
- `local-coder` - see `.claude/agents/local-coder.md`
- `local-writer` - see `.claude/agents/local-writer.md`
- `paper-auditor` - see `.claude/agents/paper-auditor.md`
- `reviewer-response` - see `.claude/agents/reviewer-response.md`
- `scopus-auditor` - see `.claude/agents/scopus-auditor.md`
- `scopus-researcher` - see `.claude/agents/scopus-researcher.md`
- `submit-checker` - see `.claude/agents/submit-checker.md`
- `thesis-auditor` - see `.claude/agents/thesis-auditor.md`
- `thesis-proposal-auditor` - see `.claude/agents/thesis-proposal-auditor.md`
- `thesis-to-paper` - see `.claude/agents/thesis-to-paper.md`
- `word-to-latex` - see `.claude/agents/word-to-latex.md`

The task-to-agent routing table lives in `.claude/CLAUDE.md` (section "Tooling").
