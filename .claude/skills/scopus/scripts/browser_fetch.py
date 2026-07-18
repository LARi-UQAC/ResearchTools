"""
browser_fetch.py - Tier 8 (last-resort) full-text retrieval through a real browser.

The lighter tiers of download_pdf.py use plain HTTP (requests / curl / curl_cffi).
Some publishers block every headless HTTP client with an *active* browser
challenge (Akamai's JS sensor, Cloudflare's managed challenge) or an SSO cookie
handshake that a scripted client drops, even from an IP-entitled institutional
network. A real browser passes these automatically, so this module drives a
Playwright Chromium: it navigates to the article (or to a user-supplied override
URL such as a ResearchGate page for a paper the institution has no subscription
to), lets the challenge resolve, captures the entitled PDF, and falls back to
print-to-PDF for an HTML-only article.

Design notes:
    - Optional dependency: Playwright is imported defensively (mirrors curl_cffi
      in download_pdf.py). When it is absent, browser_available() returns False
      and download_pdf.py skips tier 8 with a one-line hint. The base pipeline
      keeps working without it.
    - No credentials, cookies, or session state are persisted. Institutional
      access here is IP-based; the browser only needs to reach the entitled IP
      and pass the JS challenge. ResearchGate (and any override host) is
      best-effort: a login wall or captcha trips the block-marker guard and the
      paper is left for manual retrieval.
    - Self-contained: this module does NOT import download_pdf (that would be a
      circular import), so it re-declares the small set of constants and the
      atomic PDF writer it needs. The block-marker list parallels
      download_pdf.HTML_BLOCK_MARKERS with a few ResearchGate-specific additions.
    - print-to-PDF (page.pdf()) is only supported by Chromium in headless mode.
      Because the default run is headed (more reliable against challenge managers),
      the print fallback is effectively available only under --headless; the
      primary real-PDF capture path works in both modes.

See .claude/rules/security.md for the file-write and input-validation rules this
script follows.
"""

import logging
import os
import re
from urllib.parse import urljoin, urlparse

logger = logging.getLogger(__name__)

# Optional Playwright import, matching the curl_cffi pattern in download_pdf.py:
# the whole tier degrades to "skipped with a hint" when the library is absent.
try:
    from playwright.sync_api import sync_playwright
    from playwright.sync_api import Error as _PWError  # base Playwright error
    _PW_OK = True
except ImportError:  # pragma: no cover - optional dependency
    sync_playwright = None
    _PWError = Exception
    _PW_OK = False

PDF_MAGIC = b"%PDF"
MAX_PDF_BYTES = 100 * 1024 * 1024  # 100 MB cap, matching download_pdf.py
NAV_TIMEOUT_S = 60                 # per-navigation timeout
IDLE_TIMEOUT_S = 20                # extra wait for the JS challenge to settle

# A desktop Chrome profile string; a genuine engine drives it, so this only sets
# the advertised UA.
BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# Markers that betray a paywall, login wall, or bot challenge instead of the
# article body: their presence forbids the print-to-PDF fallback (the HTML
# analogue of the %PDF magic check). Parallels download_pdf.HTML_BLOCK_MARKERS
# with ResearchGate's author-gated "request full-text" wording added.
BLOCK_MARKERS = (
    "access denied", "acces refuse", "please sign in", "sign in to",
    "log in to", "purchase pdf", "buy this article", "get access",
    "subscribe to", "institutional login", "captcha", "are you a robot",
    "enable javascript", "cloudflare", "just a moment", "403 forbidden",
    "404 not found", "page not found", "request unsuccessful",
    "request full-text", "request full text",
)


def _clean_doi(doi: str) -> str:
    """Strip any DOI URL prefix and surrounding whitespace (local copy so the
    module stays independent of download_pdf)."""
    doi = (doi or "").strip()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:", "DOI:"):
        if doi.lower().startswith(prefix.lower()):
            doi = doi[len(prefix):]
            break
    return doi.strip()


def _save_pdf_bytes(data: bytes, dest: str) -> bool:
    """
    --------------------------------------------------------------------------
    Purpose:
        Validate an in-memory byte string as a real PDF and write it atomically
        to `dest`. The first bytes must be the %PDF magic number and the body
        must stay under the size cap. A temporary *.part file is renamed into
        place only after a complete, validated write (mirrors
        download_pdf._write_validated for a bytes source rather than a stream).

    Inputs:
        data (bytes): the candidate PDF bytes (from a captured response, a
            download, or page.pdf()).
        dest (str): final destination path for the PDF.

    Outputs:
        ok (bool): True when a valid PDF was written; False otherwise (no partial
        file is left behind).
    --------------------------------------------------------------------------
    """
    if not data or not data.startswith(PDF_MAGIC):
        logger.warning("[BROWSER] not a PDF (magic mismatch) - discarded")
        return False
    if len(data) > MAX_PDF_BYTES:
        logger.warning("[BROWSER] exceeds %d-byte cap - discarded", MAX_PDF_BYTES)
        return False
    tmp = f"{dest}.part"
    try:
        with open(tmp, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, dest)
        return True
    except OSError as exc:
        logger.warning("[BROWSER] write failed for %s: %s", dest, exc)
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass
        return False


def _abs_https(href: str, base: str) -> str | None:
    """Resolve `href` against `base` and return it only if the result is https."""
    if not href:
        return None
    resolved = urljoin(base or "", href)
    return resolved if urlparse(resolved).scheme == "https" else None


def _discover_pdf_url(page, doi: str, override_url: str | None) -> str | None:
    """
    --------------------------------------------------------------------------
    Purpose:
        From the loaded page, work out a direct PDF URL to navigate to when the
        initial navigation did not itself yield a PDF response. Prefers the
        Highwire citation_pdf_url meta tag, then an override-host download link
        (ResearchGate "Download full-text", any .pdf anchor), then a per-publisher
        pattern reconstructed from the DOI.

    Inputs:
        page: the Playwright page (already navigated).
        doi (str): the cleaned DOI (used for the publisher patterns).
        override_url (str | None): the user-supplied entry URL, if any.

    Outputs:
        url (str | None): an https PDF URL to try, or None when none is found.
    --------------------------------------------------------------------------
    """
    try:
        cur = page.url or ""
    except _PWError:
        cur = ""

    # 1. citation_pdf_url meta - the generic route most publishers expose.
    try:
        meta = page.get_attribute('meta[name="citation_pdf_url"]', "content")
    except _PWError:
        meta = None
    hit = _abs_https(meta, cur) if meta else None
    if hit:
        return hit

    # 2. Override host (ResearchGate / author page / repository): a visible
    #    full-text download control or a direct .pdf anchor.
    if override_url:
        for sel in (
            'a[href$=".pdf"]',
            'a[href*="/download"]',
            'a:has-text("Download full-text")',
            'a:has-text("Download full text")',
        ):
            try:
                el = page.query_selector(sel)
            except _PWError:
                el = None
            if el:
                try:
                    href = el.get_attribute("href")
                except _PWError:
                    href = None
                hit = _abs_https(href, cur) if href else None
                if hit:
                    return hit
        return None

    # 3. Per-publisher pattern reconstructed from the DOI / current URL.
    d = _clean_doi(doi)
    if "ieeexplore.ieee.org" in cur:
        match = re.search(r"/document/(\d+)", cur)
        if match:
            return ("https://ieeexplore.ieee.org/stamp/stamp.jsp"
                    f"?tp=&arnumber={match.group(1)}")
    if d.startswith("10.1080/"):
        return f"https://www.tandfonline.com/doi/pdf/{d}"
    if d.startswith("10.1007/"):
        return f"https://link.springer.com/content/pdf/{d}.pdf"
    return None


def browser_available() -> bool:
    """True when Playwright is importable (its Chromium is verified lazily at
    launch; a missing browser surfaces an actionable install hint then)."""
    return _PW_OK


def fetch_pdf_via_browser(doi: str, dest: str, *, override_url: str | None = None,
                          headed: bool = True, timeout_s: int = NAV_TIMEOUT_S) -> dict | None:
    """
    --------------------------------------------------------------------------
    Purpose:
        Retrieve a paper's full-text PDF with a real Chromium. Navigates to the
        override URL when supplied, else to the DOI; passes the JS/SSO challenge
        a plain HTTP client cannot; captures the publisher PDF (network response
        or download) and, for an HTML-only article with no paywall markers, falls
        back to print-to-PDF (headless only).

    Inputs:
        doi (str): the DOI (used to build the doi.org entry URL and publisher
            PDF patterns).
        dest (str): destination path for the PDF (filename decided by the caller).
        override_url (str | None): a user-supplied full-text URL to fetch instead
            of the DOI (ResearchGate, author page, repository, preprint).
        headed (bool): run a visible browser (default True, more reliable against
            challenge managers). print-to-PDF fallback needs headless.
        timeout_s (int): per-navigation timeout in seconds.

    Outputs:
        result (dict | None): {"format": "pdf", "source": <s>, "file": <name>}
        where <s> is "override" (override URL used), "browser" (DOI real PDF), or
        "browser-print" (HTML print fallback); None when nothing usable was
        obtained (paper stays failed / manual).
    --------------------------------------------------------------------------
    """
    if not _PW_OK:
        logger.info("[BROWSER] Playwright not installed - tier skipped "
                    "(run: pip install playwright && playwright install chromium)")
        return None

    entry_url = override_url or f"https://doi.org/{_clean_doi(doi)}"
    if urlparse(entry_url).scheme != "https":
        logger.warning("[BROWSER] refusing non-https URL: %s", entry_url)
        return None
    source = "override" if override_url else "browser"
    captured: dict[str, bytes | None] = {"data": None}

    def _on_response(resp) -> None:
        if captured["data"] is not None:
            return
        try:
            ctype = (resp.headers or {}).get("content-type", "").lower()
            if "application/pdf" in ctype:
                body = resp.body()
                if body and body.startswith(PDF_MAGIC):
                    captured["data"] = body
        except _PWError:
            pass
        except Exception:  # pragma: no cover - listener must never raise
            pass

    def _on_download(download) -> None:
        if captured["data"] is not None:
            return
        try:
            path = download.path()
            if path and os.path.exists(path):
                with open(path, "rb") as handle:
                    body = handle.read()
                if body.startswith(PDF_MAGIC):
                    captured["data"] = body
        except _PWError:
            pass
        except Exception:  # pragma: no cover
            pass

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=not headed)
            try:
                context = browser.new_context(accept_downloads=True, user_agent=BROWSER_UA)
                page = context.new_page()
                page.set_default_timeout(timeout_s * 1000)
                page.on("response", _on_response)
                page.on("download", _on_download)

                page.goto(entry_url, wait_until="domcontentloaded")
                try:
                    page.wait_for_load_state("networkidle", timeout=IDLE_TIMEOUT_S * 1000)
                except _PWError:
                    pass  # challenge pages often never reach full idle

                # If the entry navigation did not itself deliver a PDF, resolve a
                # direct PDF URL and navigate to it (the response listener catches
                # the resulting application/pdf, including an embedded viewer's).
                if captured["data"] is None:
                    pdf_url = _discover_pdf_url(page, doi, override_url)
                    if pdf_url:
                        try:
                            page.goto(pdf_url, wait_until="domcontentloaded")
                            page.wait_for_timeout(1500)
                        except _PWError:
                            pass

                if captured["data"] is not None:
                    ok = _save_pdf_bytes(captured["data"], dest)
                    return ({"format": "pdf", "source": source,
                             "file": os.path.basename(dest)} if ok else None)

                # HTML-only fallback: print-to-PDF unless the page is a
                # paywall/login/challenge stub. Chromium only supports page.pdf()
                # in headless mode, so this path is inert under --headed.
                try:
                    html = (page.content() or "").lower()
                except _PWError:
                    html = ""
                if html and not any(marker in html for marker in BLOCK_MARKERS):
                    try:
                        pdf_bytes = page.pdf()
                    except _PWError as exc:
                        logger.info("[BROWSER] print-to-PDF unavailable "
                                    "(headed mode?): %s", exc)
                        pdf_bytes = None
                    if pdf_bytes and _save_pdf_bytes(pdf_bytes, dest):
                        return {"format": "pdf", "source": "browser-print",
                                "file": os.path.basename(dest)}
                return None
            finally:
                browser.close()
    except _PWError as exc:
        logger.warning("[BROWSER] failed for %s: %s", override_url or doi, exc)
        return None
    except Exception as exc:  # pragma: no cover - Chromium launch / unexpected
        logger.warning("[BROWSER] error for %s: %s", override_url or doi, exc)
        return None
