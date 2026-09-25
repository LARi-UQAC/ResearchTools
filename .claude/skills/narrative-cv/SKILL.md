---
name: narrative-cv
description: "Use when drafting, updating, or tailoring a narrative 'CV descriptif' for a Quebec/Canadian grant competition (FRQ's CV-FRQ, structurally identical to the tri-agency CIHR/NSERC/SSHRC CV commun des trois organismes): three sections (career/skills, up to ten contributions and experiences, supervision and mentoring), matched to one program's own objectives and evaluation criteria. Trigger on: CV-FRQ, CV descriptif, CV trois organismes, narrative CV, tri-agency CV, tailor my CV to this grant, /cv."
allowed-tools: [Read, Write, Edit, Bash, AskUserQuestion]
permissions: [read, write, env, network]
---

# narrative-cv - the FRQ / tri-agency narrative CV

## Overview

FRQ's CV-FRQ and the tri-agency (CIHR/NSERC/SSHRC) "CV commun des trois
organismes" are the SAME format (confirmed 2026-09-25 against both official
pages): three sections, up to ten items in section 2, capped at 6 pages in
French or 5 in English. What differs is only the submission channel's font
and file requirement (see `contribution_types.json`'s `portal_variants`).

This skill is built around a **durable master inventory** rather than a
stateless per-run extraction, because the pain the skill exists to remove is
re-deriving the candidate's best contributions from scratch for every grant.
The inventory lives in the researcher's OWN external project folder (never
inside ResearchTools - R7), grows across grant cycles, and is re-ranked and
re-selected for each new competition rather than rebuilt.

## When to use

- A grant competition (FRQNT/FRQSC/FRQS, CIHR/NSERC/SSHRC, or any program
  that asks for the CV-FRQ / tri-agency narrative CV) needs a tailored CV.
- The candidate's inventory of publications, mentoring, service, awards,
  patents, or other fundable contributions needs refreshing with recent work.
- Not for a standard chronological/academic CV (education, employment,
  full publication list) - that is a different genre with no page cap and no
  relevance-to-one-program framing; this skill is for the FRQ/tri-agency
  narrative form specifically.

## Pipeline (three scripts, one JSON model)

| Stage | Script | Job |
|---|---|---|
| 1 - inventory | `scripts/cv_inventory.py` | CRUD over the master inventory YAML: `init`, `add` (validated, deduplicated by id/DOI), `list`, `stats` (staleness signal), `mark-used`. Never calls Scopus itself - the caller runs `scopus_api.py` and `extract_contributions.py` and hands ONE validated item's JSON to `add`. |
| 2 - select | `scripts/cv_select.py` | Deterministic keyword-overlap ranking of inventory items against a competition's own objectives/evaluation-criteria text. A mechanical SIGNAL only - the final relevance judgment (FRQ's own instruction: content "interprété à la lumière des objectifs... du programme") is the calling agent's, not this script's. |
| 3 - build | `scripts/cv_build.py` | Renders ONE `cv_model.json` to LaTeX (`render_latex`) and a plain-text companion (`render_text`) for the new-FRQnet-portal paste-in channel, builds the mandatory old-portal filename (`filename`, per normes_presentation.pdf), and checks the compiled PDF's page count against the 6/5-page cap (`check-pages`). One model, two renderers, so they cannot drift apart - the same pattern `paper2talk`'s `talk_model.py` uses. |

Data lives in `scripts/contribution_types.json` (R6): the three section
titles (FR/EN, plus the tri-agency's "Déclaration personnelle" label for
section 1), the closed clientele set (milieu académique / milieu de pratique
/ grand public), the closed category set (FRQ's own Annexe list), the 6/5
page budget, and the three portal variants with their font/margin/filename
rules.

## Workflow (driven by the `narrative-cv-writer` agent, `/cv`)

1. **Resolve the target**: competition (organisme-programme-année), language
   (sets the 6 vs 5-page cap), portal variant, and - for the old-portal PDF
   path only - the candidate's FRQ identification number for the filename.
2. **Refresh the inventory**: `cv_inventory.py stats` for staleness, then a
   Scopus AU-ID search (two-step, exactly `cover-paper.md`'s Artifact 3
   pattern: resolve AU-ID first, `--sort recent`, never a bare name or ORCID)
   restricted to the competition's own subject/keywords, `extract-contributions`
   on any newly retrieved paper, `cv_inventory.py add` per new item. Ask the
   user (grouped `AskUserQuestion`) for non-publication items Scopus cannot
   see (new mentees, awards, service, patents, media) since the inventory's
   own `used_in` history shows what a past CV already drew on.
3. **Rank and select**: `cv_select.py` against the competition's objectives/
   criteria text, then the agent's own judgment picks up to 10 for section 2
   and the supporting threads for sections 1 and 3.
4. **Draft the prose** via the `scientific-writing` skill's composition
   rules (R1.7 no semicolon, R1.8 short sentences), applying FRQ's own
   mechanical rules per item: bold the candidate's and co-researchers' names,
   `*` after every supervised HQP name, one clientèle tag, the date/period,
   and "s.o." rather than padding a genuinely non-applicable section.
5. **Build**: `cv_build.py render` (LaTeX + text), compile, `check-pages`;
   for the old portal, `cv_build.py filename` for the mandatory name.
6. **Self-check**: page budget, `latex-hygiene`'s `aiscan` (< 20% per this
   repo's standard), the composition-rules checklist.
7. **Journal**: dispatch `local-writer` to append one line to the vault's
   `10_Projets/Subventions/<organisme>-<programme>-<année>/Decisions.md`
   (root `CLAUDE.md` Case 4) - never write the vault directly.

Full contractual pipeline, exit checklist, and the AskUserQuestion/overwrite
gates: `.claude/agents/narrative-cv-writer.md`.

## Quick reference

| Need | Command |
|---|---|
| Refresh inventory staleness | `python scripts/cv_inventory.py stats --path <inventory.yaml>` |
| Add one validated item | `python scripts/cv_inventory.py add --path <inv.yaml> --from-json <item.json> --yes` |
| Rank against a competition | `python scripts/cv_select.py --inventory <inv.yaml> --criteria-file <objectives.txt> --top 10` |
| Render both outputs | `python scripts/cv_build.py render --model <cv_model.json> --target both --out <basename>` |
| Old-portal filename | `python scripts/cv_build.py filename --surname Otis --frq-id XXXYY1234 --title CVdescriptif` |
| Page-budget check | `python scripts/cv_build.py check-pages --pdf <cv.pdf> --language fr` |

## Common mistakes

- **Treating this as a full chronological CV.** It is not: no education/
  employment history section, no full publication list - only the three FRQ
  sections, and section 2 is capped at 10 items regardless of career length.
- **Re-extracting from scratch each grant.** Defeats the whole point of the
  inventory; run `cv_inventory.py stats` first to see what is already there.
- **Selecting the ten highest-`cv_select.py`-score items unreviewed.** The
  script's score is a keyword-overlap signal, not a final ranking; FRQ's own
  instruction ties relevance to the PROGRAM's objectives, which the agent
  must read, not infer from keyword frequency alone.
- **Assuming the tri-agency PDF is byte-identical to the government's own
  Arial template.** LaTeX substitutes Helvetica for Arial (stated in
  `contribution_types.json`, R14) - visually close, not pixel-identical.
- **Writing the inventory or a CV draft into ResearchTools.** Both belong in
  the researcher's own external project folder (R7); this skill's `scripts/`
  holds only the reusable code.
