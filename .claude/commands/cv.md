# Narrative CV (CV-FRQ / CV des trois organismes)

Draft, refresh, or tailor the narrative "CV descriptif" to a grant competition, via the
`narrative-cv-writer` agent and the `narrative-cv` skill.

Procedure:

1. Resolve from `$ARGUMENTS` (or ask, grouped, if missing): the competition
   (organisme-programme-année), a path or pasted text for the competition's own objectives and
   evaluation criteria, the target language (`fr` = 6-page cap, `en` = 5-page cap), and the
   portal variant (`frq_old_portal`, `frq_new_portal`, or `tri_agency`).
2. Delegate to the `narrative-cv-writer` agent, which runs the full contractual pipeline: refresh
   the durable master contributions inventory (Scopus + `extract-contributions` for
   publications, a grouped question for non-publication items), rank it against the
   competition's own objectives via `cv_select.py`, draft the three FRQ sections through the
   `scientific-writing` skill, build the LaTeX/PDF and plain-text outputs via `cv_build.py`, and
   self-check the page budget and AI-usage score.
3. `--refresh-only` runs Step 2 of the pipeline (inventory refresh) with no draft produced -
   useful right after a new publication or award, so the inventory stays current between grants.

The inventory and every drafted CV live in the active profile's `cv.project_dir`
(`profiles/<active>.yaml`), never inside this repository.

Report the output paths, the final page count against the cap, every sanctioned skip, and the
agent's own ✓/✗ exit checklist. Respond in French unless the active file is in English.

$ARGUMENTS
