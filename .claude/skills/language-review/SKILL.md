---
name: language-review
description: "Language correction codes (orthographe, grammaire, accord, ponctuation, style, register, terminology, typography) and the composition flags R1.x and R2.x, kept in one table that both research auditors (LaTeX track changes) and undergraduate report grading (PDF annotations) cite, with a ready-to-fill correction table. Use when a language correction, a style or register flag, a correction table, or an R1.x rule must be named, coded or written down, in French or in English. Trigger on: language-review, language correction, orthographe, grammaire, style, correction table, R1.x, SEMICOLON IN PROSE, SENTENCE TOO LONG."
---

# language-review

## Overview

One table holds every language-only correction code: what it is called in French and English, how
severe it is, which documents it applies to, which composition rule it enforces, and how it is applied
in LaTeX and in a PDF. Callers cite a code; they do not keep their own list. Content codes (SC, M, R,
D, FT, EQ, REF, Q, MAJ) are not language and stay in `reviewer-response`.

## Where things live

| File | Holds |
|---|---|
| `assets/language_categories.json` | the table: `code`, `flag`, `label_fr`, `label_en`, `severity`, `scope`, `rule`, `latex_action`, `pdf_action` (`color`, `prefix`), plus `not_language` |
| `assets/correction_table.csv` | the empty table to fill: `location,code,original,proposed,reason` |
| `assets/correction_table.md` | the same table with fictitious filled rows |
| `references/categories.md` | each code with one French and one English example |
| `../scientific-writing/references/composition_rules.md` | the R1.x and R2.x rules themselves (pointed to, never copied) |
| `scripts/lang_table_check.py` | validates the table and lists the flags an agent file prints |

## How a caller cites a code

- **Research auditors (LaTeX).** Print the entry's `flag` in brackets, exactly as written, with the
  location: `[SEMICOLON IN PROSE: line 42]`. Cite the entry's `rule` (`R1.7`). Apply the fix with the
  entry's `latex_action`: `direct_fix` edits the source with no markup (isolated spelling or
  punctuation), `replaced` writes `\replaced[id=..]{new}{old}`. An entry whose `flag` is null has no
  bracket text yet; cite its code (`[SP]`).
- **Undergraduate grading (PDF).** Use an entry whose `scope` is `undergraduate` or `both`. The
  annotation note starts with `pdf_action.prefix` and is drawn in `pdf_action.color`.
- **Either target.** Fill one row of the correction table per correction. `proposed` is the full
  replacement text, never an instruction.

## Checking an agent

```
python .claude/skills/language-review/scripts/lang_table_check.py --agent .claude/agents/paper-auditor.md --json
```

Exit 0: every language flag in the agent's composition sections is in the table. Exit 1: the report
names the flags the table lacks. Exit 2: refusal (a malformed table or an unreadable file, named).
A flag that sits in a composition section but concerns structure or process (`ABSTRACT LABELED
SECTIONS`, `IAG DECLARATION MISSING`) is declared under `not_language` with its reason.

## Adding a code

Add one entry to `language_categories.json` with every key, a unique upper-case code of one to six
letters, and both labels. Then run the suite:
`.claude/skills/language-review/scripts/Test/test_lang_table_check.py`. A missing key, a duplicate
code or flag, an empty PDF prefix and a content code are refused by name.

## Common mistakes

| Mistake | Fix |
|---|---|
| Rewording a flag (`TOO-LONG SENTENCE`) | Copy `flag` exactly; plans and tests match the text. |
| Inventing an R1.x number | Copy `rule`; null means no composition rule applies. |
| Putting a content issue (a wrong result) under a language code | Content belongs to the caller's own codes. |
| Writing "fix the grammar" in `proposed` | Write the corrected sentence. |
