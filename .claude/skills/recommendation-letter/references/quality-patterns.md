# Quality patterns for authored letters

Claude reads this when writing `body_tex` for the authored track
(`scholarship`, `academic_position`, `industry_position`, `appreciation`).
The two form types (`acceptance`, `dispense`) do not use this file; their
wording is fixed in the script.

## Replicate

1. Direct opening verdict: the first sentence states the relationship and a
   clear recommendation. Do not bury it.
2. Quantified claims: back each assertion with a number or a named example
   (impact factor, GPA, project name, number of students supervised).
3. Named funding sources: CRSNG, FRQNT, MITACS, FRQ-NT by name where relevant.
4. The professor's own experience: one concrete paragraph on working with the
   candidate (a difficult project handled, a result delivered, a course
   co-taught), distinct from the candidate's self-presentation. This is what
   separates a real recommendation from a summary of the dossier.
5. Future collaboration: the closing names planned co-supervision,
   co-authorship, or a joint grant where applicable.
6. Availability: offer to provide further information.
7. Specific course names and levels, not "he taught courses" but "he taught
   Human-Robot Interaction at the graduate level".

## Avoid

1. Generic superlatives without evidence.
2. Repeating the same point across paragraphs.
3. Passive voice that weakens the recommendation.
4. Skills listed without context.
5. Paragraphs longer than eight sentences.
6. Leftover placeholder text or `[A COMPLETER]` tokens in the final letter.
7. Em dashes, smart quotes, invisible characters, or stray markdown
   (`**`, `#`). Keep the AI-usage score under 20%.

## Candidate reference by status

- `applicant`: "le candidat / M. X" (French) or "the candidate X" (English).
  Never call an applicant "etudiant".
- `current_student`: "X, etudiant(e) au <programme>".
- `graduated`: "le Dr X" / "Dr. X".

## Honesty

Never fabricate a grade, a publication, a funding amount, or an anecdote. If a
fact is not in the candidate's files or supplied by the professor, leave it as
`[A COMPLETER]` for the professor to fill. A support or recommendation letter
carries the professor's signature; its claims must be verifiable.