---
applyTo: "**"
---

# Workflows

Common task flows in this workspace. Each maps a goal to the command, the agent it drives,
and the output produced. Full arguments are in `README.md`.

## Research and writing flows

| Goal | Command | Agent / skill | Output |
|---|---|---|---|
| Literature review on a topic | `/litreview <topic>` | `scopus-researcher` | Structured review, PRISMA + gap/coverage/Pareto matrices, hypotheses, BibTeX |
| Find or validate one reference | `/scopus`, `/ref` | `scopus` skill | Validated metadata, formatted reference, clickable DOI |
| Audit an existing review | `/auditreview [file]` | `scopus-auditor` | Reference validation + executable improvement plan |
| Audit a complete paper | `/auditpaper [file]` | `paper-auditor` (+ `scholar-evaluation`) | Track-change markup plan + ScholarEval score |
| Audit a UQAC thesis | `/auditthesis [main.tex]` | `thesis-auditor` | Front-matter, hypothesis-flow, and formatting audit plan |
| Audit a UQAC thesis proposal | by name | `thesis-proposal-auditor` | Proposal-specific audit plan (<=35 pages body) |
| Clean a `.bib` | `/bibclean [file.bib]` | `bib-cleaner` | Cleaned `.bib` + report (dedup, DOI enrichment, SJR) |
| Respond to reviewers | `/replyreviewer ...` | `reviewer-response` | One letter per reviewer + traceable `changes` markup |
| Check submission readiness | `/submitcheck <tex> <journal>` | `submit-checker` | Pass/fail submission checklist |
| Build a submission package | by name | `cover-paper` | Hidden cover letter, title page PDF, author profile PDF, graphical abstract (Canva MCP + FigureLabs prompt) |
| Convert Word to LaTeX | `/word2latex <docx>` | `word2latex` skill / `word-to-latex` | Faithful `.tex` matching the `.docx` |

## LaTeX maintenance

- Validate TiKZ figures with `/tikz` before committing them (anchoring, perpendicular
  arrows, no overlaps, TiKZiT compatibility).
- Diagnose and fix LaTeX build errors with `/latex` (reads `out/*.log` first, cites the
  failing line, states whether a two-pass recompilation is needed).

## Calling an agent explicitly

Agents are normally triggered by context. To invoke one directly, address it by name, for
example: "Use the `scopus-auditor` agent to audit the review in `literature_review.tex`."
The slash commands are thin wrappers over these agents.

## Documentation maintenance

After a substantive change, update the relevant doc and verify that links resolve. Keep
`README.md` and `Architecture.md` as the authoritative inventory; do not duplicate their
tables into `.claude/CLAUDE.md`.

## Environments

Use the correct virtual environment for the layer you are working in, and run the relevant
tests manually before pushing (see `testing.md`). There is no CI/CD pipeline.
