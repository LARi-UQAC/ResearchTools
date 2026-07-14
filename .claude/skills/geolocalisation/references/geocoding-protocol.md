# Geocoding protocol — how a study location is inferred and scored

This reference defines exactly what `extract_locations.py` does, what the `confidence` column means,
how to override a point, and where the method is known to fail. The host workflow in
[../SKILL.md](../SKILL.md) depends on these definitions; read this before trusting any output.

## 1. What is being geolocated

The **study / case-study site**: the geographic place where the empirical work of a paper was
carried out (the city studied, the region surveyed, the terrain modelled). This is deliberately
**not** the author's affiliation, which is a property of who wrote the paper, not of what the paper
studied. A Swiss team studying seismic risk in Kabul has a study site in Afghanistan, not
Switzerland. The two coincide often enough to be tempting and differ often enough to be wrong, so
they are never conflated here.

## 2. Extraction pipeline

For each bib entry:

1. **Parse the bib.** Pull `citekey`, the `author` field (first-author surname -> `Surname et al.`
   label), the `doi`, and the `THEME: Tx` tag from the trailing comment line if present.
2. **Fetch the text.** Call the sibling `scopus` skill (`scopus_api.py cite <doi>`) once per DOI and
   keep `title`, `abstract`, and author/index `keywords`. Responses are cached per DOI so re-runs are
   free and offline. Entries with no DOI, or that Scopus cannot resolve, get an empty location.
3. **Match place names.** Build a search text from `title + abstract + keywords` and match it against
   an offline gazetteer:
   - **Countries** — Natural Earth admin-0 names plus a small alias map (`US`/`USA`/`United States`,
     `UK`/`United Kingdom`, `Korea` -> `South Korea`, etc.). Country centroids come from the basemap.
   - **Cities** — Natural Earth 10 m populated places (name -> lat/lon, parent country). Matching is
     whole-word and case-insensitive; single-token city names shorter than 4 characters are ignored
     to avoid collisions with common words.
4. **Resolve to one point.** Prefer a city whose parent country is also mentioned in the text. Fall
   back to a lone city, then to a country centroid. Record the terms that fired in `matched`.
5. **Score confidence** (section 3) and write the row.

## 3. Confidence rubric

| Level | When | What to plot |
|---|---|---|
| `high` | a city and its parent country both appear in the text | the city point, safe to plot |
| `medium` | a single city (country not confirmed) OR exactly one country and no city | plot, but spot-check |
| `low` | several candidate countries, or a city whose country conflicts with the text | needs a human decision before plotting |
| `none` | no place term fired, or no DOI / unresolved | empty location; human must supply it |

The score measures **agreement of signals in the abstract**, not correctness. A confident wrong
answer is possible: an abstract that foregrounds an author's country or a dataset's origin can score
`high` on the wrong place. This is why step 2 of the workflow (human review) is mandatory and why the
`matched` column exists — it lets a reviewer see *why* a point was placed and catch author-country
false positives at a glance.

## 4. Override file format

The override CSV is the durable home of curated locations. Its rows win over anything the auto
extraction produced, matched by `citekey`, and may introduce citekeys the auto pass left empty.

Minimum columns:

```csv
citekey,ville,pays,lat,lon
rahman2025susceptibility,Kabul,Afghanistan,34.53,69.17
otto2026sanborn,Chicago (IL),USA,41.88,-87.63
```

Optional columns `etude`, `theme`, `confidence`, `source` are respected if present; otherwise `etude`
and `theme` are taken from the bib, `confidence` is set to `manual`, and `source` to `override`. A row
with empty `lat,lon` explicitly marks a paper as **not mappable** (global scope, no single site) and
removes it from the plotted map without deleting it from the table.

## 5. Known failure modes (state these to the user)

- **Global / methodological papers** name no site — expect `none`; that is correct, not a bug.
- **Author-country false positives** — the most common error; the `matched` column is the tell.
- **Ambiguous city names** (Springfield, San Jose, Cambridge) resolve to the most populous match,
  which may be the wrong one. Whole-word + country-agreement matching reduces but does not remove this.
- **Non-English or transliterated place names** (Pekin/Beijing, Chiraz/Shiraz) may miss if the
  abstract uses a spelling absent from the gazetteer. Add an alias or override the row.
- **Multi-site studies** collapse to one point (the first resolved). Note it in the `etude` label or
  split into two override rows with distinct citekeys (`key`, `key-b`).

## 6. Data provenance

- `world_countries.geojson` — Natural Earth 110 m admin-0 countries, public domain, used for the
  basemap and country centroids.
- `ne_10m_populated_places` — Natural Earth 10 m populated places, public domain, used as the city
  gazetteer. Both are fetched once (TLS verified) and cached under the skill's `data/` folder; on a
  network that intercepts TLS, drop the files there by hand rather than disabling verification.

## 7. Provenance notes (audit trail)

Every located paper gets `provenance/<citekey>.md` recording the resolved location, the field it
was read from (`title` / `abstract` / `keywords` / `full-text`), the matched term, the DOI, and the
**verbatim source sentence**. The CSV carries the same as `evidence_field` and `evidence`, and the
HTML popup shows both, so a point can be verified without leaving the map. The `provenance/` folder
is rewritten on each run (stale notes from a previous run are cleared), so it always matches the
current CSV. The point of the trail is to make the author-country false positive (section 3)
catchable at a glance: if the evidence sentence is an affiliation line, the point is wrong.

## 8. Full-text fallback (`--full-text`)

A case-study city is usually stated in the body, not the abstract, so `--full-text` raises recall
for `none`/`low` abstract results. Pipeline: download the paper via the scopus skill's
`download_pdf.py` (Elsevier PDF, then the open-access tiers; cached in `refs/`), extract text with
PyMuPDF, and scan it — but only the **study-cue sentences** (section-cue phrases like "case study",
"study area", "we selected ... in", "were situated in"), with the reference list removed and any
**affiliation/header line rejected** (a sentence naming a Department/University/Institute/e-mail is
an author's city, not the study site).

This affiliation filter is essential: an unfiltered full-text scan is dominated by author
affiliations and dataset cities and maps *authors*, not *studies* (observed: 33 of a 71-paper
corpus resolved to an affiliation city, several of them contradicting the correct abstract answer).
With the filter, full text adds only genuine site sentences. To avoid regressions it adopts a
full-text location **only** when the abstract found nothing, or when the full-text hit is `high` (a
cue sentence naming both city and country); a weak full-text guess never displaces a `low` abstract
answer. Full text is opt-in because it downloads PDFs; the abstract-only path stays offline after
the Scopus calls.
