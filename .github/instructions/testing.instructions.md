---
applyTo: "**"
---

# Testing

General testing guidance for any project in this workspace. When a project ships its own
test suite, run it from the correct environment before pushing; there is no CI/CD pipeline,
so tests are run manually.

## Principle

- Test the behavior that matters: a script's contract (inputs, outputs, error paths), not
  its internals.
- Prefer fast, deterministic tests. Patch slow or network-bound dependencies (model loads,
  remote APIs) with fixtures so the suite runs offline where possible.
- Use tolerance-based comparison for floats (e.g. `assertAlmostEqual`, `places=2`).
- Document an expected timeout in a comment for any long-running test.

## Environments

- Use the project's own virtual environment for the layer you are working in (a repo may
  have more than one `.venv`). Activate it before running scripts or tests.
- Never mix dependencies across environments.

## ResearchTools script surface

The runnable code in this repo is the skill scripts under `.claude/skills/*/scripts/`. To
exercise them, set the required environment variables, then dry-run the entry points:

- `scopus` skill: `scopus_api.py` (Scopus REST client), `bib_batch.py` (batch
  title-to-DOI resolution, enrichment, grading, BibTeX generation), `semantic_scholar_api.py`
  (fallback + `external_ids_for_doi`), `download_pdf.py` (any-format full-text retrieval:
  Elsevier/S2 PDF, then Unpaywall/arXiv/PMC/landing HTML, then an opt-in browser tier),
  `browser_fetch.py` (tier 8: a real Playwright Chromium for challenge-gated publishers,
  with a per-paper `refs/_sources.json` override URL), and the cross-review cores
  (`gemini_reviewer.py`, `github_reviewer.py`, `gemini_table.py`).
- `extract-statistic` skill: `extract_text.py` (`--stats-scan` and `--section-scan`; pluggable
  Markdown backend Docling -> pymupdf4llm/MarkItDown -> tag-strip). The `extract-futureworks`
  skill ships no script of its own and reuses `extract_text.py --section-scan`.
- `deliberation` skill: `deliberate.py` (two-round Gemini/Copilot debate).
- `word2latex` skill: `docx_inspect.py`, `manuscript_bib.py`.

Offline unit tests (no network, no API key, no model load; run with the project Python):

```powershell
python .claude/skills/scopus/scripts/Test/test_download_pdf.py            # any-format tiers (incl. publisher/curl), tier-8 wiring, _sources.json, HTML validation
python .claude/skills/scopus/scripts/Test/test_browser_fetch.py           # tier 8: real-PDF capture / no-print / paywall / override with Playwright mocked
python .claude/skills/scopus/scripts/Test/test_bib_batch.py               # title match, venue grading, BibTeX invariants
python .claude/skills/extract-statistic/scripts/Test/test_section_scan.py # scan_sections / section-scan
```

The `test_download_pdf.py` suite patches `requests.get`, so the Unpaywall/arXiv/PMC tiers and the
HTML fetch are exercised with no network. `test_browser_fetch.py` replaces the Playwright sync API
with fakes and forces `_PW_OK`, so the browser tier's four branches run without installing Chromium.
The section-scan suite works on plain strings, so the
heavy Docling/MarkItDown imports never load.

### Required / optional environment variables

| Variable | Status | Used for |
|---|---|---|
| `SCOPUS_API_KEY` (or `.claude/skills/scopus/.scopus_key`) | Required | All Scopus search, validation, and PDF retrieval |
| `UNPAYWALL_EMAIL` (or `--email`) | Optional | Unpaywall open-access tier in `download_pdf.py` (HTML/PDF fallback) |
| `GEMINI_API_KEY` | Optional | Gemini cross-review and table enrichment |
| `GITHUB_TOKEN` | Optional | GPT cross-review via GitHub Models |
| `S2_API_KEY` (or `SEMANTIC_SCHOLAR_API_KEY`) | Optional | Semantic Scholar backfill (else throttled public pool) |

Scopus access needs a campus network or active VPN unless an `--insttoken` is supplied.

## Documentation of test results

When adding or modifying tests:
1. Update docstrings to reference any related documentation (formulas, validation rules).
2. If a test validates a published equation, link to its canonical reference in a comment.
3. State the expected timeout for long-running tests in a comment.

## No CI/CD

There is no automated pipeline. Run the relevant tests manually before pushing.
