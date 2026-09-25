"""
publications.py - Cached, rate-limited access to one author's Scopus
publications.

ThesisTracker never calls Elsevier. The key, the throttling, and the
approved-publisher policy stay here; a caller sees plain JSON with a per-entry
approved_publisher flag.

The cache is on disk and keyed by a hash, so a cache directory listing does not
reveal which people were looked up.
"""

import hashlib
import json
import logging
import os
import sys
import time
from typing import Any, Callable

from .config import Settings

logger = logging.getLogger(__name__)

# scopus_api.py lives in a DIFFERENT skill (scopus, not form-service), so
# skill_bridge's sys.path bootstrap does not cover it. Mounted into the image
# at /opt/scopus/scripts; SCOPUS_SCRIPTS_DIR overrides it for a local run
# straight from a checkout.
_DEFAULT_SCOPUS_SCRIPTS = os.environ.get(
    "SCOPUS_SCRIPTS_DIR",
    os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))))),
        ".claude", "skills", "scopus", "scripts"))
if _DEFAULT_SCOPUS_SCRIPTS not in sys.path:
    sys.path.insert(0, _DEFAULT_SCOPUS_SCRIPTS)

import scopus_api  # noqa: E402


class TokenBucket:
    """
    A minimal token bucket. Sized for the Elsevier quota rather than for load:
    the point is to never hammer Scopus from a report that iterates a roster.
    """

    def __init__(self, capacity: int, refill_per_minute: int,
                 now: Callable[[], float] = time.monotonic) -> None:
        self.capacity = capacity
        self.refill_per_minute = refill_per_minute
        self._now = now
        self._tokens = float(capacity)
        self._last = now()

    def take(self) -> bool:
        """
        ----------------------------------------------------------------------
        Purpose:
            Consume one token, refilling first for the elapsed time.

        Inputs:
            none

        Outputs:
            allowed (bool): True when a token was available
        ----------------------------------------------------------------------
        """
        current = self._now()
        elapsed = max(0.0, current - self._last)
        self._last = current
        self._tokens = min(float(self.capacity),
                           self._tokens + elapsed * (self.refill_per_minute / 60.0))
        if self._tokens < 1.0:
            return False
        self._tokens -= 1.0
        return True


def cache_key(author: str, count: int) -> str:
    """
    --------------------------------------------------------------------------
    Purpose:
        Build a stable cache key for one query. The author name is trimmed and
        lowercased so trivial spelling variants share an entry, and the digest
        keeps the name out of the file system.

    Inputs:
        author (str): the queried author name
        count (int): how many documents were requested

    Outputs:
        key (str): SHA-256 hexadecimal digest
    --------------------------------------------------------------------------
    """
    normalized = f"{' '.join(author.lower().split())}|{count}"
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _cache_path(key: str, settings: Settings) -> str:
    return os.path.join(settings.publications_cache_dir, f"{key}.json")


def read_cache(key: str, settings: Settings, now: float | None = None) -> dict[str, Any] | None:
    """
    --------------------------------------------------------------------------
    Purpose:
        Return a cached payload when one exists and is younger than the TTL.

    Inputs:
        key (str): cache key
        settings (Settings): service configuration
        now (float | None): epoch seconds, injected by the tests

    Outputs:
        payload (dict | None): the cached document, or None on miss or expiry
    --------------------------------------------------------------------------
    """
    path = _cache_path(key, settings)
    if not os.path.isfile(path):
        return None
    age = (time.time() if now is None else now) - os.path.getmtime(path)
    if age > settings.publications_ttl_s:
        logger.info("[FORM-SERVICE] publications cache entry expired")
        return None
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError):
        return None


def write_cache(key: str, payload: dict[str, Any], settings: Settings) -> None:
    """
    --------------------------------------------------------------------------
    Purpose:
        Persist a payload for later reuse.

    Inputs:
        key (str): cache key
        payload (dict): the document to store
        settings (Settings): service configuration

    Outputs:
        none
    --------------------------------------------------------------------------
    """
    os.makedirs(settings.publications_cache_dir, exist_ok=True)
    with open(_cache_path(key, settings), "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False)


class RateLimited(RuntimeError):
    """Raised when the Scopus token bucket is empty."""


class ScopusUnavailable(RuntimeError):
    """Raised when Scopus cannot be reached or no key is configured."""


def fetch_publications(author: str, count: int, refresh: bool, settings: Settings,
                       bucket: TokenBucket,
                       fetcher: Callable[..., dict[str, Any]] | None = None
                       ) -> tuple[dict[str, Any], bool]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Return one author's publications, from cache when possible. A cache hit
        costs no Scopus quota, so a cohort report over a roster of already seen
        students makes no network call at all.

    Inputs:
        author (str): the author name
        count (int): how many documents
        refresh (bool): bypass the cache
        settings (Settings): service configuration
        bucket (TokenBucket): the shared rate limiter
        fetcher (callable | None): injected for tests; defaults to
            scopus_api.author_documents

    Outputs:
        result (tuple): (payload, cached)

    Raises:
        RateLimited when the bucket is empty on a cache miss.
        ScopusUnavailable when no key is configured or Scopus is unreachable.
        ValueError when the author cannot be resolved.
    --------------------------------------------------------------------------
    """
    key = cache_key(author, count)
    if not refresh:
        cached = read_cache(key, settings)
        if cached is not None:
            return cached, True

    if not bucket.take():
        raise RateLimited(
            "the Scopus rate limit for this service is exhausted, retry shortly")

    call = fetcher or scopus_api.author_documents
    try:
        payload = call(author, count=count)
    except ValueError:
        raise
    except Exception as exc:  # network, key, quota: one actionable class
        # The message is safe to surface: _get_api_key never echoes the key.
        raise ScopusUnavailable(str(exc)) from exc

    write_cache(key, payload, settings)
    return payload, False
