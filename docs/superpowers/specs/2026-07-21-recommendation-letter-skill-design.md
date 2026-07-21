# Design spec - `recommendation-letter` skill

Date: 2026-07-21
Status: approved (brainstorming), pending implementation plan
Author: Martin Otis (with Claude Code)

## 1. Purpose

A new ResearchTools **skill** `recommendation-letter`, invoked by a single
`/recommendation-letter` command, that generates professional letters in
LaTeX -> PDF for Prof. Martin Otis / LAR.i. It ingests a candidate's own
files (CV, transcript, project description, motivation letter), extracts the
facts, and writes a letter that highlights **both** the candidate's dossier
**and** the professor's own experience with the candidate. Output goes to
`out/` per the repo writing standard.

It is a **skill, not an agent**: a reusable, script-backed, user-invoked
capability (per `docs/authoring-and-mirrors.md` section 5). It does not run
the auditor/researcher pipeline machinery (no Scopus, no deliberation, no
ScholarEval) because a letter is not a scientific manuscript. The repo
style-hygiene rules and the AI-usage < 20 % gate still apply to any authored
prose.

## 2. Scope and non-goals

In scope:

- Six letter types across two generation tracks (section 4).
- Candidate-file ingestion and fact extraction.
- Candidate-status-driven titling (applicant / current_student / graduated).
- Funding-provider modelling (supervisor-provided vs candidate-secured).
- Paired acceptance + dispense generation for new international students.
- A stdlib-only Python scaffold/validator script with offline unit tests.
- All inventory + mirror updates (README, Architecture, routing table,
  workflows, `install.ps1`, regenerated Copilot/OpenCode/Continue/Aider
  mirrors).

Non-goals:

- No `requirements.txt` / `pip-audit` surface: the script is standard library
  only (zero third-party dependency, zero CVE surface). `pdflatex` is an
  external tool with graceful degradation.
- No Obsidian plan-mode case or vault journaling: letters are not among the
  six vault cases in the root `CLAUDE.md`.
- The repo-root `CLAUDE.md` is generated from `CLAUDE.template.md` and is not
  edited here. The routing table lives in `.claude/CLAUDE.md`.
- No French-named command file (`lettre-invitation.md`): it breaks the
  English-only definition-file convention. French triggering is carried by
  the SKILL.md `description`.
- `latex-writer` / `scientific-writing` are not invoked: a letter is
  professional correspondence, not IMRAD prose.

## 3. Architecture overview

```
/recommendation-letter  ->  recommendation-letter skill
                                |
              +-----------------+------------------+
              |                                    |
     Authored track                        Form track
  (scholarship, academic_position,     (acceptance, dispense)
   industry_position, appreciation)     fixed FR templates +
   Claude writes body_tex;              conditional blocks +
   script scaffolds + validates         %%GENDER_E%% placeholders;
                                        script assembles from fields
              |                                    |
              +-----------------+------------------+
                                |
                    generate_letter.py  (stdlib only)
                    scaffold, escape, candidate-ref, funding
                    paragraph, dates, word/page count,
                    style-hygiene lint, pdflatex 2-pass -> out/
```

The two tracks share preamble, letterhead, signature, date formatting,
escaping, word/page counting, the style-hygiene linter, and compilation.
They differ only in how the letter **body** is produced: authored (a
Claude-written `body_tex` field) versus template-filled (embedded template +
conditional-block assembly).

## 4. Letter types

| `letter_type` | Track | Language | Purpose |
|---|---|---|---|
| `scholarship` | authored | fr / en | Lettre d'appui for a scholarship / research stay |
| `academic_position` | authored | fr / en | Recommendation for a faculty position |
| `industry_position` | authored | fr / en | Recommendation for an industry position |
| `appreciation` | authored | fr / en | Lettre d'appréciation |
| `acceptance` | form | fr only | Confirms admission into LAR.i (MSc / PhD / research stay) |
| `dispense` | form | fr only | Invitation, short research stay < 120 days, work-permit exemption |

`acceptance` and `dispense` are standardized administrative forms; their exact
wording (objet line, immigration paragraph, tabular fields) must be
reproduced, so they are template-filled, not authored.

## 5. Candidate status and reference

`candidate_status` drives how the candidate is named:

| Value | Meaning | Reference (fr) | Reference (en) |
|---|---|---|---|
| `applicant` | Admission candidate, **not yet a student** | «le candidat» / «M./Mme <Nom>» | "the candidate" / "Mr./Ms. <Name>" |
| `current_student` | On the team, not yet graduated | «<Nom>, étudiant(e) au <programme>» | "<Name>, a student in the <program>" |
| `graduated` | Degree completed | «le Dr <Nom>» / «Pr <Nom>» (uses `candidate_title`) | "Dr. <Name>" / "Prof. <Name>" |

`derive_candidate_reference(config)` returns the canonical string, gender-aware
(étudiant / étudiante). The script emits a warning on mismatch: `graduated`
without a doctoral title, or `current_student` / `applicant` carrying `Dr.`.

For `acceptance`, the candidate is an `applicant` (admission confers student
status): the fixed template's «l'étudiant%%GENDER_E%%» / «futur directeur de
recherche» wording applies once accepted. In authored-track letters an
`applicant` is never called «étudiant».

## 6. Funding model

New dimension `funding_provider`, evaluated first:

| Value | Meaning |
|---|---|
| `supervisor` | The professor provides funding via an organism (MITACS, CRSNG, FRQNT, BEFM, internal RA/TA, ...) |
| `candidate` | The candidate secured their own funding (external scholarship, or self / family funded) |
| `combination` | Both sources |

`funding_model` is the mechanism, extended for the candidate side:

- Supervisor side: `mitacs_acceleration`, `mitacs_gra`, `mitacs_bso`, `befm`,
  `internal`, `combination`.
- Candidate side: `scholarship` (external, e.g. PFLA / ELAP), `self_funded`
  (parents / personal).

`build_funding_paragraph(config)` branches on `funding_provider` first:

- `supervisor` -> «je confirme un financement de <montant> via <organisme> ...»
  assembled from the MITACS / BEFM / internal blocks in the integration doc.
- `candidate` -> «<candidate_reference> assure son propre financement via
  <bourse externe | financement personnel> ...».
- `combination` -> both, supervisor part then candidate part.

If nothing resolves, the paragraph is `[À COMPLÉTER : détails du financement]`
and a warning is printed.

## 7. JSON config schema

Shared / context fields:

```
letter_type, language, target, target_institution, limit, reference_number,
date, candidate_name, candidate_gender (M|F),
candidate_status (applicant|current_student|graduated),
candidate_title, candidate_program
```

Authored track adds:

```
body_tex          # the Claude-authored LaTeX-safe body (salutation -> closing)
```

Plus the authored-track content fields carried from the base plan
(`relationship`, `academic_results`, `project_description`, `candidate_tasks`,
`research_env`, `stay_dates`, `deliverables`, `co_supervisor`,
`scholarship_subtype`, `research_achievements`, `teaching_experience`,
`involvement`, `personal_qualities`, `future_collaboration`,
`technical_skills`, `management_experience`, `contribution`, `impact`). These
inform Claude's authoring and may seed `body_tex`; the script does not need
them once `body_tex` is present.

Form track (acceptance / dispense) adds:

```
invitation_pair (both|acceptance_only|dispense_only),
funding_provider (supervisor|candidate|combination),
degree_level (msc|phd|phd_eng|research_stay),
lab_collaborators, funding_model, funding_amount, funding_source_details,
mitacs_reference, partner_company, partner_description, project_end_date,
prerequisites, publication_requirements, additional_funding, tools_technologies,
candidate_address, stay_start (YYYY/MM/DD), stay_end (YYYY/MM/DD),
remuneration, weekly_hours (default 40), home_institution,
position_title (default "Chercheur(e) invité(e)"), tasks_description,
conditional_scholarship (true|false), conditional_scholarship_name
```

Fields irrelevant to a given `letter_type` are ignored. Missing required
fields become `[À COMPLÉTER]` placeholders + a stderr warning; exit 0.

## 8. `generate_letter.py` responsibilities (stdlib only)

CLI: `--config CONFIG [--output out/] [--no-compile] [--strict]`.

Shared services:

- Assemble PREAMBLE + LETTERHEAD(lang) + body + SIGNATURE(lang). Letterhead
  and signature are the Otis / LAR.i blocks (from the base plan, section 5.2 /
  5.3).
- LaTeX-escape scalar fields only (never `body_tex` or the fixed templates,
  which are already LaTeX-safe).
- Date formatting: fr «Le 27 mars 2026», en "March 27, 2026"; dispense header
  «Chicoutimi, le 4 mars 2026»; tabular dates normalised to `YYYY/MM/DD`.
- Word count of the body; page count from the compiled PDF
  (`/Type /Page` scan).
- `%%GENDER_E%%` and the other gender placeholders (section 9) applied last.
- **Style-hygiene linter** enforcing `.claude/CLAUDE.md`: flags U+200B / U+200C
  / U+200D, U+2026, em / en dash, U+E0000-E007F tags, smart quotes, stray
  `**` / `#`. `--strict` turns any hit into a non-zero exit.
- `candidate_reference` derivation (section 5) and status/title mismatch
  warning.
- `funding_provider`-aware `build_funding_paragraph` (section 6).
- `pdflatex` 2-pass compile to `out/`, aux (`.aux/.log/.out`) cleanup;
  graceful degradation with a message if `pdflatex` is absent.

Authored track: wrap `body_tex` between the assembled header
(date + subject + salutation) and the signature.

Form track: select `TEMPLATE_ACCEPTANCE_FR` or `TEMPLATE_DISPENSE_FR`, resolve
conditional blocks (`%%DEGREE_DESCRIPTION%%`, `%%LAB_COLLABORATORS_SENTENCE%%`,
`%%MITACS_OPPORTUNITY_SENTENCE%%`, `%%FUNDING_PARAGRAPH%%`,
`%%PREREQUISITES_PARAGRAPH%%`, `%%PROJECT_DETAILS_PARAGRAPH%%`,
`%%CONDITIONAL_PARAGRAPH%%`, `%%IMMIGRATION_PARAGRAPH%%`), then fill scalars.

Paired output: `invitation_pair == both` -> emit
`letter_<surname>_acceptance.tex` and `letter_<surname>_dispense.tex`, compile
both, report both word/page counts.

Immigration paragraph: the standard work-permit-exemption text
(`IMMIGRATION_PARAGRAPH_STANDARD`); the conditional-scholarship sentence, when
present, precedes it. If `stay_end - stay_start > 120` days, print a warning
and append the extra immigration-validation clause before the final period.
The subject line keeps "MOINS DE 120 JOURS" (the exemption threshold is the
reference), per the integration doc.

## 9. Gender placeholders (form track)

| Placeholder | M | F |
|---|---|---|
| `%%GENDER_E%%` | (empty) | `e` |
| `%%GENDER_CELUI%%` | `celui-ci` | `celle-ci` |
| `%%GENDER_HEUREUX%%` | `heureux` | `heureuse` |
| `%%GENDER_IL%%` | `Il` | `Elle` |
| `%%GENDER_DE_ETUDIANT%%` | `de l'étudiant` | `de l'étudiante` |
| `%%SALUTATION%%` | `Monsieur,` | `Madame,` |

`%%GENDER_E%%` is applied after all other placeholders as a plain string
replacement.

## 10. Skill workflow (SKILL.md)

1. **Ingest** - resolve candidate files (folder or paths from `$ARGUMENTS`):
   CV, transcript, project description, motivation letter. Extract GPA,
   courses, publications, project facts, dates.
2. **Elicit gaps** - Round 1 context (letter_type, language, target, limit,
   for form types `invitation_pair` and `funding_provider`); Round 2 candidate
   profile (incl. `candidate_status`); Round 3 type-specific, including a
   question for the professor's own experience/relationship with the
   candidate (authored track) and the acceptance/dispense field sets (form
   track). Pre-fill from ingested files; ask only what is missing or
   uncertain; flag `[À COMPLÉTER]`.
3. **Confirm** - JSON summary + `candidate_reference` preview + resolved
   funding provider.
4. **Author body** (authored track only) - Claude writes `body_tex`: opening
   verdict, candidate dossier highlights, the professor's own experience,
   honest weighing of strengths, closing + availability; style-hygiene
   compliant.
5. **Generate** - write config to the scratchpad JSON, run
   `generate_letter.py --config <json> --output out/`.
6. **Validate and fix** - read warnings (style-hygiene, limits, placeholders,
   status/title mismatch, 120-day); edit and re-run as needed.
7. **Deliver** - `.tex` + `.pdf` in `out/` (two of each when `both`).

## 11. Error handling and validation

- Invalid JSON -> error with the parse detail, exit 1.
- Missing required fields -> `[À COMPLÉTER]` placeholders + warnings, exit 0.
- `pdflatex` failure -> print the last 20 log lines, still deliver `.tex`,
  exit 0.
- `pdflatex` absent -> info message, `.tex` only, exit 0.
- Warnings (stderr): placeholder present, over word/page limit, missing
  pillar (authored academic letters), status/title mismatch, funding
  unresolved, stay > 120 days, candidate-name accent sanity.

## 12. Testing (offline, stdlib, no network, no model, no pdflatex)

`.claude/skills/recommendation-letter/scripts/Test/test_generate_letter.py`:

- Config parse and schema tolerance.
- LaTeX escaping of scalar fields; `body_tex` and fixed templates left intact.
- `derive_candidate_reference` for the status x gender matrix
  (applicant / current_student / graduated, M / F).
- FR / EN date formatting; dispense header format; tabular date normalisation.
- `build_funding_paragraph` branching for supervisor / candidate / combination
  and each `funding_model`.
- Gender placeholder resolution, `%%GENDER_E%%` in `accepté` / `invité`.
- 120-day duration logic (< 120, = 120, > 120: warning + extra clause).
- Paired generation (`both` -> two tex targets, `--no-compile`).
- Style-hygiene linter catches em dash / zero-width / smart quotes / stray
  markdown, and `--strict` exit code.
- `[À COMPLÉTER]` detection.

Eval configs in `evals/` (from the integration doc, accents corrected):
`test_scholarship_fr.json`, `test_academic_en.json`, `test_academic_fr.json`,
`test_acceptance_msc.json`, `test_acceptance_phd.json`,
`test_acceptance_female.json`, `test_dispense.json`,
`test_dispense_conditional.json`, `test_both_pair.json`, plus `evals.json`.

## 13. File layout

```
.claude/skills/recommendation-letter/
  SKILL.md
  scripts/
    generate_letter.py
    Test/
      test_generate_letter.py
  references/
    quality-patterns.md         # authored-track patterns + anti-patterns
  evals/
    evals.json
    test_scholarship_fr.json
    test_academic_en.json
    test_academic_fr.json
    test_acceptance_msc.json
    test_acceptance_phd.json
    test_acceptance_female.json
    test_dispense.json
    test_dispense_conditional.json
    test_both_pair.json
.claude/commands/recommendation-letter.md
```

## 14. Inventory and mirror updates

Per `docs/authoring-and-mirrors.md` sections 7-9 and the `adding-a-skill-checklist`
memory. Counts today: 10 skills, 15 agents, 19 commands.

- **README.md**: skills 10 -> 11 in the three count spots (header "N skills",
  the "N ship" sentence, File-Locations "(N skills)"); add the skills-table
  row; add a `### recommendation-letter` subsection; add a Prerequisites row
  (`pdflatex`); add the File-Locations tree entry and fix the connector on the
  previous last skill. Commands 19 -> 20 (header, File-Locations count,
  Commands-table row, tree, fix previous connector).
- **Architecture.md**: skill inventory 10 -> 11; add the command node and a
  `command -> skill` edge in the mermaid graph (no agent); note it is omitted
  from the command -> agent -> skill matrix.
- **.claude/CLAUDE.md** "Tooling" routing table: add the row (the only
  discoverability path for a skill in Copilot / OpenCode / Continue).
- **.claude/rules/workflows.md**: add a Research-and-writing flow row.
- **install.ps1**: add the skill to the Copilot skills-pointer sentence.
- Run `.\install.ps1 -Profile engineering` to regenerate `.github/`,
  `.opencode/`, `.continue/`, `CONVENTIONS.md`. Commit the canonical change and
  the regenerated mirrors together.

Verify: `rtk grep -n "recommendation-letter" .claude/CLAUDE.md README.md
Architecture.md .github/copilot-instructions.md .github/prompts/
.continue/rules/researchtools.md`.

## 15. Open questions

None blocking. The base-letter templates (scholarship / academic / industry /
appreciation) are authored, so only their structure specs and the two form
templates (acceptance / dispense, reproduced from the 11 real letters via the
integration doc) need to be embedded.
