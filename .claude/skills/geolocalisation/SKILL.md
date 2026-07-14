---
name: geolocalisation
description: "Build a spatial map of a literature-review corpus from a BibTeX file. Extracts each paper's study / case-study location automatically (per-DOI Scopus abstract + title + keywords, matched against an offline Natural Earth gazetteer), writes a reviewable draft table with a confidence column, lets a human curate or override it, then renders the corpus as CSV, KML (Google My Maps), GeoJSON (QGIS/Leaflet), a static world map PNG for the review figure, an interactive HTML map, and a per-country count table. Use this skill whenever the user wants to map, geolocate, or geographically situate the papers of a corpus or review; turn a .bib into study_locations.csv or a study-location map; produce a KML/GeoJSON/world-map figure of where studies were conducted; or asks about the geographic coverage, spatial distribution, or country breakdown of a reference set. Triggers on: /geolocalisation, 'map the corpus', 'geolocate the studies', 'carte des études', 'où ont eu lieu les études', 'bib to map', 'study locations map'."
allowed-tools: [Read, Write, Edit, Bash]
permissions: [read]
---

# Geolocalisation — map a review corpus in space

Turn a corpus `.bib` into a set of geographic artifacts that show **where the studies of a
literature review were conducted**. The skill automates the extraction that used to be done by
hand, but keeps a human in the loop because a study's location is inferred from text and is never
certain. The extraction method, the confidence rubric, the override-file format, and the honest
limits are in [references/geocoding-protocol.md](references/geocoding-protocol.md) — read it before
running, it is the contract for what the numbers mean.

## What it produces

From one `.bib` (and its per-entry `THEME:` comments, if present), it produces up to six artifacts:

| File | Role |
|---|---|
| `study_locations.csv` | source table: `citekey, etude, ville, pays, lat, lon, theme, confidence, source, matched, evidence_field, evidence, provenance` |
| `provenance/<citekey>.md` | one audit note per located paper: resolved location, which field it was read from (title/abstract/keywords/full-text), the matched term, and the **verbatim snippet** copy-pasted from the article |
| `study_locations.kml` | same points, importable in Google My Maps (My Maps -> Create -> Import); evidence in the description |
| `study_locations.geojson` | open standard, loads in QGIS / Leaflet / any web map; evidence in the properties |
| `study_locations_map.png` | world map (Natural Earth basemap + points, per-country heatmap) for the review figure |
| `study_locations_map.html` | interactive zoomable map; each point's popup shows the evidence snippet + provenance file so the map itself is auditable. Needs `folium`; skipped with a logged note if absent |
| `country_counts.csv` | studies per country, feeds the heatmap and gives a citable table |

Every plotted point is traceable: the CSV carries `evidence_field` (where the location
was read) and `evidence` (the exact source sentence), `provenance/<citekey>.md` holds the
full audit note, and the HTML popup surfaces both so a reviewer can verify a point without
leaving the map.

## The critical caveat — read this first

A study's **case-study location is not a bibliographic field**. No API (Scopus included) returns
it. It lives in the paper's text. This skill infers it from the Scopus **abstract + title +
author/index keywords** by matching place names against an offline gazetteer. That inference is
heuristic:

- It misses studies whose abstract never names the site (global/methodological papers, benchmarks).
- It mislabels when the abstract names a place that is **not** the study site (an author's country,
  a compared method's origin, a dataset's provenance). Author affiliation is **not** the study site.

Therefore the skill never emits a "final" map in one shot. It emits a **draft with a confidence
column**, the user reviews it, and a **manual override always wins** before rendering. Present the
draft honestly: say how many points are `high` vs `low` vs `none`, and that low/none rows need a
human eye. Do not silently promote a `low` guess to a plotted point without flagging it.

## Inputs

- **Required:** a corpus `.bib` path. Every entry needs a `doi` for the auto path to work; entries
  without a DOI are carried through with an empty location for the user to fill.
- **Optional:** an override CSV (`--override`) whose rows replace or add points by `citekey`. This
  is where curated / hand-checked locations live. Same columns as the output table; only
  `citekey, ville, pays, lat, lon` are needed (theme is read from the bib if omitted).
- **Environment:** `SCOPUS_API_KEY` (or `.claude/skills/scopus/.scopus_key`) plus campus network or
  UQAC VPN for the auto extraction. Without it, run in `--no-scopus` mode: the skill parses the bib
  and produces an empty-location template for full manual entry.

## Workflow

Follow these steps in order. Steps 1 and 3 are scripts; step 2 is the human checkpoint that makes
the output trustworthy.

### Step 1 — Extract a draft table

```bash
python .claude/skills/geolocalisation/scripts/extract_locations.py \
    --bib <corpus.bib> --out <dir> [--override <curated.csv>] [--full-text] \
    [--email you@inst.edu] [--no-scopus] [--insttoken TOKEN]
```

This parses the bib (citekey, first-author label, theme), queries Scopus once per DOI (cached under
`<dir>/.scopus_cache/`), matches place names, writes `<dir>/study_locations.csv` with `confidence`,
`evidence_field`, and `evidence` columns, and drops one `provenance/<citekey>.md` audit note per
located paper. It prints a summary: N high / M medium / K low / U none.

**`--full-text`** raises recall for the studies whose abstract never names the site (the common
case for a case-study city stated only in the body). For every `none`/`low` abstract result it
downloads the paper through the scopus skill's `download_pdf.py` (Elsevier PDF, then the
open-access tiers; needs `--email` for Unpaywall), extracts the text with PyMuPDF, scans the
study-cue sentences first and the reference-list-stripped body second, and adopts the full-text
location only when it beats the abstract. Files are cached under `<dir>/refs/`, so a second run is
cheap. It is opt-in because it fetches PDFs; without it the skill is abstract-only and offline after
the Scopus calls.

### Step 2 — Human review (mandatory before rendering)

Show the user the draft, grouped by confidence. Ask them to correct or confirm — especially every
`low` and `none` row, and any `high` row where the matched term looks like an author country rather
than a study site. The cleanest way to persist corrections is an **override CSV**: the user edits it
(or you edit it on their instruction), then re-run step 1 with `--override` so their rows win. Never
skip this step; a map of wrong points is worse than no map. If the user explicitly says "just render
the draft", note in your reply that the map is unreviewed.

### Step 3 — Render the artifacts

```bash
python .claude/skills/geolocalisation/scripts/generate_geomap.py \
    --csv <dir>/study_locations.csv --out <dir> [--formats csv,kml,geojson,png,html] \
    [--title "..."] [--min-confidence low]
```

`--formats` selects the subset to emit (default: all available). `--min-confidence` drops points
below a threshold from the plotted map (they stay in the CSV). The basemap `world_countries.geojson`
(Natural Earth 110 m, public domain) is read from the skill's `data/` folder; if absent it is fetched
once (TLS verified) and cached there.

## Boundaries

- The skill **infers and renders**; it does not fabricate. A location it cannot support with a
  matched term is left empty, not guessed.
- It does **not** validate the references themselves — that is the `scopus` skill / `bib-cleaner`.
  Feed it a `.bib` that is already clean.
- Author affiliation mapping is a **different** deliverable (institution, not study site). If the
  user actually wants that, say so and stop: it is a separate mode not built here.

## Dependencies

`matplotlib` (PNG). Optional: `folium` (HTML), `PyMuPDF` (the `--full-text` PDF scan; reuses the
scopus skill's `download_pdf.py`). No geopandas/GDAL — the basemap is drawn from raw GeoJSON.
Install and audit per the repo rule:

```bash
pip install -r .claude/skills/geolocalisation/scripts/requirements.txt
pip-audit -r .claude/skills/geolocalisation/scripts/requirements.txt
```
