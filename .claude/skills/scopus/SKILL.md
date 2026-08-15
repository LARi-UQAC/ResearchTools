---
name: scopus
description: "Use this skill to search Scopus for academic references, validate existing references, or produce literature reviews. Trigger on: /scopus, mentions of Scopus search, reference validation requests, finding papers on a topic."
allowed-tools: [Read, Write, Edit, Bash]
permissions: [env, read, write, network]
---

# Scopus Skill

## Prerequisites

Before running any command, verify:

1. API key is set: `python -c "import os; print('OK' if os.environ.get('SCOPUS_API_KEY') else 'NOT SET')"`
2. `requests` is installed: `python -c "import requests; print('OK')"` — if missing, run `pip install requests`
3. Network: campus network or VPN active (Scopus blocks non-institutional IPs)

If the key is missing, ask the user to run:
```powershell
[System.Environment]::SetEnvironmentVariable("SCOPUS_API_KEY", "your-key", "User")
```
Then restart Claude Code for the variable to be visible.

**Optional — Semantic Scholar fallback.** Scopus search returns only the first
author (`dc:creator`), and a few abstract records carry no author block. When a
Semantic Scholar key is set, the script backfills the full ordered author list
by DOI. Key env var (checked in order): `S2_API_KEY`,
`SEMANTIC_SCHOLAR_API_KEY`. Without a key the public S2 pool is used (heavily
throttled). The fallback is non-fatal: if S2 is unreachable or lacks the DOI,
the pure-Scopus data is returned unchanged. See `## Semantic Scholar fallback`.

---

## Mode Dispatch

Parse `$ARGUMENTS` to determine the mode, then run the script from the skill directory:

```powershell
cd ".claude/skills/scopus"
```

| If `$ARGUMENTS` starts with | Mode | Script call |
|---|---|---|
| `validate ` | Title/DOI existence check. Queries the title as a **quoted phrase**, publishes `title_similarity` per hit, and refuses to designate one record when `total_found > 1` (see `### Validate`) | `python scripts/scopus_api.py validate "<rest of args>"` |
| `verify ` | **Per-field validation against Scopus** — title, authors (full ordered list), journal, volume, issue, pages, year | `python scripts/scopus_api.py verify "<DOI or title>" --expected-title "..." --expected-authors "..." --expected-journal "..." --expected-volume "..." --expected-issue "..." --expected-pages "..." --expected-year "YYYY"` |
| `cite ` | Full metadata by DOI (now includes volume, issue, pages, full author list) | `python scripts/scopus_api.py cite "<DOI>"` |
| `author ` | Author profile. **Prefer the AU-ID form**: resolving a name to an AU-ID needs the Author Search API, which many keys are not entitled for (see `### Author`) | `python scripts/scopus_api.py author "AU-ID(<digits>)"` (or `author "<name>"`, which degrades) |
| `journal ` | Venue metadata — journal, conference proceeding, book series, trade journal (SJR, CiteScore, publisher, ISSN/ISBN, venue type). **With `--issn` it also returns `pct` (best CiteScore subject percentile) and the `quartile` derived from it**; prefer that form, a lookup by title answers a sparse stub | `python scripts/scopus_api.py journal "<venue name>" [--issn "<ISSN>"] [--fallback-doi "<DOI>"]` |
| `review ` | Literature review | `python scripts/scopus_api.py search "<rest>" --count 15` then synthesize |
| `download ` | **Full-text retrieval** into a project `refs/` dir (Elsevier -> Semantic Scholar -> publisher PDF with browser-TLS (curl_cffi) + Akamai interstitial solver + curl fallback -> Unpaywall -> arXiv -> PMC -> validated landing HTML) | `python scripts/download_pdf.py doi "<DOI>" --latex "<main.tex>"` or `python scripts/download_pdf.py bib "<refs.bib>" --latex "<main.tex>"` |
| `batch ` | **Batch corpus pipeline**, candidates -> `.bib` — strict TITLE() title-to-DOI resolution (no weak-hit fallback), cite enrichment, venue grading A-D, BibTeX generation (doi + clickable url, at-free excluded blocks, forbidden-char normalization) | `python scripts/bib_batch.py all candidates.json --corpus corpus.json --bib review.bib` (modes: `resolve`, `enrich`, `bib`, `all`) |
| `audit ` | **Audit an existing `.bib`**, the opposite direction — required fields, duplicates, DOI validation, venue metrics by ISSN, publisher approval; writes an annotated pass-through copy and a measured report | `python scripts/bib_audit.py "<file.bib>" --json` (see `## Auditing an existing .bib`) |
| anything else | Search. **Ordered by citations by default**, and bare keywords are scoped to title/abstract/keywords — see `## Search ordering and scope` before changing either | `python scripts/scopus_api.py search "<all args>" --count 10 [--sort recent] [--year_min YYYY]` |

---

## Search ordering and scope

Two defaults decide what a search actually returns. Both are measured, and both
are overridable.

### Ordering: `--sort`, default `cited`

Scopus orders by **descending date** when no `sort` parameter is sent. A search
therefore answered the most recent and least cited papers, and no founding work
could ever appear. MEASURED (2026-08-05, `TITLE-ABS-KEY(free space optical
communication)`, 17 467 hits, `count=5`, one key, one session):

| Ordering | Five first results |
| --- | --- |
| no `sort` (the old behaviour) | 2026 (3 cit.), 2026 (2), 2026 (2), 2026 (2), 2026 (**0**) |
| `-citedby-count` (the default) | 2012 (4720), 2005 (4338), 2004 (2696), 2014 (**2434**), 2021 (2073) |
| `relevancy` | 2023 (3), 2010 (15), 2004 (0), 2021 (14), 2022 (0) |

The three calls answer HTTP 200 and the same `totalResults`, so a check that only
reads the status code proves nothing about the ordering. The fourth hit of the
citation ordering is Khalighi 2014 (`10.1109/COMST.2014.2329501`), the canonical
survey a literature task had previously had to fetch from another tool.
`relevancy` is accepted and worthless on that query: do not make it the default.

| Value | Alias | Use for |
| --- | --- | --- |
| `-citedby-count` | `cited` | **default** — discovery, literature reviews, finding the founding works |
| `-coverDate` | `recent` | delta searches for NEW papers, "most recent publications" lists |
| `coverDate` | `oldest` | historical ordering |
| `-pubyear` / `pubyear` | `recent-year` / `oldest-year` | same, at year granularity |
| `relevancy` | - | Scopus relevance ranking |
| `none` | - | send no sort parameter (legacy Scopus ordering) |

Use the **alias** form: `argparse` reads `--sort -coverDate` as a new option and
refuses the call. Either `--sort recent` or `--sort=-coverDate` works.

Any caller that needs recency must say so. `cover-paper` (the ten most recent
papers of an author) and `litreview-updater` (the delta of newly published work)
both pass `--sort recent` for that reason.

### Scope: bare keywords are wrapped in `TITLE-ABS-KEY()`

A query naming no field searches `ALL`, every indexed field including reference
lists. That was survivable under date ordering and is not under citation
ordering: MEASURED (2026-08-12) the bare query `free space optical communication`
answered *Elements of Information Theory*, *QUANTUM ESPRESSO* and *GEANT4* — the
most-cited papers in all of Scopus that happen to contain those words somewhere.

So a query that names **no** Scopus field is wrapped in `TITLE-ABS-KEY(...)`.
A query that already names one (`TITLE(`, `AU-ID(`, `SRCTITLE(`, `AUTHLASTNAME(`,
...) or filters on `PUBYEAR` is sent verbatim; the boolean operators `AND`, `OR`,
`NOT`, `PRE`, `W` do not count as field names. The response reports
`query_qualified` and echoes the resolved `query`, so the scope is never silent.
Pass `--raw-query` to search every indexed field on purpose.

---

## Output Formatting

### Search results

Present as a numbered list:

```
[1] Title. Author et al. (Year). Journal. DOI: https://doi.org/... 
[2] ...
```

### Validate

Coarse existence check. For reference auditing prefer `verify`, which compares
field by field.

**Read the literal schema below, not a paraphrase.** There is **no `found` key**
and **no `record` key**. A client written against an imagined `found` field read
`None` as false and reported four "NOT FOUND" verdicts in a row on papers that
all existed, with `total_found: 1` in the same payload:

```json
{
  "mode": "validate",
  "query": "<the title as asked for>",
  "scopus_query": "TITLE(\"<cleaned title>\")",
  "query_form": "phrase" | "loose",
  "total_found": 6,
  "ambiguous": true,
  "best_match_index": 3,
  "warning": "6 records match this title. Do NOT take results[0]: ...",
  "results": [
    {
      "title": "...", "authors": "...", "journal": "...", "year": "2023",
      "doi": "10.xxxx/yyyy", "citations": "12",
      "title_similarity": 0.98,
      "doi_prefix": "10.1016", "publisher_by_prefix": "Elsevier"
    }
  ]
}
```

How to read it:

- **Existence** is `total_found > 0`. A DOI query (`10.` prefix) does not come
  through here at all: it is delegated to `cite` and returns the `cite` schema.
- **`ambiguous: true` means do not take `results[0]`.** MEASURED (2026-08-05):
  the exact title `Deep learning for unmanned aerial vehicles detection: A
  review` returned 6 records whose **first** was a corrigendum to an unrelated
  paper on photovoltaic thermal imaging (`10.1016/j.engappai.2025.113587`). A
  client reading `results[0]` cited the wrong reference with nothing to warn it.
  Compare `title_similarity`, or start from `best_match_index`, then confirm the
  chosen record with `verify` before it enters a `.bib` or a `\bibitem`.
- **`query_form`** says which query answered: `phrase` is the precise
  `TITLE("...")` form, tried first; `loose` is the older `TITLE(...)` form, tried
  only when the phrase returned nothing, so precision is gained without ever
  losing a record that used to be found.
- **`title_similarity`** is a 0-to-1 ratio on the normalized titles (case,
  punctuation and leading article stripped). It ranks candidates; it does not
  validate one. That is `verify`'s job.

### Verify (field-by-field validation)

This is the canonical mode for reference auditing. A paper is considered valid **only when every supplied field matches Scopus**. The fields checked are:

| Field | What is compared |
|---|---|
| `title` | normalized lowercase, punctuation stripped |
| `authors` | each author position is checked independently — surname must match and initial must agree. Mismatched 2nd / 3rd authors are a recurrent issue and are reported per position |
| `journal` | publication name. Covers four venue types: **journal**, **conference / proceedings**, **book** (monograph or edited volume), and **book series**. The comparison is the same string match; venue type is reported separately by the `journal` mode |
| `volume` | numeric component only (tokens such as `Vol.`, `Volume` are stripped) |
| `issue` | numeric component only (`No.`, `Issue`, `n°` stripped) |
| `pages` | normalized to `start-end` form (handles `–`, `—`, `--`, `pp.`) |
| `year` | digits only |

Output schema:

```json
{
  "mode": "verify",
  "query": "10.xxxx/yyyy",
  "resolution": "doi" | "title-exact" | "title-best-match" | "not-found",
  "scopus_doi": "10.xxxx/yyyy",
  "valid": true | false,
  "mismatched_fields": ["volume", "issue", "authors"],
  "field_checks": [ { "field": "...", "match": true|false|null, "expected": "...", "scopus": "..." } ],
  "scopus_record": { "title": "...", "authors": [...], "journal": "...", "volume": "...", ... }
}
```

`match: null` means the caller did not supply that field — it is **not** treated as a passing check.

### Review mode

1. Run search with `--count 15`
2. For each paper that has a DOI, run `cite` to retrieve the full abstract
3. Identify 3–5 themes across the papers
4. Write 3–5 sentences per theme, citing papers with `[N]`
5. Append a numbered reference list
6. Append a BibTeX block ready to paste into LaTeX

### Publisher: read the DOI prefix, not `prism:publisher`

`search`, `validate` and `cite` all carry two derived fields beside the Scopus
`publisher`:

| Field | Meaning |
| --- | --- |
| `doi_prefix` | the registrant prefix, e.g. `10.1007`. Empty when the entry has no DOI |
| `publisher_by_prefix` | the publisher that prefix designates, e.g. `Springer`. Empty when the prefix is unknown |

`prism:publisher` is misleading and three cases proved it on one 25-reference
chapter: the IJASS carried a Korean learned society while `10.1007` says
Springer, Deskos carried "Academic Press" which is an Elsevier imprint, and two
entries had the field empty. The prefix is assigned by the registration agency
and does not negotiate, so **decide the publisher from `publisher_by_prefix`**
and keep `publisher` as context.

An empty `publisher_by_prefix` means *not stated*, never *not approved*: an
unknown prefix must be named to the professor, not silently dropped. The table
lives in `scripts/doi_publisher.py`, ported from the book repository's
`audit_editeurs.py`. One entry diverges **on purpose** and must not be
"aligned": `10.1186` (BioMed Central) is out of list on the book side and inside
the approved list of this repository, per the References section of
`.claude/CLAUDE.md`. Changing that needs the author's agreement.

### Author

Show: name, affiliation, h-index, document count, top papers by citation. Which
of those fields are available depends on what the key is entitled for, and the
mode says so in a `source` field rather than pretending.

**Entitlement, MEASURED 2026-08-12.** A key entitled for Scopus Search answers
`401 AUTHORIZATION_ERROR` on the Author Search API, on the Author Retrieval API,
and on any `view=COMPLETE` search. The key is valid; those products are not
licensed. Read the `statusCode`, not the HTTP code: reporting this as an invalid
key sends the user hunting for a fault that is not there. A consequence worth
stating plainly: without the Author APIs, **no Scopus AU-ID can be resolved from
a name**, and the abstract records come back with an empty author block too, so
there is no back door.

Three paths, in order of authority:

| Call | `source` | What you get |
| --- | --- | --- |
| `author "AU-ID(57210200087)"` (or the bare digits, or `--au-id`) | `scopus-search-by-au-id` | Full profile from the entitled **Search API**: document count, affiliation from the most recent paper, top papers, and an h-index **computed** from the citation counts. `name` and `coauthors` stay empty, they need the author block |
| `author "<name>"`, key entitled | `scopus-author-search` | The historical behaviour, unchanged: candidates with their Scopus `author_id` |
| `author "<name>"`, key NOT entitled | `semantic-scholar-fallback` | Candidates from Semantic Scholar with name, affiliations, paper count and h-index. **`author_id` is `null`** — S2 has no Scopus identifier and none is invented |

The computed h-index is not an approximation of a different number: it is the
definition applied to the indexed documents, paged 25 at a time until the index
can no longer grow. On the reference author it returns 19, the same value
Semantic Scholar publishes independently.

To get a real Scopus profile when the fallback fires, either request the Author
Search entitlement for the key at `https://dev.elsevier.com`, or read the AU-ID
off the author's scopus.com profile page once and use the AU-ID form, which
needs no extra entitlement. For a publication list, resolving the AU-ID first
was already the rule: never query by bare name, and never by ORCID, which
returns only the subset the author has claimed.

### Venue (journal mode)

The `journal` mode covers every venue type Scopus indexes:

| `venue_type` value | Examples | SJR quartile rule |
| --- | --- | --- |
| `journal` | IEEE Trans., Elsevier journals | Q1–Q4 by SJR |
| `conference proceeding` | IEEE conference proceedings with ISSN, Springer LNCS | Q1–Q4 by SJR when present |
| `trade journal` | industry magazines | Q1–Q4 by SJR when present |
| `book series` | Springer Lecture Notes, Studies in Computational Intelligence | SJR sometimes assigned |
| `book` (via `--fallback-doi`) | one-off monographs, edited volumes without ISSN | SJR not applicable — publisher approval is the only criterion |
| `unknown` | venue not found in the Serial Title API and no fallback DOI | mark `[VENUE UNVERIFIED]` |

For books and edited volumes without ISSN, the Serial Title API returns no result. Provide `--fallback-doi "<DOI of any cited chapter>"` so the script can resolve the venue via the Abstract Retrieval API and surface `aggregation_type` and `publisher` — the response then carries `"source": "abstract-retrieval-fallback"`.

**Look venues up by ISSN, not by title.** Measured on an 81-entry corpus: a title
query answers a sparse record (no publisher, no SJR), and so does an ISSN query
that also passes `field=`. Take the ISSN from the entry's own `cite` record and
pass it to `--issn`; a record often carries both the print and the electronic
ISSN, and the script tries each until one resolves:

```powershell
python scripts/scopus_api.py journal "IEEE Transactions on Robotics" --issn "19410468 15523098"
```

The `--issn` response adds `pct`, the best CiteScore subject-area percentile, and
`quartile` derived from it (`>=75` Q1, `>=50` Q2, `>=25` Q3, else Q4). Scopus
publishes the percentile, not the quartile, so this is the only way to obtain one.
Read `quartile` together with `sjr_applicable`: a book series carries no quartile,
which says nothing about its quality.

---

## Auditing an existing .bib

`scripts/bib_audit.py` runs the opposite direction from `bib_batch.py`. Use
`bib_batch.py` to build a corpus from candidate titles; use `bib_audit.py` when a
`.bib` already exists and the question is what is wrong with it.

```powershell
python scripts/bib_audit.py "<file.bib>" --json
```

It writes `<base>_clean.bib` and `<base>_bib_report.md` beside the source, keeps a
`<base>_bib_audit_cache.json` so a rerun costs no quota, and prints a JSON summary
on stdout. `--out-bib` / `--out-report` redirect the outputs, `--cache` relocates
the cache, and `--no-network` replays the cache without a single Scopus call.

One pass validates every DOI (`cite`), resolves venue metrics by ISSN
(`journal --issn`), and flags required fields, duplicates, author formatting,
publisher approval and venue-name drift. Three distinctions are worth keeping in
mind when reading its output, because collapsing them produces false alarms:

- A 404 on a dataset DOI (OSF, Zenodo, figshare, arXiv) means the artifact is not
  indexed in Scopus, not that the reference is broken.
- A transport error is `[DOI UNVERIFIED]` and must be rerun, never turned into a
  verdict.
- A venue where SJR does not apply is not a weak journal.

The annotated copy is a pass-through: entries keep their order and their content,
flags are injected as `%` comments between the `bib-audit` sentinels, and no
injected line contains `@` (BibTeX has no comment syntax and parses any stray `@`
as a new entry). Rerunning over the output regenerates the annotations instead of
stacking a second copy.

The report holds only what is measurable. The judgment — what to fix first, what
goes to the professor — is written by the `bib-cleaner` agent, which drives this
script.

---

## PDF retrieval

`scripts/download_pdf.py` fetches the full-text PDF of references that are already
*fully known* (validated DOI + metadata) and stores them in a `refs/` directory placed
directly under the LaTeX project. It is a separate script — `scopus_api.py` stays a pure
JSON metadata client and never writes files.

Two subcommands:

```powershell
# single reference, refs/ resolved next to main.tex
python scripts/download_pdf.py doi "10.1109/TRO.2024.1" --citekey Smith2024 --latex "path/src/main.tex"

# whole bibliography; --bib path explicit, or auto-discovered from \bibliography{} in the .tex
python scripts/download_pdf.py bib "path/src/assets/references.bib" --latex "path/src/main.tex"
python scripts/download_pdf.py bib --latex "path/src/main.tex"
```

Behaviour:

- **Output dir** = `dirname(main.tex)/refs` (or an explicit `--out-dir`). No path is
  hardcoded; everything is derived from `--latex` / `--bib` / `--out-dir`.
- **Filename** = `<citekey>.pdf` when known (stable presence check), else
  `<author>_<year>_<title>.pdf`.
- **Presence-gated**: an existing target file is skipped — no re-download.
- **Source chain**: 1) Elsevier Full-Text API (`SCOPUS_API_KEY` env, read like every
  other mode; optional `--insttoken` for off-campus). 2) Semantic Scholar `openAccessPdf`
  as the fallback when Scopus cannot deliver. Works for OA papers without the VPN.
- **Validation on every fetch**: HTTPS-only, capped redirect hops, `%PDF` magic-byte
  check (rejects publisher HTML "access denied" pages), and a 100 MB size cap. Atomic
  write via a `*.part` rename.
- **Reports**: `refs/_manifest.json` (per-reference file + source + status) and
  `refs/_failed.md` (DOI links to fetch manually on the UQAC network).

Env var: `SCOPUS_API_KEY` (Windows user variable). The Elsevier source is skipped if it
is unset; the Semantic Scholar fallback still runs.

## Semantic Scholar fallback

`scripts/semantic_scholar_api.py` is the fallback metadata source. It resolves a
paper by DOI on the Academic Graph API and returns authors in the same
`{surname, given_name, initials, display}` shape as Scopus, so the two lists are
directly comparable in `verify` mode.

| Concern | Behaviour |
|---|---|
| Rate limit | Hard 1 request/second, cumulative across all endpoints. `_throttle()` enforces a >= 1.05 s gap; do not bypass. |
| Coverage | DOI-precise lookup only. If S2's DOI index lacks the paper (404), no authors are returned — by design, to never substitute a wrong author list during an audit. |
| Trigger | Auto for `cite`/`verify` when Scopus returns 0 authors. For `search`, opt-in with `--enrich-authors` (one throttled S2 call per result DOI). |
| Output marker | Every enriched record carries `authors_source: "scopus" \| "semantic_scholar"`. Search results gain `authors_full` (list) when enriched. |
| Disable | Pass `--no-s2` to any call for pure-Scopus behaviour. |

Standalone testing:
```powershell
python scripts/semantic_scholar_api.py authors "10.1023/A:1010933404324"
python scripts/semantic_scholar_api.py paper   "10.1023/A:1010933404324"
```

Search with author backfill:
```powershell
python scripts/scopus_api.py search "soft robotics actuator" --count 5 --enrich-authors
```

---

## Discovery tools beside Scopus

### Consensus — quota and alternation protocol

Consensus is metered on the free tier: **30 searches per month**, reset on the
first of the month, and it refuses **more than three simultaneous searches** with
`Rate limit exceeded`. A single literature task exhausted the monthly quota
mid-run, with five axes still uncovered.

Rules of use:

- Consensus serves **discovery**, when a query needs an editorial ranking Scopus
  does not produce. It is not a validation source.
- Never in a burst. Alternate each Consensus search with the Scopus validation of
  what it returned; that alternation is also what lets the rate settle.
- Since the citation ordering above, Consensus is **optional** for notoriety
  ranking alone. Its own remaining value is the synthesis by question.

### Scopus AI — manual only

Scopus AI has no programmatic interface in this skill; the consultation is manual
on `https://www.scopus.com/ai`. Prompt to copy as is, replacing the two fields in
angle brackets. It is written in English, the language of the tool.

```text
Act as a research librarian preparing a reference list for a peer-reviewed
engineering chapter on <SUBJECT, e.g.: airborne optical turret for target
designation and free-space optical data link>.

Return between 8 and 12 references that are the most established work on this
topic, ranked by scholarly influence rather than by publication date. For each
reference give exactly these fields, one per line:

  TITLE | FIRST AUTHOR | YEAR | VENUE | DOI | CITATION COUNT

Hard constraints:
1. Peer-reviewed journal or conference papers only. Exclude preprints,
   including arXiv. Exclude theses, patents, white papers and vendor
   documentation.
2. Only these publishers: IEEE, Springer, Elsevier, Taylor & Francis,
   Cambridge, Wiley, IET, IOP, ACM, MDPI, ASME.
3. Every entry must carry a DOI. Drop any entry whose DOI you cannot state.
4. Do not invent a reference. If fewer than 8 entries satisfy the constraints,
   return fewer and say how many were dropped and why.
5. After the list, name the three most-cited works you EXCLUDED because of
   constraint 1 or 2, with their DOI and the reason. Do not silently omit a
   canonical reference.

Then, in at most five sentences, state which sub-topics of <SUBJECT> are poorly
covered by peer-reviewed literature, so that the chapter can say so explicitly
instead of citing weak sources.
```

Two rules of use, both measured. The output of a discovery tool is a
**candidate**, never a reference: every DOI goes through
`python scripts/scopus_api.py cite "<DOI>"` before it enters a `.bib` or a
`\bibitem`. And the year a discovery tool announces is replaced by the Scopus
year, a preprint date having contradicted four entries out of twenty-five in one
task and two more in the next.

Point 5 of the prompt exists for a measured reason: the prescribed conduct facing
an out-of-list publisher is to **name** the discarded reference and its
substitute, never to keep silent, since an axis stripped of its canonical
reference reads as a poor axis when it is in fact a censored one.

---

## Error Handling

| Error | Action |
|---|---|
| `401 Unauthorized` | API key invalid — ask user to verify `SCOPUS_API_KEY` |
| `403 Forbidden` | Not on institution network — ask user to connect to UQAC VPN or provide `--insttoken` |
| `429 Too Many Requests` | Rate limit hit — wait 60 s and retry once |
| `requests` module missing | Run `pip install requests` then retry |
| No results returned | Broaden search terms; suggest alternative Scopus query keywords |

For off-campus access without VPN, append `--insttoken <token>` to any script call.
