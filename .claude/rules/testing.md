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

- `scopus` skill: `scopus_api.py` (Scopus REST client), `semantic_scholar_api.py`
  (fallback), `download_pdf.py` (full-text retrieval), and the cross-review cores
  (`gemini_reviewer.py`, `github_reviewer.py`, `gemini_table.py`).
- `deliberation` skill: `deliberate.py` (two-round Gemini/Copilot debate).
- `word2latex` skill: `docx_inspect.py`, `manuscript_bib.py`.

### Required / optional environment variables

| Variable | Status | Used for |
|---|---|---|
| `SCOPUS_API_KEY` (or `.claude/skills/scopus/.scopus_key`) | Required | All Scopus search, validation, and PDF retrieval |
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
