---
name: replyreviewer
description: "Generate point-by-point LaTeX reviewer response letters and apply track-change markup directly in the paper using the changes package (\\added, \\deleted, \\replaced). The reviewer ID in the markup is the direct link between paper modifications and the response letter. One response .tex file per reviewer comment file. Trigger on: /replyreviewer, requests to respond to peer review comments, requests to create author response letters."
---

Launch the `reviewer-response` agent with the following arguments:

$ARGUMENTS

Expected usage:

    /replyreviewer --paper paper.tex --reviewers r1.txt r2.txt --title "Title" --editor "Name"

Arguments:

- `--paper <path.tex>` : path to the original LaTeX paper (required)
- `--reviewers <files>` : one or more reviewer comment files (.txt); first = R1, second = R2, etc. (required)
- `--title "..."` : paper title for the letter header (optional; extracted from `\title{}` if omitted)
- `--editor "..."` : editor name for the salutation (optional; defaults to `[EDITOR NAME]`)

The agent will autonomously:

1. Parse the original paper structure and build a section map for correction targeting
2. Extract and classify all reviewer comments (G grammar, S style, SC scientific, M methodology, R results, D discussion, FT figures/tables, EQ equations, REF references, Q quality, MAJ major revision)
3. Draft a one-paragraph author response for each comment (academic style, AI risk < 10%)
4. Check the paper preamble and add `\usepackage{changes}` with `\definechangesauthor` declarations for each reviewer (R1 blue, R2 red, R3 orange, R4+ purple) if missing
5. Apply corrections directly in the paper: grammar fixes without markup; all other changes with `\added[id=RN]{new}`, `\replaced[id=RN]{new}{old}`, or `\deleted[id=RN]{old}` — the reviewer ID in each command is the direct link between the paper modification and the response letter item
6. Validate every reference proposed for any comment via Scopus (including DOI validation): found with DOI = auto-approved, add to paper and response letter; found without DOI = auto-approved, add everywhere, flag `[NO DOI]`; not found = remove, search for a validated alternative; for every approved reference assign a confidence level (`[HIGH/MEDIUM/LOW CONFIDENCE]`) based on how well the Scopus abstract matches the reviewer's comment context, write a one-sentence justification as a LaTeX comment after each `\bibitem` entry in the response letter (`% [CONFIDENCE: HIGH] — ...`) and after each BibTeX entry in the `.bib` file, and ensure the author response paragraph presents the reference's contribution with at least one sentence
7. Generate one `.tex` response letter per reviewer as `<basename>_response_R<N>.tex`; each specific comment item includes the section reference where the change appears in the paper (e.g., "Section 3.2, paragraph 2 — marked in blue [R1]")
8. Output a summary of all files created, changes applied, and any comments requiring manual review

Response letter structure:

- Formal opening (standard thank-you paragraph addressed to the editor)
- Section 1.1 General Comments
- Section 1.2 Specific Comments (numbered point-by-point: verbatim comment, author response, then paper location reference)
- Section 2 References Added (IEEE style, Scopus-validated, clickable DOI)

After generation, review the `.tex` letter files and edit the author responses as needed.
Once satisfied, remove `\added{}`/`\deleted{}`/`\replaced{}` markup before final submission,
then run `/auditpaper` to verify the cleaned paper.
