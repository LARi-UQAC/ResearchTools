---
name: extract-paper-idea
description: "Extract a paper's own content (contribution, novelty, method, results, limitations, future work) into one JSON artifact from its full text, the basis for drafting or refreshing its abstract - or, for a UQAC thesis, its Resume (French) + Abstract (English) pair. Ships no reader of its own: reuses paper2talk's LaTeX flattening, extract-statistic's future-works section scan, and extract-contributions' marker scan, pointed at the paper's own text rather than a cited one. Trigger on: extract-paper-idea, extraction du contenu de l'article, paper idea extraction, abstract source JSON, draft the abstract, refresh the abstract."
---

# extract-paper-idea

## Why this exists

An abstract drafted from memory, or from the abstract's own prior wording, drifts from what the
paper actually shows - the same failure `extract-contributions` was built to catch on citations,
one level up: here the paper is citing itself. This skill grounds every abstract component in a
verbatim extraction of the paper's own contribution, method, results, limitations, and future work,
so the `abstract-writer` agent drafts from evidence rather than paraphrase.

## Precondition, not an option

The paper's `.tex` must resolve to at least one `\section` after `\input`/`\include` flattening. A
paper with none still gets an extraction (every mechanical field degrades to empty, `warnings`
names it), never a crash and never an invented section.

## Mechanical vs judgment — the schema's core contract

`extract_paper_idea.py` (`scripts/extract_paper_idea.py`) does every MECHANICAL step and ships no
reader of its own (R18):

- `paper2talk`'s `paper_extract.resolve_includes` / `sections_of` — `\input`/`\include` flattening
  and the generic section map (level, title, word count).
- `extract-statistic`'s `extract_text.scan_sections` — the future-works-cue sections
  (`limitations`, `future_work`/`open_problems`), the same scan `extract-futureworks` audit mode
  already runs, pointed here at the flattened text.
- `extract-contributions`' `extract_contributions.analyse_file` — the paper's OWN
  contribution/novelty/method/result marker sentences. This is the same marker scan run elsewhere
  on a CITED paper; here it runs on the author's own text directly (`text=` parameter, no temp
  file), so "what does this paper claim" is answered from its own words either way. The text
  handed to the scan is prepared first (`_prepare_evidence_text`): the paper's existing
  abstract/résumé/bibliography are stripped out (they are not NEW evidence - the whole point is to
  ground the abstract in the paper's own body, not in its own prior wording), and every
  `\section{Title}` becomes its own short sentence (`. Title. `) instead of a bare macro, since a
  bare macro's backslash silently blocks the sentence-boundary lookahead the scan's splitter uses
  and glues two unrelated sentences together across the heading (measured 2026-09-25).

```bash
python .claude/skills/extract-paper-idea/scripts/extract_paper_idea.py "<paper.tex>" --json
```

Output, written to `<basename>_abstract_extraction.json` beside the paper (and printed with
`--json`):

| Field | Filled by | Meaning |
|---|---|---|
| `source.tex_path` / `document_type` / `language` | script | absolute path; `"paper"` or `"thesis"` (`uqac.cls` anywhere in the FLATTENED text, so a `\input`'d preamble file is still caught); `"fr"`/`"en"` (babel's LAST option in a multi-language list, French aliases `francais`/`frenchb`/`acadian` included, else a stopword-count fallback) |
| `title` | script | from `\title{}`, or `null` |
| `section_map` | script | `[{level, title, words, text}, ...]`, in document order — `text` is the section's own body (bounded to 2000 chars), so the agent drafts Background/Objective/Implications from evidence already in the JSON instead of re-reading the raw `.tex` |
| `background_context` | **agent** | the research problem/context (from the Introduction's `section_map` text) |
| `objective_purpose` | **agent** | the paper's stated aim (from the Introduction's `section_map` text) |
| `methodology_summary` | script | joined `method`-kind marker sentences |
| `key_findings` | script | `result`-kind marker sentences |
| `contribution_novelty` | script | `contribution`/`novelty`-kind marker sentences |
| `contribution_status` | script | `ok` / `no-contribution` / `empty` / `unreadable`, the same four statuses `extract-contributions` keeps apart elsewhere — never merged, so "no marker matched" and "text too short to judge" read differently. Anything but `ok` is also appended to `warnings` |
| `limitations` | script | future-works-cue `limitations` section excerpt(s) |
| `future_work` | script | future-works-cue `future_work`/`open_problems` excerpt(s) |
| `implications` | **agent** | 1-2 sentences (from the Discussion/Conclusion's `section_map` text) |
| `hypotheses` | **agent** | UQAC thesis only: the thesis's own stated, testable hypothesis/hypotheses (its own 3rd Résumé/Abstract component, see below); left `[]` for a paper |
| `keyword_candidates` | **agent** | 4-8 keywords (see below) |
| `existing_abstract` / `existing_resume` | script | verbatim text, or `null` when blank or absent |
| `existing_abstract_present` / `existing_resume_present` | script | `true` when the environment exists at all, even blank — distinct from `existing_abstract`/`existing_resume` being `null`, since "nothing to overwrite" and "overwrite an empty shell" are different agent behaviours |
| `warnings` | script | e.g. a `\input` that was never opened, no `\section` found, a non-`ok` `contribution_status` |

The **agent** fields are always `null`/`[]` out of the script — this skill's contract is that the
script never invents them, and the calling agent (`abstract-writer`) fills them from the
`section_map`'s own `text` entries before drafting.

## Document-type branch

- **Paper** → one abstract, in `source.language` — never a forced bilingual pair. Five components:
  Background, Purpose, Method, Findings, Implications (see `abstract-writer.md` Step 4).
- **UQAC thesis** (`document_type: "thesis"`) → BOTH a French Résumé and an English Abstract, per
  the template's own bilingual requirement, drafted from the SAME JSON so the two stay
  component-aligned rather than independently improvised. `thesis-auditor.md` already runs exactly
  this check on a finished thesis: "Compare the French résumé and English abstract component by
  component" — sharing one source of facts is what makes that check pass by construction instead
  of by luck. `thesis-auditor.md:234-242` requires SIX components, not five, plus a keywords line,
  and this pair must draft all of them or `thesis-auditor` rejects it on the next audit:

  1. **Context and problematic** (`background_context`) — the research domain and the problem.
  2. **Objectives** (`objective_purpose`) — what the thesis aims to accomplish.
  3. **Hypotheses** (`hypotheses`) — at least one testable hypothesis, stated explicitly.
  4. **Methodology** (`methodology_summary`) — the main method used.
  5. **Main result** (`key_findings`) — a concrete, quantitative finding.
  6. **Conclusion and future work** (`implications` + `future_work`) — what follows or remains open.

  Plus a **keywords line** (`keyword_candidates`), required for both the Résumé and the Abstract —
  `thesis-auditor.md` flags its absence as `[RESUME KEYWORDS MISSING]` / `[ABSTRACT KEYWORDS
  MISSING]` on its own.

## Keyword rules

4-8 keywords, complementing (not repeating) the title. A journal-supplied controlled vocabulary,
when the venue has one, takes precedence over free choice. Written into BOTH a paper's abstract
(as `\keywords{}`/`IEEEkeywords`, matching the paper's own venue convention) and a thesis's
Résumé/Abstract pair (as their required keywords line) — never computed and then left unwritten.

## Length

- **Journal/conference paper**: 100-250 words (up to 300 if the venue allows) — see
  `.claude/skills/scientific-writing/references/imrad_structure.md`, not restated here.
- **UQAC thesis Résumé/Abstract**: 250-350 words target, `<200` too short, `>400` too long —
  verified in `.claude/agents/thesis-auditor.md:232-245`, not a second, independently-invented
  number.

## Self-check gate (mandatory, not optional)

Every draft is checked against BOTH of the following before it is shown to the user. A draft
failing either is rewritten, never shipped with a caveat:

- `.claude/skills/scientific-writing/references/composition_rules.md`'s own self-check list:
  R1.1/R1.2 (passive by default), R1.4 (no `I`/`my`/`me`/`mine`), R1.5 (`we`/`our`/`us` confined to
  the Contributions paragraph and the Conclusion — so NEVER in an abstract), R1.6 (no informal
  language), R1.7 (no semicolon), R1.8 (short sentences), R2.6 (no list, ever), R3.4 (a title is a
  noun phrase, never a question or a remark), R4.1 (unstructured by default, no labels unless the
  venue requires them), R4.2 (no `\cite{}`, no reference), R4.3 (no acronym, full stop — even one
  already defined elsewhere in the paper), R4.4 (no equation).
- `.claude/skills/latex-hygiene/scripts/tex_check.py aiscan` — AI-usage score under 20%, the same
  repo-wide hard rule every other authoring agent here already enforces.

## What this skill does NOT do

No Scopus, no deliberation, no scholar-evaluation. The abstract carries no citation (R4.2), so none
of the reference-validation or cross-model-debate machinery every other authoring agent in this
repo runs applies here.

## Where the pieces live

- `scripts/extract_paper_idea.py` — the CLI and the merge. Imports its three sibling scripts
  directly (the same cross-skill pattern `extract_contributions.py` already uses for
  `extract_text.py`), rather than shelling out to each in turn. Calls
  `extract_text.configure_streams()` before printing, so a non-cp1252 title or claim (measured
  2026-09-25: `≤`) degrades the console encoding rather than crashing after the JSON file was
  already written (R8/R9, the same defect class `testing.md` already documents for 2026-09-13).
- `scripts/Test/test_extract_paper_idea.py` — 17 tests, offline, no network, no PDF.
