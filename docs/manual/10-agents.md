# Agents

Chapter 10 of the ResearchTools manual. Back to [table of contents](../../README.md).

Agents are specialists Claude delegates to automatically based on context, or explicitly on
request ("use the `scopus-auditor` agent to…"). Fifteen ship in this repo; most back a slash
command. Two of them (`local-writer`, `local-coder`) are local-delegation agents: a cheap
cloud wrapper that drives a local Ollama model over a Bash bridge (see "Local delegation").
Two are loop orchestrators: `authoring-loop` (ScholarEval-gated writing loop) and the
code loop in the `loop-engineer` skill (see "Loop engineering").

Format (repo convention): one flat markdown file per agent at `.claude/agents/<name>.md`,
opening with YAML frontmatter (`name:`, `description:`). This is what Claude Code's subagent
discovery scans; a sub-folder layout is invisible to it. Note the asymmetry with skills,
which ARE folder-based (`skills/<name>/SKILL.md`). The canonical `.claude/agents/` files are
the single source of truth; per-tool mirrors are generated from them (see
"Using the agents outside Claude Code" below).

| Agent | Purpose | Command / trigger | Path |
| --- | --- | --- | --- |
| `scopus-researcher` | Autonomous literature review: search, validate, summarize, PRISMA + gap/coverage/Pareto matrices, hypotheses, LaTeX output | `/litreview` | `.claude/agents/scopus-researcher.md` |
| `litreview-updater` | Incrementally refresh an existing review with new papers: windowed Scopus + Consensus search, delta dedup, validation/grading, preemption check (deliberation + scholar-evaluation), dated `\added{}` copy `_up_YYYYMMDD.tex` + CHANGELOG; unattended draft + REVIEW REQUIRED | `/litupdate` | `.claude/agents/litreview-updater.md` |
| `scopus-auditor` | Audit an existing review; validate every reference; executable improvement plan | `/auditreview` | `.claude/agents/scopus-auditor.md` |
| `paper-auditor` | Full paper content audit (intro→future works) + Scopus validation + ScholarEval score + improvement plan | `/auditpaper` | `.claude/agents/paper-auditor.md` |
| `thesis-auditor` | Full UQAC thesis audit (front matter, hypothesis flow, chapter structure, bilingual consistency, UQAC compliance) + ScholarEval score | `/auditthesis` | `.claude/agents/thesis-auditor.md` |
| `thesis-proposal-auditor` | Audit a UQAC thesis **proposal** (≤35 pages body, testable hypotheses, suggested methodology, no full results) + ScholarEval score | thesis-proposal audit / by name | `.claude/agents/thesis-proposal-auditor.md` |
| `reviewer-response` | Point-by-point response letters + traceable `changes`-package markup in the paper | `/replyreviewer` | `.claude/agents/reviewer-response.md` |
| `bib-cleaner` | Validate, deduplicate, normalize and DOI-enrich a `.bib` file | `/bibclean` | `.claude/agents/bib-cleaner.md` |
| `submit-checker` | Pass/fail submission checklist against a target journal's requirements | `/submitcheck` | `.claude/agents/submit-checker.md` |
| `talk-builder` | Accepted paper → conference talk: six opening questions first, build contract, `talk_model.json`, render (PowerPoint / Beamer / web), then the validate → notes → render → inspect loop until every page is clean | `/talk` | `.claude/agents/talk-builder.md` |
| `word-to-latex` | Faithful Word `.docx` → LaTeX conversion (pandoc + visual-fidelity patches) | `/word2latex` | `.claude/agents/word-to-latex.md` |
| `cover-paper` | Submission package: hidden Cover Letter in source, standalone Title Page PDF, Corresponding Author Profile PDF (recent papers from Scopus), Graphical Abstract via Canva MCP from the paper's figures (Elsevier/Springer spec + FigureLabs prompt) | by name (at submission) | `.claude/agents/cover-paper.md` |
| `narrative-cv-writer` | Draft/refresh/tailor the FRQ / tri-agency narrative CV to one grant competition: refresh the durable master contributions inventory (Scopus AU-ID two-step + `extract-contributions`, plus a grouped question for non-publication items), rank against the competition's own objectives via `cv_select.py`, draft the three sections through `scientific-writing`, render LaTeX/PDF + plain text, self-check the page budget and AI-usage score | `/cv` | `.claude/agents/narrative-cv-writer.md` |
| `thesis-to-paper` | Integrate a thesis + its conference papers into one submission-ready journal manuscript (invited extension); pandoc reference conversion, figure pipeline, content-delta matrix, then `/litreview` + `scientific-writing` + `/bibclean` + `/submitcheck` + `/auditpaper` inline, with a multi-session checkpoint protocol | by name / "extend this paper to a journal version" | `.claude/agents/thesis-to-paper.md` |
| `authoring-loop` | ScholarEval-gated authoring loop: define subject -> author (Fable 5) -> audit with `scholar-evaluation` (Sonnet/Haiku) -> loop to `min_score` or `max_budget` -> record learnings to memory via `local-writer`. Authoring counterpart of the `loop-engineer` code loop | by name / "improve this to a ScholarEval target under a budget" | `.claude/agents/authoring-loop.md` |
| `abstract-writer` | Extract a paper's own content (`extract-paper-idea` skill) and draft or refresh its abstract, grounded in its own contribution/method/results/limitations rather than a paraphrase; for a UQAC thesis, drafts the Résumé (French) + Abstract (English) pair from the same extraction. No citations, no Scopus, no deliberation. Self-checks against `composition_rules.md` + the `latex-hygiene` AI-usage scanner; confirms before overwriting existing content | `/abstract` | `.claude/agents/abstract-writer.md` |
| `latex-writer` | Bilingual LaTeX authoring: papers (IEEE/Springer/Elsevier), Beamer slides, TiKZ diagrams, thesis | by context (writing) | `.claude/agents/latex-writer.md` |
| `local-writer` | High-token repetitive writing (docstrings, comments, Markdown docs, Obsidian summaries) via the resolver's writer-role model over a Bash bridge; NOT LaTeX text authoring | by context / by name | `.claude/agents/local-writer.md` |
| `local-coder` | Local code generation against a spec/failing test, refactor snippets, scaffolds via the resolver's coder-role model over a Bash bridge; no state-changing git | by context / by name | `.claude/agents/local-coder.md` |

The four ScholarEval auditors (`scopus-auditor`, `paper-auditor`, `thesis-auditor`,
`thesis-proposal-auditor`) score the document before writing the plan; after the plan is
executed they re-run the scoring on the revised source and report a before/after ScholarEval
comparison (baseline vs post), hard-gated so execution only completes when the score improves.

## `latex-writer` key rules

- TiKZ: relative positioning only (drawio2tikz-converted figures are the sanctioned absolute-coordinate exception); arrows perpendicular; no overlaps
- References: peer-reviewed only (IEEE, Springer, Elsevier, Taylor & Francis, Cambridge, Wiley, IET, IOP, ACM, MDPI, ASME, ACME, BioMed Central (BMC)); DOI via hyperref; any other publisher needs user confirmation
- Tables: rows = parameters, cols = concepts; bold headers; 10 % grey row shading
- Language: French default for UQAC thesis, English for scientific papers
- Avoid AI-detectable patterns: zero-width spaces, smart quotes, em dashes, perfect parallel lists

## `reviewer-response` key rules

- Reviewer files assigned sequentially: first file = R1, second = R2, etc.
- Grammar-only fixes (G): applied directly, no markup
- Additions `\added[id=RN]{}`, deletions `\deleted[id=RN]{}`, rewrites `\replaced[id=RN]{}{}` (changes package)
- Reviewer colors: R1 blue, R2 red, R3 orange, R4+ purple (`\definechangesauthor`)
- Every proposed reference validated via Scopus; `[NO DOI]` flagged in the summary when applicable

## Local delegation (Ollama subagents)

`local-writer` and `local-coder` cut cloud cost by keeping the top model as orchestrator and
pushing token-heavy generation to local models on the GPU. Each agent runs on a cheap cloud
model (Haiku) that only frames the task and drives a local model over `ollama_bridge.py`,
which speaks Ollama's HTTP API and takes `--role writer` or `--role coder` instead of a model
name; the bulk text or code is generated locally and free. No gateway is used and cloud stays
on your normal subscription auth, so only the small Haiku wrapper spends cloud tokens.

Requirements: Ollama running, and a qualified tag for the role you are about to use
(`model_resolver.py --resolve --role coder`). There is no fallback tag: an unqualified role
is an explicit stop, never a silent substitution of a weaker model. LiteLLM
(`~/.litellm/ollama.yaml`) is optional and only gives the bridge its keep-alive / context
tuning. `local-writer` never authors LaTeX prose (it may add `%` comments only); all
scientific and LaTeX redaction stays with `latex-writer` + `scientific-writing` on the
latest cloud Claude model.

`aider-setup` is a second, separate local-coding lane that needs no Claude Code at all — how it
differs from `local-coder` and the nightly run itself: chapter [06](06-aider-pipeline.md).

## Loop engineering (local-model dev loop)

The `loop-engineer` skill runs a budget-bounded develop-and-improve loop: design → plan →
code → comment → test → review → score → correct, repeating until a composite quality gate
is met or a hard budget cap is hit. It keeps the best cloud model (Fable 5) as
orchestrator/judge, uses cheaper cloud tiers (Opus for plans, Sonnet for execution and
review) for the actions, and delegates code and comments to the local `local-coder` /
`local-writer` agents so the heavy generation is free.

Option contract: `--loop --budget <max_usd> --score <min_score> [--max-iters N]`. The default
stop gate is composite: tests green AND no CRITICAL/HIGH review findings AND aggregate score
`>=` min_score (default 90); a literal 100 is opt-in. The loop also stops on the hard budget
cap, the max-iterations cap, or a no-progress plateau. The score aggregates findings from the
installed reviewers (`/code-review`, `/security-guidance`, `pr-review-toolkit`,
`systematic-debugging`) plus the betterleaks / pip-audit hooks, with security as a hard floor
(any CRITICAL fails the gate regardless of the aggregate). The final merge to a protected
branch is human-gated: the loop stops at "ready to merge" and waits for your confirmation.
The loop diagram and the use-case diagram are in [Architecture.md](../../Architecture.md)
("Layer 5 — Loop engineering").

The same loop applies to writing through the `authoring-loop` agent (the ScholarEval-gated
variant): define a subject, author with an authoring agent (`/litreview`, `latex-writer`,
`/replyreviewer`, …) on Fable 5, audit with the `scholar-evaluation` skill on Sonnet or Haiku
to get a score, loop until the ScholarEval target or the budget is reached, then record the
learnings to memory via `local-writer`. The five steps are documented in the loop-engineer
[SKILL.md](../../.claude/skills/loop-engineer/SKILL.md).

## Obsidian knowledge-capture loop

Both loops read and write the Obsidian vault so learnings persist across iterations and projects
(Claude Code has no cross-project memory of its own; the vault is that broad memory).
`local-writer` is the single, serialized vault writer; `local-coder` reads only and hands it any
learning. Reads happen at plan time (baked into the plan by `brainstorming` / `writing-plans` on
the cloud tiers) and, during a run, only by the local agents (task start, checkpoints, error
recovery); `executing-plans` does not read. Writes land in `10_Projets/<projet>/` logs and
reusable `30_Ressources/` atomic notes through the outbox only - the SessionStart/SessionEnd
`obsidian-outbox-flush.py` hook is the sole write path, never a fallback. The `~/bin/obsidian`
wrapper is for reads. Requires Obsidian open with the CLI enabled. Full design in [docs/contributor-notes.md](../contributor-notes.md)
section 5; routing in [.claude/CLAUDE.md](../../.claude/CLAUDE.md).

## Calling an agent explicitly

Agents are normally triggered automatically by context. To invoke one directly, address it
by name in your message:

```
Use the scopus-auditor agent to audit the review in paper_review/literature_review.tex
```

```
reviewer-response agent: --paper sn-article.tex --reviewers r1.txt --editor "Prof. Yin"
```

The slash commands `/auditreview`, `/replyreviewer`, `/litreview`, etc. are thin wrappers that
call these agents with the same argument syntax — use the commands for convenience and the
explicit agent names when you need finer control or want to chain agents in one message.

## Using the agents outside Claude Code

`install.ps1` regenerates per-tool mirrors from the canonical `.claude/agents/*.md`
files. Run it after adding or editing an agent, then commit the regenerated output. Add
`-Personal` to also copy the Copilot agent profiles to `~/.copilot/agents/`, which makes
them available to Copilot CLI in every project (re-run after agent edits to refresh).

| Tool | Generated target | Notes |
| --- | --- | --- |
| GitHub Copilot (agents) | `.github/agents/<name>.agent.md` | Auto-discovered once on the default branch (GitHub.com agents panel, coding agent, VS Code, Copilot CLI `/agent` or `copilot --agent <name>`). Copilot caps agent prompts at 30,000 characters, so the five large agents ship as stubs that read the canonical file first. |
| GitHub Copilot (commands) | `.github/prompts/<name>.prompt.md` | One prompt file per task command (13); invoke as `/<name>` in Copilot Chat. The Claude session modes (`concis`, `slim`, `focus`, `ctx`) are skipped. |
| GitHub Copilot (rules) | `.github/instructions/<name>.instructions.md` | One per `.claude/rules/*.md`, applied to all files (`applyTo: "**"`), plus the master `.github/copilot-instructions.md` (mission, agent routing, skills pointer). |
| GitHub Copilot (skills) | none needed | Skills are plain repo folders (`.claude/skills/<name>/SKILL.md`); Copilot agents read them directly, and the master instructions point there. |
| OpenCode | `.opencode/agent/<name>.md` | Full body, `description` frontmatter. |
| Continue | `.continue/rules/researchtools.md` | One rule pointing at the canonical files and routing table. |
| Aider | `CONVENTIONS.md` | Pointer paragraph (created once, never overwritten). |
| `AGENTS.md` readers (OpenHuman, Hermes Agent, Codex, and others) | `AGENTS.md` | Distilled master, regenerated on every run; agent list, routing pointer, skills examples, and the cross-cutting rules. |
| Codex (skills) | `.agents/skills/<name>/SKILL.md` | Codex is the one harness with a native skill convention: it scans `.agents/skills` from the working directory up to the repo root. Each mirror is a **pointer** carrying only the frontmatter, since the description is the whole trigger surface and the body it then reads is the canonical file. Descriptions are trimmed to whole sentences to fit Codex's skill-list budget (8000 chars when the context window is unknown); over budget Codex shortens and then omits entries, so the trim is deliberate rather than left to chance. |
| Codex (nested instructions) | `.claude/skills/AGENTS.md` | Codex concatenates one `AGENTS.md` per directory from the git root down to the working directory, later files overriding earlier ones, capped by `project_doc_max_bytes` (32 KiB default). This one adds the script-surface rule for sessions working inside the skills tree. |

For global availability in Claude Code (any working directory), `install-junctions.ps1`
links each `.claude/agents/<name>.md` into `~/.claude/agents/` per file (symlink; hard-link
fallback when Developer Mode is off — re-run after a `git pull` that changes agents).
Skills keep their per-folder junctions.

---
[← 09 ThesisTracker integration](09-thesistracker-integration.md) | [Table of contents](../../README.md) | [11 File locations →](11-file-locations.md)
