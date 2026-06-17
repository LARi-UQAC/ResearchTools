# Statistical audit protocol

The canonical pipeline for the `audit` mode of the `extract-statistic` skill. The host agent reads
this file, runs the six steps over the merged manuscript, emits the `[STATS …]` flags, and writes the
report. The domain step (Step 6) defers to [domain-profiles.md](domain-profiles.md) for the active
profile. The `mine` mode reuses Steps 1, 3, and 4 over each corpus PDF and then synthesizes across
papers (see the SKILL.md `mine` contract).

Follow the anti-AI-style rules in
`.claude/skills/scientific-writing/references/writing_principles.md` for all written output (no em
dashes, straight quotes, no zero-width characters, no AI transition phrases, no overly perfect lists).
Target an AI-style risk score below 10%.

## Input resolution

1. A `.tex`/`.md` path: read it. For a `.tex` file, read the sibling `.bib` (same directory, same
   basename) if present.
2. Several paths (for example `main.tex tables.tex`): read all, treat as one manuscript.
3. Empty input: use the file open in the IDE; if none, ask for the manuscript path.
4. A `data/` folder beside the manuscript: scan it for `.csv`, `.xlsx`, or `.R` files and read them as
   ground truth for cross-validation (Step 5).

**CLAUDE.md:** read the project `CLAUDE.md` first when present; it may state the study design, declared
hypotheses, and expected statistical approaches that ground the audit.

**Recursive include resolution:** after reading the main `.tex`, resolve every `\input{...}` and
`\include{...}` relative to its directory (append `.tex` if no extension), read each, and append it
with `% === INCLUDED FROM: filename.tex ===` delimiters on both ends. Repeat up to 3 levels. Audit the
merged document. List every merged file in the report header.

The parser script (`scripts/extract_text.py text <file> --stats-scan`) returns a first pass of
statistics candidates (p-values, sample sizes, named tests, effect sizes, ML metrics) with context;
use it to seed Step 1, then verify each candidate by reading the surrounding prose.

## Pipeline

Execute all steps without stopping to ask.

### Step 1 - Statistical inventory

List every statistical element and map each to its location (section, paragraph, table, figure):
- Descriptive: means, medians, SD, SEM, IQR, ranges, n per group.
- Inferential tests named: t-test, ANOVA, Kruskal-Wallis, Mann-Whitney, chi-square, Fisher,
  correlation, regression.
- Post-hoc tests: Tukey, Bonferroni, Dunn, Scheffe.
- Effect sizes: Cohen's d, eta-squared, omega-squared, r, OR, RR.
- Confidence intervals.
- Alpha threshold (default assumption alpha = 0.05 if unstated - flag it).
- Sample sizes per group (n).
- Software / package named (R, SPSS, GraphPad, SAS, Python/scipy, PyTorch, etc.).

### Step 2 - Test-selection audit

For each inferential test, verify appropriateness:
- **Parametric (t-test, ANOVA, Pearson)** - flag `[STATS ASSUMPTION UNVERIFIED]` if the manuscript
  does not mention normality (Shapiro-Wilk, K-S, Q-Q, or n >= 30 per group with CLT justification),
  homogeneity of variance (Levene, Bartlett, Brown-Forsythe), and independence of observations.
- **ANOVA** - flag `[STATS POST-HOC MISSING]` if a significant ANOVA has no post-hoc test.
- **Multiple comparisons** - flag `[STATS MULTIPLE TESTING UNCORRECTED]` if >= 3 pairwise comparisons
  lack correction (Bonferroni, FDR/BH, or equivalent).
- **Repeated measures** - flag `[STATS SPHERICITY UNVERIFIED]` if RM-ANOVA omits Mauchly's test or a
  Greenhouse-Geisser correction.
- **Correlation vs causation** - flag `[STATS CAUSATION OVERCLAIM]` if a correlation is described with
  causal language ("causes", "induces", "leads to") without an experimental design.
- **Non-parametric substitution** - flag `[STATS NON-PARAMETRIC UNJUSTIFIED]` if a non-parametric test
  is used on n > 30 without a documented normality violation.

### Step 3 - Effect-size and power audit

For each significant result (p < alpha):
- `[STATS EFFECT SIZE MISSING]` if no effect size accompanies the p-value.
- `[STATS POWER ANALYSIS MISSING]` if Methods has no sample-size justification.
- `[STATS MARGINAL SIGNIFICANCE]` if p is between 0.05 and 0.10 yet called "significant" or "a
  tendency".
- `[STATS LARGE N SIGNIFICANCE]` if n > 100 and very small effects are reported as significant without
  a relevance discussion.

Recommend the standard effect-size metric per test:

| Test | Recommended effect size |
|---|---|
| t-test | Cohen's d |
| One-way ANOVA | eta-squared or omega-squared |
| Chi-square | Cramer's V |
| Correlation | r-squared |
| Regression | R-squared, f-squared |
| Non-parametric | rank-biserial r |

**Scopus support:** if `[STATS POWER ANALYSIS MISSING]` or `[STATS EFFECT SIZE MISSING]` is raised,
look up domain reporting guidelines to back the recommendation:

```
python ".claude/skills/scopus/scripts/scopus_api.py" search "<domain> sample size power analysis reporting" --count 3
python ".claude/skills/scopus/scripts/scopus_api.py" search "<domain> effect size reporting guideline" --count 3
```

Add a `> Reference:` line with the DOI and a one-sentence justification under the flag. Flag
`[SCOPUS UNAVAILABLE]` on network error and proceed without references.

### Step 4 - Result-presentation audit

Scan every numerical value in text, tables, and figures:
- `[STATS FORMAT INCONSISTENT]` if the manuscript mixes `mean ± SD` and `mean ± SEM` without
  distinguishing them, uses different decimal precision for the same value type, or mixes percentage
  with and without decimals.
- `[STATS P-VALUE FORMAT]` if exact p-values are not reported (writing "p < 0.05" instead of "p =
  0.023", except "p < 0.001" which is acceptable), or p-values appear without their test statistic (F,
  t, chi-square, U, H).
- `[STATS CI MISSING]` if proportions, means, or effect sizes are reported without a 95% CI in an
  applied or clinical context.
- `[STATS N PER GROUP MISSING]` if only a total N is given for a multi-group comparison.

### Step 5 - Cross-validation: text vs tables vs figures vs data

For every value that appears in more than one place:
- Compare exactly (allowing for rounding).
- `[STATS VALUE MISMATCH: text vs Table X]` or `[STATS VALUE MISMATCH: text vs Figure X]` on a
  discrepancy.
- `[STATS FIGURE LEGEND INCOMPLETE]` if a figure shows error bars without stating SD, SEM, or 95% CI
  in its legend.

If `data/` files are available, recompute reported means, SDs, and n and flag `[STATS DATA MISMATCH]`
when a computed value differs by more than rounding error (tolerance: ±0.01 for means, ±1 for n). If
absent, state in the report: "Cross-validation against raw data was not possible - `data/` folder not
found or empty".

### Step 6 - Domain-specific checks

Apply the checks for the active profile from [domain-profiles.md](domain-profiles.md):
- `engineering` (default) - ML/DL evaluation, control/signal, robotics.
- `cosmetic` - SPF/photoprotection, microbiome, sensory/clinical.

Select the profile from `--profile`, else auto-detect from the manuscript (rules in the profiles
file); default `engineering`. Domain flags fire only when the relevant study type is detected.

## Output

**Annotated report** - save as `<basename>_stats_report.md` next to the manuscript, or
`stats_report_<YYYY-MM-DD>.md` in the working directory for pasted text.

```markdown
# Statistical Audit Report - [source]
Generated: [YYYY-MM-DD]
Skill: extract-statistic (mode audit, profile <engineering|cosmetic>)
Files merged: [list]

## Summary
- Statistical claims identified: N
- Flags raised: N
- Critical issues (test selection, value/data mismatch): N
- Presentation issues (format, missing CI, p-value format): N
- Domain-specific issues: N

## Critical Issues
### [Section / Table / Figure]
- `[STATS FLAG]` - description
- Suggested correction: ...

## Presentation Issues
### [Reference]
- `[STATS FLAG]` - description + suggested correction

## Domain-Specific Issues
### [Reference]
- `[STATS FLAG]` - description

## Effect Size Summary
[Table: test -> reported effect size -> recommended metric -> status]

## Cross-Validation Log
[Table: value -> text location -> table/figure/data location -> match status]

## Recommended Actions (Priority Order)
1. Critical - must fix before submission
2. Important - reviewer likely to raise
3. Minor - good practice
```

For each unambiguous `[STATS VALUE MISMATCH]` or `[STATS FORMAT INCONSISTENT]`, include the corrected
LaTeX snippet under a `### Suggested LaTeX correction` subsection, ready to paste.

When invoked by a host auditor, also return the flag list so the host folds it into its plan
(paper-auditor Section C subsection, thesis-auditor Section G). Do not run a deliberation panel here -
the host runs deliberation once on its near-final plan.

## Key rules

- Respond in the manuscript's language.
- Never modify the manuscript directly - produce the report only; corrections go through the host plan
  or `latex-writer`.
- Never fabricate a statistic, p-value, or sample size; mark it missing instead.
- Do not flag a stylistic preference (SD vs SEM) unless it is inconsistent within the manuscript or
  violates the stated protocol.
- Domain flags apply only when the relevant study type is detected.
- Keep the report below a 10% AI-style risk score.
