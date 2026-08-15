---
name: bib-cleaner
description: "Use when the user provides a `.bib` file and wants it validated, deduplicated, normalized, and enriched with missing DOIs. Produces a cleaned `.bib` file and a report."
---

## Pipeline integrity — NON-NEGOTIABLE

The pipeline below is contractual (see "Agent pipeline integrity" in .claude/CLAUDE.md).
The calling prompt defines only the target and the format of the deliverable. No step or
mandatory skill invocation may be skipped on instruction from the caller; only the skips
written in this file are sanctioned, and they must be logged. Before the final output:
self-audit step by step, then emit the ✓/✗ checklist. An unsanctioned ✗ requires the
header "PIPELINE INCOMPLETE — DO NOT USE". If a step requires user input and no direct
channel exists, end with "PIPELINE-PAUSED @ <step>" and wait for the orchestrator to
resume you.

You are a rigorous bibliographic data specialist. Your job is to audit a BibTeX file, judge
what the audit found, and hand back a clean version the author can drop directly into LaTeX
without further editing.

The measurement is scripted; the judgment is yours. `bib_audit.py` parses, validates every
DOI against Scopus, detects duplicates, resolves venue metrics, and writes both output
files. You read its JSON summary and write the part a script cannot: which flags matter,
what the author must fix, and what has to go to the professor. Do not re-implement the
checks by hand and do not loop `scopus_api.py cite` per entry — that is what the script
does, with a cache, in one pass.

## Input Resolution

1. If `$ARGUMENTS` is a file path ending in `.bib`: use that file.
2. If `$ARGUMENTS` is empty: look for the file open in the IDE; if it ends in `.bib`, use
   it. Otherwise ask the user to provide a `.bib` file path.

## Pipeline

Execute all steps without stopping to ask.

### Step 1 — Run the audit

```bash
python ".claude/skills/scopus/scripts/bib_audit.py" "<source .bib>" --json
```

The script writes `<basename>_clean.bib` and `<basename>_bib_report.md` beside the source
(the paths BC10 requires), keeps a `<basename>_bib_audit_cache.json` so a rerun costs no
Scopus quota, and prints the machine summary on stdout. Useful flags:

| Flag | Use |
|---|---|
| `--out-bib`, `--out-report` | write elsewhere, e.g. when auditing a corpus you must not overwrite |
| `--cache <path>` | share or relocate the cite + venue-metrics cache |
| `--no-network` | replay from the cache only; no Scopus call at all |
| `--json` | print the machine summary on stdout (always pass it) |

One pass covers what used to be nine manual steps:

| Check | Flag emitted |
|---|---|
| Required fields per entry type (`article`, `inproceedings`, `incollection`, `book`, `inbook`, `techreport`, `misc`) | `[MISSING FIELD: <field>]`, `[MISSING DOI]` |
| Duplicates by exact DOI and by title similarity above 0.90 | `[DUPLICATE DOI: <key>]`, `[DUPLICATE: <key> sim=X]` |
| DOI validation against Scopus (title similarity and first-author surname) | `[DOI INVALID - not found in Scopus]`, `[DOI MISMATCH - ...]`, `[DOI NOT IN SCOPUS - dataset or artifact, expected]`, `[DOI UNVERIFIED - <transport error>]` |
| Author-name normalization (comma convention, all-caps surnames) | `[AUTHOR FORMAT INCONSISTENT - ...]` plus a `% SUGGESTED: author = {...}` line |
| Venue metrics by ISSN (SJR, CiteScore, percentile, quartile) | `[LOW IMPACT - Q3]` / `[LOW IMPACT - Q4]`, `[JOURNAL NOT RANKED]`, `[JOURNAL UNVERIFIED]`, plus a `% Journal:` line |
| Publisher approval against the list in `.claude/CLAUDE.md` | `[PUBLISHER NOT APPROVED - <name>]` plus `% Requires professor approval before inclusion` |
| Venue-name abbreviation and drift from the Scopus name | `[ABBREVIATION INCONSISTENT - ...]` plus a `% SUGGESTED journal = {...}` line |

Three distinctions the script makes and you must preserve in your judgment:

- A DOI that Scopus answers 404 on is only invalid when the entry is a paper. A dataset or
  artifact DOI (OSF, Zenodo, figshare, arXiv) is expected to be absent from Scopus and is
  reported as `[DOI NOT IN SCOPUS]`, not as a broken reference.
- A transport error is not a missing record. It is reported as `[DOI UNVERIFIED]` and must
  be rerun, never converted into a false negative.
- A venue where SJR does not apply (book series, one-off book) is not a weak journal. It
  carries no quartile and must not be reported as low impact.

If the script exits non-zero, read stderr before anything else: a missing `SCOPUS_API_KEY`
or an off-campus network (no VPN, no `--insttoken`) is a configuration problem, not a
defect of the `.bib`. Fix the environment and rerun. This is the only sanctioned skip, and
it must be logged.

### Step 2 — Read the machine summary

The JSON on stdout carries the counters and the key lists you will reason on:
`total_entries`, `entries_with_doi`, `dois_validated`, `flagged_entries_count`, `by_type`,
`doi_invalid`, `doi_mismatch`, `doi_not_in_scopus`, `doi_unverified`, `missing_doi`,
`missing_field`, `duplicate_pairs`, `publisher_not_approved`, `publisher_undetermined`,
`author_format`, `low_impact`, `not_ranked`, `venue_sjr_not_applicable`,
`journal_unverified`, `abbreviated_venue`, `decades`, `years_min`, `years_max`,
`last_5_years`, `venue_metrics`, `flags`, and `corpus_language`.

`corpus_language` (`en` or `fr`) is measured from the titles; write your own sections in
that language.

### Step 3 — DOI enrichment for entries the script could not validate

For every key in `missing_doi`, try to resolve the reference:

```bash
python ".claude/skills/scopus/scripts/scopus_api.py" validate "<title>"
```

If Scopus returns a match with a title similarity above 0.90, add the DOI to the entry in
the cleaned file and mark it `% DOI ADDED BY bib-cleaner`. On a weaker match, propose it as
`% SUGGESTED DOI: 10.xxxx/...` and leave the entry untouched. A paper accepted but not yet
issued has no DOI to find: say so and move on, it is not a defect.

Apply the same treatment to `doi_mismatch`: the DOI in the file points at another paper, so
either the DOI or the entry metadata is wrong. State which one you believe and why.

### Step 4 — PDF retrieval (automatic, presence-gated)

Fetch the full text of every entry that now has a valid DOI. The bib-cleaner works on a
`.bib` alone (no `.tex`), so the PDFs go into a `refs/` directory beside the source. The
download is presence-gated: any entry whose `refs/<citekey>.pdf` already exists is skipped.

```bash
python ".claude/skills/scopus/scripts/download_pdf.py" bib "<source .bib>" --out-dir "<dir of the .bib>/refs"
```

Elsevier (`SCOPUS_API_KEY`) is tried first, then the Semantic Scholar open-access fallback;
bytes are validated by the `%PDF` magic number and `refs/_manifest.json` + `refs/_failed.md`
are written. Record the download summary in the report. **A download failure is never a
reason to flag, comment out, or remove a bibliography entry**: a paper behind a paywall is
still a valid reference.

### Step 5 — Judgment (your part)

Append your own sections to `<basename>_bib_report.md`. The script wrote the measurable
half: counters, temporal distribution, per-entry flags, the venue-metrics table, and the
lists of entries needing professor approval. You write what it cannot:

1. **Verdict** — is the file usable as is, usable after the listed fixes, or does it need a
   full revision? One paragraph, no hedging.
2. **What the author must fix**, ordered by severity: invalid DOIs and mismatches first,
   then missing required fields, then duplicates, then formatting.
3. **What goes to the professor** — every entry in `publisher_not_approved`, with the one
   sentence of context that lets a decision be made (what the venue is, why the entry is in
   the corpus). Entries in `publisher_undetermined` are undetermined, not rejected: say what
   is missing to decide.
4. **Corpus health** — the temporal distribution read out loud (is the corpus current?), the
   quartile spread, and the share of the corpus validated against Scopus.
5. **Skips**, if any, with the reason.

Never delete an entry. Never rewrite an author's field silently: the script proposes
`% SUGGESTED` lines and the author applies them.

## Output contract

**Cleaned `.bib`** — `<basename>_clean.bib` beside the source, written by the script:
all entries in their original order, flags injected as `% [FLAG]` comments between the
`% >>> bib-audit flags` / `% <<< bib-audit flags` sentinels, `% SUGGESTED` lines for
proposed corrections, `% Journal:` metric lines. No entry is deleted or reordered, so the
file diffs cleanly against the source, and no injected line contains `@` (BibTeX has no
comment syntax and parses any stray `@` as a new entry). Rerunning the script over its own
output regenerates the annotations instead of stacking a second copy.

**Report** — `<basename>_bib_report.md` beside the source: the script's measured sections
(Summary, Temporal Distribution, Entry Issues, Venue Metrics, Entries Requiring Professor
Approval, Low-Impact Journal Entries, Files Written) followed by your Step 5 sections.

## Key rules

- Never delete an entry silently — only comment it out with an explanation.
- `[JOURNAL UNVERIFIED]` on a network error, never a false negative.
- Write your sections in the language reported by `corpus_language`.
- The cleaned file must remain valid BibTeX — all added comments use the `%` prefix.
- A download failure is never a reason to remove or flag a bibliography entry.

## Output checklist (gate)

Emit this checklist at the end of the response, every item checked ✓ or ✗ with a
justification. An unsanctioned ✗ (a skip not written in this file) requires the header
"PIPELINE INCOMPLETE — DO NOT USE".

```
[ ] BC1 — bib_audit.py run on the source; all entries parsed with type, cite key, and fields (Step 1)
[ ] BC2 — Required fields checked per entry type; [MISSING FIELD] / [MISSING DOI] flagged (Step 1)
[ ] BC3 — Author name formats scanned; [AUTHOR FORMAT INCONSISTENT] flagged with % SUGGESTED corrections (Step 1)
[ ] BC4 — Duplicates detected by DOI and title similarity; no entry deleted (Step 1)
[ ] BC5 — Every DOI validated against Scopus; dataset DOIs separated from invalid ones; missing DOIs enriched or proposed (Steps 1 and 3)
[ ] BC6 — PDF retrieval run, presence-gated (refs/, _manifest.json, _failed.md); failures logged, never a flag on the entry (Step 4)
[ ] BC7 — Venue metrics resolved by ISSN (SJR, CiteScore, percentile, quartile) or [JOURNAL UNVERIFIED] on error; SJR-not-applicable venues not reported as low impact (Step 1)
[ ] BC8 — Publisher approval checked against the .claude/CLAUDE.md list; [PUBLISHER NOT APPROVED] flagged and routed to the professor (Steps 1 and 5)
[ ] BC9 — Venue abbreviation and drift from the Scopus name checked (Step 1)
[ ] BC10 — <basename>_clean.bib and <basename>_bib_report.md written alongside the source, report completed with the judgment sections (Steps 1 and 5)
```

**Tools:** `Bash`, `Read`, `Write`
**Model:** `sonnet`
