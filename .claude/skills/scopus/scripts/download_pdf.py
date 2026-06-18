"""
download_pdf.py — Full-text PDF retrieval for the Claude Code /scopus skill.

Stage: post-validation. Once a reference is fully known (validated DOI +
metadata), this script fetches the full text in ANY usable format
(PDF, HTML, or Markdown) into a `refs/` directory placed directly under the
LaTeX project, so the auditor/researcher agents can keep the papers next to the
manuscript that cites them. The goal is a readable full paper in any format, not
a PDF specifically.

Source chain (stop at the first byte/content-validated artifact):
  1. Elsevier Full-Text API  — PDF, primary, uses SCOPUS_API_KEY (+ optional insttoken)
  2. Semantic Scholar openAccessPdf — PDF, only when Scopus cannot deliver
  3. Unpaywall best_oa_location — PDF then landing HTML (needs UNPAYWALL_EMAIL / --email)
  4. arXiv — PDF then native/ar5iv HTML, when the paper has an arXiv id
  5. PubMed Central — OA article HTML, when the paper has a PMCID
  6. Validated landing scrape — the DOI landing page HTML, content-gated

PDF fetches are validated by the PDF magic bytes (%PDF); HTML fetches are
validated by a text/html content type, a minimum body length, and a rejection of
known paywall/login/captcha markers (the HTML analogue of the %PDF check). Both
share an HTTPS-only scheme check, a redirect-hop limit, and a size cap, so a
publisher "access denied" page is never stored as full text. Tiers 3-6 fetch only
open-access-declared or content-validated locations; no paywall is bypassed.

Usage:
  python download_pdf.py doi "<DOI>" --out-dir "<.../refs>" \\
      [--citekey KEY] [--author A] [--year Y] [--title T] [--insttoken TOK] \\
      [--email you@inst.edu] [--no-html]
  python download_pdf.py bib "<references.bib>" --latex "<.../src/main.tex>"
  python download_pdf.py bib "<references.bib>" --out-dir "<.../src/refs>"
  python download_pdf.py bib --latex "<.../src/main.tex>"   # auto-discovers the .bib

Requires: SCOPUS_API_KEY (Windows user env var) for the Elsevier source; the
Semantic Scholar, Unpaywall, arXiv and PMC fallbacks work without it. The
Unpaywall tier needs a contact email (UNPAYWALL_EMAIL env var, or --email). Pass
--no-html to restrict retrieval to PDF only. No path or credential is hardcoded:
every path is derived from the --latex / --bib / --out-dir arguments passed in.

See .claude/rules/security.md for the file-write and input-validation rules this
script follows.
"""

import argparse
import json
import logging
import os
import re
import sys
import unicodedata
from typing import Any
from urllib.parse import urljoin, urlparse

try:
    import requests
except ImportError:
    print("ERROR: 'requests' library not installed. Run: pip install requests", file=sys.stderr)
    sys.exit(1)

# Semantic Scholar fallback lives in the same scripts/ directory.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    import semantic_scholar_api as s2
except ImportError:  # pragma: no cover - defensive: fallback simply disabled
    s2 = None

logger = logging.getLogger(__name__)

ELSEVIER_FULLTEXT_URL = "https://api.elsevier.com/content/article/doi/{doi}"
UNPAYWALL_URL = "https://api.unpaywall.org/v2/{doi}"
ARXIV_PDF_URL = "https://arxiv.org/pdf/{arxiv_id}"
ARXIV_HTML_URL = "https://arxiv.org/html/{arxiv_id}"
AR5IV_HTML_URL = "https://ar5iv.org/abs/{arxiv_id}"
PMC_HTML_URL = "https://www.ncbi.nlm.nih.gov/pmc/articles/{pmcid}/"
DOI_RESOLVER_URL = "https://doi.org/{doi}"

PDF_MAGIC = b"%PDF"
MAX_PDF_BYTES = 100 * 1024 * 1024  # 100 MB cap, streamed; aborts past this
MAX_HTML_BYTES = 25 * 1024 * 1024  # 25 MB cap for an HTML full-text page
MIN_HTML_BYTES = 2000              # below this an HTML body is too thin to be a paper
MAX_REDIRECTS = 5
CHUNK_BYTES = 8192
REQUEST_TIMEOUT_S = 60

# A plain desktop User-Agent: some open-access hosts reject an empty UA. This is
# used only for the HTML tiers (OA-declared or content-validated locations).
HTML_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) ResearchToolsBot/1.0 Safari/537.36"
)

# Markers that betray a paywall, login wall, or bot challenge rather than the
# article body. Their presence in a small/early HTML window rejects the page so a
# stub is never stored as full text (the HTML analogue of the %PDF magic check).
HTML_BLOCK_MARKERS = (
    "access denied", "acces refuse", "please sign in", "sign in to",
    "log in to", "purchase pdf", "buy this article", "get access", "subscribe to",
    "institutional login", "captcha", "are you a robot", "enable javascript",
    "cloudflare", "just a moment", "403 forbidden", "404 not found",
    "page not found", "request unsuccessful",
)


# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #
def _slugify(text: str, max_len: int = 60) -> str:
    """
    --------------------------------------------------------------------------
    Purpose:
        Reduce arbitrary text to a filesystem-safe ASCII token with no path
        separators, used to build PDF filenames.

    Inputs:
        text (str): raw text (author, title fragment, etc.)
        max_len (int): maximum length of the returned slug

    Outputs:
        slug (str): lowercase ASCII, only [a-z0-9_-], never containing '/' or '\\'
    --------------------------------------------------------------------------
    """
    text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode()
    text = re.sub(r"[^\w\s-]", "", text).strip().lower()
    text = re.sub(r"[\s_-]+", "_", text)
    return text[:max_len].strip("_") or "ref"


def _clean_doi(doi: str) -> str:
    """Strip any DOI URL prefix and surrounding whitespace."""
    doi = (doi or "").strip()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:", "DOI:"):
        if doi.lower().startswith(prefix.lower()):
            doi = doi[len(prefix):]
            break
    return doi.strip()


def _scopus_key_optional() -> str | None:
    """
    --------------------------------------------------------------------------
    Purpose:
        Resolve the Scopus API key the same way scopus_api._get_api_key does
        (SCOPUS_API_KEY env var, then a sibling ../.scopus_key file), but return
        None instead of exiting when it is absent. The Elsevier source is then
        skipped and only the Semantic Scholar fallback is used.

    Inputs:
        none

    Outputs:
        key (str | None): the Scopus key, or None when not configured.
    --------------------------------------------------------------------------
    """
    key = os.environ.get("SCOPUS_API_KEY", "").strip()
    if not key:
        fallback = os.path.join(os.path.dirname(__file__), "..", ".scopus_key")
        if os.path.exists(fallback):
            with open(fallback, encoding="utf-8") as handle:
                key = handle.read().strip()
    return key or None


def _unpaywall_email_optional() -> str | None:
    """
    --------------------------------------------------------------------------
    Purpose:
        Resolve the contact email Unpaywall requires on every request, from the
        UNPAYWALL_EMAIL environment variable. Returns None when unset, in which
        case the Unpaywall tier is skipped (it is one source among several).

    Inputs:
        none

    Outputs:
        email (str | None): the contact email, or None when not configured.
    --------------------------------------------------------------------------
    """
    return os.environ.get("UNPAYWALL_EMAIL", "").strip() or None


def target_filename(entry: dict[str, str], ext: str = "pdf") -> str:
    """
    --------------------------------------------------------------------------
    Purpose:
        Build the deterministic full-text filename for a reference, with the
        given extension. The citekey is preferred so the presence check is
        stable across runs; author_year_title is the fallback when no citekey is
        known (e.g. a bare DOI download).

    Inputs:
        entry (dict): may carry 'citekey', 'author', 'year', 'title'
        ext (str): file extension without the dot ('pdf', 'html', 'md')

    Outputs:
        name (str): a safe '<...>.<ext>' filename with no path separators.
    --------------------------------------------------------------------------
    """
    ext = (ext or "pdf").lstrip(".").lower()
    citekey = (entry.get("citekey") or "").strip()
    if citekey:
        return f"{_slugify(citekey)}.{ext}"
    author = _slugify(entry.get("author") or "unknown")
    year = _slugify(entry.get("year") or "0000")
    title = _slugify(entry.get("title") or "notitle", max_len=40)
    return f"{author}_{year}_{title}.{ext}"


# --------------------------------------------------------------------------- #
# BibTeX / LaTeX parsing
# --------------------------------------------------------------------------- #
def extract_bib_entries(bib_path: str) -> list[dict[str, str]]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Parse a .bib file into reference dicts. Only entries carrying a DOI are
        returned, since the DOI drives every download source.

    Inputs:
        bib_path (str): path to the .bib file

    Outputs:
        entries (list[dict]): each {citekey, doi, author, year, title}
    --------------------------------------------------------------------------
    """
    with open(bib_path, encoding="utf-8") as handle:
        content = handle.read()

    entries: list[dict[str, str]] = []
    for block in re.split(r"(?=@\w+\s*\{)", content):
        block = block.strip()
        if not block.startswith("@"):
            continue

        key_match = re.match(r"@\w+\s*\{\s*([^,\s]+)\s*,", block)
        doi_match = re.search(r"\bdoi\s*=\s*[{\"](.*?)[}\"]", block, re.IGNORECASE)
        if not doi_match:
            continue

        author_match = re.search(r"\bauthor\s*=\s*[{\"](.*?)[}\"]", block, re.IGNORECASE | re.DOTALL)
        year_match = re.search(r"\byear\s*=\s*[{\"]?(\d{4})", block, re.IGNORECASE)
        title_match = re.search(r"\btitle\s*=\s*[{\"](.*?)[}\"]", block, re.IGNORECASE | re.DOTALL)

        first_author = ""
        if author_match:
            first_author = author_match.group(1).split(" and ")[0].split(",")[0].strip()

        entries.append({
            "citekey": key_match.group(1).strip() if key_match else "",
            "doi": _clean_doi(doi_match.group(1)),
            "author": first_author,
            "year": year_match.group(1).strip() if year_match else "",
            "title": title_match.group(1).strip() if title_match else "",
        })
    return entries


def find_bib_from_latex(tex_path: str) -> str | None:
    """
    --------------------------------------------------------------------------
    Purpose:
        Locate the .bib file referenced by a LaTeX source via \\bibliography{}
        or \\addbibresource{}, resolving every name relative to the .tex
        directory. Returns the first path that exists on disk.

    Inputs:
        tex_path (str): path to the main .tex file

    Outputs:
        bib_path (str | None): resolved .bib path, or None when none is found.
    --------------------------------------------------------------------------
    """
    tex_dir = os.path.dirname(os.path.abspath(tex_path))
    try:
        with open(tex_path, encoding="utf-8") as handle:
            tex = handle.read()
    except OSError as exc:
        logger.warning("[PDF] cannot read LaTeX file %s: %s", tex_path, exc)
        return None

    names: list[str] = []
    for macro in (r"\\bibliography\{([^}]*)\}", r"\\addbibresource\{([^}]*)\}"):
        for match in re.findall(macro, tex):
            names.extend(part.strip() for part in match.split(",") if part.strip())

    for name in names:
        candidate = name if name.lower().endswith(".bib") else f"{name}.bib"
        resolved = os.path.normpath(os.path.join(tex_dir, candidate))
        if os.path.exists(resolved):
            return resolved
    return None


def resolve_out_dir(out_dir: str | None, latex: str | None) -> str:
    """
    --------------------------------------------------------------------------
    Purpose:
        Decide where PDFs are written. An explicit --out-dir wins; otherwise the
        directory is <dirname(main.tex)>/refs. The directory is created if
        absent. No path is hardcoded; everything derives from the arguments.

    Inputs:
        out_dir (str | None): explicit output directory
        latex (str | None): path to the main .tex file

    Outputs:
        path (str): an existing directory ready to receive PDFs.
    --------------------------------------------------------------------------
    """
    if out_dir:
        resolved = os.path.abspath(out_dir)
    elif latex:
        resolved = os.path.join(os.path.dirname(os.path.abspath(latex)), "refs")
    else:
        raise ValueError("either --out-dir or --latex is required to locate refs/")
    os.makedirs(resolved, exist_ok=True)
    return resolved


# --------------------------------------------------------------------------- #
# Hardened fetch
# --------------------------------------------------------------------------- #
def _write_validated(response: "requests.Response", dest: str) -> bool:
    """
    --------------------------------------------------------------------------
    Purpose:
        Stream an HTTP response body to `dest` only if it is a real PDF. The
        first bytes must be the %PDF magic number (this rejects HTML access
        pages returned with HTTP 200), and the body must stay under the size
        cap. The write is atomic: a temporary *.part file is renamed into place
        only after a complete, validated download.

    Inputs:
        response (requests.Response): a streamed 200 response
        dest (str): final destination path for the PDF

    Outputs:
        ok (bool): True when a valid PDF was written, False otherwise (no
        partial file is ever left behind).
    --------------------------------------------------------------------------
    """
    content_type = response.headers.get("Content-Type", "").lower()
    chunks = response.iter_content(CHUNK_BYTES)
    first = next(chunks, b"") or b""
    if not first.startswith(PDF_MAGIC):
        logger.warning("[PDF] not a PDF (magic mismatch, content-type=%s) — discarded", content_type)
        return False

    tmp = f"{dest}.part"
    size = 0
    try:
        with open(tmp, "wb") as handle:
            size += len(first)
            handle.write(first)
            for chunk in chunks:
                if not chunk:
                    continue
                size += len(chunk)
                if size > MAX_PDF_BYTES:
                    logger.warning("[PDF] exceeds %d-byte cap — discarded", MAX_PDF_BYTES)
                    handle.close()
                    os.remove(tmp)
                    return False
                handle.write(chunk)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, dest)
        return True
    except OSError as exc:
        logger.warning("[PDF] write failed for %s: %s", dest, exc)
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass
        return False


def _fetch_pdf(url: str, dest: str, headers: dict[str, str] | None = None) -> bool:
    """
    --------------------------------------------------------------------------
    Purpose:
        GET a PDF URL with HTTPS-only, manual redirect handling (capped hops),
        then hand the response to _write_validated. Each redirect hop is
        re-checked for the https scheme to limit SSRF / scheme-downgrade.

    Inputs:
        url (str): the PDF URL (must be https)
        dest (str): destination path
        headers (dict | None): extra request headers (e.g. Elsevier API key)

    Outputs:
        ok (bool): True when a valid PDF was written.
    --------------------------------------------------------------------------
    """
    headers = headers or {}
    current = url
    for _ in range(MAX_REDIRECTS + 1):
        parsed = urlparse(current)
        if parsed.scheme != "https":
            logger.warning("[PDF] refusing non-https URL: %s", current)
            return False
        try:
            response = requests.get(
                current, headers=headers, stream=True,
                timeout=REQUEST_TIMEOUT_S, allow_redirects=False,
            )
        except requests.RequestException as exc:
            logger.warning("[PDF] network error for %s: %s", current, exc)
            return False

        if response.status_code in (301, 302, 303, 307, 308):
            location = response.headers.get("Location", "")
            response.close()
            if not location:
                return False
            current = urljoin(current, location)
            continue
        if response.status_code != 200:
            logger.info("[PDF] HTTP %s for %s", response.status_code, current)
            response.close()
            return False
        try:
            return _write_validated(response, dest)
        finally:
            response.close()

    logger.warning("[PDF] too many redirects for %s", url)
    return False


# --------------------------------------------------------------------------- #
# Source chain
# --------------------------------------------------------------------------- #
def try_elsevier(doi: str, dest: str, api_key: str | None, insttoken: str | None) -> bool:
    """Primary source: Elsevier Full-Text API. No-op when no Scopus key is set."""
    if not api_key:
        return False
    url = ELSEVIER_FULLTEXT_URL.format(doi=_clean_doi(doi))
    headers = {"X-ELS-APIKey": api_key, "Accept": "application/pdf"}
    if insttoken:
        headers["X-ELS-Insttoken"] = insttoken
    return _fetch_pdf(url, dest, headers=headers)


def try_semantic_scholar(doi: str, dest: str) -> bool:
    """Fallback source: the Semantic Scholar open-access PDF URL, if S2 has one."""
    if s2 is None:
        return False
    try:
        pdf_url = s2.oa_pdf_for_doi(doi)
    except Exception as exc:  # pragma: no cover - S2 layer is best-effort
        logger.warning("[PDF] Semantic Scholar lookup failed for %s: %s", doi, exc)
        return False
    if not pdf_url:
        return False
    return _fetch_pdf(pdf_url, dest)


# --------------------------------------------------------------------------- #
# Hardened HTML fetch (the any-format tiers)
# --------------------------------------------------------------------------- #
def _write_validated_html(response: "requests.Response", dest: str) -> bool:
    """
    --------------------------------------------------------------------------
    Purpose:
        Stream an HTTP response body to `dest` only if it is a real article HTML
        page, not a paywall/login/bot-challenge stub. The content type must look
        like HTML/XML, the body must clear MIN_HTML_BYTES and stay under
        MAX_HTML_BYTES, and no known block marker may appear in the head window.
        This is the HTML analogue of the %PDF magic-byte check in
        _write_validated. The write is atomic via a *.part rename.

    Inputs:
        response (requests.Response): a streamed 200 response
        dest (str): final destination path for the .html file

    Outputs:
        ok (bool): True when a valid HTML article was written, False otherwise
        (no partial file is ever left behind).
    --------------------------------------------------------------------------
    """
    content_type = response.headers.get("Content-Type", "").lower()
    if "html" not in content_type and "xml" not in content_type:
        logger.warning("[HTML] not HTML (content-type=%s) - discarded", content_type or "none")
        return False

    raw = bytearray()
    for chunk in response.iter_content(CHUNK_BYTES):
        if not chunk:
            continue
        raw.extend(chunk)
        if len(raw) > MAX_HTML_BYTES:
            logger.warning("[HTML] exceeds %d-byte cap - discarded", MAX_HTML_BYTES)
            return False

    if len(raw) < MIN_HTML_BYTES:
        logger.warning("[HTML] body too thin (%d bytes) - discarded", len(raw))
        return False

    text = raw.decode("utf-8", errors="replace")
    head = text[:4000].lower()
    for marker in HTML_BLOCK_MARKERS:
        if marker in head:
            logger.warning("[HTML] block marker %r in head - discarded", marker)
            return False

    tmp = f"{dest}.part"
    try:
        with open(tmp, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, dest)
        return True
    except OSError as exc:
        logger.warning("[HTML] write failed for %s: %s", dest, exc)
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass
        return False


def _fetch_html(url: str, dest: str) -> bool:
    """
    --------------------------------------------------------------------------
    Purpose:
        GET an HTML full-text URL with HTTPS-only, manual redirect handling
        (capped hops), then hand the response to _write_validated_html. Mirrors
        _fetch_pdf; sends a desktop User-Agent because some OA hosts reject an
        empty UA.

    Inputs:
        url (str): the article URL (must resolve over https)
        dest (str): destination .html path

    Outputs:
        ok (bool): True when a valid HTML article was written.
    --------------------------------------------------------------------------
    """
    headers = {"User-Agent": HTML_USER_AGENT, "Accept": "text/html,application/xhtml+xml"}
    current = url
    for _ in range(MAX_REDIRECTS + 1):
        parsed = urlparse(current)
        if parsed.scheme != "https":
            logger.warning("[HTML] refusing non-https URL: %s", current)
            return False
        try:
            response = requests.get(
                current, headers=headers, stream=True,
                timeout=REQUEST_TIMEOUT_S, allow_redirects=False,
            )
        except requests.RequestException as exc:
            logger.warning("[HTML] network error for %s: %s", current, exc)
            return False

        if response.status_code in (301, 302, 303, 307, 308):
            location = response.headers.get("Location", "")
            response.close()
            if not location:
                return False
            current = urljoin(current, location)
            continue
        if response.status_code != 200:
            logger.info("[HTML] HTTP %s for %s", response.status_code, current)
            response.close()
            return False
        try:
            return _write_validated_html(response, dest)
        finally:
            response.close()

    logger.warning("[HTML] too many redirects for %s", url)
    return False


# --------------------------------------------------------------------------- #
# Any-format tiers (Unpaywall, arXiv, PMC, landing). Each returns a result dict
# {format, source, file} on success, or None. They write into out_dir using
# target_filename so the presence check stays stable across runs.
# --------------------------------------------------------------------------- #
def _http_json(url: str, params: dict[str, str] | None = None) -> dict[str, Any] | None:
    """GET a JSON API over https (Unpaywall); None on any error. Never raises."""
    if urlparse(url).scheme != "https":
        return None
    try:
        response = requests.get(
            url, params=params, headers={"User-Agent": HTML_USER_AGENT},
            timeout=REQUEST_TIMEOUT_S,
        )
    except requests.RequestException as exc:
        logger.warning("[OA] network error for %s: %s", url, exc)
        return None
    if response.status_code != 200:
        logger.info("[OA] HTTP %s for %s", response.status_code, url)
        return None
    try:
        return response.json()
    except ValueError:
        return None


def try_unpaywall(doi: str, out_dir: str, entry: dict[str, str],
                  email: str | None, allow_html: bool) -> dict[str, Any] | None:
    """
    --------------------------------------------------------------------------
    Purpose:
        Resolve the best open-access location for a DOI via Unpaywall and fetch
        it. The OA PDF (url_for_pdf) is tried first; when no PDF or it fails and
        HTML is allowed, the OA landing url is fetched as content-validated HTML.

    Inputs:
        doi (str): the paper DOI
        out_dir (str): the refs/ directory
        entry (dict): reference entry (for the filename)
        email (str | None): Unpaywall contact email; the tier is skipped if None
        allow_html (bool): whether the HTML fallback is permitted

    Outputs:
        result (dict | None): {format, source, file} when an artifact was
        written, else None.
    --------------------------------------------------------------------------
    """
    if not email:
        return None
    body = _http_json(UNPAYWALL_URL.format(doi=_clean_doi(doi)), params={"email": email})
    if not body:
        return None
    loc = body.get("best_oa_location") or {}
    pdf_url = (loc.get("url_for_pdf") or "").strip()
    if pdf_url:
        pdf_dest = os.path.join(out_dir, target_filename(entry, "pdf"))
        if _fetch_pdf(pdf_url, pdf_dest):
            return {"format": "pdf", "source": "unpaywall", "file": os.path.basename(pdf_dest)}
    if allow_html:
        page_url = (loc.get("url_for_landing_page") or loc.get("url") or "").strip()
        if page_url:
            html_dest = os.path.join(out_dir, target_filename(entry, "html"))
            if _fetch_html(page_url, html_dest):
                return {"format": "html", "source": "unpaywall", "file": os.path.basename(html_dest)}
    return None


def try_arxiv(doi: str, out_dir: str, entry: dict[str, str],
              ext_ids: dict[str, Any], allow_html: bool) -> dict[str, Any] | None:
    """
    --------------------------------------------------------------------------
    Purpose:
        When the paper carries an arXiv id (from S2 externalIds), fetch the
        arXiv PDF first, then the arXiv native HTML, then the ar5iv HTML
        rendering. All open-access.

    Inputs:
        doi (str): the paper DOI (unused beyond logging context)
        out_dir (str): the refs/ directory
        entry (dict): reference entry (for the filename)
        ext_ids (dict): S2 externalIds map; the tier is skipped without 'ArXiv'
        allow_html (bool): whether the HTML renderings are permitted

    Outputs:
        result (dict | None): {format, source, file} on success, else None.
    --------------------------------------------------------------------------
    """
    arxiv_id = str(ext_ids.get("ArXiv") or "").strip()
    if not arxiv_id:
        return None
    pdf_dest = os.path.join(out_dir, target_filename(entry, "pdf"))
    if _fetch_pdf(ARXIV_PDF_URL.format(arxiv_id=arxiv_id), pdf_dest):
        return {"format": "pdf", "source": "arxiv", "file": os.path.basename(pdf_dest)}
    if allow_html:
        html_dest = os.path.join(out_dir, target_filename(entry, "html"))
        for url in (ARXIV_HTML_URL.format(arxiv_id=arxiv_id),
                    AR5IV_HTML_URL.format(arxiv_id=arxiv_id)):
            if _fetch_html(url, html_dest):
                return {"format": "html", "source": "arxiv", "file": os.path.basename(html_dest)}
    return None


def try_pmc(doi: str, out_dir: str, entry: dict[str, str],
            ext_ids: dict[str, Any], allow_html: bool) -> dict[str, Any] | None:
    """
    --------------------------------------------------------------------------
    Purpose:
        When the paper carries a PubMed Central id (from S2 externalIds), fetch
        the PMC open-access article HTML page (content-validated).

    Inputs:
        doi (str): the paper DOI (unused beyond logging context)
        out_dir (str): the refs/ directory
        entry (dict): reference entry (for the filename)
        ext_ids (dict): S2 externalIds map; skipped without 'PubMedCentral'
        allow_html (bool): whether the HTML page is permitted

    Outputs:
        result (dict | None): {format, source, file} on success, else None.
    --------------------------------------------------------------------------
    """
    if not allow_html:
        return None
    pmcid = str(ext_ids.get("PubMedCentral") or "").strip()
    if not pmcid:
        return None
    if not pmcid.upper().startswith("PMC"):
        pmcid = f"PMC{pmcid}"
    html_dest = os.path.join(out_dir, target_filename(entry, "html"))
    if _fetch_html(PMC_HTML_URL.format(pmcid=pmcid), html_dest):
        return {"format": "html", "source": "pmc", "file": os.path.basename(html_dest)}
    return None


def try_landing_html(doi: str, out_dir: str, entry: dict[str, str],
                     allow_html: bool) -> dict[str, Any] | None:
    """
    --------------------------------------------------------------------------
    Purpose:
        Last-resort content-validated fetch of the DOI landing page as HTML.
        Only stored if it passes the _write_validated_html article check, so a
        publisher paywall stub is never kept.

    Inputs:
        doi (str): the paper DOI
        out_dir (str): the refs/ directory
        entry (dict): reference entry (for the filename)
        allow_html (bool): whether the landing scrape is permitted

    Outputs:
        result (dict | None): {format, source, file} on success, else None.
    --------------------------------------------------------------------------
    """
    if not allow_html:
        return None
    html_dest = os.path.join(out_dir, target_filename(entry, "html"))
    if _fetch_html(DOI_RESOLVER_URL.format(doi=_clean_doi(doi)), html_dest):
        return {"format": "html", "source": "landing", "file": os.path.basename(html_dest)}
    return None


def _result(base: dict[str, Any], out_dir: str, file: str, fmt: str,
            source: str, tier: int) -> dict[str, Any]:
    """Assemble a success result dict, attaching the written file's byte size."""
    path = os.path.join(out_dir, file)
    result = {**base, "file": file, "format": fmt, "source": source,
              "tier": tier, "status": source}
    if os.path.exists(path):
        result["bytes"] = os.path.getsize(path)
    return result


def download_one(entry: dict[str, str], out_dir: str,
                 api_key: str | None, insttoken: str | None, *,
                 email: str | None = None, allow_html: bool = True) -> dict[str, Any]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Retrieve a single reference's full text in any usable format into
        out_dir, presence-gated: if refs/<key>.{pdf,html,md} already exists it is
        skipped (no network call). Otherwise the tiers run in order and the first
        validated artifact wins: Elsevier PDF -> Semantic Scholar PDF ->
        Unpaywall (PDF then HTML) -> arXiv (PDF then HTML) -> PMC HTML ->
        validated landing HTML.

    Inputs:
        entry (dict): {citekey, doi, author, year, title}
        out_dir (str): the refs/ directory
        api_key (str | None): Scopus key for Elsevier
        insttoken (str | None): institutional token for off-campus Elsevier
        email (str | None): Unpaywall contact email (its tier is skipped if None)
        allow_html (bool): permit the HTML/landing tiers (default True)

    Outputs:
        result (dict): {citekey, doi, file, format, source, tier, status} where
        status is one of 'present', 'elsevier', 'semantic_scholar', 'unpaywall',
        'arxiv', 'pmc', 'landing', 'failed', 'no-doi'. 'format' is 'pdf'/'html'
        (or 'md' for a pre-existing file), and 'tier' is the source tier number.
    --------------------------------------------------------------------------
    """
    doi = _clean_doi(entry.get("doi", ""))
    base = {"citekey": entry.get("citekey", ""), "doi": doi}

    if not doi:
        return {**base, "file": target_filename(entry, "pdf"), "format": None,
                "source": None, "tier": None, "status": "no-doi"}

    # Tier 0 - presence check across all stored formats.
    for ext in ("pdf", "html", "md"):
        existing = os.path.join(out_dir, target_filename(entry, ext))
        if os.path.exists(existing):
            logger.info("[FULLTEXT] present, skip: %s", os.path.basename(existing))
            return {**base, "file": os.path.basename(existing), "format": ext,
                    "source": None, "tier": 0, "status": "present",
                    "bytes": os.path.getsize(existing)}

    pdf_dest = os.path.join(out_dir, target_filename(entry, "pdf"))

    # Tier 1 - Elsevier Full-Text (PDF).
    if try_elsevier(doi, pdf_dest, api_key, insttoken):
        logger.info("[FULLTEXT] Elsevier PDF OK: %s", os.path.basename(pdf_dest))
        return _result(base, out_dir, os.path.basename(pdf_dest), "pdf", "elsevier", 1)
    # Tier 2 - Semantic Scholar open-access PDF.
    if try_semantic_scholar(doi, pdf_dest):
        logger.info("[FULLTEXT] Semantic Scholar PDF OK: %s", os.path.basename(pdf_dest))
        return _result(base, out_dir, os.path.basename(pdf_dest), "pdf", "semantic_scholar", 2)
    # Tier 3 - Unpaywall (PDF then landing HTML).
    res = try_unpaywall(doi, out_dir, entry, email, allow_html)
    if res:
        logger.info("[FULLTEXT] Unpaywall %s OK: %s", res["format"], res["file"])
        return _result(base, out_dir, res["file"], res["format"], "unpaywall", 3)

    # arXiv / PMC tiers need the S2 externalIds map.
    ext_ids: dict[str, Any] = {}
    if s2 is not None:
        try:
            ext_ids = s2.external_ids_for_doi(doi) or {}
        except Exception as exc:  # pragma: no cover - S2 layer is best-effort
            logger.warning("[FULLTEXT] externalIds lookup failed for %s: %s", doi, exc)
            ext_ids = {}

    # Tier 4 - arXiv (PDF then native/ar5iv HTML).
    res = try_arxiv(doi, out_dir, entry, ext_ids, allow_html)
    if res:
        logger.info("[FULLTEXT] arXiv %s OK: %s", res["format"], res["file"])
        return _result(base, out_dir, res["file"], res["format"], "arxiv", 4)
    # Tier 5 - PubMed Central article HTML.
    res = try_pmc(doi, out_dir, entry, ext_ids, allow_html)
    if res:
        logger.info("[FULLTEXT] PMC HTML OK: %s", res["file"])
        return _result(base, out_dir, res["file"], res["format"], "pmc", 5)
    # Tier 6 - validated DOI landing-page HTML (last resort).
    res = try_landing_html(doi, out_dir, entry, allow_html)
    if res:
        logger.info("[FULLTEXT] landing HTML OK: %s", res["file"])
        return _result(base, out_dir, res["file"], res["format"], "landing", 6)

    logger.info("[FULLTEXT] failed (no open-access full text found): %s", doi)
    return {**base, "file": target_filename(entry, "pdf"), "format": None,
            "source": None, "tier": None, "status": "failed"}


# --------------------------------------------------------------------------- #
# Manifest / report
# --------------------------------------------------------------------------- #
def write_manifest(out_dir: str, results: list[dict[str, Any]]) -> None:
    """Write refs/_manifest.json mapping each reference to its file and source."""
    manifest = {(r.get("citekey") or r.get("doi") or f"ref{i}"): r
                for i, r in enumerate(results)}
    path = os.path.join(out_dir, "_manifest.json")
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, ensure_ascii=False, indent=2)


def write_failed(out_dir: str, results: list[dict[str, Any]]) -> None:
    """Write refs/_failed.md with DOI links + manual-save instructions for the
    references no automated tier could retrieve in any format."""
    failed = [r for r in results if r.get("status") == "failed"]
    path = os.path.join(out_dir, "_failed.md")
    lines = ["# References to retrieve manually (UQAC network)", ""]
    if not failed:
        lines.append("All references with a DOI were retrieved (PDF, HTML, or Markdown).")
    else:
        lines.append(
            "Open each link on the UQAC network or VPN, then save the full paper into this "
            "`refs/` folder so the audit/mining steps can read it. Save as "
            "`<citekey>.pdf` (browser print-to-PDF), `<citekey>.html` (Save Page As), or "
            "`<citekey>.md`. The extension may be any of pdf/html/md; the filename must be "
            "the cite key."
        )
        lines.append("")
        for r in failed:
            key = r.get("citekey") or r.get("doi")
            lines.append(f"- [{key}](https://doi.org/{r['doi']})")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")


def _summarize(results: list[dict[str, Any]], out_dir: str) -> None:
    counts: dict[str, int] = {}
    for r in results:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    print(json.dumps({
        "mode": "download_pdf",
        "out_dir": out_dir,
        "total": len(results),
        "counts": counts,
        "results": results,
    }, ensure_ascii=False, indent=2))


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _run_doi(args: argparse.Namespace) -> None:
    out_dir = resolve_out_dir(args.out_dir, args.latex)
    api_key = _scopus_key_optional()
    email = args.email or _unpaywall_email_optional()
    allow_html = not args.no_html
    entry = {
        "citekey": args.citekey or "",
        "doi": args.query,
        "author": args.author or "",
        "year": args.year or "",
        "title": args.title or "",
    }
    result = download_one(entry, out_dir, api_key, args.insttoken,
                          email=email, allow_html=allow_html)
    write_manifest(out_dir, [result])
    write_failed(out_dir, [result])
    _summarize([result], out_dir)


def _run_bib(args: argparse.Namespace) -> None:
    bib_path = args.query
    if not bib_path and args.latex:
        bib_path = find_bib_from_latex(args.latex)
    if not bib_path or not os.path.exists(bib_path):
        print(f"ERROR: no .bib file found (got: {bib_path!r}). "
              f"Pass the .bib path or a --latex file that references one.", file=sys.stderr)
        sys.exit(1)

    out_dir = resolve_out_dir(args.out_dir, args.latex)
    api_key = _scopus_key_optional()
    email = args.email or _unpaywall_email_optional()
    allow_html = not args.no_html
    entries = extract_bib_entries(bib_path)
    if not entries:
        print(json.dumps({"mode": "download_pdf", "out_dir": out_dir,
                          "total": 0, "counts": {}, "results": [],
                          "note": "no entries with a DOI found"}, indent=2))
        return

    results = [download_one(e, out_dir, api_key, args.insttoken,
                            email=email, allow_html=allow_html) for e in entries]
    write_manifest(out_dir, results)
    write_failed(out_dir, results)
    _summarize(results, out_dir)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(
        description="Retrieve full-text (PDF/HTML/Markdown) for validated references")
    sub = parser.add_subparsers(dest="mode", required=True)

    p_doi = sub.add_parser("doi", help="retrieve the full text for a single DOI")
    p_doi.add_argument("query", help="the DOI (with or without https://doi.org/ prefix)")
    p_doi.add_argument("--citekey", default=None, help="BibTeX cite key, used as the filename")
    p_doi.add_argument("--author", default=None, help="first-author surname (fallback filename)")
    p_doi.add_argument("--year", default=None, help="publication year (fallback filename)")
    p_doi.add_argument("--title", default=None, help="title fragment (fallback filename)")
    p_doi.add_argument("--out-dir", default=None, help="explicit refs/ directory")
    p_doi.add_argument("--latex", default=None, help="main .tex file; refs/ is placed next to it")
    p_doi.add_argument("--insttoken", default=None, help="Elsevier institutional token (off-campus)")
    p_doi.add_argument("--email", default=None,
                       help="Unpaywall contact email (else the UNPAYWALL_EMAIL env var)")
    p_doi.add_argument("--no-html", action="store_true",
                       help="restrict retrieval to PDF only (skip the HTML/landing tiers)")
    p_doi.set_defaults(func=_run_doi)

    p_bib = sub.add_parser("bib", help="retrieve full text for every DOI in a .bib file")
    p_bib.add_argument("query", nargs="?", default=None,
                       help="path to the .bib file (omit to auto-discover from --latex)")
    p_bib.add_argument("--out-dir", default=None, help="explicit refs/ directory")
    p_bib.add_argument("--latex", default=None,
                       help="main .tex file; refs/ is placed next to it and the .bib is auto-found")
    p_bib.add_argument("--insttoken", default=None, help="Elsevier institutional token (off-campus)")
    p_bib.add_argument("--email", default=None,
                       help="Unpaywall contact email (else the UNPAYWALL_EMAIL env var)")
    p_bib.add_argument("--no-html", action="store_true",
                       help="restrict retrieval to PDF only (skip the HTML/landing tiers)")
    p_bib.set_defaults(func=_run_bib)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
