"""
download_pdf.py — Full-text PDF retrieval for the Claude Code /scopus skill.

Stage: post-validation. Once a reference is fully known (validated DOI +
metadata), this script fetches the full PDF into a `refs/` directory placed
directly under the LaTeX project, so the auditor/researcher agents can keep the
papers next to the manuscript that cites them.

Source chain (stop at the first byte-validated PDF):
  1. Elsevier Full-Text API  — primary, uses SCOPUS_API_KEY (+ optional insttoken)
  2. Semantic Scholar openAccessPdf — fallback, only when Scopus cannot deliver

Every download is validated by the PDF magic bytes (%PDF), an HTTPS-only scheme
check, a redirect-hop limit, and a size cap, so publisher "access denied" HTML
pages are never stored as `.pdf`.

Usage:
  python download_pdf.py doi "<DOI>" --out-dir "<.../refs>" \\
      [--citekey KEY] [--author A] [--year Y] [--title T] [--insttoken TOK]
  python download_pdf.py bib "<references.bib>" --latex "<.../src/main.tex>"
  python download_pdf.py bib "<references.bib>" --out-dir "<.../src/refs>"
  python download_pdf.py bib --latex "<.../src/main.tex>"   # auto-discovers the .bib

Requires: SCOPUS_API_KEY (Windows user env var) for the Elsevier source; the
Semantic Scholar fallback works without it. No path or credential is hardcoded:
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
PDF_MAGIC = b"%PDF"
MAX_PDF_BYTES = 100 * 1024 * 1024  # 100 MB cap, streamed; aborts past this
MAX_REDIRECTS = 5
CHUNK_BYTES = 8192
REQUEST_TIMEOUT_S = 60


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


def target_filename(entry: dict[str, str]) -> str:
    """
    --------------------------------------------------------------------------
    Purpose:
        Build the deterministic PDF filename for a reference. The citekey is
        preferred so the presence check is stable across runs; author_year_title
        is the fallback when no citekey is known (e.g. a bare DOI download).

    Inputs:
        entry (dict): may carry 'citekey', 'author', 'year', 'title'

    Outputs:
        name (str): a safe '<...>.pdf' filename with no path separators.
    --------------------------------------------------------------------------
    """
    citekey = (entry.get("citekey") or "").strip()
    if citekey:
        return f"{_slugify(citekey)}.pdf"
    author = _slugify(entry.get("author") or "unknown")
    year = _slugify(entry.get("year") or "0000")
    title = _slugify(entry.get("title") or "notitle", max_len=40)
    return f"{author}_{year}_{title}.pdf"


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


def download_one(entry: dict[str, str], out_dir: str,
                 api_key: str | None, insttoken: str | None) -> dict[str, Any]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Download a single reference's PDF into out_dir, presence-gated: if the
        target file already exists it is skipped (no network call). Otherwise
        the Elsevier source is tried first, then Semantic Scholar.

    Inputs:
        entry (dict): {citekey, doi, author, year, title}
        out_dir (str): the refs/ directory
        api_key (str | None): Scopus key for Elsevier
        insttoken (str | None): institutional token for off-campus Elsevier

    Outputs:
        result (dict): {citekey, doi, file, source, status} where status is one
        of 'present', 'elsevier', 'semantic_scholar', 'failed', 'no-doi'.
    --------------------------------------------------------------------------
    """
    doi = _clean_doi(entry.get("doi", ""))
    filename = target_filename(entry)
    dest = os.path.join(out_dir, filename)
    base = {"citekey": entry.get("citekey", ""), "doi": doi, "file": filename}

    if not doi:
        return {**base, "source": None, "status": "no-doi"}
    if os.path.exists(dest):
        logger.info("[PDF] present, skip: %s", filename)
        return {**base, "source": None, "status": "present",
                "bytes": os.path.getsize(dest)}

    if try_elsevier(doi, dest, api_key, insttoken):
        logger.info("[PDF] Elsevier OK: %s", filename)
        return {**base, "source": "elsevier", "status": "elsevier",
                "bytes": os.path.getsize(dest)}
    if try_semantic_scholar(doi, dest):
        logger.info("[PDF] Semantic Scholar OA OK: %s", filename)
        return {**base, "source": "semantic_scholar", "status": "semantic_scholar",
                "bytes": os.path.getsize(dest)}

    logger.info("[PDF] failed (institutional access required): %s", doi)
    return {**base, "source": None, "status": "failed"}


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
    """Write refs/_failed.md with DOI links for manual UQAC-network retrieval."""
    failed = [r for r in results if r.get("status") == "failed"]
    path = os.path.join(out_dir, "_failed.md")
    lines = ["# References to download manually (UQAC network)", ""]
    if not failed:
        lines.append("All references with a DOI were retrieved.")
    else:
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
    entry = {
        "citekey": args.citekey or "",
        "doi": args.query,
        "author": args.author or "",
        "year": args.year or "",
        "title": args.title or "",
    }
    result = download_one(entry, out_dir, api_key, args.insttoken)
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
    entries = extract_bib_entries(bib_path)
    if not entries:
        print(json.dumps({"mode": "download_pdf", "out_dir": out_dir,
                          "total": 0, "counts": {}, "results": [],
                          "note": "no entries with a DOI found"}, indent=2))
        return

    results = [download_one(e, out_dir, api_key, args.insttoken) for e in entries]
    write_manifest(out_dir, results)
    write_failed(out_dir, results)
    _summarize(results, out_dir)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(description="Download full-text PDFs for validated references")
    sub = parser.add_subparsers(dest="mode", required=True)

    p_doi = sub.add_parser("doi", help="download the PDF for a single DOI")
    p_doi.add_argument("query", help="the DOI (with or without https://doi.org/ prefix)")
    p_doi.add_argument("--citekey", default=None, help="BibTeX cite key, used as the PDF filename")
    p_doi.add_argument("--author", default=None, help="first-author surname (fallback filename)")
    p_doi.add_argument("--year", default=None, help="publication year (fallback filename)")
    p_doi.add_argument("--title", default=None, help="title fragment (fallback filename)")
    p_doi.add_argument("--out-dir", default=None, help="explicit refs/ directory")
    p_doi.add_argument("--latex", default=None, help="main .tex file; refs/ is placed next to it")
    p_doi.add_argument("--insttoken", default=None, help="Elsevier institutional token (off-campus)")
    p_doi.set_defaults(func=_run_doi)

    p_bib = sub.add_parser("bib", help="download PDFs for every DOI in a .bib file")
    p_bib.add_argument("query", nargs="?", default=None,
                       help="path to the .bib file (omit to auto-discover from --latex)")
    p_bib.add_argument("--out-dir", default=None, help="explicit refs/ directory")
    p_bib.add_argument("--latex", default=None,
                       help="main .tex file; refs/ is placed next to it and the .bib is auto-found")
    p_bib.add_argument("--insttoken", default=None, help="Elsevier institutional token (off-campus)")
    p_bib.set_defaults(func=_run_bib)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
