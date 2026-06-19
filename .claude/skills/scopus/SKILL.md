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
| `validate ` | Title/DOI lookup (legacy, single-field) | `python scripts/scopus_api.py validate "<rest of args>"` |
| `verify ` | **Per-field validation against Scopus** — title, authors (full ordered list), journal, volume, issue, pages, year | `python scripts/scopus_api.py verify "<DOI or title>" --expected-title "..." --expected-authors "..." --expected-journal "..." --expected-volume "..." --expected-issue "..." --expected-pages "..." --expected-year "YYYY"` |
| `cite ` | Full metadata by DOI (now includes volume, issue, pages, full author list) | `python scripts/scopus_api.py cite "<DOI>"` |
| `author ` | Author profile | `python scripts/scopus_api.py author "<name>"` |
| `journal ` | Venue metadata — journal, conference proceeding, book series, trade journal (SJR, CiteScore, publisher, ISSN/ISBN, venue type) | `python scripts/scopus_api.py journal "<venue name or ISSN>" [--fallback-doi "<DOI>"]` |
| `review ` | Literature review | `python scripts/scopus_api.py search "<rest>" --count 15` then synthesize |
| `download ` | **Full-text PDF retrieval** into a project `refs/` dir (Elsevier primary, Semantic Scholar OA fallback) | `python scripts/download_pdf.py doi "<DOI>" --latex "<main.tex>"` or `python scripts/download_pdf.py bib "<refs.bib>" --latex "<main.tex>"` |
| anything else | Search (optional `--year_min YYYY` to constrain to recent papers) | `python scripts/scopus_api.py search "<all args>" --count 10` |

---

## Output Formatting

### Search results

Present as a numbered list:

```
[1] Title. Author et al. (Year). Journal. DOI: https://doi.org/... 
[2] ...
```

### Validate

Report `✓ Found` or `✗ Not found`, then show the full metadata block (title, authors, journal, year, DOI, citations). Use this only as a coarse existence check — for reference auditing prefer `verify`.

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

### Author

Show: full name, affiliation, h-index, document count, top 5 papers by citation.

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

## Error Handling

| Error | Action |
|---|---|
| `401 Unauthorized` | API key invalid — ask user to verify `SCOPUS_API_KEY` |
| `403 Forbidden` | Not on institution network — ask user to connect to UQAC VPN or provide `--insttoken` |
| `429 Too Many Requests` | Rate limit hit — wait 60 s and retry once |
| `requests` module missing | Run `pip install requests` then retry |
| No results returned | Broaden search terms; suggest alternative Scopus query keywords |

For off-campus access without VPN, append `--insttoken <token>` to any script call.
