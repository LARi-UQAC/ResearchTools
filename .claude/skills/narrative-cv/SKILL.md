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
re-selected for each new competition rather than rebuilt. That folder is the
active profile's `cv.project_dir`; a leading `{{HOME}}` there stands for the
user's home directory, so the tracked profile names no machine path.

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
   rules (R1.7 no semicolon, R1.8 short sentences), applying the funder's
   mechanical rules per item: `*` after every supervised HQP name, one
   clientèle tag, the date/period, and "s.o." rather than padding a genuinely
   non-applicable section. **Bold differs by funder, read it from the
   variant's `citation_rules`:**
   - **FRQ** (`frq_old_portal`, `frq_new_portal`): bold the candidate's name
     and every co-researcher named in the application.
   - **CRSNG / tri-agency** (`tri_agency`): bold **nothing** except a lead
     author who is not listed first (alphabetical authorship). NSERC's own
     words (instructions page dated 2026-01-27): "If the lead author is not
     listed first (e.g., if authorship is alphabetical), bold the lead
     author's name." No rule bolds the candidate or the co-applicants, and
     doing so makes a third author read as the lead author.
   The asterisk rule is the same for both.
5. **Build**: `cv_build.py render` (LaTeX + text), compile, `check-pages`;
   for the old portal, `cv_build.py filename` for the mandatory name. The
   `render` report carries `warnings`: under `tri_agency`, every bolded name
   in a reference is listed for the author to confirm it is a lead author
   not listed first. Model conveniences: `"prose_file": "section1.tex"` keeps
   sections 1 and 3 as LaTeX files beside the model, and a section-2 item's
   `"references": [...]` puts each citation on its own line before the
   description; inside item fields `**Name**` is bold and a DOI URL becomes a
   clickable link.
6. **Self-check**: page budget, `latex-hygiene`'s `aiscan` (< 20% per this
   repo's standard), the composition-rules checklist.
7. **Journal**: dispatch `local-writer` to append one line to the vault's
   `10_Projets/Subventions/<organisme>-<programme>-<année>/Decisions.md`
   (root `CLAUDE.md` Case 4) - never write the vault directly.

Full contractual pipeline, exit checklist, and the AskUserQuestion/overwrite
gates: `.claude/agents/narrative-cv-writer.md`.

## Service mode (/cv/build)

ThesisTracker builds a researcher's CV with consenting students' rows through
`deploy/form-service`'s stateless `POST /cv/build`, which imports `cv_build.py`
through `deploy/form-service/app/cv_bridge.py` (the same pattern
`skill_bridge.py` uses for the PDF routes):

- ThesisTracker sends the **inline** model (no `prose_file`, section `"3"`
  carrying `"hqp_list": true` when it has rows to render) plus the consenting
  students' rows and the reference year; the service returns the LaTeX
  and/or plain text, never a PDF.
- **The PDF and the page-budget check stay local.** The service never
  compiles LaTeX (C2, security: the service is public-reachable and
  compiling network input would let it read server files). Compile and run
  `cv_build.py check-pages` on the professor's own machine as before.
- `cv_build.py inline --model <cv_model.json> --out <file.json>` turns a
  local model that still uses `prose_file` (the normal authoring path above)
  into one with inline `prose`, ready to upload. It refuses an `--out` equal
  to `--model`, and a model whose sections carry `hqp`/`hqp_rows`/`rows` -
  student rows never travel through a file on this skill's side.
- **Student rows are never written to the CV folder**, or anywhere else in
  this skill: `render_hqp`/`validate_hqp_rows` run entirely in memory inside
  the service process, and the consenting rows live only in ThesisTracker.

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

- **Applying the FRQ bold rule to a CRSNG / tri-agency CV.** Measured
  2026-09-27 on a CRSNG Alliance CV: the candidate and a co-researcher were
  bolded in third position, which the tri-agency convention reads as "lead
  author". Under `tri_agency`, bold only a lead author not listed first, and
  treat any `render` warning as a question to answer, not noise.

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
