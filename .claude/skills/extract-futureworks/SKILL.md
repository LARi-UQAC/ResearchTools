---
name: extract-futureworks
description: "Future-works analysis skill with two modes. Mode audit: review one manuscript's own future-works / conclusion / limitations section (.tex/.md) — presence, testability, link to a stated limitation, and novelty against the literature — and emit flagged findings for the host agent's plan. Mode mine: extract the stated future works / open problems of a corpus from full text (download via download_pdf.py any-format, parse via extract_text.py --section-scan) and synthesize a corpus future-works table (with fit to the review and a Pareto 80/20 effort-vs-impact ranking) plus a research-opportunity list. Used inside the four auditors (audit) and scopus-researcher (mine). Trigger when an agent reaches its future-works / hypothesis step."
---

# Future-works analysis (audit + corpus mining)

A reusable future-works capability invoked by the academic agents. It mirrors the
`extract-statistic` skill: two modes, one input contract each, and a strict boundary — it produces
findings, the host agent judges them through its own deliberation step. The full pipeline and flag
catalogue live in [references/futureworks-protocol.md](references/futureworks-protocol.md); the
heading cues used to locate the relevant passages live in
[references/section-cues.md](references/section-cues.md). Read both before using this skill. This file
is the entry point and contract.

## When to use

- **Mode `audit`** — a host auditor ([paper-auditor](../../agents/paper-auditor.md),
  [scopus-auditor](../../agents/scopus-auditor.md),
  [thesis-auditor](../../agents/thesis-auditor.md),
  [thesis-proposal-auditor](../../agents/thesis-proposal-auditor.md)) reaches its
  future-works / hypothesis step. The skill audits the work's own stated future works and is then used
  to validate the work's hypotheses and to propose stronger ones drawn from the cited corpus.
- **Mode `mine`** — [scopus-researcher](../../agents/scopus-researcher.md) has downloaded the
  corpus full text and wants every paper's stated future works extracted and synthesized, so the gap
  map, the Pareto matrix, and the hypotheses target real, author-declared open problems for the next
  research project.

## When NOT to use

- As a standalone command typed by the user. The skill is invoked by the agents at their future-works
  step, not directly. (It still runs if a user points it at a file, but its outputs feed a host
  pipeline.)
- For broad ideation unanchored to a manuscript or a corpus.

## Cross-review boundary (do not run deliberation here)

This skill does **not** run a deliberation panel and does **not** call `gemini_reviewer.py` or
`github_reviewer.py`. The host agents already run the mandatory [deliberation](../deliberation/SKILL.md)
step once on their near-final output; the findings produced here are merged into the host plan and
critiqued there. This keeps one panel per run.

## Modes

### Mode `audit` — one manuscript's own future works

- **Input:** a `.tex` or `.md` manuscript path. Resolve `\input{}`/`\include{}` recursively (up to 3
  levels) and audit the merged document, exactly as the host auditors merge their input.
- **Pipeline (see the protocol reference):** locate the future-works / conclusion / limitations
  section -> presence check -> per-statement testability and specificity audit -> link-to-limitation
  audit -> novelty check against Scopus -> hypothesis cross-check (validate the work's stated
  hypotheses against the corpus future works and propose stronger ones).
- **Output:**
  - `<basename>_futurework_report.md` next to the manuscript (or
    `futurework_report_<YYYY-MM-DD>.md` in the working directory for pasted text).
  - A list of `[FW …]` flags the host folds into its plan (paper-auditor Section E, scopus-auditor
    Section F1, thesis / thesis-proposal Section B).
- **Never modify the manuscript directly.** Corrections are applied by the host plan / `latex-writer`.

### Mode `mine` — corpus future works from full text

- **Input:** a `.bib` (preferred) or an existing `refs/` directory.
- **Steps:**
  1. Ensure each retained paper's full text is present in any format - call
     `.claude/skills/scopus/scripts/download_pdf.py` (presence-gated; PDF, then the HTML/Markdown
     any-format tiers).
  2. Parse every present file with `scripts/extract_text.py` (`--section-scan` on) to get the
     future-work / conclusion / limitations excerpts per paper.
  3. Synthesize a **corpus future-works table** (one row per stated future-work item: paper,
     statement, category, fit to the review theme/gap, effort 1-5, impact 1-5) and a
     **research-opportunity list** (recurring "X remains future work" across papers = high-value,
     author-declared gap). The host ranks the rows by a Pareto 80/20 score (lowest effort x highest
     impact first).
- **Presence-gated:** a paper whose full text could not be retrieved (status `pdf-missing`)
  contributes title/abstract-level future works only and is flagged `[FW FULLTEXT-MISSING]`; it never
  blocks the pipeline.
- **Output:** `<basename>_corpus_futurework.md` (human-readable ranked table + opportunity list) and
  `<basename>_corpus_futurework.json` (machine-readable, consumed by scopus-researcher). These route
  into scopus-researcher Step 9b (gap map), Step 9d (Pareto matrix), and Step 10 (hypotheses).

## Prerequisites

- A Markdown/PDF backend importable for parsing (Docling preferred, else pymupdf4llm + pymupdf, else
  the HTML tag-strip) - see `.claude/skills/extract-statistic/scripts/requirements.txt`. A missing
  backend degrades to abstract-level future works and flags it.
- For full-text retrieval in `mine` mode: `.claude/skills/scopus/scripts/download_pdf.py` reachable,
  `SCOPUS_API_KEY` for the Elsevier source, and `UNPAYWALL_EMAIL` for the Unpaywall tier (the arXiv /
  PMC / Semantic Scholar tiers work without a key).
- For novelty / hypothesis lookups during the audit: `scopus_api.py` reachable. A network error is
  flagged `[SCOPUS UNAVAILABLE]` and the audit proceeds without references.

## Invocation

```powershell
# Mode audit (host auditor):
python ".claude/skills/extract-statistic/scripts/extract_text.py" text "<manuscript.tex>" --section-scan
# then apply the pipeline in references/futureworks-protocol.md and write <basename>_futurework_report.md

# Mode mine (scopus-researcher / auditor cited-corpus mining):
python ".claude/skills/scopus/scripts/download_pdf.py" bib "<corpus.bib>" --latex "<main.tex>"
python ".claude/skills/extract-statistic/scripts/extract_text.py" bib "<corpus.bib>" --latex "<main.tex>" --section-scan
# then synthesize <basename>_corpus_futurework.md + .json
```

The parser (`extract_text.py`) is shared with `extract-statistic`; this skill reuses its
`--section-scan` output rather than shipping its own script. Pass `--stats-scan --section-scan`
together when an agent mines statistics and future works in the same pass.

## Resources

- `references/futureworks-protocol.md` - the audit + mine pipelines, the `[FW …]` flag catalogue, the
  output format, and the Pareto ranking rule.
- `references/section-cues.md` - the English and French heading cues used to locate the future-work /
  conclusion / limitations / open-problems passages.
- The shared parser `.claude/skills/extract-statistic/scripts/extract_text.py` (`--section-scan`); it
  reuses `download_pdf.py` for any-format retrieval (it does not reimplement downloading).

## Key rules

- Respond in the manuscript's language (French if the manuscript is French, English if English).
- Anti-AI-style hygiene follows `.claude/skills/scientific-writing/references/writing_principles.md`
  (canonical): no em dashes, straight quotes only, no zero-width characters, no AI transition phrases,
  no overly perfect lists. Target an AI-style risk score below 10%.
- Never fabricate a future-work statement or a hypothesis; if the source does not state it, mark it
  missing.
- Every proposed hypothesis must be testable by a named method and validated for novelty against
  Scopus before it is offered (reuse the `scopus_api.py search` pattern).
- The Pareto 80/20 ranking is the host's: this skill supplies the per-paper future-work rows; the host
  scores effort vs impact and maps each row to the review's themes and gaps.
