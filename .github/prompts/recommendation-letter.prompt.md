---
description: "Recommendation, support, appreciation, acceptance, and dispense letters"
---

Generate a LAR.i / Prof. Otis letter in LaTeX -> PDF. Read the skill at
`.claude/skills/recommendation-letter/SKILL.md` and follow its workflow.

1. Resolve the candidate files from the arguments (a folder, a list of paths,
   or the file open in the IDE) and extract the facts (GPA, courses,
   publications, project, dates).
2. Elicit the missing context with AskUserQuestion: letter type, language,
   `candidate_status` (applicant / current_student / graduated),
   `funding_provider` for acceptance and dispense, and invitation pairing.
3. For the four authored types (scholarship, academic_position,
   industry_position, appreciation), write the body prose: highlight the
   candidate's dossier AND the professor's own experience with the candidate;
   honest weighing of strengths; style hygiene, AI-usage < 20%. For acceptance
   and dispense, only collect field values (the script owns the fixed wording).
4. Write the JSON config to the scratchpad and run:
   `python .claude/skills/recommendation-letter/scripts/generate_letter.py --config <json> --output out/`
5. Resolve every warning, then deliver the `.tex` and `.pdf` from `out/`.

For an invitation for a new international student, offer both the acceptance and
the dispense letter (`invitation_pair=both`). Never put a real candidate's
personal data into a committed file.

the file(s) or topic given after the command in the chat message (if none was given, use the file currently open in the editor)

Respond in French unless the active file is in English.
