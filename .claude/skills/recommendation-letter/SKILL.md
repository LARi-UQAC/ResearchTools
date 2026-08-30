---
name: recommendation-letter
description: >
  Generate support, recommendation, appreciation, acceptance, and dispense
  (short-stay invitation) letters for a supervisor's students and candidates,
  in LaTeX compiled to PDF, signed by the active profile's author. Ingests the
  candidate's own files
  (CV, transcript, project description, motivation letter) and highlights both
  the candidate's dossier and the professor's own experience with the
  candidate. Trigger on: recommendation letter, support letter, appreciation
  letter, acceptance letter, invitation letter, dispense / work permit
  exemption letter, lettre d'appui, lettre de recommandation, lettre
  d'appreciation, lettre d'acceptation, lettre d'invitation, lettre de
  dispense, PFLA, ELAP, CRSNG, FRQNT, MITACS, or /recommendation-letter.
allowed-tools: [Read, Write, Edit, Bash, AskUserQuestion, Glob]
---

# Recommendation Letter Generator

Two generation tracks, six letter types. All output goes to `out/`.

- Authored track (`scholarship`, `academic_position`, `industry_position`,
  `appreciation`; French or English): Claude writes the body prose, the Python
  script wraps it in the shared scaffold.
- Form track (`acceptance`, `dispense`; French only): the script fills a fixed
  administrative template from the config fields. Do not paraphrase the fixed
  wording (objet line, immigration paragraph).

The script `scripts/generate_letter.py` is standard-library only (no pip
install). `pdflatex` compiles the PDF; if absent, the `.tex` is still produced.

## Candidate status (drives how the candidate is named)

- `applicant`: admission candidate, not yet a student -> "le candidat / M. X".
- `current_student`: on the team, not graduated -> "X, etudiant(e) au <programme>".
- `graduated`: degree completed -> "le Dr X" / "Dr. X" (uses candidate_title).

## Funding provider (acceptance / dispense)

- `supervisor`: the professor funds via an organism (MITACS, CRSNG, FRQNT,
  BEFM, internal RA/TA).
- `candidate`: the candidate's own funding (external scholarship, or
  self / family funded).
- `combination`: both.

## Workflow

1. Ingest candidate files from `$ARGUMENTS` (a folder or a list of paths):
   CV, transcript, project description, motivation letter. Extract GPA, course
   names, publications, project facts, dates. Read PDFs/text directly.
2. Elicit gaps with AskUserQuestion:
   - Round 1 context: `letter_type`, `language`, `target`, `target_institution`,
     `limit`, `reference_number`; for form types also `invitation_pair` and
     `funding_provider`.
   - Round 2 profile: `candidate_name`, `candidate_gender`, `candidate_status`,
     `candidate_title`, `candidate_program`.
   - Round 3 type-specific fields, plus a question for the professor's own
     experience / relationship with the candidate (authored track).
   Pre-fill from the ingested files; ask only what is missing or uncertain;
   mark anything unknown `[A COMPLETER]`.
3. Confirm a JSON summary of all fields with the user before generating.
4. Author `body_tex` (authored track only): a direct opening verdict, the
   candidate's dossier highlights, a distinct paragraph on the professor's own
   experience, an honest weighing of strengths, and a closing offer of
   availability. Follow `references/quality-patterns.md`. Style hygiene: no em
   dash, straight quotes, no invisible characters (AI-usage < 20%). Never
   fabricate a grade, a publication, or a funding amount; leave `[A COMPLETER]`.
5. Generate: write the config to a scratchpad JSON and run
   `python .claude/skills/recommendation-letter/scripts/generate_letter.py --config <json> --output out/`.
6. Read the warnings (placeholder, over-limit, status/title mismatch, style
   hygiene, 120-day). Fix the body or fields and re-run as needed.
7. Deliver the `.tex` and `.pdf` from `out/` (two of each when
   `invitation_pair=both`).

## Notes

- The two form types reproduce the exact administrative wording; the script
  owns it. Do not rewrite the immigration paragraph.
- The dispense letter subject keeps "MOINS DE 120 JOURS" even when the stay is
  longer (the work-permit exemption threshold is the reference); the script
  warns and appends the extra immigration clause.
- All shipped eval / test data is synthetic (`Candidat Exemple ...`). Never
  commit a real candidate's personal data to the repository.