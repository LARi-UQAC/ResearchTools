---
description: "Professor Expertise Finder"
---

Find university professors closest to a set of expertise keywords, via the
`professor-expertise-finder` agent and skill.

Procedure:

1. Resolve from `the file(s) or topic given after the command in the chat message (if none was given, use the file currently open in the editor)`, or ask (grouped, in this order, per the skill's
   "ask, never assume" rule): the **search location** (a country, a
   country + province/state/region, a city, or worldwide — never a default),
   then the **expertise keywords** and the ranking scope (global top N, or
   best per university).
2. Delegate to the `professor-expertise-finder` agent, which runs the full
   workflow: reuse or build the location's verified department/faculty-list
   table, extract and score professors against the keywords with the /5
   rubric (`references/scoring.md`), and keep only professors with at least
   two verified in-field articles.
3. Variants, invoked at any point in the conversation rather than only here:
   `--test <names>` scores named candidates directly (any location);
   `--exclude <file>` applies an exclusion list (Excel/CSV); `--reference
   <file>` searches a reviewers spreadsheet first; `--batch <id>` enters
   allocation mode for one keyword set of a multi-application batch, with
   the no-reuse / university-cap / conflict-of-interest guards enforced by
   `scripts/selections.py`.

Report the ranked table in the skill's Output Contract format (name linked
to profile, full university name, email with its source link, score with
subscores, linked articles), plus the XLSX path, and — in batch mode — the
registry's running distinct-professor count. Respond in French unless the
active conversation is in English.

the file(s) or topic given after the command in the chat message (if none was given, use the file currently open in the editor)

