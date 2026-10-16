---
name: wp-portfolio-sync
description: "Migrate a researcher's final CIHR / Canadian Common CV XML export into their WordPress portfolio once, through the WordPress REST API, between cvsync markers. Trigger on: WordPress portfolio, CV XML to WordPress, CCV migration, portfolio.uqac.ca, /portfolio."
---

# WordPress Portfolio Sync

A **one-shot migration** (D1): a researcher's final CIHR / Canadian Common CV (CCV) XML
export is parsed, mapped to WordPress pages, previewed, and pushed through the WordPress
REST API between `<!-- cvsync:MARKER -->` comments. Once pushed, the website is the source
of truth for that data; the XML is never read again, and this skill is never re-run over
the same section.

**No student data is parsed from the XML.** `cihr_cv.py` recognises no supervision section
at all. A mapping entry with `renderer: phq` is refused everywhere this skill checks a
mapping. Student data is published from ThesisTracker, once its own consent flow ships
(Phase 2) - out of scope here.

Phase 2 (ThesisTracker calling a stateless endpoint that reuses `render_phq`) and Phase 3
(narrative-cv through a stateless `/cv/build`) are separate, later efforts; this skill ships
none of their wiring.

## Prerequisites

- `pip install -r scripts/requirements.txt` (PyYAML, `requests` - imported lazily, only when
  a network call is about to be made).
- WordPress credentials in the environment, never committed:
  - `WP_APP_USER` and `WP_APP_PASSWORD` - a WordPress Application Password, created once
    under *Users -> Profile -> Application passwords* while signed in.
  - Fallback: a cookie file (`config/cookies.json`, see
    `templates/cookies.json.example`), path from `WP_COOKIES` or `<data-dir>/config/cookies.json`
    - still contained to `--data-dir` the same as every other researcher-supplied path.
    Works, but expires with the session that produced it. A write (`push_wp.py`) additionally
    needs `WP_NONCE` set to the nonce a logged-in WordPress session returns; without it a
    cookie-authenticated push refuses up front rather than failing on every individual PUT.
    A read-only cookie session (`discover.py`, which never writes) does not need it.

## Data folder

All researcher data (the XML, `cihr.json`, `config/`) lives under an explicit `--data-dir`
given on every command, which must resolve outside this repository (the repository is
public). Layout:

```
<data-dir>/
  cv.xml                     input, supplied by the researcher
  cihr.json                  written by cihr_cv.py
  config/mapping.yaml        required
  config/pages.json          written by discover.py
  config/exclusions.yaml, implications_extra.yaml, services_extra.yaml,
    distinctions_extra.yaml, contributions.yaml, historique/*.md   all optional
  config/cookies.json        optional, fallback authentication, a secret
```

## mapping.yaml

See `templates/mapping.example.yaml` for a fully worked, fictitious example. Top level, all
required: `site` (https URL), `ref_year` (int), `recent_window` (int >= 1), `recent_label`
(string), `excluded_funding_statuses` (list, may be empty), `entries` (non-empty list). Each
entry has `cv_path`, `page_id`, `mode` (`markers` | `replace` | `split`), and mode-specific
keys - `marker` for `markers`; `renderer`, `recent_marker`, `history_marker` and (for
`distinctions`) `subkey` for `split`; nothing more for `replace`. `validate_mapping` refuses
a missing key, a wrong type, `renderer: phq`, an unknown renderer, a duplicate
`(page_id, marker)` pair, and a `replace` page shared with another entry.

## Workflow

Run every command below from this skill's own `.claude/skills/wp-portfolio-sync/` directory
(where `scripts/` and `wp-sync-config.json` sit beside each other) - `scripts/cihr_cv.py` is
relative to that working directory, not to the repository root or to `<data-dir>`.

```bash
# 1. Parse the CV XML (CIHR/CCV export)
python scripts/cihr_cv.py cv.xml --data-dir <data-dir> --json

# 2. First run only: discover WordPress pages, then fill config/mapping.yaml's page_id values
python scripts/discover.py --data-dir <data-dir> --json

# 3. Preview every planned change - no network write
python scripts/preview.py --data-dir <data-dir> --json

# 4. Push, dry run first (no --apply writes nothing)
python scripts/push_wp.py --data-dir <data-dir> --json

# 5. Push for real, only after reviewing the dry run
python scripts/push_wp.py --data-dir <data-dir> --apply --yes --json
```

The `/portfolio` command and the `wp-portfolio-agent` agent drive this same sequence with
the researcher's approval gates built in.

## Exit codes

`0` success; `1` failure (network, HTTP, unreadable input, a write that did not verify);
`2` refusal by design (missing or invalid argument or config, gate failure, `--apply`
without `--yes`, an output path outside `--data-dir`, `--data-dir` inside the repository,
missing credentials, an empty section). Every state-changing or network CLI accepts
`--json` and prints one JSON object on stdout besides its human text on stderr - on success
AND on a refusal or failure, where it is `{"error": ..., "exit_code": ...}` rather than
nothing, so a caller scripting against `--json` can tell the two apart without parsing
stderr. Secrets never appear in either.

## Guardrails

- **Markers only.** `markers` and `split` entries only ever replace content between the
  page's own `<!-- cvsync:MARKER -->` ... `<!-- /cvsync:MARKER -->` comments. Hand-written
  content outside the markers is never touched.
- **The N-year rule.** `ref_year`, `recent_window` and `recent_label` in `mapping.yaml`
  drive every renderer's recent/history split; none of the three has a code default.
  `preview.py` warns when `ref_year` has fallen behind the current year.
- **Exclusions and status filtering.** `config/exclusions.yaml` removes named dossiers from
  any section (financement, implications, services, distinctions - both subkeys).
  `excluded_funding_statuses` removes funding records by status (e.g. an application still
  under review).
- **Editorial texts are opt-in.** An entry's `editorial_texts: true` plus an existing
  `config/contributions.yaml` are both required before any assistant-adjacent prose is
  injected; without both, rendering is strictly factual.
- **The anti-fabrication gate is built into the push.** `verify_titles.py`'s `verify_mapping`
  runs inside `push_wp.py` before any network call, in dry run and in `--apply` (D6): every
  `<strong>` title in the rendered HTML must exist in the parsed CV, the entry's own extras
  file, or an approved static seed.
- **Raw content only.** `push_wp.py` reads and writes `content.raw` (`context=edit`), never
  `content.rendered` - a block-editor page or one holding shortcodes survives the round trip.
- **Read-back after every write.** A PUT's outcome (including a timeout) is confirmed by
  reading the page back and comparing every block; `updated` means verified, not merely sent.
- **Every write is backed up first.** `push_wp.py` snapshots a page's `content.raw` exactly as
  read, to `<data-dir>/backups/page-<id>-<timestamp>.html`, immediately before its PUT - so a
  hand-edit this push overwrites can still be restored by hand. Skipped on a dry run.
- **One-shot.** Once a page has been migrated, the website is the source of truth for it.
  Re-running this skill over content the researcher has since edited by hand is a mistake
  the agent is built to catch (`push_wp.py`'s dry run shows `would-change` on content that
  should have been left alone).
- **Secrets never printed.** `WP_APP_PASSWORD` and any cookie value stay out of every log
  line, exception message and `--json` report.

## Known limitations

- `markers` and `replace` entries are outside the anti-fabrication gate's PER-TITLE coverage
  (their generic HTML puts arbitrary JSON keys in `<strong>`, which the gate cannot
  distinguish from a title); they are reported `not_covered` rather than title-checked. They
  ARE still scanned for a denylisted sensitive key reachable anywhere in their `cv_path`
  subtree (`sensitive_keys.json`, PR #50 review, H1) - a structural check, not a judgment
  that the rendered text is genuine. That gap is accepted rather than closed by cutting these
  two modes to `split` only: the operator confirmed they stay, since a researcher's own
  static page content (`replace`) and hand-placed blocks (`markers`) have no model-written
  text to fabricate in the first place - the anti-fabrication gate exists for `split`'s
  CV-driven renderers, where a wrong extras-file scope was the actual 2026-09-30 incident.
- French and English section/field labels of a CIHR/CCV generic-cv export are recognised
  (`cihr_labels.json`); an XML whose sections carry neither parses to zero records and
  refuses to publish (`cihr_cv.py` exits 1 rather than pushing "0 subventions"). The English
  strings are proven only against a fictitious fixture built from them, not a live export -
  verify against one before relying on a label outside that fixture's coverage.
- `render_phq` is a pure, fully tested function with no caller in this phase (D3): it is
  ready for Phase 2 to wire up, but nothing in this skill invokes it. Kept deliberately (PR #50
  review, M8): it is forward-built infrastructure for a named future phase, not dead code -
  removing it would mean re-deriving and re-testing the same six-year-window/alumni-ordering
  contract when Phase 2 lands.
- `discover.py`'s pagination boundary (stopping on a 400 past the first page, spec section
  "fetch_pages") is not proven exact against every WordPress version's own off-by-one
  behaviour at the final page (PR #50 review, L4); accepted as a residual rather than fixed,
  since the empty-or-short-batch check already stops correctly in the common case and a
  wrong boundary here degrades to one extra or missing page in `config/pages.json`, caught at
  Step 2's researcher confirmation before anything is pushed.

## Layout

- `scripts/wp_errors.py`, `wp_config.py`, `wp_paths.py`, `wp_common.py` - exceptions, the
  `{value, provenance}` config reader, data-folder containment, shared helpers and the
  bounded HTTP client.
- `scripts/cihr_cv.py` - CIHR/CCV generic-cv XML -> JSON (no supervision parser, D2), reading
  `scripts/cihr_labels.json`'s French/English label synonym table.
- `scripts/parse_cv.py` - generic XML -> JSON, for a non-CIHR export.
- `scripts/render.py` - the HTML renderers (financement, implications, services,
  distinctions, and `render_phq` for Phase 2) plus `render_entry`, the only function that
  reads `config/`.
- `scripts/verify_titles.py` - the anti-fabrication gate, reading `scripts/sensitive_keys.json`
  for its `markers`/`replace` denylist scan.
- `scripts/push_wp.py` - mapping validation, page planning, and the push itself.
- `scripts/discover.py` - list WordPress pages (id, slug, title, link).
- `scripts/preview.py` - offline report of what `push_wp.py` would change.
- `templates/mapping.example.yaml`, `templates/cookies.json.example` - fictitious starting
  points; copy into `<data-dir>/config/` and adapt.
- `scripts/Test/` - offline tests, no network, no real data folder.

## Tests

```bash
for f in .claude/skills/wp-portfolio-sync/scripts/Test/test_*.py; do python "$f"; done
```
