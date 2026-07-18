# Design — Playwright browser PDF fallback tier for `download_pdf.py`

Date: 2026-07-18
Status: approved (brainstorming), pending implementation plan
Scope: `.claude/skills/scopus/scripts/` (scopus skill full-text retrieval pipeline)

## Context and problem

`download_pdf.py` retrieves full text for validated references through an ordered
chain of tiers (Elsevier API, Semantic Scholar OA, publisher PDF, Unpaywall,
arXiv, PMC, DOI landing HTML). For the `IEEE_TCAS_I/litreview` corpus, 16
references remain unrecoverable. Diagnosis on the UQAC VPN established:

- The egress IP is entitled (AS54606, Université du Québec à Chicoutimi) — the
  institution grants access **by IP**, with no per-site login.
- Every publisher nonetheless blocks a headless HTTP client with an *active*
  browser challenge that `requests`, system `curl`, and `curl_cffi` cannot pass:
  IEEE returns an Akamai `HTTP 202` JS sensor challenge; Taylor & Francis returns
  a Cloudflare `HTTP 403` managed challenge; Springer runs an IDP cookie
  handshake that a scripted client drops. No paper has a green-OA/arXiv/PMC copy.

A real browser passes these challenges automatically. Because access is
IP-based, a browser on the VPN needs **no credentials** — it simply navigates,
lets the challenge resolve, and receives the entitled PDF. The goal is a
last-resort browser tier that recovers these papers and stays reusable for
future corpora.

Non-goals (YAGNI): SSO/Shibboleth login, credential or cookie persistence,
`storage_state`, browser automation for anything other than reaching an
IP-entitled PDF. If a future corpus needs SSO, a gitignored `storage_state` is a
documented future extension, not part of this work.

## Chosen approach

Approach A: a separate sibling module `browser_fetch.py` that owns all Playwright
logic, wired into `download_pdf.py` as a new opt-in last-resort **tier 8**. This
isolates the heavy async browser dependency in its own testable unit and mirrors
the existing `semantic_scholar_api` sibling-module pattern; `download_pdf.py`
stays a thin orchestrator. (Rejected: inlining the tier — bloats a 1215-line file
and mixes async Playwright with the sync `requests` pipeline; a standalone script
— duplicates manifest/failed/filename logic and breaks the single-pipeline UX.)

## Architecture

```
download_pdf.py (sync orchestrator)
  download_one(entry, ..., use_browser=False, headed=True)
    tier 0 present ─ tier 1 elsevier ─ ... ─ tier 7 landing html
    tier 8 browser  ──guarded by use_browser + browser_fetch.browser_available()──▶
                                                        browser_fetch.py
                                                          fetch_pdf_via_browser(doi, dest, ...)
                                                            Playwright sync API → Chromium
```

The browser tier runs only when both `--browser` is passed AND Playwright + its
Chromium are installed. It is always the final tier, attempted after every
lighter tier has failed.

## Components and interfaces

### `browser_fetch.py` (new)

- Optional Playwright import at module load, matching the `curl_cffi` pattern in
  `download_pdf.py` (a `try/except ImportError` that sets an availability flag).
- `browser_available() -> bool` — True only if Playwright imports AND a Chromium
  executable is resolvable; otherwise False (caller skips the tier with a hint).
- `fetch_pdf_via_browser(doi: str, dest: str, *, headed: bool = True, timeout_s: int = 60) -> dict | None`
  - Launch Chromium (bundled), one context, one page.
  - Attach a **response listener** that buffers the body of any response whose
    `content-type` contains `application/pdf`, and a **download listener** for
    attachment-style PDFs.
  - Navigate `https://doi.org/{doi}`; wait for network idle so the JS challenge
    resolves.
  - Resolve the PDF URL: read the `citation_pdf_url` meta from the DOM, plus a
    per-publisher hint — IEEE `stamp.jsp?arnumber=<n>` (arnumber scraped from the
    `/document/<n>/` URL), Taylor & Francis `/doi/pdf/<doi>`, Springer
    `/content/pdf/<doi>.pdf`, ASME equivalent. Navigate to / click it.
  - If a PDF was captured → validate `%PDF` magic bytes → atomic save →
    return `{"format": "pdf", "source": "browser", "file": <name>}`.
  - Else if the page is an HTML article **with no paywall markers** →
    `page.pdf()` print-to-PDF → save → return `{"source": "browser-print", ...}`.
  - Else (paywall markers, or nothing) → return `None`. Never save a paywall page.
- Returns are plain dicts so `download_pdf.py` needs no Playwright types.

### `download_pdf.py` (edits)

- Optional import of `browser_fetch` (defensive `try/except`, like `s2`).
- `download_one(...)` gains keyword args `use_browser: bool = False`,
  `headed: bool = True`; adds tier 8 after tier 7, guarded by
  `use_browser and browser_fetch and browser_fetch.browser_available()`.
- CLI: `--browser` (enable tier 8) and `--headless` (default is headed) added to
  both the `doi` and `bib` subparsers; `_run_doi` / `_run_bib` thread the flags
  into `download_one`.
- New helper `_write_validated_bytes(data: bytes, dest: str) -> bool` sharing the
  `%PDF` magic-byte check, `MAX_PDF_BYTES` cap, and atomic `.part` + `os.replace`
  logic already in `_write_validated` (which consumes a streaming response, so a
  bytes-input sibling is needed). Prefer refactoring the common core into one
  private routine both call.
- `download_one` status list documents the new `browser` and `browser-print`
  sources; `write_manifest` / `write_failed` already generalize over the source
  string.
- Filenames continue to use `target_filename` (`<citekey>.pdf`), unchanged.

## Data flow (one paper, tier 8)

1. Tiers 0–7 all fail for `<doi>`.
2. `download_one` calls `browser_fetch.fetch_pdf_via_browser(doi, dest, headed)`.
3. Chromium navigates to the DOI, passes the challenge, reaches the article.
4. Publisher PDF response captured → magic-byte validated → written atomically.
5. Result dict flows back into the normal `_result` assembly → `_manifest.json`
   and (if still failed) `_failed.md`, exactly like every other tier.

## Error handling

- Playwright / Chromium absent → `browser_available()` False → tier skipped with
  a one-line stderr hint (`run: pip install playwright && playwright install
  chromium`). Base pipeline unaffected.
- Per-paper navigation wrapped in try/except with a Playwright timeout; any
  failure returns `None` so one paper never aborts a batch.
- Reuse `HTML_BLOCK_MARKERS` to detect a paywall/login/captcha page and refuse
  the print-to-PDF fallback on it.
- Chromium launch failure surfaces the actionable install message.

## Headed vs headless

Default **headed** (visible window) for maximum reliability against challenge
managers, which flag headless more aggressively; `--headless` is opt-in. The user
runs on a Windows desktop with a display, so headed is practical.

## Dependencies and security

- Add `playwright` to `requirements.txt` as an **optional** dependency, documented
  in the same style as `curl_cffi` (the tier degrades to skipped when absent).
  Pin the version and `pip-audit` it before install; the Chromium binary is
  installed separately via `playwright install chromium` (not a pip artifact).
- **No credentials, cookies, tokens, or `storage_state` are written to disk** —
  access is IP-based. Nothing new needs gitignoring. This automates the user's
  own IP-entitled institutional access (legitimate use).
- No secret is logged; the module logs only the DOI and the tier outcome.

## Testing (offline; no real browser, no network)

- New `Test/test_browser_fetch.py`: patch the Playwright entry point that
  `browser_fetch` imports, and drive three cases — (a) a captured
  `application/pdf` body → bytes validated and file written; (b) HTML-only page,
  no paywall markers → print-to-PDF path taken; (c) page with a paywall marker →
  returns `None`, nothing written.
- `Test/test_download_pdf.py` additions: tier 8 skipped when `use_browser` is
  False; skipped when `browser_available()` is patched False; invoked and yields
  `status == "browser"` when both are true (browser_fetch mocked).
- Reuse the existing `FakeResponse` / `mock.patch.object` / `TemporaryDirectory`
  patterns. No Chromium download in CI-less local runs.

## Documentation to update

- `download_pdf.py` module docstring: tier count 8 → 9, describe tier 8 and the
  `--browser` / `--headless` flags, note the optional Playwright dependency and
  `playwright install chromium`.
- `README.md` scopus script-surface line: mention the browser tier.
- `.claude/rules/testing.md`: add the `test_browser_fetch.py` unit-test line and
  its offline (mocked-Playwright) property.
- `requirements.txt`: the optional-`playwright` note.

## Acceptance

- With `--browser` on the UQAC VPN, the 16 failed papers are attempted through a
  real Chromium; recovered PDFs land in `refs/` as `<citekey>.pdf`, `_manifest.json`
  marks them `browser` (or `browser-print`), and `_failed.md` shrinks accordingly.
- Offline unit tests pass with Playwright absent (tier cleanly skipped) and with
  Playwright mocked (three save/skip cases).
- The base pipeline behaves identically when `--browser` is not passed.
