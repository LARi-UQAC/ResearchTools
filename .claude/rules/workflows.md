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
| Integrate a thesis + conference papers into one journal manuscript | by name / "extend this paper to a journal version" | `thesis-to-paper` | Submission-ready journal `.tex` (+ sections, refs, PDF), content-delta matrix, disclosure letter; multi-session checkpoint protocol |
| Iterate a manuscript/review to a target ScholarEval score under a budget | by name / "improve this to a ScholarEval target" | `authoring-loop` (author on Fable 5, audit with `scholar-evaluation` on Sonnet/Haiku) | Improved `.tex` + per-iteration ScholarEval scores, `authoring-loop-log.md`, learnings written to memory by `local-writer` |
| Convert Word to LaTeX | `/word2latex <docx>` | `word2latex` skill / `word-to-latex` | Faithful `.tex` matching the `.docx` |

## Local delegation flows

Keep the top cloud model as orchestrator and push token-heavy generation to local models on
the GPU. Each local agent runs on a cheap cloud model (Haiku) that frames the task and drives
a local model over a Bash bridge (`ollama run`); the bulk output is generated locally and
free. No gateway; cloud stays on the normal subscription auth.

| Goal | Agent | Model | Output |
|---|---|---|---|
| Docstrings, code comments, Markdown docs, CHANGELOG, Obsidian summaries | `local-writer` | haiku wrapper + local `ornith:9b` (bridge) | Rule-compliant text written to the target file |
| Code against a spec/failing test, refactor snippets, scaffolds | `local-coder` | haiku wrapper + local `qwen3.5:9b` (bridge) | Minimal, style-matched code edits |
| Budget-bounded develop-and-improve loop | `loop-engineer` skill (`/loopdev`) | Fable 5 orchestrates; Opus plans; Sonnet executes/reviews; local agents generate | Branch + PR at the human merge gate, `PROCESS.md` + score ledger |

Bridge rule: the local model sees only the prompt (no repo, no conversation), so every rule
constraint and input must be in the prompt; write it to a scratchpad file and run
`rtk ollama run <model> "$(cat <file>)"`. Until the 9B models are imported the bridge falls
back to `qwen2.5-coder:7b`. LiteLLM (`~/.litellm/ollama.yaml`) is optional (keep-alive /
context tuning only).

LaTeX boundary: `local-writer` may add `%` comments in a `.tex` file but never authors
LaTeX or scientific prose - that stays with `latex-writer` + `scientific-writing` on the
latest cloud Claude model.

Loop-engineering stop gate (default, composite): tests green AND no CRITICAL/HIGH review
finding AND aggregate score `>=` min_score (default 90). Hard stops: budget cap
(`--budget`), max iterations, or a no-progress plateau. Security is a hard floor (any
CRITICAL fails the gate). Merge to a protected branch is human-gated; local agents never
merge on their own. See `Architecture.md` "Layer 5 - Loop engineering" for the loop and
use-case diagrams.

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
