---
description: "Map a review corpus's study locations"
---

Turn a corpus `.bib` into a spatial map of where each paper's study was conducted. Thin wrapper over the `geolocalisation` skill — read `.claude/skills/geolocalisation/SKILL.md` and follow its three-stage, human-in-the-loop workflow. The case-study site is inferred from text and is never certain, so the skill emits a reviewable draft with a confidence column and a per-paper provenance note; a manual override CSV always wins.

Procedure:

1. Resolve the corpus `.bib` path from `the file(s) or topic given after the command in the chat message (if none was given, use the file currently open in the editor)` (a path, a directory containing one `.bib`, or the file open in the IDE). Choose an output directory (default: next to the `.bib`).
2. **Stage 1 — extract a draft.** Query Scopus once per DOI, match place names against the offline Natural Earth gazetteer, and write `study_locations.csv` (with `confidence`, `evidence_field`, `evidence`) plus one `provenance/<citekey>.md` audit note per located paper:
   ```
   python ".claude/skills/geolocalisation/scripts/extract_locations.py" --bib <corpus.bib> --out <dir>
   ```
   Add `--full-text --email <you@inst.edu>` to recover the studies whose abstract never names the site: it downloads each `none`/`low` paper via the scopus skill's `download_pdf.py`, reads it with PyMuPDF, and scans only study-cue sentences with affiliation lines rejected (an unfiltered full-text scan maps authors, not studies). Use `--no-scopus` for a manual-entry template when Scopus is unreachable.
3. **Stage 2 — human review (mandatory).** Present the draft grouped by confidence. Flag every `low`/`none` row and any `high` row whose `evidence` reads like an author affiliation rather than a study site. Persist corrections in an override CSV (`citekey,ville,pays,lat,lon`) and re-run Stage 1 with `--override <curated.csv>` so the curated rows win. Never render an unreviewed map without saying so.
4. **Stage 3 — render.** Emit the artifacts from the reviewed CSV:
   ```
   python ".claude/skills/geolocalisation/scripts/generate_geomap.py" --csv <dir>/study_locations.csv --out <dir> [--formats csv,kml,geojson,png,html] [--min-confidence low] [--title "..."]
   ```

Report at the end:

- The confidence breakdown (high / medium / low / none) and how many rows were mapped vs left unmapped
- The artifact paths produced (CSV, KML, GeoJSON, PNG, HTML, `country_counts.csv`) and the `provenance/` folder
- The top countries by study count
- Any rows that still need a human decision (low/none, or a full-text guess that looks like an affiliation)

Requires `SCOPUS_API_KEY` and campus network or UQAC VPN for the auto path (`--full-text` additionally uses `UNPAYWALL_EMAIL` / `--email`). Apply the pipeline directly; do not ask "would you like me to..." between stages except at the Stage 2 review checkpoint. Respond in French unless the active file is in English.

the file(s) or topic given after the command in the chat message (if none was given, use the file currently open in the editor)

