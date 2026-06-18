# Future-works protocol

The canonical pipeline for the `extract-futureworks` skill. The host agent reads this file, runs the
mode that applies, emits the `[FW …]` flags or the corpus artifacts, and folds them into its plan. The
skill never runs a deliberation panel; the host runs deliberation once on its near-final output.

Follow the anti-AI-style rules in
`.claude/skills/scientific-writing/references/writing_principles.md` for all written output (no em
dashes, straight quotes, no zero-width characters, no AI transition phrases, no overly perfect lists).
Target an AI-style risk score below 10%. Respond in the manuscript's language.

The parser (`.claude/skills/extract-statistic/scripts/extract_text.py ... --section-scan`) returns the
future-work / conclusion / limitations / open-problems excerpts per file. Use its `sections` output to
seed each mode, then read the surrounding prose to judge each item. The heading cues are in
[section-cues.md](section-cues.md).

## Mode `audit` - one manuscript's own future works

Input resolution: a `.tex`/`.md` path; for a `.tex` file resolve every `\input{}`/`\include{}`
relative to its directory (append `.tex` if no extension), read each, append with
`% === INCLUDED FROM: filename.tex ===` delimiters, repeat up to 3 levels, and audit the merged
document. List every merged file in the report header.

### Step 1 - Locate and inventory the future-works content

Run `extract_text.py text <merged manuscript> --section-scan`. From the returned `sections`, identify
the future-work statements (a Future Work / Future Directions section, or future-tense sentences inside
the Conclusion). Build a numbered list FW1, FW2, ... with the exact text of each statement.

Flag `[FW MISSING]` if no future-work statement exists anywhere in the conclusion or a dedicated
section - a paper or thesis must state where the work goes next.

### Step 2 - Per-statement testability and specificity audit

For each FW_N:
- `[FW NOT TESTABLE]` if the statement names no method, metric, or experiment by which a follow-up
  could confirm it ("improve the system" with no handle).
- `[FW VAGUE]` if it is a generic aspiration ("explore other applications") with no concrete target.
- `[FW GENERAL KNOWLEDGE]` if it restates a well-known direction with no novel angle.

### Step 3 - Link-to-limitation audit

Each future work should answer a stated limitation. Cross-check the manuscript's Limitations /
Discussion against FW_N. Flag `[FW NOT LINKED TO LIMITATION]` when a future work does not correspond to
any acknowledged limitation, or when a stated limitation has no matching future work.

### Step 4 - Novelty check against the literature

For each FW_N that survives Steps 2-3, verify it is not already done:

```
python ".claude/skills/scopus/scripts/scopus_api.py" search "<future-work topic>" --count 5
```

- `[FW ALREADY EXISTS]` if a Scopus paper demonstrating this exact contribution is found - add a
  `> Reference:` line with the DOI and propose rephrasing the future work as a refinement or a new
  angle. Flag `[SCOPUS UNAVAILABLE]` on a network error and proceed without the reference.

### Step 5 - Hypothesis cross-check (the host's hypothesis gate)

This is why the four auditors embed this skill. Using the corpus future works mined from the cited
references (run mode `mine` over the work's own `.bib`, below), the host:
1. **Validates each hypothesis already stated** in the paper/thesis. A stated hypothesis that the
   corpus repeatedly lists as an open problem is well-grounded; one that the corpus shows is already
   closed is flagged `[FW HYPOTHESIS ALREADY CLOSED]` with the DOI.
2. **Proposes at least one stronger hypothesis** drawn from the corpus future works that the work does
   not yet pursue, each testable by a named method and novelty-checked (Step 4).

The host plan is not final until this validation and at least one corpus-derived improved hypothesis
are written into its hypothesis section (paper-auditor Section E, scopus-auditor Section F1,
thesis / thesis-proposal Section B).

### Output (mode audit)

Save `<basename>_futurework_report.md` next to the manuscript (or `futurework_report_<YYYY-MM-DD>.md`
for pasted text):

```markdown
# Future-Works Report - [source]
Generated: [YYYY-MM-DD]
Skill: extract-futureworks (mode audit)
Files merged: [list]

## Future works stated in the manuscript
| ID | Statement (first 15 words) | Testable | Linked to a limitation | Novelty |
|---|---|---|---|---|

## Flags
- `[FW …]` - description + suggested correction

## Hypothesis validation (from the cited corpus future works)
- H_N: [stated hypothesis] -> [grounded / already closed (DOI)] -> [action]

## Proposed stronger hypotheses (corpus-derived)
- [testable statement] | method | gap it answers | target journal
```

Return the `[FW …]` flag list so the host folds it into its plan.

## Mode `mine` - corpus future works from full text

Input: a `.bib` (preferred) or an existing `refs/` directory.

### Step 1 - Ensure full text, any format

```
python ".claude/skills/scopus/scripts/download_pdf.py" bib "<corpus.bib>" --latex "<main.tex>"
```

Presence-gated; PDF first, then the HTML / Markdown any-format tiers. A paper with no retrievable full
text is left for Step 2 to flag.

### Step 2 - Parse the future-works excerpts

```
python ".claude/skills/extract-statistic/scripts/extract_text.py" bib "<corpus.bib>" --latex "<main.tex>" --section-scan
```

Each record carries `sections` (future-work / conclusion / limitations excerpts) and `format`. A record
with status `pdf-missing` contributes title/abstract-level future works only and is flagged
`[FW FULLTEXT-MISSING]`; it never blocks the pipeline. If no parser backend is available, the mode
degrades to abstract-level future works and records the limitation.

### Step 3 - Synthesize the corpus future-works table

One row per (paper, stated future-work item):

| Paper [cite] | Stated future work | Category | Fit to the review (theme / gap G[N]) | Effort (1-5) | Impact (1-5) |
|---|---|---|---|---|---|

- **Category** is the cue label (future_work / open_problems / limitations / conclusion).
- **Fit to the review** maps the item to a literature-review theme and, where it applies, to a gap
  G[N] (the host supplies the theme/gap context).
- **Effort** and **Impact** are 1-5 judgments by the host: effort to carry out the work, impact on the
  field. Never fabricate a future-work statement; if a paper states none, omit it from the table (do
  not invent rows).

### Step 4 - Pareto 80/20 ranking and the opportunity list

Score each row by a Pareto value (high impact, low effort first; for example `impact / effort` or
`impact + (6 - effort)`) and sort descending, so the cheapest 20% of work that yields about 80% of the
impact rises to the top. Build a **research-opportunity list** from the recurring items: a future work
stated by several papers is a high-value, author-declared gap.

### Output (mode mine)

- `<basename>_corpus_futurework.md` - the ranked table above + the opportunity list (human-readable).
- `<basename>_corpus_futurework.json` - machine-readable, with per-row {citekey, statement, category,
  fit, effort, impact, pareto_score} and the opportunity list, consumed by scopus-researcher.

Route into scopus-researcher Step 9b (gap map), Step 9d (Pareto matrix), and Step 10 (hypotheses): the
top-Pareto rows are the floor for the proposed contributions, and at least one hypothesis plus one
research-project title must be derived from them before the review is complete.

## Flag catalogue

| Flag | Meaning |
|---|---|
| `[FW MISSING]` | No future-work statement in the conclusion or a dedicated section |
| `[FW NOT TESTABLE]` | Statement names no method, metric, or experiment |
| `[FW VAGUE]` | Generic aspiration with no concrete target |
| `[FW GENERAL KNOWLEDGE]` | Restates a well-known direction with no novel angle |
| `[FW NOT LINKED TO LIMITATION]` | Future work / limitation mismatch |
| `[FW ALREADY EXISTS]` | Scopus shows the future work is already demonstrated (DOI given) |
| `[FW HYPOTHESIS ALREADY CLOSED]` | A stated hypothesis is already closed in the corpus (DOI given) |
| `[FW FULLTEXT-MISSING]` | A corpus paper's full text could not be retrieved (abstract-level only) |
| `[SCOPUS UNAVAILABLE]` | Scopus network error during the novelty check |

## Key rules

- Never fabricate a future-work statement or a hypothesis; mark it missing instead.
- Every proposed hypothesis is testable by a named method and novelty-checked against Scopus before it
  is offered.
- Never modify the manuscript directly; corrections go through the host plan or `latex-writer`.
- Do not run a deliberation panel here; the host runs deliberation once on its near-final output.
- Keep all written output below a 10% AI-style risk score.
