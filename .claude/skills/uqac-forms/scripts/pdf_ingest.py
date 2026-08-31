"""
pdf_ingest.py - the validated PDF-ingest contract for the uqac-forms skill.

Stage: retrieval. Given an https URL, it produces a file on disk that is proven
to be a PDF, or nothing at all. It holds no registry, no cache index and no
knowledge of what a UQAC form is: the caller supplies the URL and the
destination path. ResearchTools is stateless PDF mechanics, and ThesisTracker
owns the catalogue (see NEW_ARCHITECTURE.md section 1).

The contract this module implements is published, not private, because TT-8
implements the same contract in Node (api/_lib/drift.js). Both sides must agree:

    scheme      https only, re-checked on every redirect hop
    redirects   at most MAX_REDIRECTS, followed manually
    size        MAX_PDF_BYTES, enforced DURING the stream
    magic       the first four bytes are %PDF
    timeout     REQUEST_TIMEOUT_S on every request
    write       atomic, via a *.part file and os.replace

Three of those rules exist because of a specific failure, and each has a test in
Test/test_pdf_ingest.py:

  - The scheme is re-checked per hop because checking only the URL the caller
    typed is not a scheme check: a source answering 302 to http:// defeats it.
  - The size cap is enforced mid-stream because a cap applied once the body is
    already in memory cannot prevent the allocation it exists to prevent.
  - The magic bytes are checked because UQAC answers HTTP 200 with an HTML
    access page when a form moves, so a status code never proves a PDF.

See .claude/rules/security.md for the input-validation rules this script follows.
"""

import hashlib
import logging
import os
from urllib.parse import urljoin, urlparse

import requests

logger = logging.getLogger(__name__)

# Kept identical to TT-8's api/_lib/drift.js. Changing one without the other
# splits the contract, and the split would only show up on a real UQAC form.
MAX_PDF_BYTES: int = 25 * 1024 * 1024
MAX_REDIRECTS: int = 5
REQUEST_TIMEOUT_S: float = 30.0
CHUNK_BYTES: int = 64 * 1024

PDF_MAGIC: bytes = b"%PDF"
_REDIRECT_STATUSES: frozenset = frozenset({301, 302, 303, 307, 308})


def sha256_bytes(data: bytes) -> str:
    """
    --------------------------------------------------------------------------
    Purpose:
        Hash a bytes object with SHA-256, for callers that already hold the
        body in memory.

    Inputs:
        data (bytes): the content to hash

    Outputs:
        digest (str): lowercase hexadecimal digest, 64 characters
    --------------------------------------------------------------------------
    """
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: str) -> str:
    """
    --------------------------------------------------------------------------
    Purpose:
        Hash a file with SHA-256, streamed, so a large PDF is never fully
        resident in memory.

    Inputs:
        path (str): file to hash

    Outputs:
        digest (str): lowercase hexadecimal digest, 64 characters
    --------------------------------------------------------------------------
    """
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK_BYTES), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_validated(response: object, dest: str, max_bytes: int) -> bool:
    """
    --------------------------------------------------------------------------
    Purpose:
        Stream a response body to disk, refusing anything that is not a PDF and
        anything over the size cap. The write is atomic: a temporary *.part
        file is renamed into place only once the whole body has been accepted,
        so a caller never observes a half-written form.

    Inputs:
        response (object): a streamed response exposing iter_content and close
        dest (str): final path to write
        max_bytes (int): hard ceiling on the body size

    Outputs:
        accepted (bool): True when dest now holds a validated PDF
    --------------------------------------------------------------------------
    """
    tmp = f"{dest}.part"
    parent = os.path.dirname(dest)
    if parent:
        os.makedirs(parent, exist_ok=True)

    size = 0
    checked_magic = False
    try:
        with open(tmp, "wb") as handle:
            for chunk in response.iter_content(CHUNK_BYTES):
                if not chunk:
                    continue
                # The cap is checked before the write, not after the download,
                # so an endless source costs one chunk rather than all of them.
                size += len(chunk)
                if size > max_bytes:
                    logger.warning(
                        "[UQAC-FORMS] exceeds the %d-byte cap - discarded", max_bytes)
                    return False
                if not checked_magic:
                    # The first chunk is at least CHUNK_BYTES unless the body is
                    # shorter, so four bytes are available whenever they exist
                    # at all. A body too short to carry them is not a PDF.
                    if not chunk.startswith(PDF_MAGIC):
                        logger.warning(
                            "[UQAC-FORMS] not a PDF: the body does not begin with %%PDF")
                        return False
                    checked_magic = True
                handle.write(chunk)
        if not checked_magic:
            logger.warning("[UQAC-FORMS] refusing an empty body")
            return False
        os.replace(tmp, dest)
        return True
    finally:
        # Reached on refusal and on exception alike. A leftover *.part that
        # looks like a cached form is worse than no file.
        if os.path.exists(tmp):
            os.remove(tmp)


def fetch_pdf(url: str, dest: str, *,
              max_bytes: int = MAX_PDF_BYTES,
              max_redirects: int = MAX_REDIRECTS,
              timeout_s: float = REQUEST_TIMEOUT_S) -> str | None:
    """
    --------------------------------------------------------------------------
    Purpose:
        Download one PDF over https and write it to dest, or refuse. Redirects
        are followed by hand rather than by requests, because requests cannot
        re-check the scheme between hops and an https source that redirects to
        http would otherwise be fetched in the clear.

    Inputs:
        url (str): https source URL
        dest (str): path to write the validated PDF to
        max_bytes (int): size ceiling, default MAX_PDF_BYTES
        max_redirects (int): redirect ceiling, default MAX_REDIRECTS
        timeout_s (float): per-request timeout, default REQUEST_TIMEOUT_S

    Outputs:
        path (str | None): dest on success, None on any refusal or failure.
            Every refusal is logged with its reason; none raises.
    --------------------------------------------------------------------------
    """
    current = url
    for _ in range(max_redirects + 1):
        if urlparse(current).scheme != "https":
            logger.warning("[UQAC-FORMS] refusing a non-https URL: %s", current)
            return None

        response = None
        try:
            response = requests.get(
                current, stream=True, timeout=timeout_s, allow_redirects=False)

            if response.status_code in _REDIRECT_STATUSES:
                location = response.headers.get("Location")
                if not location:
                    logger.warning(
                        "[UQAC-FORMS] redirect with no Location from %s", current)
                    return None
                # Relative Locations are legal, so resolve against the hop that
                # issued them before the next scheme check sees the result.
                current = urljoin(current, location)
                continue

            if response.status_code != 200:
                logger.warning("[UQAC-FORMS] %s answered %d",
                               current, response.status_code)
                return None

            if _write_validated(response, dest, max_bytes):
                return dest
            return None
        except requests.RequestException as err:
            logger.warning("[UQAC-FORMS] request failed for %s: %s", current, err)
            return None
        finally:
            if response is not None:
                response.close()

    logger.warning("[UQAC-FORMS] more than %d redirects from %s", max_redirects, url)
    return None
