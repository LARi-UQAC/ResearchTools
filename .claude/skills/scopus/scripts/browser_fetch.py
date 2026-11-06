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
    - Session state IS persisted: the Chrome profile named by browser-fetch.json
      keeps a solved challenge and, for a host listed in `hosts`, an institutional
      sign-in, across papers and runs. The profile holds session cookies, so it
      stays outside the repository. No password is stored by this module: one is
      read from a secret provider (browser_login.py) for a single fill. Access is
      IP-based for most publishers, so a sign-in is attempted only for a listed
      host. ResearchGate (and any override host) is best-effort: a login wall or
      captcha simply yields no PDF and the paper is left for manual retrieval.
    - Self-contained: this module does NOT import download_pdf (that would be a
      circular import), so it re-declares the small set of constants and the
      atomic PDF writer it needs.

See .claude/rules/security.md for the file-write and input-validation rules this
script follows.
"""

import json
import logging
import os
import re
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))
import browser_login  # noqa: E402  (sibling module: provider and step vocabularies)

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

# curl_cffi downloads the PDF with the browser's own cookies once the owner has cleared
# the challenge (hybrid option of Issue #11). It reproduces Chrome's TLS fingerprint; it
# solves nothing. Optional, same degrade-with-a-hint contract as Playwright.
try:
    from curl_cffi import requests as _cffi_requests
    _CFFI_OK = True
except ImportError:  # pragma: no cover - optional dependency
    _cffi_requests = None
    _CFFI_OK = False

# No stealth or anti-detect LIBRARY (chosen 2026-11-05, open to change: Issue #11). ScienceDirect shows
# real Chrome 157 an interactive Cloudflare Turnstile checkbox (measured
# 2026-11-05) and answers the bundled Chromium with an interstitial that never
# clears (measured 2026-09-17). The answer is the installed Chrome and a human
# click. The launch still passes --disable-blink-features=AutomationControlled and
# a navigator.webdriver override (BrowserSession.context): two small tweaks, not a
# library, kept until the owner decides (Issue #11, open points). A plain Chrome
# with no driver shows the same checkbox (measured 2026-11-06), so they do not
# explain it.

PDF_MAGIC = b"%PDF"

# Every timeout, limit and host setting lives in browser-fetch.json beside this
# module, each with its provenance (R0, R4). The persistent browser profile it
# names keeps a solved challenge and an institutional session across papers in a
# run and across runs: a fresh context starts with no cookies, no history and no
# local storage, which is itself a bot signal. The directory is disposable
# (deleting it costs only the stored cookies) and is NOT placed in the
# repository, since it holds session cookies for the operator's institutional
# access.
CONFIG_PATH = _HERE / "browser-fetch.json"

_NUMBER_KEYS = ("nav_timeout_s", "idle_timeout_s", "human_window_s", "headless_wait_s",
                "poll_s", "popup_wait_s", "viewer_settle_s", "download_wait_s",
                "download_retry_pause_s", "step_timeout_s", "provider_timeout_s",
                "stream_chunk_bytes", "title_chars")
_REQUIRED_KEYS = _NUMBER_KEYS + ("max_pdf_bytes", "channel", "profile_dir", "user_agent",
                                 "secret_provider", "allow_totp_from_vault", "hosts",
                                 "challenge_title_markers", "challenge_selectors",
                                 "curl_impersonate", "max_redirects")
_config_cache: dict[str, dict[str, Any]] = {}


class BrowserRungError(Exception):
    """Rung 8 could not run for a named reason; download_pdf records it as an error."""


class BrowserConfigError(BrowserRungError, ValueError):
    """browser-fetch.json is missing, unreadable or holds a bad value (R3)."""


def _positive_number(value: Any) -> bool:
    """
    --------------------------------------------------------------------------
    Purpose:
        Tell whether a configuration value is a usable limit.

    Inputs:
        value (Any): the value read from browser-fetch.json.

    Outputs:
        ok (bool): True for an int or float above zero. A bool is not a number
        here, since JSON true would otherwise read as 1.
    --------------------------------------------------------------------------
    """
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0


def _validate_host(name: str, host: Any, where: str) -> None:
    """Check one hosts entry; raise BrowserConfigError naming the host and the field."""
    def bad(field: str, why: str) -> BrowserConfigError:
        return BrowserConfigError("%s: hosts[%r].%s %s" % (where, name, field, why))

    # The key is compared with the lower-cased host name of the page, so a capital
    # letter, a scheme or a path would make the entry match nothing, in silence.
    if not isinstance(name, str) or not name or name != name.lower() \
            or urlparse("https://" + name).hostname != name:
        raise BrowserConfigError("%s: hosts key %r must be a lower-case bare host name "
                                 "(for example www.example.org)" % (where, name))

    if not isinstance(host, dict):
        raise bad("(entry)", "must be an object")
    entry = host.get("entry_url")
    if not isinstance(entry, str) or urlparse(entry).scheme != "https" or \
            not urlparse(entry).hostname:
        raise bad("entry_url", "must be an https URL")
    for field in ("username_env", "vault_item", "logged_in_selector"):
        if not isinstance(host.get(field), str) or not host[field].strip():
            raise bad(field, "must be a non-empty string")
    # The only pages a password or a one-time code may be typed into. Bare host
    # names: a URL or a path here would invite a prefix match.
    login_hosts = host.get("login_hosts")
    if not isinstance(login_hosts, list) or not login_hosts or not all(
            isinstance(h, str) and h.strip() and urlparse("https://" + h).hostname == h.lower()
            for h in login_hosts):
        raise bad("login_hosts", "must be a non-empty list of bare host names "
                                 "(the pages a secret may be typed into)")
    steps = host.get("steps")
    if not isinstance(steps, list) or not steps:
        raise bad("steps", "must be a non-empty list")
    for index, step in enumerate(steps):
        if not isinstance(step, dict) or step.get("action") not in browser_login.STEP_ACTIONS:
            raise bad("steps", "entry %d needs an action in %s"
                      % (index, ", ".join(browser_login.STEP_ACTIONS)))
        if not isinstance(step.get("selector"), str) or not step["selector"].strip():
            raise bad("steps", "entry %d needs a non-empty selector" % index)


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Read browser-fetch.json and return its values with the provenance
        stripped. Every key must be present, carry a non-empty provenance (R4)
        and hold a value of the right kind. Nothing is defaulted (R3).

    Inputs:
        path (str | Path | None): the file to read, default CONFIG_PATH.

    Outputs:
        values (dict): key -> value, hosts already validated.

    Raises:
        BrowserConfigError: the file is missing or not JSON, a key is absent, a
            value lacks its provenance or has the wrong kind, the secret
            provider is unknown, or a hosts entry is malformed. The message
            names the file and the key (and the host).
    --------------------------------------------------------------------------
    """
    target = Path(path) if path else CONFIG_PATH
    where = target.name
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except OSError as exc:
        raise BrowserConfigError("%s: cannot read %s (%s)"
                                 % (where, target, type(exc).__name__)) from None
    except ValueError:
        raise BrowserConfigError("%s: %s is not valid JSON" % (where, target)) from None
    if not isinstance(raw, dict):
        raise BrowserConfigError("%s: the top level must be an object" % where)

    values: dict[str, Any] = {}
    for key in _REQUIRED_KEYS:
        entry = raw.get(key)
        if not isinstance(entry, dict) or "value" not in entry:
            raise BrowserConfigError("%s: key %r is missing or has no 'value'" % (where, key))
        if not str(entry.get("provenance") or "").strip():
            raise BrowserConfigError("%s: key %r has no provenance (R4)" % (where, key))
        values[key] = entry["value"]

    for key in _NUMBER_KEYS:
        if not _positive_number(values[key]):
            raise BrowserConfigError("%s: key %r must be a positive number" % (where, key))
    max_bytes = values["max_pdf_bytes"]
    if not isinstance(max_bytes, int) or isinstance(max_bytes, bool) or max_bytes <= 0:
        raise BrowserConfigError("%s: key 'max_pdf_bytes' must be a positive integer" % where)
    for key in ("channel", "user_agent"):
        if values[key] is not None and (not isinstance(values[key], str)
                                        or not values[key].strip()):
            raise BrowserConfigError("%s: key %r must be a non-empty string or null"
                                     % (where, key))
    if not isinstance(values["profile_dir"], str) or not values["profile_dir"].strip():
        raise BrowserConfigError("%s: key 'profile_dir' must be a non-empty string" % where)
    if values["secret_provider"] not in browser_login.SECRET_PROVIDERS:
        raise BrowserConfigError("%s: key 'secret_provider' must be one of %s"
                                 % (where, ", ".join(browser_login.SECRET_PROVIDERS)))
    if not isinstance(values["allow_totp_from_vault"], bool):
        raise BrowserConfigError("%s: key 'allow_totp_from_vault' must be true or false" % where)
    for key in ("challenge_title_markers", "challenge_selectors"):
        items = values[key]
        if not isinstance(items, list) or not items or not all(
                isinstance(i, str) and i.strip() for i in items):
            raise BrowserConfigError("%s: key %r must be a non-empty list of non-empty strings"
                                     % (where, key))
    if not isinstance(values["curl_impersonate"], str) or not values["curl_impersonate"].strip():
        raise BrowserConfigError("%s: key 'curl_impersonate' must be a non-empty string" % where)
    redirects = values["max_redirects"]
    if not isinstance(redirects, int) or isinstance(redirects, bool) or redirects <= 0:
        raise BrowserConfigError("%s: key 'max_redirects' must be a positive integer" % where)
    if not isinstance(values["hosts"], dict):
        raise BrowserConfigError("%s: key 'hosts' must be an object" % where)
    for name, host in values["hosts"].items():
        _validate_host(name, host, where)
    return values


def _config(config: dict[str, Any] | None) -> dict[str, Any]:
    """The caller's config when given, else the shipped file (read once per path)."""
    if config is not None:
        return config
    key = str(CONFIG_PATH)
    if key not in _config_cache:
        _config_cache[key] = load_config()
    return _config_cache[key]


def profile_dir(config: dict[str, Any]) -> str:
    """The persistent profile folder named by the config, with ~ expanded."""
    return os.path.expanduser(config["profile_dir"])


FALLBACK_PROFILE_SUFFIX = "-chromium"


def _is_missing_channel(exc: Exception) -> bool:
    """True when Playwright says the requested browser distribution is not installed."""
    text = str(exc).lower()
    return "distribution" in text and "not found" in text


def _launch_context(pw: Any, cfg: dict[str, Any], headed: bool) -> Any:
    """
    --------------------------------------------------------------------------
    Purpose:
        Open the persistent browser context: the installed browser named by the
        config's channel (Chrome) with the persistent profile. When that
        distribution is not installed, fall back to the bundled Chromium in a
        profile folder of its own and say so in the log, never silently. Any
        other launch failure is not a missing Chrome and propagates.

    Inputs:
        pw: the Playwright object (pw.chromium launches the browser).
        cfg (dict): loaded config (channel, profile_dir, user_agent).
        headed (bool): visible window when True.

    Outputs:
        context: the Playwright persistent context.

    Raises:
        playwright Error: the launch failed for a reason other than a missing
            Chrome, or the bundled Chromium failed too.
    --------------------------------------------------------------------------
    """
    profile = profile_dir(cfg)
    kwargs: dict[str, Any] = {
        "headless": not headed, "accept_downloads": True,
        "args": ["--disable-blink-features=AutomationControlled"]}
    if cfg["user_agent"]:
        kwargs["user_agent"] = cfg["user_agent"]
    channel = cfg["channel"]
    if channel:
        os.makedirs(profile, exist_ok=True)
        try:
            return pw.chromium.launch_persistent_context(profile, channel=channel, **kwargs)
        except _PWError as exc:
            if not _is_missing_channel(exc):
                raise
            profile += FALLBACK_PROFILE_SUFFIX
            logger.warning("[BROWSER] the %r browser is not installed: falling back to the "
                           "bundled Chromium (profile %s), which ScienceDirect's challenge "
                           "may refuse. Install Chrome or run: playwright install chrome",
                           channel, profile)
    os.makedirs(profile, exist_ok=True)
    return pw.chromium.launch_persistent_context(profile, **kwargs)


def _clean_doi(doi: str) -> str:
    """Strip any DOI URL prefix and surrounding whitespace (local copy so the
    module stays independent of download_pdf)."""
    doi = (doi or "").strip()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:", "DOI:"):
        if doi.lower().startswith(prefix.lower()):
            doi = doi[len(prefix):]
            break
    return doi.strip()


def _save_pdf_bytes(data: bytes, dest: str, max_bytes: int | None = None) -> bool:
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
        max_bytes (int | None): size cap; default the config's max_pdf_bytes.

    Outputs:
        ok (bool): True when a valid PDF was written; False otherwise (no partial
        file is left behind).
    --------------------------------------------------------------------------
    """
    cap = max_bytes if max_bytes is not None else _config(None)["max_pdf_bytes"]
    if not data or not data.startswith(PDF_MAGIC):
        logger.warning("[BROWSER] not a PDF (magic mismatch) - discarded")
        return False
    if len(data) > cap:
        logger.warning("[BROWSER] exceeds %d-byte cap - discarded", cap)
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


def _click_download_button(pg, captured: dict, cfg: dict[str, Any]) -> None:
    """In a viewer/reader page, click an explicit Download control and keep the
    downloaded file if it is a PDF. Used after a 'View PDF' click opens a reader
    (e.g. Taylor & Francis /doi/epdf) that streams the file only on Download.
    Waits come from cfg (download_wait_s, download_retry_pause_s)."""
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
            with pg.expect_download(timeout=int(cfg["download_wait_s"] * 1000)) as info:
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
                pg.wait_for_timeout(int(cfg["download_retry_pause_s"] * 1000))
            except _PWError:
                pass


def _try_click_through(page, captured: dict, cfg: dict[str, Any]) -> None:
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
        cfg (dict): the loaded config (popup_wait_s, viewer_settle_s, ...).

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
            with page.expect_popup(timeout=int(cfg["popup_wait_s"] * 1000)) as info:
                el.click()
            popup = info.value
        except _PWError:
            popup = None  # click navigated the same tab, or opened nothing
        target = popup or page
        try:
            target.wait_for_load_state("domcontentloaded")
            target.wait_for_timeout(int(cfg["viewer_settle_s"] * 1000))  # viewer streams its PDF
        except _PWError:
            pass
        if captured["data"] is not None:
            return
        _click_download_button(target, captured, cfg)


def browser_available() -> bool:
    """True when Playwright is importable (its Chromium is verified lazily at
    launch; a missing browser surfaces an actionable install hint then)."""
    return _PW_OK


class BrowserSession:
    """
    --------------------------------------------------------------------------
    Purpose:
        One browser for a whole run. The browser is launched on first use and
        closed once, so a solved challenge and an institutional sign-in carry
        over from one paper to the next: the second paper does not sign in again
        while the session cookie is valid.

    Inputs:
        config (dict | None): values from load_config(); default the shipped file.
        headed (bool): visible window when True. A shared session fixes this for
            every paper it serves.

    Outputs:
        An object with context() (launch on demand), close() (idempotent) and
        context-manager support.
    --------------------------------------------------------------------------
    """

    def __init__(self, config: dict[str, Any] | None = None, headed: bool = True) -> None:
        self.cfg = _config(config)
        self.headed = headed
        self._manager: Any = None
        self._context: Any = None
        # host -> why its sign-in failed in this run. A host that failed once is not
        # tried again for the next paper: each try would re-read the secret and wait
        # the whole human window, and repeated bad submissions can lock the account.
        self.failed_sign_ins: dict[str, str] = {}

    def context(self) -> Any:
        """Return the persistent context, launching the browser on the first call."""
        if self._context is None:
            manager = sync_playwright()
            playwright = manager.__enter__()
            try:
                context = _launch_context(playwright, self.cfg, self.headed)
            except BaseException:
                manager.__exit__(None, None, None)
                raise
            self._manager, self._context = manager, context
            # Reduce the automation fingerprint: Cloudflare/Akamai re-challenge
            # every navigation when navigator.webdriver is true.
            try:
                context.add_init_script(
                    "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});")
            except _PWError:  # pragma: no cover
                pass
        return self._context

    def restart(self) -> Any:
        """Drop a dead browser (the window was closed, Chrome crashed) and launch a new
        one on the same profile. Sign-in memory is kept."""
        self.close()
        return self.context()

    def close(self) -> None:
        """Close the browser once; later calls do nothing."""
        context, manager = self._context, self._manager
        self._context = self._manager = None
        if context is not None:
            try:
                context.close()
            except _PWError:  # pragma: no cover - already gone
                pass
        if manager is not None:
            manager.__exit__(None, None, None)

    def __enter__(self) -> "BrowserSession":
        return self

    def __exit__(self, *exc: Any) -> bool:
        self.close()
        return False


class _use_session:
    """Yield the caller's session, or a private one that is closed on exit."""

    def __init__(self, session: BrowserSession | None, cfg: dict[str, Any], headed: bool):
        self._owned = session is None
        self.session = session if session is not None else BrowserSession(cfg, headed)

    def __enter__(self) -> BrowserSession:
        return self.session

    def __exit__(self, *exc: Any) -> bool:
        if self._owned:
            self.session.close()
        return False


# How far from the end of a PDF the %%EOF trailer is looked for. The PDF 1.7 reference
# (ISO 32000-1, 7.5.5) tells readers to look in the last 1024 bytes; four times that is
# a margin for trailing padding. Specified by the standard, margin chosen by the author
# 2026-11-05, not measured. A module constant and not a config key because
# _is_complete_pdf takes no configuration.
PDF_TRAILER_WINDOW_BYTES = 4096


def _is_complete_pdf(data: Any) -> bool:
    """
    --------------------------------------------------------------------------
    Purpose:
        Tell whether a body is a whole PDF and not a truncated chunk: readers
        stream the file in HTTP ranges, so one body can look valid yet be partial.

    Inputs:
        data (Any): the body (bytes) or None.

    Outputs:
        ok (bool): True when it starts with %PDF and carries an %%EOF trailer
        within PDF_TRAILER_WINDOW_BYTES of its end.
    --------------------------------------------------------------------------
    """
    return bool(data) and data.startswith(PDF_MAGIC) \
        and b"%%EOF" in data[-PDF_TRAILER_WINDOW_BYTES:]


def _hybrid_fetch(context: Any, page: Any, url: str, cfg: dict[str, Any]) -> bytes | None:
    """
    --------------------------------------------------------------------------
    Purpose:
        Download a PDF with curl_cffi using the cookies and user agent of the
        browser session, after the owner cleared the challenge in it. The server
        sees Chrome's TLS fingerprint with the clearance cookie it issued, which
        a plain Playwright request does not reproduce. Nothing is solved or
        hidden: without the owner's click there is no cookie to send.

    Inputs:
        context: the Playwright persistent context (cookies are read from it).
        page: a page of that context (user agent and referring origin).
        url (str): the PDF URL, https only.
        cfg (dict): loaded config (curl_impersonate, max_redirects, nav_timeout_s).

    Outputs:
        data (bytes | None): the complete PDF, or None for any failure: curl_cffi
        absent, no user agent, plain http, a redirect to http, too many hops, a
        non-200 status, a challenge page, a truncated file. Never raises.
        Redirects are followed by hand and the cookies are re-read for each hop,
        so a cookie of one host is never sent to another. No cookie value is
        logged.
    --------------------------------------------------------------------------
    """
    if not _CFFI_OK:
        logger.info("[BROWSER] curl_cffi not installed: the PDF is not downloaded with the "
                    "browser's cookies (pip install curl_cffi)")
        return None
    try:
        agent = page.evaluate("navigator.userAgent")
    except _PWError:
        return None
    if not isinstance(agent, str) or not agent:
        return None   # a clearance cookie is bound to the user agent that earned it
    origin = urlparse(page.url or "")
    referer = "%s://%s/" % (origin.scheme, origin.netloc) if origin.scheme and origin.netloc else ""
    current = url
    for _ in range(cfg["max_redirects"] + 1):
        if urlparse(current).scheme != "https":
            logger.info("[BROWSER] hybrid download refused a non-https URL")
            return None
        try:
            cookies = {c["name"]: c["value"] for c in context.cookies([current])}
        except _PWError:
            cookies = {}
        headers = {"User-Agent": agent, "Accept": "application/pdf,*/*;q=0.8"}
        if referer:
            headers["Referer"] = referer
        try:
            response = _cffi_requests.get(
                current, headers=headers, cookies=cookies, impersonate=cfg["curl_impersonate"],
                timeout=cfg["nav_timeout_s"], allow_redirects=False, stream=True)
        except Exception as exc:   # curl_cffi raises its own hierarchy
            logger.info("[BROWSER] hybrid download failed (%s)", type(exc).__name__)
            return None
        try:
            if response.status_code in (301, 302, 303, 307, 308):
                location = (response.headers or {}).get("Location", "")
                if not location:
                    return None
                current = urljoin(current, location)
                continue
            if response.status_code != 200:
                logger.info("[BROWSER] hybrid download answered HTTP %s", response.status_code)
                return None
            body = _read_capped(response, cfg["max_pdf_bytes"], cfg["stream_chunk_bytes"])
            return body if _is_complete_pdf(body) else None
        except Exception as exc:   # a reset connection while streaming
            logger.info("[BROWSER] hybrid download failed (%s)", type(exc).__name__)
            return None
        finally:
            try:
                response.close()
            except Exception:  # pragma: no cover - already closed
                pass
    logger.info("[BROWSER] hybrid download: too many redirects")
    return None


def _read_capped(response: Any, cap: int, chunk_bytes: int) -> bytes | None:
    """
    --------------------------------------------------------------------------
    Purpose:
        Read a streamed body, refusing it as soon as it is known to pass `cap`
        bytes: by the declared Content-Length before any byte is read, else while
        counting what arrives (a missing or malformed length does not switch the
        cap off).

    Inputs:
        response: a curl_cffi response opened with stream=True.
        cap (int): the most bytes accepted.
        chunk_bytes (int): the size of each read (config stream_chunk_bytes).

    Outputs:
        body (bytes | None): the whole body, or None when it is over the cap.
    --------------------------------------------------------------------------
    """
    try:
        declared = int((response.headers or {}).get("Content-Length", ""))
    except (TypeError, ValueError):
        declared = None
    if declared is not None and declared > cap:
        logger.info("[BROWSER] hybrid download refused: declared length over the %d-byte cap", cap)
        return None
    chunks: list[bytes] = []
    size = 0
    for chunk in response.iter_content(chunk_size=int(chunk_bytes)):
        if not chunk:
            continue
        size += len(chunk)
        if size > cap:
            logger.info("[BROWSER] hybrid download refused: body over the %d-byte cap", cap)
            return None
        chunks.append(chunk)
    return b"".join(chunks)


_last_outcome = ""


def last_outcome() -> str:
    """What the browser saw on the last call that captured no PDF ('' after a success).
    Host and title only, never a path or query: those can hold tokens."""
    return _last_outcome


def _describe_last_page(page: Any, cfg: dict[str, Any]) -> str:
    """One line on the page the browser ended on, for the failure record."""
    try:
        host = urlparse(page.url or "").hostname or "(unknown)"
    except Exception:  # pragma: no cover - a closed page
        host = "(unknown)"
    try:
        title = " ".join((page.title() or "").split())[:int(cfg["title_chars"])]
    except _PWError:
        title = ""
    challenge = "a challenge was still showing" if _challenge_showing(page, cfg) \
        else "no challenge showing"
    # The page controls its title, and agents read this record: it is labelled as text
    # from the web, quoted and cut, never worded as an instruction.
    return ("no PDF captured; last page host=%s title (untrusted page text)=%r; %s"
            % (host, title, challenge))


def _challenge_showing(page: Any, cfg: dict[str, Any]) -> bool:
    """True while a Cloudflare challenge is on screen: the page title holds a configured
    marker, or a configured selector matches. A browser error counts as not showing."""
    try:
        title = (page.title() or "").lower()
    except _PWError:
        title = ""
    if any(marker.lower() in title for marker in cfg["challenge_title_markers"]):
        return True
    return any(_present(page, selector) for selector in cfg["challenge_selectors"])


def _present(page: Any, selector: str) -> bool:
    """True when the selector matches an element now (a browser error counts as no)."""
    try:
        return page.query_selector(selector) is not None
    except _PWError:
        return False


def _sign_in(page: Any, host: str, host_cfg: dict[str, Any], cfg: dict[str, Any],
             drain: Any, wait_s: float | None = None) -> None:
    """
    --------------------------------------------------------------------------
    Purpose:
        Sign in to the owner's institution for a listed publisher host: open the
        configured entry URL, run the configured steps (fill the user name, the
        password read from the secret provider, optionally a one-time code,
        click), then wait up to the human window for the owner to approve the MFA
        prompt. The wait ends as soon as the signed-in marker appears or a full
        PDF has been captured. Only the configured fields are touched.

    Inputs:
        page: the Playwright page.
        host (str): the publisher host, for messages.
        host_cfg (dict): the validated hosts entry.
        cfg (dict): the loaded config.
        drain: callable returning True once a complete PDF has been captured.
        wait_s (float | None): how long to wait for the signed-in marker. None
            means the configured human window; a headless run passes the short
            headless wait, since nobody can approve an MFA prompt there.

    Outputs:
        None. The page is left signed in.

    Raises:
        BrowserRungError: the user name variable is unset, a provider refused, a
            field did not appear, a one-time code is needed but not allowed, or
            the sign-in did not complete within the human window. No message
            holds a secret.
    --------------------------------------------------------------------------
    """
    username_env = host_cfg["username_env"]
    username = os.environ.get(username_env, "").strip()
    if not username:
        raise BrowserRungError("sign-in to %s needs the user name in the environment variable "
                               "%s, which is not set" % (host, username_env))
    if any(s["action"] == "fill_totp" for s in host_cfg["steps"]) and \
            not cfg["allow_totp_from_vault"]:
        raise BrowserRungError("sign-in to %s has a fill_totp step but allow_totp_from_vault is "
                               "false in browser-fetch.json" % host)

    def refuse(why: str) -> BrowserRungError:
        return BrowserRungError("sign-in to %s: %s" % (host, why))

    allowed_hosts = [h.lower() for h in host_cfg["login_hosts"]]

    def require_login_origin() -> None:
        # A redirect chain (an open redirect on the entry URL, a hijacked link)
        # could land on a look-alike page. A secret is typed only into https pages
        # of the configured login hosts, checked before the secret is read.
        current = urlparse(page.url or "")
        if current.scheme != "https" or (current.hostname or "").lower() not in allowed_hosts:
            raise refuse("the page reached is on %r, which is not one of the login_hosts "
                         "in browser-fetch.json, so no password or code was typed or read"
                         % (current.hostname or "(unknown)"))

    try:
        page.goto(host_cfg["entry_url"], wait_until="domcontentloaded")
    except _PWError:
        raise refuse("the entry page could not be opened") from None
    logger.info("[BROWSER] signing in to %s (the secret comes from the %s provider)",
                host, cfg["secret_provider"])
    for step in host_cfg["steps"]:
        selector, action = step["selector"], step["action"]
        try:
            # The element handle is taken BEFORE a secret is read and the fill goes
            # through it: a handle belongs to one document, so a page that was
            # replaced while the secret was being read cannot receive it.
            element = page.wait_for_selector(selector, timeout=int(cfg["step_timeout_s"] * 1000))
        except _PWError:
            raise refuse("the element %r did not appear within %g s (the selectors in "
                         "browser-fetch.json may need updating)"
                         % (selector, cfg["step_timeout_s"])) from None
        if element is None:
            raise refuse("the element %r is not available" % selector)
        try:
            if action == "click":
                element.click()
                continue
            if action == "fill_username":
                value = username
            elif action == "fill_password":
                require_login_origin()
                value = browser_login.get_password(
                    host_cfg["vault_item"], cfg["secret_provider"],
                    timeout_s=cfg["provider_timeout_s"], username=username)
                require_login_origin()      # the read takes up to provider_timeout_s
            else:
                require_login_origin()
                value = browser_login.get_totp(
                    host_cfg["vault_item"], cfg["secret_provider"],
                    allow=cfg["allow_totp_from_vault"], timeout_s=cfg["provider_timeout_s"],
                    username=username)
                require_login_origin()
            element.fill(value)
        except browser_login.LoginError as exc:
            raise refuse(str(exc)) from None
        except _PWError:
            raise refuse("the step %r on %r failed" % (action, selector)) from None
        finally:
            value = None   # drop the secret at once

    marker, poll_ms = host_cfg["logged_in_selector"], int(cfg["poll_s"] * 1000)
    window_s = cfg["human_window_s"] if wait_s is None else wait_s
    for _ in range(max(1, int(window_s / cfg["poll_s"]))):
        if _present(page, marker) or drain():
            return
        try:
            page.wait_for_timeout(poll_ms)
        except _PWError:
            break
    if _present(page, marker) or drain():
        return
    raise refuse("did not complete within %g s: approve the MFA prompt promptly, or check the "
                 "logged_in_selector in browser-fetch.json" % window_s)


def fetch_pdf_via_browser(doi: str, dest: str, *, override_url: str | None = None,
                          headed: bool = True, timeout_s: float | None = None,
                          config: dict[str, Any] | None = None,
                          session: BrowserSession | None = None) -> dict | None:
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
        timeout_s (float | None): per-navigation timeout in seconds; default the
            config's nav_timeout_s.
        config (dict | None): values from load_config(); default the shipped
            browser-fetch.json.
        session (BrowserSession | None): a browser shared by the papers of one
            run, so a sign-in is done once. Without one, a private browser is
            opened and closed for this call. A shared session fixes headed and
            the config for the call.

    Outputs:
        result (dict | None): {"format": "pdf", "source": <s>, "file": <name>}
        where <s> is "override" (override URL used) or "browser" (DOI real PDF);
        None when no real PDF was captured (paper stays failed / manual).

    Raises:
        BrowserConfigError: browser-fetch.json is unusable (R3).
        BrowserRungError: a sign-in was needed and could not be done (secret
            provider locked or missing, form field absent, MFA not approved in
            time). The text names the cause and holds no secret.
    --------------------------------------------------------------------------
    """
    if not _PW_OK:
        logger.info("[BROWSER] Playwright not installed - tier skipped "
                    "(run: pip install playwright && playwright install chromium)")
        return None
    global _last_outcome
    _last_outcome = ""
    cfg = session.cfg if session is not None else _config(config)
    if session is not None:
        headed = session.headed
    if timeout_s is None:
        timeout_s = cfg["nav_timeout_s"]

    entry_url = override_url or f"https://doi.org/{_clean_doi(doi)}"
    if urlparse(entry_url).scheme != "https":
        logger.warning("[BROWSER] refusing non-https URL: %s", entry_url)
        return None
    source = "override" if override_url else "browser"
    captured: dict[str, bytes | None] = {"data": None}
    pdf_responses: list = []       # responses whose content-type is application/pdf
    pdf_urls: list = []            # their URLs, for a full (non-ranged) re-fetch
    tried_urls: set = set()        # (url, challenge showing) already re-fetched in full
    sign_in_error: BrowserRungError | None = None   # raised at the end if nothing was captured

    _complete = _is_complete_pdf

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
        with _use_session(session, cfg, headed) as sess:
            # The session owns the persistent context; a private one is closed
            # when this block ends, a shared one stays open for the next paper.
            context = sess.context()
            page = None
            wire_popup = None
            try:
                try:
                    page = context.new_page()
                except _PWError as exc:
                    # The owner closed the window or Chrome crashed: a dead shared
                    # context would fail every later paper of the run. Only a
                    # closed target is retried, once, on a fresh browser.
                    if "closed" not in str(exc).lower():
                        raise
                    logger.warning("[BROWSER] the browser was closed: launching a new one")
                    context = sess.restart()
                    page = context.new_page()
                page.set_default_timeout(int(timeout_s * 1000))
                page.on("response", _note_response)
                page.on("download", _on_download)

                # A "View PDF" click often opens the reader in a popup tab; wire
                # the same listeners onto any page the context opens.
                def _wire_popup(popup) -> None:
                    popup.on("response", _note_response)
                    popup.on("download", _on_download)
                wire_popup = _wire_popup
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
                    showing = _challenge_showing(page, cfg) if pdf_urls else False
                    for url in list(dict.fromkeys(pdf_urls)):
                        # One try per URL and challenge state: this runs on every poll
                        # of the human window, and a failure while the challenge shows
                        # is retried once after the click, not every two seconds.
                        if (url, showing) in tried_urls:
                            continue
                        tried_urls.add((url, showing))
                        # curl_cffi with the browser's cookies first (Chrome's TLS
                        # fingerprint), Playwright's own request client second.
                        body = _hybrid_fetch(context, page, url, cfg)
                        if not _complete(body):
                            try:
                                api = context.request.get(url, timeout=int(timeout_s * 1000))
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
                                                 timeout=int(cfg["idle_timeout_s"] * 1000))
                    except _PWError:
                        pass  # challenge / reader pages often never fully idle
                    # The long human window applies only while a challenge is on
                    # screen. Once none is showing, a short quiet period
                    # (headless_wait_s) lets the PDF stream, then the wait ends.
                    # Measured live 2026-11-05: waiting the full window after the
                    # owner had already clicked cost three times 120 s.
                    budget_s = cfg["human_window_s"] if headed else cfg["headless_wait_s"]
                    quiet_polls = max(1, int(cfg["headless_wait_s"] / cfg["poll_s"]))
                    quiet = 0
                    for _ in range(max(1, int(budget_s / cfg["poll_s"]))):
                        if _drain():
                            return
                        if headed and _challenge_showing(page, cfg):
                            quiet = 0
                        else:
                            quiet += 1
                            if quiet > quiet_polls:
                                return
                        try:
                            page.wait_for_timeout(int(cfg["poll_s"] * 1000))
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
                    # A publisher host listed in browser-fetch.json needs the
                    # owner's institutional sign-in. Check it before settling, so
                    # the human window is not spent on a paywall page. At most one
                    # sign-in per paper: a still-valid session cookie (shared
                    # session) shows the signed-in marker and skips it.
                    # A challenge on the landing page is cleared first: the sign-in
                    # would otherwise navigate away from it and spend its short
                    # step timeout on a page nobody can fill yet.
                    host = (urlparse(page.url or "").hostname or "").lower()
                    host_cfg = cfg["hosts"].get(host)
                    settled = False
                    if host_cfg and headed and _challenge_showing(page, cfg):
                        _settle()
                        settled = True
                        host = (urlparse(page.url or "").hostname or "").lower()
                        host_cfg = cfg["hosts"].get(host)
                    signed_in_now = False
                    if captured["data"] is None and host_cfg \
                            and not _present(page, host_cfg["logged_in_selector"]):
                        # A sign-in that cannot complete does not end the paper: the
                        # owner may be entitled by address, or the marker may render
                        # late. The capture is still tried, and the sign-in error is
                        # raised at the end only when nothing was captured.
                        if host in sess.failed_sign_ins:
                            sign_in_error = BrowserRungError(
                                "sign-in to %s already failed in this run (%s): not tried again"
                                % (host, sess.failed_sign_ins[host]))
                        else:
                            try:
                                _sign_in(page, host, host_cfg, cfg, _drain,
                                         wait_s=None if headed else cfg["headless_wait_s"])
                            except BrowserRungError as exc:
                                sess.failed_sign_ins[host] = str(exc)
                                sign_in_error = exc
                            else:
                                signed_in_now = True
                        if captured["data"] is None:
                            try:
                                page.goto(entry_url, wait_until="domcontentloaded")
                            except _PWError:
                                pass
                    if signed_in_now or not settled:
                        _settle()
                    # DOM-based PDF discovery is for a DOI landing page; skip it
                    # for an override host (already the target page) so we do not
                    # re-navigate and re-trigger its challenge.
                    if captured["data"] is None and not override_url:
                        page_url = _discover_pdf_url(page, doi, override_url)
                        if page_url and page_url != pattern_url:
                            # The challenge is cleared by now: download the link with the
                            # browser's cookies; navigate to it only if that fails.
                            data = _hybrid_fetch(context, page, page_url, cfg)
                            if _complete(data):
                                captured["data"] = data
                            else:
                                try:
                                    page.goto(page_url, wait_until="domcontentloaded")
                                except _PWError:
                                    pass
                                _settle()
                    if captured["data"] is None:
                        _try_click_through(page, captured, cfg)
                        _settle()

                if captured["data"] is not None:
                    ok = _save_pdf_bytes(captured["data"], dest, cfg["max_pdf_bytes"])
                    return ({"format": "pdf", "source": source,
                             "file": os.path.basename(dest)} if ok else None)

                # No real publisher PDF was captured. We deliberately do NOT print
                # the rendered page to PDF: on challenge-gated publishers the
                # reachable page is a blank challenge shell or a landing/abstract
                # page, and a print-to-PDF of it is indistinguishable junk that
                # would pollute the corpus. Leave the paper failed / for manual.
                _last_outcome = _describe_last_page(page, cfg)
                logger.info("[BROWSER] no capturable PDF at %s - left for manual (%s)",
                            override_url or doi, _last_outcome)
                if sign_in_error is not None:
                    raise sign_in_error
                return None
            finally:
                # Per-paper cleanup. The browser itself belongs to the session.
                if wire_popup is not None:
                    try:
                        context.remove_listener("page", wire_popup)
                    except Exception:  # pragma: no cover - listener already gone
                        pass
                if page is not None:
                    try:
                        page.close()
                    except _PWError:  # pragma: no cover - page already gone
                        pass
    except BrowserRungError:
        raise
    except _PWError as exc:
        logger.warning("[BROWSER] failed for %s: %s", override_url or doi, exc)
        _last_outcome = _crash_outcome(exc)
        return None
    except Exception as exc:  # pragma: no cover - Chromium launch / unexpected
        logger.warning("[BROWSER] error for %s: %s", override_url or doi, exc)
        _last_outcome = _crash_outcome(exc)
        return None


def _crash_outcome(exc: BaseException) -> str:
    """
    --------------------------------------------------------------------------
    Purpose:
        The one-line record for a browser that did not run: a launch that failed
        (the profile is held by another Chrome) or a window that died. The
        exception text is left out, since it can carry a path under the home
        directory; the full text stays in the log line written by the caller.

    Inputs:
        exc (BaseException): the error that ended the rung.

    Outputs:
        text (str): the record, naming the error type and the usual cause.
    --------------------------------------------------------------------------
    """
    return ("no PDF captured; the browser could not start or stopped (%s): another Chrome "
            "may be using the profile, or the window was closed" % type(exc).__name__)
