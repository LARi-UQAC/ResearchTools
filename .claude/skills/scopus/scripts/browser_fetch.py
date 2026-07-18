"""
browser_fetch.py - Tier 8 (last-resort) full-text retrieval through a real browser.

The lighter tiers of download_pdf.py use plain HTTP (requests / curl / curl_cffi).
Some publishers block every headless HTTP client with an *active* browser
challenge (Akamai's JS sensor, Cloudflare's managed challenge) or an SSO cookie
handshake that a scripted client drops, even from an IP-entitled institutional
network. A real browser passes these automatically, so this module drives a
Playwright Chromium: it navigates to the article (or to a user-supplied override
URL such as a ResearchGate page for a paper the institution has no subscription
to), lets the challenge resolve, and captures the entitled publisher PDF (network
response or download).

The tier only ever saves a byte-validated %PDF. It does NOT print the rendered
page to PDF: on challenge-gated publishers the reachable page is a blank
challenge shell or a landing/abstract page, and a print-to-PDF of it is
indistinguishable junk that would pollute the corpus (observed in practice -
blank 1-page prints and Springer landing pages were saved as "papers"). A paper
with no capturable real PDF is left failed / for manual retrieval.

Design notes:
    - Optional dependency: Playwright is imported defensively (mirrors curl_cffi
      in download_pdf.py). When it is absent, browser_available() returns False
      and download_pdf.py skips tier 8 with a one-line hint. The base pipeline
      keeps working without it.
    - No credentials, cookies, or session state are persisted. Institutional
      access here is IP-based; the browser only needs to reach the entitled IP
      and pass the JS challenge. ResearchGate (and any override host) is
      best-effort: a login wall or captcha simply yields no PDF and the paper is
      left for manual retrieval.
    - Self-contained: this module does NOT import download_pdf (that would be a
      circular import), so it re-declares the small set of constants and the
      atomic PDF writer it needs.

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
ASSIST_WAIT_S = 45                 # headed: time for a human to accept cookies /
#                                    solve a visible challenge; polled, breaks
#                                    the instant a PDF is captured
POLL_S = 1.5                       # poll interval while waiting for the PDF

# A desktop Chrome profile string; a genuine engine drives it, so this only sets
# the advertised UA.
BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
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

    # 3. IEEE: the article URL carries the arnumber; the stamp page embeds the PDF.
    if "ieeexplore.ieee.org" in cur:
        match = re.search(r"/document/(\d+)", cur)
        if match:
            return ("https://ieeexplore.ieee.org/stamp/stamp.jsp"
                    f"?tp=&arnumber={match.group(1)}")
    return None


def _doi_pattern_url(doi: str) -> str | None:
    """
    --------------------------------------------------------------------------
    Purpose:
        A direct PDF / reader URL derivable from the DOI alone, with no page
        loaded. Navigating straight to it avoids the extra article-page hop, and
        every hop can re-trigger a Cloudflare/Akamai challenge.

    Inputs:
        doi (str): the DOI.

    Outputs:
        url (str | None): the reader/PDF URL, or None when no pattern applies.
    --------------------------------------------------------------------------
    """
    d = _clean_doi(doi)
    if d.startswith("10.1080/"):
        # The Taylor & Francis /doi/pdf direct link is Cloudflare-403'd, but the
        # /doi/epdf reader streams the file as an application/pdf response
        # (/doi/pdfdirect) on load, which the response listener catches.
        return f"https://www.tandfonline.com/doi/epdf/{d}?needAccess=true"
    if d.startswith("10.1007/"):
        return f"https://link.springer.com/content/pdf/{d}.pdf"
    return None


def _click_download_button(pg, captured: dict) -> None:
    """In a viewer/reader page, click an explicit Download control and keep the
    downloaded file if it is a PDF. Used after a 'View PDF' click opens a reader
    (e.g. Taylor & Francis /doi/epdf) that streams the file only on Download."""
    for sel in ('a:has-text("Download PDF")', 'button:has-text("Download PDF")',
                'a:has-text("Download")', 'button:has-text("Download")',
                '[aria-label*="Download" i]', 'a[download]', 'a[href*="/doi/pdf"]'):
        if captured["data"] is not None:
            return
        try:
            el = pg.query_selector(sel)
        except _PWError:
            el = None
        if not el:
            continue
        try:
            with pg.expect_download(timeout=15000) as info:
                el.click()
            download = info.value
            path = download.path()
            if path and os.path.exists(path):
                with open(path, "rb") as handle:
                    body = handle.read()
                if body.startswith(PDF_MAGIC):
                    captured["data"] = body
                    return
        except _PWError:
            # The click may instead stream the PDF as a response (caught by the
            # context listener); give it a moment, then move on.
            try:
                pg.wait_for_timeout(1500)
            except _PWError:
                pass


def _try_click_through(page, captured: dict) -> None:
    """
    --------------------------------------------------------------------------
    Purpose:
        Reproduce the human "View PDF / Download PDF" flow from an article page:
        click the PDF control, follow a viewer that opens in a popup tab, and
        click its Download button. This carries the passed-challenge session that
        a direct GET of /doi/pdf lacks (the Taylor & Francis case: a direct
        /doi/pdf is Cloudflare-403'd, but the click-through succeeds). Any PDF
        that results is stored in captured["data"] by the context/page response
        and download listeners, or by _click_download_button.

    Inputs:
        page: the loaded Playwright article page.
        captured (dict): shared {"data": bytes | None} sink.

    Outputs:
        none (mutates captured in place).
    --------------------------------------------------------------------------
    """
    for sel in ('a[href*="/doi/epdf"]', 'a:has-text("View PDF")',
                'button:has-text("View PDF")', 'a:has-text("Download PDF")',
                'button:has-text("Download PDF")', 'a:has-text("Full Text PDF")'):
        if captured["data"] is not None:
            return
        try:
            el = page.query_selector(sel)
        except _PWError:
            el = None
        if not el:
            continue
        popup = None
        try:
            with page.expect_popup(timeout=8000) as info:
                el.click()
            popup = info.value
        except _PWError:
            popup = None  # click navigated the same tab, or opened nothing
        target = popup or page
        try:
            target.wait_for_load_state("domcontentloaded")
            target.wait_for_timeout(2500)  # let the viewer stream its PDF
        except _PWError:
            pass
        if captured["data"] is not None:
            return
        _click_download_button(target, captured)


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
        or download). Saves only a byte-validated %PDF - never a print-to-PDF of
        the rendered page (that produced blank/landing-page false positives).

    Inputs:
        doi (str): the DOI (used to build the doi.org entry URL and publisher
            PDF patterns).
        dest (str): destination path for the PDF (filename decided by the caller).
        override_url (str | None): a user-supplied full-text URL to fetch instead
            of the DOI (ResearchGate, author page, repository, preprint).
        headed (bool): run a visible browser (default True, more reliable against
            challenge managers).
        timeout_s (int): per-navigation timeout in seconds.

    Outputs:
        result (dict | None): {"format": "pdf", "source": <s>, "file": <name>}
        where <s> is "override" (override URL used) or "browser" (DOI real PDF);
        None when no real PDF was captured (paper stays failed / manual).
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
    pdf_responses: list = []       # responses whose content-type is application/pdf
    pdf_urls: list = []            # their URLs, for a full (non-ranged) re-fetch

    def _complete(data) -> bool:
        # A whole PDF starts with %PDF and carries an %%EOF trailer near the end.
        # Readers stream the file in HTTP ranges, so a single response body can be
        # a valid-looking but truncated chunk; require the trailer to reject it.
        return bool(data) and data.startswith(PDF_MAGIC) and b"%%EOF" in data[-4096:]

    def _note_response(resp) -> None:
        # Do NOT read the body inside the event handler: in the sync API
        # Response.body() there is unreliable. Collect the response and its URL
        # and read them once the page has settled (see _drain).
        try:
            ctype = (resp.headers or {}).get("content-type", "").lower()
        except Exception:  # pragma: no cover - listener must never raise
            return
        if "application/pdf" in ctype:
            pdf_responses.append(resp)
            try:
                pdf_urls.append(resp.url)
            except Exception:  # pragma: no cover
                pass

    def _on_download(download) -> None:
        if captured["data"] is not None:
            return
        try:
            path = download.path()
            if path and os.path.exists(path):
                with open(path, "rb") as handle:
                    body = handle.read()
                if _complete(body):
                    captured["data"] = body
        except _PWError:
            pass
        except Exception:  # pragma: no cover
            pass

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                headless=not headed,
                args=["--disable-blink-features=AutomationControlled"])
            try:
                context = browser.new_context(accept_downloads=True, user_agent=BROWSER_UA)
                # Reduce the automation fingerprint: Cloudflare/Akamai re-challenge
                # every navigation when navigator.webdriver is true.
                try:
                    context.add_init_script(
                        "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});")
                except _PWError:  # pragma: no cover
                    pass
                page = context.new_page()
                page.set_default_timeout(timeout_s * 1000)
                page.on("response", _note_response)
                page.on("download", _on_download)

                # A "View PDF" click often opens the reader in a popup tab; wire
                # the same listeners onto any page the context opens.
                def _wire_popup(popup) -> None:
                    popup.on("response", _note_response)
                    popup.on("download", _on_download)
                context.on("page", _wire_popup)

                def _drain() -> bool:
                    """Keep the first COMPLETE PDF. First try each collected
                    response body; if all are partial (ranged), re-fetch the URL
                    in full through the context request API, which reuses the
                    solved-challenge cookies and sends no Range header."""
                    if captured["data"] is not None:
                        return True
                    for resp in list(pdf_responses):
                        try:
                            body = resp.body()
                        except Exception:  # pragma: no cover - evicted body
                            body = None
                        if _complete(body):
                            captured["data"] = body
                            return True
                    for url in list(dict.fromkeys(pdf_urls)):
                        try:
                            api = context.request.get(url, timeout=timeout_s * 1000)
                            body = api.body() if api.ok else None
                        except Exception:
                            body = None
                        if _complete(body):
                            captured["data"] = body
                            return True
                    return False

                def _settle() -> None:
                    # Wait for the network to settle, then poll for the streamed
                    # PDF. In headed mode the budget is generous so a user can
                    # accept cookies / solve a visible challenge once; returns the
                    # instant a PDF is captured.
                    try:
                        page.wait_for_load_state("networkidle",
                                                 timeout=IDLE_TIMEOUT_S * 1000)
                    except _PWError:
                        pass  # challenge / reader pages often never fully idle
                    budget_s = ASSIST_WAIT_S if headed else 3
                    for _ in range(max(1, int(budget_s / POLL_S))):
                        if _drain():
                            return
                        try:
                            page.wait_for_timeout(int(POLL_S * 1000))
                        except _PWError:
                            return

                # 1. Minimise navigations - each hop can re-trigger a challenge.
                #    For a publisher whose reader/PDF URL is known from the DOI
                #    alone (T&F /doi/epdf, Springer /content/pdf), go straight
                #    there; the streamed /doi/pdfdirect (or the PDF) is drained.
                pattern_url = None if override_url else _doi_pattern_url(doi)
                if pattern_url:
                    try:
                        page.goto(pattern_url, wait_until="domcontentloaded")
                    except _PWError:
                        pass
                    _settle()

                # 2. Otherwise (or if that missed) load the entry page, discover a
                #    PDF link from its DOM (citation_pdf_url, override download
                #    link, IEEE stamp), and finally click the human "View PDF"
                #    control. The generous waits let a headed user solve a
                #    visible "verify you are human" challenge.
                if captured["data"] is None:
                    try:
                        page.goto(entry_url, wait_until="domcontentloaded")
                    except _PWError:
                        pass
                    _settle()
                    # DOM-based PDF discovery is for a DOI landing page; skip it
                    # for an override host (already the target page) so we do not
                    # re-navigate and re-trigger its challenge.
                    if captured["data"] is None and not override_url:
                        page_url = _discover_pdf_url(page, doi, override_url)
                        if page_url and page_url != pattern_url:
                            try:
                                page.goto(page_url, wait_until="domcontentloaded")
                            except _PWError:
                                pass
                            _settle()
                    if captured["data"] is None:
                        _try_click_through(page, captured)
                        _settle()

                if captured["data"] is not None:
                    ok = _save_pdf_bytes(captured["data"], dest)
                    return ({"format": "pdf", "source": source,
                             "file": os.path.basename(dest)} if ok else None)

                # No real publisher PDF was captured. We deliberately do NOT print
                # the rendered page to PDF: on challenge-gated publishers the
                # reachable page is a blank challenge shell or a landing/abstract
                # page, and a print-to-PDF of it is indistinguishable junk that
                # would pollute the corpus. Leave the paper failed / for manual.
                logger.info("[BROWSER] no capturable PDF at %s - left for manual",
                            override_url or doi)
                return None
            finally:
                browser.close()
    except _PWError as exc:
        logger.warning("[BROWSER] failed for %s: %s", override_url or doi, exc)
        return None
    except Exception as exc:  # pragma: no cover - Chromium launch / unexpected
        logger.warning("[BROWSER] error for %s: %s", override_url or doi, exc)
        return None
