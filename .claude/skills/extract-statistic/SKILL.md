---
name: extract-statistic
description: "Statistical analysis skill with two modes. Mode audit: review the statistics of one manuscript (.tex/.md) — test selection, assumptions, effect size, presentation, and cross-validation between text, tables, and figures — and emit flagged findings for the host agent's plan. Mode mine: extract the reported statistics from the full-text PDFs of a corpus (download via download_pdf.py, parse via extract_text.py) and synthesize a corpus statistics table plus a statistical-improvement opportunity list. Used inside paper-auditor and thesis-auditor (audit) and scopus-researcher (mine). Engineering-default domain profiles with a selectable cosmetic profile. Trigger when an agent reaches its statistical-audit or corpus-statistics step."
---

# Statistical analysis (audit + corpus mining)

A reusable statistical-analysis capability invoked by the academic agents. It has two modes, one
input contract each, and a strict boundary: it produces findings, the host agent judges them through
its own deliberation step. The full pipeline and flag catalogue live in
[references/statistical-audit-protocol.md](references/statistical-audit-protocol.md); the domain
checks live in [references/domain-profiles.md](references/domain-profiles.md). Read both before using
this skill. This file is the entry point and contract.

## When to use

- **Mode `audit`** — a host auditor ([paper-auditor](../../agents/paper-auditor/AGENT.md),
  [thesis-auditor](../../agents/thesis-auditor/AGENT.md)) has parsed a manuscript and reaches its
  statistical-audit step. The skill audits every statistical claim already in that manuscript.
- **Mode `mine`** — [scopus-researcher](../../agents/scopus-researcher/AGENT.md) has downloaded the
  corpus PDFs (Step 3b-PDF) and wants the reported statistics of those papers extracted and
  synthesized, so the gap map, Pareto matrix, and hypotheses target real statistical and
  methodological improvement opportunities for the next research project.

## When NOT to use

- As a standalone command typed by the user. The skill is invoked by the agents at their statistical
  step, not directly. (It still runs if a user points it at a file, but its outputs are designed to
  feed a host pipeline.)
- On a thesis proposal: a proposal carries no results, so [thesis-proposal-auditor] does not embed it.
- For broad statistical methodology tutoring unanchored to a manuscript or a corpus.

## Cross-review boundary (do not run deliberation here)

This skill does **not** run a deliberation panel and does **not** call `gemini_reviewer.py` or
`github_reviewer.py`. The host agents already run the mandatory [deliberation](../deliberation/SKILL.md)
step once on their near-final output; the statistical findings produced here are merged into the host
plan and critiqued there. This is the single place cross-review happens — keeping one panel per run.

## Modes

### Mode `audit` — one manuscript's own statistics

- **Input:** a `.tex` or `.md` manuscript path (+ a sibling `.bib`, + an optional `data/` folder for
  ground-truth cross-validation). Resolve `\input{}`/`\include{}` recursively (up to 3 levels) and
  audit the merged document, exactly as the host auditors merge their input.
- **Pipeline (see the protocol reference):** statistical inventory -> test-selection audit ->
  effect-size / power audit -> result-presentation audit -> cross-validation (text vs tables vs
  figures vs `data/`) -> domain checks for the active profile.
- **Domain profile:** `--profile engineering` (default) or `--profile cosmetic`, or auto-detected
  from the manuscript (see [references/domain-profiles.md](references/domain-profiles.md)).
- **Output:**
  - `<basename>_stats_report.md` next to the manuscript (or `stats_report_<YYYY-MM-DD>.md` in the
    working directory for pasted text).
  - A list of `[STATS …]` flags the host folds into its plan (paper-auditor Section C subsection,
    thesis-auditor Section G).
- **Never modify the manuscript directly.** Corrections are applied by the host plan / `latex-writer`.

### Mode `mine` — corpus statistics from full-text PDFs

- **Input:** a `.bib` (preferred) or an existing `refs/` directory / `refs/_manifest.json`.
- **Steps:**
  1. Ensure each retained paper's PDF is present — call
     `.claude/skills/scopus/scripts/download_pdf.py` (presence-gated; skips PDFs already in `refs/`).
  2. Parse every present PDF with `scripts/extract_text.py` (`--stats-scan` on) to get text, tables,
     and statistics candidates.
  3. Synthesize a **corpus statistics table** (dominant datasets + sample sizes, methods, metrics,
     evaluation protocols, reported effect / accuracy deltas) and a **statistical-improvement
     opportunity list** (for example: no paper reports variance over seeds; accuracy used on
     imbalanced data; no significance test on model-vs-model deltas; no effect size on benchmark
     gains).
- **Presence-gated:** a paper whose PDF failed to download (listed in `refs/_failed.md`) contributes
  title/abstract-level statistics only and is flagged `[STATS PDF-MISSING]`; it never blocks the
  pipeline.
- **Output:** `<basename>_corpus_stats.md` (human-readable table + opportunity list) and
  `<basename>_corpus_stats.json` (machine-readable, consumed by scopus-researcher). These route into
  scopus-researcher Step 9b (gap map), Step 9d (Pareto contribution columns), and Step 10
  (hypotheses).

## Prerequisites

- PyMuPDF importable for `mine` mode PDF parsing - `pymupdf4llm` (LLM-ready Markdown, tables inline)
  and `pymupdf` (structured `find_tables`); both AGPL-3.0 (see `scripts/requirements.txt`, audited with
  pip-audit). A missing import disables PDF parsing; the mode degrades to abstract-level stats and
  flags it.
- For PDF retrieval in `mine` mode: `.claude/skills/scopus/scripts/download_pdf.py` reachable, and
  `SCOPUS_API_KEY` for the Elsevier source (the Semantic Scholar open-access fallback works without
  it).
- For reporting-guideline / standard lookups during the audit: `scopus_api.py` reachable. A network
  error is flagged `[SCOPUS UNAVAILABLE]` and the audit proceeds without references.

## Invocation

```powershell
# Mode audit (host auditor):
python ".claude/skills/extract-statistic/scripts/extract_text.py" text "<manuscript.tex>" --stats-scan
# then apply the pipeline in references/statistical-audit-protocol.md and write <basename>_stats_report.md

# Mode mine (scopus-researcher, after Step 3b-PDF):
python ".claude/skills/scopus/scripts/download_pdf.py" bib "<corpus.bib>" --latex "<main.tex>"
python ".claude/skills/extract-statistic/scripts/extract_text.py" bib "<corpus.bib>" --latex "<main.tex>" --stats-scan
# then synthesize <basename>_corpus_stats.md + .json
```

## Resources

- `scripts/extract_text.py` — PDF / HTML / plaintext extraction + a statistics-candidate scan; reuses
  `download_pdf.py` for retrieval (it does not reimplement downloading).
- `scripts/requirements.txt` — `pymupdf4llm` + `pymupdf` floors with the pip-audit and AGPL note.
- `references/statistical-audit-protocol.md` — the six-step audit pipeline, flag catalogue, output
  format, and key rules.
- `references/domain-profiles.md` — the `engineering` (default) and `cosmetic` domain-check profiles
  and the auto-detection rule.

## Key rules

- Respond in the manuscript's language (French if the manuscript is French, English if English).
- Anti-AI-style hygiene follows `.claude/skills/scientific-writing/references/writing_principles.md`
  (canonical), not an inline copy: no em dashes, straight quotes only, no zero-width characters, no AI
  transition phrases, no overly perfect lists. Target an AI-style risk score below 10%.
- Never fabricate a statistic, a p-value, or a sample size; if the source does not state it, mark it
  missing.
- Do not flag a stylistic preference (SD vs SEM) unless it is inconsistent within the manuscript or
  violates the stated protocol.
- Domain flags apply only when the relevant study type is detected (the active profile gates them).
