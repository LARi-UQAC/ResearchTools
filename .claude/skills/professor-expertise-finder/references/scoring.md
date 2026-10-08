# Correspondence Score — Rubric (/5)

The total score is the sum of **five subscores**, each worth one of
`scripts/pef_config.json`'s `subscore_values` (currently `0`, `0.5`, or
`1` — see that file for provenance, R0/R6: these are enforced constants,
not a free-text convention). Half-points keep the judgment honest: a
subscore of 0.5 means "present but partial / indirect", never a fudge
factor.

Cluster the user's keywords before scoring (example clusters: application
domain / core method / deployment context / measurement). The subscores are
defined from the clusters, not from a fixed field list:

| # | Subscore | 1 | 0.5 | 0 |
|---|---|---|---|---|
| A | **Application domain** — closeness of the professor's application area to the domain cluster of the keywords (the problem being solved) | The stated expertise or articles target that domain directly | Same family of problems (e.g. surface defects instead of surface contamination), or domain present in only one article | Different application domain |
| B | **Core method** — the main technique cluster of the keywords | Central to the professor's stated research areas | Used regularly but not central, or present in articles only | Absent or unrelated |
| C | **Deployment context** — the context cluster (e.g. robotic / autonomous / in-situ / industrial deployment) | Stated expertise or lab works in that context | Occasional work or transferable setup | No such context |
| D | **Measurement** — quantification, measurement, or uncertainty/reliability estimation related to the keywords | Explicit research theme or measured in the articles | Quantification present without uncertainty, or uncertainty work on a different task | No measurement/uncertainty dimension |
| E | **Verified publications** — the two required articles, recent (`pef_config.json`'s `recent_years_window`) and in an approved-publisher venue, found via the `scopus` skill (SKILL.md Workflow 6) | Both articles verified through Scopus and their own stated contribution (via `extract-contributions`) directly matches the field of the keywords | Both verified, but only one's contribution is direct (the other is adjacent, or full text was unavailable so only Scopus metadata could be checked) | Fewer than two verified in-field articles → the professor is **excluded**, whatever the other subscores |

## Interpretation bands

`scripts/score.py`'s `BANDS` table, 1:1 with this table (provenance: the
professor's own rubric; kept in code as presentation labels over the
total rather than moved into `pef_config.json`, which holds enforced
policy values only):

| Total | Reading |
|---|---|
| 4.5 – 5.0 | Direct expert in the niche |
| 3.5 – 4.0 | Very close — core method + near domain |
| 2.5 – 3.0 | Adjacent — useful, transferable expertise |
| 1.5 – 2.0 | Peripheral — keep only if the location has few candidates, and say so |
| 0 – 1.0 | Do not retain |

`scripts/pef_config.json`'s `retain_threshold` (currently `1.5`) encodes
the floor of this table as an enforced constant: `scripts/score.py`
reports whether a total falls below it, though the skill's own Workflow
step 5 (not this script) decides whether to drop a professor from the
output.

## Rules

1. Score from evidence only: official profile (research areas), the
   Scopus-verified articles' own stated contribution (`extract-contributions`,
   never a guessed title match), lab affiliation — in that order of weight.
2. Always publish the subscores with the total, in the form
   `3.5/5 (A 1, B 1, C 0.5, D 0, E 1)`, plus one sentence of rationale per
   subscore that is not obvious.
3. Compute totals with `scripts/score.py` (validates the subscore values
   and the exclusion rule) — never add them up by hand in prose.
4. Rank by total, descending. Tie-break: higher A, then higher E, then
   alphabetical.
5. The score measures closeness to **this run's keywords** only. It is not
   a quality, reputation, or citation score, and must never be presented
   as one.
