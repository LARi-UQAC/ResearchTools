---
name: professor-expertise-finder
description: "Find professors by expertise keywords (professeurs par mots-clés, experts in <field> at universities) in any country, province/state, region, or worldwide: a faculty finder that builds or reuses a verified university/department/faculty-list table, ranks professors with a /5 correspondence score, scores named candidates (tester ces professeurs), applies an exclusion list (liste d'exclusion professeurs), and allocates reviewers across several funding applications with no-reuse, one-university-per-evaluator, and conflict-of-interest guards. Trigger on: find professors by expertise, score these professors, /expertfinder."
---

# Professor Expertise Finder

## Purpose

Given a **search location** (supplied by the user, never hardcoded) and a set of
**expertise keywords**, identify the university professors whose expertise is
closest to those keywords, and prove the match with at least two articles in
the field per professor.

This skill is location-agnostic: it works for a country, a province/state, a
region, a city, or worldwide. Any table it builds is an *instance* for one
location, stored outside the skill; the skill itself contains no place names.

## Inputs (ask, never assume)

1. **Search location** — if the request does not already name one, ask first:
   « Pour quel lieu de recherche ? Par exemple : un pays (Canada), un pays +
   province/état (Canada, Ontario), une région, une ville, ou mondial. »
   Accept: country alone; country + province/state/region; region; city;
   worldwide. The location defines the data-instance slug
   (e.g. `canada-ontario`, `canada`, `france-ile-de-france`, `worldwide`).
2. **Expertise keywords** — asked only *after* the department table for that
   location exists (Workflow step 2). Accept French, English, or both; keep
   both language versions for searching, as faculty pages and articles are
   often in only one of them.
3. **Ranking scope** — if unspecified, ask with the keywords: closest
   professors across the whole location (top N) or best per university.
4. **Named candidates (test mode)** — optional. The user may supply
   specific professors to score, as names alone or with university and
   email (chat text, list, spreadsheet, screenshot). Test mode scores
   exactly those people against the keywords; they **may be outside the
   search location** — the location table is then neither required nor
   limiting. Each named person is resolved individually (Workflow 4b).
5. **Exclusion list** — optional. The user may supply a file (Excel or
   CSV) of professors to exclude, e.g. because they are unavailable this
   year. Expected columns, any order, extra columns ignored: a name column
   (`name`, `professor`, `nom`, or first/last name columns), optionally
   `university` / `université` and `reason` / `raison`. Exclusions are
   applied with `scripts/exclusions.py` (Workflow 6b).
6. **Presumed languages** — always reported, never asked. See Workflow 6c.
7. **Reference list file (optional)** — the user may supply a spreadsheet
   of known professors/reviewers (e.g. a national list for the year) with
   names, institutions, departments, areas of expertise, declared
   language capabilities (read/write/speak per language), and an
   availability column. When such a file is supplied, it is searched
   **first** (Workflow 3b) and the web phase follows as usual. When it is
   not supplied, the run is purely web-based — the file is an accelerator
   and a source of declared data, never a boundary: professors absent
   from the file are found on the web exactly as before.
8. **Unique selection / no-reuse (batch allocation mode)** — optional,
   and essential when several keyword sets are processed in one batch
   (e.g. N funding applications needing reviewers): once a professor is
   in the **final** selection for one keyword set, they cannot be
   selected for any other set in the same batch — nobody is asked to
   review two or three applications. Enforced by the selection registry
   (Workflow 6d), never by memory. The user supplies, per set: an
   identifier, its keywords, how many professors it needs, and optionally
   suggested names for that set (scored in test mode, then allocated
   under this constraint).

## Data instances (outside the skill)

```
<data root>/<location-slug>/departments.csv
<data root>/<location-slug>/departments.xlsx
<data root>/batches/<batch-slug>/selections.csv
<data root>/batches/<batch-slug>/applications.csv
```

`<data root>` is the `PROFESSOR_EXPERTISE_DATA` environment variable when
set, else `~/workspace/professor-expertise` (resolved by
`scripts/pef_common.py`'s `data_root()` — R1, no hardcoded path: repoint the
data by setting the environment variable, never by editing a script).

Table schema (one row per department; a university may have several rows):

```
university, department, department_url, faculty_list_url, note
```

Run `scripts/table.py` to check/create/validate an instance:

```
python3 scripts/table.py path  --location "Canada, Ontario"
python3 scripts/table.py check --location "Canada, Ontario"   # exists? valid? row count
python3 scripts/table.py init  --location "Canada, Ontario"   # create empty table if missing (never overwrites)
python3 scripts/table.py validate --location "Canada, Ontario"
```

`init` takes `--dry-run` (report, write nothing); `check`/`validate`/`init`
take `--json <path>` for a machine-readable report alongside the printed text.

## Workflow

0. **Location** — obtain the search location (see Inputs). Derive the slug.
1. **Table check** — run `table.py check`. If the table exists and validates,
   reuse it as-is; do not rebuild it.
2. **Table creation (only if missing)** —
   a. Establish the complete list of universities for the location from an
      authoritative source (national/regional university association,
      ministry list, Universities Canada / equivalent).
   b. For each university, find its department(s) of computer science,
      computer engineering, or software engineering. If there is no distinct
      department, record the unit that actually carries those programs
      (combined department, school, faculty, research centre); if there is
      genuinely none, record the university with department `Aucun / None`
      and a brief justification in `note`.
   c. For each department, find the official page listing its faculty
      members (« Professeurs », « Corps professoral », « Faculty »,
      « People », directory). If no department-specific page exists, record
      the closest official page and say so in `note`.
   d. Verify every URL (Operating Rules), write the CSV, then export XLSX.
   e. Show the table to the user.
3. **Keywords** — now ask for the expertise keywords and ranking scope.
3b. **File first (only when a reference list was supplied)** — run
   `python3 scripts/file_search.py --file <list.xlsx> --terms <terms.txt> --out <matches.csv>`
   with the keyword clusters (plus close synonyms reviewers actually write
   in expertise fields, in both languages). `--min-matches N` (default 1)
   raises how many of those terms a row must hit to be shortlisted - rarely
   needed, since a low bar here only widens the web-phase candidate set, not
   the final output. The output is a **shortlist, not a result**: for each
   match it carries the file's stated expertise,
   its declared language capabilities, and its availability flag.
   - A row flagged « Not available this year / Non disponible cette
     année » (or the file's equivalent) is treated as an **exclusion**
     (Workflow 6b annex, reason = the flag, source = the file).
   - **Declared languages in the file outrank web presumption** (6c):
     when the file states read/write/speak per language, report those as
     *declared (source: file)*; use web presumption only for professors
     the file does not cover. `file_search.py` recognizes English and
     French declared-language columns only (known limitation); a third
     language in the file falls back to web presumption for that professor.
   - Expertise text from the file seeds scoring (it is the professor's
     own declared areas), but affiliation, email, articles and the final
     /5 score are still established in the web phase — and any email
     associated with the file is validated on the professor's official
     web page before use, as such files themselves usually instruct.
   Then continue with the web phase (steps 4–7) for the shortlist **and**
   for the rest of the location, unchanged.
4. **Faculty extraction** — from each `faculty_list_url`, extract the
   professors (name, university, department, profile URL) and, for every
   professor who reaches the output, the **professional email published on
   their official page**. An email is copied from the page, never built
   from a name pattern (`prenom.nom@…` is a guess, even when the pattern
   looks obvious); when no email is published on an official page, output
   `non publié` — do not fill the gap. In test mode, an email supplied by
   the user is a lead: keep it only if an official page or the
   institutional domain corroborates it, and say which. Parallelize by
   university when the location is large.
4b. **Test mode (named candidates)** — when the user supplied named
   candidates, skip steps 1–2 and 4. For each named person: verify the
   current affiliation and department on an official page (the supplied
   university/email are leads to check, not facts — an institutional email
   domain corroborates, a stale list does not); find the official profile;
   then score exactly like everyone else (steps 5–6). A named person who
   cannot be found, or who is no longer at a university, is reported as
   unresolved — never silently dropped and never scored on guesses.
5. **Expertise scoring (/5)** — cluster the keywords first (application
   domain / core method / deployment context / measurement), then score
   each professor with the rubric in `references/scoring.md`: five
   subscores A–E worth 0, 0.5, or 1 each (application domain, core method,
   deployment context, measurement/uncertainty, verified publications),
   based on, in order of weight: (1) stated research areas on the official
   profile, (2) article titles and abstracts, (3) lab affiliation. Compute
   every total with `scripts/score.py` — never by hand. Publish the total
   **with** its subscores, e.g. `3.5/5 (A 1, B 1, C 0.5, D 0, E 1)`. The
   score measures closeness to this run's keywords only, never quality or
   reputation. Professors below `pef_config.json`'s `retain_threshold`
   (currently 1.5) are not retained; E = 0 (fewer than two verified
   in-field articles) excludes outright.
6. **Article proof** — for each retained professor, find **at least two
   articles in the field** of the keywords. A professor without two verified
   articles is dropped from the final list (or explicitly flagged as
   unverified, never silently kept).
6b. **Exclusions** — if the user supplied an exclusion list, apply it to
   the ranked CSV before delivery:
   `python3 scripts/exclusions.py --ranking <ranking.csv> --exclusions <file.xlsx|.csv> --out <filtered.csv>`.
   Matching is by normalized name (accent/case-insensitive, first/last
   order-insensitive). Every excluded professor is listed in an annex with
   the reason from the file (or « raison non précisée ») — exclusions are
   visible, never silent. The script also reports exclusion entries that
   matched nobody, so typos surface instead of silently doing nothing.
   `--dry-run` previews without writing; `--json <path>` adds a report.
6c. **Presumed languages** — for every professor in the output, infer the
   presumed working languages from their official web presence, in this
   order: (1) language of their official profile page, (2) language of
   their personal / lab website, (3) language of their publications. Rule
   of thumb stated by the user: a professor who offers a web page in
   English is presumed to speak, read and write English (same for French
   or any other language); evidence in two languages ⇒ bilingual presumed.
   Always label the result « présumées » and give the basis (e.g. « EN —
   profil officiel et publications en anglais »). Institutional bilingual
   boilerplate alone (a university site offered in FR/EN) is not evidence
   about the person; the professor's own content must be in that language.
   No evidence ⇒ « indéterminée », never a guess from the person's name
   or origin.
6d. **Selection registry (batch allocation mode only)** — the registry
   `<data root>/batches/<batch-slug>/selections.csv`
   is managed exclusively through `scripts/selections.py`:
   `init` the batch before the first set; `check --professor <name>`
   before proposing anyone; `add --status final` when a set's list is
   settled. The script rejects any final add for a professor already
   final in another set of the batch. Allocation order: process sets one
   at a time; a suggested name that fits several sets is assigned to the
   set where its /5 score is highest, and the other sets fall back to
   their next candidates (from the ranking, the reference file, then the
   web). **After each set is settled, report its final choice to the
   user** — the professors chosen, their scores, and the running total of
   distinct professors used — before moving to the next set. At the end,
   `list` prints the whole batch: one final list per set, all professors
   distinct; verify the distinct count equals the batch's target before
   declaring completion.
7. **Output** — ranked table (Output Contract), delivered in chat plus an
   XLSX file next to the instance table, with the exclusions annex when an
   exclusion list was applied. In batch mode, the deliverable is one list
   per set (identifier, keywords, professors with scores, page links and
   emails) plus the registry summary (`selections.py list`).

## Output Contract

One row per retained professor:

```
rank, professor, university, department, profile_url, email,
expertise_summary, score_total_5, score_subscores, score_rationale,
languages_presumed, languages_basis,
article_1_title, article_1_url, article_2_title, article_2_url
```

`profile_url` is the professor's own official page (department profile,
personal or lab page hosted/endorsed by the institution) — the link a
reader would open to contact or read about them. `email` is their
professional email address **as published** on that official page (or on
an official institutional directory page for that professor).

**User-facing presentation format (required)** — in the chat summary and
in every delivered spreadsheet, each professor is presented as:

```
Nom Prénom (lien cliquable → page web du professeur) | Nom complet de
l'Université | Courriel | Score /5 | Article 1 (titre, lien cliquable) ;
Article 2 (titre, lien cliquable)
```

In spreadsheets the professor's name cell itself carries the hyperlink
to `profile_url`, and each article title cell carries the hyperlink to
its article URL — no bare URL columns in the user-facing sheet. In chat,
use Markdown links on the name and on each article title.
**Email rule:** the email is shown as plain text accompanied by a link
to the **source page that publishes it** (its provenance — official
profile, directory, CV, or the publication where the address appears).
Never use a `mailto:` link for the email, in chat or in spreadsheets.
**Highlighting rule (batch mode):** professors whose names were
**suggested by the user** for a set are highlighted **yellow** in the
response — in the spreadsheet, their entire row carries a yellow fill;
in chat lists, their line is prefixed with 🟨. Professors added by the
agent are not highlighted. This lets the user see at a glance which
evaluators came from their own list.

Exclusions annex (only when an exclusion list was applied), one row per
excluded professor: `professor, university, reason`.

## Operating Rules

1. **No guessed URLs, ever.** Every URL (university, department, faculty
   list, profile, article) is copied exactly from a search result or an
   opened page. A URL that could not be verified is marked unverified in
   `note`, never presented as checked.
2. **Anti-fabrication.** Every article title is checked title-by-title
   against its source page (publisher, conference, journal, Scholar/Scopus
   profile) before it enters the output. Never invent articles, expertise
   areas, department names, or affiliations.
3. **No hardcoded location.** Place names appear only in data instances and
   in the user's request — never in this skill, its scripts, or its config.
4. **Ask, don't assume.** Location first, keywords second, in that order.
   Do not start a faculty ranking before both are known.
5. **Reuse before rebuilding.** An existing, valid table for the location is
   always reused; creation is the fallback, not the default.
6. **Language.** Interact in the user's language; search in the location's
   language(s) plus English. A professor's presumed languages follow
   Workflow 6c only — never inferred from their name, origin, or employer.
7. **Supplied lists are leads, not facts.** Names, universities, and emails
   the user supplies (test mode, exclusion lists) are verified against
   official pages before use; a mismatch is reported, not papered over.
8. **No reuse is a hard rule in batch mode.** A professor final for one
   keyword set is unavailable for every later set of the batch, exactly
   like an exclusion — and the registry script, not the conversation, is
   what proves it. Never reassign silently: a conflict is reported with
   the set that already holds the professor. **The moment the user
   submits suggested names for a set, check every name against the
   registry FIRST, before any evaluation; any name already final in
   another set is flagged immediately and explicitly as « DÉJÀ UTILISÉ
   — à retirer immédiatement », naming the set that holds it.**
9. **All evaluators of one application must come from distinct
   universities.** Enforced as a cap of `pef_config.json`'s
   `max_per_university` (currently 1) professors from the same university
   in one application's final selection — a single funding application
   (one keyword set) may never have two evaluators from the same
   university. Enforced by `scripts/selections.py` (an `add` past the cap
   from the same university for the same application is rejected); when
   building a proposal, respect this from the start and say so when it
   forces a substitution — if the best-scoring candidates cluster in one
   or two universities, say that explicitly rather than silently settling
   for lower-scoring substitutes.
10. **Conflict of interest: no evaluator from the applicant's own
    university.** In batch mode, the user provides the **applicant
    university** of each funding application; record it with
    `scripts/selections.py origin --application ... --university ...`
    (stored in `applications.csv` beside the registry). A professor
    whose university equals the applicant university of an application
    may not evaluate it — `add` rejects such a registration, and
    declaring an origin retro-audits the professors already registered
    for that application and flags any conflict. When building a
    proposal for a set whose origin is known, exclude professors from
    that university from the start and say so. If the origin has not
    been provided, ask for it — the check cannot run without it.

## Files

- `SKILL.md` — this file.
- `references/scoring.md` — the /5 rubric, its interpretation bands, and
  the provenance of its enforced constants (`scripts/pef_config.json`).
- `scripts/pef_common.py` — shared helpers: `data_root()` (R1), `slugify`,
  `norm`, `name_key`, `load_config()`.
- `scripts/pef_config.json` — policy constants with provenance:
  `subscore_values`, `retain_threshold`, `max_per_university` (R0, R6).
- `scripts/table.py`, `scripts/score.py`, `scripts/exclusions.py`,
  `scripts/file_search.py`, `scripts/selections.py` — see Workflow above.
- `scripts/Test/` — offline unit tests (no network, no API key).
